import concurrent.futures
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from app.db import transaction
from app.main import create_app
from scripts.database import copy_database


@pytest.fixture
def config(tmp_path):
    return {'NAV_BACKGROUND_ENABLED':'false','NAV_DB':str(tmp_path/'nav.db'),'NAV_PASSWORD_HASH':PasswordHasher().hash('测试密码123'),'NAV_SESSION_SECRET':'s'*40,'NAV_API_TOKEN':'t'*40,'NAV_ALLOWED_HOSTS':'testserver,127.0.0.1,localhost,nav.example.com','NAV_ALLOWED_ORIGINS':'http://testserver,https://nav.example.com'}


@pytest.fixture
def app(config):
    return create_app(config)


@pytest.fixture
def client(app):
    return TestClient(app,headers={'Authorization':'Bearer '+'t'*40})


def entry(key='project-prod',**kw):
    return {'key':key,'name':'政策解读助手','url':'http://192.168.1.10:8080','category':'我的应用',**kw}


def test_privacy_and_server_session(app,config):
    with TestClient(app) as browser:
        for path in ['/links','categories','export','auth/me','openapi.json']:
            assert browser.get('/api/v1/'+path.lstrip('/')).status_code==401
        assert browser.post('/api/v1/links/upsert',json=entry()).status_code==401
        assert browser.post('/api/v1/auth/login',json={'username':'陌生人','password':'错误'}).status_code==401
        r=browser.post('/api/v1/auth/login',json={'username':'admin','password':'测试密码123'})
        assert r.status_code==200
        csrf=r.json()['data']['csrf']; old_cookie=browser.cookies.get('nav_session')
        assert 'httponly' in r.headers['set-cookie'].lower()
        assert browser.post('/api/v1/links/upsert',json=entry()).status_code==403
        browser.headers['X-CSRF-Token']=csrf
        assert browser.post('/api/v1/links/upsert',json=entry()).status_code==201
        assert browser.post('/api/v1/links/upsert',json=entry(),headers={'Origin':'https://evil.invalid'}).status_code==403
        with TestClient(create_app(config)) as second:
            assert second.get('/api/v1/links').status_code==401
            login=second.post('/api/v1/auth/login',json={'username':'admin','password':'测试密码123'})
            assert login.status_code==200
            assert len(second.get('/api/v1/links').json()['data'])==1
        assert browser.post('/api/v1/auth/logout',json={}).status_code==200
        browser.cookies.set('nav_session',old_cookie)
        assert browser.get('/api/v1/links').status_code==401
    with TestClient(app,base_url='https://nav.example.com') as public:
        r=public.post('/api/v1/auth/login',json={'username':'admin','password':'测试密码123'})
        assert 'secure' in r.headers['set-cookie'].lower()


def test_browser_read_burst_while_writer_busy_and_periodic_session_renewal(app, config, client, monkeypatch):
    from app.favicon import FaviconCache
    monkeypatch.setattr(FaviconCache, 'fetch', staticmethod(lambda _: ((Path(__file__).parents[1] / 'app/static/favicon.ico').read_bytes(), 'image/x-icon')))
    assert client.post('/api/v1/links/upsert', json=entry()).status_code == 201
    with TestClient(app) as browser:
        login = browser.post('/api/v1/auth/login', json={'username': 'admin', 'password': '测试密码123'})
        assert login.status_code == 200
        with transaction(config['NAV_DB']) as db:
            original = db.execute('SELECT expires FROM sessions').fetchone()[0]
        # A slow writer must not block ordinary authenticated reads or cached icons.
        routes = ['/links', '/categories', '/links/project-prod/favicon'] * 4
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(routes)) as pool:
            with transaction(config['NAV_DB'], write=True):
                futures = [pool.submit(browser.get, '/api/v1' + route) for route in routes]
                assert all(f.result(timeout=3).status_code == 200 for f in futures)
        with transaction(config['NAV_DB'], write=True) as db:
            assert db.execute('SELECT expires FROM sessions').fetchone()[0] == original
            db.execute('UPDATE sessions SET expires=?', (time.time() + 30 * 86400 - 4000,))
        renewed = browser.get('/api/v1/auth/me')
        assert renewed.status_code == 200 and renewed.json()['data']['csrf'] == login.json()['data']['csrf']
        assert 'Max-Age=2592000' in renewed.headers['set-cookie']
        with transaction(config['NAV_DB'], write=True) as db:
            assert db.execute('SELECT expires FROM sessions').fetchone()[0] > time.time() + 30 * 86400 - 10
            db.execute('UPDATE sessions SET expires=?', (time.time() - 1,))
        assert browser.get('/api/v1/links').status_code == 401


def test_existing_14_day_session_upgrades_to_30_days(config):
    with TestClient(create_app({**config, 'NAV_SESSION_DAYS': '14'})) as original:
        login = original.post('/api/v1/auth/login', json={'username': 'admin', 'password': '测试密码123'})
        assert login.status_code == 200 and 'Max-Age=1209600' in login.headers['set-cookie']
        cookie = original.cookies.get('nav_session')
    with TestClient(create_app(config)) as upgraded:
        upgraded.cookies.set('nav_session', cookie)
        response = upgraded.get('/api/v1/auth/me')
        assert response.status_code == 200
        assert response.json()['data']['csrf'] == login.json()['data']['csrf']
        assert 'Max-Age=2592000' in response.headers['set-cookie']
        with transaction(config['NAV_DB']) as db:
            remaining = db.execute('SELECT expires FROM sessions').fetchone()[0] - time.time()
            assert 30 * 86400 - 10 < remaining <= 30 * 86400
        upgraded.headers['X-CSRF-Token'] = response.json()['data']['csrf']
        assert upgraded.post('/api/v1/auth/logout', json={}).status_code == 200
        upgraded.cookies.set('nav_session', cookie)
        assert upgraded.get('/api/v1/auth/me').status_code == 401


def test_idempotency_update_and_presentation(client):
    r=client.post('/api/v1/links/upsert',json=entry(description='中文问答',icon='🌿',pinned=True,sort_order=42))
    assert r.status_code==201
    original=r.json()['data']; assert original['created_at']
    for _ in range(4):
        r=client.post('/api/v1/links/upsert',json=entry(description='中文问答'))
        assert r.json()['result']=='unchanged'
        assert r.json()['data']['updated_at']==original['updated_at']
    r=client.post('/api/v1/links/upsert',json={'key':'project-prod','name':'新政策助手','url':'https://new.example.com','category':'另一分类','icon':'X','pinned':False,'sort_order':0})
    data=r.json()['data']
    assert data['category']=='我的应用' and data['icon']=='🌿' and data['pinned'] and data['sort_order']==42
    assert data['description']=='中文问答' and data['created_at']==original['created_at']
    assert data['url']=='https://new.example.com'
    assert len(client.get('/api/v1/links').json()['data'])==1
    r=client.post('/api/v1/links/upsert',json={'key':'project-prod','category':'另一分类','move_category':True,'description':''})
    assert r.json()['data']['category']=='另一分类' and r.json()['data']['description']==''
    assert client.post('/api/v1/links/upsert',json={'key':'new'}).status_code==422
    assert client.post('/api/v1/links/upsert',json={'key':'project-prod','description':None}).status_code==422


def test_chinese_search_crud_category_protection(client):
    c=client.post('/api/v1/categories',json={'name':'中文分类','sort_order':10}).json()['data']
    assert client.post('/api/v1/categories',json={'name':' 中文分类 '}).status_code==409
    r=client.post('/api/v1/links',json=entry(category='中文分类',description='排放标准查询'))
    key=r.json()['data']['key']; assert r.status_code==201
    assert len(client.get('/api/v1/links',params={'q':'标准'}).json()['data'])==1
    assert len(client.get('/api/v1/links',params={'q':'192.168'}).json()['data'])==1
    assert client.patch('/api/v1/links/'+key,json={'name':'修改后的中文','pinned':True,'sort_order':99}).json()['data']['pinned']
    assert client.request('DELETE','/api/v1/categories/'+str(c['id']),json={}).status_code==409
    target=client.post('/api/v1/categories',json={'name':'迁入分类'}).json()['data']
    r=client.request('DELETE','/api/v1/categories/'+str(c['id']),json={'move_to':target['id']})
    assert r.status_code==200 and r.json()['data']['moved_links']==1
    assert client.get('/api/v1/links/'+key).json()['data']['category']=='迁入分类'
    assert client.delete('/api/v1/links/'+key).status_code==200
    assert client.get('/api/v1/links/'+key).status_code==404


@pytest.mark.parametrize('url',['http://nas:8080','https://localhost','http://192.168.1.2','http://[::1]:8000','https://例子.中国/path','https://example.com/a?x=1#b'])
def test_valid_urls(client,url):
    assert client.post('/api/v1/links/upsert',json=entry(url=url)).status_code==201


@pytest.mark.parametrize('url',['javascript:alert(1)','data:text/html,x','file:///a','ftp://abc','https://','http://a b/','http://user:pass@example.com','http://a:99999','http://a\\evil.com','http://-a.com','http://a/%0a'])
def test_invalid_urls(client,url):
    # Percent-encoded URL path bytes are allowed; literal controls and unsafe protocols are not.
    expected=201 if url=='http://a/%0a' else 422
    assert client.post('/api/v1/links/upsert',json=entry(url=url)).status_code==expected


def test_concurrent_upserts(app):
    def call(i):
        with TestClient(app,headers={'Authorization':'Bearer '+'t'*40}) as c:
            return c.post('/api/v1/links/upsert',json=entry('app-'+str(i%12),category='并发分类')).status_code
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        statuses=list(pool.map(call,range(48)))
    assert all(s in (200,201) for s in statuses)
    with TestClient(app,headers={'Authorization':'Bearer '+'t'*40}) as c:
        assert len(c.get('/api/v1/links').json()['data'])==12
        assert len(c.get('/api/v1/categories').json()['data'])==1


def test_reorder_transaction_and_import_restore(client,config,tmp_path):
    for key in ('a','b'):
        client.post('/api/v1/links/upsert',json=entry(key))
    assert client.post('/api/v1/links/reorder',json={'keys':['b','a']}).status_code==200
    assert [r['key'] for r in client.get('/api/v1/links').json()['data']]==['b','a']
    before=client.get('/api/v1/export').json()
    assert client.post('/api/v1/links/reorder',json={'keys':['a','absent']}).status_code==404
    assert [r['key'] for r in client.get('/api/v1/links').json()['data']]==['b','a']
    copy_database(config['NAV_DB'],tmp_path/'backup.db')
    restored=tmp_path/'restored.db';copy_database(tmp_path/'backup.db',restored,True)
    with TestClient(create_app({**config,'NAV_DB':str(restored)}),headers=client.headers) as c:
        after=c.get('/api/v1/export').json();after.pop('exported_at');expected=dict(before);expected.pop('exported_at');assert after==expected
    empty=tmp_path/'empty.db'
    with TestClient(create_app({**config,'NAV_DB':str(empty)}),headers=client.headers) as c:
        assert c.post('/api/v1/import',json=before).json()['data']['created']==2
        assert c.post('/api/v1/import',json=before).json()['data']['unchanged']==2
        bad=json.loads(json.dumps(before));bad['links'][1]['url']='javascript:alert(1)';bad['categories'][0]['name']='不应写入'
        assert c.post('/api/v1/import',json=bad).status_code==422
        assert c.get('/api/v1/categories').json()['data'][0]['name']=='我的应用'


def test_credential_rotation_revokes_sessions(app,config):
    browser=TestClient(app)
    assert browser.post('/api/v1/auth/login',json={'username':'admin','password':'测试密码123'}).status_code==200
    rotated=TestClient(create_app({**config,'NAV_PASSWORD_HASH':PasswordHasher().hash('new-password')}))
    rotated.cookies.update(browser.cookies)
    assert rotated.get('/api/v1/links').status_code==401


def test_username_change_preserves_password_and_revokes_old_sessions(config):
    original=TestClient(create_app({**config,'NAV_USERNAME':'admin'}))
    assert original.post('/api/v1/auth/login',json={'username':'admin','password':'测试密码123'}).status_code==200
    renamed=TestClient(create_app({**config,'NAV_USERNAME':'owner'}))
    renamed.cookies.update(original.cookies)
    assert renamed.get('/api/v1/links').status_code==401
    assert renamed.post('/api/v1/auth/login',json={'username':'admin','password':'测试密码123'}).status_code==401
    assert renamed.post('/api/v1/auth/login',json={'username':'owner','password':'测试密码123'}).status_code==200


def test_wal_backup_restore_clears_session_and_keeps_latest_data(client,config,tmp_path):
    # Keep the source WAL open, as a live service would, while backing it up.
    import sqlite3
    db=sqlite3.connect(config['NAV_DB'])
    try:
        db.execute("INSERT INTO sessions VALUES('existing','csrf',9999999999,'fingerprint')")
        db.commit()
        assert client.post('/api/v1/links/upsert',json=entry(description='WAL中最新提交')).status_code==201
        backup=tmp_path/'wal-backup.db';restored=tmp_path/'restored-session.db'
        copy_database(config['NAV_DB'],backup)
        copy_database(backup,restored,True)
        check=sqlite3.connect(restored)
        try:
            assert check.execute('SELECT count(*) FROM sessions').fetchone()[0]==0
            assert check.execute('SELECT description FROM links').fetchone()[0]=='WAL中最新提交'
            assert check.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        finally:check.close()
        assert not Path(str(restored)+'-wal').exists()
    finally:db.close()


def test_login_throttle(app):
    with TestClient(app) as c:
        for _ in range(10):
            assert c.post('/api/v1/auth/login',json={'username':'admin','password':'bad'}).status_code==401
        assert c.post('/api/v1/auth/login',json={'username':'admin','password':'bad'}).status_code==429


def test_real_http_helper(config):
    import uvicorn
    sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen();port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(create_app(config),log_level='error'))
    thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start()
    for _ in range(100):
        if server.started: break
        time.sleep(.02)
    assert server.started
    try:
        env={**os.environ,'NAV_URL':f'http://127.0.0.1:{port}','NAV_API_TOKEN':config['NAV_API_TOKEN']}
        script=str(Path(__file__).parents[1]/'skills/nav-manager/scripts/nav.py')
        cmd=[sys.executable,script,'upsert','--key','helper-prod','--name','脚本实际登记','--url','http://nas:8866','--category','我的应用']
        for outcome in ('created','unchanged'):
            result=subprocess.run(cmd,env=env,text=True,capture_output=True,timeout=20)
            assert result.returncode==0,result.stderr
            data=json.loads(result.stdout);assert data['confirmed'] and data['result']==outcome
            assert config['NAV_API_TOKEN'] not in result.stdout+result.stderr
        result=subprocess.run([sys.executable,script,'get','helper-prod'],env={**env,'NAV_API_TOKEN':'wrong'},capture_output=True,text=True)
        assert result.returncode==1 and '401' in result.stderr
    finally:
        server.should_exit=True;thread.join(timeout=5)


def test_complete_sort_scope_and_atomic_rejection(client, config):
    for key, cat in [('a', '甲'), ('b', '甲'), ('outside', '乙')]:
        assert client.post('/api/v1/links/upsert', json=entry(key, category=cat, icon='★', sort_order=99, pinned=True)).status_code == 201
    a = client.get('/api/v1/links/a').json()['data']
    before = client.get('/api/v1/export').json()
    for body, status in [({'keys':['b','missing']},404), ({'keys':['b','b']},422),
                         ({'keys':['b'], 'complete':True, 'category_id':a['category_id']},409),
                         ({'keys':['b','outside'], 'category_id':a['category_id']},409)]:
        assert client.post('/api/v1/links/reorder',json=body).status_code == status
        after = client.get('/api/v1/export').json()
        assert after['links'] == before['links']
    assert client.post('/api/v1/links/reorder', json={'keys':['b','a'], 'complete':True, 'category_id':a['category_id']}).status_code == 200
    assert [l['key'] for l in client.get('/api/v1/links?category=甲').json()['data']] == ['b','a']
    saved = client.get('/api/v1/links/a').json()['data']
    assert {k:v for k,v in saved.items() if k not in ('sort_order','updated_at')} == {k:v for k,v in a.items() if k not in ('sort_order','updated_at')}
    assert client.get('/api/v1/links/outside').json()['data']['sort_order'] == 99
    with TestClient(create_app(config),headers={'Authorization':'Bearer '+'t'*40}) as restarted:
        assert [l['key'] for l in restarted.get('/api/v1/links?category=甲').json()['data']] == ['b','a']


def test_drag_hidden_items_and_move_category_transaction(client):
    for i, key in enumerate(['a','hidden','b','c']):
        client.post('/api/v1/links/upsert',json=entry(key, category='甲', sort_order=i*10, network='lan' if key=='hidden' else 'public', icon='◆'))
    target = client.post('/api/v1/categories',json={'name':'乙'}).json()['data']
    original = client.get('/api/v1/links/c').json()['data']
    assert client.post('/api/v1/links/move',json={'key':'c','before_key':'b'}).status_code == 200
    assert [l['key'] for l in client.get('/api/v1/links?category=甲').json()['data']] == ['a','hidden','c','b']
    result = client.post('/api/v1/links/move',json={'key':'c','category_id':target['id'],'pinned':False})
    assert result.status_code == 200 and result.json()['data']['category'] == '乙'
    assert all(result.json()['data'][f] == original[f] for f in ['key','name','url','description','icon','pinned','created_at'])
    before = client.get('/api/v1/export').json()['links']
    assert client.post('/api/v1/links/move',json={'key':'a','category_id':target['id'],'before_key':'b'}).status_code == 409
    assert client.get('/api/v1/export').json()['links'] == before
    assert client.post('/api/v1/links/move',json={'key':'a','category_id':987654}).status_code == 404


def test_drag_pinned_scope_and_upsert_preserves_presentation(client):
    for i,key in enumerate(['a','b','c']):
        client.post('/api/v1/links/upsert',json=entry(key,category='甲' if i%2 else '乙',pinned=True,icon='★',sort_order=i*10))
    assert client.post('/api/v1/links/move',json={'key':'c','before_key':'a','pinned':True}).status_code == 200
    assert [l['key'] for l in client.get('/api/v1/links').json()['data']] == ['c','a','b']
    before = client.get('/api/v1/links/c').json()['data']
    client.post('/api/v1/links/upsert',json={'key':'c','name':'新名称','url':'https://new.example.com','category':'自动分类'})
    after = client.get('/api/v1/links/c').json()['data']
    assert all(after[f] == before[f] for f in ['sort_order','pinned','icon','category_id'])
    assert client.post('/api/v1/links/move',json={'key':'c','pinned':False}).status_code == 200
    assert client.get('/api/v1/links/c').json()['data']['pinned'] is False


def test_categories_reorder_atomic_and_stale_membership(client):
    ids = [client.post('/api/v1/categories',json={'name':n}).json()['data']['id'] for n in ['甲','乙','丙']]
    before = client.get('/api/v1/categories').json()['data']
    for order,status in [([ids[0],ids[0]],422), (ids[:2],409), ([ids[0],ids[1],99999],409)]:
        assert client.post('/api/v1/categories/reorder',json={'ids':order}).status_code == status
        assert client.get('/api/v1/categories').json()['data'] == before
    assert client.post('/api/v1/categories/reorder',json={'ids':ids[::-1]}).status_code == 200
    assert [c['id'] for c in client.get('/api/v1/categories').json()['data']] == ids[::-1]


def test_concurrent_drag_and_registration_preserve_all_records(client):
    for i in range(8):
        client.post('/api/v1/links/upsert',json=entry(f'old-{i}',sort_order=i*10,icon='★'))
    def action(i):
        if i%2:
            return client.post('/api/v1/links/move',json={'key':f'old-{i}','before_key':'old-0'}).status_code
        return client.post('/api/v1/links/upsert',json=entry(f'new-{i}')).status_code
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        assert all(status in (200,201) for status in pool.map(action,range(8)))
    data = client.get('/api/v1/links').json()['data']
    assert {l['key'] for l in data} == {f'old-{i}' for i in range(8)} | {f'new-{i}' for i in range(0,8,2)}
    assert all(l['icon']=='★' for l in data if l['key'].startswith('old'))


def test_sort_routes_require_authentication_and_csrf(app):
    routes = [('/links/move',{'key':'a'}),('/links/reorder',{'keys':['a'],'complete':True}),('/categories/reorder',{'ids':[1]})]
    with TestClient(app) as browser:
        for route,body in routes:
            assert browser.post('/api/v1'+route,json=body).status_code == 401
        browser.post('/api/v1/auth/login',json={'username':'admin','password':'测试密码123'})
        for route,body in routes:
            assert browser.post('/api/v1'+route,json=body).status_code == 403


def test_batch_updates_are_atomic_and_invalid_input_rolls_back(client):
    for key in ['a','b','untouched']:client.post('/api/v1/links',json=entry(key,icon='◆',sort_order=77))
    before=client.get('/api/v1/export').json()['links']
    for body,status in [({'items':[{'key':'a','name':'已修改'},{'key':'missing'}]},404),
                        ({'items':[{'key':'a'},{'key':'a'}]},422),
                        ({'items':[{'key':'a','url':'javascript:alert(1)'}]},422),
                        ({'items':[{'key':'a'}],'operation':'move','category_id':987654},404)]:
        assert client.post('/api/v1/links/batch',json=body).status_code==status
        assert client.get('/api/v1/export').json()['links']==before
    result=client.post('/api/v1/links/batch',json={'items':[{'key':'a','name':'批量中文修改','url':'https://new.example.com','description':'新说明'},{'key':'b','description':''}]})
    assert result.status_code==200 and result.json()['data']['affected']==2
    saved=client.get('/api/v1/links/a').json()['data']
    assert (saved['name'],saved['icon'],saved['sort_order'])==('批量中文修改','◆',77)
    assert next(l for l in client.get('/api/v1/export').json()['links'] if l['key']=='untouched')==next(l for l in before if l['key']=='untouched')


def test_batch_move_pin_unpin_and_delete_save_real_records(client,config):
    for key in ['a','b','other']:client.post('/api/v1/links',json=entry(key,icon='★',sort_order=22))
    target=client.post('/api/v1/categories',json={'name':'目标分类'}).json()['data']['id']
    items=[{'key':'a','name':'修改后移动'},{'key':'b'}]
    assert client.post('/api/v1/links/batch',json={'items':items,'operation':'move','category_id':target}).status_code==200
    assert all(client.get('/api/v1/links/'+key).json()['data']['category_id']==target for key in ['a','b'])
    for operation,expected in [('pin',True),('unpin',False)]:
        assert client.post('/api/v1/links/batch',json={'items':items,'operation':operation}).status_code==200
        assert all(client.get('/api/v1/links/'+key).json()['data']['pinned'] is expected for key in ['a','b'])
    with TestClient(create_app(config),headers=client.headers) as restarted:
        assert restarted.get('/api/v1/links/a').json()['data']['name']=='修改后移动'
        assert restarted.get('/api/v1/links/b').json()['data']['icon']=='★'
    assert client.post('/api/v1/links/batch',json={'items':items,'operation':'delete'}).json()['data']['affected']==2
    assert [l['key'] for l in client.get('/api/v1/links').json()['data']]==['other']
    assert any(c['id']==target for c in client.get('/api/v1/categories').json()['data'])


def test_batch_requires_authentication_and_csrf(app):
    with TestClient(app) as browser:
        assert browser.post('/api/v1/links/batch',json={'items':[{'key':'a'}]}).status_code==401
        browser.post('/api/v1/auth/login',json={'username':'admin','password':'测试密码123'})
        assert browser.post('/api/v1/links/batch',json={'items':[{'key':'a'}]}).status_code==403
