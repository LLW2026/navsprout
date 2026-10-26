import secrets
from datetime import datetime, timezone

from fastapi import HTTPException


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def fail(status, code, message):
    raise HTTPException(status_code=status, detail={'code': code, 'message': message})


def category_id(db, name):
    stamp = now()
    db.execute('INSERT INTO categories(name,created_at,updated_at) VALUES(?,?,?) ON CONFLICT(name) DO NOTHING', (name, stamp, stamp))
    return db.execute('SELECT id FROM categories WHERE name=?', (name,)).fetchone()['id']


def record(db, key):
    row = db.execute('SELECT l.*, c.name category FROM links l JOIN categories c ON c.id=l.category_id WHERE key=?', (key,)).fetchone()
    if row is None:
        fail(404, 'not_found', '链接不存在')
    data = dict(row)
    data['pinned'] = bool(data['pinned'])
    return data


def save(db, payload, mode='upsert'):
    data = payload.model_dump(exclude_unset=True) if hasattr(payload, 'model_dump') else dict(payload)
    key = data.pop('key', None) or secrets.token_hex(12)
    old = db.execute('SELECT * FROM links WHERE key=?', (key,)).fetchone()
    if mode == 'create' and old:
        fail(409, 'duplicate_key', '此标识已存在')
    if mode == 'patch' and not old:
        fail(404, 'not_found', '链接不存在')
    move = data.pop('move_category', False)
    presentation = data.pop('update_presentation', False)
    data.pop('category_id', None)
    if old:
        data.pop('created_at', None)
        data.pop('updated_at', None)
        if mode == 'upsert':
            if not move:
                data.pop('category', None)
            if not presentation:
                for field in ('pinned', 'sort_order', 'icon'):
                    data.pop(field, None)
        if 'category' in data:
            data['category_id'] = category_id(db, data.pop('category'))
        changed = {k: v for k, v in data.items() if old[k] != v}
        if not changed:
            return 'unchanged', record(db, key)
        changed['updated_at'] = now()
        db.execute('UPDATE links SET ' + ','.join(f'{k}=?' for k in changed) + ' WHERE key=?', (*changed.values(), key))
        return 'updated', record(db, key)
    if not data.get('name') or not data.get('url'):
        fail(422, 'required_fields', '创建链接时请填写名称和网址')
    data['category_id'] = category_id(db, data.pop('category', '未分类'))
    data['key'] = key
    data.setdefault('created_at', now())
    data.setdefault('updated_at', data['created_at'])
    db.execute('INSERT INTO links (' + ','.join(data) + ') VALUES (' + ','.join('?' for _ in data) + ')', tuple(data.values()))
    return 'created', record(db, key)


def export_data(db):
    categories = [dict(r) for r in db.execute('SELECT name,sort_order FROM categories ORDER BY sort_order,id')]
    links = []
    for row in db.execute('SELECT key FROM links ORDER BY category_id,sort_order,key'):
        data = record(db, row['key'])
        data.pop('category_id')
        links.append(data)
    from .groups import list_groups
    groups = list_groups(db)
    result = {'version': 2 if groups else 1, 'exported_at': now(), 'categories': categories, 'links': links}
    if groups:
        result['groups'] = [{k:v for k,v in g.items() if k != 'category_id'} for g in groups]
    return result


def import_data(db, payload):
    names = [c.name.casefold() for c in payload.categories]
    keys = [l.key for l in payload.links]
    if len(names) != len(set(names)) or len(keys) != len(set(keys)):
        fail(422, 'duplicate_import', '导入文件中存在重复分类或标识')
    for category in payload.categories:
        cid = category_id(db, category.name)
        db.execute('UPDATE categories SET sort_order=?,updated_at=? WHERE id=?', (category.sort_order, now(), cid))
    counts = {'created': 0, 'updated': 0, 'unchanged': 0}
    for link in payload.links:
        result, _ = save(db, link, mode='import')
        counts[result] += 1
    if payload.version == 2 and payload.groups is None:
        fail(422, 'groups_required', '导入文件缺少聚合数据')
    if payload.groups is not None:
        from .groups import save_group
        group_keys = [g.key for g in payload.groups]
        members = [k for g in payload.groups for k in g.keys]
        if len(group_keys) != len(set(group_keys)) or len(members) != len(set(members)):
            fail(422, 'duplicate_groups', '聚合标识或成员存在重复')
        # Keep each imported group alive while updating membership; conflicting groups are rejected.
        for group in payload.groups:
            data = group.model_dump(exclude_none=True)
            data['category_id'] = category_id(db, data.pop('category'))
            key = data['key']
            old = db.execute('SELECT 1 FROM link_groups WHERE key=?', (key,)).fetchone()
            save_group(db, data, key if old else None, restoring=True)
    return counts
