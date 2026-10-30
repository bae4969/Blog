"""KRX 원/g 식별·평가·공유 캐시·실패 대체와 상담 전달을 검증한다."""

import asyncio
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest

from app.api import market_ai, plan_ai, plan_v1
from app.services import invest_plan as ip
from app.services import naver_gold as gold


def response(**fields):
    row = {"reutersCode": ip.GOLD_CODE, "stockExchangeType": {"code": "KRX"}, "unit": "원/g",
           "closePriceRaw": "173000", "closePrice": "173,000", "fluctuations": "-190",
           "localTradedAt": "2026-10-29T15:19:55+09:00", "marketStatus": "CLOSE"}
    row.update(fields)
    return {"pollingInterval": 70000, "datas": [row]}


def holding(**fields):
    return ip.Holding.model_validate({"kind": "other", "name": "KRX 금현물 35g(매입 약 720만)",
                                     "amount": 6211860, "account": "금현물", **fields})


def document(h=None):
    return ip.PlanDoc(as_of="2026-10-29", accounts=[ip.Account(name="금현물", type="invest")],
                      holdings=[h if h is not None else holding()])


@pytest.fixture(autouse=True)
def clear_cache(monkeypatch):
    monkeypatch.setattr(gold, "_quote", None)
    monkeypatch.setattr(gold, "_next_fetch", 0)
    monkeypatch.setattr(gold, "_interval", 30)
    monkeypatch.setattr(gold, "_lock", asyncio.Lock())


def test_네이버_KRX_시세와_전일가격_거래시각을_파싱한다():
    q, interval = gold.parse_quote(response())
    assert (q["close"], q["prev_close"], interval) == (173000, 173190, 70)
    assert q["as_of"] == datetime(2026, 10, 29, 15, 19, 55)
    assert q["unit"] == "원/g" and not q["stale"] and q["market_status"] == "CLOSE"
    body = response()
    body["pollingInterval"] = 7000
    del body["datas"][0]["closePrice"]
    assert gold.parse_quote(body)[1] == 30


@pytest.mark.parametrize("fields", [
    {"reutersCode": "GCcv1"}, {"stockExchangeType": {"code": "BANK"}}, {"unit": "USD/oz"},
    {"closePriceRaw": "0"}, {"closePriceRaw": "-1"}, {"closePriceRaw": "NaN"},
    {"fluctuations": "173000"}, {"localTradedAt": "2026-10-29T15:19:55"}, {"localTradedAt": "오류"},
])
def test_다른_금상품이나_잘못된_시세를_평가에_쓰지_않는다(fields):
    with pytest.raises((ValueError, StopIteration)):
        gold.parse_quote(response(**fields))


@pytest.mark.parametrize(("fields", "grams"), [
    ({}, 35), ({"name": "KRX 금현물 0.5g"}, 0.5),
    ({"name": "금현물", "code": ip.GOLD_CODE, "market": "KR", "qty": 0}, 0),
    ({"name": "금현물", "code": ip.GOLD_CODE, "market": "KR", "qty": 35.5}, 35.5),
    ({"name": "금현물 약 35g"}, None), ({"name": "KRX 금현물 35주"}, None),
    ({"name": "KRX 금현물"}, None), ({"kind": "stock"}, None), ({"currency": "USD"}, None),
    ({"code": "411060", "market": "KR", "qty": 2}, None),
])
def test_명시된_KRX_그램만_읽고_금액이나_금ETF로_추정하지_않는다(fields, grams):
    assert ip.gold_grams(holding(**fields)) == grams


def test_보유문서를_변경하지_않고_그램으로_평가한다():
    doc = document()
    original = doc.model_dump_json()
    assert ip.price_pairs(doc) == ([ip.GOLD_CODE], [])
    row = ip.valuate(doc, {ip.GOLD_CODE: 173000}, {}, None)["root"]["rows"][0]
    assert (row["value"], row["qty"], row["quantity_unit"], row["price"]) == (6055000, 35, "g", 173000)
    assert doc.model_dump_json() == original
    assert ip.valuate(doc, {}, {}, None)["root"]["rows"][0]["value"] == 6211860


def test_금현물_공유캐시_지연시각_유지_재시도_동시조회(monkeypatch):
    clock = [100.0]
    calls = []
    fail = [False]
    monkeypatch.setattr(gold, "monotonic", lambda: clock[0])
    async def fetch():
        calls.append(clock[0])
        await asyncio.sleep(0)
        if fail[0]:
            raise httpx.ReadTimeout("검증용 네트워크 실패")
        return response()
    monkeypatch.setattr(gold, "_fetch", fetch)
    async def run():
        first = await asyncio.gather(*(gold.quote() for _ in range(8)))
        assert len(calls) == 1 and all(q == first[0] for q in first)
        clock[0] = 169.9
        assert await gold.quote() == first[0] and len(calls) == 1
        clock[0] = 170
        fail[0] = True
        old = await gold.quote()
        assert old == {**first[0], "stale": True} and len(calls) == 2
        assert (await gold.quote())["stale"] and len(calls) == 2
        clock[0] = 240
        fail[0] = False
        assert not (await gold.quote())["stale"] and len(calls) == 3
    asyncio.run(run())


def test_최초_실패는_가격을_만들지_않고_잘못된응답도_캐시한다(monkeypatch):
    calls = []
    async def fetch():
        calls.append(1)
        return {"datas": []}
    monkeypatch.setattr(gold, "_fetch", fetch)
    async def run():
        q = await gold.quote()
        assert q["close"] is None and q["as_of"] is None and q["stale"]
        assert await gold.quote() == q and len(calls) == 1
    asyncio.run(run())


@pytest.mark.parametrize("body", [None, [], {"datas": [None, "오류"]}])
def test_외부응답_형식이_깨져도_저장평가액으로_대체한다(monkeypatch, body):
    async def fetch():
        return body
    monkeypatch.setattr(gold, "_fetch", fetch)
    q = asyncio.run(gold.quote())
    assert q["stale"] and q["close"] is None


@pytest.mark.parametrize("state", ["fresh", "stale", "missing"])
def test_자산과_상담과_MCP가_같은_금시세와_지연여부를_받는다(monkeypatch, state):
    q, _ = gold.parse_quote(response())
    if state != "fresh":
        q["stale"] = True
    if state == "missing":
        q.update(close=None, prev_close=None, as_of=None)
    async def latest(db, pairs):
        assert all(code != ip.GOLD_CODE for code, _ in pairs)
        return {}
    async def quote():
        return deepcopy(q)
    monkeypatch.setattr(plan_v1, "_latest_quotes", latest)
    monkeypatch.setattr(market_ai, "_latest_quotes", latest)
    monkeypatch.setattr(gold, "quote", quote)
    async def run():
        doc = document()
        row = SimpleNamespace(doc=doc.model_dump_json(), rev_id=1)
        s = await plan_v1.asset_view(None, row)
        item = s["groups"][1]["items"][0]["rows"][0]
        assert s["total"] == (6211860 if state == "missing" else 6055000)
        assert s["stock_total"] == 0 and not s["stocks"]
        assert s["change"] == (None if state == "missing" else -6650)
        assert s["stale"] == int(state != "fresh") and s["estimated"] == int(state == "missing")
        assert item["quantity_unit"] == "g" and item["qty"] == 35
        assert item["quote_source"] == "naver_krx_gold"
        assert item["quote_at"] == (None if state == "missing" else "2026-10-29T15:19:55+09:00")
        p = plan_ai.prompt({"doc": doc, "assets": s}, None, ())
        assert '"gold":[{' in p and '"quantity_unit":"g"' in p and str(int(s["total"])) in p
        mcp = await market_ai.call(None, 1, "quotes_get", {"items": [{"code": ip.GOLD_CODE, "market": "KR"}]})
        assert mcp["quotes"][0]["close"] == q["close"] and mcp["quotes"][0]["stale"] == q["stale"]
    asyncio.run(run())


def test_금현물이_없는_포트폴리오는_외부조회하지_않는다(monkeypatch):
    async def fail():
        raise AssertionError("불필요한 네이버 요청")
    monkeypatch.setattr(gold, "quote", fail)
    asyncio.run(gold.add_quote(["005930"], {}))
