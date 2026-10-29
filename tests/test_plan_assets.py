"""실제 보유 자산 — 분류·대출 한 번 차감·미평가액·현재 시세·상담 전달을 검증한다."""

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import plan_ai, plan_v1
from app.main import app
from app.services import invest_plan as ip
from app.services import plan_assets as assets


def doc(**fields):
    base = {
        "as_of": "2026-10-29",
        "accounts": [{"name": "은행", "type": "cash"}, {"name": "적금", "type": "saving"},
                     {"name": "ISA", "type": "invest"}, {"name": "IRP", "type": "pension"},
                     {"name": "주거", "type": "housing"}],
        "holdings": [{"kind": "cash", "name": "입출금", "amount": 100, "account": "은행"},
                     {"kind": "cash", "name": "적금", "amount": 200, "account": "적금"},
                     {"kind": "stock", "name": "주식", "code": "005930", "market": "KR", "qty": 2, "account": "ISA"},
                     {"kind": "stock", "name": "주식", "code": "005930", "market": "KR", "qty": 3, "account": "IRP"},
                     {"kind": "other", "name": "보증금", "amount": 1000, "account": "주거"}],
        "debts": [{"name": "전세 대출", "balance": 600, "account": "주거"},
                  {"name": "신용 대출", "balance": 50, "account": "은행"}],
    }
    base.update(fields)
    return ip.PlanDoc.model_validate(base)


def summary(d=None, now=None, before=None, fx=1400, prev_fx=1300):
    d = d or doc()
    current = ip.valuate(d, now if now is not None else {"005930": 100}, {}, fx)["root"]
    previous = ip.valuate(d, before if before is not None else {"005930": 90}, {}, prev_fx)["root"]
    return assets.summarize(d, current, previous)


def test_다섯_기존_유형을_세_그룹으로_합치고_부채는_정확히_한_번_뺀다():
    s = summary()
    assert [(g["label"], g["value"]) for g in s["groups"]] == [("현금성", 300), ("투자성", 500), ("부동산", 400)]
    assert s["other_debt"] == 50 and s["total"] == 1150
    assert sum(g["value"] for g in s["groups"]) - s["other_debt"] == s["total"]
    assert s["stock_total"] == 500 and s["change"] == 50
    assert s["stock_weight_pct"] == 43.48
    assert [(r["account"], r["qty"], r["value"]) for r in s["stocks"]] == [("ISA", 2, 200), ("IRP", 3, 300)]


def test_명시된_보유_유형이_계좌_기본값보다_우선한다():
    d = doc()
    d.holdings[0].type = "invest"
    s = summary(d)
    assert [g["value"] for g in s["groups"]] == [200, 600, 400]


def test_여러_부동산의_대출을_서로_빼지_않는다():
    d = doc()
    d.accounts.append(ip.Account(name="두번째 집", type="housing"))
    d.holdings.append(ip.Holding(kind="other", name="집", amount=2000, account="두번째 집"))
    d.debts += [ip.Debt(name="주담대", balance=1700, account="두번째 집"), ip.Debt(name="전세 추가", balance=100, account="주거")]
    s = summary(d)
    assert [a["value"] for a in s["groups"][2]["items"]] == [300, 300]
    assert s["groups"][2]["value"] == 600
    assert s["total"] == 1350


def test_대출이_부동산보다_크면_음수도_그대로_표시한다():
    d = doc()
    d.debts[0].balance = 1200
    s = summary(d)
    assert s["groups"][2]["value"] == -200 and s["total"] == 550


def test_보유가_비어도_연결된_부동산_대출은_사라지지_않는다():
    s = summary(doc(holdings=[]))
    assert s["groups"][2]["value"] == -600 and s["total"] == -650


def test_연결_없는_대출을_이름만_보고_부동산에서_빼지_않는다():
    s = summary(doc(debts=[{"name": "주택 대출", "balance": 600}]))
    assert s["groups"][2]["value"] == 1000 and s["other_debt"] == 600


def test_계좌가_없는_부동산의_이름을_연결_계좌로_간주하지_않는다():
    d = ip.PlanDoc(holdings=[ip.Holding(kind="other", type="housing", name="주거", amount=1000)],
                   debts=[ip.Debt(name="대출", account="주거", balance=600)])
    s = summary(d)
    assert s["groups"][2]["value"] == 1000 and s["other_debt"] == 600 and s["total"] == 400


def test_시세_누락은_0원_대신_미확인이고_합계도_불완전하다():
    s = summary(now={})
    assert s["total"] is None and s["stock_total"] is None and s["missing"] == 2
    assert s["groups"][1]["value"] is None and s["known_total"] == 650
    assert s["change"] is None


def test_입력_평가액_대체를_최신_시세로_오인하지_않는다():
    d = doc()
    d.holdings[2].amount = 210
    d.holdings[3].amount = 330
    s = summary(d, now={})
    assert s["total"] == 1190 and s["estimated"] == 2 and s["missing"] == 0
    assert s["change"] is None and all(r["estimated"] for r in s["stocks"])
    assert all(r["valuation"] == "input" for r in s["stocks"])


def test_전일_시세_없을때_입력_평가액으로_손익을_꾸미지_않는다():
    d = doc()
    d.holdings[2].amount = 210
    assert summary(d, before={})["change"] is None


def test_해외_주식은_가격과_환율을_모두_반영한다():
    d = doc(holdings=[{"kind": "stock", "name": "미국 주식", "code": "AAPL", "market": "US", "qty": 2, "account": "ISA"}], debts=[])
    s = summary(d, now={"AAPL": 100}, before={"AAPL": 90})
    assert s["stock_total"] == 280000 and s["change"] == 46000
    assert s["stocks"][0]["weight"] == 1


def test_달러_예금도_환율_변동을_반영한다():
    d = doc(holdings=[{"kind": "cash", "name": "달러", "amount": 100, "currency": "USD", "account": "은행"}], debts=[])
    s = summary(d)
    assert s["total"] == 140000 and s["change"] == 10000


def test_예전_문서도_자산종류로_분류한다():
    d = ip.PlanDoc(holdings=[ip.Holding(kind="cash", name="현금", amount=100), ip.Holding(kind="bond", name="채권", amount=200)])
    assert [g["value"] for g in summary(d)["groups"]] == [100, 200, 0]


def test_미래_가지의_종목을_현재_잔고에_섞거나_조회하지_않는다(monkeypatch):
    d = doc(nodes=[{"id": "e", "kind": "event", "title": "미래", "at": "2027-01-01T09:00:00+09:00"},
                   {"id": "b", "kind": "branch", "parent": "e", "title": "계획", "holdings": [
                       {"kind": "stock", "name": "미래 종목", "code": "MSFT", "market": "US", "qty": 500, "account": "ISA"}]}])
    async def quotes(db, current):
        assert current.nodes == [] and ip.price_pairs(current) == (["005930"], [])
        return {"stocks": {"005930": {"close": 100, "prev_close": 90, "as_of": datetime(2026, 10, 30, 9)}}, "coins": {}, "fx": None}
    monkeypatch.setattr(plan_v1, "_quotes", quotes)
    row = SimpleNamespace(doc=d.model_dump_json(), rev_id=7)
    s = asyncio.run(plan_v1.asset_view(None, row))
    assert s["rev_id"] == 7 and s["total"] == 1150 and s["stock_total"] == 500
    assert all(r["quote_at"] == "2026-10-30T09:00:00+09:00" for r in s["stocks"])
    p = plan_ai.prompt({"doc": d, "assets": s}, None, ())
    assert '"stock_total":500.0' in p and '"total":1150.0' in p
    assert '"qty":2.0' in p and '"qty":3.0' in p
    assert "현재 주식 비중(전체 순자산 기준): 43.48%" in p
    assert "이미 대출을 차감한 순액" in p


@pytest.mark.parametrize(("at", "expected"), [(datetime(2026, 7, 1, 9, 30), "2026-07-01T22:30:00+09:00"),
                                                (datetime(2026, 11, 2, 9, 30), "2026-11-02T23:30:00+09:00")])
def test_미국_시세_시각을_서머타임에_맞춰_원화_패널에_전달한다(at, expected):
    d = doc(holdings=[{"kind": "stock", "name": "미국 주식", "code": "AAPL", "market": "US", "qty": 2, "account": "ISA"}], debts=[])
    q = {"stocks": {"AAPL": {"close": 100, "prev_close": 90, "as_of": at}}, "coins": {},
         "fx": {"close": 1400, "prev_close": 1300}}
    s = plan_v1._assets(d, None, q, ip.valuate(d, {"AAPL": 100}, {}, 1400)["root"])
    assert s["stocks"][0]["quote_at"] == expected


def test_개인_자산_API는_쿠키만으로_읽을_수_없다():
    with TestClient(app) as client:
        response = client.get("/api/v1/plan/assets")
        assert response.status_code == 401
