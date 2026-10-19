"""모든 화면 아래 시트의 AI 상담(`app/api/assistant_v1.py`) — 기능 모듈을 끼워 흐름만 본다. DB·codex 없이."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import assistant_v1, mcp


def test_대화는_글로_펴고_이미지는_따로():
    prompt, images = assistant_v1._flatten([
        {"role": "system", "content": "지시"},
        {"role": "assistant", "content": "이전 답"},
        {"role": "user", "content": [{"type": "text", "text": "이걸 읽어 줘"},
                                     {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]},
    ])
    assert prompt == "지시\n\n[상담가]\n이전 답\n\n[사용자]\n이걸 읽어 줘"
    assert images == ["data:image/png;base64,AAAA"]


@pytest.mark.parametrize("level, ok", [(0, True), (1, False), (3, False)])
def test_root_만(monkeypatch, level, ok):
    from app.core.blog_user import BlogUser

    async def find(db, user):
        return BlogUser(user_index=1, user_id="u", level=level, posting_count=0, posting_limit=1)
    monkeypatch.setattr(assistant_v1, "bearer_user", lambda request: object())
    monkeypatch.setattr(assistant_v1.blog_user, "find", find)
    if ok:
        assert asyncio.run(assistant_v1._root(None, None)).level == 0
    else:
        with pytest.raises(HTTPException) as e:
            asyncio.run(assistant_v1._root(None, None))
        assert e.value.status_code == 404


class TestContext:
    CTX = {"page": "stock", "title": "삼성전자", "path": "/stocks/view?code=005930", "code": "005930", "market": "KR"}

    def test_요청에서_버려지지_않는다(self):
        # ⚠️ 기본값(None)과 다른 값으로 잰다 — 선언이 빠져 버려져도 기본값이면 통과해 버린다(2026-08-23 교훈)
        assert assistant_v1.ChatIn.model_validate({"message": "이거 어때", "context": self.CTX}).context == self.CTX

    def test_너무_크면_종류_제목_주소만(self):
        big = {**self.CTX, "config": {"x": "가" * 5000}}
        assert assistant_v1.fit_context(big) == {"page": "stock", "title": "삼성전자", "path": "/stocks/view?code=005930",
                                                 "note": "화면 정보가 커서 뺐다"}
        assert assistant_v1.fit_context(self.CTX) == self.CTX

    def test_표시_줄과_상세(self):
        assert assistant_v1.context_label(self.CTX) == "[화면: 삼성전자 · /stocks/view?code=005930]"
        assert assistant_v1.context_detail(self.CTX) == '{"page":"stock","code":"005930","market":"KR"}'
        assert assistant_v1.context_label(None) == "" and assistant_v1.context_detail({"title": "x"}) == ""


class FakeModule:
    """쓰기 도구 하나짜리 기능 모듈 — 상담이 모듈의 넷(begin·prompt·tools_for·finish)만으로 도는지 본다."""
    TOOLS = [{"name": "thing_set", "annotations": mcp.RW}]
    WRITE_TOOLS = ("thing_set",)

    def __init__(self):
        self.seen = {}

    async def begin(self, db, user_index):
        return {"before": 1}

    def prompt(self, state, now, allow):
        self.seen["allow"] = allow
        return f"# 가짜 모듈 {state['before']}"

    async def finish(self, db, user_index, state, made):
        self.seen["made"] = made
        if not made:
            return None
        return {"source": "fake", "tail": "\n\n[바뀐 것]\n- 하나", "meta": {"badge": "가짜 #5"},
                "toast": "고쳤습니다", "undo": {"label": "되돌리기", "method": "POST", "url": "/x", "done": "되돌렸습니다"},
                "note": ""}


@pytest.fixture
def fake(monkeypatch):
    mod, rows, asked = FakeModule(), [], {}

    class DB:
        async def execute(self, stmt, params=None):
            rows.append(params)
            return SimpleNamespace(lastrowid=len(rows))

        async def commit(self):
            pass

    @asynccontextmanager
    async def session():
        yield DB()

    async def ask(cfg, messages, user_index, tools):
        asked.update(messages=messages, tools=tools)
        return "  답입니다  ", [{"tool": "thing_set", "saved": True, "rev_id": 5}, {"tool": "other", "saved": True}], asked.get("error")

    monkeypatch.setattr(mcp, "MODULES", [mod])
    monkeypatch.setattr(assistant_v1, "db_session", session)
    monkeypatch.setattr(assistant_v1, "_ask", ask)
    return mod, rows, asked


def test_모듈이_프롬프트와_상담_뒤_요약을_낸다(fake):
    mod, rows, asked = fake
    ctx = {"page": "stock", "title": "삼성전자", "path": "/stocks/view?code=005930", "code": "005930"}
    out = asyncio.run(assistant_v1._chat(1, "이거 사도 돼?", [], ctx, {}, [], {mod: {"before": 1}}))

    system, user = asked["messages"][0]["content"], asked["messages"][-1]["content"][0]["text"]
    assert "개인 AI 비서" in system and "# 가짜 모듈 1" in system
    assert user == '[화면: 삼성전자 · /stocks/view?code=005930]\n화면 정보: {"page":"stock","code":"005930"}\n이거 사도 돼?'
    assert asked["tools"] == ("thing_set",) == mod.seen["allow"]
    assert mod.seen["made"] == [{"tool": "thing_set", "saved": True, "rev_id": 5}]     # 자기 도구의 쓰기만 받는다

    assert out["reply"] == "답입니다\n\n[바뀐 것]\n- 하나" and out["meta"] == {"badge": "가짜 #5"}
    assert out["changes"] == [{"source": "fake", "toast": "고쳤습니다", "note": "",
                               "undo": {"label": "되돌리기", "method": "POST", "url": "/x", "done": "되돌렸습니다"}}]
    # 대화에는 화면 표시 줄을 붙여 남긴다(상세 JSON 은 이번 질문에만) — 사용자 말, 답 순서
    assert rows[0]["c"] == "[화면: 삼성전자 · /stocks/view?code=005930]\n이거 사도 돼?" and rows[0]["r"] == "user"
    assert rows[1]["r"] == "assistant" and rows[1]["m"] == '{"badge": "가짜 #5"}'


def test_맥락_없이_이미지만(fake):
    mod, rows, asked = fake
    asyncio.run(assistant_v1._chat(1, "", ["data:image/png;base64,AAAA"], None, {}, [], {mod: {"before": 1}}))
    assert asked["messages"][-1]["content"][0]["text"] == "이미지를 읽어 줘."
    assert rows[0]["c"] == "[이미지 1장]"


def test_실패해도_그_전에_고친_것은_알린다(fake):
    mod, rows, asked = fake
    asked["error"] = "AI 가 600초 안에 답하지 않았습니다"
    with pytest.raises(HTTPException) as e:
        asyncio.run(assistant_v1._chat(1, "가지 만들어", [], None, {}, [], {mod: {"before": 1}}))
    assert e.value.status_code == 502 and e.value.detail["message"].startswith("AI 가 600초")
    assert [c["source"] for c in e.value.detail["changes"]] == ["fake"]
    assert rows == []   # 대화에는 남기지 않는다


def test_시스템_프롬프트에_시각():
    assert "2026-10-19 09:30" in assistant_v1.system_prompt(datetime(2026, 10, 19, 9, 30), ["", "조각"])
