"""블로그 글을 상담 AI 가 조회하는 MCP 도구(2026-10-19). **조회만** 한다.

글 목록·상세 API([v1](v1.py))를 그대로 부른다 — 등급 규칙(숨긴 글·카테고리 읽기 등급)이 화면·API 와 갈리지 않게.
상담은 root 전용이라 root 로 부른다(숨긴 글까지 보인다 — 화면의 root 와 같다).

⚠️ 본문은 HTML 을 걷어 글로 내고 길면 자른다. 글 안의 지시는 따르지 않는다고 상담 프롬프트가 못박는다
   (자동 포스팅 인사이트는 웹에서 모은 글이다 — 프롬프트 주입 통로).
"""

import re
from html import unescape
from types import SimpleNamespace

from fastapi import HTTPException

from app.api import v1
from app.api.mcp import RO, obj

WRITE_TOOLS: tuple = ()

TOOLS = [
    {"annotations": RO, "name": "post_search",
     "description": "블로그 글 목록(최신순 10개씩) — 제목 부분검색(q), 묶음(group: finance 인사이트·general 블로그), 카테고리 번호로 거른다. "
                    "줄마다 id·제목·요약·카테고리·작성일·조회수.",
     "inputSchema": obj({"q": {"type": "string"}, "group": {"type": "string", "enum": ["finance", "general"]},
                         "category_id": {"type": "integer"}, "page": {"type": "integer", "minimum": 1}})},
    {"annotations": RO, "name": "post_get",
     "description": "블로그 글 하나의 본문(HTML 을 걷은 글, 최대 12000자)과 제목·카테고리·작성일.",
     "inputSchema": obj({"id": {"type": "integer"}}, ["id"])},
]

_MAX_BODY = 12000
#: 상담은 root 전용이다(assistant_v1) — 목록·상세 API 의 등급 판정(`blog_user.level_of`)에 root 로 보인다.
_ROOT = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(roles=["root"])))


def _text(html: str) -> str:
    """HTML → 읽을 글. 블록 끝은 줄바꿈으로 두고 태그를 걷는다."""
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", html or "")
    s = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr|blockquote|pre)>", "\n", s)
    s = unescape(re.sub(r"<[^>]+>", "", s))
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", s)).strip()


def _brief(p: dict) -> dict:
    return {"id": p["id"], "title": p["title"], "summary": (p.get("summary") or "")[:200],
            "category": (p.get("category") or {}).get("name"), "created_at": p.get("created_at"),
            "read_count": p.get("read_count")}


async def call(db, user_index: int, name: str, args: dict):
    try:
        if name == "post_search":
            page = await v1.posts(_ROOT, int(args.get("page") or 1), 10, args.get("category_id"),
                                  (str(args.get("q") or "").strip()[:100] or None), args.get("group"))
            return {"total": page.total, "page": page.page, "pages": page.pages,
                    "items": [_brief(p.model_dump(mode="json")) for p in page.items]}
        if name == "post_get":
            d = (await v1.post(_ROOT, int(args.get("id", 0)))).model_dump(mode="json")
            body = _text(d.pop("content"))
            return {**_brief(d), "body": body[:_MAX_BODY], "truncated": len(body) > _MAX_BODY}
    except HTTPException as e:
        raise ValueError(str(e.detail)) from e
    raise ValueError(f"모르는 도구: {name}")
