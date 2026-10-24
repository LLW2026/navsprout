#!/usr/bin/env python3
"""Maintain a small, attributed landscape collection from Lorem Picsum.

Uses the documented public endpoints, not the Unsplash API. No credentials.
The application itself serves these files locally and makes no remote requests.
"""
import concurrent.futures
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1] / 'app/static/backgrounds'
PHOTOS = [('10', '林间湖畔'), ('15', '山谷飞瀑'), ('28', '森林小径'), ('29', '山野远眺'),
          ('1015', '河谷清晨'), ('1016', '云上群山'), ('1018', '山间薄雾'), ('1039', '溪谷流水')]


def safe_url(url):
    p = urlsplit(url)
    if p.scheme != 'https' or p.hostname not in {'picsum.photos', 'fastly.picsum.photos'} or p.username or p.password or p.port not in (None, 443):
        raise ValueError('图源跳转到未允许的地址')
    return url


class Redirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, code, msg, headers, safe_url(newurl))


def fetch(url, limit):
    opener = build_opener(Redirects())
    with opener.open(Request(safe_url(url), headers={'User-Agent': 'PersonalNav-Backgrounds/1.0'}), timeout=25) as r:
        content = r.read(limit + 1)
        if len(content) > limit:
            raise ValueError('图片或元数据超过大小限制')
        return content


def download(photo):
    pid, title = photo
    info = json.loads(fetch(f'https://picsum.photos/id/{pid}/info', 32768))
    source = info['url']
    if urlsplit(source).scheme != 'https' or urlsplit(source).hostname != 'unsplash.com':
        raise ValueError('图片缺少 Unsplash 来源')
    image = fetch(f'https://picsum.photos/id/{pid}/1600/1000.jpg', 4 * 1024 * 1024)
    if not image.startswith(b'\xff\xd8\xff') or not image.endswith(b'\xff\xd9'):
        raise ValueError('图源未返回完整 JPEG')
    return {'id': pid, 'title': title, 'author': info['author'], 'source': source,
            'provider': 'Lorem Picsum / Unsplash', 'license': 'https://unsplash.com/license',
            'image': f'/static/backgrounds/{pid}.jpg'}, image


def main():
    # Fetch all first; a network failure leaves the existing collection intact.
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(download, PHOTOS))
    ROOT.mkdir(parents=True, exist_ok=True)
    for item, image in results:
        with tempfile.NamedTemporaryFile(dir=ROOT, delete=False) as f:
            f.write(image)
            tmp = Path(f.name)
        tmp.chmod(0o644)
        os.replace(tmp, ROOT / (item['id'] + '.jpg'))
    manifest = {'version': 1, 'photos': [item for item, _ in results]}
    (ROOT / 'catalog.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(f'已下载 {len(results)} 张风景，共 {sum(len(img) for _, img in results) // 1024} KB；来源已记录。')


if __name__ == '__main__':
    main()
