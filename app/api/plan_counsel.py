"""목적별 상담 도구: 미리보기 → 버전/승인 범위 확인 → 원자적 반영."""

import hashlib
import json
import secrets
from datetime import datetime

from sqlalchemy import text

from app.api import plan_v1 as pv
from app.api.mcp import RO, RW, obj
from app.services import invest_plan as ip, plan_changes as pc, plan_strategy as ps

WRITE_TOOLS = ("plan_preview", "plan_apply")
TOOLS = [
    {"name": "plan_preview", "annotations": RW,
     "description": "목표·원칙·결정·관찰·잔고 변경을 한 묶음으로 검증하고 변경안만 보관한다. 실제 계획은 아직 안 바뀐다. 원칙의 목표비중은 ETF 잔고 기준. 변경할 잔고만 holding_patch. 서버가 받은 현재 사용자 발화를 근거로 기록한다. 형식은 plan_schema로 조회.",
     "inputSchema": pc.Change.model_json_schema()},
    {"name": "plan_apply", "annotations": RW,
     "description": "plan_preview의 변경안 id를 반영한다. 사용자 현재 명시적 요청 범위 또는 직전 제시된 변경안에 대한 확인만 허용한다. 변경 중간 실패·버전 충돌은 전부 취소. 같은 id 재시도는 중복 반영하지 않는다.",
     "inputSchema": obj({"change_id": {"type": "string"}}, ["change_id"])},
    {"name": "plan_schema", "annotations": RO,
     "description": "목표·원칙·결정·관찰·실행과 변경 묶음의 입력 형식. 먼저 읽어 정확한 칸을 사용한다.",
     "inputSchema": obj()},
    {"name": "plan_allocate", "annotations": RO,
     "description": "확정된 계좌별 ETF 목표 비중으로 추가 매수 수량을 계산한다. 입금액을 비율로 나누지 않는다. 기존 잔고 부족 비중을 보정. 원가가 없어도 수량·시세가 있으면 계산 가능. 저장·주문은 안 한다.",
     "inputSchema": obj({"policy_id": {"type": "string"}, "budget": {"type": "number", "minimum": 0},
                         "decision_id": {"type": "string", "description": "기존 선택한 계획을 계산할 때 그 결정 id. 그 계획의 예산만 중복 예약에서 제외한다"},
                         "fee_rate": {"type": "number", "minimum": 0, "maximum": .1}}, ["policy_id", "budget"])},
]


def schema():
    return {"operations": pc.Change.model_json_schema(), "goal_upsert": ps.Goal.model_json_schema(),
            "policy_upsert": ps.Policy.model_json_schema(), "decision_upsert": ps.Decision.model_json_schema(),
            "observation_upsert": ps.Observation.model_json_schema(), "holding_patch": ip.Holding.model_json_schema(),
            "account_upsert": ip.Account.model_json_schema(), "debt_upsert": ip.Debt.model_json_schema(),
            "cashflow_upsert": ip.Flow.model_json_schema(), "execution_record": ip.ExecutionRecord.model_json_schema(),
            "note_add/remove": {"field": "rules|memory", "text": "원문"},
            "node_patch": "기존 노드 id와 바꿀 칸. 실행 노드는 불가", "node_archive": {"id": "기존 미실행 노드"}}


async def pending(db, user: int) -> list[dict]:
    rows = (await db.execute(text("SELECT change_id, base_rev, payload, created_at FROM invest_plan_change "
                                  "WHERE user_index=:u AND status='pending' ORDER BY created_at DESC LIMIT 10"), {"u": user})).all()
    return [{"change_id": r.change_id, "base_rev": r.base_rev, "created_at": r.created_at.isoformat(),
             **{k: json.loads(r.payload)[k] for k in ("summary", "operations", "source")}} for r in rows]


async def preview(db, user: int, args: dict, context: dict) -> dict:
    change = pc.Change.model_validate(args)
    source = context.get("message", "")
    if not source:
        raise ValueError("사용자 요청과 연결된 상담에서 변경안을 만드세요")
    fingerprint = hashlib.sha256(json.dumps(args, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    async with pv.write_lock(user):
        existing = (await db.execute(text("SELECT change_id, payload, result_rev FROM invest_plan_change "
                                          "WHERE user_index=:u AND request_key=:k"), {"u": user, "k": change.request_key})).first()
        if existing:
            payload = json.loads(existing.payload)
            if payload["fingerprint"] != fingerprint:
                raise ValueError("같은 요청 키의 내용이 다릅니다. 새 변경에는 새 request_key를 쓰세요")
            return {"prepared": True, "change_id": existing.change_id, "summary": payload["summary"],
                    "applied_rev": existing.result_rev}
        row = await pv.latest_rev(db, user)
        if (row.rev_id if row else 0) != change.base_rev:
            raise ValueError("그 사이 계획이 바뀌었습니다. plan_get으로 다시 읽고 변경안을 만드세요")
        old = await pv.resolved_doc(db, row)
        new = pc.build(old, change, source, datetime.now(pv._KST))
        await validate_funding(db, old, new)
        lines = pc.summary(old, new)
        if not lines:
            return {"prepared": False, "summary": ["변경 없음"]}
        change_id = secrets.token_hex(16)
        payload = {"fingerprint": fingerprint, "operations": [o.model_dump(mode="json") for o in change.operations],
                   "summary": lines, "source": source, "doc": new.model_dump(mode="json"),
                   "turn_id": context.get("turn_id"), "direct_scopes": sorted(pc.direct_scopes(source))}
        await db.execute(text("INSERT INTO invest_plan_change (change_id,user_index,request_key,base_rev,payload) "
                              "VALUES (:c,:u,:k,:b,:p)"),
                         {"c": change_id, "u": user, "k": change.request_key, "b": change.base_rev,
                          "p": json.dumps(payload, ensure_ascii=False)})
        await db.commit()
        return {"prepared": True, "change_id": change_id, "summary": lines,
                "can_apply": bool(context.get("turn_id")) and pc.direct_allowed(source, change.operations),
                "note": "변경안만 보관했습니다. 반영 전에는 저장 완료라고 말하지 마세요"}


async def validate_funding(db, old: ip.PlanDoc, new: ip.PlanDoc) -> None:
    px = await pv.prices(db, new)
    values = ip.valuate(new, *px)
    if ip.changed_branches(old, new):
        if errors := ip.funding_errors(old, new, values):
            raise ValueError("재원 초과 — " + "; ".join(errors))
    current = ps.review(new.strategy, values["root"]["rows"], datetime.now(pv._KST).date(), new.execution_log)
    # 자산 사실 갱신은 막지 않는다. 새로 선택/수정한 계획의 예산을 검사한다.
    affected = set()
    for decision in new.strategy.decisions:
        if decision.status != "selected" or decision == next((d for d in old.strategy.decisions if d.id == decision.id), None):
            continue
        chosen = next(s for s in decision.scenarios if s.id == decision.selected_id)
        if chosen.policy_id and not any(p.id == chosen.policy_id and p.status == "confirmed" for p in new.strategy.policies):
            raise ValueError("새로 선택하는 계획은 현재 확정된 운용 원칙을 참조해야 합니다")
        affected.add(chosen.account)
    for policy in new.strategy.policies:
        prev = next((p for p in old.strategy.policies if p.account == policy.account and p.status == "confirmed"), None)
        if policy.status == "confirmed" and policy.reserve_cash > (prev.reserve_cash if prev else 0):
            affected.add(policy.account)
    if affected:
        bad = [r["account"] for r in current["funding"] if not r["ok"] and r["account"] in affected]
        if bad:
            raise ValueError("동시 계획의 재원 부족 또는 현금 미확인: " + ", ".join(bad))


async def apply(db, user: int, change_id: str, context: dict | None = None, *, confirmed: bool = False) -> dict:
    context = context or {}
    async with pv.write_lock(user):
        r = (await db.execute(text("SELECT change_id, base_rev, payload, result_rev, status FROM invest_plan_change "
                                   "WHERE user_index=:u AND change_id=:c FOR UPDATE"), {"u": user, "c": change_id})).first()
        if r is None:
            raise ValueError("변경안이 없습니다")
        if r.status == "applied":
            return {"saved": False, "already_applied": True, "rev_id": r.result_rev, "summary": "이미 반영한 변경안입니다"}
        if r.status != "pending":
            raise ValueError("폐기한 변경안입니다")
        payload = json.loads(r.payload)
        ops = [pc.Operation.model_validate(o) for o in payload["operations"]]
        message = context.get("message", "")
        if not confirmed:
            direct = bool(context.get("turn_id")) and context["turn_id"] == payload.get("turn_id") \
                and message == payload["source"] and pc.direct_allowed(message, ops)
            previous = context.get("previous_meta", {})
            consent = previous.get("plan_change_id") == change_id and pc.affirmative(message)
            if not (direct or consent):
                raise ValueError("변경안 확인이 필요합니다. 변경 내용을 알리고 사용자 확인을 기다리세요")
        row = await pv.latest_rev(db, user)
        if (row.rev_id if row else 0) != r.base_rev:
            raise ValueError("그 사이 계획이 바뀌어 반영하지 않았습니다. 다시 검토하세요")
        old = await pv.resolved_doc(db, row)
        new = ip.PlanDoc.model_validate(payload["doc"])
        approval = "화면에서 변경안 반영" if confirmed else message
        applied_at = datetime.now(pv._KST)
        for field in ("goals", "policies", "decisions", "observations"):
            for item in getattr(new.strategy, field):
                if item.evidence.base_rev == r.base_rev and item.evidence.source == payload["source"]:
                    item.evidence.applied_at, item.evidence.authorization = applied_at, approval[:2000]
        await validate_funding(db, old, new)
        rev = await pv._save_rev(db, user, new, " · ".join(payload["summary"]))
        payload["approval"] = {"source": approval, "at": applied_at.isoformat()}
        await db.execute(text("UPDATE invest_plan_change SET status='applied', result_rev=:r, payload=:p WHERE change_id=:c AND user_index=:u"),
                         {"r": rev, "c": change_id, "u": user, "p": json.dumps(payload, ensure_ascii=False)})
        await db.commit()
        return {"saved": True, "rev_id": rev, "summary": " · ".join(payload["summary"]),
                "verified": {"strategy": new.strategy.model_dump(mode="json"), "execution_records": len(new.execution_log)},
                "next": "plan_get으로 반영 결과를 재확인하세요"}


async def allocate(db, user: int, args: dict) -> dict:
    row = await pv.latest_rev(db, user)
    doc = pv._doc_of(row)
    policy = next((p for p in doc.strategy.policies if p.id == args.get("policy_id")), None)
    if not policy:
        raise ValueError("운용 원칙이 없습니다")
    quotes = await pv._quotes(db, doc)
    view = pv._assets(doc, row, quotes, ip.valuate(doc, *pv._price_maps(quotes))["root"])
    # _assets는 계좌 그룹을 위한 뷰이므로 계산용 행은 원 시세와 함께 별도로 구성한다.
    values = ip.valuate(doc, *pv._price_maps(quotes))["root"]["rows"]
    for r in values:
        q = quotes["stocks"].get(r.get("code"), {})
        r["quote_stale"] = bool(q.get("stale"))
        r["quote_at"] = str(q.get("as_of") or "")
    decision_id = args.get("decision_id")
    if decision_id and not any(d.id == decision_id for d in doc.strategy.decisions):
        raise ValueError("계산할 결정이 없습니다")
    remaining = doc.strategy.model_copy(deep=True)
    remaining.decisions = [d for d in remaining.decisions if d.id != decision_id]
    funding = ps.review(remaining, values, datetime.now(pv._KST).date(), doc.execution_log)["funding"]
    reserved = sum(f["reserved"] for f in funding if f["account"] == policy.account)
    effective = policy.model_copy(update={"reserve_cash": policy.reserve_cash + reserved})
    result = ps.allocate(effective, values, float(args["budget"]), float(args.get("fee_rate", 0)))
    return {**result, "base_rev": row.rev_id, "checked_at": view["checked_at"],
            "other_plan_reserved": reserved,
            "holdings_as_of": view["holdings_as_of"],
            "quotes": [{"code": r["code"], "at": r["quote_at"]} for r in values if r.get("code")]}


def prompt(state: dict) -> str:
    return """# 투자계획 시나리오 상담사
목표·제약 → 현재 자산 → 대안 비교 → 계획 선택 → 관찰 → 실제 실행 확인의 순서로 판단한다.
사용자가 물은 범위만 처리하고 이미 확인된 사실·원칙은 다시 묻지 않는다. 질문이 작으면 필요한 단계만 수행한다.
목표가 비어 있어도 가능한 진단부터 하고 결론을 바꿀 질문만 묻는다. 돈의 사용 시점·필요 현금·감당 가능한 손실과 감수 의향을 구분한다.
일정 추가만으로 투자계획이 완성됐다고 말하지 않는다. 관찰만 요청하면 매매나 원칙 변경을 만들지 않는다.
추천안을 먼저 제시하고 유지·분할·보류 등 의미 있는 대안과 같은 기준으로 비교한다. 이유는 사용자의 자산·목표와 연결한다.
동조하거나 고집하지 않는다. 새 사실로 판단이 바뀌면 무엇이 달라졌는지 설명한다. 근거 없는 확률·예상 수익률은 만들지 않는다.

## 정본과 계산
plan_get은 현재 사실과 확인된 원칙의 정본이다. 과거 AI 답은 증거가 아니다. 아래 뼈대에는 현재 운용 원칙·미결 결정도 있다.
strategy.policies의 confirmed는 계좌별 ETF 자체의 잔고 비중이다. 새 납입액 배분이나 ETF 내부 자산 노출 비중으로 바꾸지 않는다.
목표 종목 연결이 불분명하면 묻고, 확인됐으면 반복 질문하지 않는다. 잘못 기록한 원칙은 새 id+supersedes로 바로잡아 원본을 보존한다.
rules/memory와 구조화 원칙을 중복 복사하지 않는다. 충돌한 옛 문장을 정리할 때는 정확한 원문을 note_remove로 함께 처리한다.
몇 주씩 살지는 plan_allocate로 계산한다. 예산은 입금 예상액이 아니라 확인된 해당 계좌 현금이다. 원가가 없어도 배분 계산은 가능하다.
수량·시세·현금이 부족하면 필요한 사실만 묻는다. 비중 오차·잔여 현금·시세 시점을 제시하고 실제 거래 가능 여부를 확인하지 않은 계산은 주문 확정으로 말하지 않는다.
계산 표에는 종목명·코드·수량·금액을 함께 쓴다. plan_allocate는 정수 수량 근사안이며 '가장 가깝다/최적'이라고 단정하지 않는다.
각 종목의 deviation_pp와 max_deviation_pp(최대 절대 편차), total_absolute_deviation_pp(절대 편차 합계)는 이미 %p 단위다. 합계를 최대 편차라고 부르거나 100을 다시 곱하지 않는다.

## 변경 도구
plan_schema에서 필요한 형식을 확인한다. plan_preview(base_rev, request_key, operations)는 변경안 검증·보관만 하며 실제 자산과 계획을 바꾸지 않는다.
한 요청의 변경은 하나의 operations에 묶는다. node_add/delete·목록 전체교체 대신 목적별 연산을 쓴다.
plan_apply(change_id)가 saved=true를 돌려줘야 반영된 것이다. 사용자의 명시적 요청 범위면 즉시 반영한다.
승인 범위가 모호해 can_apply=false라면 변경 내용을 보여주고 한 번 확인한다. 기존 변경안에 사용자가 '응/진행'이라면 새 안을 만들지 말고 그 id를 적용한다.
이미 반영한 id는 재시도해도 중복되지 않는다. 버전 충돌이면 plan_get으로 다시 읽고 차이를 재검토한다.
반영 후 plan_get으로 결과를 재조회해 실제 바뀐 것과 미확인을 구분한다. 저장되지 않은 것을 완료라고 말하지 않는다.
스키마/검증 오류를 우회하려고 범위를 넓히거나 원칙을 삭제하지 않는다.

## 사실과 실행
부분 이미지의 보이는 줄만 holding_patch. 보이지 않는 종목은 없애지 않는다. 코드+시장+계좌로 식별하고 수량·평균가·총매입비용·남은 현금을 구분한다.
보이지 않거나 바뀌지 않은 종목은 holding_patch 목록에도 넣지 않는다. 기존 종목의 단위·유형을 정리하는 작업으로 범위를 넓히지 않는다.
avg_buy_price는 평균매입가, buy_cost_krw는 현재 수량 전체의 확인된 원화 총매수비용, unit_price는 별도 시세 없는 자산의 평가단가다.
원화 평균가×수량은 추정 원가이며 확정 총비용으로 쓰지 않는다. 외화 평균가를 오늘 환율로 매수원가로 만들지 않는다.
수량 변경 시 새 원가가 없으면 미확인이다. 수익률 요청은 저장 후 assets의 pnl_pct/pnl_estimated까지 확인한다.
'항상 매입가도 봐'는 실제 잔고 반영과 이후 원칙 기록 두 요청일 수 있다. 하나를 저장하고 다른 하나를 빠뜨리지 않는다.
현재 보유 평가손익과 기간 투자성과는 다르다. 입출금·분배금·매도 이력 없이 기간 성과를 만들지 않는다.
실행은 execution_record로 reported(사용자 보고), partial/confirmed(실제 전후 잔고), corrected(원본 지정 정정)를 구분한다.
조건 충족이나 계획 수량을 체결로 기록하지 않는다. 실제 전후 자료가 없는 거래는 reported로 둔다.

## 목표·결정·관찰
goal_upsert: 목적·기간·필요 자금·제약·미결 질문. 결정은 decision_upsert, 관찰 일정은 observation_upsert.
decision.scenarios는 같은 문제에 대한 대안이며 selected_id는 사용자가 선택한 하나다. 초안은 draft, 확정은 selected. 사용자 선택 전 확정하지 않는다.
각 시나리오에 가정·근거·조건·대응·예산·중단 조건·조건 미발생 대응·재검토일을 연결한다. 조건 미정은 초안으로 둔다.
미래 조건부 계획에 현재가로 고정 주문을 만들지 않는다. 실행할 때 잔고·시세를 갱신해 계산한다. 두 조건이 겹치면 중복 실행하지 않도록 선택 관계를 설명한다.
동시에 선택한 별개 계획은 재원을 합산한다. 순수 관찰은 예산 없이 일정만 남겨도 된다. 날짜순 배열에 가짜 '관찰 완료' 가지를 만들지 않는다.
기존 트리는 과거 기록이다. 표시 정리는 삭제가 아니며 실행 노드 편집·삭제는 하지 않는다. 신규 결정은 과거 실행을 참조하되 독립적으로 저장한다.
답은 결론 → 내 자산 기준 이유 → 필요한 대안 → 지금 할 일/재검토 조건으로 짧게 한다. 모든 칸을 매번 늘어놓지 않는다.
답 본문에 변경안의 내부 id·버전 번호·영문 상태값을 나열하지 않는다. 사람에게는 변경 내용과 확정/미반영 여부를 알려준다.
""" + "\n현재 버전: " + str(state["row"].rev_id if state.get("row") else 0) + "\n" + ip.notes_block(state["doc"]) + \
        "\n현재 사실·계획:\n" + json.dumps(ip.outline(state["doc"]), ensure_ascii=False) + \
        "\n검토 중 변경안:\n" + json.dumps(state.get("pending", []), ensure_ascii=False)
