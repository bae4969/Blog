"""투자 계획 문서(`app/services/invest_plan.py`) — 형식 검증·평가·AI 답 해석. DB 없이 본다."""

import json
from datetime import datetime

import pytest
from pydantic import ValidationError

from app.services import invest_plan as ip


def _doc(**kw):
    base = {
        "holdings": [
            {"kind": "stock", "name": "삼성전자", "code": "005930", "market": "KR", "qty": 10},
            {"kind": "bond", "name": "TLT", "code": "TLT", "market": "US", "qty": 5},
            {"kind": "cash", "name": "예금", "amount": 1_000_000},
        ],
        "nodes": [
            {"id": "fomc", "kind": "event", "title": "FOMC", "at": "2026-10-29T03:00:00+09:00"},
            {"id": "cut", "parent": "fomc", "kind": "branch", "title": "인하",
             "holdings": [{"kind": "stock", "name": "삼성전자", "code": "005930", "market": "KR", "qty": 20}]},
            {"id": "hold", "parent": "fomc", "kind": "branch", "title": "동결"},
        ],
    }
    base.update(kw)
    return ip.PlanDoc.model_validate(base)


class TestTree:
    def test_정상(self):
        assert len(_doc().nodes) == 3

    @pytest.mark.parametrize("nodes, msg", [
        ([{"id": "a", "kind": "branch", "title": "x"}], "가지의 부모는 이벤트"),
        ([{"id": "e", "kind": "event", "title": "x"}], "at"),
        ([{"id": "e", "kind": "event", "title": "x", "at": "2026-10-29T00:00:00", "parent": "zz"}], "없다"),
        ([{"id": "e", "kind": "event", "title": "x", "at": "2026-10-29T00:00:00"},
          {"id": "e", "kind": "event", "title": "y", "at": "2026-10-29T00:00:00"}], "겹친다"),
        ([{"id": "e1", "kind": "event", "title": "x", "at": "2026-10-29T00:00:00"},
          {"id": "e2", "parent": "e1", "kind": "event", "title": "y", "at": "2026-10-29T00:00:00"}], "이벤트의 부모는 가지"),
        ([{"id": "e", "parent": "b", "kind": "event", "title": "x", "at": "2026-10-29T00:00:00"},
          {"id": "b", "parent": "e", "kind": "branch", "title": "y"}], "순환"),
        ([{"id": "e1", "kind": "event", "title": "x", "at": "2026-10-29T03:00:00+09:00"},
          {"id": "b", "parent": "e1", "kind": "branch", "title": "y"},
          {"id": "e2", "parent": "b", "kind": "event", "title": "z", "at": "2026-10-28T10:00:00"}], "늦어야"),
    ])
    def test_잘못된_트리(self, nodes, msg):
        with pytest.raises(ValidationError, match=msg):
            ip.PlanDoc.model_validate({"nodes": nodes})


class TestValuate:
    def test_수량_시세_환율(self):
        v = ip.valuate(_doc(), {"005930": 100.0, "TLT": 2.0}, {}, 1000.0)
        root = v["root"]
        assert [r["value"] for r in root["rows"]] == [1000.0, 10_000.0, 1_000_000.0]
        assert root["total"] == 1_011_000.0

    def test_가지는_자기_보유_없으면_부모_상태(self):
        v = ip.valuate(_doc(), {"005930": 100.0, "TLT": 2.0}, {}, 1000.0)
        assert v["cut"]["total"] == 2000.0
        assert v["hold"]["total"] == v["root"]["total"] == v["fomc"]["total"]

    def test_시세가_없으면_None_이고_합계에서_빠진다(self):
        v = ip.valuate(_doc(), {"005930": 100.0}, {}, None)
        assert v["root"]["rows"][1]["value"] is None
        assert v["root"]["total"] == 1_001_000.0

    def test_시세_요청_목록(self):
        assert ip.price_pairs(_doc()) == (["005930", "TLT"], [])


def test_변경_요약은_서버가_센다():
    old = _doc()
    new = old.model_copy(deep=True)
    new.nodes = new.nodes[:2]
    new.holdings = new.holdings[:1]
    assert ip.diff_summary(old, new) == "노드 1개 삭제, 보유 자산 갱신"


def test_프롬프트에_문서와_시각이_들어간다():
    p = ip.system_prompt(_doc(), datetime(2026, 10, 10, 9, 0))
    assert "2026-10-10 09:00" in p and '"fomc"' in p
    body = p.split("```json\n", 1)[1].split("\n```", 1)[0]     # 실린 뼈대 JSON
    assert '"holdings":[{"kind":"stock"' in body          # 지금 보유는 싣는다
    assert '"condition"' not in body and '"holdings":null' not in body and '"about"' not in body   # 노드 상세 칸은 싣지 않는다


class TestOwner:
    """투자 계획은 root(0) 본인 전용 — 관리자(1)도 404 다(있다는 사실도 알리지 않는다)."""

    @pytest.mark.parametrize("level, ok", [(0, True), (1, False), (3, False)])
    def test_root_만(self, monkeypatch, level, ok):
        import asyncio
        from fastapi import HTTPException
        from app.api import plan_v1
        from app.core.blog_user import BlogUser

        async def find(db, user):
            return BlogUser(user_index=1, user_id="u", level=level, posting_count=0, posting_limit=1)
        monkeypatch.setattr(plan_v1, "bearer_user", lambda request: object())
        monkeypatch.setattr(plan_v1.blog_user, "find", find)
        if ok:
            assert asyncio.run(plan_v1.owner(None, None)).level == 0
        else:
            with pytest.raises(HTTPException) as e:
                asyncio.run(plan_v1.owner(None, None))
            assert e.value.status_code == 404


class TestDetailFields:
    """이벤트 개요·시장 예상·출처, 가지 조건(2026-10-10) — 옛 문서는 빈 값으로 읽히고, 출처는 http(s) 만."""

    def test_옛_문서도_읽힌다(self):
        n = _doc().nodes[0]
        assert (n.about, n.expect, n.links, n.condition) == ("", "", [], "")

    def test_출처는_http_만(self):
        base = {"id": "e", "kind": "event", "title": "x", "at": "2026-10-29T00:00:00"}
        ok = ip.PlanDoc.model_validate({"nodes": [{**base, "links": [{"title": "연준", "url": "https://fed.gov/x"}]}]})
        assert ok.nodes[0].links[0].url == "https://fed.gov/x"
        with pytest.raises(ValidationError):
            ip.PlanDoc.model_validate({"nodes": [{**base, "links": [{"title": "x", "url": "javascript:alert(1)"}]}]})


class TestAccount:
    """보유의 계좌 칸(2026-10-11) — 옛 문서는 None, 같은 종목도 계좌마다 따로 평가된다."""

    def test_옛_문서는_계좌_없음(self):
        assert all(h.account is None for h in _doc().holdings)

    def test_같은_종목_두_계좌는_따로_평가(self):
        h = [{"kind": "stock", "name": "TIGER 200", "code": "102110", "market": "KR", "qty": q, "account": a}
             for q, a in ((100, "ISA"), (37, "IRP"))]
        rows = ip.valuate(_doc(holdings=h, nodes=[]), {"102110": 1000.0}, {}, None)["root"]["rows"]
        assert [(r["account"], r["value"]) for r in rows] == [("ISA", 100_000.0), ("IRP", 37_000.0)]

    def test_프롬프트_뼈대에_계좌가_실린다(self):
        h = [{"kind": "cash", "name": "현금", "amount": 1, "account": "ISA"}]
        assert ip.outline(_doc(holdings=h, nodes=[]))["holdings"][0]["account"] == "ISA"


class TestGroupAndType:
    """자산군의 국내/해외(`group`)와 유형 칸(2026-10-11) — region 이 비면 미국 시장만 해외로 본다."""

    @pytest.mark.parametrize("h, g", [
        ({"kind": "stock", "name": "삼성전자", "code": "005930", "market": "KR", "qty": 1}, "stock_kr"),
        ({"kind": "bond", "name": "TLT", "code": "TLT", "market": "US", "qty": 1}, "bond_global"),
        ({"kind": "stock", "name": "TIGER 미국S&P500", "code": "360750", "market": "KR", "qty": 1, "region": "GLOBAL"}, "stock_global"),
        ({"kind": "bond", "name": "직접 보유 국채", "amount": 1}, "bond_kr"),
        ({"kind": "cash", "name": "예금", "amount": 1, "region": "GLOBAL"}, "cash"),
    ])
    def test_자산군_칸(self, h, g):
        assert ip.group(ip.Holding.model_validate(h)) == g

    def test_평가_줄에_칸과_유형이_실린다(self):
        h = [{"kind": "other", "name": "전세보증금 순액", "amount": 10_000_000, "type": "housing"}]
        row = ip.valuate(_doc(holdings=h, nodes=[]), {}, {}, None)["root"]["rows"][0]
        assert (row["group"], row["type"]) == ("other", "housing")

    def test_모르는_유형은_거부(self):
        with pytest.raises(ValidationError):
            ip.Holding.model_validate({"kind": "cash", "name": "x", "amount": 1, "type": "주택"})


class TestTrades:
    """매매표(2026-10-11) — 직전 보유 대비 가지 보유의 차이. 계좌별로 매도 → 매수 → 현금 순."""

    def _doc(self, after):
        base = [{"kind": "stock", "name": "TIGER 200", "code": "102110", "market": "KR", "qty": 100, "account": "ISA"},
                {"kind": "stock", "name": "TIGER 200", "code": "102110", "market": "KR", "qty": 37, "account": "IRP"},
                {"kind": "cash", "name": "ISA 현금", "amount": 5_000_000, "account": "ISA"}]
        nodes = [{"id": "e", "kind": "event", "title": "FOMC", "at": "2026-10-29T03:00:00+09:00"},
                 {"id": "b", "parent": "e", "kind": "branch", "title": "매수", "holdings": after},
                 {"id": "k", "parent": "e", "kind": "branch", "title": "유지"}]
        d = _doc(holdings=base, nodes=nodes)
        return ip.trades(d, ip.valuate(d, {"102110": 10_000.0, "484790": 8_000.0}, {}, None))

    def test_계좌별_매도_매수_현금(self):
        after = [{"kind": "stock", "name": "TIGER 200", "code": "102110", "market": "KR", "qty": 80, "account": "ISA"},
                 {"kind": "bond", "name": "KODEX 미국30년", "code": "484790", "market": "KR", "qty": 300, "account": "ISA"},
                 {"kind": "stock", "name": "TIGER 200", "code": "102110", "market": "KR", "qty": 37, "account": "IRP"},
                 {"kind": "cash", "name": "ISA 현금", "amount": 2_800_000, "account": "ISA"}]
        t = self._doc(after)
        assert "k" not in t
        assert [(x["account"], x["code"] or x["name"], x["side"], x["qty"], x["value"]) for x in t["b"]] == [
            ("ISA", "102110", "sell", 20, 200_000.0),
            ("ISA", "484790", "buy", 300, 2_400_000.0),
            ("ISA", "ISA 현금", "sell", None, 2_200_000.0)]

    def test_시세_없는_종목은_직전_단가로(self):
        h = lambda q: {"kind": "bond", "name": "국채", "code": "999999", "market": "KR", "qty": q, "amount": 800_000, "account": "ISA"}
        nodes = [{"id": "e", "kind": "event", "title": "FOMC", "at": "2026-10-29T03:00:00+09:00"},
                 {"id": "b", "parent": "e", "kind": "branch", "title": "매수", "holdings": [h(300)]}]
        d = _doc(holdings=[h(100)], nodes=nodes)
        assert ip.trades(d, ip.valuate(d, {}, {}, None))["b"][0]["value"] == 1_600_000

    def test_보유가_없는_가지는_매매표가_없다(self):
        t = self._doc(None)
        assert "b" not in t and "k" not in t

    def test_팔아서_없어진_종목(self):
        after = [{"kind": "stock", "name": "TIGER 200", "code": "102110", "market": "KR", "qty": 37, "account": "IRP"},
                 {"kind": "cash", "name": "ISA 현금", "amount": 6_000_000, "account": "ISA"}]
        assert [(x["account"], x["side"], x["qty"]) for x in self._doc(after)["b"]] == [("ISA", "sell", 100), ("ISA", "buy", None)]

    def test_실행일_칸은_옛_문서에서_비어_있고_뼈대에_실린다(self):
        d = _doc()
        assert all(n.executed_at is None for n in d.nodes)
        nodes = [{"id": "e", "kind": "event", "title": "FOMC", "at": "2026-10-29T03:00:00+09:00"},
                 {"id": "b", "parent": "e", "kind": "branch", "title": "인하", "status": "realized", "executed_at": "2026-10-30"}]
        assert ip.outline(_doc(nodes=nodes))["nodes"][1]["executed_at"] == "2026-10-30"


class TestCashflow:
    """월 현금흐름(2026-10-11) — 합계·여유, 이벤트까지 지나는 달 수 × 계좌별 납입."""

    FLOW = [{"kind": "income", "name": "월급", "amount": 3_000_000},
            {"kind": "fixed", "name": "대출 이자", "amount": 300_000},
            {"kind": "living", "name": "생활비", "amount": 1_000_000},
            {"kind": "saving", "name": "청년도약", "amount": 700_000, "account": "저축"},
            {"kind": "saving", "name": "ISA 적립", "amount": 500_000, "account": "ISA"}]

    def test_옛_문서는_빈_목록(self):
        d = _doc()
        assert d.cashflow == [] and ip.cashflow_summary(d) is None and ip.accruals(d, datetime(2026, 10, 11).date()) == {}

    def test_합계와_여유(self):
        s = ip.cashflow_summary(_doc(cashflow=self.FLOW))
        assert (s["income"], s["saving"], s["surplus"]) == (3_000_000, 1_200_000, 500_000)

    @pytest.mark.parametrize("end, m", [("2026-10-29", 0), ("2026-11-10", 0), ("2026-11-11", 1), ("2026-12-10", 1), ("2027-10-11", 12)])
    def test_달_수(self, end, m):
        from datetime import date
        assert ip.months_between(date(2026, 10, 11), date.fromisoformat(end)) == m

    def test_예상_적립은_계좌별이고_가지는_이벤트_날짜(self):
        nodes = [{"id": "e", "kind": "event", "title": "12월", "at": "2026-12-12T04:00:00+09:00"},
                 {"id": "b", "parent": "e", "kind": "branch", "title": "인하"},
                 {"id": "soon", "kind": "event", "title": "곧", "at": "2026-10-29T03:00:00+09:00"}]
        a = ip.accruals(_doc(as_of="2026-10-11", nodes=nodes, cashflow=self.FLOW), datetime(2026, 10, 11).date())
        assert a["e"] == {"months": 2, "total": 2_400_000, "by_account": {"저축": 1_400_000, "ISA": 1_000_000}}
        assert a["b"] == a["e"] and "soon" not in a

    def test_프롬프트_뼈대와_변경_요약(self):
        d = _doc(cashflow=self.FLOW)
        assert ip.outline(d)["cashflow"][3] == {"kind": "saving", "name": "청년도약", "amount": 700_000, "account": "저축"}
        assert ip.diff_summary(_doc(), d) == "현금흐름 갱신"


def test_대화는_글로_펴고_이미지는_따로():
    from app.api.plan_v1 import _flatten
    prompt, images = _flatten([
        {"role": "system", "content": "지시"},
        {"role": "assistant", "content": "이전 답"},
        {"role": "user", "content": [{"type": "text", "text": "이걸 읽어 줘"},
                                     {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]},
    ])
    assert prompt == "지시\n\n[상담가]\n이전 답\n\n[사용자]\n이걸 읽어 줘"
    assert images == ["data:image/png;base64,AAAA"]


class TestRetrospect:
    """복기 — 지난 이벤트의 가지마다 그때(이벤트 시각 시세)→지금(오늘 시세)."""

    def test_그때와_지금_평가(self):
        doc = _doc()   # fomc(2026-10-29) 아래 cut(삼성전자 20주)·hold(부모 그대로)
        now = ip.valuate(doc, {"005930": 120.0, "TLT": 2.0}, {}, 1000.0)
        then = {"fomc": ip.valuate(doc, {"005930": 100.0, "TLT": 2.0}, {}, 1000.0)}
        r = ip.retrospect(doc, now, then)
        assert r["cut"]["then"] == 2000.0 and r["cut"]["now"] == 2400.0
        assert r["cut"]["change"] == 400.0 and round(r["cut"]["pct"], 1) == 20.0 and r["cut"]["missing"] == 0
        assert r["hold"]["change"] == 200.0          # 삼성전자 10주 × 20원
        assert set(r) == {"cut", "hold"}

    def test_그때_시세가_없으면_빠진_수를_센다(self):
        doc = _doc()
        r = ip.retrospect(doc, ip.valuate(doc, {"005930": 120.0, "TLT": 2.0}, {}, 1000.0),
                          {"fomc": ip.valuate(doc, {"005930": 100.0}, {}, None)})   # TLT·환율 없음
        assert r["hold"]["missing"] == 1

    def test_지난_이벤트만(self):
        from datetime import datetime, timedelta, timezone
        kst = timezone(timedelta(hours=9))
        assert [e.id for e in ip.past_events(_doc(), datetime(2026, 10, 29, 3, 0, tzinfo=kst))] == ["fomc"]
        assert ip.past_events(_doc(), datetime(2026, 10, 29, 2, 59, tzinfo=kst)) == []
