"""Fetch small site icons without forwarding browser cookies or API credentials."""
import hashlib
import json
import os
import threading
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

MAX_BYTES = 256 * 1024


def web_url(url):
    p = urlsplit(url)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
        raise ValueError('invalid icon URL')
    return url


class Redirects(HTTPRedirectHandler):
    max_redirections = 3

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        web_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def request_bytes(url, limit=MAX_BYTES, prefix=False):
    request = Request(web_url(url), headers={'User-Agent': 'PersonalNav/1.0', 'Accept': 'image/*,text/html;q=0.5', 'Accept-Encoding': 'identity'})
    # Ignore host proxy variables and never pass through a user's authorization.
    with build_opener(ProxyHandler({}), Redirects()).open(request, timeout=2.5) as response:
        if not prefix and int(response.headers.get('Content-Length', '0')) > limit:
            raise ValueError('icon too large')
        data = response.read(limit if prefix else limit + 1)
        if len(data) > limit:
            raise ValueError('icon too large')
        return data, response.geturl()


def image_type(data):
    # Raster formats only: remote SVG/HTML is never served on the app's origin.
    if data.startswith(b'\x00\x00\x01\x00') and len(data) >= 22:
        return 'image/x-icon'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if data.startswith(b'GIF8'):
        return 'image/gif'
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        return 'image/webp'
    return None


class IconLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'link' and 'icon' in attrs.get('rel', '').lower().split() and attrs.get('href'):
            self.urls.append(attrs['href'])


class FaviconCache:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.locks = [threading.Lock() for _ in range(64)]

    def get(self, url):
        p = urlsplit(web_url(url))
        origin = f'{p.scheme}://{p.netloc}/'
        key = hashlib.sha256(origin.encode()).hexdigest()
        metadata = self.directory / (key + '.json')
        icon = self.directory / (key + '.image')
        with self.locks[int(key[:4], 16) % len(self.locks)]:
            try:
                saved = json.loads(metadata.read_text())
                if saved['expires'] > time.time():
                    return (icon.read_bytes(), saved['type']) if saved['type'] else None
            except (OSError, ValueError, KeyError):
                pass
            result = self.fetch(origin)
            if result:
                temporary = icon.with_suffix('.tmp')
                temporary.write_bytes(result[0]); temporary.chmod(0o600)
                os.replace(temporary, icon)
            metadata.write_text(json.dumps({'expires': time.time() + (7 * 86400 if result else 3600), 'type': result[1] if result else None}))
            metadata.chmod(0o600)
            return result

    @staticmethod
    def fetch(origin):
        def image(url):
            try:
                data, _ = request_bytes(url)
                kind = image_type(data)
                return (data, kind) if kind else None
            except (OSError, ValueError):
                return None
        result = image(urljoin(origin, 'favicon.ico'))
        if result:
            return result
        try:
            page, final_url = request_bytes(origin, 64 * 1024, prefix=True)
            parser = IconLinks(); parser.feed(page.decode('utf-8', errors='replace'))
            for href in parser.urls[:2]:
                result = image(urljoin(final_url, href))
                if result:
                    return result
        except (OSError, ValueError):
            pass
        return None
