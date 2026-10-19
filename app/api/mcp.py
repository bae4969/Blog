"""`/mcp` — 상담 AI(codex)가 블로그 데이터를 조회하고 고치는 MCP 서버. **어느 기능도 모른다**(2026-10-19 분리).

codex 는 블로그 컨테이너 안에서 `codex exec` 로 돈다([assistant_v1](assistant_v1.py) — 상담, 투자 계획의 매일 점검).
그때 이 서버를 `-c mcp_servers.blog.url=…` 로 붙이고, 토큰은 환경변수로 넘긴다.

## 도구 모듈

도구는 기능별 모듈이 갖고, `main.py` 가 `register()` 로 붙인다(투자 계획 = [plan_ai](plan_ai.py) …). 모듈은
- `TOOLS` — 도구 정의 목록(MCP `tools/list` 형식). 조회 도구는 `RO` 표시를 단다.
- `WRITE_TOOLS` — 그중 쓰기 도구 이름. 상담이 연 것만 쓸 수 있다(`issue(allow=…)`).
- `async call(db, user_index, name, args)` — 결과(JSON 으로 낼 값). 쓰기는 `{"saved": True, …}` 를 돌려주면 토큰이 기억한다.
  잘못된 입력은 `ValueError(이유)` — AI 가 보고 고친다.
- (선택) `CLOSED_HINT` — 닫힌 쓰기 도구를 불렀을 때 AI 에게 줄 말.

## 인증 — 상담 한 번짜리 토큰

`issue()` 가 상담마다 무작위 토큰을 만들어 그 사람(`user_index`)에게 묶고, 상담이 끝나면 `revoke()` 한다.
토큰은 codex 자식 프로세스의 환경변수로만 건너가고 밖으로 나가지 않는다. 남의 데이터에는 닿을 수 없다.

## 프로토콜 — streamable HTTP 의 최소한

POST 로 JSON-RPC 한 통을 받아 JSON 으로 답한다(SSE 스트림은 열지 않는다 — GET 은 405).
`initialize`·`ping`·`tools/list`·`tools/call` 만 처리하고, 알림(id 없음)은 202 로 받기만 한다.
"""

import json
import secrets
import time

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse

from app.db.session import db_session

router = APIRouter()

#: 모든 도구가 읽기 전용이라는 표시. codex 는 `default_tools_approval_mode="writes"` 일 때 이게 붙은 도구만 승인 없이
#: 부른다 — 비대화식(`codex exec`)이라 승인할 사람이 없어, 이게 없으면 호출이 막힌다(2026-10-10 스파이크로 확인).
RO = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
#: 쓰기 도구 표시. codex 쪽은 도구별로 자동 승인을 따로 켠다(codex_runner — 비대화식이라 승인할 사람이 없다).
RW = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}
RW_DEL = {**RW, "destructiveHint": True}


def obj(props: dict | None = None, required: list | None = None) -> dict:
    """도구 입력 스키마 — 모르는 키는 받지 않는다."""
    return {"type": "object", "properties": props or {}, "required": required or [], "additionalProperties": False}


# ---------------------------------------------------------------------------
# 도구 모듈
# ---------------------------------------------------------------------------

MODULES: list = []


def register(*modules) -> None:
    for m in modules:
        if m not in MODULES:
            MODULES.append(m)


def tools() -> list[dict]:
    return [t for m in MODULES for t in m.TOOLS]


def write_tools() -> tuple:
    return tuple(name for m in MODULES for name in m.WRITE_TOOLS)


def _module_of(name: str):
    return next((m for m in MODULES if any(t["name"] == name for t in m.TOOLS)), None)


# ---------------------------------------------------------------------------
# 토큰
# ---------------------------------------------------------------------------

#: 토큰 → {user, exp(만료 시각), ro(조회만), allow(연 쓰기 도구), made(이 상담이 저장한 쓰기 결과)}. codex 는 한 번에
#: 하나라(codex_runner) 앞 실행을 기다리는 시간(최대 600초)과 실행 상한(600초)에 여유. 끝나면 revoke 하므로 길어도 남지 않는다.
_TOKENS: dict[str, dict] = {}
_TTL = 1260


def issue(user_index: int, read_only: bool = False, allow: tuple | None = None) -> str:
    """`read_only` 면 쓰기 도구를 서버가 거절한다(매일 점검 — codex 쪽 승인을 안 켜도 서버에서 한 번 더 막는다).
    `allow` 는 이 상담에 연 쓰기 도구(없으면 전부)."""
    now = time.time()
    for t, hit in list(_TOKENS.items()):   # 지난 것 청소
        if hit["exp"] < now:
            _TOKENS.pop(t, None)
    token = secrets.token_urlsafe(32)
    _TOKENS[token] = {"user": user_index, "exp": now + _TTL, "ro": read_only, "made": [],
                      "allow": set(write_tools() if allow is None else allow)}
    return token


def revoke(token: str) -> list[dict]:
    """토큰을 거두고 그 상담이 저장한 쓰기 결과들(`{"tool", **결과}`)을 돌려준다 — 모듈이 자기 것만 골라 요약·되돌리기를 만든다."""
    hit = _TOKENS.pop(token, None)
    return hit["made"] if hit else []


def _user_of(request: Request) -> dict | None:
    """토큰 항목 — 토큰이 없거나 만료면 None."""
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    hit = _TOKENS.get(header[7:].strip())
    return hit if hit and hit["exp"] > time.time() else None


# ---------------------------------------------------------------------------
# JSON-RPC
# ---------------------------------------------------------------------------

def _result(mid, result) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": mid, "result": result})


def _error(mid, code: int, message: str) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}})


def _text(mid, text: str, error: bool = False) -> JSONResponse:
    return _result(mid, {"content": [{"type": "text", "text": text}], **({"isError": True} if error else {})})


@router.get("/mcp", include_in_schema=False)
async def mcp_get():
    return Response(status_code=status.HTTP_405_METHOD_NOT_ALLOWED)


@router.post("/mcp", include_in_schema=False)
async def mcp(request: Request):
    who = _user_of(request)
    if who is None:
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)
    try:
        msg = await request.json()
    except ValueError:
        return _error(None, -32700, "JSON 이 아닙니다")
    if not isinstance(msg, dict):
        return _error(None, -32600, "요청 한 통씩 보내 주세요(배치는 받지 않습니다)")

    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:                       # 알림(notifications/initialized 등) — 받기만 한다
        return Response(status_code=status.HTTP_202_ACCEPTED)
    if method == "initialize":
        return _result(mid, {"protocolVersion": params.get("protocolVersion") or "2025-06-18",
                             "capabilities": {"tools": {}},
                             "serverInfo": {"name": "blog", "version": "1"}})
    if method == "ping":
        return _result(mid, {})
    writes = write_tools()
    if method == "tools/list":
        # 닫힌 쓰기 도구는 목록에서도 뺀다 — 프롬프트로 "부르지 말라"고 해도 불렀다(2026-10-14 실제 상담).
        return _result(mid, {"tools": [t for t in tools() if t["name"] not in writes
                                       or (not who["ro"] and t["name"] in who["allow"])]})
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        mod = _module_of(name)
        if mod is None:
            return _text(mid, f"모르는 도구: {name}", error=True)
        if name in writes and who["ro"]:
            return _text(mid, "조회만 하는 실행입니다 — 쓰기 도구는 쓸 수 없습니다", error=True)
        if name in writes and name not in who["allow"]:
            return _text(mid, f"이 상담에서는 {name} 을 쓸 수 없습니다. " + getattr(mod, "CLOSED_HINT", ""), error=True)
        try:
            async with db_session() as db:
                data = await mod.call(db, who["user"], name, args)
        except (ValueError, KeyError, TypeError) as e:
            return _text(mid, str(e), error=True)
        if name in writes and isinstance(data, dict) and data.get("saved"):
            who["made"].append({"tool": name, **data})
        return _text(mid, json.dumps(data, ensure_ascii=False, default=str))
    return _error(mid, -32601, f"모르는 메서드: {method}")
