"""Run group and sorting UI checks against an ephemeral loopback database."""
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from argon2 import PasswordHasher

ROOT = Path(__file__).resolve().parents[1]


def main():
    os.chdir(ROOT)
    (ROOT / 'artifacts').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='nav-groups-') as scratch:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        password, token = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
        config = {
            'NAV_DB': scratch + '/nav.db', 'NAV_USERNAME': 'admin',
            'NAV_PASSWORD_HASH': PasswordHasher().hash(password),
            'NAV_SESSION_SECRET': secrets.token_urlsafe(40), 'NAV_API_TOKEN': token,
            'NAV_ALLOWED_HOSTS': '127.0.0.1,localhost', 'NAV_HTTPS_HOSTS': '',
            'NAV_ALLOWED_ORIGINS': base, 'NAV_BACKGROUND_ENABLED': 'false',
        }
        env = {
            **os.environ, **config, 'PYTHONPATH': str(ROOT),
            'NAV_TEST_URL': base, 'NAV_TEST_PASSWORD': password, 'NAV_TEST_API_TOKEN': token,
            'NAV_ORDER_ISOLATED': '1', 'NAV_GROUPS_ISOLATED': '1',
            'NAV_TEST_ARTIFACT_PREFIX': 'groups-regression',
            'PLAYWRIGHT_MODULE': os.environ.get('PLAYWRIGHT_MODULE', str(ROOT / 'node_modules/playwright')),
        }
        # Serve a local icon fixture so these checks do not depend on external websites.
        source = (
            "from app.favicon import FaviconCache;from pathlib import Path;"
            "FaviconCache.fetch=staticmethod(lambda _: (Path('app/static/favicon.ico').read_bytes(),'image/x-icon'));"
            "import uvicorn;uvicorn.run('app.main:create_app',factory=True,host='127.0.0.1',port="
            + str(port) + ",access_log=False)"
        )
        with open('artifacts/groups-test-server.log', 'w') as log:
            proc = subprocess.Popen([sys.executable, '-c', source], env=env, stdout=log, stderr=log)
            try:
                for _ in range(100):
                    if proc.poll() is not None:
                        raise RuntimeError('临时服务启动失败，请查看 artifacts/groups-test-server.log')
                    try:
                        with urllib.request.urlopen(base + '/healthz', timeout=1):
                            break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise RuntimeError('临时服务启动超时')
                subprocess.run(['node', 'tests/groups.cjs'], env=env, check=True)
                # Group checks clean their fixtures; keep the original order regression isolated too.
                subprocess.run(['node', 'tests/appearance-order.cjs'], env=env, check=True)
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()


if __name__ == '__main__':
    main()
