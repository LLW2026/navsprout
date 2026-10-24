"""Download one new public-library photo each day; keep an atomic local cache."""
import hashlib
import json
import os
import re
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

CHINA = timezone(timedelta(hours=8))
MAX_IMAGE = 6 * 1024 * 1024


def trusted_url(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in {'picsum.photos', 'fastly.picsum.photos'} or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError('图源地址不受支持')
    return url


class Redirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, code, msg, headers, trusted_url(newurl))


def download(url, limit):
    # This independent client never forwards browser headers or navigation credentials.
    with build_opener(Redirects()).open(Request(trusted_url(url), headers={'User-Agent': 'PersonalNav-DailyBackground/1.0'}), timeout=18) as response:
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError('图源响应过大')
        return data


def fetch_photo(period, recent):
    for attempt in range(5):
        seed = f'navsprout-{period}-{attempt}'
        info = json.loads(download(f'https://picsum.photos/seed/{seed}/info', 32768))
        pid = str(info['id'])
        source = urlsplit(info['url'])
        if not re.fullmatch(r'\d{1,6}', pid) or source.scheme != 'https' or source.hostname != 'unsplash.com' or source.username or source.password:
            raise ValueError('图源元数据不完整')
        if pid in recent:
            continue
        data = download(f'https://picsum.photos/id/{pid}/1600/1000.jpg', MAX_IMAGE)
        if not data.startswith(b'\xff\xd8\xff') or not data.endswith(b'\xff\xd9'):
            raise ValueError('图源未返回完整 JPEG')
        return {'id': f'{period}-{pid}', 'source_id': pid, 'author': str(info['author'])[:160],
                'source': info['url'], 'license': 'https://unsplash.com/license',
                'provider': 'Lorem Picsum / Unsplash', 'sha256': hashlib.sha256(data).hexdigest()}, data
    raise ValueError('图源暂未提供新的图片')


class Backgrounds:
    def __init__(self, root, fallback, refresh_time='06:00', enabled=True):
        if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', refresh_time):
            raise RuntimeError('NAV_BACKGROUND_REFRESH_TIME 请填写 00:00 至 23:59')
        self.hour, self.minute = map(int, refresh_time.split(':'))
        self.refresh_time = refresh_time
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.fallback = json.loads(Path(fallback).read_text())['photos']
        self.enabled = enabled
        self.lock = threading.RLock()
        self.state = self._read()

    def _read(self):
        try:
            state = json.loads((self.root / 'index.json').read_text())
            state['photos'] = [p for p in state['photos'] if re.fullmatch(r'\d{4}-\d\d-\d\d-\d{1,6}', p['id']) and (self.root / (p['id'] + '.jpg')).is_file()]
            return {'photos': state['photos'], 'last_attempt': float(state.get('last_attempt', 0)),
                    'last_period': str(state.get('last_period', '')), 'failed': bool(state.get('failed', False))}
        except (OSError, ValueError, KeyError, TypeError):
            return {'photos': [], 'last_attempt': 0, 'last_period': '', 'failed': False}

    def _atomic(self, target, data):
        fd, temp = tempfile.mkstemp(prefix='.background-', dir=self.root)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temp, 0o600)
            os.replace(temp, self.root / target)
        finally:
            Path(temp).unlink(missing_ok=True)

    def slot(self, at):
        local = at.astimezone(CHINA)
        boundary = local.replace(hour=self.hour, minute=self.minute, second=0, microsecond=0)
        if local < boundary:
            boundary -= timedelta(days=1)
        return boundary.date().isoformat(), boundary + timedelta(days=1)

    def refresh_if_due(self, at=None):
        at = at or datetime.now(CHINA)
        period, _ = self.slot(at)
        if not self.enabled:
            return False
        # Reads remain responsive while the network fetch runs outside the state lock.
        with self.lock:
            if self.state.get('fetching') or (self.state['last_period'] == period and self.state['photos']) or at.timestamp() - self.state['last_attempt'] < 600:
                return False
            self.state.update(last_attempt=at.timestamp(), fetching=True)
            recent = {p['source_id'] for p in self.state['photos']}
        try:
            photo, image = fetch_photo(period, recent)
            photo.update(image=f"/api/v1/backgrounds/{photo['id']}.jpg", downloaded_at=at.isoformat())
            self._atomic(photo['id'] + '.jpg', image)
            with self.lock:
                old = self.state['photos']
                photos = [photo, *old][:30]
                updated = {'photos': photos, 'last_attempt': at.timestamp(), 'last_period': period, 'failed': False}
                self._atomic('index.json', json.dumps(updated, ensure_ascii=False).encode())
                self.state = updated
                for expired in old[29:]:
                    (self.root / (expired['id'] + '.jpg')).unlink(missing_ok=True)
            return True
        except Exception:
            with self.lock:
                self.state.update(failed=True, fetching=False)
                try:
                    self._atomic('index.json', json.dumps(self.state, ensure_ascii=False).encode())
                except OSError:
                    pass
            return False

    def catalog(self, at=None):
        period, following = self.slot(at or datetime.now(CHINA))
        with self.lock:
            photos = [dict(p) for p in self.state['photos']]
            status = 'ready' if photos and self.state['last_period'] == period else ('stale' if photos else 'fallback')
            return {'photos': photos + self.fallback, 'daily_id': photos[0]['id'] if photos else '',
                    'status': status, 'refresh_time': self.refresh_time, 'timezone': 'Asia/Shanghai',
                    'next_refresh_at': following.isoformat(), 'enabled': self.enabled}

    def image_path(self, filename):
        with self.lock:
            if not re.fullmatch(r'\d{4}-\d\d-\d\d-\d{1,6}\.jpg', filename) or not any(p['id'] + '.jpg' == filename for p in self.state['photos']):
                return None
        path = self.root / filename
        return path if path.is_file() else None
