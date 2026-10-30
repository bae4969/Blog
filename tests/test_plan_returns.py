"""매수비용은 현재 시세·납입원금·전일 변동과 분리하고, 확인된 보유 비용으로만 수익률을 낸다."""

import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api import plan_ai
from app.services import invest_plan as ip, plan_assets, plan_reconcile


DC = [
    ('TEST01', 10, 1_000, 120, 200),
    ('TEST02', 20, 4_000, 180, -400),
    ('TEST03', 5, 500, 100, 0),
    ('TEST04', 8, 1_600, 150, -400),
    ('TEST05', 3, 600, 250, 150),
    ('TEST06', 4, 800, 150, -200),
]


def doc():
    return ip.PlanDoc(accounts=[ip.Account(name='DC', type='pension', principal=99_000_000)], holdings=[
        ip.Holding(kind='stock', name=code, code=code, market='KR', qty=qty, unit='좌',
                   buy_cost_krw=cost, account='DC') for code, qty, cost, _, _ in DC] + [
        ip.Holding(kind='cash', name='현금', qty=123, account='DC')])


def summary(d=None, px=None, previous=None):
    d = d or doc()
    px = {code: price for code, _, _, price, _ in DC} if px is None else px
    current = ip.valuate(d, px, {}, {'USD': 1400})['root']
    before = ip.valuate(d, previous if previous is not None else {c: p + 100 for c, p in px.items()}, {}, {'USD': 1300})['root']
    result = plan_assets.summarize(d, current, before)
    return result, next(a for g in result['groups'] for a in g['items'] if a['name'] == 'DC')


def test_DC_총매수비용과_개별손익_계좌수익률은_전일대비와_독립적이다():
    s, account = summary()
    assert account['value'] == 7973
    assert account['buy_cost_krw'] == 8500
    assert account['pnl'] == -650
    assert account['pnl_pct'] == pytest.approx(-650 / 8500 * 100)
    assert account['pnl'] != account['change']
    for row, (_, _, cost, _, pnl) in zip(account['rows'], DC):
        assert row['buy_cost_krw'] == cost and row['pnl'] == pnl
        assert row['pnl_pct'] == pytest.approx(pnl / cost * 100)
    # 납입원금은 매수비용으로 사용하지 않고, 현금도 매수비용 분모에 넣지 않는다.
    assert account['rows'][-1]['pnl_pct'] is None
    assert s['quantity_missing'] == 0
    assert summary(previous={})[1]['pnl'] == account['pnl']


def test_매수비용_일부만_확인되면_계좌수익률을_일부합으로_만들지_않는다():
    d = doc()
    d.holdings[1].buy_cost_krw = None
    _, a = summary(d)
    assert a['pnl'] is None and a['pnl_pct'] is None and a['buy_cost_krw'] is None
    assert a['rows'][0]['pnl'] == 200
    assert a['rows'][1]['pnl_pct'] is None
    assert a['change'] is not None


@pytest.mark.parametrize('missing_qty', [False, True])
def test_입력평가액_또는_수량미확인은_매수비용이_있어도_수익률_미확인이다(missing_qty):
    d = doc()
    d.holdings[0].amount = 6_000_000
    if missing_qty:
        d.holdings[0].qty = None
    _, a = summary(d, px={})
    assert a['rows'][0]['value'] == 6_000_000
    assert a['rows'][0]['pnl'] is None and a['pnl_pct'] is None


def test_단가_또는_환율이_없으면_수익률을_0으로_꾸미지_않는다():
    d = ip.PlanDoc(holdings=[ip.Holding(kind='stock', name='미국', code='AAPL', market='US', qty=2,
                                      buy_cost_krw=200_000, account='DC')])
    values = ip.valuate(d, {'AAPL': 100}, {}, {})['root']
    a = plan_assets.summarize(d, values, values)['groups'][1]['items'][0]
    assert a['value'] is None and a['pnl'] is None and a['pnl_pct'] is None


def test_미국종목_매수비용은_원화로_저장해_현재환율을_원가에_다시_곱하지_않는다():
    d = ip.PlanDoc(holdings=[ip.Holding(kind='stock', name='미국', code='AAPL', market='US', qty=2,
                                      currency='USD', buy_cost_krw=200_000, account='DC')])
    values = ip.valuate(d, {'AAPL': 100}, {}, {'USD': 1400})['root']
    a = plan_assets.summarize(d, values, values)['groups'][1]['items'][0]
    assert a['pnl'] == 80_000 and a['pnl_pct'] == 40


@pytest.mark.parametrize('cost', [None, 0, 100, 200, 400])
def test_미확인원가_0원원가_손익0_이익_손실을_구분한다(cost):
    d = ip.PlanDoc(holdings=[ip.Holding(kind='stock', name='주식', code='005930', market='KR', qty=2,
                                      buy_cost_krw=cost, account='DC')])
    _, a = summary(d, px={'005930': 100})
    assert a['pnl'] == (None if cost is None else 200 - cost)
    assert a['pnl_pct'] == (None if not cost else (200 - cost) / cost * 100)


@pytest.mark.parametrize('cost', [-1, float('inf'), float('-inf'), float('nan')])
def test_음수나_유한하지_않은_매수비용은_저장하지_않는다(cost):
    with pytest.raises(ValidationError):
        ip.Holding(kind='cash', name='원화', qty=1, buy_cost_krw=cost)


def test_원가확인은_보유지문이나_실행이력_후속계획을_바꾸지_않는다():
    old = doc()
    old.holdings[0].buy_cost_krw = None
    old.nodes = [ip.Node(id='e', kind='event', title='계획', at='2026-12-10T09:00:00+09:00'),
                 ip.Node(id='b', parent='e', kind='branch', title='유지', holdings=old.holdings)]
    ip.stamp_branches(ip.PlanDoc(), old)
    new = old.model_copy(deep=True)
    new.holdings[0].buy_cost_krw = DC[0][2]
    assert ip.holdings_stamp(old.holdings) == ip.holdings_stamp(new.holdings)
    assert plan_reconcile.stamp(old.holdings) == plan_reconcile.stamp(new.holdings)
    assert plan_reconcile.rebase(new, ({}, {}, {})) == []
    assert not ip.stale_branches(new)
    assert ip.trades(new, ip.valuate(new, {}, {}, {}))['b'] == []


def test_미래_매수수량을_덧붙일때_기존보유의_총매수비용을_그대로_복사하지_않는다():
    root = ip.Holding(kind='stock', name='주식', code='005930', market='KR', qty=3, buy_cost_krw=250, account='DC')
    cash = ip.Holding(kind='cash', name='현금', qty=1000, account='DC')
    d = ip.PlanDoc(holdings=[root, cash], nodes=[
        ip.Node(id='e', kind='event', title='계획', at='2026-12-10T09:00:00+09:00'),
        ip.Node(id='b', parent='e', kind='branch', title='1주 매수',
                basis=[root.model_copy(update={'qty': 2}), cash],
                holdings=[root, cash.model_copy(update={'qty': 900})])])
    assert plan_reconcile.rebase(d, ({'005930': 100}, {}, {})) == ['b']
    assert d.nodes[-1].holdings[0].qty == 4 and d.nodes[-1].holdings[0].buy_cost_krw is None
    assert d.holdings[0].buy_cost_krw == 250


def test_미래_외화결제에도_기존_외화매수비용을_그대로_복사하지_않는다():
    cash = ip.Holding(kind='cash', name='달러', qty=110, currency='USD', buy_cost_krw=150_000, account='DC')
    stock = ip.Holding(kind='stock', name='미국', qty=1, code='AAPL', market='US', account='DC')
    d = ip.PlanDoc(holdings=[stock, cash], nodes=[
        ip.Node(id='e', kind='event', title='계획', at='2026-12-10T09:00:00+09:00'),
        ip.Node(id='b', parent='e', kind='branch', title='1주 매수',
                basis=[stock, cash.model_copy(update={'qty': 100})],
                holdings=[stock.model_copy(update={'qty': 2}), cash.model_copy(update={'qty': 90})])])
    assert plan_reconcile.rebase(d, ({'AAPL': 10}, {}, {'USD': 1400})) == ['b']
    after = next(h for h in d.nodes[-1].holdings if h.kind == 'cash')
    assert after.qty == 100 and after.buy_cost_krw is None
    assert cash.buy_cost_krw == 150_000


@pytest.mark.parametrize(('qty', 'sent', 'expected'), [(10, 'omit', 1000), (11, 'omit', None),
                                                     (10, None, None), (11, 1100, 1100)])
def test_MCP_원가저장과_같은수량의_생략보존_수량변경의_미확인처리(monkeypatch, qty, sent, expected):
    state = {'doc': doc()}
    async def latest(db, user):
        return SimpleNamespace(doc=state['doc'].model_dump_json())
    async def save(db, user, new, note):
        state['doc'] = new
        return 2
    async def prices(db, new):
        return {}, {}, {}
    class DB:
        async def commit(self):
            pass
    monkeypatch.setattr(plan_ai, 'latest_rev', latest)
    monkeypatch.setattr(plan_ai, '_save_rev', save)
    monkeypatch.setattr(plan_ai, 'prices', prices)
    holdings = [h.model_dump(mode='json') for h in state['doc'].holdings]
    holdings[0]['qty'] = qty
    if sent == 'omit':
        holdings[0].pop('buy_cost_krw')
    else:
        holdings[0]['buy_cost_krw'] = sent
    asyncio.run(plan_ai._write(DB(), 991, 'holdings_set', {'holdings': holdings}))
    assert state['doc'].holdings[0].buy_cost_krw == expected
    s, _ = summary(state['doc'])
    for row in s['stocks']:
        row['quote_at'] = None
    prompt = plan_assets.prompt({**s, 'holdings_as_of': None, 'checked_at': None})
    assert 'buy_cost_krw' in prompt and 'pnl_pct' in prompt and '전일 대비' in prompt
