import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
import anyio
from contextlib import asynccontextmanager
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .db import migrate, transaction
from .backgrounds import Backgrounds
from .batch import edit_batch
from .groups import group_record, list_groups, save_group, move_card, reorder_cards
from .favicon import FaviconCache
from .media import MediaCache
from .models import GroupCreate, GroupPatch, BatchEdit, Category, CategoryOrder, Create, DeleteCategory, ImportData, LinkFields, Login, MoveLink, Reorder, Upsert
from .ordering import move_link, reorder_categories, reorder_links
from .service import export_data, fail, import_data, now, record, save

STATIC = Path(__file__).parent / 'static'


class SchemeSessions:
    """Starlette signs an opaque ID; identity, expiry and CSRF live in SQLite."""
    def __init__(self, app, secret_key, https_hosts, max_age):
        self.https_hosts = https_hosts
        options = dict(secret_key=secret_key, session_cookie='nav_session', same_site='lax', max_age=max_age)
        self.secure = SessionMiddleware(app, https_only=True, **options)
        self.lan = SessionMiddleware(app, https_only=False, **options)

    async def __call__(self, scope, receive, send):
        host = dict(scope.get('headers', [])).get(b'host', b'').decode().split(':')[0]
        middleware = self.secure if scope.get('scheme') == 'https' or host in self.https_hosts else self.lan
        await middleware(scope, receive, send)


def create_app(config=None):
    cfg = dict(os.environ if config is None else config)
    path = cfg.get('NAV_DB', '/data/nav.db')
    password_hash = cfg.get('NAV_PASSWORD_HASH', '')
    secret = cfg.get('NAV_SESSION_SECRET', '')
    token = cfg.get('NAV_API_TOKEN', '')
    if len(secret) < 32 or len(token) < 32 or not password_hash.startswith('$argon2id$'):
        raise RuntimeError('请配置 Argon2id 密码哈希及至少 32 字符的会话密钥、API 令牌')
    username = cfg.get('NAV_USERNAME', 'admin')
    origins = set(cfg.get('NAV_ALLOWED_ORIGINS', 'http://localhost:8866,http://127.0.0.1:8866').split(','))
    age = int(cfg.get('NAV_SESSION_DAYS', '30')) * 86400
    fingerprint = hashlib.sha256((username + password_hash + secret).encode()).hexdigest()
    migrate(path)
    icons = FaviconCache(Path(path).parent / 'favicon-cache')
    icon_limiter = anyio.CapacityLimiter(6)
    media = MediaCache(Path(path).parent / 'media-cache')
    background_enabled = cfg.get('NAV_BACKGROUND_ENABLED', 'true').lower()
    if background_enabled not in ('true', 'false'):
        raise RuntimeError('NAV_BACKGROUND_ENABLED 请填写 true 或 false')
    backgrounds = Backgrounds(Path(path).parent / 'background-cache', STATIC / 'backgrounds/catalog.json', cfg.get('NAV_BACKGROUND_REFRESH_TIME', '06:00'), background_enabled == 'true')

    async def refresh_backgrounds():
        while True:
            await anyio.to_thread.run_sync(backgrounds.refresh_if_due, abandon_on_cancel=True)
            await anyio.sleep(30)

    @asynccontextmanager
    async def lifespan(app):
        async with anyio.create_task_group() as tasks:
            if backgrounds.enabled:
                tasks.start_soon(refresh_backgrounds)
            yield
            tasks.cancel_scope.cancel()

    app = FastAPI(title='NavSprout API', version='1.0.0', docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.db_path = path
    app.state.backgrounds = backgrounds
    app.add_middleware(SchemeSessions, secret_key=secret, https_hosts=set(cfg.get('NAV_HTTPS_HOSTS', 'nav.example.com').split(',')), max_age=age)

    @app.middleware('http')
    async def guard(request, call_next):
        if request.method in ('POST', 'PATCH', 'PUT', 'DELETE'):
            if request.headers.get('origin') and request.headers['origin'] not in origins:
                return JSONResponse({'error': {'code': 'origin_denied', 'message': '此访问来源未获允许'}}, status_code=403)
            size = 0
            chunks = []
            async for chunk in request.stream():
                size += len(chunk)
                if size > 4 * 1024 * 1024:
                    return JSONResponse({'error': {'code': 'too_large', 'message': '文件或请求超过 4 MB'}}, status_code=413)
                chunks.append(chunk)
            request._body = b''.join(chunks)
        response = await call_next(request)
        response.headers.setdefault('Cache-Control', 'no-store')
        if request.url.path.startswith('/static/') and response.status_code in (200, 304):
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable' if request.query_params.get('v') else 'public, no-cache'
        response.headers.update({
            'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'DENY', 'Referrer-Policy': 'no-referrer',
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        })
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        detail = exc.detail if isinstance(exc.detail, dict) else {'code': 'not_found' if exc.status_code == 404 else 'request_error', 'message': '页面或接口不存在' if exc.status_code == 404 else '请求无法完成'}
        return JSONResponse({'error': detail}, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        fields = ['.'.join(map(str, e['loc'][1:])) for e in exc.errors()]
        return JSONResponse({'error': {'code': 'validation_error', 'message': '请检查填写内容、字段类型和网址格式', 'fields': fields}}, status_code=422)

    @app.exception_handler(sqlite3.IntegrityError)
    async def integrity_error(request, exc):
        return JSONResponse({'error': {'code': 'conflict', 'message': '分类名称或链接标识已存在'}}, status_code=409)

    @app.exception_handler(sqlite3.OperationalError)
    async def database_error(request, exc):
        return JSONResponse({'error': {'code': 'database_busy', 'message': '数据暂时无法保存，请稍后重试'}}, status_code=503, headers={'Retry-After': '2'})

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        return JSONResponse({'error': {'code': 'internal_error', 'message': '服务暂时无法完成请求'}}, status_code=500)

    def authenticated(request: Request):
        auth = request.headers.get('authorization', '')
        if auth:
            if auth.startswith('Bearer ') and hmac.compare_digest(auth[7:].encode(), token.encode()):
                return {'method': 'token'}
            fail(401, 'unauthorized', '访问令牌无效')
        sid = request.session.get('sid', '')
        checked_at = time.time()
        with transaction(path) as db:
            session = db.execute('SELECT * FROM sessions WHERE id=?', (hashlib.sha256(sid.encode()).hexdigest(),)).fetchone() if sid else None
        if not session or session['expires'] <= checked_at or session['fingerprint'] != fingerprint:
            request.session.clear()
            fail(401, 'unauthorized', '请先登录')
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and not hmac.compare_digest(request.headers.get('x-csrf-token', '').encode(), session['csrf'].encode()):
            fail(403, 'csrf_failed', '页面已过期，请刷新后重试')
        # Icon bursts and ordinary reads share authentication without becoming writers.
        # Renew at most once per hour; the conditional update cannot revive a removed session.
        renewal_cutoff = checked_at + age - min(3600, age / 4)
        if session['expires'] <= renewal_cutoff:
            with transaction(path, write=True) as db:
                renewed = db.execute('UPDATE sessions SET expires=? WHERE id=? AND fingerprint=? AND expires>? AND expires<=?', (checked_at + age, session['id'], fingerprint, checked_at, renewal_cutoff)).rowcount
            if renewed:
                request.session['sid'] = sid
        return {'method': 'session', 'csrf': session['csrf']}

    auth_dep = [Depends(authenticated)]

    def private_file(request, path, media_type):
        response = FileResponse(path, media_type=media_type, stat_result=path.stat(), headers={'Cache-Control': 'private, no-cache', 'Vary': 'Authorization'})
        if response.headers['etag'] in [v.strip() for v in request.headers.get('if-none-match', '').split(',')]:
            return Response(status_code=304, headers=dict(response.headers))
        return response

    @app.get('/api/v1/backgrounds', dependencies=auth_dep)
    def background_catalog():
        catalog = backgrounds.catalog()
        for photo in catalog['photos']:
            photo['optimized_image'] = f"/api/v1/backgrounds/{photo['id']}.image?v=3"
            photo['preview'] = f"/api/v1/backgrounds/{photo['id']}-preview.webp?v=3"
        return {'data': catalog}

    @app.get('/api/v1/backgrounds/{filename}', dependencies=auth_dep)
    def background_image(filename: str, request: Request):
        if filename.endswith(('.webp', '.image')):
            image_id = filename.rsplit('.', 1)[0]
            preview = image_id.endswith('-preview')
            if preview:
                image_id = image_id[:-8]
            cached = backgrounds.image_path(image_id + '.jpg')
            if not cached and image_id in {p['id'] for p in backgrounds.fallback}:
                cached = STATIC / 'backgrounds' / (image_id + '.jpg')
            if not cached:
                fail(404, 'not_found', '背景图片不存在')
            optimized = media.image(cached, preview)
            return private_file(request, optimized, 'image/webp' if optimized.suffix == '.webp' else 'image/jpeg')
        cached = backgrounds.image_path(filename)
        if not cached:
            fail(404, 'not_found', '背景图片不存在')
        return private_file(request, cached, 'image/jpeg')

    @app.get('/healthz')
    def health():
        with transaction(path) as db:
            db.execute('SELECT 1').fetchone()
        return {'status': 'ok'}

    @app.get('/favicon.ico', include_in_schema=False)
    def app_favicon():
        return FileResponse(STATIC / 'favicon.ico', media_type='image/x-icon')

    @app.post('/api/v1/auth/login')
    def login(body: Login, request: Request):
        client = request.client.host
        stamp = time.time()
        with transaction(path, write=True) as db:
            db.execute('DELETE FROM login_attempts WHERE at<?', (stamp - 900,))
            if db.execute('SELECT count(*) FROM login_attempts WHERE client=?', (client,)).fetchone()[0] >= 10:
                fail(429, 'rate_limited', '尝试次数较多，请 15 分钟后重试')
            db.execute('INSERT INTO login_attempts VALUES(?,?)', (client, stamp))
        try:
            valid = PasswordHasher().verify(password_hash, body.password)
        except (VerificationError, InvalidHashError):
            valid = False
        if not hmac.compare_digest(body.username.encode(), username.encode()) or not valid:
            fail(401, 'invalid_login', '账号或密码不正确')
        sid, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with transaction(path, write=True) as db:
            old_sid = request.session.get('sid', '')
            db.execute('DELETE FROM sessions WHERE id=? OR expires<?', (hashlib.sha256(old_sid.encode()).hexdigest(), stamp))
            db.execute('DELETE FROM login_attempts WHERE client=?', (client,))
            db.execute('INSERT INTO sessions VALUES(?,?,?,?)', (hashlib.sha256(sid.encode()).hexdigest(), csrf, stamp + age, fingerprint))
        request.session.clear()
        request.session['sid'] = sid
        return {'data': {'username': username, 'csrf': csrf}}

    @app.get('/api/v1/auth/me')
    def me(identity=Depends(authenticated)):
        return {'data': {'username': username, **identity}}

    @app.post('/api/v1/auth/logout', dependencies=auth_dep)
    def logout(request: Request):
        sid = request.session.get('sid', '')
        with transaction(path, write=True) as db:
            db.execute('DELETE FROM sessions WHERE id=?', (hashlib.sha256(sid.encode()).hexdigest(),))
        request.session.clear()
        return {'data': {'logged_out': True}}

    @app.get('/api/v1/categories', dependencies=auth_dep)
    def categories():
        with transaction(path) as db:
            return {'data': [dict(r) for r in db.execute("SELECT c.*,count(l.key) link_count,coalesce(sum(l.network='lan'),0) lan_count,coalesce(sum(l.network='public'),0) public_count FROM categories c LEFT JOIN links l ON l.category_id=c.id GROUP BY c.id ORDER BY c.sort_order,c.id")]}

    @app.post('/api/v1/categories', dependencies=auth_dep, status_code=201)
    def add_category(body: Category):
        stamp = now()
        with transaction(path, write=True) as db:
            cur = db.execute('INSERT INTO categories(name,sort_order,created_at,updated_at) VALUES(?,?,?,?)', (body.name, body.sort_order, stamp, stamp))
            return {'data': dict(db.execute('SELECT * FROM categories WHERE id=?', (cur.lastrowid,)).fetchone())}

    @app.post('/api/v1/categories/reorder', dependencies=auth_dep)
    def category_order(body: CategoryOrder):
        with transaction(path, write=True) as db:
            reorder_categories(db, body.ids)
        return {'data': {'saved': True}}

    @app.patch('/api/v1/categories/{cid}', dependencies=auth_dep)
    def edit_category(cid: int, body: Category):
        with transaction(path, write=True) as db:
            if not db.execute('SELECT id FROM categories WHERE id=?', (cid,)).fetchone():
                fail(404, 'not_found', '分类不存在')
            db.execute('UPDATE categories SET name=?,sort_order=?,updated_at=? WHERE id=?', (body.name, body.sort_order, now(), cid))
            return {'data': dict(db.execute('SELECT * FROM categories WHERE id=?', (cid,)).fetchone())}

    @app.delete('/api/v1/categories/{cid}', dependencies=auth_dep)
    def delete_category(cid: int, body: DeleteCategory):
        with transaction(path, write=True) as db:
            if not db.execute('SELECT id FROM categories WHERE id=?', (cid,)).fetchone():
                fail(404, 'not_found', '分类不存在')
            count = db.execute('SELECT count(*) FROM links WHERE category_id=?', (cid,)).fetchone()[0]
            if count:
                if body.move_to == cid or not db.execute('SELECT id FROM categories WHERE id=?', (body.move_to,)).fetchone():
                    fail(409, 'category_not_empty', '请先选择链接迁入的分类')
                db.execute('UPDATE link_groups SET category_id=?,updated_at=? WHERE category_id=?', (body.move_to, now(), cid))
                db.execute('UPDATE links SET category_id=?,updated_at=? WHERE category_id=?', (body.move_to, now(), cid))
            db.execute('DELETE FROM categories WHERE id=?', (cid,))
        return {'data': {'deleted': True, 'moved_links': count}}

    @app.get('/api/v1/groups', dependencies=auth_dep)
    def groups():
        with transaction(path) as db:
            return {'data': list_groups(db)}

    @app.post('/api/v1/groups', dependencies=auth_dep, status_code=201)
    def create_group(body: GroupCreate):
        with transaction(path, write=True) as db:
            data = save_group(db, body.model_dump())
        return {'data': data}

    @app.patch('/api/v1/groups/{key}', dependencies=auth_dep)
    def patch_group(key: str, body: GroupPatch):
        with transaction(path, write=True) as db:
            data = save_group(db, body.model_dump(exclude_unset=True), key)
        return {'data': data}

    @app.delete('/api/v1/groups/{key}', dependencies=auth_dep)
    def dissolve_group(key: str):
        with transaction(path, write=True) as db:
            group_record(db, key)
            db.execute('DELETE FROM link_groups WHERE key=?', (key,))
        return {'data': {'dissolved': True}}

    @app.delete('/api/v1/groups/{key}/members/{member}', dependencies=auth_dep)
    def detach_member(key: str, member: str):
        with transaction(path, write=True) as db:
            group_record(db, key)
            if not db.execute('SELECT 1 FROM group_members WHERE group_key=? AND link_key=?', (key, member)).fetchone():
                fail(404, 'not_found', '网址已移出聚合')
            db.execute('DELETE FROM group_members WHERE group_key=? AND link_key=?', (key, member))
        return {'data': {'detached': True}}

    @app.post('/api/v1/cards/reorder', dependencies=auth_dep)
    def card_order(body: Reorder):
        with transaction(path, write=True) as db:
            reorder_cards(db, body)
        return {'data': {'saved': True}}

    @app.post('/api/v1/cards/move', dependencies=auth_dep)
    def card_move(body: MoveLink):
        with transaction(path, write=True) as db:
            move_card(db, body)
        return {'data': {'saved': True}}

    @app.get('/api/v1/links', dependencies=auth_dep)
    def links(q: str = '', category: str = '', organization: str = '', network: str = '', environment: str = ''):
        with transaction(path) as db:
            result = [record(db, row['key']) for row in db.execute('SELECT key FROM links ORDER BY sort_order,key')]
            group_names = {r['link_key']:r['name'] for r in db.execute('SELECT m.link_key,g.name FROM group_members m JOIN link_groups g ON g.key=m.group_key')}
        keyword = q.casefold()
        return {'data': [r for r in result if (not keyword or any(keyword in text.casefold() for text in (r['name'], r['url'], r['description'], group_names.get(r['key'], '')))) and all(not v or r[k] == v for k, v in [('category', category), ('organization', organization), ('network', network), ('environment', environment)])]}

    @app.post('/api/v1/links/upsert', dependencies=auth_dep)
    def upsert(body: Upsert):
        with transaction(path, write=True) as db:
            result, data = save(db, body)
        return JSONResponse({'result': result, 'data': data}, status_code=201 if result == 'created' else 200)

    @app.post('/api/v1/links', dependencies=auth_dep, status_code=201)
    def create_link(body: Create):
        with transaction(path, write=True) as db:
            result, data = save(db, body, 'create')
        return {'result': result, 'data': data}

    @app.post('/api/v1/links/batch', dependencies=auth_dep)
    def batch_edit(body: BatchEdit):
        with transaction(path, write=True) as db:
            data = edit_batch(db, body)
        return {'data': data}

    @app.post('/api/v1/links/reorder', dependencies=auth_dep)
    def reorder(body: Reorder):
        with transaction(path, write=True) as db:
            reorder_links(db, body)
        return {'data': {'saved': True}}

    @app.post('/api/v1/links/move', dependencies=auth_dep)
    def move(body: MoveLink):
        with transaction(path, write=True) as db:
            data = move_link(db, body)
        return {'data': data}

    @app.get('/api/v1/links/{key}', dependencies=auth_dep)
    def get_link(key: str):
        with transaction(path) as db:
            return {'data': record(db, key)}

    @app.get('/api/v1/links/{key}/favicon', dependencies=auth_dep)
    async def link_favicon(key: str, request: Request):
        with transaction(path) as db:
            url = record(db, key)['url']
        result = await anyio.to_thread.run_sync(icons.get, url, limiter=icon_limiter)
        headers = {'Cache-Control': 'private, no-cache', 'Vary': 'Authorization'}
        if not result:
            return Response(status_code=204, headers=headers)
        headers['ETag'] = '"' + hashlib.sha256(result[0]).hexdigest() + '"'
        if headers['ETag'] in [v.strip() for v in request.headers.get('if-none-match', '').split(',')]:
            return Response(status_code=304, headers=headers)
        return Response(result[0], media_type=result[1], headers=headers)

    @app.patch('/api/v1/links/{key}', dependencies=auth_dep)
    def patch_link(key: str, body: LinkFields):
        with transaction(path, write=True) as db:
            result, data = save(db, {'key': key, **body.model_dump(exclude_unset=True)}, 'patch')
        return {'result': result, 'data': data}

    @app.delete('/api/v1/links/{key}', dependencies=auth_dep)
    def delete_link(key: str):
        with transaction(path, write=True) as db:
            record(db, key)
            db.execute('DELETE FROM links WHERE key=?', (key,))
        return {'data': {'deleted': True}}

    @app.get('/api/v1/export', dependencies=auth_dep)
    def export():
        with transaction(path) as db:
            return JSONResponse(export_data(db), headers={'Content-Disposition': 'attachment; filename="navigation.json"'})

    @app.post('/api/v1/import', dependencies=auth_dep)
    def import_(body: ImportData):
        with transaction(path, write=True) as db:
            return {'data': import_data(db, body)}

    @app.get('/api/v1/openapi.json', dependencies=auth_dep)
    def openapi():
        return app.openapi()

    index_html = (STATIC / 'index.html').read_text()
    for asset in STATIC.iterdir():
        if asset.is_file() and asset.suffix in {'.js', '.css', '.svg', '.png'}:
            version = hashlib.sha256(asset.read_bytes()).hexdigest()[:16]
            index_html = index_html.replace(f'/static/{asset.name}"', f'/static/{asset.name}?v={version}"')

    @app.get('/')
    def index():
        return HTMLResponse(index_html)

    app.mount('/static', StaticFiles(directory=STATIC), name='static')
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=cfg.get('NAV_ALLOWED_HOSTS', 'localhost,127.0.0.1,nav.example.com,192.168.1.10,192.168.1.11').split(','))
    return app
