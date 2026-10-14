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

        monkeypatch.setattr(plan_v1, "latest_rev", latest_rev)
        monkeypatch.setattr(plan_v1, "_save_rev", save_rev)
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
