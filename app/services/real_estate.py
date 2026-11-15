"""아파트 실거래 분석. 원본은 SELECT만, 집계는 프로세스별 한 작업 + 유한 캐시.

기간 차트는 인접 분기마다 단지·면적을 매칭한다. 기존 통계 API는 고정 표본을 유지한다.
상위 지역은 하위 변화율을 평균하지 않고 원 표본의 변화율을 합쳐 중앙값을 낸다.
"""
import asyncio
import calendar
from array import array
from collections import OrderedDict, defaultdict
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
import json
import hashlib
import logging
from pathlib import Path
from statistics import median
import time

from sqlalchemy import text
from app.db.session import db_session

log = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))
MAP_DIR = Path(__file__).resolve().parents[2] / 'public/maps/real-estate'
CACHE_DIR = Path('/tmp/blog-real-estate-v2')
MIN_CELLS = 5  # 통계적 유의성 기준이 아닌, 극소 표본의 색칠·순위 노출 방지선
_cache = OrderedDict()
_jobs = {}
_build_lock = asyncio.Lock()
_meta = None
_meta_at = 0.0
_meta_lock = asyncio.Lock()
_cohort_lock = asyncio.Lock()


@lru_cache(maxsize=1)
def geography():
    return json.loads((MAP_DIR / 'regions.json').read_text())


def period_index(day: date, unit: str) -> int:
    if unit == 'month':
        return day.year * 12 + day.month - 1
    if unit == 'quarter':
        return day.year * 4 + (day.month - 1) // 3
    return day.year


def period_start(index: int, unit: str) -> date:
    n = {'month': 12, 'quarter': 4, 'year': 1}[unit]
    return date(index // n, (index % n) * (12 // n) + 1, 1)


def period_label(index: int, unit: str) -> str:
    d = period_start(index, unit)
    if unit == 'month':
        return f'{d.year}-{d.month:02d}'
    if unit == 'quarter':
        return f'{d.year} Q{(d.month - 1) // 3 + 1}'
    return str(d.year)


def window(unit, end, count, comparison):
    last = period_index(date.fromisoformat(end + '-01'), unit)
    lag = {'month': 12, 'quarter': 4, 'year': 1}[unit] if comparison == 'year' else 1
    display = list(range(last - count + 1, last + 1))
    required = sorted(set(display + [p - lag for p in display]))
    return display, required, lag


def summarize(amounts, ppms, ratios, cells, counts):
    return [dict(count=counts[i], median=median(a) if a else None,
                 ppm=median(ppms[i]) if ppms[i] else None,
                 change=median(ratios[i]) if ratios[i] else None,
                 samples=cells[i] if isinstance(cells, list) else cells,
                 reliable=(cells[i] if isinstance(cells, list) else cells) >= MIN_CELLS)
            for i, a in enumerate(amounts)]


def analyze_rows(rows, unit, display, required, lag, paired=False, date_windows=None):
    """지역 하나의 원본 → 가격·거래량·고정 표본 변화율. 테스트도 이 경계를 검증한다."""
    position = {p: i for i, p in enumerate(display)}
    amounts = [array('d') for _ in display]
    ppms = [array('d') for _ in display]
    cells = defaultdict(lambda: defaultdict(list))
    for dt, amount, area, apt, dealing in rows:
        p = (next((p for p,(a,b) in date_windows.items() if a <= dt < b), None)
             if date_windows else period_index(dt, unit))
        if p not in required:
            continue
        amount, area = float(amount), float(area)
        if p in position:
            i = position[p]
            amounts[i].append(amount)
            ppms[i].append(amount / area)
        if apt and dealing == '중개거래':
            cells[(apt, str(area))][p].append(amount)
    minimum = 1 if unit == 'month' else 2
    ratios = [array('d') for _ in display]
    samples = [0] * len(display) if paired else 0
    for prices in cells.values():
        if not paired and any(len(prices.get(p, ())) < minimum for p in required):
            continue
        if not paired:
            samples += 1
        medians = {p: median(v) for p, v in prices.items() if len(v) >= minimum}
        for i, p in enumerate(display):
            if p not in medians or p - lag not in medians:
                continue
            if paired:
                samples[i] += 1
            ratios[i].append((medians[p] / medians[p - lag] - 1) * 100)
    return amounts, ppms, ratios, samples


def candle_boundaries(display, date_windows=None):
    """분기 또는 최근 3개월을 겹치지 않는 세 월 구간으로 나눈다."""
    return {p: ([date_windows[p][0], months_before(date_windows[p][1], 2),
                 months_before(date_windows[p][1], 1), date_windows[p][1]] if date_windows else
                [period_start(p * 3 + i, 'month') for i in range(4)]) for p in display}


def candle_buckets(rows, boundaries):
    buckets = [[(array('d'), array('d')) for _ in range(3)] for _ in boundaries]
    # 일반 분기는 날짜에서 바로 찾고, 최근 3개월은 한 개의 비교 창만 확인한다.
    positions = {p: i for i, p in enumerate(boundaries)}
    for dt, amount, area, _apt, _dealing in rows:
        p = period_index(dt, 'quarter')
        candidates = [p] if p in boundaries else []
        if len(boundaries) == 1:
            candidates = boundaries
        for p in candidates:
            cuts = boundaries[p]
            for j, (start, stop) in enumerate(zip(cuts, cuts[1:])):
                if start <= dt < stop:
                    amounts, ppms = buckets[positions[p]][j]
                    amounts.append(float(amount))
                    ppms.append(float(amount) / float(area))
                    break
    return buckets


def summarize_candles(buckets):
    result = []
    for months in buckets:
        item = {'counts': [len(a) for a, _ in months]}
        for metric, column in [('median', 0), ('ppm', 1)]:
            values = [median(pair[column]) if pair[column] else None for pair in months]
            # 중간 월이 비어도 보간하거나 다른 월을 시가·종가로 대체하지 않는다.
            item[metric] = (dict(o=values[0], h=max(values), l=min(values), c=values[-1])
                            if all(v is not None for v in values) else None)
        result.append(item)
    return result


async def metadata():
    global _meta, _meta_at
    async with _meta_lock:
        if _meta is not None and time.monotonic() - _meta_at < 300:
            return _meta
        async with db_session() as db:
            regions = (await db.execute(text('SELECT lawd_cd, name FROM N8N.rtms_sgg ORDER BY lawd_cd'))).all()
            fills = (await db.execute(text("SELECT lawd_cd, ym, COUNT(*) AS pages, "
                "SUM(status='done') AS done, MAX(CASE WHEN status='done' THEN updated_at END) AS updated "
                "FROM N8N.rtms_fill WHERE kind='매매' GROUP BY lawd_cd,ym"))).all()
        codes = {str(r[0]) for r in regions}
        geo = geography()
        mapped = set(geo['nodes']['KR']['codes'])
        coverage = defaultdict(set)
        incomplete = defaultdict(set)
        updated = None
        revisions = defaultdict(list)
        for code, ym, pages, done, stamp in fills:
            revisions[str(ym)].append([str(code), pages, int(done or 0), stamp.isoformat() if stamp else None])
            if pages == done:
                coverage[str(ym)].add(str(code))
            else:
                incomplete[str(ym)].add(str(code))
            if stamp and (updated is None or stamp > updated):
                updated = stamp
        months = sorted(coverage.keys() | incomplete.keys())
        if not months:
            raise ValueError('수집된 기간이 없습니다.')
        _meta = dict(regions={str(r[0]): r[1] for r in regions},
            first_month=months[0][:4] + '-' + months[0][4:],
            last_month=months[-1][:4] + '-' + months[-1][4:],
            updated_at=updated.isoformat() if updated else None,
            unmapped=sorted(codes - mapped),
            revisions={m: hashlib.sha256(json.dumps(sorted(v)).encode()).hexdigest() for m,v in revisions.items()},
            coverage={m: sorted(v) for m, v in coverage.items()},
            incomplete={m: sorted(v) for m, v in incomplete.items()})
        _meta_at = time.monotonic()
        return _meta


def collection_revision(meta):
    return hashlib.sha256(json.dumps(meta.get('revisions', {}),sort_keys=True).encode()).hexdigest()


def window_revision(window, meta):
    start, stop = window
    first = period_index(start, 'month')
    last = period_index(stop, 'month') + (stop.day > 1)
    revisions = meta.get('revisions', {})
    parts = [revisions.get(f'{period_start(i,"month"):%Y%m}') if 'revisions' in meta else meta['updated_at']
             for i in range(first,last)]
    return hashlib.sha256(json.dumps([sorted(meta['regions']), *map(str,window), parts]).encode()).hexdigest()


def _window_cached(key, meta, start, stop):
    path = CACHE_DIR / (key + '.json')
    try:
        saved = json.loads(path.read_text())
        revision = window_revision((start,stop),meta)
        valid = saved.get('window_revision') == revision
        # 최초 이관은 동일 수집본에서 만든 결과만 허용한다.
        if not saved.get('window_revision'):
            valid = saved['updated_at'] == meta['updated_at']
        if valid and saved['payload']['metadata'].get('as_of_month') == datetime.now(KST).strftime('%Y-%m'):
            if not saved.get('window_revision'):
                saved['window_revision'] = revision
                temporary = path.with_suffix('.tmp')
                temporary.write_text(json.dumps(saved,ensure_ascii=False))
                temporary.replace(path)
            return saved['payload']
    except (OSError,ValueError,KeyError):
        pass
    return None


def public_metadata(meta):
    today = datetime.now(KST).date()
    last = min(date.fromisoformat(meta['last_month'] + '-01'), today)
    default = period_start(period_index(last, 'quarter') - 1, 'quarter')
    return dict(collection_revision=collection_revision(meta), first_month=meta['first_month'], last_month=meta['last_month'],
                default_end=default.strftime('%Y-%m'), updated_at=meta['updated_at'],
                boundary_date=geography()['boundary_date'], unmapped=meta['unmapped'],
                min_samples=MIN_CELLS, as_of_month=today.strftime('%Y-%m'))


def _collection_complete(meta, codes, start, stop):
    p = period_index(start, 'month'); end = period_index(stop, 'month') + (stop.day > 1)
    return all(set(codes) <= set(meta['coverage'].get(f'{period_start(m,"month"):%Y%m}', []))
               for m in range(p, end))


def prune_cache():
    # 이동 구간 캐시가 전체 이력·연도 조각을 밀어내지 않도록 각각 상한을 둔다.
    groups = {'full': [], 'range': [], 'aggregate': [], 'cohort': []}
    for path in CACHE_DIR.glob('*.json'):
        group = ('cohort' if path.name.startswith('cohort-v1-') else
                 'full' if path.name.startswith('history-quarter-') and '-all-' in path.name else
                 'range' if path.name.startswith('history-') else 'aggregate')
        groups[group].append(path)
    for group, limit in [('full', 2), ('range', 16), ('aggregate', 32), ('cohort', 128)]:
        for old in sorted(groups[group], key=lambda p: p.stat().st_mtime, reverse=True)[limit:]:
            old.unlink(missing_ok=True)


def slice_history(full, first, last, source_first):
    start, stop = first-source_first, last-source_first+1
    periods = full['periods'][start:stop]
    regions = {code: points[start:stop] for code, points in full['regions'].items()}
    counts = {}
    for code, points in regions.items():
        counts[code] = sum(p['count'] for p in points)
        if points and points[-1].get('rolling'):
            all_points = full['regions'][code]
            # 마지막 봉은 최근 3개월이지만 누적 거래량은 달력 분기만 한 번씩 센다.
            calendar_last = full['map_summary'][code]['count'] - sum(p['count'] for p in all_points[:-1])
            counts[code] += calendar_last - points[-1]['count']
    return regions, periods, counts


async def _build(key, unit, end, count, comparison, meta, paired=False, progress_key=None, date_windows=None):
    async with _build_lock:
        started = time.monotonic()
        display, required, lag = window(unit, end, count, comparison)
        begin, stop = period_start(min(required), unit), period_start(max(required) + 1, unit)
        if date_windows:
            begin = min(a for a,b in date_windows.values())
            stop = max(b for a,b in date_windows.values())
        nodes = geography()['nodes']
        accum = {}
        result = {}
        boundaries = candle_boundaries(display, date_windows) if paired and unit == 'quarter' else None
        candle_accum = {}
        for code in meta['regions']:
            # 법정동 코드와 날짜의 복합 인덱스로 지역 하나씩 조회. 원본·수집 상태는 변경하지 않는다.
            async with db_session() as db:
                rows = (await db.execute(text(
                    "SET STATEMENT max_statement_time=25 FOR SELECT deal_date,amount,exclu_ar,apt_seq,dealing_gbn "
                    "FROM N8N.rtms_trade WHERE lawd_cd=:code AND deal_date>=:begin AND deal_date<:stop "
                    "AND kind='매매' AND cdeal_type='' AND cdeal_day='' AND amount>0 AND exclu_ar>0"),
                    dict(code=code, begin=begin, stop=stop))).all()
            amounts, ppms, ratios, samples = await asyncio.to_thread(analyze_rows, rows, unit, display, required, lag, paired, date_windows)
            buckets = await asyncio.to_thread(candle_buckets, rows, boundaries) if boundaries else None
            del rows
            result[code] = summarize(amounts, ppms, ratios, samples, [len(a) for a in amounts])
            if buckets is not None:
                for point, candle in zip(result[code], summarize_candles(buckets)):
                    point['candle'] = candle
            parent = nodes.get(code, {}).get('parent') or 'KR'
            while parent:
                if parent not in accum:
                    accum[parent] = ([array('d') for _ in display], [array('d') for _ in display],
                                     [array('d') for _ in display], [0] * len(display) if paired else 0)
                aa, ap, ar, ns = accum[parent]
                for i in range(len(display)):
                    aa[i].extend(amounts[i]); ap[i].extend(ppms[i]); ar[i].extend(ratios[i])
                accum[parent] = aa, ap, ar, [a+b for a,b in zip(ns,samples)] if paired else ns + samples
                if buckets is not None:
                    if parent not in candle_accum:
                        candle_accum[parent] = [[(array('d'), array('d')) for _ in range(3)] for _ in display]
                    for target, source in zip(candle_accum[parent], buckets):
                        for (ta, tp), (sa, sp) in zip(target, source):
                            ta.extend(sa); tp.extend(sp)
                parent = nodes[parent]['parent']
            _jobs[progress_key or key]['processed'] += 1
            await asyncio.sleep(0)  # 화면/API 요청에 실행권을 돌려준다.
        for code, (amounts, ppms, ratios, samples) in accum.items():
            result[code] = await asyncio.to_thread(summarize, amounts, ppms, ratios, samples, [len(a) for a in amounts])
        for code, buckets in candle_accum.items():
            for point, candle in zip(result[code], await asyncio.to_thread(summarize_candles, buckets)):
                point['candle'] = candle
        today = datetime.now(KST).date()
        for code, series in result.items():
            codes = nodes[code]['codes'] if code in nodes else [code]
            comparison_complete = all(_collection_complete(meta, codes, period_start(p, unit),
                min(period_start(p + 1, unit), period_start(period_index(today, 'month') + 1, 'month')))
                for p in required)
            for p, point in zip(display, series):
                a, b = period_start(p, unit), period_start(p + 1, unit)
                if date_windows:
                    a,b = date_windows[p]
                    point['rolling'] = True
                    point['stop'] = b.isoformat()
                    point['comparison_start'] = date_windows[p-1][0].isoformat()
                    point['comparison_stop'] = a.isoformat()
                point['period'] = period_label(p, unit)
                point['start'] = a.isoformat()
                # 최소 1개월의 신고 여유를 둬도 확정값이라는 뜻은 아니다.
                point['provisional'] = bool(date_windows) or b > period_start(period_index(today, 'month') - 1, 'month')
                # 진행 중인 분기·연도의 미래 월은 수집 누락이 아니다.
                observed_stop = min(b, period_start(period_index(today, 'month') + 1, 'month'))
                point['complete'] = _collection_complete(meta, codes, a, observed_stop)
                reference_start = date_windows[p-1][0] if date_windows else period_start(p-1, unit)
                point['comparison_complete'] = (_collection_complete(meta, codes, reference_start, observed_stop) if paired else comparison_complete)
        payload = dict(unit=unit, end=end, comparison=comparison, count=count,
            periods=[period_label(p, unit) for p in display], regions=result,
            required_periods=[period_label(p, unit) for p in required],
            minimum_trades=1 if unit == 'month' else 2, method=f'adjacent_{unit}' if paired else 'fixed', metadata=public_metadata(meta))
        CACHE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        file = CACHE_DIR / (key + '.json')
        temporary = file.with_suffix('.tmp')
        temporary.write_text(json.dumps({'updated_at': meta['updated_at'], 'window_revision': window_revision((begin,stop),meta), 'payload': payload}, ensure_ascii=False))
        temporary.replace(file)
        # 재시작 사이에도 디스크 캐시를 무한히 쌓지 않는다.
        prune_cache()
        # 연도 조각은 디스크로 재사용하고, 화면 응답 캐시를 밀어내지 않는다.
        if not paired:
            _cache[key] = (meta['updated_at'], payload)
            _cache.move_to_end(key)
            while len(_cache) > 8:
                _cache.popitem(last=False)
        log.info('부동산 집계 완료: %s %.1fs', key, time.monotonic() - started)


async def _run(key, *args):
    try:
        await _build(key, *args)
    except Exception:
        log.exception('부동산 집계 실패: %s', key)
        _jobs[key]['error'] = '데이터 집계에 실패했습니다. 잠시 후 다시 시도해 주세요.'
        _jobs[key]['failed_at'] = time.monotonic()
    finally:
        _jobs[key]['task'] = None


async def snapshot(unit, end, count, comparison):
    meta = await metadata()
    display, required, lag = window(unit, end, count, comparison)
    if period_start(min(required), unit) < date(2006, 1, 1):
        raise ValueError('비교 기준 기간은 2006년 이후여야 합니다.')
    if end > meta['last_month'] or end > datetime.now(KST).strftime('%Y-%m'):
        raise ValueError('수집되지 않은 미래 기간입니다.')
    key = f'{unit}-{end}-{count}-{comparison}'
    if key in _cache and _cache[key][0] == meta['updated_at']:
        _cache.move_to_end(key)
        return _cache[key][1]
    path = CACHE_DIR / (key + '.json')
    if path.exists() and key not in _cache:
        try:
            saved = json.loads(path.read_text())
            if saved['updated_at'] == meta['updated_at']:
                _cache[key] = (saved['updated_at'], saved['payload'])
                while len(_cache) > 8:
                    _cache.popitem(last=False)
                return saved['payload']
        except (OSError, ValueError, KeyError):
            pass
    job = _jobs.get(key)
    if job and job.get('error'):
        if time.monotonic() - job['failed_at'] < 60:
            raise RuntimeError(job['error'])
        del _jobs[key]
        job = None
    if not job or not job['task']:
        if any(j['task'] for j in _jobs.values()):
            return {'pending': True, 'queued': True}
        # 완료 작업은 캐시에 있으므로 상태 사전도 한 항목만 유지한다.
        _jobs.clear()
        _jobs[key] = {'processed': 0, 'task': None}
        _jobs[key]['task'] = asyncio.create_task(_run(key, unit, end, count, comparison, meta))
    return {'pending': True, 'processed': _jobs[key]['processed'], 'total': len(meta['regions'])}


# 장기 자료도 1년씩 집계해 원본 거래 전체를 메모리에 쌓지 않는다.
def _history_cached(key, watermark):
    if (key in _cache and _cache[key][0] == watermark
            and _cache[key][1]['metadata'].get('as_of_month') == datetime.now(KST).strftime('%Y-%m')):
        _cache.move_to_end(key)
        return _cache[key][1]
    path = CACHE_DIR / (key + '.json')
    if path.exists():
        try:
            saved = json.loads(path.read_text())
            if (saved['updated_at'] == watermark
                    and saved['payload']['metadata'].get('as_of_month') == datetime.now(KST).strftime('%Y-%m')):
                return saved['payload']
        except (OSError, ValueError, KeyError):
            pass
    return None


def history_window(span, meta):
    if span not in ('1', '3', '5', '10', 'all'):
        raise ValueError('표시 기간은 1년·3년·5년·10년·전체 중 선택해야 합니다.')
    first = period_index(date.fromisoformat(meta['first_month'] + '-01'), 'quarter')
    last = min(period_index(date.fromisoformat(meta['last_month'] + '-01'), 'quarter'),
               period_index(datetime.now(KST).date(), 'quarter'))
    start = first if span == 'all' else max(first, last - int(span) * 4 + 1)
    return start, last


def months_before(day, months):
    index = day.year*12 + day.month-1-months
    year,month = index//12,index%12+1
    return date(year,month,min(day.day,calendar.monthrange(year,month)[1]))


def rolling_window(meta, last):
    today = datetime.now(KST).date()
    if not meta['updated_at']:
        return None
    observed = min(today, datetime.fromisoformat(meta['updated_at']).date())
    stop = observed + timedelta(days=1)
    if last != period_index(observed,'quarter') or stop >= period_start(last+1,'quarter'):
        return None
    return months_before(stop,3), stop


def comparison_years(first_window, last_window):
    first_center = sum(day.toordinal() for day in first_window)/2
    last_center = sum(day.toordinal() for day in last_window)/2
    return (last_center-first_center)/365.2425


def period_map_summary(series, ratios, years):
    annualized = [((1 + change / 100) ** (1 / years) - 1) * 100 for change in ratios] if years > 0 else []
    return dict(count=sum(p['count'] for p in series),
                change=median(annualized) if annualized else None,
                period_change=median(ratios) if ratios else None,
                samples=len(ratios), reliable=len(annualized) >= MIN_CELLS,
                complete=all(p['complete'] for p in series),
                comparison_complete=bool(series) and series[0]['complete'] and series[-1]['complete'],
                provisional=any(p['provisional'] for p in series))


def endpoint_medians(rows):
    """법정동 한 곳·한 구간. 미구분 포함, 확인된 직거래 제외, 조합당 2건 이상."""
    cells = defaultdict(list)
    for _day, amount, area, apt, dealing in rows:
        if apt and dealing != '직거래' and amount > 0 and area > 0:
            cells[(apt, str(float(area)))].append(float(amount))
    return [[apt, area, median(values)] for (apt, area), values in cells.items() if len(values) >= 2]


async def endpoint_snapshot(window, meta, job_key=None, *, reuse=True):
    async with _cohort_lock:
        return await _endpoint_snapshot(window, meta, job_key, reuse=reuse)


async def _endpoint_snapshot(window, meta, job_key=None, *, reuse=True):
    start, stop = window
    key = f'cohort-v1-{start.isoformat()}-{stop.isoformat()}'
    cached = _history_cached(key, meta['updated_at']) if reuse else None
    if cached is not None:
        return cached['regions']
    result = {}
    for code in meta['regions']:
        async with db_session() as db:
            rows = (await db.execute(text(
                "SET STATEMENT max_statement_time=25 FOR SELECT deal_date,amount,exclu_ar,apt_seq,dealing_gbn "
                "FROM N8N.rtms_trade WHERE lawd_cd=:code AND deal_date>=:start AND deal_date<:stop "
                "AND kind='매매' AND cdeal_type='' AND cdeal_day='' AND amount>0 AND exclu_ar>0 "
                "AND apt_seq<>'' AND COALESCE(dealing_gbn,'')<>'직거래'"),
                dict(code=code, start=start, stop=stop))).all()
        result[code] = await asyncio.to_thread(endpoint_medians, rows)
        if job_key is not None:
            _jobs[job_key]['processed'] += 1
    CACHE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = CACHE_DIR / (key + '.json')
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'updated_at': meta['updated_at'], 'payload': {
        'metadata': public_metadata(meta), 'regions': result}}, ensure_ascii=False))
    temporary.replace(path)
    prune_cache()
    return result


async def _period_map(first, last, series, meta, job_key, first_window, last_window, cumulative_counts):
    if first == last:
        return {code: dict(period_map_summary(points, [], 0), count=cumulative_counts[code]) for code, points in series.items()}
    nodes = geography()['nodes']
    ratios = {code: array('d') for code in series}
    left = await endpoint_snapshot(first_window, meta, job_key)
    right = await endpoint_snapshot(last_window, meta, job_key)
    for code in meta['regions']:
        prices = {(apt, area): amount for apt, area, amount in right[code]}
        changes = [(prices[(apt, area)] / amount - 1) * 100
                   for apt, area, amount in left[code] if (apt, area) in prices]
        ratios[code].extend(changes)
        parent = nodes.get(code, {}).get('parent') or 'KR'
        while parent:
            ratios[parent].extend(changes)
            parent = nodes[parent]['parent']
    summaries = {code: period_map_summary(points, ratios[code], comparison_years(first_window,last_window)) for code, points in series.items()}
    for code,point in summaries.items():
        point['count'] = cumulative_counts[code]
    return summaries


async def _history_run(key, span, meta, bounds=None):
    started = time.monotonic()
    try:
        first, last = bounds or history_window(span, meta)
        source_last = history_window("all", meta)[1]
        full = None
        if bounds or span == 'all':
            # 이전 전체 이력의 봉·거래량은 그대로 재사용하고 가격 비교만 새 기준으로 계산한다.
            full = (_history_cached(f'history-quarter-v5-all-{source_last}', meta['updated_at']) or
                    _history_cached(f'history-quarter-v4-all-{source_last}', meta['updated_at']))
        if full and full['metadata'].get('collection_revision', collection_revision(meta)) != collection_revision(meta):
            full = None
        from_full = full is not None
        if from_full:
            result, periods, cumulative_counts = slice_history(full, first, last, history_window('all', meta)[0])
        else:
            result = {}
            periods = []
            for year in range(first // 4, last // 4 + 1):
                stop = min(year * 4 + 3, source_last)
                count = stop - year * 4 + 1
                end = period_start(stop, 'quarter').strftime('%Y-%m')
                shard_key = f'paired-quarter-candle-v1-{end}-{count}'
                shard = _window_cached(shard_key, meta, period_start(year*4-1,'quarter'), period_start(stop+1,'quarter'))
                if shard is None:
                    await _build(shard_key, 'quarter', end, count, 'previous', meta, True, key)
                    shard = _history_cached(shard_key, meta['updated_at'])
                else:
                    _jobs[key]['processed'] += len(meta['regions'])
                indices = [i for i in range(count) if first <= year * 4 + i <= last]
                periods.extend(shard['periods'][i] for i in indices)
                for code, series in shard['regions'].items():
                    result.setdefault(code, []).extend(series[i] for i in indices)
            cumulative_counts = {code:sum(p['count'] for p in points) for code,points in result.items()}
        first_window = period_start(first,'quarter'),period_start(first+1,'quarter')
        last_window = period_start(last,'quarter'),period_start(last+1,'quarter')
        rolling = rolling_window(meta,last)
        if rolling:
            last_window = rolling
        if rolling and not from_full:
            rolling_key = f'rolling-quarter-candle-v1-{rolling[1].isoformat()}'
            latest = _window_cached(rolling_key,meta, months_before(rolling[0],3), rolling[1])
            if latest is None:
                await _build(rolling_key,'quarter',period_start(last,'quarter').strftime('%Y-%m'),1,'previous',meta,True,key,
                             {last:rolling,last-1:(months_before(rolling[0],3),rolling[0])})
                latest = _history_cached(rolling_key,meta['updated_at'])
            else:
                _jobs[key]['processed'] += len(meta['regions'])
            for code,points in result.items():
                points[-1] = latest['regions'][code][0]
        map_summary = await _period_map(first, last, result, meta, key,first_window,last_window,cumulative_counts)
        payload = dict(map_summary=map_summary, map_method='endpoint_matched_cagr',
                       map_dealing_filter='exclude_direct_include_unknown', map_years=comparison_years(first_window,last_window),
                       map_windows={'first':[d.isoformat() for d in first_window],'last':[d.isoformat() for d in last_window]},
                       unit='quarter', span=span, end=period_label(last,'quarter'), count=len(periods),
                       periods=periods, regions=result, method='adjacent_quarter',
                       required_periods=[], minimum_trades=2, metadata=public_metadata(meta))
        _cache[key] = (meta['updated_at'], payload)
        _cache.move_to_end(key)
        while len(_cache) > 8:
            _cache.popitem(last=False)
        file = CACHE_DIR / (key + '.json')
        temporary = file.with_suffix('.tmp')
        temporary.write_text(json.dumps({'updated_at': meta['updated_at'], 'payload': payload}, ensure_ascii=False))
        temporary.replace(file)
        prune_cache()
        log.info('부동산 기간 차트 완료: %s %.1fs', key, time.monotonic()-started)
    except Exception:
        log.exception('부동산 기간 차트 집계 실패: %s', key)
        _jobs[key]['error'] = '기간 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.'
        _jobs[key]['failed_at'] = time.monotonic()
    finally:
        _jobs[key]['task'] = None


def history_bounds(meta, first, last):
    earliest, latest = history_window('all', meta)
    if first is None or last is None or not earliest <= first <= last <= latest:
        raise ValueError('조회 범위는 수집된 분기 안에서 시작·끝을 함께 지정해야 합니다.')
    return first, last


async def history(span='3', first=None, last=None):
    meta = await metadata()
    bounds = history_bounds(meta, first, last) if first is not None or last is not None else None
    first, last = bounds or history_window(span, meta)
    key = f'history-range-v2-{first}-{last}' if bounds else f'history-quarter-v5-{span}-{last}'
    cached = _history_cached(key, meta['updated_at'])
    if cached is not None and cached['metadata'].get('collection_revision', collection_revision(meta)) == collection_revision(meta):
        if 'collection_revision' not in cached['metadata']:
            cached['metadata']['collection_revision'] = collection_revision(meta)
            path = CACHE_DIR / (key + '.json')
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps({'updated_at':meta['updated_at'],'payload':cached},ensure_ascii=False))
            temporary.replace(path)
        return cached
    job = _jobs.get(key)
    if job and job.get('error'):
        if time.monotonic() - job['failed_at'] < 60:
            raise RuntimeError(job['error'])
        job = None
    if not job or not job['task']:
        if any(j['task'] for j in _jobs.values()):
            return {'pending': True, 'queued': True}
        _jobs.clear()
        _jobs[key] = {'processed': 0, 'task': None}
        _jobs[key]['task'] = asyncio.create_task(_history_run(key, span, meta, bounds))
    return {'pending': True, 'processed': _jobs[key]['processed'],
            'total': (last // 4 - first // 4 + 2 + bool(rolling_window(meta,last))) * len(meta['regions'])}
