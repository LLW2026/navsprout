"""Single-level groups retain independent link records and registration keys."""
import secrets
from .service import fail, now, record


def group_record(db, key):
    row = db.execute('SELECT g.*,c.name category FROM link_groups g JOIN categories c ON c.id=g.category_id WHERE g.key=?', (key,)).fetchone()
    if row is None:
        fail(404, 'not_found', '聚合卡片不存在')
    result = dict(row)
    result['pinned'] = bool(result['pinned'])
    result['keys'] = [r['link_key'] for r in db.execute('SELECT link_key FROM group_members WHERE group_key=? ORDER BY sort_order,link_key', (key,))]
    return result


def list_groups(db):
    return [group_record(db, r['key']) for r in db.execute('SELECT key FROM link_groups ORDER BY sort_order,key')]


def save_group(db, data, key=None, restoring=False):
    data = dict(data)
    old = group_record(db, key) if key else None
    keys = data.pop('keys', old['keys'] if old else [])
    if not keys or (not old and len(keys) < 2 and not restoring):
        fail(422, 'members_required', '请选择至少两个网址' if not old else '请保留至少一个网址，或拆分聚合')
    if len(keys) != len(set(keys)):
        fail(422, 'duplicate_keys', '所选网址存在重复标识')
    members = [record(db, k) for k in keys]
    cid = data.get('category_id', old['category_id'] if old else members[0]['category_id'])
    if not db.execute('SELECT id FROM categories WHERE id=?', (cid,)).fetchone():
        fail(404, 'not_found', '分类不存在')
    # A group category change moves its current members; newly added links must already belong there.
    for member in members:
        moving = old and member['key'] in old['keys'] and cid != old['category_id']
        if member['category_id'] != cid and not moving:
            fail(409, 'different_category', '只能聚合同一分类的网址')
        owner = db.execute('SELECT group_key FROM group_members WHERE link_key=?', (member['key'],)).fetchone()
        if owner and owner['group_key'] != key:
            fail(409, 'already_grouped', '所选网址已属于其他聚合，请先移出')
    stamp = now()
    if old:
        allowed = {k:v for k,v in data.items() if k in ('name','icon','pinned','sort_order','category_id') and old[k] != v}
        if allowed:
            allowed['updated_at'] = stamp
            db.execute('UPDATE link_groups SET '+','.join(k+'=?' for k in allowed)+' WHERE key=?', (*allowed.values(),key))
    else:
        key = data.pop('key', None) or 'group-'+secrets.token_hex(12)
        db.execute('INSERT INTO link_groups(key,name,category_id,icon,pinned,sort_order,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                   (key,data['name'],cid,data.get('icon',''),data.get('pinned',False),data.get('sort_order',min(m['sort_order'] for m in members)),data.get('created_at',stamp),data.get('updated_at',stamp)))
    # Insert first: removing the final old member would deliberately dissolve an empty group.
    for i, member in enumerate(keys):
        db.execute('INSERT INTO group_members(link_key,group_key,sort_order) VALUES(?,?,?) ON CONFLICT(link_key) DO UPDATE SET sort_order=excluded.sort_order', (member,key,i*10))
    placeholders = ','.join('?' for _ in keys)
    db.execute(f'DELETE FROM group_members WHERE group_key=? AND link_key NOT IN ({placeholders})', (key,*keys))
    if old and keys != old['keys']:
        db.execute('UPDATE link_groups SET updated_at=? WHERE key=?', (stamp,key))
    return group_record(db,key)


def card_entities(db, category_id=None):
    entries = [dict(r) for r in db.execute('SELECT key,name,category_id,pinned,sort_order FROM links WHERE key NOT IN (SELECT link_key FROM group_members)')]
    entries += [{**dict(r),'key':'group:'+r['key']} for r in db.execute('SELECT key,name,category_id,pinned,sort_order FROM link_groups')]
    return [r for r in entries if category_id is None or r['category_id']==category_id]


def update_card(db, key, values):
    group = key.startswith('group:')
    table, actual = ('link_groups',key[6:]) if group else ('links',key)
    changed = {**values,'updated_at':now()}
    db.execute(f'UPDATE {table} SET '+','.join(k+'=?' for k in changed)+' WHERE key=?', (*changed.values(),actual))


def reorder_cards(db, body):
    entries = card_entities(db,body.category_id)
    available = {r['key'] for r in entries}
    if len(body.keys)!=len(set(body.keys)):
        fail(422,'duplicate_keys','排序列表中存在重复卡片')
    if (body.complete and set(body.keys)!=available) or not set(body.keys)<=available:
        fail(409,'order_changed','卡片已变化，请刷新后重试')
    for i,key in enumerate(body.keys):
        update_card(db,key,{'sort_order':i*10})


def move_card(db, body):
    entries = card_entities(db)
    source = next((r for r in entries if r['key']==body.key),None)
    if not source:
        fail(409,'order_changed','卡片已变化，请刷新后重试')
    cid = body.category_id if body.category_id is not None else source['category_id']
    pinned = body.pinned if body.pinned is not None else source['pinned']
    if not db.execute('SELECT id FROM categories WHERE id=?',(cid,)).fetchone():
        fail(404,'not_found','分类不存在')
    if body.before_key==body.key:
        return
    scope = sorted((r for r in entries if (r['pinned'] if pinned else not r['pinned'] and r['category_id']==cid) and r['key']!=body.key),key=lambda r:(r['sort_order'],r['key']))
    keys = [r['key'] for r in scope]
    if body.before_key is not None and body.before_key not in keys:
        fail(409,'order_changed','目标卡片已变化，请刷新后重试')
    keys.insert(keys.index(body.before_key) if body.before_key else len(keys),body.key)
    update_card(db,body.key,{'category_id':cid,'pinned':bool(pinned)})
    for i,key in enumerate(keys):
        update_card(db,key,{'sort_order':i*10})
