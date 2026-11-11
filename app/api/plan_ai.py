"""투자 계획이 상담 AI 에 붙는 자리(2026-10-19 분리) — MCP 도구, 프롬프트 조각, 상담 뒤 요약.

상담([assistant_v1](assistant_v1.py))과 MCP([mcp](mcp.py))는 계획을 모른다. `main.py` 가 이 모듈을 둘에 붙인다.

- MCP: 조회(계획·이력·배분 계산) + 목적별 변경안 검토·원자적 반영. 옛 전체 교체 도구는 호환용이며 상담에는 열지 않는다.
  **계획을 고치는 길은 쓰기 도구뿐이다**(전에 쓰던 답 끝의 plan 블록은 2026-10-10 에 걷었다 — AI 가 노드 하나 고치려고
  문서 전체를 다시 쓰다 빠뜨리는 일이 없게). 쓰기마다 `PlanDoc` 으로 검증하고 통과하면 새 버전으로 쌓는다.
- 상담: `begin` 이 상담 직전 계획을 읽고, `prompt` 가 프롬프트 조각을, `tools_for` 가 이번 상담에 열 쓰기 도구를,
  `finish` 가 상담이 쌓은 버전의 요약·[바뀐 것]·되돌리기를 낸다.
"""

from sqlalchemy import text

from app.api.mcp import RO, RW, RW_DEL, obj
from app.api.plan_v1 import _assets, _doc_of, _price_maps, _quotes, _save_rev, latest_rev, plan_view, prices, resolved_doc, write_lock
from app.services import invest_plan as ip
from app.services import plan_assets, plan_reconcile
from app.api import plan_counsel

#: 쓰기 도구 이름 — codex_runner 가 상담이 연 것에만 자동 승인을 건다.
LEGACY_WRITE_TOOLS = ("node_add", "node_update", "node_delete", "holdings_set", "cashflow_set", "accounts_set", "debts_set",
                      "rules_set", "memory_set")
WRITE_TOOLS = LEGACY_WRITE_TOOLS + plan_counsel.WRITE_TOOLS
#: 원칙·기억 쓰기 — 웹 검색 결과의 지시(프롬프트 주입)로 바뀌면 이후 상담·점검에 계속 실린다. 사용자가 시킨 상담에만 연다.
NOTE_TOOLS = ("rules_set", "memory_set")
CLOSED_HINT = "목록 전체 교체 도구는 닫혀 있습니다. 목적별 변경안(plan_preview)을 검토한 뒤 plan_apply로 반영하세요"

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
     "description": "지금 보유(holdings) 목록을 통째로 바꾼다. avg_buy_price는 평균매입단가(currency 기준), buy_cost_krw는 현재 보유 전체의 총 매수비용(원), 미확인은 null. 매입가를 unit_price에 넣지 않는다. 저장 후 plan_get으로 수량·평균가·원가·성과를 확인한다. as_of는 YYYY-MM-DD.",
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
TOOLS += plan_counsel.TOOLS


async def call_context(db, user_index: int, name: str, args: dict, context: dict):
    if name == "plan_preview":
        return await plan_counsel.preview(db, user_index, args, context)
    if name == "plan_apply":
        return await plan_counsel.apply(db, user_index, args["change_id"], context)
    return await call(db, user_index, name, args)


# ---------------------------------------------------------------------------
# MCP 도구
# ---------------------------------------------------------------------------

async def call(db, user_index: int, name: str, args: dict):
    if name == "plan_schema":
        return plan_counsel.schema()
    if name == "plan_allocate":
        return await plan_counsel.allocate(db, user_index, args)
    if name == "plan_get":
        return await plan_view(db, await latest_rev(db, user_index))
    if name == "node_get":
        view = await plan_view(db, await latest_rev(db, user_index))
        node = next((n for n in view["doc"]["nodes"] if n["id"] == args.get("id")), None)
        if node is None:
            raise ValueError(f"없는 노드입니다: {args.get('id')}")
        return {"node": node, "value": view["values"].get(node["id"]),
                "before": view["execution_before"].get(node["id"]), "retro": view["retro"].get(node["id"]),
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

    old = await resolved_doc(db, await latest_rev(db, user_index))
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
        if (hit.get("executed_at") or hit.get("execution")) and any(hit.get(k) != v for k, v in fields.items()):
            raise ValueError("과거 실행 노드는 고치지 않습니다. 실행 정정을 남기세요")
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
        if any(n["id"] in gone and (n.get("executed_at") or n.get("execution")) for n in nodes):
            raise ValueError("실행 기록이 있는 노드는 삭제할 수 없습니다")
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
    if name == "holdings_set":
        for raw, holding in zip(args["holdings"], new.holdings):
            previous = [h for h in old.holdings if plan_reconcile.key(h) == plan_reconcile.key(holding)]
            # 같은 잔고를 다시 보낸 상담이 매수비용 칸을 생략해도 확인된 비용은 잃지 않는다.
            # 수량이 바뀌었으면 새 비용을 확인해야 하므로 생략된 비용은 미확인으로 둔다.
            if "buy_cost_krw" not in raw and len(previous) == 1 and ip.canonical(previous[0]).qty == ip.canonical(holding).qty:
                holding.buy_cost_krw = previous[0].buy_cost_krw
            if "avg_buy_price" not in raw and len(previous) == 1 and ip.canonical(previous[0]).qty == ip.canonical(holding).qty:
                holding.avg_buy_price = previous[0].avg_buy_price
    if errs := plan_reconcile.quantity_errors(old, new):
        raise ValueError("수량 확인 필요 — 저장하지 않았습니다: " + "; ".join(errs[:8]))
    if old.holdings != new.holdings:
        new.holdings = [ip.as_quantity(h) for h in new.holdings]
    # 실행 이력·기준 잔고는 서버만 쓴다. AI 입력으로 과거 이력을 바꾸지 않는다.
    old_nodes = {n.id: n for n in old.nodes}
    for n in new.nodes:
        previous = old_nodes.get(n.id)
        if n.holdings is not None and (previous is None or previous.holdings != n.holdings):
            n.holdings = [ip.as_quantity(h) for h in n.holdings]
        n.execution = previous.execution.model_copy(deep=True) if previous and previous.execution else None
        n.basis = previous.basis if previous else None
    plan_reconcile.capture_execution(old, new)
    ip.stamp_branches(old, new)
    px = await prices(db, new) if ip.changed_branches(old, new) or old.holdings != new.holdings else None
    if px is not None:
        plan_reconcile.rebase(new, px)
    if ip.changed_branches(old, new):
        if errs := ip.funding_errors(old, new, ip.valuate(new, *px)):
            raise ValueError("재원 초과 — 저장하지 않았습니다: " + "; ".join(errs))
    if new == old:
        return {"saved": False, "summary": "변경 없음"}
    plan_reconcile.preserve_execution(old, new)
    rev_id = await _save_rev(db, user_index, new, what)
    await db.commit()
    return {"saved": True, "rev_id": rev_id, "summary": what,
            "consistency": plan_reconcile.memory_conflicts(new)}


# ---------------------------------------------------------------------------
# 상담
# ---------------------------------------------------------------------------

def tools_for(message: str, last_reply: str = "") -> tuple:
    # 쓰기 범위는 변경안에 묶인 실제 사용자 요청과 서버가 저장한 이전 변경안으로 검증한다.
    return plan_counsel.WRITE_TOOLS


async def begin(db, user_index: int) -> dict:
    """상담 직전 계획 — 프롬프트에 싣고, 끝난 뒤 무엇이 바뀌었는지 견준다."""
    row = await latest_rev(db, user_index)
    doc = await resolved_doc(db, row)
    quotes = await _quotes(db, doc)
    px = _price_maps(quotes)
    plan_reconcile.rebase(doc, px)
    assets = _assets(doc, row, quotes, ip.valuate(doc, *px)["root"])
    return {"row": row, "doc": doc, "assets": assets, "pending": await plan_counsel.pending(db, user_index)}


def prompt(state: dict, now, allow: tuple) -> str:
    base = plan_counsel.prompt(state)
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
    ours = {w["rev_id"] for w in made if w.get("saved") and w.get("rev_id")}
    mine = [r for r in since if r.rev_id in ours]
    drafts = [w for w in made if w.get("prepared")]
    remaining = await plan_counsel.pending(db, user_index) if drafts else []
    remaining_by_id = {p["change_id"]: p for p in remaining}
    proposed = next((remaining_by_id[w["change_id"]] for w in reversed(drafts) if w.get("change_id") in remaining_by_id), None)
    if not mine:
        if proposed:
            return {"source": "plan", "tail": "\n\n[반영 대기]\n" + "\n".join("- " + s for s in proposed["summary"]),
                    "meta": {"plan_change_id": proposed["change_id"]},
                    "toast": "투자계획 변경안을 검토할 수 있습니다", "undo": None, "note": None}
        return None
    latest = await latest_rev(db, user_index)
    new = _doc_of(latest)
    plan_changed = any(getattr(old, f) != getattr(new, f) for f in ("nodes", "strategy", "rules", "memory"))
    undo = row.rev_id if row and plan_changed and len(mine) == len(since) else None
    rev_id = mine[-1].rev_id
    from app.services.plan_changes import summary
    changes = summary(old, new)
    return {
        "source": "plan",
        "tail": "\n\n[바뀐 것]\n" + "\n".join(f"- {c}" for c in changes[:30]) if changes else "",
        "meta": {"plan_rev": rev_id, "badge": f"계획 버전 #{rev_id}",
                 **({"plan_change_id": proposed["change_id"]} if proposed else {})},
        "toast": "계획을 고쳤습니다: " + " · ".join(r.summary for r in mine)[:300] + f" ({ip.diff_summary(old, new)})",
        "undo": {"label": "계획 되돌리기", "method": "POST",
                 "url": f"/api/v1/plan/revisions/{undo}/restore?expect={latest.rev_id}",
                 "done": "계획을 되돌렸습니다. 현재 잔고와 실행 기록은 유지했습니다"} if undo else None,
        "note": "상담 중 다른 저장이 있어 한 번에 되돌리지 않습니다 — 버전 기록에서 고르세요" if row and plan_changed and undo is None else "",
    }
