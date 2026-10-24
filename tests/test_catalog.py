import json
import sys

from scripts import sync_catalog


def test_catalog_append_at_sort_limit_preserves_existing_record(tmp_path, monkeypatch):
    old = {'key': 'existing', 'name': '已有', 'url': 'https://old.example.com/', 'category': '分类', 'icon': '🌿', 'pinned': True, 'sort_order': 1000000, 'created_at': 'original'}
    records = {'existing': dict(old)}
    writes = []

    def request(method, route, payload=None):
        if method == 'POST':
            assert payload['sort_order'] <= 1000000
            writes.append(dict(payload))
            records[payload['key']] = {**payload, 'icon': '', 'pinned': False, 'created_at': 'new'}
            return {'result': 'created', 'data': records[payload['key']]}
        if route == '/links': return {'data': list(records.values())}
        return {'data': records[route.rsplit('/', 1)[-1]]}

    manifest = tmp_path / 'catalog.json'
    manifest.write_text(json.dumps({'entries': [{'key': 'new', 'name': '新应用', 'url': 'https://new.example.com/', 'category': '分类'}]}))
    monkeypatch.setattr(sync_catalog.client, 'request', request)
    monkeypatch.setattr(sys, 'argv', ['sync_catalog.py', str(manifest), '--apply'])
    assert sync_catalog.main() == 0
    assert len(writes) == 1 and records['existing'] == old


def test_ambiguous_catalog_stops_before_writing(tmp_path, monkeypatch):
    records = [{'key': 'one', 'url': 'https://example.com/', 'sort_order': 1}, {'key': 'two', 'url': 'https://example.com', 'sort_order': 2}]
    calls = []

    def request(method, route, payload=None):
        calls.append(method); return {'data': records}

    manifest = tmp_path / 'catalog.json'; manifest.write_text(json.dumps({'entries': [{'key': 'new', 'name': '应用', 'url': 'https://example.com/'}]}))
    monkeypatch.setattr(sync_catalog.client, 'request', request)
    monkeypatch.setattr(sys, 'argv', ['sync_catalog.py', str(manifest), '--apply'])
    assert sync_catalog.main() == 1
    assert calls == ['GET']
