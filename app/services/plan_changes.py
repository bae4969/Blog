"""상담 변경 묶음의 순수 검증. 부분 잔고·관찰·운용 원칙은 목적별로 변경한다."""

from datetime import datetime
import re

from pydantic import Field

from app.services import invest_plan as ip, plan_reconcile, plan_strategy as ps


class Operation(ps.Strict):
    kind: str = Field(pattern=r"^(holding_patch|account_upsert|debt_upsert|cashflow_upsert|goal_upsert|policy_upsert|decision_upsert|observation_upsert|note_add|note_remove|node_patch|node_archive|execution_record)$")
    data: dict


class Change(ps.Strict):
    base_rev: int = Field(ge=0)
    request_key: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    operations: list[Operation] = Field(min_length=1, max_length=50)


def _upsert(rows: list, item: dict, key: str) -> None:
    if key not in item:
        raise ValueError(f"{key}가 필요합니다")
    index = next((i for i, r in enumerate(rows) if r.get(key) == item[key]), None)
    if index is None:
        rows.append(item)
    else:
        rows[index] = item


def _fields(data, model):
    extra = set(data) - set(model.model_fields)
    if extra:
        raise ValueError("알 수 없는 칸: " + ", ".join(sorted(extra)))


def build(old: ip.PlanDoc, change: Change, source: str, now: datetime) -> ip.PlanDoc:
    data = old.model_dump(mode="json")
    evidence = ps.Evidence(source=source[:2000], at=now, base_rev=change.base_rev).model_dump(mode="json")
    for operation in change.operations:
        kind, item = operation.kind, dict(operation.data)
        if kind == "holding_patch":
            _fields(item, ip.Holding)
            if "amount" in item:
                raise ValueError("새 잔고는 amount 대신 실제 수량 qty와 필요한 단가를 기록하세요")
            if not item.get("account") or not (item.get("code") or item.get("name")):
                raise ValueError("잔고 변경에는 계좌와 종목 코드(시세 없는 자산은 이름)가 필요합니다")
            matches = [r for r in data["holdings"] if r.get("account") == item["account"]
                       and (r.get("code") == item["code"] and r.get("market") == item.get("market") if item.get("code")
                            else r.get("name") == item["name"] and r.get("currency", "KRW") == item.get("currency", "KRW"))]
            if len(matches) > 1:
                raise ValueError("잔고가 중복됩니다. 계좌·종목·통화를 확인하세요")
            if matches:
                row = matches[0]
                def normalized(raw):
                    h = ip.canonical(ip.Holding.model_validate(raw))
                    if h.type is None:
                        h.type = next((a.type for a in old.accounts if a.name == h.account), None)
                    return h
                # 조회 어댑터가 붙인 단위·계좌 유형만 재전송된 경우 원본의 다른 종목은 건드리지 않는다.
                if normalized(row) == normalized({**row, **item}):
                    continue
                if "qty" in item and item["qty"] != row.get("qty"):
                    for cost in ("buy_cost_krw", "avg_buy_price"):
                        row[cost] = None
                    row["amount"] = None
                row.update(item)
            else:
                data["holdings"].append(item)
        elif kind in ("account_upsert", "debt_upsert", "cashflow_upsert"):
            field, model = {"account_upsert": ("accounts", ip.Account), "debt_upsert": ("debts", ip.Debt),
                            "cashflow_upsert": ("cashflow", ip.Flow)}[kind]
            _fields(item, model)
            # 같은 이름의 현금흐름도 계좌·종류로 구분한다.
            if kind == "cashflow_upsert":
                hits = [i for i, r in enumerate(data[field]) if (r.get("name"), r.get("account"), r.get("kind"))
                        == (item.get("name"), item.get("account"), item.get("kind"))]
                if len(hits) > 1:
                    raise ValueError("현금흐름 항목이 중복됩니다")
                if hits:
                    data[field][hits[0]] = item
                else:
                    data[field].append(item)
            else:
                previous = next((r for r in data[field] if r.get("name") == item.get("name")), {})
                _upsert(data[field], {**previous, **item}, "name")
        elif kind in ("goal_upsert", "policy_upsert", "decision_upsert", "observation_upsert"):
            field = {"goal_upsert": "goals", "policy_upsert": "policies", "decision_upsert": "decisions",
                     "observation_upsert": "observations"}[kind]
            item["evidence"] = evidence
            if kind == "policy_upsert":
                existing = next((p for p in data["strategy"][field] if p["id"] == item.get("id")), None)
                if existing and existing["status"] in ("confirmed", "superseded"):
                    raise ValueError("확정 원칙은 새 id와 supersedes로 대체하세요. 원본은 보존합니다")
                if item.get("supersedes"):
                    prev = next((p for p in data["strategy"][field] if p["id"] == item["supersedes"]), None)
                    if not prev or prev["account"] != item.get("account"):
                        raise ValueError("대체할 계좌 원칙을 확인하세요")
                    if item.get("status") != "confirmed":
                        raise ValueError("확정된 새 원칙만 이전 원칙을 대체합니다")
                    prev["status"] = "superseded"
            _upsert(data["strategy"][field], item, "id")
        elif kind in ("note_add", "note_remove"):
            if set(item) != {"field", "text"} or item["field"] not in ("rules", "memory"):
                raise ValueError("field(rules|memory)와 text가 필요합니다")
            rows = data[item["field"]]
            if kind == "note_add" and item["text"] not in rows:
                rows.append(item["text"])
            elif kind == "note_remove":
                if item["text"] not in rows:
                    raise ValueError("제거할 원문이 없습니다")
                rows.remove(item["text"])
        elif kind == "node_patch":
            _fields(item, ip.Node)
            node = next((n for n in data["nodes"] if n["id"] == item.get("id")), None)
            if not node:
                raise ValueError("기존 노드만 수정할 수 있습니다. 새 일정은 observation, 새 계획은 decision을 쓰세요")
            if node.get("executed_at") or node.get("execution"):
                raise ValueError("과거 실행 노드는 수정하지 않습니다. 새 결정이나 실행 정정을 남기세요")
            if set(item) & {"execution", "basis", "base", "executed_at"}:
                raise ValueError("실행·기준 잔고는 일반 노드 편집으로 바꿀 수 없습니다")
            node.update(item)
        elif kind == "node_archive":
            node = next((n for n in data["nodes"] if n["id"] == item.get("id")), None)
            if not node or set(item) != {"id"}:
                raise ValueError("보관할 노드 id가 필요합니다")
            if node.get("executed_at") or node.get("execution"):
                raise ValueError("실행 기록은 보존합니다. 화면의 과거 보기로 확인하세요")
            node["status"] = "dropped"
        elif kind == "execution_record":
            if not item.get("source"):
                raise ValueError("실행 보고·잔고 확인의 근거가 필요합니다")
            record = ip.ExecutionRecord.model_validate(item)
            refs = {n.id for n in old.nodes} | {d["id"] for d in data["strategy"]["decisions"]}
            if record.reference not in refs:
                raise ValueError("실행을 연결할 결정 또는 노드가 없습니다")
            if any(r["id"] == record.id for r in data["execution_log"]):
                raise ValueError("실행 id가 이미 있습니다. 정정은 새 id로 기록하세요")
            if record.status in ("confirmed", "partial"):
                if record.before != old.holdings:
                    raise ValueError("실행 전 잔고가 현재 확인된 잔고와 다릅니다")
                # 이번에 확인된 실제 after를 명시적으로 반영한다. 계획 수량을 체결로 추정하지 않는다.
                data["holdings"] = [h.model_dump(mode="json") for h in record.after]
                data["as_of"] = record.at.isoformat()
            data["execution_log"].append(record.model_dump(mode="json"))
    new = ip.PlanDoc.model_validate(data)
    errors = plan_reconcile.quantity_errors(old, new)
    if errors:
        raise ValueError("; ".join(errors[:8]))
    plan_reconcile.preserve_execution(old, new)
    for n in new.nodes:
        previous = next((p for p in old.nodes if p.id == n.id), None)
        n.execution = previous.execution if previous else None
        n.basis = previous.basis if previous else None
    ip.stamp_branches(old, new)
    return new


def summary(old: ip.PlanDoc, new: ip.PlanDoc) -> list[str]:
    lines = ip.change_lines(old, new)
    before = {plan_reconcile.key(h): h for h in old.holdings}
    for h in new.holdings:
        prev = before.get(plan_reconcile.key(h))
        for field, label in (("qty", "수량"), ("avg_buy_price", "평균매입가"), ("buy_cost_krw", "총매수비용")):
            a, b = getattr(prev, field, None), getattr(h, field)
            if a != b:
                lines.append(f"{h.account} · {h.name} {label}: {a if a is not None else '미확인'} → {b if b is not None else '미확인'}")
    for field, label in (("goals", "목표"), ("policies", "운용 원칙"), ("decisions", "결정"), ("observations", "관찰")):
        previous = {r.id: r for r in getattr(old.strategy, field)}
        for row in getattr(new.strategy, field):
            if row != previous.get(row.id):
                lines.append(f"{label}: {row.title}")
                if field == "policies":
                    status = {"draft": "초안", "confirmed": "확정", "superseded": "이전 원칙 보존"}[row.status]
                    lines.append(f"{row.account} · ETF 잔고 기준 · " + " / ".join(f"{t.name} {t.weight * 100:g}%" for t in row.targets)
                                 + f" · {'매도 금지' if row.buy_only else '매도 허용'} · 보존 현금 {row.reserve_cash:g}원 · {status}")
                elif field == "decisions":
                    selected = next((s for s in row.scenarios if s.id == row.selected_id), None)
                    lines.append(f"{row.question} · " + (f"선택: {selected.title} · {selected.budget:g}원" if selected else "미선택 초안"))
                elif field == "observations":
                    lines.append(f"{row.at.isoformat()} · {row.purpose} · {row.source}")
    if len(new.execution_log) > len(old.execution_log):
        lines.append("실행 기록 추가(기존 기록 보존)")
    if old.nodes != new.nodes:
        lines.append(ip.diff_summary(old, new))
    return lines


def direct_scopes(message: str) -> set[str]:
    """사용자가 현재 말한 명시적 변경 요청만 허용한다. 모호한 제안은 확인된 변경안으로 반영.

    단어 '원칙'만으로 쓰기를 열지 않는다. 부정/질문은 보수적으로 미리보기로 남긴다.
    """
    scopes = set()
    patterns = (("facts", "잔고|보유|수량|매입|입금|자산|현금|계좌|부채|수입|지출"),
                ("policy", "원칙|규칙|비중|비율|매도|항상|늘"), ("notes", "원칙|기억|잊|메모"),
                ("goals", "목표|목적|기간"), ("decisions", "계획|시나리오|결정"),
                ("observations", "관찰|일정|이벤트|점검"), ("execution", "체결|매매했|매수했|실행|샀어|팔았"))
    # 별도 문장의 금지는 다른 문장의 명시적 요청을 취소하지 않는다.
    # 같은 문장 안의 부정·질문·인용은 모호하므로 변경안 확인으로 남긴다.
    for sentence in re.findall(r"[^.!?？。\n]+[.!?？。]?", message):
        if re.search(r"[?？]|하지\s*마|말아|말고|검토만|분석만|제안만|기록했|저장했|[\"“”‘’]", sentence):
            continue
        if not re.search(r"저장해|기록해|반영해|갱신해|등록해|추가해|남겨|바꿔|기억해|고쳐|수정해|삭제해|지워", sentence):
            continue
        if re.search(r"(?:관찰\s*)?(?:일정|관찰|점검)만", sentence):
            scopes.add("observations")
            continue
        scopes.update(scope for scope, pattern in patterns if re.search(pattern, sentence))
    return scopes


def scope(operation: Operation) -> str:
    return {"holding_patch": "facts", "account_upsert": "facts", "debt_upsert": "facts", "cashflow_upsert": "facts",
            "goal_upsert": "goals", "policy_upsert": "policy", "decision_upsert": "decisions",
            "observation_upsert": "observations", "note_add": "notes", "note_remove": "notes",
            "node_patch": "decisions", "node_archive": "decisions", "execution_record": "execution"}[operation.kind]


def affirmative(message: str) -> bool:
    return bool(re.fullmatch(r"\s*(응|ㅇㅇ|네|예|좋아|ㄱ|진행|진행해|진행해줘|저장해|저장해줘|반영해|반영해줘)[.!\s]*", message))


def direct_allowed(message: str, operations: list[Operation]) -> bool:
    if not {scope(o) for o in operations} <= direct_scopes(message):
        return False
    # 제안 작성 지시를 실제 대안 선택으로 확대하지 않는다.
    for op in operations:
        if op.kind == "decision_upsert" and op.data.get("status") == "selected" and not re.search("선택해|선택해서|선택한|확정해|확정한|채택해", message):
            return False
        if op.kind == "execution_record" and op.data.get("status") in ("confirmed", "partial", "corrected"):
            return False  # 전후 잔고/정정 묶음은 사용자가 실제 변경안을 확인한다.
    return True
