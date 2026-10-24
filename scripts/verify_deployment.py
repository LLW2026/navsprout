"""Exercise the live API; optional restart/recreate of this Compose application only."""
import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8866')
    parser.add_argument('--exercise-restarts', action='store_true')
    args = parser.parse_args()
    config = dict((k, v.strip("'")) for k, v in (line.split('=',1) for line in (ROOT/'.env').read_text().splitlines() if line and not line.startswith('#')))
    token = config['NAV_API_TOKEN']
    checks = []

    def api(route, method='GET', payload=None):
        req = urllib.request.Request(args.url+'/api/v1'+route, headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'}, method=method, data=json.dumps(payload,ensure_ascii=False).encode() if payload is not None else None)
        with urllib.request.urlopen(req,timeout=30) as r:
            return json.load(r)

    def digest():
        data=api('/export');data.pop('exported_at',None)
        return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),len(data['links'])

    def ready():
        for _ in range(40):
            try:
                with urllib.request.urlopen(args.url+'/healthz',timeout=2) as r:
                    if r.status==200:return
            except (OSError,urllib.error.URLError):pass
            time.sleep(.5)
        raise RuntimeError('服务重启后未就绪')

    ready()
    # The fixture lives in its own category and is always removed.
    prefix='acceptance-'+str(int(time.time()))
    category='验收临时-'+prefix
    try:
        def register(index):
            return api('/links/upsert','POST',{'key':prefix+'-'+str(index%2),'name':'并发登记应用'+str(index%2),'url':'http://nas:8866','category':category})
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results=list(pool.map(register,range(12)))
        assert sum(r['result']=='created' for r in results)==2
        assert len(api('/links?category='+urllib.parse.quote(category))['data'])==2
        checks.append('生产容器：12次并发登记仅2条，分类唯一')
        key=prefix+'-0'
        api('/links/'+key,'PATCH',{'pinned':True,'icon':'🌿','sort_order':88})
        updated=api('/links/upsert','POST',{'key':key,'name':'已更名','url':'https://new.example.com','category':'不得创建的分类','pinned':False,'icon':'X','sort_order':0})['data']
        assert (updated['pinned'],updated['icon'],updated['sort_order'],updated['category'])==(True,'🌿',88,category)
        assert updated['name']=='已更名' and updated['url']=='https://new.example.com'
        checks.append('生产容器：改名改域名，人工分类、排序、置顶和图标保留')
    finally:
        for record in api('/links')['data']:
            if record['key'].startswith(prefix):api('/links/'+record['key'],'DELETE')
        for c in api('/categories')['data']:
            if c['name']==category:api('/categories/'+str(c['id']),'DELETE',{})
    before,count=digest()
    if args.exercise_restarts:
        for action in (['restart','nav'],['up','-d','--force-recreate','nav']):
            subprocess.run(['docker','compose',*action],cwd=ROOT,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            ready()
            assert digest()==(before,count)
            checks.append('容器'+('重启' if action[0]=='restart' else '重建')+'后全部导航内容与时间戳哈希一致')
    backup=ROOT/'backups'/(prefix+'.db')
    subprocess.run([sys.executable,str(ROOT/'scripts/database.py'),'backup',str(ROOT/'data/nav.db'),str(backup)],check=True,stdout=subprocess.PIPE)
    restored=ROOT/'artifacts'/('restored-'+prefix+'.db')
    subprocess.run([sys.executable,str(ROOT/'scripts/database.py'),'restore',str(backup),str(restored),'--app-stopped'],check=True,stdout=subprocess.PIPE)
    import sqlite3
    with sqlite3.connect(restored) as db:
        assert db.execute('SELECT count(*) FROM links').fetchone()[0]==count
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert db.execute('SELECT count(*) FROM sessions').fetchone()[0]==0
    checks.append('生产数据库在线备份并恢复到隔离文件，完整性、条数和会话清理通过')
    output={'url':args.url,'checks':checks,'links':count,'content_sha256':before}
    (ROOT/'artifacts/deployment-results.json').write_text(json.dumps(output,ensure_ascii=False,indent=2))
    print(json.dumps(output,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
