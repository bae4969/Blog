"""`/mcp` — 투자 계획 상담 중에 codex 가 블로그 데이터를 조회하고 계획을 고치는 MCP 서버(2026-10-10).

codex 는 블로그 컨테이너 안에서 `codex exec` 로 돈다([plan_v1](plan_v1.py) `_ask`). 그때 이 서버를
`-c mcp_servers.blog.url=…` 로 붙이고, 토큰은 환경변수로 넘긴다.

- 조회 도구(읽기 전용 표시): 지금 계획·버전 이력·시세·종목 검색.
- 쓰기 도구: 노드 추가·수정·삭제, 보유 통째로 바꾸기. **계획을 고치는 길은 이것뿐이다**(전에 쓰던 답 끝의
  plan 블록은 2026-10-10 에 걷었다 — AI 가 노드 하나 고치려고 문서 전체를 다시 쓰다 빠뜨리는 일이 없게).
  쓰기마다 서버가 `PlanDoc` 으로 검증하고 통과하면 새 버전으로 쌓는다. 거부되면 이유를 AI 에게 돌려준다.

## 인증 — 상담 한 번짜리 토큰

`issue()` 가 상담마다 무작위 토큰을 만들어 그 사람(`user_index`)에게 묶고, 상담이 끝나면 `revoke()` 한다.
토큰은 codex 자식 프로세스의 환경변수로만 건너가고 밖으로 나가지 않는다. 남의 계획에는 닿을 수 없다.

## 프로토콜 — streamable HTTP 의 최소한

POST 로 JSON-RPC 한 통을 받아 JSON 으로 답한다(SSE 스트림은 열지 않는다 — GET 은 405).
`initialize`·`ping`·`tools/list`·`tools/call` 만 처리하고, 알림(id 없음)은 202 로 받기만 한다.
"""

import json
import secrets
import time

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.db.session import db_session
from app.services import invest_plan as ip
from app.ui.stocks import _latest_quotes, _stock_page

router = APIRouter()

#: 토큰 → (user_index, 만료 시각). 상담 상한(600초)보다 조금 길게.
_TOKENS: dict[str, tuple[int, float]] = {}
_TTL = 660


def issue(user_index: int) -> str:
    now = time.time()
    for t, (_, exp) in list(_TOKENS.items()):   # 지난 것 청소
        if exp < now:
            _TOKENS.pop(t, None)
    token = secrets.token_urlsafe(32)
    _TOKENS[token] = (user_index, now + _TTL)
    return token


def revoke(token: str) -> None:
    _TOKENS.pop(token, None)


def _user_of(request: Request) -> int | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    hit = _TOKENS.get(header[7:].strip())
    return hit[0] if hit and hit[1] > time.time() else None


# ---------------------------------------------------------------------------
# 도구
# ---------------------------------------------------------------------------

def _obj(props: dict | None = None, required: list | None = None) -> dict:
    return {"type": "object", "properties": props or {}, "required": required or [], "additionalProperties": False}


#: 모든 도구가 읽기 전용이라는 표시. codex 는 `default_tools_approval_mode="writes"` 일 때 이게 붙은 도구만 승인 없이
#: 부른다 — 비대화식(`codex exec`)이라 승인할 사람이 없어, 이게 없으면 호출이 막힌다(2026-10-10 스파이크로 확인).
_RO = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}

#: 쓰기 도구 표시. codex 쪽은 도구별로 자동 승인을 따로 켠다(codex_runner — 비대화식이라 승인할 사람이 없다).
_RW = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}
_RW_DEL = {**_RW, "destructiveHint": True}
#: 쓰기 도구 이름 — codex_runner 가 이 목록에만 자동 승인을 건다.
WRITE_TOOLS = ("node_add", "node_update", "node_delete", "holdings_set", "cashflow_set")

TOOLS = [
    {"annotations": _RO, "name": "plan_get", "description": "지금 계획 문서와 노드별 평가(오늘 시세·원화 환산 금액·환율), 월 현금흐름 합계(cashflow)와 이벤트까지의 예상 적립(accrual).",
     "inputSchema": _obj()},
    {"annotations": _RO, "name": "node_get",
     "description": "노드 하나의 모든 칸(개요·예상·조건·액션·보유 등)과 그 시점 평가(오늘 시세), 지난 이벤트면 복기.",
     "inputSchema": _obj({"id": {"type": "string"}}, ["id"])},
    {"annotations": _RO, "name": "plan_revisions", "description": "계획 버전 이력(최근 것부터 최대 50개) — 번호·시각·바뀐 것 요약. 보유 변화를 볼 때 쓴다.",
     "inputSchema": _obj()},
    {"annotations": _RO, "name": "plan_revision_get", "description": "특정 버전의 계획 문서와 평가(평가는 오늘 시세 기준).",
     "inputSchema": _obj({"rev_id": {"type": "integer"}}, ["rev_id"])},
    {"annotations": _RO, "name": "quotes_get", "description": "종목 최신 종가·직전 종가·등락률. market 은 KR·US·COIN. 원/달러 환율도 함께 준다.",
     "inputSchema": _obj({"items": {"type": "array", "maxItems": 30, "items": _obj(
         {"code": {"type": "string"}, "market": {"type": "string", "enum": ["KR", "US", "COIN"]}}, ["code", "market"])}},
         ["items"])},
    {"annotations": _RO, "name": "stock_search", "description": "종목 이름·코드로 검색(최대 10개) — 코드를 모를 때 쓴다. market 을 비우면 한국+미국.",
     "inputSchema": _obj({"q": {"type": "string"}, "market": {"type": "string", "enum": ["KR", "US", "COIN"]}}, ["q"])},
    {"annotations": _RW, "name": "node_add",
     "description": "노드(이벤트·가지) 하나를 더한다. node 는 계획 문서 형식의 노드 객체 그대로다. 저장되면 새 버전 번호를 준다.",
     "inputSchema": _obj({"node": {"type": "object"}}, ["node"])},
    {"annotations": _RW, "name": "node_update",
     "description": "노드 하나의 칸을 고친다. fields 에 바꿀 칸만 넣는다(id 는 못 바꾼다). 가지의 holdings 는 전체 목록으로.",
     "inputSchema": _obj({"id": {"type": "string"}, "fields": {"type": "object"}}, ["id", "fields"])},
    {"annotations": _RW_DEL, "name": "node_delete",
     "description": "노드 하나와 그 아래 노드를 모두 지운다.",
     "inputSchema": _obj({"id": {"type": "string"}}, ["id"])},
    {"annotations": _RW, "name": "holdings_set",
     "description": "지금 보유(holdings) 목록을 통째로 바꾼다(이미지로 잔고를 읽었을 때 등). as_of 는 기준일 YYYY-MM-DD.",
     "inputSchema": _obj({"holdings": {"type": "array", "items": {"type": "object"}}, "as_of": {"type": "string"}},
                         ["holdings"])},
    {"annotations": _RW, "name": "cashflow_set",
     "description": "월 현금흐름(cashflow — 수입·고정 지출·생활비·저축·납입) 목록을 통째로 바꾼다. 금액은 한 달 원화.",
     "inputSchema": _obj({"cashflow": {"type": "array", "items": {"type": "object"}}}, ["cashflow"])},
]


async def _usdkrw(db) -> float | None:
    fx = (await _latest_quotes(db, [("KRWUSD", "f")])).get("KRWUSD")
    return fx["close"] if fx else None


async def _call(db, user_index: int, name: str, args: dict):
    from app.api.plan_v1 import latest_rev, plan_view   # 순환 임포트를 피한다(plan_v1 이 이 모듈을 부른다)

    if name == "plan_get":
        return await plan_view(db, await latest_rev(db, user_index))
    if name == "node_get":
        view = await plan_view(db, await latest_rev(db, user_index))
        node = next((n for n in view["doc"]["nodes"] if n["id"] == args.get("id")), None)
        if node is None:
            raise ValueError(f"없는 노드입니다: {args.get('id')}")
        return {"node": node, "value": view["values"].get(node["id"]), "retro": view["retro"].get(node["id"]),
                "accrual": view["accrual"].get(node["id"])}
    if name == "plan_revisions":
        rows = (await db.execute(text(
            "SELECT rev_id, summary, created_at FROM invest_plan_rev WHERE user_index = :u "
            "ORDER BY rev_id DESC LIMIT 50"), {"u": user_index})).all()
        return [{"rev_id": r.rev_id, "at": r.created_at.isoformat(), "summary": r.summary} for r in rows]
    if name == "plan_revision_get":
        row = (await db.execute(text(
            "SELECT rev_id, doc, summary, created_at FROM invest_plan_rev WHERE user_index = :u AND rev_id = :r"),
            {"u": user_index, "r": int(args.get("rev_id", 0))})).first()
        if row is None:
            raise ValueError("없는 버전입니다")
        return await plan_view(db, row)
    if name == "quotes_get":
        items = args.get("items") or []
        stocks = [i["code"] for i in items if i.get("market") != "COIN"]
        coins = [i["code"] for i in items if i.get("market") == "COIN"]
        sq = await _latest_quotes(db, [(c, "s") for c in stocks])
        cq = await _latest_quotes(db, [(c, "c") for c in coins])
        return {"usdkrw": await _usdkrw(db), "quotes": [
            {"code": i["code"], "market": i.get("market"),
             **((cq if i.get("market") == "COIN" else sq).get(i["code"]) or {"close": None})} for i in items]}
    if name == "stock_search":
        q = str(args.get("q", "")).strip()[:50]
        if not q:
            raise ValueError("q 가 비었습니다")
        _, rows = await _stock_page(db, args.get("market") or "", q, 1, 10)
        return [{"code": r.code, "name_kr": r.name_kr, "name_en": r.name_en, "market": r.market} for r in rows]
    if name in WRITE_TOOLS:
        return await _write(db, user_index, name, args)
    raise ValueError(f"모르는 도구: {name}")


async def _write(db, user_index: int, name: str, args: dict) -> dict:
    """지금 버전을 고쳐 검증하고 새 버전으로 쌓는다. 검증에 걸리면 ValueError(이유) — AI 가 보고 고친다."""
    from pydantic import ValidationError

    from app.api.plan_v1 import _doc_of, _save_rev, latest_rev

    old = _doc_of(await latest_rev(db, user_index))
    data = old.model_dump(mode="json")
    nodes = data["nodes"]
    if name == "node_add":
        node = args.get("node") or {}
        if any(n["id"] == node.get("id") for n in nodes):
            raise ValueError(f"이미 있는 id 입니다: {node.get('id')} — node_update 를 쓰세요")
        nodes.append(node)
        what = f"노드 추가: {node.get('title', node.get('id'))}"
    elif name == "node_update":
        hit = next((n for n in nodes if n["id"] == args.get("id")), None)
        if hit is None:
            raise ValueError(f"없는 노드입니다: {args.get('id')}")
        fields = {k: v for k, v in (args.get("fields") or {}).items() if k != "id"}
        hit.update(fields)
        what = f"노드 수정: {hit.get('title', hit['id'])}({', '.join(fields) or '변경 없음'})"
    elif name == "node_delete":
        target = args.get("id")
        if not any(n["id"] == target for n in nodes):
            raise ValueError(f"없는 노드입니다: {target}")
        gone, grew = {target}, True
        while grew:   # 그 아래 노드까지
            more = {n["id"] for n in nodes if n.get("parent") in gone} - gone
            gone |= more
            grew = bool(more)
        data["nodes"] = [n for n in nodes if n["id"] not in gone]
        what = f"노드 삭제: {target}" + (f" 외 {len(gone) - 1}개" if len(gone) > 1 else "")
    elif name == "cashflow_set":
        data["cashflow"] = args.get("cashflow") or []
        what = "현금흐름 갱신"
    else:   # holdings_set
        data["holdings"] = args.get("holdings") or []
        if args.get("as_of"):
            data["as_of"] = args["as_of"]
        what = "보유 자산 갱신"
    try:
        new = ip.PlanDoc.model_validate(data)
    except ValidationError as e:
        raise ValueError(f"계획 형식 오류 — 저장하지 않았습니다: {e}") from e
    if new == old:
        return {"saved": False, "summary": "변경 없음"}
    rev_id = await _save_rev(db, user_index, new, what)
    await db.commit()
    return {"saved": True, "rev_id": rev_id, "summary": what}


# ---------------------------------------------------------------------------
# JSON-RPC
# ---------------------------------------------------------------------------

def _result(mid, result) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": mid, "result": result})


def _error(mid, code: int, message: str) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}})


@router.get("/mcp", include_in_schema=False)
async def mcp_get():
    return Response(status_code=status.HTTP_405_METHOD_NOT_ALLOWED)


@router.post("/mcp", include_in_schema=False)
async def mcp(request: Request):
    user_index = _user_of(request)
    if user_index is None:
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
                             "serverInfo": {"name": "blog-plan", "version": "1"}})
    if method == "ping":
        return _result(mid, {})
    if method == "tools/list":
        return _result(mid, {"tools": TOOLS})
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        try:
            async with db_session() as db:
                data = await _call(db, user_index, name, args)
        except (ValueError, KeyError, TypeError) as e:
            return _result(mid, {"content": [{"type": "text", "text": str(e)}], "isError": True})
        return _result(mid, {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, default=str)}]})
    return _error(mid, -32601, f"모르는 메서드: {method}")
