"""상담 중 codex 가 조회하는 MCP(`app/api/plan_mcp.py`) — 토큰·JSON-RPC 껍데기. DB 를 건드리지 않는 것만 본다."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import plan_mcp

app = FastAPI()
app.include_router(plan_mcp.router)
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
    t = plan_mcp.issue(7)
    assert _rpc(t, "ping").json()["result"] == {}
    plan_mcp.revoke(t)
    assert _rpc(t, "ping").status_code == 401


def test_초기화와_도구_목록():
    t = plan_mcp.issue(7)
    init = _rpc(t, "initialize", {"protocolVersion": "2025-06-18"}).json()["result"]
    assert init["protocolVersion"] == "2025-06-18" and "tools" in init["capabilities"]
    names = [x["name"] for x in _rpc(t, "tools/list").json()["result"]["tools"]]
    assert names == ["plan_get", "node_get", "plan_revisions", "plan_revision_get", "quotes_get", "stock_search",
                     "node_add", "node_update", "node_delete", "holdings_set", "cashflow_set", "rules_set", "memory_set"]
    assert set(plan_mcp.WRITE_TOOLS) == set(names[6:])
    plan_mcp.revoke(t)


def test_알림은_202_모르는_메서드는_오류():
    t = plan_mcp.issue(7)
    assert _rpc(t, "notifications/initialized", mid=None).status_code == 202
    assert _rpc(t, "resources/list").json()["error"]["code"] == -32601
    assert client.get("/mcp").status_code == 405
    plan_mcp.revoke(t)


class TestWrite:
    """쓰기 도구 — 지금 버전을 고쳐 검증하고 새 버전으로 쌓는다. DB 대신 가짜 버전 저장소를 끼운다."""

    def _store(self, monkeypatch, doc):
        import asyncio
        from types import SimpleNamespace
        from app.api import plan_v1
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

        monkeypatch.setattr(plan_v1, "latest_rev", latest_rev)
        monkeypatch.setattr(plan_v1, "_save_rev", save_rev)
        monkeypatch.setattr(plan_v1, "prices", prices)
        run = lambda name, args: asyncio.run(plan_mcp._write(DB(), 1, name, args))
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

    def test_상담이_쌓은_버전을_토큰이_기억한다(self, monkeypatch):
        import asyncio
        self._store(monkeypatch, self.BASE)

        class DB:
            async def commit(self):
                pass

        t = plan_mcp.issue(1)
        for _ in range(2):   # 두 번째는 변경 없음 — 쌓이지 않는다
            asyncio.run(plan_mcp._write(DB(), 1, "rules_set", {"rules": ["a"]}, plan_mcp._TOKENS[t]["revs"]))
        assert plan_mcp.revoke(t) == [101] and plan_mcp.revoke(t) == []

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
    t = plan_mcp.issue(7, read_only=True)
    r = _rpc(t, "tools/call", {"name": "node_delete", "arguments": {"id": "x"}}).json()["result"]
    plan_mcp.revoke(t)
    assert r["isError"] and "조회만" in r["content"][0]["text"]


def test_원칙_기억은_연_상담에서만_쓴다():
    t = plan_mcp.issue(7, allow=tuple(x for x in plan_mcp.WRITE_TOOLS if x not in plan_mcp.NOTE_TOOLS))
    names = [x["name"] for x in _rpc(t, "tools/list").json()["result"]["tools"]]
    r = _rpc(t, "tools/call", {"name": "memory_set", "arguments": {"memory": ["x"]}}).json()["result"]
    plan_mcp.revoke(t)
    assert "memory_set" not in names and "rules_set" not in names and "node_add" in names
    assert r["isError"] and "시킨 상담에서만" in r["content"][0]["text"]
    ro = plan_mcp.issue(7, read_only=True)
    names = [x["name"] for x in _rpc(ro, "tools/list").json()["result"]["tools"]]
    plan_mcp.revoke(ro)
    assert not set(names) & set(plan_mcp.WRITE_TOOLS) and "plan_get" in names


def test_원칙_기억을_여는_말():
    from app.api import plan_v1
    assert "rules_set" in plan_v1.write_tools_for("레버리지는 원칙으로 남겨")
    assert "memory_set" in plan_v1.write_tools_for("그거 잊어 줘")
    tools = plan_v1.write_tools_for("FOMC 가지 만들어 줘")
    assert "memory_set" not in tools and "rules_set" not in tools and "node_add" in tools
