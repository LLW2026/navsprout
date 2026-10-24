"""Create a dedicated account and secrets without printing credentials."""
import argparse
import os
import secrets
from pathlib import Path

from argon2 import PasswordHasher


def protected(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8866)
    parser.add_argument('--lan-ip', default='127.0.0.1')
    parser.add_argument('--domain', default='')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if (root / '.env').exists():
        raise SystemExit('.env 已存在，未覆盖')
    private = Path.home() / '.config/navsprout'
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    password = secrets.token_urlsafe(18)
    token = secrets.token_urlsafe(36)
    origins = [f'http://{host}:{args.port}' for host in dict.fromkeys(['localhost', '127.0.0.1', args.lan_ip])]
    values = {
        'NAV_PORT': args.port, 'NAV_BIND_IP': '0.0.0.0', 'NAV_UID': os.getuid(), 'NAV_GID': os.getgid(),
        'NAV_USERNAME': 'admin', 'NAV_PASSWORD_HASH': PasswordHasher().hash(password),
        'NAV_SESSION_SECRET': secrets.token_urlsafe(36), 'NAV_API_TOKEN': token,
        'NAV_DB': '/data/nav.db', 'NAV_SESSION_DAYS': 30,
        'NAV_ALLOWED_HOSTS': ','.join(dict.fromkeys(h for h in ['localhost', '127.0.0.1', args.lan_ip, args.domain] if h)),
        'NAV_HTTPS_HOSTS': args.domain,
        'NAV_BACKGROUND_ENABLED': 'true', 'NAV_BACKGROUND_REFRESH_TIME': '06:00',
        'NAV_ALLOWED_ORIGINS': ','.join([*origins, *([f'https://{args.domain}'] if args.domain else [])]),
    }
    protected(private / 'admin-password.txt', password + '\n')
    protected(private / 'nav-manager.env', f'NAV_URL=http://{args.lan_ip}:{args.port}\nNAV_API_TOKEN={token}\n')
    protected(root / '.env', ''.join(f"{k}='{v}'\n" for k, v in values.items()))
    (root / 'data').mkdir(mode=0o700, exist_ok=True)
    print('配置已生成：', root / '.env')
    print('账号：admin；密码保存在：', private / 'admin-password.txt')
    print('自动登记配置保存在：', private / 'nav-manager.env')


if __name__ == '__main__':
    main()
