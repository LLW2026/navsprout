import concurrent.futures
import sqlite3

from fastapi.testclient import TestClient

from app.db import migrate, transaction
from app.main import create_app
from scripts.database import copy_database
from test_core import app, client, config, entry


def seed(client):
    result=[]
    for i in range(4):
        r=client.post('/api/v1/links/upsert',json=entry(f'g-{i}',name=f'入口{i}',category='应用',network='lan' if i%2 else 'public',pinned=i==1,icon='验',sort_order=i*10))
        assert r.status_code==201
        result.append(r.json()['data'])
    return result


def make(client,keys=('g-0','g-1'),name='聚合应用'):
    response=client.post('/api/v1/groups',json={'name':name,'keys':list(keys)})
    assert response.status_code==201,response.text
    return response.json()['data']


def test_create_rename_and_dissolve_preserve_links(client):
    original=seed(client);g=make(client)
    assert g['keys']==['g-0','g-1'] and not g['pinned']
    assert client.get('/api/v1/groups').json()['data']==[g]
    edited=client.patch('/api/v1/groups/'+g['key'],json={'name':'新名称','icon':'合','pinned':True}).json()['data']
    assert edited['name']=='新名称' and edited['pinned'] and edited['icon']=='合'
    assert [client.get('/api/v1/links/'+r['key']).json()['data'] for r in original]==original
    assert client.delete('/api/v1/groups/'+g['key']).status_code==200
    assert client.get('/api/v1/groups').json()['data']==[]
    assert [client.get('/api/v1/links/'+r['key']).json()['data'] for r in original]==original


def test_same_category_no_nesting_duplicate_members_and_atomic_update(client):
    seed(client);g=make(client)
    assert client.post('/api/v1/groups',json={'name':'嵌套','keys':['group:'+g['key'],'g-2']}).status_code==404
    assert client.post('/api/v1/groups',json={'name':'重复','keys':['g-0','g-2']}).status_code==409
    assert client.post('/api/v1/groups',json={'name':'重复','keys':['g-2','g-2']}).status_code==422
    client.patch('/api/v1/links/g-2',json={'category':'其他分类'})
    assert client.patch('/api/v1/groups/'+g['key'],json={'name':'不应保存','keys':['g-0','g-2']}).status_code==409
    assert client.get('/api/v1/groups').json()['data'][0]==g
    assert client.post('/api/v1/groups',json={'name':'单成员','keys':['g-3']}).status_code==422


def test_add_remove_order_and_empty_group_cleanup(client):
    seed(client);g=make(client)
    path='/api/v1/groups/'+g['key']
    r=client.patch(path,json={'keys':['g-2','g-1','g-0']})
    assert r.status_code==200 and r.json()['data']['keys']==['g-2','g-1','g-0']
    assert client.delete(path+'/members/g-1').status_code==200
    assert client.get('/api/v1/links/g-1').status_code==200
    client.delete('/api/v1/links/g-2')
    assert client.get('/api/v1/groups').json()['data'][0]['keys']==['g-0']
    client.delete(path+'/members/g-0')
    assert client.get('/api/v1/groups').json()['data']==[]
    assert client.get('/api/v1/links/g-0').status_code==200


def test_move_member_detaches_and_group_moves_atomically(client):
    seed(client);g=make(client)
    target=client.post('/api/v1/categories',json={'name':'目标'}).json()['data']['id']
    moved=client.patch('/api/v1/groups/'+g['key'],json={'category_id':target}).json()['data']
    assert moved['category_id']==target and moved['keys']==g['keys']
    for key in g['keys']:
        assert client.get('/api/v1/links/'+key).json()['data']['category_id']==target
    client.patch('/api/v1/links/g-0',json={'category':'移出'})
    assert client.get('/api/v1/groups').json()['data'][0]['keys']==['g-1']
    client.post('/api/v1/links/batch',json={'operation':'move','items':[{'key':'g-1'}],'category_id':g['category_id']})
    assert client.get('/api/v1/groups').json()['data']==[]


def test_category_delete_migrates_groups_without_dissolving(client):
    seed(client);g=make(client)
    target=client.post('/api/v1/categories',json={'name':'迁入'}).json()['data']['id']
    assert client.request('DELETE','/api/v1/categories/'+str(g['category_id']),json={}).status_code==409
    response=client.request('DELETE','/api/v1/categories/'+str(g['category_id']),json={'move_to':target})
    assert response.status_code==200
    group=client.get('/api/v1/groups').json()['data'][0]
    assert group['keys']==g['keys'] and group['category_id']==target


def test_automation_search_filters_and_private_api(app,client):
    seed(client);g=make(client)
    assert len(client.get('/api/v1/links?q=聚合应用').json()['data'])==2
    assert len(client.get('/api/v1/links?q=聚合应用&network=lan').json()['data'])==1
    response=client.post('/api/v1/links/upsert',json={'key':'g-0','name':'新名称','url':'https://new.example.org'})
    assert response.json()['result']=='updated'
    assert client.get('/api/v1/groups').json()['data'][0]==g
    assert client.get('/api/v1/links/g-0').json()['data']['icon']=='验'
    with TestClient(app) as anonymous:
        assert anonymous.get('/api/v1/groups').status_code==401
        assert anonymous.post('/api/v1/groups',json={'name':'聚合','keys':g['keys']}).status_code==401
        assert anonymous.patch('/api/v1/groups/'+g['key'],json={'pinned':True}).status_code==401
        assert anonymous.post('/api/v1/cards/move',json={'key':'g-2'}).status_code==401


def test_groups_require_session_csrf(app,client):
    seed(client)
    with TestClient(app) as browser:
        login=browser.post('/api/v1/auth/login',json={'username':'admin','password':'测试密码123'})
        assert login.status_code==200
        data={'name':'聚合','keys':['g-0','g-1']}
        assert browser.post('/api/v1/groups',json=data).status_code==403
        assert browser.post('/api/v1/groups',json=data,headers={'X-CSRF-Token':login.json()['data']['csrf']}).status_code==201


def test_card_ordering_treats_groups_as_one_and_preserves_member_order(client):
    seed(client);g=make(client);ref='group:'+g['key']
    original=client.get('/api/v1/links/g-0').json()['data']
    assert client.post('/api/v1/cards/reorder',json={'keys':[ref,'g-3','g-2'],'complete':True}).status_code==200
    assert client.post('/api/v1/cards/reorder',json={'keys':[ref,'g-0','g-2','g-3'],'complete':True}).status_code==409
    assert client.post('/api/v1/cards/move',json={'key':ref,'before_key':'g-2'}).status_code==200
    group=client.get('/api/v1/groups').json()['data'][0]
    assert group['keys']==g['keys']
    assert client.get('/api/v1/links/g-0').json()['data']==original
    target=client.post('/api/v1/categories',json={'name':'拖动目标'}).json()['data']['id']
    assert client.post('/api/v1/cards/move',json={'key':ref,'category_id':target,'pinned':False}).status_code==200
    assert client.get('/api/v1/groups').json()['data'][0]['category_id']==target


def test_export_import_backup_restore_groups_and_legacy_data(client,config,tmp_path):
    seed(client);g=make(client)
    client.delete('/api/v1/groups/'+g['key']+'/members/g-1')
    exported=client.get('/api/v1/export').json()
    assert exported['version']==2 and exported['groups'][0]['keys']==['g-0']
    other={**config,'NAV_DB':str(tmp_path/'other.db')}
    with TestClient(create_app(other),headers={'Authorization':'Bearer '+'t'*40}) as fresh:
        assert fresh.post('/api/v1/import',json=exported).status_code==200
        actual=fresh.get('/api/v1/export').json();actual.pop('exported_at');exported.pop('exported_at')
        assert actual==exported
        broken={**exported,'groups':exported['groups']*2}
        assert fresh.post('/api/v1/import',json=broken).status_code==422
        assert fresh.get('/api/v1/groups').json()['data'][0]['keys']==['g-0']
    backup=tmp_path/'backup.db';copy_database(config['NAV_DB'],backup)
    restored=tmp_path/'restored.db';copy_database(backup,restored,restore=True)
    with TestClient(create_app({**config,'NAV_DB':str(restored)}),headers={'Authorization':'Bearer '+'t'*40}) as fresh:
        assert len(fresh.get('/api/v1/groups').json()['data'])==1
    legacy={**exported,'version':1};legacy.pop('groups')
    assert client.post('/api/v1/import',json=legacy).status_code==200
    assert client.get('/api/v1/groups').json()['data'][0]['key']==g['key']


def test_concurrent_group_claims_only_one_winner(app,client):
    seed(client)
    def create(i):
        with TestClient(app,headers={'Authorization':'Bearer '+'t'*40}) as c:
            return c.post('/api/v1/groups',json={'name':str(i),'keys':['g-0','g-1']}).status_code
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        codes=list(pool.map(create,range(4)))
    assert codes.count(201)==1 and codes.count(409)==3
    assert len(client.get('/api/v1/groups').json()['data'])==1


def test_upgrade_v1_preserves_rows_and_session(config,client):
    seed(client)
    with transaction(config['NAV_DB'],write=True) as db:
        before=[dict(r) for r in db.execute('SELECT * FROM links ORDER BY key')]
        db.execute('DROP TABLE group_members');db.execute('DROP TABLE link_groups')
        db.execute('DROP TRIGGER detach_moved_link');db.execute('PRAGMA user_version=1')
    migrate(config['NAV_DB'])
    with transaction(config['NAV_DB']) as db:
        assert [dict(r) for r in db.execute('SELECT * FROM links ORDER BY key')]==before
        assert db.execute('PRAGMA user_version').fetchone()[0]==2


def test_imported_long_group_key_can_be_moved(client):
    seed(client)
    exported=client.get('/api/v1/export').json()
    key='g'*128
    exported.update(version=2,groups=[{'key':key,'name':'长标识聚合','category':'应用','keys':['g-0','g-1']}])
    assert client.post('/api/v1/import',json=exported).status_code==200
    assert client.post('/api/v1/cards/move',json={'key':'group:'+key,'before_key':'g-2'}).status_code==200
    assert client.post('/api/v1/cards/move',json={'key':'g-3','before_key':'group:'+key}).status_code==200
