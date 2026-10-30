"""모든 자산의 수량·단가 평가, 잔고 변경 뒤 계획과 실제 이력의 일관성을 검증한다."""

import asyncio
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from app.api import plan_ai, plan_v1
from app.api import market_ai
from app.services import invest_plan as ip
from app.services import plan_reconcile as rec


def cash(qty, currency="KRW", account="ISA"):
    return ip.Holding(kind="cash", name=currency, account=account, qty=qty, currency=currency)


def stock(qty, code="484790", kind="bond"):
    return ip.Holding(kind=kind, name="KODEX 미국30년국채액티브(H)", code=code, market="KR", qty=qty, account="ISA")


def positions(us=400, kr=20, money=7830000):
    return [cash(money), stock(us), stock(kr, "385560")]


def plan():
    d = ip.PlanDoc(as_of=date(2026, 10, 29), holdings=positions(),
                   memory=["미국30년국채(H)는 날짜 기준으로 나눠 산다(2026-10-29 · 2026-12-10, 각 약 120만)."], nodes=[
        ip.Node(id="e1", kind="event", title="1차", at="2026-10-29T03:00:00+09:00"),
        ip.Node(id="b1", parent="e1", kind="branch", title="1차 매수", condition="각각 약 60만 원 매수",
                holdings=positions(475, 31, 6632405)),
        ip.Node(id="e2", parent="b1", kind="event", title="2차", at="2026-12-10T09:10:00+09:00"),
        ip.Node(id="b2", parent="e2", kind="branch", title="2차 매수", condition="각각 약 60만 원 매수",
                holdings=positions(550, 42, 5434810))])
    ip.stamp_branches(ip.PlanDoc(), d)
    return d


PX = ({"484790": 8155, "385560": 55430}, {}, {"USD": 1400})


def test_원화_외화_주식_코인_금_부동산은_수량과_단가로_평가한다():
    hs = [cash(1000), cash(2.5, "USD"), cash(100, "JPY"), cash(1.5, "EUR"),
          stock(2, "005930", "stock"),
          ip.Holding(kind="stock", name="미국", code="AAPL", market="US", qty=.5, currency="USD"),
          ip.Holding(kind="crypto", name="코인", code="BTC", market="COIN", qty=.1),
          ip.Holding(kind="other", name="금", code=ip.GOLD_CODE, market="KR", qty=35, unit="g"),
          ip.Holding(kind="other", name="부동산 지분", qty=.5, unit="건", unit_price=10000)]
    d = ip.PlanDoc(holdings=hs)
    value = ip.valuate(d, {"005930": 100, "AAPL": 10, ip.GOLD_CODE: 173000}, {"BTC": 500},
                       {"USD": 1400, "JPY": 9, "EUR": 1500})["root"]
    expected = [1000, 3500, 900, 2250, 200, 7000, 50, 6055000, 5000]
    assert [r["value"] for r in value["rows"]] == expected
    assert value["total"] == sum(expected)
    for row in value["rows"]:
        assert row["value"] == row["qty"] * row["unit_value_krw"]


def test_일본엔은_1엔_단가로_계산하고_알수없는_환율은_0이나_달러환율로_대체하지_않는다():
    d = ip.PlanDoc(holdings=[cash(10000, "JPY")])
    assert ip.valuate(d, {}, {}, {"JPY": 8.5})["root"]["total"] == 85000
    assert ip.valuate(d, {}, {}, {"USD": 1400})["root"]["rows"][0]["value"] is None
    for invalid in [0, -1, float("nan"), float("inf")]:
        assert ip.valuate(d, {}, {}, {"JPY": invalid})["root"]["rows"][0]["value"] is None


def test_옛_원화_잔액은_1원1개로_읽되_주식수나_외화잔액은_역산하지_않는다():
    hs = [ip.Holding(kind="cash", name="현금", amount=2000),
          ip.Holding(kind="stock", name="주식", code="005930", market="KR", amount=1000),
          ip.Holding(kind="cash", name="SOL트래블 외화예금(원화 환산)", amount=848730),
          ip.Holding(kind="other", name="보증금", amount=10000, type="housing")]
    d = ip.PlanDoc(holdings=hs)
    original = d.model_dump_json()
    rows = ip.valuate(d, {"005930": 100}, {}, {"USD": 1400})["root"]["rows"]
    assert [r["qty"] for r in rows] == [2000, None, None, 1]
    assert [r["quantity_missing"] for r in rows] == [False, True, True, False]
    assert [r["value"] for r in rows] == [2000, 1000, 848730, 10000]
    assert d.model_dump_json() == original


def test_API_문서는_확인된_자산을_수량형식으로_보여주고_원본은_보존한다():
    d = ip.PlanDoc(holdings=[ip.Holding(kind="cash", name="원화", amount=1000),
                            ip.Holding(kind="cash", name="달러", amount=100, currency="USD"),
                            ip.Holding(kind="other", name="주거", amount=10000, type="housing")])
    before = d.model_dump_json()
    output = ip.quantity_doc(d)
    assert [h.qty for h in output.holdings] == [1000, 100, 1]
    assert [h.unit_price for h in output.holdings] == [1, 1, 10000]
    assert all(h.amount is None for h in output.holdings)
    assert d.model_dump_json() == before
    assert ip.outline(d)["holdings"][0]["qty"] == 1000


def test_새_선택항목이_없으면_기존_버전의_보유지문이_유지된다():
    h = ip.Holding(kind="stock", name="삼성전자", code="005930", market="KR", qty=1)
    assert ip.holdings_stamp([h]) == "61582189d1acc466"  # 수량·단가 통일 전 형식으로 저장된 지문


def test_0개_자산은_옛_평가액이_남아있어도_0원이다():
    d = ip.PlanDoc(holdings=[ip.Holding(kind="stock", name="주식", code="005930", market="KR", qty=0, amount=1000)])
    assert ip.valuate(d, {}, {}, None)["root"]["rows"][0]["value"] == 0


def test_한_계좌의_이름이_같은_외화도_통화별_수량을_섞지_않는다():
    before = [ip.Holding(kind="cash", name="외화", account="외화", currency=c, qty=q)
              for c, q in [("USD", 100), ("JPY", 10000)]]
    after = [h.model_copy(update={"qty": q}) for h, q in zip(before, [90, 10010])]
    d = ip.PlanDoc(holdings=before, nodes=[
        ip.Node(id="e", kind="event", title="조정", at="2026-12-10T09:00:00+09:00"),
        ip.Node(id="b", parent="e", kind="branch", title="실행", holdings=after)])
    lines = ip.trades(d, ip.valuate(d, {}, {}, {"USD": 1400, "JPY": 9}))["b"]
    assert [(r["quantity_unit"], r["side"], r["qty"]) for r in lines] == [("USD", "sell", 10), ("JPY", "buy", 10)]


@pytest.mark.parametrize("h", [
    {"kind": "cash", "name": "USD", "currency": "USD", "amount": 100},
    {"kind": "stock", "name": "주식", "code": "005930", "market": "KR", "amount": 1000},
    {"kind": "other", "name": "부동산", "amount": 10000},
    {"kind": "cash", "name": "현금", "qty": 100, "unit_price": 2},
    {"kind": "stock", "name": "주식", "qty": 2},
])
def test_새로_쓰는_자산은_수량이_필요하고_현금_단가를_조작할수_없다(h):
    assert rec.quantity_errors(ip.PlanDoc(), ip.PlanDoc(holdings=[ip.Holding(**h)]))


def test_옛_미확인_자료는_그대로_보존할수_있고_확인한_수량을_금액으로_되돌릴수_없다():
    old = ip.PlanDoc(holdings=[ip.Holding(kind="stock", name="DC", code="005930", market="KR", amount=1000)])
    assert rec.quantity_errors(old, old.model_copy(deep=True)) == []
    new = old.model_copy(deep=True)
    new.holdings[0].qty = 10
    assert not rec.quantity_errors(old, new)
    assert rec.quantity_errors(new, old)


def test_매수전후_이력을_보존하고_2차는_기존_75주11주를_현재잔고에_더한다():
    old = plan()
    new = old.model_copy(deep=True)
    new.holdings = positions(473, 30, 6674888)
    b1 = new.nodes[1]
    b1.holdings = new.holdings
    b1.executed_at, b1.status = date(2026, 10, 30), "realized"
    rec.capture_execution(old, new)
    assert rec.rebase(new, PX) == ["b2"]
    assert [h.qty for h in new.nodes[-1].holdings] == [5453533, 548, 41]
    assert not ip.stale_branches(new)
    trades = ip.trades(new, ip.valuate(new, *PX))
    assert [(r["qty"], r["value"]) for r in trades["b1"] if r["kind"] == "bond"] == [(73, None), (10, None)]
    assert [r["qty"] for r in trades["b2"] if r["kind"] == "bond"] == [75, 11]
    snapshot = b1.execution.model_dump_json()
    new.holdings = positions(480, 40, 8000000)
    assert rec.rebase(new, PX) == ["b2"]
    assert [h.qty for h in new.nodes[-1].holdings][1:] == [555, 51]
    assert b1.execution.model_dump_json() == snapshot
    assert [r["qty"] for r in ip.trades(new, ip.valuate(new, *PX))["b1"] if r["kind"] == "bond"] == [73, 10]


@pytest.mark.parametrize("prices,money", [(({}, {}, None), 6674888), (PX, 1)])
def test_단가나_재원이_부족하면_후속계획을_임의로_적용하지_않는다(prices, money):
    d = plan()
    d.nodes[1].holdings = positions(473, 30, money)
    before = d.nodes[-1].model_dump_json()
    assert rec.rebase(d, prices) == []
    assert d.nodes[-1].model_dump_json() == before and "b2" in ip.stale_branches(d)


def test_실행_표시만으로_계획수량을_실제체결로_확정하지_않는다():
    old = plan()
    new = old.model_copy(deep=True)
    new.nodes[1].executed_at = date(2026, 10, 30)
    rec.capture_execution(old, new)
    assert new.nodes[1].execution is None


def test_옛_지문과_실제_잔고_변경으로만_기준과_이력을_복원한다():
    original = plan()
    marked = original.model_copy(deep=True)
    marked.nodes[1].holdings = positions(473, 30, 6674888)
    marked.nodes[1].executed_at = date(2026, 10, 30)
    current = marked.model_copy(deep=True)
    current.holdings = marked.nodes[1].holdings
    current.as_of = date(2026, 10, 30)
    for n in current.nodes:
        n.basis = None
    raw = current.model_dump_json()
    rec.restore_references(current, [current.model_copy(deep=True), marked, original])
    assert current.nodes[1].execution.before[1].qty == 400
    assert current.nodes[-1].basis[1].qty == 475
    assert rec.rebase(current, PX) == ["b2"]
    assert ip.PlanDoc.model_validate_json(raw).nodes[1].execution is None


def test_같은_계획의_회차당_기억금액_충돌은_표시하고_기억은_보존한다():
    d = plan()
    original = d.memory[:]
    issues = rec.memory_conflicts(d)
    assert len(issues) == 1 and issues[0]["nodes"] == ["b1", "b2"]
    assert d.memory == original
    d.memory = ["다른 종목은 2026-10-29 각 120만 매수", "미국30년국채(H)는 2026-10-29 각 60만 매수"]
    assert rec.memory_conflicts(d) == []


def test_같은_종목의_계획_날짜가_바뀌면_기억_일정과_대조한다():
    d = plan()
    d.memory = ["미국30년국채(H)는 날짜 기준으로 나눠 산다(2026-10-29 · 2026-12-10, 각 약 60만)."]
    d.nodes[2].at = datetime.fromisoformat("2026-12-11T09:10:00+09:00")
    assert rec.memory_conflicts(d)[0]["differences"] == ["schedule"]


@pytest.fixture
def store(monkeypatch):
    state = {"doc": plan(), "saved": []}
    async def latest(db, user):
        return SimpleNamespace(doc=state["doc"].model_dump_json())
    async def save(db, user, doc, summary):
        state["doc"] = doc
        state["saved"].append(summary)
        return len(state["saved"])
    async def prices(db, doc):
        return PX
    class DB:
        async def commit(self):
            pass
    monkeypatch.setattr(plan_ai, "latest_rev", latest)
    monkeypatch.setattr(plan_ai, "_save_rev", save)
    monkeypatch.setattr(plan_ai, "prices", prices)
    def write(tool, args):
        return asyncio.run(plan_ai._write(DB(), 1, tool, args))
    return state, write


def test_실제_쓰기_순서로_실행후_잔고갱신과_후속계획을_함께_저장한다(store):
    state, write = store
    actual = [h.model_dump(mode="json") for h in positions(473, 30, 6674888)]
    write("node_update", {"id": "b1", "fields": {"holdings": actual, "status": "realized", "executed_at": "2026-10-30"}})
    assert state["doc"].nodes[1].execution is None
    write("holdings_set", {"holdings": actual, "as_of": "2026-10-30"})
    d = state["doc"]
    assert d.nodes[1].execution.before[1].qty == 400 and d.nodes[1].execution.after[1].qty == 473
    assert [h.qty for h in d.nodes[-1].holdings][1:] == [548, 41]
    assert all(h.amount is None for h in d.holdings)
    assert not ip.stale_branches(d)
    snapshot = d.nodes[1].execution.model_dump_json()
    forged = d.nodes[1].execution.model_copy(deep=True)
    forged.before[1].qty = 0
    assert not write("node_update", {"id": "b1", "fields": {"execution": forged.model_dump(mode="json")}})["saved"]
    assert state["doc"].nodes[1].execution.model_dump_json() == snapshot


def test_수량없는_새보유_저장은_기존문서에_영향을_주지_않는다(store):
    state, write = store
    original = state["doc"].model_dump_json()
    hs = [h.model_dump(mode="json") for h in state["doc"].holdings]
    hs[1].update(qty=None, amount=10000)
    with pytest.raises(ValueError, match="수량 확인 필요"):
        write("holdings_set", {"holdings": hs})
    assert state["doc"].model_dump_json() == original and not state["saved"]


def test_MCP는_외화마다_원단위환율과_시각을_반환한다(monkeypatch):
    async def latest(db, pairs):
        return {code: {"close": {"KRWUSD": 1400, "KRWJPY": 9}[code], "as_of": datetime(2026, 10, 30, 12)}
                for code, prefix in pairs if code in ("KRWUSD", "KRWJPY")}
    monkeypatch.setattr(market_ai, "_latest_quotes", latest)
    out = asyncio.run(market_ai.call(None, 1, "quotes_get", {"items": [], "currencies": ["KRW", "JPY", "THB"]}))
    assert out["fx_rates"]["KRW"]["close"] == 1
    assert out["fx_rates"]["JPY"] == {"close": 9, "as_of": "2026-10-30 12:00 KST", "unit": "원/JPY"}
    assert out["fx_rates"]["THB"]["close"] is None


def test_환율_변동이_외화_수량을_바꾸지_않고_자산과_상담에_반영된다(monkeypatch):
    rates = {"USD": 1400, "JPY": 9}
    async def latest(db, pairs):
        return {code: {"close": rates[code[3:]], "prev_close": rates[code[3:]] - 1,
                       "as_of": datetime(2026, 10, 30, 12)} for code, prefix in pairs if prefix == "f" and code[3:] in rates}
    monkeypatch.setattr(plan_v1, "_latest_quotes", latest)
    d = ip.PlanDoc(holdings=[cash(100, "JPY"), cash(2, "USD"), cash(500)])
    row = SimpleNamespace(doc=d.model_dump_json(), rev_id=1)
    async def run():
        a = await plan_v1.asset_view(None, row)
        assert a["total"] == 4200 and a["change"] == 102
        r = a["groups"][0]["items"][0]["rows"][0]
        assert r["qty"] == 100 and r["fx_rate"] == 9 and r["valuation"] == "fx"
        assert r["quote_at"] == "2026-10-30T12:00:00+09:00"
        rates["JPY"] = 10
        b = await plan_v1.asset_view(None, row)
        assert b["total"] == 4300 and b["groups"][0]["items"][0]["rows"][0]["qty"] == 100
        p = plan_ai.prompt({"doc": d, "assets": b}, None, ())
        assert '"currency":"JPY"' in p and '"fx_rate":10' in p and '"total":4300' in p
    asyncio.run(run())
