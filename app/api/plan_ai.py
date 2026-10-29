"""투자 계획이 상담 AI 에 붙는 자리(2026-10-19 분리) — MCP 도구, 프롬프트 조각, 상담 뒤 요약.

상담([assistant_v1](assistant_v1.py))과 MCP([mcp](mcp.py))는 계획을 모른다. `main.py` 가 이 모듈을 둘에 붙인다.

- MCP: 조회(지금 계획·버전 이력 — 시세·종목 검색은 [market_ai](market_ai.py)) + 쓰기(노드 추가·수정·삭제, 보유·현금흐름·계좌·부채·원칙·기억 통째로).
  **계획을 고치는 길은 쓰기 도구뿐이다**(전에 쓰던 답 끝의 plan 블록은 2026-10-10 에 걷었다 — AI 가 노드 하나 고치려고
  문서 전체를 다시 쓰다 빠뜨리는 일이 없게). 쓰기마다 `PlanDoc` 으로 검증하고 통과하면 새 버전으로 쌓는다.
- 상담: `begin` 이 상담 직전 계획을 읽고, `prompt` 가 프롬프트 조각을, `tools_for` 가 이번 상담에 열 쓰기 도구를,
  `finish` 가 상담이 쌓은 버전의 요약·[바뀐 것]·되돌리기를 낸다.
"""

import re

from sqlalchemy import text

from app.api.mcp import RO, RW, RW_DEL, obj
from app.api.plan_v1 import _doc_of, _save_rev, asset_view, latest_rev, plan_view, prices, write_lock
from app.services import invest_plan as ip
from app.services import plan_assets

#: 쓰기 도구 이름 — codex_runner 가 상담이 연 것에만 자동 승인을 건다.
WRITE_TOOLS = ("node_add", "node_update", "node_delete", "holdings_set", "cashflow_set", "accounts_set", "debts_set",
               "rules_set", "memory_set")
#: 원칙·기억 쓰기 — 웹 검색 결과의 지시(프롬프트 주입)로 바뀌면 이후 상담·점검에 계속 실린다. 사용자가 시킨 상담에만 연다.
NOTE_TOOLS = ("rules_set", "memory_set")
CLOSED_HINT = ("원칙·기억은 사용자가 '기억해·원칙으로·잊어·빼'처럼 시킨 상담에서만 고친다. "
               "남길 만하면 사용자에게 \"원칙(기억)으로 남길까요?\" 하고 물어라")

TOOLS = [
    {"annotations": RO, "name": "plan_get", "description": "지금 계획 문서와 노드별 평가(오늘 시세·원화 환산 금액·환율), 월 현금흐름 합계(cashflow)와 이벤트까지의 예상 적립(accrual).",
     "inputSchema": obj()},
    {"annotations": RO, "name": "node_get",
     "description": "노드 하나의 모든 칸(개요·예상·조건·액션·보유 등)과 그 시점 평가(오늘 시세), 지난 이벤트면 복기, 가지면 매매표(trades — 직전 보유 대비 계좌별 매수·매도 수량·대략 금액).",
     "inputSchema": obj({"id": {"type": "string"}}, ["id"])},
    {"annotations": RO, "name": "plan_revisions", "description": "계획 버전 이력(최근 것부터 최대 50개) — 번호·시각·바뀐 것 요약. 보유 변화를 볼 때 쓴다.",
     "inputSchema": obj()},
    {"annotations": RO, "name": "plan_revision_get", "description": "특정 버전의 계획 문서와 평가(평가는 오늘 시세 기준).",
     "inputSchema": obj({"rev_id": {"type": "integer"}}, ["rev_id"])},
    {"annotations": RW, "name": "node_add",
     "description": "노드(이벤트·가지) 하나를 더한다. node 는 계획 문서 형식의 노드 객체 그대로다. 저장되면 새 버전 번호를 준다.",
     "inputSchema": obj({"node": {"type": "object"}}, ["node"])},
    {"annotations": RW, "name": "node_update",
     "description": "노드 하나의 칸을 고친다. fields 에 바꿀 칸만 넣는다(id 는 못 바꾼다). 가지의 holdings 는 전체 목록으로.",
     "inputSchema": obj({"id": {"type": "string"}, "fields": {"type": "object"}}, ["id", "fields"])},
    {"annotations": RW_DEL, "name": "node_delete",
     "description": "노드 하나와 그 아래 노드를 모두 지운다.",
     "inputSchema": obj({"id": {"type": "string"}}, ["id"])},
    {"annotations": RW, "name": "holdings_set",
     "description": "지금 보유(holdings) 목록을 통째로 바꾼다(이미지로 잔고를 읽었을 때 등). as_of 는 기준일 YYYY-MM-DD.",
     "inputSchema": obj({"holdings": {"type": "array", "items": {"type": "object"}}, "as_of": {"type": "string"}},
                        ["holdings"])},
    {"annotations": RW, "name": "cashflow_set",
     "description": "월 현금흐름(cashflow — 수입·고정 지출·생활비·저축·납입) 목록을 통째로 바꾼다. 금액은 한 달 원화.",
     "inputSchema": obj({"cashflow": {"type": "array", "items": {"type": "object"}}}, ["cashflow"])},
    {"annotations": RW, "name": "accounts_set",
     "description": "계좌 목록(accounts — 기관·유형·목적·원금·개설·만기)을 통째로 바꾼다. 보유·납입·부채의 account 는 이 목록의 name 이어야 한다.",
     "inputSchema": obj({"accounts": {"type": "array", "items": {"type": "object"}}}, ["accounts"])},
    {"annotations": RW, "name": "debts_set",
     "description": "부채 목록(debts — 빌린 곳·잔액·연 금리·만기·연결 계좌)을 통째로 바꾼다. 순자산 = 보유 평가 − 부채 잔액.",
     "inputSchema": obj({"debts": {"type": "array", "items": {"type": "object"}}}, ["debts"])},
    {"annotations": RW, "name": "rules_set",
     "description": "원칙(rules — AI 가 늘 지킬 사용자 규칙) 목록을 통째로 바꾼다. 한 줄에 하나, 300자 이내, 최대 30줄.",
     "inputSchema": obj({"rules": {"type": "array", "items": {"type": "string"}}}, ["rules"])},
    {"annotations": RW, "name": "memory_set",
     "description": "기억(memory — 사용자에 대한 사실·상황·선호) 목록을 통째로 바꾼다. 한 줄에 하나, 300자 이내, 최대 50줄.",
     "inputSchema": obj({"memory": {"type": "array", "items": {"type": "string"}}}, ["memory"])},
]


# ---------------------------------------------------------------------------
# MCP 도구
# ---------------------------------------------------------------------------

async def call(db, user_index: int, name: str, args: dict):
    if name == "plan_get":
        return await plan_view(db, await latest_rev(db, user_index))
    if name == "node_get":
        view = await plan_view(db, await latest_rev(db, user_index))
        node = next((n for n in view["doc"]["nodes"] if n["id"] == args.get("id")), None)
        if node is None:
            raise ValueError(f"없는 노드입니다: {args.get('id')}")
        return {"node": node, "value": view["values"].get(node["id"]), "retro": view["retro"].get(node["id"]),
                "accrual": view["accrual"].get(node["id"]), "trades": view["trades"].get(node["id"])}
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
    if name in WRITE_TOOLS:
        return await _write(db, user_index, name, args)
    raise ValueError(f"모르는 도구: {name}")


#: 목록을 통째로 바꾸는 도구 → 받아야 할 키. 키가 없으면 비우지 않고 거절한다 — `args.get(…) or []` 였을 때
#: 키 이름을 틀리면 보유가 통째로 비었다(2026-10-14 검토).
_SET_KEYS = {"holdings_set": "holdings", "cashflow_set": "cashflow", "accounts_set": "accounts", "debts_set": "debts",
             "rules_set": "rules", "memory_set": "memory"}


async def _write(db, user_index: int, name: str, args: dict) -> dict:
    """지금 버전을 고쳐 검증하고 새 버전으로 쌓는다. 검증에 걸리면 ValueError(이유) — AI 가 보고 고친다."""
    key = _SET_KEYS.get(name)
    if key and not isinstance(args.get(key), list):
        raise ValueError(f"{key} 목록이 없습니다 — 저장하지 않았습니다(통째로 바꾸는 도구라 전체 목록을 보내야 한다)")
    # 화면 저장·[실행함]·되돌리기와 같은 잠금 — 읽고 고쳐 쌓는 사이에 다른 쓰기가 끼면 한쪽이 사라진다(2026-10-14 검토).
    async with write_lock(user_index):
        return await _write_locked(db, user_index, name, args)


async def _write_locked(db, user_index: int, name: str, args: dict) -> dict:
    from pydantic import ValidationError

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
        data["cashflow"] = args["cashflow"]
        what = "현금흐름 갱신"
    elif name == "accounts_set":
        data["accounts"] = args["accounts"]
        what = "계좌 갱신"
    elif name == "debts_set":
        data["debts"] = args["debts"]
        what = "부채 갱신"
    elif name == "rules_set":
        data["rules"] = args["rules"]
        what = "원칙 갱신"
    elif name == "memory_set":
        data["memory"] = args["memory"]
        what = "기억 갱신"
    else:   # holdings_set
        data["holdings"] = args["holdings"]
        if args.get("as_of"):
            data["as_of"] = args["as_of"]
        what = "보유 자산 갱신"
    try:
        new = ip.PlanDoc.model_validate(data)
    except ValidationError as e:
        raise ValueError(f"계획 형식 오류 — 저장하지 않았습니다: {e}") from e
    ip.stamp_branches(old, new)
    if ip.changed_branches(old, new):
        if errs := ip.funding_errors(old, new, ip.valuate(new, *await prices(db, new))):
            raise ValueError("재원 초과 — 저장하지 않았습니다: " + "; ".join(errs))
    if new == old:
        return {"saved": False, "summary": "변경 없음"}
    rev_id = await _save_rev(db, user_index, new, what)
    await db.commit()
    return {"saved": True, "rev_id": rev_id, "summary": what}


# ---------------------------------------------------------------------------
# 상담
# ---------------------------------------------------------------------------

#: 원칙·기억을 고치라는 말 — 이게 있는 상담에만 rules_set·memory_set 을 연다(2026-10-14 검토, 사용자 선택 A).
#: 단어 검사라 넓게 잡는다("빼"·"지워"는 다른 뜻일 때도 열리지만 여는 쪽 실수라 괜찮다). 없으면 AI 가 "남길까요?"라고 묻는다.
_NOTE_INTENT = re.compile(r"기억|원칙|규칙|잊|빼|지워|지우|삭제")
#: 직전 답이 "원칙(기억)으로 남길까요?" 라고 물었으면 이번 답("ㅇㅇ")에 그 말이 없어도 연다 — 안 열면 물어 놓고
#: 저장할 길이 없어 같은 질문만 되풀이했다(2026-10-16 운영 상담).
_NOTE_ASKED = re.compile(r"(원칙|기억)으로\s*남길까요")


def tools_for(message: str, last_reply: str = "") -> tuple:
    if _NOTE_INTENT.search(message) or _NOTE_ASKED.search(last_reply):
        return WRITE_TOOLS
    return tuple(t for t in WRITE_TOOLS if t not in NOTE_TOOLS)


async def begin(db, user_index: int) -> dict:
    """상담 직전 계획 — 프롬프트에 싣고, 끝난 뒤 무엇이 바뀌었는지 견준다."""
    row = await latest_rev(db, user_index)
    return {"row": row, "doc": _doc_of(row), "assets": await asset_view(db, row)}


def prompt(state: dict, now, allow: tuple) -> str:
    base = ip.plan_prompt(state["doc"], "rules_set" in allow)
    return base + "\n\n" + plan_assets.prompt(state["assets"])


async def finish(db, user_index: int, state: dict, made: list[dict]) -> dict | None:
    """상담이 쌓은 버전의 요약 — [바뀐 것] 꼬리, 대화에 남길 버전 번호, 토스트와 되돌리기.

    되돌리기(상담 직전 버전으로)는 그 사이에 다른 저장(화면의 원칙·기억·[실행함])이 없을 때만 준다 — 있으면 그것까지
    되돌리게 된다(2026-10-14 검토). 바뀐 게 없으면 None.
    """
    row, old = state["row"], state["doc"]
    since = (await db.execute(text(
        "SELECT rev_id, summary FROM invest_plan_rev WHERE user_index = :u AND rev_id > :p ORDER BY rev_id"),
        {"u": user_index, "p": row.rev_id if row else 0})).all()
    ours = {w["rev_id"] for w in made}
    mine = [r for r in since if r.rev_id in ours]
    if not mine:
        return None
    latest = await latest_rev(db, user_index)
    new = _doc_of(latest)
    undo = row.rev_id if row and len(mine) == len(since) else None
    rev_id = mine[-1].rev_id
    changes = ip.change_lines(old, new)
    return {
        "source": "plan",
        "tail": "\n\n[바뀐 것]\n" + "\n".join(f"- {c}" for c in changes[:30]) if changes else "",
        "meta": {"plan_rev": rev_id, "badge": f"계획 버전 #{rev_id}"},
        "toast": "계획을 고쳤습니다: " + " · ".join(r.summary for r in mine)[:300] + f" ({ip.diff_summary(old, new)})",
        "undo": {"label": "되돌리기", "method": "POST",
                 "url": f"/api/v1/plan/revisions/{undo}/restore?expect={latest.rev_id}",
                 "done": f"계획을 {undo}번 버전으로 되돌렸습니다"} if undo else None,
        "note": "상담 중 다른 저장이 있어 한 번에 되돌리지 않습니다 — 버전 기록에서 고르세요" if row and undo is None else "",
    }
