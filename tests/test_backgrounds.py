import concurrent.futures
import hashlib
import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app import backgrounds
from app.backgrounds import Backgrounds, CHINA, MAX_IMAGE, download, fetch_photo, trusted_url
from app.main import create_app
from test_core import config

FALLBACK = Path(__file__).parents[1] / 'app/static/backgrounds/catalog.json'
JPEG = bytes.fromhex('ffd8 ffc0 0011 08 0d05 1388 03 012200 021101 031101 ffd9')


def photo(pid):
    return {'id':pid, 'source_id':pid.rsplit('-',1)[-1], 'author':'测试摄影者',
            'source':'https://unsplash.com/photos/test', 'license':'https://unsplash.com/license',
            'width':5000, 'height':3333, 'sha256':hashlib.sha256(JPEG).hexdigest()}, JPEG


def test_daily_boundary_once_per_day_and_cache_survives_restart(tmp_path, monkeypatch):
    calls=[]
    def fetch(period, recent):
        calls.append((period,set(recent)))
        return photo(period+'-'+str(len(calls)))
    monkeypatch.setattr(backgrounds,'fetch_photo',fetch)
    library=Backgrounds(tmp_path,FALLBACK)
    at=datetime(2026,10,24,7,tzinfo=CHINA)
    assert library.refresh_if_due(at)
    assert not library.refresh_if_due(at+timedelta(hours=15))
    assert not library.refresh_if_due(datetime(2026,10,25,5,59,59,tzinfo=CHINA))
    assert library.refresh_if_due(datetime(2026,10,25,6,tzinfo=CHINA))
    assert calls==[('2026-10-24',set()),('2026-10-25',{'1'})]
    state=library.catalog(datetime(2026,10,25,6,tzinfo=CHINA))
    assert state['status']=='ready' and state['daily_id']=='2026-10-25-2'
    assert state['next_refresh_at']=='2026-10-26T06:00:00+08:00'
    restarted=Backgrounds(tmp_path,FALLBACK)
    assert not restarted.refresh_if_due(datetime(2026,10,25,8,tzinfo=CHINA))
    assert restarted.image_path('2026-10-25-2.jpg').read_bytes()==JPEG


def test_network_failure_retains_old_image_and_retry_backoff(tmp_path,monkeypatch):
    monkeypatch.setattr(backgrounds,'fetch_photo',lambda period,recent:photo(period+'-1'))
    library=Backgrounds(tmp_path,FALLBACK)
    start=datetime(2026,10,24,7,tzinfo=CHINA)
    assert library.refresh_if_due(start)
    broken=Mock(side_effect=OSError('网络不可用'))
    monkeypatch.setattr(backgrounds,'fetch_photo',broken)
    tomorrow=datetime(2026,10,25,6,tzinfo=CHINA)
    assert not library.refresh_if_due(tomorrow)
    assert not library.refresh_if_due(tomorrow+timedelta(minutes=9))
    assert broken.call_count==1
    assert library.catalog(tomorrow)['status']=='stale'
    assert library.image_path('2026-10-24-1.jpg').read_bytes()==JPEG
    restarted=Backgrounds(tmp_path,FALLBACK)
    assert not restarted.refresh_if_due(tomorrow+timedelta(minutes=9))
    monkeypatch.setattr(backgrounds,'fetch_photo',lambda period,recent:photo(period+'-2'))
    assert restarted.refresh_if_due(tomorrow+timedelta(minutes=10))
    assert restarted.catalog(tomorrow)['daily_id']=='2026-10-25-2'


def test_concurrent_refresh_only_fetches_once_and_reads_do_not_wait(tmp_path,monkeypatch):
    started,release=threading.Event(),threading.Event()
    def fetch(period,recent):
        started.set();assert release.wait(3);return photo(period+'-1')
    monkeypatch.setattr(backgrounds,'fetch_photo',fetch)
    library=Backgrounds(tmp_path,FALLBACK)
    at=datetime(2026,10,24,7,tzinfo=CHINA)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        first=pool.submit(library.refresh_if_due,at);assert started.wait(2)
        others=list(pool.map(lambda _:library.refresh_if_due(at),range(7)))
        assert others==[False]*7
        assert library.catalog(at)['status']=='fallback'
        release.set();assert first.result(timeout=3)


def test_history_bound_and_no_arbitrary_file_reads(tmp_path,monkeypatch):
    monkeypatch.setattr(backgrounds,'fetch_photo',lambda period,recent:photo(period+'-1'))
    library=Backgrounds(tmp_path,FALLBACK)
    start=datetime(2026,10,1,7,tzinfo=CHINA)
    for i in range(32):assert library.refresh_if_due(start+timedelta(days=i))
    assert len(list(tmp_path.glob('*.jpg')))==30
    assert library.image_path('2026-10-01-1.jpg') is None
    assert library.image_path('../../nav.db') is None
    assert library.image_path('index.json') is None
    assert len(json.loads((tmp_path/'index.json').read_text())['photos'])==30


@pytest.mark.parametrize('url',['http://picsum.photos/id/1','https://evil.example/x','https://picsum.photos@evil.example/x','https://picsum.photos:444/x','file:///etc/passwd'])
def test_image_source_allowlist(url):
    with pytest.raises(ValueError):trusted_url(url)


def test_remote_metadata_duplicate_rejection_and_jpeg_validation(monkeypatch):
    def remote(url,limit):
        if url.endswith('/info'):
            pid='1' if '-0/' in url else '2'
            return json.dumps({'id':pid,'author':'摄影者','url':'https://unsplash.com/photos/photo-'+pid, 'width':5000, 'height':3333}).encode()
        assert url=='https://picsum.photos/id/2/5000/3333.jpg' and limit==MAX_IMAGE
        return JPEG
    monkeypatch.setattr(backgrounds,'download',remote)
    saved,data=fetch_photo('2026-10-24',{'1'})
    assert saved['source_id']=='2' and data==JPEG
    def invalid(url,limit):
        return remote(url,limit) if url.endswith('/info') else b'<html>bad response</html>'
    monkeypatch.setattr(backgrounds,'download',invalid)
    with pytest.raises(ValueError):fetch_photo('2026-10-24',{'1'})


def test_background_api_requires_login_and_scheduler_runs_without_browser(config,monkeypatch):
    event=threading.Event()
    original=Backgrounds.refresh_if_due
    def refresh(self,at=None):
        result=original(self,at);event.set();return result
    monkeypatch.setattr(Backgrounds,'refresh_if_due',refresh)
    monkeypatch.setattr(backgrounds,'fetch_photo',lambda period,recent:photo(period+'-123'))
    app=create_app({**config,'NAV_BACKGROUND_ENABLED':'true'})
    with TestClient(app) as browser:
        assert event.wait(3),'后台任务必须无需打开网页即可执行'
        assert browser.get('/api/v1/backgrounds').status_code==401
        with TestClient(app,headers={'Authorization':'Bearer '+'t'*40}) as authorized:
            meta=authorized.get('/api/v1/backgrounds').json()['data']
            assert meta['status']=='ready'
            url=meta['photos'][0]['image']
            assert browser.get(url).status_code==401
            image=authorized.get(url)
            assert image.status_code==200 and image.content==JPEG
            assert image.headers['content-type']=='image/jpeg'
            assert authorized.get('/api/v1/backgrounds/2026-01-01-999.jpg').status_code==404


@pytest.mark.parametrize('value',['24:00','6:00','06:60','wrong'])
def test_schedule_configuration_validation(tmp_path,value):
    with pytest.raises(RuntimeError):Backgrounds(tmp_path,FALLBACK,value)


def test_jpeg_frame_size_and_bad_headers():
    assert backgrounds.jpeg_dimensions(JPEG)==(5000,3333)
    assert backgrounds.jpeg_dimensions(JPEG.replace(b'\xff\xc0',b'\xff\xc2'))==(5000,3333)
    for broken in [b'html', b'\xff\xd8\xff\xd9', JPEG[:-2], b'\xff\xd8\xff\xe0\xff\xff\xff\xd9']:
        with pytest.raises(ValueError):backgrounds.jpeg_dimensions(broken)


def test_small_and_portrait_sources_are_skipped_without_upscaling(monkeypatch):
    calls=[]
    sizes=[(1600,1000),(5000,6000),(5000,3333)]
    def remote(url,limit):
        if url.endswith('/info'):
            index=int(url.split('-')[-1].split('/')[0]);width,height=sizes[index]
            return json.dumps({'id':str(index),'author':'测试','url':'https://unsplash.com/photos/test','width':width,'height':height}).encode()
        calls.append(url);return JPEG
    monkeypatch.setattr(backgrounds,'download',remote)
    saved,_=fetch_photo('2026-10-24',set())
    assert saved['width']==5000 and saved['height']==3333
    assert calls==['https://picsum.photos/id/2/5000/3333.jpg']
    assert backgrounds.photo_size({'width':4000,'height':2670})==(4000,2670)
    assert backgrounds.photo_size({'width':6000,'height':4000})==(5000,3333)
    assert backgrounds.photo_size({}) is None
    assert backgrounds.photo_size({'width':8000,'height':2500}) is None


def test_returned_jpeg_must_match_native_size(monkeypatch):
    def remote(url,limit):
        if url.endswith('/info'):
            return json.dumps({'id':'2','author':'测试','url':'https://unsplash.com/photos/test','width':4000,'height':2670}).encode()
        return JPEG  # Actual 5000x3333 differs from advertised/requested 4000x2670.
    monkeypatch.setattr(backgrounds,'download',remote)
    with pytest.raises(ValueError,match='实际分辨率'):fetch_photo('2026-10-24',set())


def test_old_low_resolution_cache_upgrades_same_day_without_wait(tmp_path,monkeypatch):
    at=datetime(2026,10,24,7,tzinfo=CHINA)
    old,_=photo('2026-10-24-1');old.update(width=1600,height=1000,image='/api/v1/backgrounds/2026-10-24-1.jpg')
    (tmp_path/'2026-10-24-1.jpg').write_bytes(JPEG)
    (tmp_path/'index.json').write_text(json.dumps({'photos':[old],'last_attempt':at.timestamp(),'last_period':'2026-10-24','failed':False}))
    library=Backgrounds(tmp_path,FALLBACK)
    assert library.catalog(at)['status']=='fallback'
    assert not any(p['id']==old['id'] for p in library.catalog(at)['photos'])
    fetch=Mock(return_value=photo('2026-10-24-2'))
    monkeypatch.setattr(backgrounds,'fetch_photo',fetch)
    assert library.refresh_if_due(at)
    current=library.catalog(at)
    assert current['status']=='ready' and current['photos'][0]['width']==5000
    assert current['photos'][0]['image'].endswith('?v=2')
    restarted=Backgrounds(tmp_path,FALLBACK)
    assert not restarted.refresh_if_due(at+timedelta(minutes=1))
    assert fetch.call_count==1
