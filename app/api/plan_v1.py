"""`/api/v1/plan` — 투자 계획(2026-10-10). **root(레벨 0) 본인 전용**이다.

AI 와 상담하며 이벤트 분기 계획을 짜고, 보유 자산 이미지를 읽혀 갱신한다. 계획 형식·검증·평가는
[invest_plan](../services/invest_plan.py), 여기는 DB·AI 호출·권한만 맡는다.

## AI 는 블로그 안의 codex CLI 다

처음엔 32.ai_stream API 를 거쳤는데, 거기서는 AI 가 블로그 데이터를 조회할 길이 없었다(공용이라 MCP 를 붙일 수
없다). 그래서 블로그가 직접 codex 에 로그인하고 `codex exec` 에 블로그 MCP(`/mcp`, 읽기 전용)를 붙여 부른다
([codex_runner](../services/codex_runner.py), [plan_mcp](plan_mcp.py)). MCP 토큰은 상담 한 번짜리다.
codex 는 대화를 기억하지 않아 매번 시스템 프롬프트(지금 계획 문서 포함) + 최근 대화를 글로 펴서 넘긴다.

⚠️ 응답은 10~60초 걸린다(글자 단위 스트리밍이 아니라 메시지 단위). 화면이 진행 표시를 띄운다.
⚠️ 개인 자산 데이터라 읽기도 Bearer 다(관심 종목과 같은 규칙 — [watchlist_v1](watchlist_v1.py)).
"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text

from app.api import plan_mcp
from app.api.deps import bearer_user
from app.core import app_settings, blog_user
from app.core.config import settings
from app.db.session import db_session
from app.services import codex_runner
from app.services import invest_plan as ip
from app.ui.stocks import _candle_candidates, _latest_quotes

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/plan", tags=["plan"])

_KST = timezone(timedelta(hours=9))
#: AI 에 넘기는 지난 대화 수. 계획은 시스템 프롬프트의 문서가 들고 있으니 길게 줄 필요가 없다.
_HISTORY = 20
_MAX_IMAGES = 4
_MAX_IMAGE_CHARS = 4_000_000   # data URL 한 장(≈3MB). 화면이 미리 줄여 보낸다.


async def owner(db, request: Request):
    """root 만. 다른 사람에게는 있다는 사실도 알리지 않는다(404)."""
    me = await blog_user.find(db, bearer_user(request))
    if me is None or me.level != 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return me


#: 사용자별 쓰기 잠금 — MCP 쓰기·원칙 저장·[실행함]·되돌리기가 "최신을 읽고 고쳐 새 버전으로 쌓는" 사이에 서로 끼지
#: 않게 한다(끼면 한쪽 변경이 사라졌다, 2026-10-14 검토). 앱 워커가 하나라 프로세스 안 잠금이면 충분하다.
_WRITE_LOCKS: dict[int, "asyncio.Lock"] = {}


def write_lock(user_index: int):
    import asyncio
    return _WRITE_LOCKS.setdefault(user_index, asyncio.Lock())


async def latest_rev(db, user_index: int):
    return (await db.execute(text(
        "SELECT rev_id, doc, summary, created_at FROM invest_plan_rev WHERE user_index = :u "
        "ORDER BY rev_id DESC LIMIT 1"), {"u": user_index})).first()


def _doc_of(row) -> ip.PlanDoc:
    return ip.PlanDoc.model_validate_json(row.doc) if row else ip.empty_doc()


async def _save_rev(db, user_index: int, doc: ip.PlanDoc, summary: str) -> int:
    res = await db.execute(text(
        "INSERT INTO invest_plan_rev (user_index, doc, summary) VALUES (:u, :d, :s)"),
        {"u": user_index, "d": doc.model_dump_json(), "s": summary[:500]})
    return res.lastrowid


_ET = ZoneInfo("America/New_York")


async def _closes_at(db, items: list[tuple[str, str, bool]], at: datetime) -> dict[str, float]:
    """`(코드, 접두사, 미국 종목?)` → 그 시각 **이전 마지막 종가**. 캔들이 없으면 키가 없다.

    ⚠️ 미국 종목 캔들의 시각은 현지(ET), 나머지(국내·코인·환율)는 KST 다 — 기준 시각을 종목마다 맞춰 비교한다.
    """
    want: dict[str, tuple[str, bool]] = {}
    for code, prefix, us in items:
        for cand in _candle_candidates(code, prefix):
            want.setdefault(cand, (code, us))
    if not want:
        return {}
    found = (await db.execute(text(
        "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = 'candle' AND TABLE_NAME IN :n")
        .bindparams(bindparam("n", expanding=True)), {"n": list(want)})).all()
    picked: dict[str, tuple[str, bool]] = {}
    for (tbl,) in found:
        code, us = want[tbl]
        picked.setdefault(code, (tbl, us))
    at_kst = at.astimezone(_KST).replace(tzinfo=None)
    at_et = at.astimezone(_ET).replace(tzinfo=None)
    parts, params = [], {"kst": at_kst, "et": at_et}
    for i, (code, (tbl, us)) in enumerate(picked.items()):
        if not tbl.replace("_", "").isalnum():   # information_schema 가 준 이름이지만 한 번 더
            continue
        params[f"c{i}"] = code
        parts.append(f"SELECT :c{i} AS code, (SELECT execution_close FROM `candle`.`{tbl}` WHERE execution_datetime <= "
                     f"{':et' if us else ':kst'} ORDER BY execution_datetime DESC LIMIT 1) AS close_price")
    if not parts:
        return {}
    rows = (await db.execute(text(" UNION ALL ".join(parts)), params)).all()
    return {code: float(c) for code, c in rows if c is not None}


async def prices(db, doc: ip.PlanDoc) -> tuple[dict, dict, float | None]:
    """(종목 종가, 코인 종가, 원/달러) — 오늘 시세. 평가(`ip.valuate`)에 그대로 넣는다."""
    stocks, coins = ip.price_pairs(doc)
    sq = await _latest_quotes(db, [(c, "s") for c in stocks])
    cq = await _latest_quotes(db, [(c, "c") for c in coins])
    fx = (await _latest_quotes(db, [("KRWUSD", "f")])).get("KRWUSD")
    return ({k: v["close"] for k, v in sq.items()}, {k: v["close"] for k, v in cq.items()}, fx["close"] if fx else None)


async def plan_view(db, row) -> dict:
    """문서 + 노드마다 원화 평가(미래 노드도 오늘 시세 — 비율을 보라는 뜻), 지난 이벤트의 복기, 월 현금흐름 합계와 이벤트까지의 예상 적립."""
    doc = _doc_of(row)
    stocks, coins = ip.price_pairs(doc)
    stock_px, coin_px, usdkrw = await prices(db, doc)
    values = ip.valuate(doc, stock_px, coin_px, usdkrw)

    # 복기 — 지난 이벤트마다 그 시각의 종가로 다시 평가한다(같은 시각의 이벤트는 한 번만 읽는다).
    us_codes = {h.code for h in ip._all_holdings(doc) if h.code and h.market == "US"}
    then_values, cache = {}, {}
    for ev in ip.past_events(doc, datetime.now(_KST)):
        at = ip._kst(ev.at)
        if at not in cache:
            px = await _closes_at(db, [(c, "s", c in us_codes) for c in stocks] + [(c, "c", False) for c in coins]
                                  + [("KRWUSD", "f", False)], at)
            cache[at] = ip.valuate(doc, {c: px[c] for c in stocks if c in px}, {c: px[c] for c in coins if c in px},
                                   px.get("KRWUSD"))
        then_values[ev.id] = cache[at]
    return {
        "rev_id": row.rev_id if row else None,
        "summary": row.summary if row else "",
        "updated_at": row.created_at.isoformat() if row else None,
        "usdkrw": usdkrw,
        "doc": doc.model_dump(mode="json"),
        "values": values,
        "retro": ip.retrospect(doc, values, then_values),
        "cashflow": ip.cashflow_summary(doc),
        "accrual": ip.accruals(doc, datetime.now(_KST).date()),
        "trades": ip.trades(doc, values),
        "stale": sorted(ip.stale_branches(doc)),
    }


@router.get("", summary="지금 계획과 노드별 평가")
async def get_plan(request: Request):
    async with db_session() as db:
        me = await owner(db, request)
        return await plan_view(db, await latest_rev(db, me.user_index))


class ChatMessage(BaseModel):
    chat_id: int
    role: str
    content: str
    rev_id: int | None
    created_at: str


@router.get("/chat", response_model=list[ChatMessage], summary="상담 대화(오래된 것부터)")
async def get_chat(request: Request, limit: int = 100):
    async with db_session() as db:
        me = await owner(db, request)
        rows = (await db.execute(text(
            "SELECT chat_id, role, content, rev_id, created_at FROM invest_plan_chat WHERE user_index = :u "
            "ORDER BY chat_id DESC LIMIT :n"), {"u": me.user_index, "n": max(1, min(limit, 500))})).all()
    return [ChatMessage(chat_id=r.chat_id, role=r.role, content=r.content, rev_id=r.rev_id,
                        created_at=r.created_at.isoformat()) for r in reversed(rows)]


class ChatIn(BaseModel):
    message: str = Field(default="", max_length=8000)
    images: list[str] = Field(default_factory=list, max_length=_MAX_IMAGES,
                              description="data:image/…;base64,… — 저장하지 않고 이번 요청에만 쓴다")


def _flatten(messages: list[dict]) -> tuple[str, list[str]]:
    """대화 → (codex 에 stdin 으로 넣을 글, 이미지 data URL). 시스템 프롬프트를 맨 앞에, 그 뒤로 말한 순서대로."""
    parts, images = [], []
    label = {"user": "사용자", "assistant": "상담가"}
    for m in messages:
        content = m["content"]
        if isinstance(content, list):
            images += [c["image_url"]["url"] for c in content if c.get("type") == "image_url"]
            content = "\n".join(c["text"] for c in content if c.get("type") == "text")
        parts.append(content if m["role"] == "system" else f"[{label[m['role']]}]\n{content}")
    return "\n\n".join(parts), images


#: 원칙·기억을 고치라는 말 — 이게 있는 상담에만 rules_set·memory_set 을 연다(2026-10-14 검토, 사용자 선택 A).
#: 단어 검사라 넓게 잡는다("빼"·"지워"는 다른 뜻일 때도 열리지만 여는 쪽 실수라 괜찮다). 없으면 AI 가 "남길까요?"라고 묻는다.
_NOTE_INTENT = re.compile(r"기억|원칙|규칙|잊|빼|지워|지우|삭제")
#: 직전 답이 "원칙(기억)으로 남길까요?" 라고 물었으면 이번 답("ㅇㅇ")에 그 말이 없어도 연다 — 안 열면 물어 놓고
#: 저장할 길이 없어 같은 질문만 되풀이했다(2026-10-16 운영 상담).
_NOTE_ASKED = re.compile(r"(원칙|기억)으로\s*남길까요")


def write_tools_for(message: str, last_reply: str = "") -> tuple:
    if _NOTE_INTENT.search(message) or _NOTE_ASKED.search(last_reply):
        return plan_mcp.WRITE_TOOLS
    return tuple(t for t in plan_mcp.WRITE_TOOLS if t not in plan_mcp.NOTE_TOOLS)


async def _ask(cfg: dict, messages: list[dict], user_index: int, tools: tuple) -> tuple[str, list[int]]:
    """codex 한 번 → (답, 이 상담이 쌓은 버전들). 상담 동안만 유효한 MCP 토큰을 그 사람에게 묶어 넘기고, 끝나면 회수한다.

    계획은 AI 가 MCP 쓰기 도구로 고친다(plan_mcp) — 고칠 때마다 이미 새 버전이 쌓여 있다.
    ⚠️ 실패해도 그 전에 쓴 버전은 남는다 — 화면이 실패 뒤 계획을 다시 읽는다(plan.js send).
    """
    prompt, images = _flatten(messages)
    token = plan_mcp.issue(user_index, allow=tools)
    made: list[int] = []
    try:
        model = codex_runner.resolve_model(cfg["ai_model"])
        reply = await codex_runner.run(prompt, model, images, settings.plan_mcp_url, token, tools,
                                       effort=codex_runner.resolve_effort(model, cfg["ai_effort"]))
    except codex_runner.CodexError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))
    finally:
        made = plan_mcp.revoke(token)
    return reply, made


#: 상담이 돌고 있는 사용자. 휴대폰은 기다리는 사이 요청이 끊기는데 서버는 끝까지 답을 만들어 저장한다 — 화면은
#: `/chat/busy` 로 끝나길 기다렸다 대화를 다시 읽고, 그 사이 다시 보낸 상담은 409 로 막는다(끊긴 줄 알고 다시 보내
#: AI 가 같은 일을 두 번 했다 — 2026-10-14~16 운영 로그). 앱 워커가 하나라 프로세스 안 집합이면 충분하다.
_CHATTING: set[int] = set()


@router.get("/chat/busy", summary="상담이 아직 돌고 있나")
async def chat_busy(request: Request):
    async with db_session() as db:
        me = await owner(db, request)
    return {"busy": me.user_index in _CHATTING}


@router.post("/chat", summary="상담 — AI 가 MCP 쓰기 도구로 계획을 고치면 그때마다 새 버전이 쌓인다")
async def chat(request: Request, body: ChatIn):
    msg = body.message.strip()
    if not msg and not body.images:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "메시지나 이미지가 필요합니다")
    for img in body.images:
        if not img.startswith("data:image/") or len(img) > _MAX_IMAGE_CHARS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "이미지는 3MB 이하 data URL 이어야 합니다")

    async with db_session() as db:
        me = await owner(db, request)
        row = await latest_rev(db, me.user_index)
        old = _doc_of(row)
        cfg = await app_settings.load(db)
        history = (await db.execute(text(
            "SELECT role, content FROM invest_plan_chat WHERE user_index = :u ORDER BY chat_id DESC LIMIT :n"),
            {"u": me.user_index, "n": _HISTORY})).all()

    if me.user_index in _CHATTING:
        raise HTTPException(status.HTTP_409_CONFLICT, "앞의 상담이 아직 진행 중입니다")
    _CHATTING.add(me.user_index)
    try:
        return await _chat(me, msg, body.images, row, old, cfg, history)
    finally:
        _CHATTING.discard(me.user_index)


async def _chat(me, msg: str, images: list[str], row, old: ip.PlanDoc, cfg: dict, history) -> dict:
    # ⚠️ AI 를 기다리는 동안(최대 10분) DB 커넥션을 붙잡지 않는다 — 세션을 닫고 부른다.
    user_part = [{"type": "text", "text": msg or "이미지를 읽어 줘."}] + [
        {"type": "image_url", "image_url": {"url": u}} for u in images]
    last_reply = next((r.content for r in history if r.role == "assistant"), "")
    tools = write_tools_for(msg, last_reply)
    messages = ([{"role": "system", "content": ip.system_prompt(old, datetime.now(_KST), "rules_set" in tools)}]
                + [{"role": r.role, "content": r.content} for r in reversed(history)]
                + [{"role": "user", "content": user_part}])
    reply, ours = await _ask(cfg, messages, me.user_index, tools)
    reply = reply.strip()

    prev = row.rev_id if row else 0
    note = ""
    async with db_session() as db:
        # 상담 시작 뒤 쌓인 버전 — 이 상담이 쓴 것(ours)만 요약하고, 되돌리기(상담 직전 버전으로)는 그 사이에 다른 저장
        # (화면의 원칙·기억·[실행함])이 없을 때만 준다. 있으면 그것까지 되돌리게 된다(2026-10-14 검토).
        since = (await db.execute(text(
            "SELECT rev_id, summary FROM invest_plan_rev WHERE user_index = :u AND rev_id > :p ORDER BY rev_id"),
            {"u": me.user_index, "p": prev})).all()
        made = [r for r in since if r.rev_id in ours]
        undo = row.rev_id if row and made and len(made) == len(since) else None
        if made and undo is None and row:
            note = "상담 중 다른 저장이 있어 한 번에 되돌리지 않습니다 — 버전 기록에서 고르세요"
        latest = await latest_rev(db, me.user_index)
        rev_id = made[-1].rev_id if made else None
        summary = ""
        if made:
            summary = " · ".join(r.summary for r in made)[:300] + f" ({ip.diff_summary(old, _doc_of(latest))})"
            if changes := ip.change_lines(old, _doc_of(latest)):
                reply += "\n\n[바뀐 것]\n" + "\n".join(f"- {c}" for c in changes[:30])
        stored = msg + (f"\n[이미지 {len(images)}장]" if images else "")
        await db.execute(text(
            "INSERT INTO invest_plan_chat (user_index, role, content) VALUES (:u, 'user', :c)"),
            {"u": me.user_index, "c": stored or "[이미지]"})
        res = await db.execute(text(
            "INSERT INTO invest_plan_chat (user_index, role, content, rev_id) VALUES (:u, 'assistant', :c, :r)"),
            {"u": me.user_index, "c": reply or "(계획을 고쳤습니다)", "r": rev_id})
        await db.commit()
        plan = await plan_view(db, latest) if made else None
    return {"chat_id": res.lastrowid, "reply": reply, "rev_id": rev_id, "prev_rev_id": undo,
            "summary": summary, "note": note, "plan": plan}


@router.get("/revisions", summary="계획 버전(최근 것부터)")
async def revisions(request: Request):
    async with db_session() as db:
        me = await owner(db, request)
        rows = (await db.execute(text(
            "SELECT rev_id, summary, created_at FROM invest_plan_rev WHERE user_index = :u "
            "ORDER BY rev_id DESC LIMIT 50"), {"u": me.user_index})).all()
    return [{"rev_id": r.rev_id, "summary": r.summary, "created_at": r.created_at.isoformat()} for r in rows]


@router.post("/revisions/{rev_id}/restore", summary="옛 버전으로 되돌린다(새 버전으로 다시 쌓는다)")
async def restore(request: Request, rev_id: int,
                  expect: int | None = Query(None, description="지금 버전이 이것일 때만 — 토스트 [되돌리기]가 그 사이 다른 변경을 덮지 않게")):
    async with db_session() as db:
        me = await owner(db, request)
        async with write_lock(me.user_index):
            return await _restore(db, me.user_index, rev_id, expect)


async def _restore(db, user_index: int, rev_id: int, expect: int | None) -> dict:
    if expect is not None and (cur := await latest_rev(db, user_index)) and cur.rev_id != expect:
        raise HTTPException(status.HTTP_409_CONFLICT, "그 사이 계획이 바뀌어 되돌리지 않았습니다 — 버전 기록에서 고르세요")
    row = (await db.execute(text(
        "SELECT doc FROM invest_plan_rev WHERE user_index = :u AND rev_id = :r"),
        {"u": user_index, "r": rev_id})).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "없는 버전입니다")
    await _save_rev(db, user_index, ip.PlanDoc.model_validate_json(row.doc), f"{rev_id}번 버전으로 되돌림")
    await db.commit()
    return await plan_view(db, await latest_rev(db, user_index))


class NotesIn(BaseModel):
    rules: list[str] = Field(default_factory=list, max_length=ip.MAX_RULES)
    memory: list[str] = Field(default_factory=list, max_length=ip.MAX_MEMORY)
    base_rev_id: int | None = Field(default=None, description="화면이 연 버전 — 그 사이 바뀌었으면 409(상담이 고친 걸 덮지 않게)")


@router.put("/notes", summary="원칙·기억을 통째로 바꾼다(화면 목록, 새 버전으로 쌓는다)")
async def put_notes(request: Request, body: NotesIn):
    from pydantic import ValidationError

    async with db_session() as db:
        me = await owner(db, request)
        async with write_lock(me.user_index):
            row = await latest_rev(db, me.user_index)
            if (row.rev_id if row else None) != body.base_rev_id:
                raise HTTPException(status.HTTP_409_CONFLICT, "그 사이 계획이 바뀌었습니다 — 다시 열어 주세요")
            old = _doc_of(row)
            try:
                new = ip.PlanDoc.model_validate({**old.model_dump(mode="json"),
                                                 "rules": [r for r in body.rules if r.strip()],
                                                 "memory": [m for m in body.memory if m.strip()]})
            except ValidationError:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "한 줄은 300자까지입니다")
            if new == old:
                return {**await plan_view(db, row), "saved": False, "prev_rev_id": None}
            await _save_rev(db, me.user_index, new, ip.diff_summary(old, new))
            await db.commit()
            view = await plan_view(db, await latest_rev(db, me.user_index))
            return {**view, "saved": True, "prev_rev_id": row.rev_id if row else None}


@router.post("/nodes/{node_id}/executed", summary="가지의 매매를 했다고 표시한다(오늘 날짜, 새 버전으로 쌓는다)")
async def mark_executed(request: Request, node_id: str):
    async with db_session() as db:
        me = await owner(db, request)
        async with write_lock(me.user_index):
            row = await latest_rev(db, me.user_index)
            doc = _doc_of(row)
            node = next((n for n in doc.nodes if n.id == node_id), None)
            if node is None or node.kind != "branch":
                raise HTTPException(status.HTTP_404_NOT_FOUND, "없는 가지입니다")
            node.executed_at = datetime.now(_KST).date()
            await _save_rev(db, me.user_index, doc, f"실행함: {node.title}")
            await db.commit()
            view = await plan_view(db, await latest_rev(db, me.user_index))
            return {**view, "prev_rev_id": row.rev_id if row else None}


# ---------------------------------------------------------------------------
# 이벤트 시작 메일 — 앱 안에서 1분마다 훑는다(main.py lifespan 이 띄운다)
# ---------------------------------------------------------------------------
#
# - 사람마다 최신 계획에서 시작 시각이 지난(24시간 안) pending 이벤트를 고른다([plan_mail](../services/plan_mail.py)).
# - **보내기 전에** `invest_plan_notice` 에 (사람, 노드, 시각)을 INSERT IGNORE 로 먼저 차지한다 — 차지한 쪽만 보낸다.
#   재시작이 겹치거나 컨테이너가 둘이어도 같은 알림이 두 번 가지 않는다. 이벤트 시각이 옮겨지면 키가 달라 다시 간다.
# - 보내기에 실패하면 차지한 줄을 지워 다음 1분에 다시 해 본다(24시간이 지나면 그만둔다).
# - SMTP 설정(관리자 › 외부 연동)이 비어 있으면 아무것도 하지 않는다.
#
# ⚠️ 테스트 컨테이너(BlogTest)도 같은 루프를 돈다 — 테스트 DB 에 SMTP 를 넣어 두면 테스트 계획의 메일도 간다.

_MAIL_TICK = 60


def _send(cfg: dict, msg) -> None:
    import smtplib
    from email.utils import format_datetime, make_msgid
    # Date·Message-ID 는 우리가 붙인다 — 비워 두면 메일 앱이 보낸 시각을 엉뚱하게 보일 수 있다(2026-10-17 사용자 지적).
    if "Date" not in msg:
        msg["Date"] = format_datetime(datetime.now(_KST))
    if "Message-ID" not in msg:
        msg["Message-ID"] = make_msgid(domain=cfg["smtp_user"].rpartition("@")[2] or None)
    port = int(cfg["smtp_port"])
    if port == 465:
        server = smtplib.SMTP_SSL(cfg["smtp_host"], port, timeout=20)
    else:
        server = smtplib.SMTP(cfg["smtp_host"], port, timeout=20)
        server.starttls()
    with server:
        server.login(cfg["smtp_user"], cfg["smtp_password"])
        server.send_message(msg)


async def mail_tick(now: datetime) -> int:
    """한 번 훑는다. 보낸 메일 수를 돌려준다."""
    import asyncio
    from app.services import plan_mail

    async with db_session() as db:
        cfg = await app_settings.load(db)
        if not (cfg["smtp_host"] and cfg["smtp_user"] and cfg["smtp_password"] and cfg["plan_mail_to"]):
            return 0
        rows = (await db.execute(text(
            "SELECT r.user_index, r.rev_id, r.doc, r.summary, r.created_at FROM invest_plan_rev r "
            "JOIN (SELECT user_index, MAX(rev_id) AS m FROM invest_plan_rev GROUP BY user_index) x ON r.rev_id = x.m"))).all()
        sent = 0
        for row in rows:
            doc = _doc_of(row)
            due = plan_mail.due_events(doc, now)
            if not due:
                continue
            view = await plan_view(db, row)
            for ev in due:
                at = ip._kst(ev.at).astimezone(_KST).replace(tzinfo=None)
                claimed = (await db.execute(text(
                    "INSERT IGNORE INTO invest_plan_notice (user_index, node_id, event_at) VALUES (:u, :n, :a)"),
                    {"u": row.user_index, "n": ev.id, "a": at})).rowcount
                await db.commit()
                if not claimed:
                    continue
                msg = plan_mail.compose(doc, view, ev, cfg["smtp_user"], cfg["plan_mail_to"],
                                        f"https://blog.{settings.base_domain}/stocks/plan")
                try:
                    await asyncio.to_thread(_send, cfg, msg)
                except Exception as e:   # noqa: BLE001 — 어떤 실패든 다음 1분에 다시 해 본다
                    logger.warning("이벤트 메일 실패(%s %s): %r", row.user_index, ev.id, e)
                    await db.execute(text(
                        "DELETE FROM invest_plan_notice WHERE user_index = :u AND node_id = :n AND event_at = :a"),
                        {"u": row.user_index, "n": ev.id, "a": at})
                    await db.commit()
                    continue
                sent += 1
                # 상담 기록에도 남긴다 — 매일 점검 메일처럼 다음 상담에서 AI 가 "그 메일"을 이어 다루게(2026-10-17 사용자: 연속성)
                await db.execute(text(
                    "INSERT INTO invest_plan_chat (user_index, role, content) VALUES (:u, 'assistant', :c)"),
                    {"u": row.user_index, "c": "[이벤트 시작 메일] " + plan_mail.event_text(doc, view, ev)})
                await db.commit()
                logger.info("이벤트 메일 보냄: user=%s event=%s(%s) → %s", row.user_index, ev.id, ev.title, cfg["plan_mail_to"])
    return sent


# ---------------------------------------------------------------------------
# 매일 점검 메일(2026-10-14) — 설정 시각(기본 12:00)에 AI 가 계획에 영향을 줄 이슈를 찾고, 있을 때만 보낸다
# ---------------------------------------------------------------------------
#
# - 관리자 › 외부 연동의 [매일 점검] 켬/끔·시각. 기본은 꺼짐이다(테스트 컨테이너도 이 루프를 돈다).
# - 하루 한 번은 `invest_plan_notice` 의 (사람, "daily", 그날 0시)를 먼저 차지해 지킨다. 시각을 6시간 넘겨 켜지면 그날은 건너뛴다.
# - codex 는 **조회 전용 토큰**으로 부른다(쓰기 도구 승인도 넘기지 않는다) — 계획은 상담에서만 바뀐다.
# - 실패(로그인 풀림·답 형식 깨짐 등)는 "점검 실패" 메일 한 통 — 조용한 날과 구분한다. 그날은 다시 하지 않는다(매분 codex 를 부르지 않게).
# - 무난한 하루(none)면 아무것도 보내지 않는다. 보낸 날은 상담 기록에도 남겨 다음 상담이 이어 다룬다.

_DAILY_ID = "daily"
_daily_tasks: set = set()   # 돌고 있는 점검 — 참조를 쥐고 있어야 도중에 GC 되지 않는다


async def daily_tick(now: datetime) -> int:
    """점검할 때면 사람마다 그날 몫을 차지하고 점검을 띄운다. 띄운 수를 돌려준다."""
    import asyncio
    from app.services import plan_mail

    async with db_session() as db:
        cfg = await app_settings.load(db)
        day = plan_mail.daily_due(cfg, now)
        if day is None or not (cfg["smtp_host"] and cfg["smtp_user"] and cfg["smtp_password"] and cfg["plan_mail_to"]):
            return 0
        rows = (await db.execute(text(
            "SELECT r.user_index, r.rev_id, r.doc FROM invest_plan_rev r "
            "JOIN (SELECT user_index, MAX(rev_id) AS m FROM invest_plan_rev GROUP BY user_index) x ON r.rev_id = x.m"))).all()
        started = 0
        for row in rows:
            claimed = (await db.execute(text(
                "INSERT IGNORE INTO invest_plan_notice (user_index, node_id, event_at) VALUES (:u, :n, :a)"),
                {"u": row.user_index, "n": _DAILY_ID, "a": datetime.combine(day, datetime.min.time())})).rowcount
            await db.commit()
            if not claimed:
                continue
            task = asyncio.create_task(daily_check(cfg, row.user_index, _doc_of(row), day, now))
            _daily_tasks.add(task)
            task.add_done_callback(_daily_tasks.discard)
            started += 1
    return started


async def daily_check(cfg: dict, user_index: int, doc: ip.PlanDoc, day, now: datetime) -> bool:
    """codex 로 한 번 점검하고, 알릴 일이 있으면 메일·상담 기록. 점검을 못 했으면(로그인·실행 실패, 답 형식 깨짐)
    "점검 실패" 메일을 보낸다 — 조용한 날과 구분한다. 메일을 보냈으면 True."""
    import asyncio
    from app.services import plan_mail

    page = f"https://blog.{settings.base_domain}/stocks/plan"
    token = plan_mcp.issue(user_index, read_only=True)
    failure = None
    try:
        model = codex_runner.resolve_model(cfg["ai_model"])
        reply = await codex_runner.run(ip.daily_prompt(doc, now), model, mcp_url=settings.plan_mcp_url, mcp_token=token,
                                       effort=codex_runner.resolve_effort(model, cfg["ai_effort"]))
    except codex_runner.CodexError as e:
        failure, reply = str(e), ""
    finally:
        plan_mcp.revoke(token)
    check = None if failure else plan_mail.parse_check(reply)
    if check is None:
        failure = failure or f"AI 답의 형식이 깨졌습니다: {reply.strip()[:150]}"
        logger.warning("매일 점검 실패(user=%s %s): %s", user_index, day, failure)
        msg = plan_mail.compose_daily_failure(day, failure, cfg["smtp_user"], cfg["plan_mail_to"], page)
    elif check["level"] == "none":
        logger.info("매일 점검: user=%s %s — 알릴 일 없음", user_index, day)
        return False
    else:
        msg = plan_mail.compose_daily(check, day, cfg["smtp_user"], cfg["plan_mail_to"], page)
    try:
        await asyncio.to_thread(_send, cfg, msg)
    except Exception as e:   # noqa: BLE001 — 점검은 하루 한 번, 다시 하지 않는다
        logger.warning("매일 점검 메일 실패(user=%s %s): %r", user_index, day, e)
        return False
    if check is None:
        return True
    async with db_session() as db:
        await db.execute(text(
            "INSERT INTO invest_plan_chat (user_index, role, content) VALUES (:u, 'assistant', :c)"),
            {"u": user_index, "c": "[매일 점검 메일] " + plan_mail.daily_text(check, day)})
        await db.commit()
    logger.info("매일 점검 메일 보냄: user=%s %s %s → %s", user_index, check["level"], check["title"], cfg["plan_mail_to"])
    return True


async def mail_loop() -> None:
    import asyncio
    await asyncio.sleep(20)   # 기동 직후 DB·공개키 준비를 기다린다
    while True:
        now = datetime.now(_KST)
        try:
            await mail_tick(now)
        except Exception:   # noqa: BLE001 — 루프는 죽지 않는다
            logger.exception("이벤트 메일 루프 오류")
        try:
            await daily_tick(now)
        except Exception:   # noqa: BLE001
            logger.exception("매일 점검 루프 오류")
        await asyncio.sleep(_MAIL_TICK)
