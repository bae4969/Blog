"""Dart가 완성한 아파트 집계의 SELECT 어댑터. 원본 조회·계산·DB 쓰기는 하지 않는다."""
import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
import gzip
import json
import logging
from pathlib import Path
import time

from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError
from app.db.session import engine
from app.services.real_estate import geography, KST, MIN_CELLS, period_label

log = logging.getLogger(__name__)
CACHE_DIR = Path('/tmp/blog-real-estate-db-v1')
METHOD = 'sale-v1:month-daily-median:quarter-month-median:endpoint-unknown:adjacent-broker'
_active = None
_active_at = 0.0
_active_lock = asyncio.Lock()
_load_lock = asyncio.Lock()
_bundles = OrderedDict()

# 원본 manifest(약9MB)는 읽거나 응답에 복사하지 않는다.
ACTIVE_SQL = text("""SELECT s.snapshot_id,s.method_version,s.geography_version,s.collection_revision,
    s.as_of,s.completed_at,s.quarter_count,s.windows_json,
    JSON_VALUE(s.metadata_json,'$.source_updated_at') AS source_updated_at,
    JSON_VALUE(s.metadata_json,'$.matching_supported') AS matching_supported,
    JSON_VALUE(s.metadata_json,'$.geography_mapping_complete') AS geography_mapping_complete
    FROM N8N.re_agg_active a JOIN N8N.re_agg_snapshot s
      ON s.snapshot_id=a.snapshot_id AND s.asset_type=a.asset_type
    WHERE a.asset_type='apartment' AND a.status='ready' AND s.status='ready'""")
PERIOD_SQL = text("""SELECT region_code,quarter,rolling,trade_count,calendar_trade_count,
    complete,provisional,comparison_complete,payload_json
    FROM N8N.re_agg_period WHERE snapshot_id=:snapshot AND region_code IN :codes
    ORDER BY region_code,quarter""").bindparams(bindparam('codes',expanding=True))
COMPARISON_SQL = text("""SELECT region_code,first_quarter,last_quarter,years,annual_change,
    matched_samples,comparison_complete FROM N8N.re_agg_comparison
    WHERE snapshot_id=:snapshot AND region_code IN :codes""").bindparams(bindparam('codes',expanding=True))


@asynccontextmanager
async def snapshot_connection():
    async with engine.connect() as connection:
        try:
            # SESSION/GLOBAL 없이 다음 트랜잭션에만 적용해 공용 연결 기본값을 유지한다.
            await connection.exec_driver_sql('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            await connection.exec_driver_sql('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
            yield connection
        finally:
            await connection.rollback()


def _json(value):
    return json.loads(value) if isinstance(value,str) else value


def _kst(value):
    if not value:
        return None
    dt = datetime.fromisoformat(str(value))
    return dt.replace(tzinfo=KST).isoformat() if dt.tzinfo is None else dt.astimezone(KST).isoformat()


def normalize_snapshot(row):
    if row is None:
        raise RuntimeError('아파트 집계 완성본이 아직 준비되지 않았습니다.')
    if row['method_version'] != METHOD or str(row['matching_supported']).lower() not in ('true','1'):
        raise RuntimeError('집계 계산 기준이 변경되어 확인이 필요합니다.')
    if str(row['geography_mapping_complete']).lower() not in ('true','1'):
        raise RuntimeError('집계 지역과 지도 경계의 연결을 확인해야 합니다.')
    windows = _json(row['windows_json'])
    quarters = [w['quarter'] for w in windows]
    if len(quarters) != row['quarter_count'] or len(quarters)<2 or quarters != list(range(quarters[0],quarters[-1]+1)):
        raise RuntimeError('집계 기간이 완전하지 않습니다.')
    as_of = date.fromisoformat(str(row['as_of']))
    last_day = min(as_of,date.fromisoformat(windows[-1]['stop'])-timedelta(days=1))
    metadata = dict(snapshot_id=row['snapshot_id'],method_version=row['method_version'],
        geography_version=row['geography_version'],collection_revision=row['collection_revision'],
        first_month=windows[0]['start'][:7],last_month=last_day.strftime('%Y-%m'),
        updated_at=_kst(row['source_updated_at']),computed_at=_kst(row['completed_at']),
        as_of=as_of.isoformat(),as_of_month=as_of.strftime('%Y-%m'),
        boundary_date=geography()['boundary_date'],unmapped=[],min_samples=MIN_CELLS,
        matching_supported=True,geography_mapping_complete=True)
    return dict(snapshot_id=row['snapshot_id'],geography_version=row['geography_version'],
                windows=windows,metadata=metadata)


async def read_snapshot(connection):
    row = (await connection.execute(ACTIVE_SQL)).mappings().first()
    return normalize_snapshot(row)


def _last_snapshot():
    try:
        saved=json.loads((CACHE_DIR/'latest.json').read_text())
        if saved['metadata']['method_version'] == METHOD:
            return saved
    except (OSError,ValueError,KeyError):
        pass
    return None


async def active_snapshot():
    global _active,_active_at
    async with _active_lock:
        if _active and time.monotonic()-_active_at < 30:
            return _active
        try:
            async with snapshot_connection() as connection:
                result = await read_snapshot(connection)
        except SQLAlchemyError:
            result = _active or await asyncio.to_thread(_last_snapshot)
            if result is None:
                raise
            log.warning('부동산 DB 확인 실패 — 마지막 완성본 유지')
        _active,_active_at = result,time.monotonic()
        return result


async def metadata():
    return (await active_snapshot())['metadata']


def adapt_bundle(snapshot, codes, periods, comparisons):
    windows = snapshot['windows']
    first = windows[0]['quarter']
    n = len(windows)
    size = n*(n-1)//2
    series = {code:[None]*n for code in codes}
    matrices = {code:dict(rates=[None]*size,samples=[None]*size,complete=[False]*size) for code in codes}
    for row in periods:
        code,i = row['region_code'],row['quarter']-first
        if not 0<=i<n or series[code][i] is not None:
            raise RuntimeError('집계 기간 행이 올바르지 않습니다.')
        payload = _json(row['payload_json'])
        w = windows[i]
        series[code][i] = dict(period=period_label(row['quarter'],'quarter'),start=w['start'],stop=w['stop'],
            rolling=bool(row['rolling']),count=row['trade_count'],calendar_count=row['calendar_trade_count'],
            median=payload['median_price'],ppm=payload['median_ppm'],
            change=payload['adjacent_change'],samples=payload['adjacent_samples'],
            reliable=payload['adjacent_samples']>=MIN_CELLS,
            complete=bool(row['complete']),comparison_complete=bool(row['comparison_complete']),
            provisional=bool(row['provisional']),comparison_start=payload['comparison_start'],
            comparison_stop=payload['comparison_stop'],
            candle=dict(counts=payload['bucket_counts'],median=payload['price_ohlc'],ppm=payload['ppm_ohlc']))
    if any(any(point is None for point in points) for points in series.values()):
        raise RuntimeError('집계 기간 행이 누락되었습니다.')
    for row in comparisons:
        i,j = row['first_quarter']-first,row['last_quarter']-first
        if not 0<=i<j<n:
            raise RuntimeError('집계 비교 구간이 올바르지 않습니다.')
        idx = j*(j-1)//2+i
        cell = matrices[row['region_code']]
        if cell['samples'][idx] is not None:
            raise RuntimeError('집계 비교 행이 중복되었습니다.')
        cell['rates'][idx] = row['annual_change']
        cell['samples'][idx] = row['matched_samples']
        cell['complete'][idx] = bool(row['comparison_complete'])
    if any(None in cell['samples'] for cell in matrices.values()):
        raise RuntimeError('집계 비교 행이 누락되었습니다.')
    centers = [(date.fromisoformat(w['start']).toordinal()+date.fromisoformat(w['stop']).toordinal())/2 for w in windows]
    summaries = {}
    for code,points in series.items():
        cell = matrices[code];idx = (n-1)*(n-2)//2
        summaries[code] = dict(count=sum(p['calendar_count'] for p in points),change=cell['rates'][idx],
            samples=cell['samples'][idx],reliable=cell['samples'][idx]>=MIN_CELLS,
            complete=all(p['complete'] for p in points),comparison_complete=cell['complete'][idx],
            provisional=any(p['provisional'] for p in points))
    return dict(unit='quarter',span='all',count=n,end=period_label(windows[-1]['quarter'],'quarter'),
        periods=[period_label(w['quarter'],'quarter') for w in windows],regions=series,map_summary=summaries,
        map_method='endpoint_matched_cagr',map_dealing_filter='exclude_direct_include_unknown',
        map_years=(centers[-1]-centers[0])/365.2425,
        matrix=dict(version=snapshot['snapshot_id'],centers=centers,regions=matrices),metadata=snapshot['metadata'])


async def load_bundle(region):
    async with snapshot_connection() as connection:
        snapshot = await read_snapshot(connection)
        scope = (await connection.execute(text("""SELECT region_code,parent_code,leaf_codes_json
            FROM N8N.re_agg_region WHERE asset_type='apartment' AND geography_version=:geography
            AND (region_code=:region OR parent_code=:region)"""),
            dict(geography=snapshot['geography_version'],region=region))).mappings().all()
        nodes=geography()['nodes']
        codes=[region,*nodes[region]['children']]
        if set(codes) != {r['region_code'] for r in scope} or any(
            sorted(_json(r['leaf_codes_json'])) != sorted(nodes[r['region_code']]['codes'])
            or r['parent_code'] != nodes[r['region_code']]['parent'] for r in scope):
            raise RuntimeError('집계 지역과 지도 경계가 일치하지 않습니다.')
        params=dict(snapshot=snapshot['snapshot_id'],codes=codes)
        periods=(await connection.execute(PERIOD_SQL,params)).mappings().all()
        comparisons=(await connection.execute(COMPARISON_SQL,params)).mappings().all()
    # DB 읽기는 끝낸 뒤 압축한다. 응답 전체를 한 번에 교체한다.
    payload = await asyncio.to_thread(adapt_bundle,snapshot,codes,periods,comparisons)
    body = await asyncio.to_thread(lambda:gzip.compress(json.dumps(payload,ensure_ascii=False,
        separators=(',',':'),allow_nan=False).encode(),compresslevel=5,mtime=0))
    return snapshot,body


def _cache_path(snapshot_id,region):
    return CACHE_DIR/f'{snapshot_id}_{region}.json.gz'


def _remember(key,body):
    _bundles[key]=body
    _bundles.move_to_end(key)
    while len(_bundles)>16:
        _bundles.popitem(last=False)


def _read_bundle(key):
    if key in _bundles:
        _bundles.move_to_end(key)
        return _bundles[key]
    try:
        return _cache_path(*key).read_bytes()
    except FileNotFoundError:
        return None


def _save_bundle(snapshot,region,body):
    CACHE_DIR.mkdir(parents=True,exist_ok=True,mode=0o700)
    path=_cache_path(snapshot['snapshot_id'],region)
    temporary=path.with_suffix('.tmp')
    temporary.write_bytes(body);temporary.replace(path)
    latest=CACHE_DIR/'latest.json';temporary=latest.with_suffix('.tmp')
    temporary.write_text(json.dumps(snapshot,ensure_ascii=False));temporary.replace(latest)
    # 응답 캐시는 다시 만들 수 있다. 원본과 DB 완성본은 변경하지 않는다.
    for old in sorted(CACHE_DIR.glob('*.json.gz'),key=lambda p:p.stat().st_mtime,reverse=True)[64:]:
        old.unlink(missing_ok=True)


async def explorer(region):
    global _active,_active_at
    if region not in geography()['nodes']:
        raise ValueError('존재하지 않는 지역입니다.')
    snapshot=await active_snapshot()
    key=(snapshot['snapshot_id'],region)
    async with _load_lock:
        cached=await asyncio.to_thread(_read_bundle,key)
        if cached is not None:
            _remember(key,cached)
            return cached
        snapshot,body=await load_bundle(region)
        _active,_active_at=snapshot,time.monotonic()
        await asyncio.to_thread(_save_bundle,snapshot,region,body)
        _remember((snapshot['snapshot_id'],region),body)
        return body
