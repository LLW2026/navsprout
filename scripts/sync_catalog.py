"""Review/apply an explicitly curated catalog through the shared navigation client."""
import argparse
import importlib.util
import json
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('nav_client', ROOT / 'skills/nav-manager/scripts/nav.py')
client = importlib.util.module_from_spec(spec); spec.loader.exec_module(client)


def canonical(url):
    p = urlsplit(url)
    return (p.scheme.lower(), p.netloc.lower(), p.path.rstrip('/'), p.query, p.fragment)


def main():
    parser = argparse.ArgumentParser(description='按已核实清单补充导航；默认只预览')
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    try:
        entries = json.loads(args.manifest.read_text())['entries']
        current = client.request('GET', '/links')['data']
        by_key = {r['key']: r for r in current}
        by_url = {}
        for row in current:
            by_url.setdefault(canonical(row['url']), []).append(row)
        seen_keys, seen_urls, report = set(), set(), []
        next_order = min(1000000, max((r['sort_order'] for r in current), default=0) + 10)
        # Resolve every match before writing, so ambiguous manifests make no changes.
        plan = []
        for entry in entries:
            payload = dict(entry); previous = payload.pop('previous_key', None)
            old = by_key.get(payload['key']) or by_key.get(previous)
            matches = by_url.get(canonical(payload['url']), [])
            if not old:
                if len(matches) > 1: raise ValueError('同一网址存在多条记录，请先在网页确认')
                old = matches[0] if matches else None
            elif any(r['key'] != old['key'] for r in matches):
                raise ValueError('目标网址已由另一条记录使用，请先确认')
            if old: payload['key'] = old['key']
            else: payload['sort_order'] = next_order; next_order = min(1000000, next_order + 10)
            if payload['key'] in seen_keys or canonical(payload['url']) in seen_urls:
                raise ValueError('清单中存在重复标识或网址')
            seen_keys.add(payload['key']); seen_urls.add(canonical(payload['url']))
            payload['move_category'] = True
            plan.append((payload, old))
        for payload, old in plan:
            result = 'would_update' if old else 'would_create'
            if args.apply:
                saved = client.request('POST', '/links/upsert', payload)
                actual = client.request('GET', '/links/' + quote(payload['key'], safe=''))['data']
                if actual != saved['data']: raise client.NavError('登记后记录发生变化，请重新核对')
                if old and any(actual[f] != old[f] for f in ('icon', 'pinned', 'sort_order', 'created_at')):
                    raise client.NavError('人工展示字段发生变化，请核对记录')
                result = saved['result']
            report.append({'result': result, 'key': payload['key'], 'name': payload['name'], 'url': payload['url'], 'category': payload['category']})
        output = {'applied': args.apply, 'entries': report}
        if args.report:
            args.report.write_text(json.dumps(output, ensure_ascii=False, indent=2)); args.report.chmod(0o600)
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except (client.NavError, ValueError, KeyError, OSError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
