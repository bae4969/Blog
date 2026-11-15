"""완성 세대 SELECT 변환·캐시·실패 처리. 원본 DB와 운영 집계에는 쓰지 않는다."""
import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import date,datetime
import gzip
import json

import pytest
from sqlalchemy.exc import OperationalError
from app.services import real_estate_db as db


@pytest.fixture
def raw_snapshot():
    return dict(snapshot_id='a'*64,method_version=db.METHOD,geography_version='g',collection_revision='r',
        as_of=date(2026,11,15),completed_at=datetime(2026,11,15,19),quarter_count=3,
        source_updated_at='2026-11-14T02:30:05',matching_supported='true',geography_mapping_complete='true',
        windows_json=json.dumps([
            dict(quarter=8105,start='2026-04-01',stop='2026-07-01'),
            dict(quarter=8106,start='2026-07-01',stop='2026-10-01'),
            dict(quarter=8107,start='2026-08-15',stop='2026-11-15')]))


@pytest.fixture
def records(raw_snapshot):
    snapshot=db.normalize_snapshot(raw_snapshot)
    periods=[]
    for code in ['KR','11']:
        for i in range(3):
            payload=dict(median_price=100+i,median_ppm=2+i,adjacent_change=None,adjacent_samples=0,
                comparison_start='2026-01-01',comparison_stop='2026-04-01',bucket_counts=[1,2,3],
                price_ohlc=dict(o=100,h=110,l=90,c=105),ppm_ohlc=dict(o=2,h=3,l=1,c=2))
            periods.append(dict(region_code=code,quarter=8105+i,rolling=int(i==2),trade_count=[10,20,25][i],
                calendar_trade_count=[10,20,5][i],complete=1,provisional=int(i==2),comparison_complete=0,
                payload_json=json.dumps(payload)))
    comparisons=[dict(region_code=c,first_quarter=i,last_quarter=j,years=1,annual_change=rate,
                matched_samples=samples,comparison_complete=complete)
        for c in ['KR','11'] for i,j,rate,samples,complete in
        [(8106,8107,None,0,1),(8105,8107,0.0,7,1),(8105,8106,-1.5,3,0)]]
    return snapshot,periods,comparisons


def test_adapter_preserves_count_units_zero_null_and_comparison_flags(records):
    snapshot,periods,comparisons=records
    body=db.adapt_bundle(snapshot,['KR','11'],periods,comparisons)
    assert body['map_summary']['11']['count']==35  # rolling25를 중복 더하면55
    assert body['regions']['11'][-1]['count']==25
    assert body['regions']['11'][-1]['calendar_count']==5
    assert body['regions']['11'][-1]['median']==102
    assert body['regions']['11'][-1]['candle']['counts']==[1,2,3]
    assert body['matrix']['regions']['11']==dict(rates=[-1.5,0.0,None],samples=[3,7,0],complete=[False,True,True])
    assert body['map_summary']['11']['change']==0 and body['map_summary']['11']['reliable']
    assert body['regions']['11'][-1]['comparison_complete'] is False
    assert body['map_summary']['11']['comparison_complete'] is True  # 인접 비교와 끝점 비교를 혼용하지 않는다.
    assert body['metadata']['updated_at'].endswith('+09:00')
    assert 'sources' not in body['metadata'] and 'manifest' not in json.dumps(body)


def test_incomplete_or_duplicate_generation_is_not_exposed(records):
    snapshot,periods,comparisons=records
    with pytest.raises(RuntimeError,match='기간 행이 누락'):
        db.adapt_bundle(snapshot,['KR','11'],periods[:-1],comparisons)
    with pytest.raises(RuntimeError,match='비교 행이 누락'):
        db.adapt_bundle(snapshot,['KR','11'],periods,comparisons[:-1])
    with pytest.raises(RuntimeError,match='중복'):
        db.adapt_bundle(snapshot,['KR','11'],periods,comparisons+[comparisons[0]])


def test_unready_unsupported_or_broken_snapshot_rejected(raw_snapshot):
    with pytest.raises(RuntimeError,match='아직 준비'):
        db.normalize_snapshot(None)
    for key,value in [('method_version','new-unknown'),('matching_supported','false'),
                      ('geography_mapping_complete','false'),('quarter_count',4)]:
        with pytest.raises(RuntimeError):
            db.normalize_snapshot(dict(raw_snapshot,**{key:value}))


@pytest.mark.asyncio
async def test_consistent_read_is_next_transaction_only_and_always_rolls_back(monkeypatch):
    statements=[]
    class Connection:
        async def exec_driver_sql(self,sql):statements.append(sql)
        async def rollback(self):statements.append('ROLLBACK')
    class Engine:
        @asynccontextmanager
        async def connect(self):yield Connection()
    monkeypatch.setattr(db,'engine',Engine())
    with pytest.raises(ValueError):
        async with db.snapshot_connection():raise ValueError('읽기 중 실패')
    assert statements==['SET TRANSACTION ISOLATION LEVEL REPEATABLE READ',
                        'START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY','ROLLBACK']
    assert not any('SESSION' in s or 'GLOBAL' in s for s in statements)


@pytest.fixture
def empty_cache(monkeypatch,tmp_path):
    monkeypatch.setattr(db,'CACHE_DIR',tmp_path)
    monkeypatch.setattr(db,'_active',None)
    monkeypatch.setattr(db,'_active_at',0.0)
    monkeypatch.setattr(db,'_bundles',OrderedDict())
    monkeypatch.setattr(db,'_active_lock',asyncio.Lock())
    monkeypatch.setattr(db,'_load_lock',asyncio.Lock())
    return tmp_path


@pytest.mark.asyncio
async def test_concurrent_cold_requests_single_load_and_restart_disk_reuse(monkeypatch,empty_cache,records):
    snapshot,_,_=records
    calls=[]
    async def active():return snapshot
    async def load(region):
        calls.append(region)
        await asyncio.sleep(.01)
        return snapshot,b'compressed-complete'
    monkeypatch.setattr(db,'active_snapshot',active)
    monkeypatch.setattr(db,'load_bundle',load)
    results=await asyncio.gather(*(db.explorer('KR') for _ in range(4)))
    assert calls==['KR'] and results==[b'compressed-complete']*4
    db._bundles.clear()
    assert await db.explorer('KR')==b'compressed-complete' and calls==['KR']
    assert db._last_snapshot()==snapshot


@pytest.mark.asyncio
async def test_generation_switch_is_atomic_and_failed_new_load_keeps_old(monkeypatch,empty_cache,records):
    snapshot,_,_=records
    new=dict(snapshot,snapshot_id='b'*64,metadata=dict(snapshot['metadata'],snapshot_id='b'*64))
    latest=snapshot
    async def active():return latest
    async def load(region):return latest,latest['snapshot_id'].encode()
    monkeypatch.setattr(db,'active_snapshot',active)
    monkeypatch.setattr(db,'load_bundle',load)
    assert await db.explorer('KR')==b'a'*64
    latest=new
    async def fail(region):raise OperationalError('SELECT',{},Exception('offline'))
    monkeypatch.setattr(db,'load_bundle',fail)
    with pytest.raises(OperationalError):await db.explorer('KR')
    assert db._last_snapshot()['snapshot_id']==snapshot['snapshot_id']
    assert db._read_bundle((snapshot['snapshot_id'],'KR'))==b'a'*64
    monkeypatch.setattr(db,'load_bundle',load)
    assert await db.explorer('KR')==b'b'*64
    assert db._last_snapshot()['snapshot_id']==new['snapshot_id']


@pytest.mark.asyncio
async def test_db_failure_keeps_last_complete_but_never_starts_raw_calculation(monkeypatch,empty_cache,records):
    snapshot,_,_=records
    @asynccontextmanager
    async def offline():
        raise OperationalError('SELECT',{},Exception('offline'))
        yield
    monkeypatch.setattr(db,'snapshot_connection',offline)
    with pytest.raises(OperationalError):await db.active_snapshot()
    db._save_bundle(snapshot,'KR',b'last-good')
    assert await db.explorer('KR')==b'last-good'
    assert (await db.metadata())['snapshot_id']==snapshot['snapshot_id']


@pytest.mark.asyncio
async def test_adapter_reads_ready_and_all_region_tables_in_one_connection(monkeypatch,records):
    snapshot,periods,comparisons=records
    events=[]
    class Result:
        def __init__(self,rows):self.rows=rows
        def mappings(self):return self
        def all(self):return self.rows
    class Connection:
        async def execute(self,statement,params):
            sql=str(statement);events.append(sql)
            assert params.get('snapshot',snapshot['snapshot_id'])==snapshot['snapshot_id']
            if 're_agg_region' in sql:
                return Result([dict(region_code='KR',parent_code=None,leaf_codes_json='["11"]'),
                               dict(region_code='11',parent_code='KR',leaf_codes_json='["11"]')])
            return Result(periods if 're_agg_period' in sql else comparisons)
    @asynccontextmanager
    async def connection():
        events.append('OPEN');yield Connection();events.append('CLOSE')
    async def read(c):events.append('ACTIVE');return snapshot
    monkeypatch.setattr(db,'snapshot_connection',connection)
    monkeypatch.setattr(db,'read_snapshot',read)
    monkeypatch.setattr(db,'geography',lambda:{'nodes':{'KR':{'parent':None,'children':['11'],'codes':['11']},
                                                        '11':{'parent':'KR','children':[],'codes':['11']}}})
    actual,body=await db.load_bundle('KR')
    assert actual==snapshot
    assert events[0:2]==['OPEN','ACTIVE'] and events[-1]=='CLOSE'
    assert len(events)==6
    assert json.loads(gzip.decompress(body))['matrix']['version']==snapshot['snapshot_id']
    assert all('rtms_' not in q and 'cohort' not in q and 'INSERT' not in q for q in events)
