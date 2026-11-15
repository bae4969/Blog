"""분기 양 끝의 매칭 결과를 미리 계산한다. 화면 조작은 이 스냅샷 안에서만 처리한다."""
import asyncio
from array import array
from collections import defaultdict
import gzip
import hashlib
import json
import logging
import math
import shutil
from statistics import median
import time

from app.services import real_estate as source

log = logging.getLogger(__name__)
ROOT = source.CACHE_DIR / 'explorer-v1'
_task = None
_status = {'pending': True}


window_revision = source.window_revision


def snapshot_version(meta):
    return hashlib.sha256(json.dumps([source.public_metadata(meta), meta.get('revisions', {})], sort_keys=True).encode()).hexdigest()[:20]


def pair_index(first, last):
    # 열 우선 삼각 행렬: (0,1), (0,2), (1,2), ...
    return last * (last - 1) // 2 + first


def matched_pair(left, right, years, nodes):
    """법정동·단지·면적을 먼저 매칭하고, 원 조합별 연환산값을 부모까지 합친다."""
    values = defaultdict(list)
    for code, cells in left.items():
        prices = {(apt, area): amount for apt, area, amount in right.get(code, [])}
        rates = [((prices[(apt,area)] / amount) ** (1 / years) - 1) * 100
                 for apt,area,amount in cells if (apt,area) in prices]
        parent = code
        while parent:
            values[parent].extend(rates)
            parent = nodes.get(parent, {}).get('parent') or ('KR' if parent not in nodes else None)
    return {code: (median(v), len(v)) for code,v in values.items() if v}


def _read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def current_manifest():
    current = _read_json(ROOT / 'current.json')
    if current:
        return _read_json(ROOT / current['version'] / 'manifest.json')
    return None


async def cohort(window, meta):
    revision = window_revision(window,meta)
    folder = ROOT / 'cohorts'
    folder.mkdir(parents=True,exist_ok=True)
    path = folder / ('-'.join(map(str,window)) + '.json')
    cached = await asyncio.to_thread(_read_json,path)
    if cached and cached['revision'] == revision:
        return cached['regions'], revision
    # 같은 수집본으로 이미 검증한 단일 구간 캐시도 최초 이관 때 재사용한다.
    result = await source.endpoint_snapshot(window,meta,reuse=cached is None)
    def save():
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'revision':revision,'regions':result}, separators=(',',':')))
        temporary.replace(path)
    await asyncio.to_thread(save)
    return result, revision


def _matrix_arrays(folder, nodes, size, old_size):
    result = {}
    for code in nodes:
        rates, samples = array('d'), array('I')
        if folder and (folder / f'{code}.rates').exists():
            rates.frombytes((folder / f'{code}.rates').read_bytes())
            samples.frombytes((folder / f'{code}.samples').read_bytes())
        if len(rates) != old_size or old_size > size:
            rates, samples = array('d'),array('I')
        rates.extend([math.nan] * (size-len(rates)))
        samples.extend([0] * (size-len(samples)))
        result[code] = rates, samples
    return result


def _write_snapshot(folder, full, matrices, windows, revisions, version):
    nodes = source.geography()['nodes']
    centers = [sum(d.toordinal() for d in w)/2 for w in windows]
    summaries = full['map_summary']
    for code,(rates,samples) in matrices.items():
        (folder / f'{code}.rates').write_bytes(rates.tobytes())
        (folder / f'{code}.samples').write_bytes(samples.tobytes())
    # 현재 지도와 직계 하위 지역만 전송한다. 계산용 원 단지 표본은 공개하지 않는다.
    for region in nodes:
        codes = [region, *nodes[region]['children']]
        codes = [code for code in codes if code in full['regions']]
        matrices_json = {code: {'rates':[v if math.isfinite(v) else None for v in matrices[code][0]],
                                'samples':list(matrices[code][1])} for code in codes}
        bundle = dict(full, regions={code:full['regions'][code] for code in codes},
                      map_summary={code:summaries[code] for code in codes},
                      matrix={'version':version,'centers':centers,'regions':matrices_json})
        raw = json.dumps(bundle,ensure_ascii=False,separators=(',',':')).encode()
        (folder / f'{region}.json.gz').write_bytes(gzip.compress(raw,compresslevel=5,mtime=0))
    manifest = {'version':version,'periods':full['periods'],'revisions':revisions,'metadata':full['metadata']}
    (folder / 'manifest.json').write_text(json.dumps(manifest))
    temporary = ROOT / 'current.tmp'
    temporary.write_text(json.dumps({'version':version}))
    temporary.replace(ROOT / 'current.json')
    # 최신 두 개의 완성본만 보관한다. 불완성 작업 폴더는 완성본을 대체하지 않는다.
    generations = sorted([p for p in ROOT.iterdir() if p.is_dir() and (p/'manifest.json').exists()],key=lambda p:p.stat().st_mtime,reverse=True)
    for old in generations[2:]:
        shutil.rmtree(old)
    # 이동하는 최근 3개월 파일도 누적되지 않도록 현 스냅샷의 창만 남긴다.
    active = {'-'.join(map(str,w))+'.json' for w in windows}
    for old in (ROOT/'cohorts').glob('*.json'):
        if old.name not in active:
            old.unlink()


async def build(meta):
    global _status
    version = snapshot_version(meta)
    previous = current_manifest()
    if previous and previous['version'] == version:
        return
    began = time.monotonic()
    _status = {'pending':True,'phase':'history'}
    while True:
        full = await source.history('all')
        if not full.get('pending'):
            break
        await asyncio.sleep(1)
    # 수집 버전이 집계 도중 바뀌면 다음 순회에서 하나의 버전으로 다시 준비한다.
    if full['metadata']['updated_at'] != meta['updated_at']:
        return
    first,last = source.history_window('all',meta)
    windows = [(source.period_start(i,'quarter'),source.period_start(i+1,'quarter')) for i in range(first,last+1)]
    rolling = source.rolling_window(meta,last)
    if rolling:
        windows[-1] = rolling
    revisions = [window_revision(w,meta) for w in windows]
    old_revisions = previous['revisions'] if previous and previous['periods'][0] == full['periods'][0] else []
    old_size = len(old_revisions)*(len(old_revisions)-1)//2
    old_folder = ROOT / previous['version'] if old_revisions else None
    nodes = source.geography()['nodes']
    n = len(windows)
    matrices = await asyncio.to_thread(_matrix_arrays,old_folder,full['regions'],n*(n-1)//2,old_size)
    _status = {'pending':True,'phase':'cohorts','processed':0,'total':n}
    # 각 창의 원본은 한 번 읽어 디스크에 남긴다. 모든 원 거래를 RAM에 올리지 않는다.
    for i,w in enumerate(windows):
        await cohort(w,meta)
        _status['processed'] = i+1
    _status = {'pending':True,'phase':'matrix','processed':0,'total':n*(n-1)//2}
    computed = 0
    for j in range(1,n):
        right = None
        for i in range(j):
            idx = pair_index(i,j)
            if j < len(old_revisions) and old_revisions[i] == revisions[i] and old_revisions[j] == revisions[j]:
                _status['processed'] += 1
                continue
            if right is None:
                right,_ = await cohort(windows[j],meta)
            left,_ = await cohort(windows[i],meta)
            result = await asyncio.to_thread(matched_pair,left,right,source.comparison_years(windows[i],windows[j]),nodes)
            for code,(rates,samples) in matrices.items():
                rates[idx],samples[idx] = result.get(code,(math.nan,0))
            computed += 1
            _status['processed'] += 1
        await asyncio.sleep(0)
    folder = ROOT / version
    folder.mkdir(parents=True,exist_ok=True)
    await asyncio.to_thread(_write_snapshot,folder,full,matrices,windows,revisions,version)
    _status = {'pending':False}
    log.info('부동산 표시 구간 사전 계산 완료: %s %d개 조합 %.1fs',version,computed,time.monotonic()-began)


async def refresh_loop():
    global _status
    while True:
        try:
            await build(await source.metadata())
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception('부동산 사전 계산 실패 — 이전 완성본 유지')
            _status = {'pending':True,'error':'부동산 통계를 준비하지 못했습니다. 잠시 후 다시 시도해 주세요.'}
        await asyncio.sleep(300)


def start():
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(refresh_loop())
    return _task


async def explorer(region):
    if region not in source.geography()['nodes']:
        raise ValueError('존재하지 않는 지역입니다.')
    start()
    manifest = current_manifest()
    if not manifest:
        if _status.get('error'):
            raise RuntimeError(_status['error'])
        return dict(_status)
    folder = ROOT / manifest['version']
    return await asyncio.to_thread((folder / f'{region}.json.gz').read_bytes)
