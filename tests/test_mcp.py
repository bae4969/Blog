"""상담 중 codex 가 조회하는 MCP — 본체(`app/api/mcp.py`: 토큰·JSON-RPC·모듈 등록)와 투자 계획 도구(`app/api/plan_ai.py`).
DB 를 건드리지 않는 것만 본다."""

import ast
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import blog_ai, market_ai, mcp, plan_ai

mcp.register(plan_ai, market_ai, blog_ai)
app = FastAPI()
app.include_router(mcp.router)
client = TestClient(app)


def _rpc(token, method, params=None, mid=1):
    body = {"jsonrpc": "2.0", "method": method, "params": params or {}}
    if mid is not None:
        body["id"] = mid
    return client.post("/mcp", json=body, headers={"Authorization": f"Bearer {token}"} if token else {})


def test_토큰이_없거나_틀리면_401():
    assert _rpc(None, "tools/list").status_code == 401
    assert _rpc("nope", "tools/list").status_code == 401


def test_회수한_토큰은_못_쓴다():
    t = mcp.issue(7)
    assert _rpc(t, "ping").json()["result"] == {}
    mcp.revoke(t)
    assert _rpc(t, "ping").status_code == 401


def test_초기화와_도구_목록():
    t = mcp.issue(7)
    init = _rpc(t, "initialize", {"protocolVersion": "2025-06-18"}).json()["result"]
    assert init["protocolVersion"] == "2025-06-18" and "tools" in init["capabilities"]
    names = [x["name"] for x in _rpc(t, "tools/list").json()["result"]["tools"]]
    assert names[:13] == ["plan_get", "node_get", "plan_revisions", "plan_revision_get",
                          "node_add", "node_update", "node_delete", "holdings_set", "cashflow_set", "accounts_set", "debts_set",
                          "rules_set", "memory_set"]
    assert set(plan_ai.WRITE_TOOLS) == set(names[4:13]) == set(mcp.write_tools())
    assert {"quotes_get", "stock_search", "stock_candles", "stock_disclosures", "market_heatmap", "index_quotes",
            "watchlist_get", "backtest_portfolios", "backtest_portfolio_get", "post_search", "post_get"} <= set(names[13:])
    assert len(names) == len(set(names))   # 모듈끼리 이름이 겹치지 않는다
    mcp.revoke(t)


def test_알림은_202_모르는_메서드는_오류():
    t = mcp.issue(7)
    assert _rpc(t, "notifications/initialized", mid=None).status_code == 202
    assert _rpc(t, "resources/list").json()["error"]["code"] == -32601
    assert client.get("/mcp").status_code == 405
    mcp.revoke(t)


class TestWrite:
    """쓰기 도구 — 지금 버전을 고쳐 검증하고 새 버전으로 쌓는다. DB 대신 가짜 버전 저장소를 끼운다."""

    def _store(self, monkeypatch, doc):
        import asyncio
        from types import SimpleNamespace
        from app.services import invest_plan as ip

        saved = []
        state = {"doc": ip.PlanDoc.model_validate(doc)}

        async def latest_rev(db, u):
            return SimpleNamespace(doc=state["doc"].model_dump_json())

        async def save_rev(db, u, new, summary):
            state["doc"] = new
            saved.append(summary)
            return len(saved) + 100

        class DB:
            async def commit(self):
                pass

        async def prices(db, doc):
            return state.get("px", {}), {}, None

        monkeypatch.setattr(plan_ai, "latest_rev", latest_rev)
        monkeypatch.setattr(plan_ai, "_save_rev", save_rev)
        monkeypatch.setattr(plan_ai, "prices", prices)
        run = lambda name, args: asyncio.run(plan_ai._write(DB(), 1, name, args))
        return run, state, saved

    BASE = {"nodes": [{"id": "e", "kind": "event", "title": "FOMC", "at": "2026-10-29T03:00:00+09:00"},
                      {"id": "b", "parent": "e", "kind": "branch", "title": "인하"},
                      {"id": "e2", "parent": "b", "kind": "event", "title": "12월", "at": "2026-12-10T04:00:00+09:00"}]}

    def test_추가_수정_삭제(self, monkeypatch):
        run, state, saved = self._store(monkeypatch, self.BASE)
        assert run("node_add", {"node": {"id": "h", "parent": "e", "kind": "branch", "title": "동결"}})["rev_id"] == 101
        run("node_update", {"id": "h", "fields": {"condition": "금리 유지", "id": "바꾸면안됨"}})
        assert [n.condition for n in state["doc"].nodes if n.id == "h"] == ["금리 유지"]
        out = run("node_delete", {"id": "b"})           # 아래 e2 까지 함께
        assert out["summary"] == "노드 삭제: b 외 1개"
        assert [n.id for n in state["doc"].nodes] == ["e", "h"]
        run("holdings_set", {"holdings": [{"kind": "cash", "name": "예금", "amount": 100}], "as_of": "2026-10-10"})
        assert state["doc"].holdings[0].amount == 100 and len(saved) == 4

    def test_계좌_칸이_쓰기_뒤에도_남는다(self, monkeypatch):
        run, state, _ = self._store(monkeypatch, self.BASE)
        h = [{"kind": "stock", "name": "TIGER 200", "code": "102110", "market": "KR", "qty": 100, "account": "ISA"}]
        run("holdings_set", {"holdings": h})
        run("node_update", {"id": "b", "fields": {"holdings": [{**h[0], "qty": 50}, {**h[0], "qty": 50, "account": "IRP"}]}})
        assert state["doc"].holdings[0].account == "ISA"
        assert [x.account for x in state["doc"].nodes[1].holdings] == ["ISA", "IRP"]

    @pytest.mark.parametrize("name,args", [("holdings_set", {"holding": []}), ("cashflow_set", {}),
                                           ("rules_set", {"rules": "문자열"}), ("memory_set", {"memo": ["x"]})])
    def test_통째로_바꾸는_도구는_키가_없으면_비우지_않고_거절(self, monkeypatch, name, args):
        run, state, saved = self._store(monkeypatch, {**self.BASE, "holdings": [{"kind": "cash", "name": "예금", "amount": 1}],
                                                      "rules": ["a"], "memory": ["b"]})
        with pytest.raises(ValueError, match="목록이 없습니다"):
            run(name, args)
        assert saved == [] and state["doc"].holdings and state["doc"].rules == ["a"]

    def test_상담이_저장한_쓰기를_토큰이_기억한다(self, monkeypatch):
        self._store(monkeypatch, self.BASE)

        class DB:
            async def commit(self):
                pass

        @asynccontextmanager
        async def session():
            yield DB()

        monkeypatch.setattr(mcp, "db_session", session)
        t = mcp.issue(1)
        for _ in range(2):   # 두 번째는 변경 없음 — 쌓이지 않는다
            r = _rpc(t, "tools/call", {"name": "rules_set", "arguments": {"rules": ["a"]}}).json()["result"]
            assert not r.get("isError")
        made = mcp.revoke(t)
        assert [(w["tool"], w["rev_id"]) for w in made] == [("rules_set", 101)] and mcp.revoke(t) == []

    FUND = {"holdings": [{"kind": "cash", "name": "예수금", "amount": 1_000_000, "account": "ISA"},
                         {"kind": "stock", "name": "TIGER 200", "code": "102110", "market": "KR", "qty": 10, "account": "ISA"}],
            "nodes": [{"id": "e", "kind": "event", "title": "FOMC", "at": "2026-10-29T03:00:00+09:00"}]}

    def _branch(self, cash, qty, account="ISA"):
        return {"id": "b", "parent": "e", "kind": "branch", "title": "인하", "holdings": [
            {"kind": "cash", "name": "예수금", "amount": cash, "account": "ISA"},
            {"kind": "stock", "name": "TIGER 200", "code": "102110", "market": "KR", "qty": qty, "account": account}]}

    def test_판_것보다_많이_사면_거절(self, monkeypatch):
        run, state, saved = self._store(monkeypatch, self.FUND)
        state["px"] = {"102110": 100_000}                       # 실행 전 ISA 200만
        with pytest.raises(ValueError, match="재원 초과"):
            run("node_add", {"node": self._branch(1_000_000, 30)})   # 현금 그대로 20주 더 — 400만
        assert saved == []
        out = run("node_add", {"node": self._branch(0, 20)})        # 현금 100만으로 10주 — 200만
        assert out["saved"]

    def test_다른_계좌로_옮기면_거절(self, monkeypatch):
        run, state, _ = self._store(monkeypatch, self.FUND)
        state["px"] = {"102110": 100_000}
        with pytest.raises(ValueError, match="IRP"):
            run("node_add", {"node": self._branch(1_000_000, 10, account="IRP")})

    def test_잔고가_바뀌면_가지는_다시_짜야_함(self, monkeypatch):
        from app.services import invest_plan as ip
        run, state, _ = self._store(monkeypatch, self.FUND)
        run("node_add", {"node": {**self._branch(1_000_000, 10), "base": "AI가_보낸_값"}})
        b = state["doc"].nodes[1]
        assert b.base and b.base != "AI가_보낸_값" and ip.stale_branches(state["doc"]) == set()
        run("node_update", {"id": "e", "fields": {"title": "10월 FOMC"}})       # 다른 노드를 고쳐도 기준은 그대로
        assert state["doc"].nodes[1].base == b.base
        run("holdings_set", {"holdings": self.FUND["holdings"] + [
            {"kind": "stock", "name": "삼성전자", "code": "005930", "market": "KR", "qty": 1, "account": "ISA"}]})
        assert ip.stale_branches(state["doc"]) == {"b"}

    def test_원칙_기억_쓰기(self, monkeypatch):
        run, state, saved = self._store(monkeypatch, self.BASE)
        assert run("rules_set", {"rules": ["레버리지 안 씀"]})["summary"] == "원칙 갱신"
        assert run("memory_set", {"memory": ["상여 1월·7월"]})["summary"] == "기억 갱신"
        assert state["doc"].rules == ["레버리지 안 씀"] and state["doc"].memory == ["상여 1월·7월"]
        assert run("rules_set", {"rules": []})["summary"] == "원칙 갱신" and state["doc"].rules == []
        with pytest.raises(ValueError):
            run("memory_set", {"memory": ["가" * 301]})

    def test_현금흐름_쓰기(self, monkeypatch):
        run, state, saved = self._store(monkeypatch, self.BASE)
        out = run("cashflow_set", {"cashflow": [{"kind": "income", "name": "월급", "amount": 3_000_000},
                                                {"kind": "saving", "name": "청년도약", "amount": 700_000, "account": "저축"}]})
        assert out["summary"] == "현금흐름 갱신" and [f.kind for f in state["doc"].cashflow] == ["income", "saving"]
        with pytest.raises(ValueError):
            run("cashflow_set", {"cashflow": [{"kind": "bonus", "name": "x", "amount": 1}]})
        assert len(saved) == 1

    def test_검증에_걸리면_저장하지_않는다(self, monkeypatch):
        import pytest
        run, state, saved = self._store(monkeypatch, self.BASE)
        with pytest.raises(ValueError, match="형식 오류"):
            run("node_add", {"node": {"id": "x", "parent": "e", "kind": "event", "title": "잘못", "at": "2026-11-01T00:00:00"}})
        with pytest.raises(ValueError, match="이미 있는 id"):
            run("node_add", {"node": {"id": "b", "parent": "e", "kind": "branch", "title": "겹침"}})
        with pytest.raises(ValueError, match="없는 노드"):
            run("node_update", {"id": "zz", "fields": {"title": "x"}})
        assert saved == []

    def test_바뀐_게_없으면_버전을_쌓지_않는다(self, monkeypatch):
        run, state, saved = self._store(monkeypatch, self.BASE)
        assert run("node_update", {"id": "b", "fields": {"title": "인하"}}) == {"saved": False, "summary": "변경 없음"}
        assert saved == []


def test_조회_전용_토큰은_쓰기_도구를_거절한다():
    t = mcp.issue(7, read_only=True)
    r = _rpc(t, "tools/call", {"name": "node_delete", "arguments": {"id": "x"}}).json()["result"]
    mcp.revoke(t)
    assert r["isError"] and "조회만" in r["content"][0]["text"]


def test_원칙_기억은_연_상담에서만_쓴다():
    t = mcp.issue(7, allow=tuple(x for x in plan_ai.WRITE_TOOLS if x not in plan_ai.NOTE_TOOLS))
    names = [x["name"] for x in _rpc(t, "tools/list").json()["result"]["tools"]]
    r = _rpc(t, "tools/call", {"name": "memory_set", "arguments": {"memory": ["x"]}}).json()["result"]
    mcp.revoke(t)
    assert "memory_set" not in names and "rules_set" not in names and "node_add" in names
    assert r["isError"] and "시킨 상담에서만" in r["content"][0]["text"]
    ro = mcp.issue(7, read_only=True)
    names = [x["name"] for x in _rpc(ro, "tools/list").json()["result"]["tools"]]
    mcp.revoke(ro)
    assert not set(names) & set(plan_ai.WRITE_TOOLS) and "plan_get" in names


def test_원칙_기억을_여는_말():
    assert "rules_set" in plan_ai.tools_for("레버리지는 원칙으로 남겨")
    assert "memory_set" in plan_ai.tools_for("그거 잊어 줘")
    tools = plan_ai.tools_for("FOMC 가지 만들어 줘")
    assert "memory_set" not in tools and "rules_set" not in tools and "node_add" in tools


def test_원칙_기억을_물었으면_다음_답에서_연다():
    # 직전 답이 "기억으로 남길까요?" 였으면 "ㅇㅇ" 에도 연다 — 안 열면 같은 질문만 되풀이했다(2026-10-16 운영)
    assert "memory_set" in plan_ai.tools_for("ㅇㅇ", "‘ISA는 저축·투자용’이라는 점을 기억으로 남길까요?")
    assert "rules_set" in plan_ai.tools_for("응", "원칙으로 남길까요?")
    assert "memory_set" not in plan_ai.tools_for("ㅇㅇ", "5년 이상 보유할 수 있을까요?")


def test_모르는_도구는_오류():
    t = mcp.issue(7)
    r = _rpc(t, "tools/call", {"name": "nope", "arguments": {}}).json()["result"]
    mcp.revoke(t)
    assert r["isError"] and "모르는 도구" in r["content"][0]["text"]


def test_조회_도구는_모두_읽기_전용_표시():
    # 표시가 없으면 비대화식 codex 가 승인을 기다리다 막힌다(2026-10-10 스파이크)
    for t in mcp.tools():
        assert t["annotations"]["readOnlyHint"] is (t["name"] not in mcp.write_tools()), t["name"]


def test_블로그_본문은_글로_편다():
    html = "<p>첫 줄&amp;둘</p><script>alert(1)</script><ul><li>가</li><li>나</li></ul>"
    assert blog_ai._text(html) == "첫 줄&둘\n가\n나"


def test_캔들은_물은_기간만_200개까지():
    from datetime import datetime, timedelta
    now = datetime.now() + timedelta(hours=9)
    rows = [{"at": (now - timedelta(days=d + 0.5)).strftime("%Y-%m-%dT%H:%M:%S"), "open": 1, "high": 2, "low": 0, "close": 1,
             "volume": 5} for d in range(400, -1, -1)]
    out = market_ai._rows(rows, True, 90)
    assert len(out) == 90 and out[-1][5] == 5 and len(market_ai._rows(rows, False, 365)) == 200


@pytest.mark.parametrize("name", ["mcp.py", "assistant_v1.py"])
def test_상담과_MCP_본체는_기능을_모른다(name):
    # 2026-10-19 사용자: 채팅을 코드로 투자 계획에서 떼어 내는 게 핵심 — 기능 모듈은 main.py 가 붙인다.
    src = (Path(__file__).parent.parent / "app" / "api" / name).read_text(encoding="utf-8")
    mods = [n.module or "" for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom)]
    mods += [a.name for n in ast.walk(ast.parse(src)) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names]
    assert not [m for m in mods if "plan" in m or "invest" in m], mods
