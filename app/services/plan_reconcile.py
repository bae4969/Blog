"""수량 검증·계획 기준 잔고·실행 이력. 전략과 기억을 임의로 바꾸지 않는다."""

import re

from app.services import invest_plan as ip


def key(h: ip.Holding) -> tuple:
    return h.account, h.market, h.code or h.name, h.currency


def stamp(holdings: list[ip.Holding]) -> str:
    rows = [ip.canonical(h) for h in holdings]
    return ip.holdings_stamp([h.model_copy(update={"amount": None}) if h.qty is not None else h for h in rows])


def quantity_errors(old: ip.PlanDoc, new: ip.PlanDoc) -> list[str]:
    """미확인 옛 줄은 그대로 보존할 수 있다. 새 줄·변경된 줄에는 명시된 수량이 필요하다."""
    legacy = {ip.canonical(h).model_dump_json() for h in ip._all_holdings(old)}
    known = {key(h) for h in old.holdings if h.qty is not None}
    errors = []
    for h in ip._all_holdings(new):
        c = ip.canonical(h)
        signature = c.model_dump_json()
        if h.qty is None:
            if signature in legacy and not (h in new.holdings and key(h) in known):
                continue
            errors.append(f"{h.account or '계좌 없음'} · {h.name}: 수량을 확인해 qty로 저장하세요. 평가액에서 역산하지 마세요")
        elif h.kind in ("stock", "crypto") or h.kind == "bond" and h.code:
            if not h.code or not h.market:
                errors.append(f"{h.name}: 종목 코드·시장·수량이 필요합니다")
        elif h.kind != "cash" and c.code is None and c.unit_price is None:
            errors.append(f"{h.name}: 시세가 없는 자산은 수량과 단가(unit_price)가 필요합니다")
        if h.kind == "cash" and h.unit_price not in (None, 1):
            errors.append(f"{h.name}: 현금은 원통화 1단위가 1개입니다. unit_price는 1입니다")
    return errors


def restore_references(doc: ip.PlanDoc, revisions: list[ip.PlanDoc]) -> None:
    """옛 지문과 실제 잔고 변경을 버전 이력으로 확인한다. 읽을 때도 복원 가능하며 추정 이력은 만들지 않는다."""
    targets = [n for n in doc.nodes if n.kind == "branch" and n.holdings is not None]
    waiting = {}
    for previous in revisions:
        states = ip.states(previous)
        for n in targets:
            if n.basis is None and n.base:
                candidates = [p for p in previous.nodes if p.id == n.id]
                if candidates:
                    parent = states[candidates[0].parent]
                    if ip.holdings_stamp(parent) == n.base:
                        n.basis = [h.model_copy(deep=True) for h in parent]
            if not n.executed_at or n.execution:
                continue
            if n.id in waiting:
                after = waiting[n.id]
                if stamp(previous.holdings) != stamp(after):
                    n.execution = ip.Execution(before=previous.holdings, after=after).model_copy(deep=True)
            elif previous.as_of == n.executed_at and stamp(previous.holdings) == stamp(n.holdings):
                waiting[n.id] = previous.holdings


def _rebase(n: ip.Node, parent: list[ip.Holding], prices: tuple) -> list[ip.Holding]:
    before = {key(h): ip.canonical(h) for h in n.basis}
    after = {key(h): ip.canonical(h) for h in n.holdings}
    result = {key(h): ip.canonical(h) for h in parent}
    costs, cash_changes = {}, {}
    for k in dict.fromkeys([*before, *after]):
        b, a = before.get(k), after.get(k)
        if b == a:
            continue
        if any(h.qty is None for h in (a, b) if h is not None):
            raise ValueError("수량 미확인")
        delta = (a.qty if a else 0) - (b.qty if b else 0)
        ref = a or b
        if ref.kind == "cash":
            cash_changes[k] = delta
            continue
        current = result.get(k)
        if current and current.qty is None:
            raise ValueError("현재 수량 미확인")
        qty = (current.qty if current else 0) + delta
        if qty < -1e-8:
            raise ValueError("보유보다 큰 매도")
        updated = (current or ref).model_copy(update={"qty": max(0, qty), "amount": None})
        if a and b and a.unit_price != b.unit_price:
            updated.unit_price = a.unit_price
        result[k] = updated
        if delta:
            unit_value = ip._value(ref.model_copy(update={"qty": 1, "amount": None}), *prices)[0]
            if unit_value is None:
                raise ValueError("단가 미확인")
            costs[ref.account] = costs.get(ref.account, 0) + delta * unit_value
    for k, delta in cash_changes.items():
        if k[0] in costs:
            continue  # 매매 자금은 갱신된 단가로 아래에서 계산한다.
        current = result.get(k)
        if current is None or current.qty is None or current.qty + delta < -1e-8:
            raise ValueError("현금 수량 미확인 또는 부족")
        result[k] = current.model_copy(update={"qty": max(0, current.qty + delta), "amount": None})
    for account, cost in costs.items():
        cash = [(k, h) for k, h in result.items() if h.account == account and h.kind == "cash"]
        if len(cash) != 1 or cash[0][1].qty is None:
            raise ValueError("결제 통화를 확인해야 하는 계좌")
        k, h = cash[0]
        fx = ip.fx_rate(prices[2], h.currency)
        if not fx or h.qty - cost / fx < -1e-8:
            raise ValueError("환율 미확인 또는 현금 부족")
        result[k] = h.model_copy(update={"qty": max(0, h.qty - cost / fx), "amount": None})
    return list(result.values())


def rebase(doc: ip.PlanDoc, prices: tuple) -> list[str]:
    """기존 매수·매도 수량을 유지해 기준 잔고와 예상 결제금액을 갱신한다. 결정·날짜·원칙은 유지한다."""
    changed, visited = [], set()
    by_id = {n.id: n for n in doc.nodes}
    def visit(n):
        if n.id in visited:
            return
        if n.parent:
            visit(by_id[n.parent])
        visited.add(n.id)
        if n.kind != "branch" or n.execution or n.executed_at or n.holdings is None or n.basis is None:
            return
        parent = ip.states(doc)[n.parent]
        if stamp(n.basis) == stamp(parent):
            # 어댑터가 변환한 옛 줄도 같은 기준임을 보존한다.
            n.base = ip.holdings_stamp(parent)
            return
        try:
            holdings = _rebase(n, parent, prices)
        except ValueError:
            return  # 재원·수량을 알 수 없으면 기존 stale 경고를 유지한다.
        n.holdings = holdings
        n.basis = [h.model_copy(deep=True) for h in parent]
        n.base = ip.holdings_stamp(parent)
        changed.append(n.id)
    for n in doc.nodes:
        visit(n)
    return changed


def capture_execution(old: ip.PlanDoc, new: ip.PlanDoc) -> None:
    if stamp(old.holdings) == stamp(new.holdings):
        return
    candidates = [n for n in new.nodes if n.kind == "branch" and n.executed_at and not n.execution
                  and n.holdings is not None and stamp(n.holdings) == stamp(new.holdings)]
    if len(candidates) == 1:
        candidates[0].execution = ip.Execution(before=old.holdings, after=new.holdings).model_copy(deep=True)


_EACH = re.compile(r"각(?:각)?\s*(?:약\s*)?([\d,.]+)\s*(만|억|원)")
_DATES = re.compile(r"\d{4}-\d{2}-\d{2}")


def memory_conflicts(doc: ip.PlanDoc) -> list[dict]:
    """같은 날짜의 '각 N원' 매수 기억과 계획의 명시된 예산만 비교한다. 애매한 문장은 단정하지 않는다."""
    by_id = {n.id: n for n in doc.nodes}
    states = ip.states(doc)
    def each(text):
        match = _EACH.search(text)
        return float(match[1].replace(",", "")) * {"만": 1e4, "억": 1e8, "원": 1}[match[2]] if match else None
    def mentions(memory, node):
        def clean(s):
            return re.sub(r"[^A-Za-z0-9가-힣]", "", s.replace("액티브", ""))
        before = {key(h): ip.canonical(h) for h in node.basis or states[node.parent]}
        actions = " ".join(node.actions)
        for h in node.holdings or []:
            if h.kind == "cash":
                continue
            old = before.get(key(h))
            if old and old.qty == ip.canonical(h).qty and not (h.code and h.code in actions or h.name in actions):
                continue
            name = re.sub(r"^(KODEX|TIGER|RISE|ACE|SOL|PLUS|HANARO)\s*", "", h.name)
            if h.code and h.code in memory or len(clean(name)) >= 5 and clean(name) in clean(memory):
                return True
        return False
    issues = []
    for memory in doc.memory:
        amount, dates = each(memory), set(_DATES.findall(memory))
        if amount is None or not dates or not re.search(r"매수|산다|분할", memory):
            continue
        matches, budgets, plan_dates = [], [], set()
        for n in doc.nodes:
            parent = by_id.get(n.parent)
            if n.kind != "branch" or n.status == "dropped" or parent is None:
                continue
            budget = each(n.condition)
            at = ip._kst(parent.at).date().isoformat() if parent.at else ""
            if not mentions(memory, n):
                continue
            plan_dates.add(at)
            if at in dates and budget is not None and budget != amount:
                budgets.append(n.id)
            if at in dates:
                matches.append(n.id)
        schedule = bool(plan_dates and dates - plan_dates and re.search(r"날짜|분할|회차|일정", memory))
        if budgets or schedule:
            issues.append({"kind": "memory_plan", "memory": memory, "nodes": budgets or matches,
                           "differences": (["budget"] if budgets else []) + (["schedule"] if schedule else []),
                           "message": "기억과 계획의 매수 금액·일정이 다릅니다. 현재 계획을 기준으로 확인해 주세요"})
    return issues
