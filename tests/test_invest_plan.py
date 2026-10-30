"""투자 계획 문서(`app/services/invest_plan.py`) — 형식 검증·평가·AI 답 해석. DB 없이 본다."""

import asyncio
import json
from datetime import datetime, timedelta, timezone

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
    from app.api import assistant_v1
    p = assistant_v1.system_prompt(datetime(2026, 10, 10, 9, 0), [ip.plan_prompt(_doc())])
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
            ("ISA", "ISA 현금", "sell", 2_200_000.0, 2_200_000.0)]

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
        assert [(x["account"], x["side"], x["qty"]) for x in self._doc(after)["b"]] == [("ISA", "sell", 100), ("ISA", "buy", 1_000_000)]

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


class TestNotes:
    """원칙·기억(2026-10-14) — 문서 칸, 프롬프트, 변경 요약, 화면 저장 API(PUT /notes)."""

    def test_옛_문서는_빈_목록_줄은_공백을_뗀다(self):
        assert ip.PlanDoc.model_validate({}).rules == []
        assert ip.PlanDoc.model_validate({"rules": ["  레버리지 안 씀 "]}).rules == ["레버리지 안 씀"]

    @pytest.mark.parametrize("data", [{"rules": [""]}, {"memory": ["가" * 301]}, {"rules": ["x"] * 31}, {"memory": ["x"] * 51}])
    def test_빈_줄_긴_줄_한도_초과는_거절(self, data):
        with pytest.raises(ValueError):
            ip.PlanDoc.model_validate(data)

    def test_상담과_점검_프롬프트에_늘_싣는다(self):
        doc = ip.PlanDoc.model_validate({"rules": ["레버리지 ETF 안 씀"], "memory": ["상여는 1월·7월"]})
        now = datetime(2026, 10, 14, 12, 0, tzinfo=timezone(timedelta(hours=9)))
        for prompt in (ip.plan_prompt(doc), ip.daily_prompt(doc, now)):
            assert "- 레버리지 ETF 안 씀" in prompt and "- 상여는 1월·7월" in prompt
        assert "(없음)" in ip.plan_prompt(ip.PlanDoc())

    def test_변경_요약(self):
        old = ip.PlanDoc()
        assert ip.diff_summary(old, ip.PlanDoc(rules=["a"], memory=["b"])) == "원칙 갱신, 기억 갱신"

    def _api(self, monkeypatch, rev_id=5, doc=None):
        from contextlib import asynccontextmanager
        from types import SimpleNamespace
        from app.api import plan_v1

        state = {"row": SimpleNamespace(rev_id=rev_id, doc=ip.PlanDoc.model_validate(doc or {}).model_dump_json()),
                 "saved": []}

        class DB:
            async def commit(self):
                pass

        @asynccontextmanager
        async def session():
            yield DB()

        async def owner(db, request):
            return SimpleNamespace(user_index=1)

        async def latest(db, u):
            return state["row"]

        async def save(db, u, new, summary):
            state["saved"].append(summary)
            state["row"] = SimpleNamespace(rev_id=state["row"].rev_id + 1, doc=new.model_dump_json())

        async def view(db, row):
            return {"rev_id": row.rev_id, "doc": json.loads(row.doc)}

        for name, fn in (("db_session", session), ("owner", owner), ("latest_rev", latest), ("_save_rev", save),
                         ("plan_view", view)):
            monkeypatch.setattr(plan_v1, name, fn)
        return (lambda body: asyncio.run(plan_v1.put_notes(None, plan_v1.NotesIn(**body)))), state

    def test_저장은_새_버전_빈_줄은_뺀다(self, monkeypatch):
        put, state = self._api(monkeypatch)
        out = put({"rules": ["레버리지 안 씀", "  "], "memory": ["상여 1월"], "base_rev_id": 5})
        assert out["saved"] and out["prev_rev_id"] == 5 and out["rev_id"] == 6 and out["doc"]["rules"] == ["레버리지 안 씀"]
        assert state["saved"] == ["원칙 갱신, 기억 갱신"]

    def test_바뀐_게_없으면_버전을_안_쌓는다(self, monkeypatch):
        put, state = self._api(monkeypatch, doc={"rules": ["a"]})
        assert not put({"rules": ["a"], "base_rev_id": 5})["saved"] and state["saved"] == []

    def test_그_사이_바뀌었으면_409_긴_줄은_422(self, monkeypatch):
        from fastapi import HTTPException
        put, _ = self._api(monkeypatch)
        with pytest.raises(HTTPException) as e:
            put({"rules": ["a"], "base_rev_id": 4})
        assert e.value.status_code == 409
        with pytest.raises(HTTPException) as e:
            put({"rules": ["가" * 301], "base_rev_id": 5})
        assert e.value.status_code == 422


class TestIntegrity:
    """2026-10-14 검토(반론자)에서 나온 검사 — 환산에 필요한 market, 이벤트마다 실현 가지 하나, 복기 비교 범위, 되돌리기 충돌."""

    def test_종목은_market_이_있어야_한다(self):
        with pytest.raises(ValueError, match="market"):
            ip.Holding.model_validate({"kind": "stock", "name": "AAPL", "code": "AAPL", "qty": 1, "currency": "USD"})
        ip.Holding.model_validate({"kind": "cash", "name": "달러", "amount": 100, "currency": "USD"})   # 시세 없는 것은 그대로

    def test_실현_가지는_이벤트마다_하나(self):
        nodes = [{"id": "e", "kind": "event", "title": "FOMC", "at": "2026-10-29T03:00:00+09:00"},
                 {"id": "a", "parent": "e", "kind": "branch", "title": "인하", "status": "realized"},
                 {"id": "b", "parent": "e", "kind": "branch", "title": "동결", "status": "realized"}]
        with pytest.raises(ValueError, match="하나"):
            ip.PlanDoc.model_validate({"nodes": nodes})

    def test_그때만_빠진_보유가_있으면_비교하지_않는다(self):
        doc = ip.PlanDoc.model_validate({"holdings": [
            {"kind": "cash", "name": "예금", "amount": 100},
            {"kind": "stock", "name": "삼성전자", "code": "005930", "market": "KR", "qty": 1}], "nodes": [
            {"id": "e", "kind": "event", "title": "FOMC", "at": "2026-10-01T03:00:00+09:00"},
            {"id": "b", "parent": "e", "kind": "branch", "title": "동결"}]})
        now = ip.valuate(doc, {"005930": 100}, {}, None)
        then = ip.valuate(doc, {}, {}, None)            # 그때 시세 없음
        r = ip.retrospect(doc, now, {"e": then})["b"]
        assert r["missing"] == 1 and r["pct"] is None and r["change"] is None
        same = ip.retrospect(doc, now, {"e": ip.valuate(doc, {"005930": 50}, {}, None)})["b"]
        assert same["pct"] == pytest.approx(100 * (200 / 150 - 1))

    def test_되돌리기는_기대한_버전이_아니면_409(self, monkeypatch):
        from types import SimpleNamespace
        from fastapi import HTTPException
        from app.api import plan_v1

        async def latest(db, u):
            return SimpleNamespace(rev_id=7)
        monkeypatch.setattr(plan_v1, "latest_rev", latest)
        with pytest.raises(HTTPException) as e:
            asyncio.run(plan_v1._restore(None, 1, 5, expect=6))
        assert e.value.status_code == 409


def test_바뀐_것_줄():
    old = ip.PlanDoc.model_validate({"rules": ["a", "b"], "holdings": [
        {"kind": "cash", "name": "예금", "amount": 1, "account": "저축"},
        {"kind": "stock", "name": "TIGER 200", "code": "102110", "market": "KR", "qty": 1, "account": "ISA"}]})
    new = ip.PlanDoc.model_validate({"rules": ["a", "c"], "memory": ["m"], "holdings": [
        {"kind": "stock", "name": "TIGER 200", "code": "102110", "market": "KR", "qty": 2, "account": "ISA"},
        {"kind": "stock", "name": "삼성전자", "code": "005930", "market": "KR", "qty": 1}]})
    assert ip.change_lines(old, new) == ["원칙 + ‘c’", "원칙 − ‘b’", "기억 + ‘m’",
                                         "보유 − 예금 · 저축", "보유 ~ TIGER 200 · ISA", "보유 + 삼성전자"]


def test_원칙_기억_도구가_닫힌_상담은_프롬프트가_알린다():
    assert "원칙(기억)으로 남길까요?\" 하고 물어라" in ip.plan_prompt(ip.PlanDoc(), notes_open=False)
    assert "열려 있다" in ip.plan_prompt(ip.PlanDoc())


class TestAccountsDebts:
    """계좌 목록·부채(2026-10-17 사용자: LLM 이 잘 정리하게 구조적으로, 부채는 (나) 따로 두고 주거는 전액)."""

    ACC = [{"name": "ISA", "institution": "NH투자증권", "type": "invest", "principal": 2_000_000},
           {"name": "주거", "type": "housing"}]
    HOLD = [{"kind": "cash", "name": "예수금", "amount": 1_000_000, "account": "ISA"},
            {"kind": "stock", "name": "TIGER 200", "code": "102110", "market": "KR", "qty": 10, "account": "ISA"},
            {"kind": "other", "name": "전세보증금", "amount": 150_000_000, "account": "주거"}]
    DEBT = [{"name": "전세대출", "lender": "NH농협", "balance": 100_000_000, "rate": 1.5, "account": "주거"}]

    def test_계좌_목록에_없는_계좌는_거절(self):
        with pytest.raises(ValidationError, match="계좌 목록"):
            ip.PlanDoc.model_validate({"accounts": self.ACC, "holdings": self.HOLD + [{"kind": "cash", "name": "x", "amount": 1, "account": "입출금"}]})
        with pytest.raises(ValidationError, match="계좌 목록"):   # 가지 보유도 본다
            ip.PlanDoc.model_validate({"accounts": self.ACC, "holdings": self.HOLD, "nodes": [
                {"id": "e", "kind": "event", "title": "e", "at": "2026-11-01T09:00:00+09:00"},
                {"id": "b", "parent": "e", "kind": "branch", "title": "b", "holdings": [{"kind": "cash", "name": "x", "amount": 1, "account": "ISA2"}]}]})
        with pytest.raises(ValidationError, match="계좌 목록"):   # 부채의 연결 계좌도
            ip.PlanDoc.model_validate({"accounts": self.ACC, "holdings": self.HOLD, "debts": [{**self.DEBT[0], "account": "집"}]})
        # 옛 문서(계좌 목록 없음)는 그대로 읽힌다
        assert ip.PlanDoc.model_validate({"holdings": [{"kind": "cash", "name": "x", "amount": 1, "account": "아무거나"}]})

    def test_순자산과_계좌_표(self):
        doc = ip.PlanDoc.model_validate({"accounts": self.ACC, "holdings": self.HOLD, "debts": self.DEBT,
                                         "cashflow": [{"kind": "saving", "name": "ISA 납입", "amount": 300_000, "account": "ISA"}]})
        v = ip.valuate(doc, {"102110": 90_000}, {}, None)
        assert v["root"]["total"] == 151_900_000 and v["root"]["net"] == 51_900_000
        # 유형이 빈 보유는 계좌의 유형을 쓴다(화면 유형별 비중)
        assert [r["type"] for r in v["root"]["rows"]] == ["invest", "invest", "housing"]
        isa, home = ip.account_view(doc, v)
        assert isa["value"] == 1_900_000 and isa["pnl"] == -100_000 and round(isa["pnl_pct"], 1) == -5.0 and isa["monthly"] == 300_000
        assert home["debt"] == 100_000_000 and home["pnl"] is None

    def test_AI_뼈대와_바뀐_것에_계좌·부채(self):
        old = ip.PlanDoc.model_validate({"accounts": self.ACC, "holdings": self.HOLD})
        new = ip.PlanDoc.model_validate({"accounts": self.ACC, "holdings": self.HOLD, "debts": self.DEBT})
        o = ip.outline(new)
        assert o["accounts"][0] == {"name": "ISA", "institution": "NH투자증권", "type": "invest", "principal": 2_000_000.0}
        assert o["debts"][0]["balance"] == 100_000_000 and o["debts"][0]["rate"] == 1.5
        assert "부채 + 전세대출" in ip.change_lines(old, new) and "부채 갱신" in ip.diff_summary(old, new)
