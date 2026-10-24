import base64
import concurrent.futures
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from app.favicon import FaviconCache, image_type
from app.main import create_app

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jD1kAAAAASUVORK5CYII=')


@pytest.fixture
def site():
    state = {'mode': 'ico', 'requests': Counter(), 'authorization': []}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state['requests'][self.path] += 1
            state['authorization'].append(self.headers.get('Authorization'))
            data = b''; status = 200
            if self.path == '/favicon.ico':
                if state['mode'] == 'ico': data = PNG
                elif state['mode'] == 'oversize':
                    self.send_response(200); self.send_header('Content-Length', str(1024 * 1024)); self.end_headers(); return
                elif state['mode'] == 'redirect':
                    self.send_response(302); self.send_header('Location', 'file:///etc/passwd'); self.end_headers(); return
                else: data = b'<html>not an icon</html>'
            elif self.path == '/':
                data = b'<html><head><link rel="shortcut icon" href="/assets/logo.png"></head></html>' if state['mode'] == 'declared' else b'<html><head></head></html>'
            elif self.path == '/assets/logo.png': data = PNG
            else: status = 404
            self.send_response(status); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)

        def log_message(self, *args): pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    yield f'http://127.0.0.1:{server.server_port}/', state
    server.shutdown(); server.server_close(); thread.join()


def test_icon_fetch_cache_concurrency_and_restart(site, tmp_path):
    url, state = site; cache = FaviconCache(tmp_path / 'icons')
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(cache.get, [url] * 8))
    assert all(r == (PNG, 'image/png') for r in results)
    assert state['requests']['/favicon.ico'] == 1
    assert FaviconCache(tmp_path / 'icons').get(url) == (PNG, 'image/png')
    assert state['requests']['/favicon.ico'] == 1
    assert state['authorization'] == [None]


@pytest.mark.parametrize('mode,success', [('declared', True), ('html', False), ('oversize', False), ('redirect', False)])
def test_declared_icon_and_invalid_fallback(site, tmp_path, mode, success):
    url, state = site; state['mode'] = mode
    cache = FaviconCache(tmp_path / 'icons')
    result = cache.get(url)
    assert result == ((PNG, 'image/png') if success else None)
    before = dict(state['requests']); assert cache.get(url) == result
    assert dict(state['requests']) == before
    assert image_type(b'<svg><script>alert(1)</script></svg>') is None


def test_private_icon_route_and_category_network_counts(tmp_path, monkeypatch):
    from argon2 import PasswordHasher
    monkeypatch.setattr(FaviconCache, 'fetch', staticmethod(lambda _: (PNG, 'image/png')))
    app = create_app({'NAV_BACKGROUND_ENABLED':'false','NAV_DB': str(tmp_path / 'nav.db'), 'NAV_PASSWORD_HASH': PasswordHasher().hash('password'), 'NAV_SESSION_SECRET': 's' * 40, 'NAV_API_TOKEN': 't' * 40, 'NAV_ALLOWED_HOSTS': 'testserver'})
    with TestClient(app) as client:
        assert client.get('/api/v1/links/test/favicon').status_code == 401
        client.headers['Authorization'] = 'Bearer ' + 't' * 40
        for key, network in [('lan', 'lan'), ('public', 'public')]:
            assert client.post('/api/v1/links/upsert', json={'key': key, 'name': key, 'url': 'http://nas:8866', 'category': '分类', 'network': network}).status_code == 201
        category = client.get('/api/v1/categories').json()['data'][0]
        assert (category['lan_count'], category['public_count'], category['link_count']) == (1, 1, 2)
        response = client.get('/api/v1/links/lan/favicon')
        assert response.status_code == 200 and response.content == PNG
        assert response.headers['content-type'] == 'image/png'
        assert client.get('/api/v1/links/missing/favicon').status_code == 404
        assert image_type(client.get('/favicon.ico').content) == 'image/x-icon'
