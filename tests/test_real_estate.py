"""실거래 분석의 기간·고정 표본·상위 지역 재집계·지도 트리 계약."""
from datetime import date
from statistics import median
import pytest
from app.services.real_estate import (analyze_rows, geography, period_index,
    period_start, window, summarize, _collection_complete)


def trade(month, price, apt='A', area=84, dealing='중개거래'):
    return (date.fromisoformat(month + '-15'), price, area, apt, dealing)


@pytest.mark.parametrize('unit,day,label', [('month',date(2026,12,31),date(2026,12,1)),
    ('quarter',date(2026,12,31),date(2026,10,1)),('year',date(2026,12,31),date(2026,1,1))])
def test_period_roundtrip(unit,day,label):
    assert period_start(period_index(day,unit),unit)==label


def test_fixed_cohort_excludes_missing_month_and_direct_trade_from_prices_only():
    display,required,lag=window('month','2026-09',3,'previous')
    rows=[trade(m,p) for m,p in zip(['2026-06','2026-07','2026-08','2026-09'],[100,110,121,133.1])]
    rows += [trade('2026-09',999,'B'),trade('2026-09',888,'C',dealing='직거래')]
    a,p,r,n=analyze_rows(rows,'month',display,required,lag)
    assert n==1
    assert [len(x) for x in a]==[1,1,3]
    assert [median(x) for x in r]==pytest.approx([10,10,10])
    assert median(a[-1])==888


def test_median_prices_then_median_changes_not_average():
    display,required,lag=window('month','2026-08',2,'previous')
    rows=[]
    for apt,prices in [('A',[100,110,121]),('B',[100,150,150]),('C',[100,90,81])]:
        rows.extend(trade(m,p,apt) for m,p in zip(['2026-06','2026-07','2026-08'],prices))
    a,p,r,n=analyze_rows(rows,'month',display,required,lag)
    assert n==3
    assert [median(x) for x in r]==pytest.approx([10,0])


def test_quarter_minimum_two_trades_per_cell_and_area_matching():
    display,required,lag=window('quarter','2026-07',2,'previous')
    rows=[]
    for month,amount in [('2026-01',100),('2026-04',120),('2026-07',180)]:
        rows += [trade(month,amount),trade(month,amount)]
        rows += [trade(month,amount,'B')]
        rows += [trade(month,amount,'A',85)]
    a,p,r,n=analyze_rows(rows,'quarter',display,required,lag)
    assert n==1
    assert [median(x) for x in r]==pytest.approx([20,50])


def test_year_on_year_reference_periods_and_no_zero_for_missing():
    display,required,lag=window('quarter','2026-07',4,'year')
    assert lag==4 and len(required)==8
    a,p,r,n=analyze_rows([],'quarter',display,required,lag)
    summary=summarize(a,p,r,n,[len(x) for x in a])
    assert all(x['change'] is None and x['median'] is None and x['count']==0 for x in summary)


def test_tree_has_unique_leaf_codes_and_correct_city_drilldown():
    nodes=geography()['nodes']
    assert nodes['11']['parent']=='KR'
    assert len(nodes['11']['children'])==25
    assert nodes['41110']['parent']=='41'
    assert nodes['41111']['parent']=='41110'
    assert nodes['41130']['parent']=='41'
    assert nodes['41135']['parent']=='41130'
    assert nodes['41590']['parent']=='41'
    assert len(nodes['41590']['children'])==4
    assert len(nodes['KR']['codes'])==len(set(nodes['KR']['codes']))==256
    for node in nodes.values():
        if node['children']:
            assert set(node['codes'])=={code for child in node['children'] for code in nodes[child]['codes']}


def test_collection_checks_every_month_and_every_region():
    meta={'coverage':{'202601':['11110','11140'],'202602':['11110'],'202603':['11110','11140']}}
    assert _collection_complete(meta,['11110'],date(2026,1,1),date(2026,4,1))
    assert not _collection_complete(meta,['11110','11140'],date(2026,1,1),date(2026,4,1))


def test_uncollected_future_month_is_not_a_missing_completed_month():
    meta={'coverage':{'202610':['11110'],'202611':['11110']}}
    today=date(2026,11,15)
    observed_stop=min(date(2027,1,1),period_start(period_index(today,'month')+1,'month'))
    assert _collection_complete(meta,['11110'],date(2026,10,1),observed_stop)
    assert not _collection_complete(meta,['11110'],date(2026,10,1),date(2027,1,1))


def test_every_navigation_node_has_matching_map_features():
    import json
    from app.services.real_estate import MAP_DIR
    for key,node in geography()['nodes'].items():
        data=json.loads((MAP_DIR/(key+'.json')).read_text())
        assert {f['id'] for f in data['features']}==set(node['children'] or [key])
        assert all(f['path'].startswith('M') and len(f['label'])==2 for f in data['features'])


def test_adjacent_month_cohort_varies_without_long_window_survivorship():
    display, required, lag = window('month', '2026-09', 3, 'previous')
    rows = [trade('2026-06', 100, 'A'), trade('2026-07', 110, 'A'),
            trade('2026-07', 200, 'B'), trade('2026-08', 240, 'B'),
            trade('2026-08', 300, 'C'), trade('2026-09', 390, 'C'),
            trade('2026-09', 999, 'D', dealing='직거래')]
    a, p, r, n = analyze_rows(rows, 'month', display, required, lag, paired=True)
    assert n == [1, 1, 1]
    assert [median(v) for v in r] == pytest.approx([10, 20, 30])
    assert len(a[-1]) == 2 and median(a[-1]) == 694.5
    summary = summarize(a, p, r, n, [len(v) for v in a])
    assert [v['samples'] for v in summary] == n
    assert all(not v['reliable'] for v in summary)
    short, needed, step = window('month', '2026-09', 2, 'previous')
    _, _, short_ratios, short_n = analyze_rows(rows, 'month', short, needed, step, paired=True)
    assert short_n == n[-2:]
    assert [median(v) for v in short_ratios] == pytest.approx([20, 30])


def test_adjacent_month_missing_reference_is_not_zero_change():
    display, required, lag = window('month', '2026-09', 2, 'previous')
    a, p, r, n = analyze_rows([trade('2026-09', 100)], 'month', display, required, lag, paired=True)
    values = summarize(a, p, r, n, [len(v) for v in a])
    assert n == [0, 0]
    assert values[0]['median'] is None and values[1]['median'] == 100
    assert all(v['change'] is None for v in values)


def test_history_range_clamps_to_source_and_bounds_span():
    from app.services.real_estate import history_window
    meta = {'first_month': '2006-01', 'last_month': '2025-11'}
    first, last = history_window('3', meta)
    assert last-first+1 == 12
    assert period_label_for_test(first) == '2023-01'
    assert history_window('all', meta)[0] == 2006*4
    with pytest.raises(ValueError):
        history_window('500', meta)


def period_label_for_test(index):
    return period_start(index, 'quarter').strftime('%Y-%m')


def test_period_map_matches_endpoints_without_requiring_intermediate_trades():
    from app.services.real_estate import period_map_summary
    first = period_index(date(2023,12,1), 'month')
    last = period_index(date(2026,11,1), 'month')
    rows = [trade('2023-12',100,'A'),trade('2026-11',150,'A'),
            trade('2023-12',200,'B'),trade('2026-11',160,'B'),
            trade('2026-11',1000,'C'),trade('2026-11',500,'A',dealing='직거래')]
    _,_,ratios,n = analyze_rows(rows,'month',[last],[first,last],last-first,True)
    assert n == [2]
    assert sorted(ratios[0]) == pytest.approx([-20,50])
    series = [dict(count=10,complete=True,provisional=False),dict(count=20,complete=True,provisional=True)]
    point = period_map_summary(series,ratios[0],1)
    assert point['change'] == pytest.approx(15)
    assert point['count'] == 30 and point['samples'] == 2 and point['provisional']
    assert not point['reliable']


def test_period_map_incomplete_month_is_not_a_complete_total():
    from app.services.real_estate import period_map_summary
    point = period_map_summary([dict(count=10,complete=False,provisional=False)],[],1)
    assert not point['complete'] and not point['comparison_complete']
    assert point['change'] is None


def test_quarter_pairs_pool_transactions_before_median_and_require_two_each():
    display, required, lag = window('quarter', '2026-04', 1, 'previous')
    rows = [trade('2026-01',100,'A'),trade('2026-03',300,'A'),
            trade('2026-04',300,'A'),trade('2026-06',500,'A'),
            trade('2026-01',200,'B'),trade('2026-03',200,'B'),
            trade('2026-04',100,'B'),trade('2026-06',100,'B'),
            trade('2026-03',50,'C'),trade('2026-06',100,'C'),
            trade('2026-06',999,'D',dealing='직거래')]
    a,p,r,n = analyze_rows(rows,'quarter',display,required,lag,paired=True)
    assert n == [2]
    assert sorted(r[0]) == pytest.approx([-50,100])
    assert median(r[0]) == 25
    assert len(a[0]) == 6
    assert median(a[0]) == 200


@pytest.mark.parametrize('span,expected', [('1',4),('3',12),('5',20),('all',84)])
def test_quarter_history_includes_partial_current_quarter(monkeypatch, span, expected):
    from app.services import real_estate as service
    from datetime import datetime
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):
            return cls(2026,11,15,tzinfo=tz)
    monkeypatch.setattr(service,'datetime',Clock)
    first,last=service.history_window(span,{'first_month':'2006-01','last_month':'2026-11'})
    assert last-first+1 == expected
    assert service.period_label(last,'quarter') == '2026 Q4'


@pytest.mark.asyncio
async def test_build_current_quarter_includes_observed_months_without_requiring_december(monkeypatch,tmp_path):
    from app.services import real_estate as service
    from datetime import datetime
    from contextlib import asynccontextmanager
    import json
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):
            return cls(2026,11,15,tzinfo=tz)
    rows=[trade('2026-07',100),trade('2026-09',200),
          trade('2026-10',200),trade('2026-11',400)]
    class Result:
        def all(self):return rows
    class DB:
        async def execute(self,*args,**kwargs):return Result()
    @asynccontextmanager
    async def connection():yield DB()
    monkeypatch.setattr(service,'datetime',Clock)
    monkeypatch.setattr(service,'db_session',connection)
    monkeypatch.setattr(service,'CACHE_DIR',tmp_path)
    monkeypatch.setattr(service,'geography',lambda:dict(boundary_date='2026-10-01',nodes={
        '11110':{'parent':'11','codes':['11110']},'11':{'parent':'KR','codes':['11110']},
        'KR':{'parent':None,'codes':['11110']}}))
    monkeypatch.setattr(service,'_jobs',{'test-quarter':{'processed':0}})
    meta=dict(regions={'11110':'종로구'},coverage={f'2026{m:02d}':['11110'] for m in range(7,12)},
              first_month='2006-01',last_month='2026-11',updated_at='2026-11-14',unmapped=[])
    await service._build('test-quarter','quarter','2026-10',1,'previous',meta,paired=True)
    payload=json.loads((tmp_path/'test-quarter.json').read_text())['payload']
    point=payload['regions']['KR'][0]
    assert point['count']==2 and point['change']==100 and point['samples']==1
    assert point['complete'] and point['comparison_complete'] and point['provisional']
    assert payload['method']=='adjacent_quarter' and payload['minimum_trades']==2
    # 미래 월이 아니라 실제 관측 월이 빠지면 누락으로 판단한다.
    del meta['coverage']['202610']
    await service._build('test-quarter','quarter','2026-10',1,'previous',meta,paired=True)
    point=json.loads((tmp_path/'test-quarter.json').read_text())['payload']['regions']['KR'][0]
    assert not point['complete'] and not point['comparison_complete']


def test_history_cache_invalidates_on_collection_update_and_calendar_month(monkeypatch,tmp_path):
    from app.services import real_estate as service
    from datetime import datetime
    import json
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return cls(2026,11,15,tzinfo=tz)
    monkeypatch.setattr(service,'datetime',Clock)
    monkeypatch.setattr(service,'CACHE_DIR',tmp_path)
    monkeypatch.setattr(service,'_cache',{})
    saved={'updated_at':'old','payload':{'metadata':{'as_of_month':'2026-11'}}}
    path=tmp_path/'quarter.json';path.write_text(json.dumps(saved))
    assert service._history_cached('quarter','old')==saved['payload']
    assert service._history_cached('quarter','new') is None
    saved['payload']['metadata']['as_of_month']='2026-10';path.write_text(json.dumps(saved))
    assert service._history_cached('quarter','old') is None


@pytest.mark.parametrize('years,total,expected', [(2,21,10),(2,-19,-10),(.75,33.1,46.41),(2.75,0,0)])
def test_period_cagr_uses_comparison_interval(years,total,expected):
    from app.services.real_estate import period_map_summary
    point=period_map_summary([dict(count=10,complete=True,provisional=True)],[total]*5,years)
    assert point['change']==pytest.approx(expected)
    assert point['period_change']==total and point['reliable'] and point['provisional']


def test_period_cagr_transforms_each_cell_before_even_sample_median():
    from app.services.real_estate import period_map_summary
    point=period_map_summary([], [0,300], 2)
    assert point['change']==50  # 0%와 100%의 중앙값. 누적 중앙값 150%의 연환산과 다르다.
    assert point['period_change']==150


def test_period_cagr_zero_interval_has_no_annual_rate():
    from app.services.real_estate import period_map_summary
    point=period_map_summary([], [0]*5, 0)
    assert point['change'] is None and not point['reliable']


def test_rolling_window_on_january_first_uses_previous_three_months(monkeypatch):
    from app.services import real_estate as service
    from datetime import datetime
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return cls(2027,1,1,tzinfo=tz)
    monkeypatch.setattr(service,'datetime',Clock)
    last=period_index(date(2027,1,1),'quarter')
    assert service.rolling_window({'updated_at':'2027-01-01T03:00:00'},last)==(date(2026,10,2),date(2027,1,2))
    assert service.rolling_window({'updated_at':'2026-12-31T03:00:00'},last) is None
    # 달력이 바뀌어도 새 수집분이 없으면 이전 관측 구간을 그대로 유지한다.
    assert service.rolling_window({'updated_at':'2026-12-27T03:00:00'},last-1)==(date(2026,9,28),date(2026,12,28))
    assert service.rolling_window({'updated_at':'2026-12-31T03:00:00'},last-1) is None
    assert service.months_before(date(2027,5,31),3)==date(2027,2,28)
    assert service.months_before(date(2024,5,31),3)==date(2024,2,29)


def test_rolling_windows_count_calendar_boundary_days_once():
    from app.services.real_estate import analyze_rows
    end=period_index(date(2027,1,1),'quarter')
    windows={end-1:(date(2026,7,2),date(2026,10,2)),end:(date(2026,10,2),date(2027,1,2))}
    rows=[(date(2026,7,2),100,84,'A','중개거래'),(date(2026,10,1),200,84,'A','중개거래'),
          (date(2026,10,2),200,84,'A','중개거래'),(date(2026,12,31),300,84,'A','중개거래'),
          (date(2027,1,1),400,84,'A','중개거래'),(date(2027,1,2),999,84,'A','중개거래')]
    a,_,r,n=analyze_rows(rows,'quarter',[end],[end-1,end],1,True,windows)
    assert list(a[0])==[200,300,400] and n==[1] and r[0][0]==100
    meta={'coverage':{'202610':['11110'],'202611':['11110'],'202612':['11110']}}
    assert not _collection_complete(meta,['11110'],windows[end][0],windows[end][1])
    meta['coverage']['202701']=['11110']
    assert _collection_complete(meta,['11110'],windows[end][0],windows[end][1])


@pytest.mark.asyncio
async def test_rolling_chart_replacement_does_not_double_count_map_volume(monkeypatch,tmp_path):
    from app.services import real_estate as service
    from datetime import datetime
    from collections import OrderedDict
    import json
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return cls(2026,11,15,tzinfo=tz)
    monkeypatch.setattr(service,'datetime',Clock)
    monkeypatch.setattr(service,'CACHE_DIR',tmp_path)
    monkeypatch.setattr(service,'_cache',OrderedDict())
    monkeypatch.setattr(service,'_jobs',{'test':{'processed':0,'task':True}})
    monkeypatch.setattr(service,'geography',lambda:{'boundary_date':'2026-10-01'})
    calendar_points=[dict(count=n,complete=True,provisional=False) for n in [10,20,30,10]]
    latest=dict(count=35,complete=True,provisional=True,rolling=True)
    def cached(key,stamp):
        if key.startswith('rolling'):return {'regions':{'KR':[latest]}}
        return {'periods':['2026 Q1','2026 Q2','2026 Q3','2026 Q4'],'regions':{'KR':calendar_points.copy()}}
    monkeypatch.setattr(service,'_history_cached',cached)
    monkeypatch.setattr(service,'_window_cached',lambda key,meta,start,stop:cached(key,meta['updated_at']))
    async def period_map(first,last,series,meta,key,first_window,last_window,cumulative_counts):
        assert sum(p['count'] for p in series['KR'])==95
        assert cumulative_counts['KR']==70
        assert last_window==(date(2026,8,15),date(2026,11,15))
        return {'KR':{'count':cumulative_counts['KR']}}
    monkeypatch.setattr(service,'_period_map',period_map)
    meta=dict(regions={'11110':'종로구'},first_month='2006-01',last_month='2026-11',updated_at='2026-11-14T03:00:00',unmapped=[])
    await service._history_run('test','1',meta)
    assert not service._jobs['test'].get('error')
    payload=json.loads((tmp_path/'test.json').read_text())['payload']
    assert payload['map_summary']['KR']['count']==70 and payload['regions']['KR'][-1]['count']==35
    assert payload['map_windows']['last']==['2026-08-15','2026-11-15']
    assert payload['map_years']<.75


def test_ten_year_window_has_forty_quarters():
    from app.services.real_estate import history_window
    first,last=history_window('10',{'first_month':'2006-01','last_month':'2025-11'})
    assert last-first+1==40 and period_start(first,'quarter')==date(2016,1,1)


def test_candles_use_monthly_medians_not_extreme_transactions():
    from app.services.real_estate import candle_boundaries, candle_buckets, summarize_candles
    p = period_index(date(2026, 1, 1), 'quarter')
    rows = [trade('2026-01', 100, area=10), trade('2026-01', 200, area=100),
            trade('2026-01', 9999, area=100), trade('2026-02', 400, area=20),
            trade('2026-03', 300, area=30)]
    result = summarize_candles(candle_buckets(rows, candle_boundaries([p])))[0]
    assert result['median'] == dict(o=200, h=400, l=200, c=300)
    assert result['ppm'] == dict(o=10, h=20, l=10, c=10)
    assert result['counts'] == [3, 1, 1]


def test_candles_do_not_fill_missing_months_or_confuse_flat_with_missing():
    from app.services.real_estate import candle_boundaries, candle_buckets, summarize_candles
    p = period_index(date(2026, 1, 1), 'quarter')
    rows = [trade('2026-01', 100), trade('2026-03', 100)]
    assert summarize_candles(candle_buckets(rows, candle_boundaries([p])))[0]['median'] is None
    rows.append(trade('2026-02', 100, dealing='직거래'))
    assert summarize_candles(candle_buckets(rows, candle_boundaries([p])))[0]['median'] == dict(o=100,h=100,l=100,c=100)


def test_rolling_candle_months_exclude_end_and_include_start_even_across_quarters():
    from app.services.real_estate import candle_boundaries, candle_buckets, summarize_candles
    p = period_index(date(2027, 1, 1), 'quarter')
    boundaries = candle_boundaries([p], {p:(date(2026,10,2),date(2027,1,2))})
    assert boundaries[p] == [date(2026,10,2),date(2026,11,2),date(2026,12,2),date(2027,1,2)]
    rows = [(date.fromisoformat(d),n,10,'A','') for d,n in [
        ('2026-10-01',999),('2026-10-02',100),('2026-11-01',300),
        ('2026-11-02',400),('2026-12-02',100),('2027-01-01',200),('2027-01-02',999)]]
    result = summarize_candles(candle_buckets(rows, boundaries))[0]
    assert result['counts'] == [2,1,2]
    assert result['median'] == dict(o=200,h=400,l=150,c=150)


@pytest.mark.asyncio
async def test_parent_candle_pools_raw_transactions_before_monthly_median(monkeypatch,tmp_path):
    from app.services import real_estate as service
    from contextlib import asynccontextmanager
    import json
    class DB:
        async def execute(self, sql, params):
            rows = [trade(m, n) for m in ['2025-01','2025-02','2025-03']
                    for n in ([100] if params['code']=='11110' else [200,300,400])]
            class Result:
                def all(self): return rows
            return Result()
    @asynccontextmanager
    async def connection(): yield DB()
    monkeypatch.setattr(service,'db_session',connection)
    monkeypatch.setattr(service,'CACHE_DIR',tmp_path)
    nodes={'11110':{'parent':'11','codes':['11110']},'11140':{'parent':'11','codes':['11140']},
           '11':{'parent':'KR','codes':['11110','11140']},'KR':{'parent':None,'codes':['11110','11140']}}
    monkeypatch.setattr(service,'geography',lambda:dict(boundary_date='2026-10-01',nodes=nodes))
    monkeypatch.setattr(service,'_jobs',{'test-candle':{'processed':0}})
    meta=dict(regions={'11110':'종로구','11140':'중구'},coverage={f'2025{m:02d}':['11110','11140'] for m in range(1,4)},
              first_month='2006-01',last_month='2025-03',updated_at='2025-04-01',unmapped=[])
    await service._build('test-candle','quarter','2025-01',1,'previous',meta,True)
    regions=json.loads((tmp_path/'test-candle.json').read_text())['payload']['regions']
    assert regions['11110'][0]['candle']['median']['c']==100
    assert regions['11140'][0]['candle']['median']['c']==300
    assert regions['11'][0]['candle']['median']['c']==250  # 하위 중위값의 평균 200이 아님
    assert regions['KR'][0]['candle']==regions['11'][0]['candle']
    assert regions['KR'][0]['candle']['counts']==[4,4,4]


def test_chart_range_rejects_missing_reversed_and_out_of_source_bounds():
    from app.services.real_estate import history_bounds
    meta={'first_month':'2006-01','last_month':'2025-11'}
    assert history_bounds(meta,2024*4,2025*4+2)==(8096,8102)
    for first,last in [(None,8102),(8096,None),(8102,8096),(8023,8102),(8096,8104)]:
        with pytest.raises(ValueError): history_bounds(meta,first,last)


@pytest.mark.asyncio
async def test_single_quarter_has_volume_but_no_manufactured_annual_change():
    from app.services.real_estate import _period_map
    points=[dict(count=20,complete=True,provisional=False)]
    result=await _period_map(8100,8100,{'KR':points},{},'test',
        (date(2025,1,1),date(2025,4,1)),(date(2025,1,1),date(2025,4,1)),{'KR':20})
    assert result['KR']['count']==20 and result['KR']['change'] is None
    assert result['KR']['samples']==0 and not result['KR']['reliable']


@pytest.mark.asyncio
async def test_arbitrary_chart_range_reuses_year_shard_and_excludes_outside_quarters(monkeypatch,tmp_path):
    from app.services import real_estate as service
    from collections import OrderedDict
    import json
    monkeypatch.setattr(service,'CACHE_DIR',tmp_path)
    monkeypatch.setattr(service,'_cache',OrderedDict())
    monkeypatch.setattr(service,'_jobs',{'test-range':{'processed':0,'task':True}})
    monkeypatch.setattr(service,'geography',lambda:{'boundary_date':'2026-10-01'})
    def cached(key,stamp):
        if key.startswith('history-quarter-') and '-all-' in key:return None
        assert key=='paired-quarter-candle-v1-2025-10-4'  # 2분기까지만 재조회하지 않는다.
        return {'periods':['2025 Q1','2025 Q2','2025 Q3','2025 Q4'],
                'regions':{'KR':[dict(count=i,complete=True,provisional=False) for i in [10,20,30,40]]}}
    monkeypatch.setattr(service,'_history_cached',cached)
    monkeypatch.setattr(service,'_window_cached',lambda key,meta,start,stop:cached(key,meta['updated_at']))
    async def mapping(first,last,series,meta,key,left,right,counts):
        assert (first,last)==(8101,8102) and [p['count'] for p in series['KR']]==[20,30]
        assert counts['KR']==50
        assert left==(date(2025,4,1),date(2025,7,1))
        assert right==(date(2025,7,1),date(2025,10,1))
        return {'KR':{'count':50}}
    monkeypatch.setattr(service,'_period_map',mapping)
    meta=dict(regions={'11110':'종로구'},first_month='2006-01',last_month='2026-11',updated_at='2026-11-14T03:00:00',unmapped=[])
    await service._history_run('test-range','all',meta,(8101,8102))
    assert not service._jobs['test-range'].get('error')
    data=json.loads((tmp_path/'test-range.json').read_text())['payload']
    assert data['periods']==['2025 Q2','2025 Q3'] and data['map_summary']['KR']['count']==50


def test_range_slice_keeps_calendar_volume_when_last_candle_overlaps():
    from app.services.real_estate import slice_history
    full={'periods':['Q1','Q2','Q3','Q4'], 'regions':{'KR':[dict(count=10),dict(count=20),dict(count=30),dict(count=35,rolling=True)]},
          'map_summary':{'KR':{'count':70}}}
    regions,periods,counts=slice_history(full,8105,8107,8104)
    assert periods==['Q2','Q3','Q4'] and sum(p['count'] for p in regions['KR'])==85
    assert counts['KR']==60
    assert slice_history(full,8105,8106,8104)[2]['KR']==50
    assert full['regions']['KR'][-1]['count']==35


def test_viewport_cache_eviction_preserves_full_history_and_year_aggregates(monkeypatch,tmp_path):
    from app.services import real_estate as service
    monkeypatch.setattr(service,'CACHE_DIR',tmp_path)
    full=tmp_path/'history-quarter-v4-all-8107.json';full.write_text('{}')
    for y in range(2006,2027): (tmp_path/f'paired-quarter-candle-v1-{y}-10-4.json').write_text('{}')
    for i in range(40): (tmp_path/f'history-range-v1-{8024+i}-8107.json').write_text('{}')
    service.prune_cache()
    assert full.exists()
    assert len(list(tmp_path.glob('paired-quarter-*.json')))==21
    assert len(list(tmp_path.glob('history-range-*.json')))==16


@pytest.mark.asyncio
async def test_viewport_uses_full_history_without_rebuilding_evicted_year_shards(monkeypatch,tmp_path):
    from app.services import real_estate as service
    from collections import OrderedDict
    import json
    monkeypatch.setattr(service,'CACHE_DIR',tmp_path)
    monkeypatch.setattr(service,'_cache',OrderedDict())
    monkeypatch.setattr(service,'_jobs',{'fast-range':{'processed':0,'task':True}})
    monkeypatch.setattr(service,'geography',lambda:{'boundary_date':'2026-10-01'})
    full={'metadata':{},'periods':['2026 Q1','2026 Q2','2026 Q3','2026 Q4'],
          'regions':{'KR':[dict(count=10),dict(count=20),dict(count=30),dict(count=35,rolling=True)]},
          'map_summary':{'KR':{'count':70}}}
    def cached(key,stamp):
        if key=='history-quarter-v5-all-8107':return None
        assert key=='history-quarter-v4-all-8107'
        return full
    monkeypatch.setattr(service,'_history_cached',cached)
    async def no_build(*args,**kwargs):raise AssertionError('범위 이동으로 원본 연도를 다시 집계하면 안 됨')
    monkeypatch.setattr(service,'_build',no_build)
    async def mapping(first,last,series,meta,key,left,right,counts):
        assert [p['count'] for p in series['KR']]==[20,30,35] and counts['KR']==60
        assert right==(date(2026,8,15),date(2026,11,15))
        return {'KR':{'count':60}}
    monkeypatch.setattr(service,'_period_map',mapping)
    meta=dict(regions={'11110':'종로구'},first_month='2026-01',last_month='2026-11',updated_at='2026-11-14T03:00:00',unmapped=[])
    await service._history_run('fast-range','all',meta,(8105,8107))
    assert not service._jobs['fast-range'].get('error')
    payload=json.loads((tmp_path/'fast-range.json').read_text())['payload']
    assert payload['map_summary']['KR']['count']==60


def test_endpoint_includes_unknown_excludes_direct_and_requires_two_per_area():
    from app.services.real_estate import endpoint_medians
    rows=[trade('2018-07',100,dealing=''),trade('2018-08',200,dealing=None),
          trade('2018-08',999,dealing='직거래'),trade('2018-09',300,'B',dealing=''),
          trade('2018-09',400,'A',area=85,dealing=''),trade('2018-09',600,'A',area=85),
          trade('2018-09',0,'C'),trade('2018-09',100,'',dealing='')]
    assert endpoint_medians(rows)==[['A','84.0',150],['A','85.0',500]]


@pytest.mark.asyncio
async def test_endpoint_cache_reused_across_ranges_and_invalidated_on_source_update(monkeypatch,tmp_path):
    from app.services import real_estate as service
    from contextlib import asynccontextmanager
    from collections import OrderedDict
    queries=[]
    class DB:
        async def execute(self, sql, params):
            assert "COALESCE(dealing_gbn,'')<>'직거래'" in str(sql)
            queries.append((params['code'],params['start']))
            price=100 if params['start'].year==2018 else 200
            rows=[trade('2018-07',price,dealing=''),trade('2018-08',price,dealing='')]
            class Result:
                def all(self):return rows
            return Result()
    @asynccontextmanager
    async def connection():yield DB()
    monkeypatch.setattr(service,'db_session',connection)
    monkeypatch.setattr(service,'CACHE_DIR',tmp_path)
    monkeypatch.setattr(service,'_cache',OrderedDict())
    monkeypatch.setattr(service,'_jobs',{'cohort-test':{'processed':0}})
    nodes={'11110':{'parent':'11'},'11140':{'parent':'11'},'11':{'parent':'KR'},'KR':{'parent':None}}
    monkeypatch.setattr(service,'geography',lambda:dict(boundary_date='2026-10-01',nodes=nodes))
    meta=dict(regions={'11110':'종로구','11140':'중구'},first_month='2006-01',last_month='2026-11',updated_at='old',unmapped=[])
    a=(date(2018,7,1),date(2018,10,1));b=(date(2026,7,1),date(2026,10,1))
    for w in [a,b,a,b]:await service.endpoint_snapshot(w,meta,'cohort-test')
    assert len(queries)==4  # 2개 지역 × 처음 보는 두 구간만 조회
    series={code:[dict(count=2,complete=True,provisional=False)] for code in nodes}
    result=await service._period_map(8074,8106,series,meta,'cohort-test',a,b,{c:4 for c in nodes})
    assert len(queries)==4  # 다른 범위 결과를 조합해도 원본 조회 없음
    assert result['KR']['samples']==2 and result['KR']['change']>0
    assert result['KR']['count']==4
    await service.endpoint_snapshot(a,{**meta,'updated_at':'new'},'cohort-test')
    assert len(queries)==6


@pytest.mark.asyncio
async def test_cached_endpoint_matching_pools_cells_without_crossing_area_or_region(monkeypatch):
    from app.services import real_estate as service
    a=(date(2018,7,1),date(2018,10,1));b=(date(2026,7,1),date(2026,10,1))
    async def cached(window,meta,key):
        return {'11110':[['A','84.0',100 if window==a else 200]],
                '11140':[['A','84.0',100],['B','84.0',100],['C','84.0',100],
                         ['D','84.0' if window==a else '85.0',100]]}
    monkeypatch.setattr(service,'endpoint_snapshot',cached)
    nodes={'11110':{'parent':'11'},'11140':{'parent':'11'},'11':{'parent':'KR'},'KR':{'parent':None}}
    monkeypatch.setattr(service,'geography',lambda:{'nodes':nodes})
    series={c:[dict(count=10,complete=True,provisional=False)] for c in nodes}
    result=await service._period_map(8074,8106,series,{'regions':{'11110':'종로구','11140':'중구'}},'test',a,b,{c:10 for c in nodes})
    assert result['11']['samples']==4 and result['11']['change']==0
    assert result['11110']['change']>0 and result['11140']['samples']==3
    assert result['KR']==result['11']
