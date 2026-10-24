from .service import fail, record, save


def edit_batch(db, body):
    keys = [item.key for item in body.items]
    if len(keys) != len(set(keys)):
        fail(422, 'duplicate_keys', '所选网址存在重复标识')
    target = None
    if body.operation == 'move':
        target = db.execute('SELECT name FROM categories WHERE id=?', (body.category_id,)).fetchone()
        if not target:
            fail(404, 'not_found', '目标分类不存在')
    for key in keys:
        record(db, key)
    result = []
    for item in body.items:
        if body.operation == 'delete':
            db.execute('DELETE FROM links WHERE key=?', (item.key,))
            continue
        data = item.model_dump(exclude_unset=True)
        if target:
            data['category'] = target['name']
        if body.operation in ('pin', 'unpin'):
            data['pinned'] = body.operation == 'pin'
        _, saved = save(db, data, 'patch')
        result.append(saved)
    return {'affected': len(keys), 'links': result}
