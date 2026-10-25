import io
import re
from pathlib import Path

from PIL import Image
from fastapi.testclient import TestClient

from app.favicon import FaviconCache
from app.media import MediaCache
from test_core import app, client, config, entry


def test_versioned_assets_change_with_content_and_private_api_not_cached(app, client):
    page = client.get('/')
    assert page.headers['cache-control'] == 'no-store'
    assets = re.findall(r'(\/static\/[^" ]+\?v=[a-f0-9]{16})', page.text)
    assert len(assets) >= 8
    for path in assets:
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'public, max-age=31536000, immutable'
        again = client.get(path, headers={'If-None-Match': response.headers['etag']})
        assert again.status_code == 304
    assert client.get('/static/app.js').headers['cache-control'] == 'public, no-cache'
    assert client.get('/api/v1/links').headers['cache-control'] == 'no-store'
    assert client.get('/static/missing.js?v=abc').headers['cache-control'] == 'no-store'


def test_cached_icon_etag_still_requires_authentication(app, client, monkeypatch):
    image = io.BytesIO(); Image.new('RGB', (32, 32), 'red').save(image, 'PNG')
    monkeypatch.setattr(FaviconCache, 'fetch', staticmethod(lambda _: (image.getvalue(), 'image/png')))
    client.post('/api/v1/links/upsert', json=entry())
    route = '/api/v1/links/project-prod/favicon'
    first = client.get(route)
    assert first.status_code == 200 and first.content == image.getvalue()
    headers = {'If-None-Match': first.headers['etag']}
    assert client.get(route, headers=headers).status_code == 304
    with TestClient(app) as anonymous:
        result = anonymous.get(route, headers=headers)
        assert result.status_code == 401 and result.headers['cache-control'] == 'no-store'
    client.patch('/api/v1/links/project-prod', json={'url': 'https://changed.example.org'})
    monkeypatch.setattr(FaviconCache, 'fetch', staticmethod(lambda _: (b'changed-image', 'image/png')))
    assert client.get(route, headers=headers).status_code == 200


def test_background_webp_same_resolution_preview_and_cache_auth(app, client):
    catalog = client.get('/api/v1/backgrounds').json()['data']
    photo = catalog['photos'][0]
    with Image.open(Path('app/static/backgrounds') / (photo['id'] + '.jpg')) as original:
        size = original.size
    first = client.get(photo['optimized_image'])
    assert first.status_code == 200 and first.headers['content-type'] in ('image/webp', 'image/jpeg')
    with Image.open(io.BytesIO(first.content)) as image:
        assert image.size == size and image.format in ('WEBP', 'JPEG')
    preview = client.get(photo['preview'])
    with Image.open(io.BytesIO(preview.content)) as image:
        assert image.width <= 640 and image.height <= 480
    assert len(preview.content) < len(first.content)
    headers = {'If-None-Match': first.headers['etag']}
    assert client.get(photo['optimized_image'], headers=headers).status_code == 304
    with TestClient(app) as anonymous:
        assert anonymous.get(photo['optimized_image'], headers=headers).status_code == 401
        assert anonymous.get(photo['preview']).status_code == 401
    assert client.get('/api/v1/backgrounds/999999999.webp').status_code == 404
    assert client.get('/api/v1/backgrounds/index-preview.webp').status_code == 404


def test_media_cache_regenerates_after_source_changes(tmp_path):
    original = tmp_path / 'source.jpg'
    Image.new('RGB', (900, 600), 'red').save(original)
    cache = MediaCache(tmp_path / 'cache')
    first = cache.image(original)
    assert cache.image(original) == first
    assert MediaCache(cache.root).image(original) == first
    Image.new('RGB', (1200, 800), 'blue').save(original)
    second = cache.image(original)
    assert second != first
    with Image.open(second) as image:
        assert image.size == (1200, 800)


def test_optimized_image_never_larger_than_original(tmp_path):
    source = tmp_path / 'noise.jpg'
    Image.effect_noise((1024, 768), 100).convert('RGB').save(source, quality=10)
    cache = MediaCache(tmp_path / 'cache')
    result = cache.image(source)
    assert result.stat().st_size <= source.stat().st_size
    assert result == source
    assert cache.image(source) == source
