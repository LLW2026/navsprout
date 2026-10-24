#!/usr/bin/env python3
"""Dependency-free navigation client. Credentials are read only from environment."""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


class NavError(Exception):
    pass


def request(method, path, payload=None):
    base = os.environ.get('NAV_URL', '').rstrip('/')
    token = os.environ.get('NAV_API_TOKEN', '')
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.query or parsed.fragment or parsed.username or parsed.password or not token:
        raise NavError('请通过 NAV_URL 和 NAV_API_TOKEN 配置导航地址与令牌')
    body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    req = urllib.request.Request(base + '/api/v1' + path, data=body, headers={'Authorization':'Bearer ' + token,'Content-Type':'application/json'}, method=method)
    # Never follow a redirect with an Authorization header.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    for attempt in range(3):
        try:
            with opener.open(req, timeout=15) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code in (502, 503, 504) and attempt < 2:
                time.sleep(1 + attempt)
                continue
            # Do not echo arbitrary proxy responses or the request's headers.
            message = {401:'认证失败，请检查令牌',403:'访问被拒绝',404:'记录不存在',409:'记录冲突',422:'登记字段或网址格式不正确',429:'请求过于频繁'}.get(exc.code, '导航接口请求失败')
            raise NavError(f'{message}（HTTP {exc.code}）') from None
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == 2:
                raise NavError('无法连接导航服务，重试后仍失败') from None
            time.sleep(1 + attempt)
        except (ValueError, json.JSONDecodeError):
            raise NavError('导航服务返回了无效的 JSON') from None


def main():
    parser = argparse.ArgumentParser(description='导航查询与登记')
    sub = parser.add_subparsers(dest='command', required=True)
    get = sub.add_parser('get'); get.add_argument('key')
    search = sub.add_parser('search'); search.add_argument('keyword', nargs='?', default='')
    upsert = sub.add_parser('upsert')
    upsert.add_argument('--key', required=True)
    for field in ('name', 'url', 'category', 'description', 'organization', 'network', 'environment'):
        upsert.add_argument('--' + field)
    upsert.add_argument('--move-category', action='store_true', default=None)
    args = parser.parse_args()
    try:
        if args.command == 'get':
            data = request('GET', '/links/' + urllib.parse.quote(args.key, safe=''))
        elif args.command == 'search':
            data = request('GET', '/links?' + urllib.parse.urlencode({'q':args.keyword}))
        else:
            payload = {k:v for k,v in vars(args).items() if k != 'command' and v is not None}
            result = request('POST', '/links/upsert', payload)
            confirmed = request('GET', '/links/' + urllib.parse.quote(args.key, safe=''))['data']
            # Concurrent legitimate writers may race the readback. Report rather than falsely confirming.
            expected = result['data']
            if confirmed != expected:
                raise NavError('登记后记录发生变化，请重新查询确认')
            data = {'result':result['result'],'confirmed':True,'data':confirmed}
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    except NavError as exc:
        print(json.dumps({'error':str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
