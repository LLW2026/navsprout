"""Atomic ordering operations; filtered clients never renumber just visible cards."""
from .service import fail, now, record


def reorder_categories(db, ids):
    if len(ids) != len(set(ids)):
        fail(422, 'duplicate_ids', '排序列表中存在重复分类')
    if set(ids) != {r['id'] for r in db.execute('SELECT id FROM categories')}:
        fail(409, 'order_changed', '分类已变化，请刷新后重试')
    stamp = now()
    for i, cid in enumerate(ids):
        db.execute('UPDATE categories SET sort_order=?,updated_at=? WHERE id=? AND sort_order<>?', (i * 10, stamp, cid, i * 10))


def reorder_links(db, body):
    if len(body.keys) != len(set(body.keys)):
        fail(422, 'duplicate_keys', '排序列表中存在重复标识')
    if body.category_id is not None:
        if not db.execute('SELECT id FROM categories WHERE id=?', (body.category_id,)).fetchone():
            fail(404, 'not_found', '分类不存在')
        available = {r['key'] for r in db.execute('SELECT key FROM links WHERE category_id=?', (body.category_id,))}
    else:
        available = {r['key'] for r in db.execute('SELECT key FROM links')}
    if body.complete and set(body.keys) != available:
        fail(409, 'order_changed', '网址已变化，请刷新后重试')
    for key in body.keys:
        record(db, key)
        if key not in available:
            fail(409, 'order_changed', '网址所属分类已变化，请刷新后重试')
    stamp = now()
    for i, key in enumerate(body.keys):
        db.execute('UPDATE links SET sort_order=?,updated_at=? WHERE key=? AND sort_order<>?', (i * 10, stamp, key, i * 10))


def move_link(db, body):
    source = record(db, body.key)
    cid = body.category_id if body.category_id is not None else source['category_id']
    pinned = body.pinned if body.pinned is not None else source['pinned']
    if not db.execute('SELECT id FROM categories WHERE id=?', (cid,)).fetchone():
        fail(404, 'not_found', '分类不存在')
    if body.before_key == body.key:
        return source
    scope, values = ('pinned=1', ()) if pinned else ('pinned=0 AND category_id=?', (cid,))
    keys = [r['key'] for r in db.execute(f'SELECT key FROM links WHERE {scope} ORDER BY sort_order,key', values) if r['key'] != body.key]
    if body.before_key is not None and body.before_key not in keys:
        fail(409, 'order_changed', '目标网址已变化，请刷新后重试')
    keys.insert(keys.index(body.before_key) if body.before_key else len(keys), body.key)
    stamp = now()
    db.execute('UPDATE links SET category_id=?,pinned=?,updated_at=? WHERE key=? AND (category_id<>? OR pinned<>?)', (cid, pinned, stamp, body.key, cid, pinned))
    for i, key in enumerate(keys):
        db.execute('UPDATE links SET sort_order=?,updated_at=? WHERE key=? AND sort_order<>?', (i * 10, stamp, key, i * 10))
    return record(db, body.key)
