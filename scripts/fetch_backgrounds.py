#!/usr/bin/env python3
"""Maintain a small, attributed landscape collection from Lorem Picsum.

Uses the documented public endpoints, not the Unsplash API. No credentials.
The app serves these fallback files locally; daily images are fetched separately.
"""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from app.backgrounds import MAX_IMAGE, download as fetch, jpeg_dimensions, photo_size

ROOT = PROJECT / 'app/static/backgrounds'
PHOTOS = [('28', '森林小径'), ('29', '山野远眺'), ('1015', '河谷清晨'),
          ('1016', '云上群山'), ('1018', '山间薄雾'), ('1039', '溪谷流水'),
          ('1011', '湖畔行舟'), ('51', '海天远景')]


def download(photo):
    pid, title = photo
    info = json.loads(fetch(f'https://picsum.photos/id/{pid}/info', 32768))
    source = info['url']
    if urlsplit(source).scheme != 'https' or urlsplit(source).hostname != 'unsplash.com':
        raise ValueError('图片缺少 Unsplash 来源')
    size = photo_size(info)
    if not size:
        raise ValueError('备用图片原始分辨率不足 4K')
    width, height = size
    image = fetch(f'https://picsum.photos/id/{pid}/{width}/{height}.jpg', MAX_IMAGE)
    if jpeg_dimensions(image) != size:
        raise ValueError('图片实际分辨率与图源不符')
    return {'id': pid, 'title': title, 'author': info['author'], 'source': source,
            'provider': 'Lorem Picsum / Unsplash', 'license': 'https://unsplash.com/license',
            'width': width, 'height': height, 'sha256': hashlib.sha256(image).hexdigest(),
            'image': f'/static/backgrounds/{pid}.jpg?v=2'}, image


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
