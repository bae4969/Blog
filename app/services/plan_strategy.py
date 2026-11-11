"""목표·원칙·결정·관찰. 시나리오는 미래 가정이고 실제 잔고/실행과 별개다."""

from datetime import date, datetime
import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Id = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,32}$")]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
Money = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Evidence(Strict):
    source: str = Field(default="", max_length=2000)
    at: datetime | None = None
    base_rev: int | None = None
    applied_at: datetime | None = None
    authorization: str = Field(default="", max_length=2000)


class Goal(Strict):
    id: Id
    title: Text
    purpose: Text
    horizon: date | None = None
    amount: Money | None = None
    reserve: Money | None = None
    loss_capacity: Money | None = None
    risk_preference: str = Field(default="", max_length=1000)
    open_questions: list[Text] = Field(default_factory=list, max_length=10)
    evidence: Evidence = Field(default_factory=Evidence)


class Target(Strict):
    code: str = Field(pattern=r"^[A-Za-z0-9._/-]{1,32}$")
    market: Literal["KR", "US"]
    name: str = Field(min_length=1, max_length=100)
    weight: float = Field(gt=0, le=1)


class Policy(Strict):
    id: Id
    title: Text
    account: str = Field(min_length=1, max_length=30)
    goal_id: Id | None = None
    targets: list[Target] = Field(min_length=1, max_length=30)
    basis: Literal["etf_balance"] = "etf_balance"
    denominator: Literal["invested_assets_excluding_cash"] = "invested_assets_excluding_cash"
    buy_only: bool = True
    reserve_cash: Money = 0
    status: Literal["draft", "confirmed", "superseded"] = "draft"
    supersedes: Id | None = None
    evidence: Evidence = Field(default_factory=Evidence)

    @model_validator(mode="after")
    def weights(self):
        if abs(sum(t.weight for t in self.targets) - 1) > 1e-8:
            raise ValueError("목표 비중 합계는 1이어야 합니다")
        if len({(t.market, t.code) for t in self.targets}) != len(self.targets):
            raise ValueError("목표 종목이 중복됩니다")
        return self


class Scenario(Strict):
    id: Id
    title: Text
    assumption: Text
    evidence: list[Text] = Field(default_factory=list, max_length=10)
    condition: str = Field(default="", max_length=1000)
    condition_source: str = Field(default="", max_length=1000)
    condition_state: Literal["unknown", "met", "not_met"] = "unknown"
    action: Literal["observe", "hold", "buy", "reduce", "defer"]
    account: str | None = Field(default=None, max_length=30)
    budget: Money = 0
    policy_id: Id | None = None
    rationale: Text
    invalidation: str = Field(default="", max_length=1000)
    fallback: str = Field(default="", max_length=1000)
    review_on: date | None = None
    # 미래 수익률을 꾸미지 않는다. 사용자가 검토하는 명시적 가격 충격만 계산한다.
    shocks: dict[str, float] = Field(default_factory=dict, max_length=30)

    @model_validator(mode="after")
    def valid_shocks(self):
        if any(v < -1 or v > 10 for v in self.shocks.values()):
            raise ValueError("충격 가정은 -100% 이상 1000% 이하여야 합니다")
        if self.action not in ("buy", "reduce") and self.budget:
            raise ValueError("관찰·유지·대기에는 매매 예산을 넣지 않습니다")
        return self


class Decision(Strict):
    id: Id
    title: Text
    goal_id: Id | None = None
    question: Text
    scenarios: list[Scenario] = Field(default_factory=list, max_length=6)
    selected_id: Id | None = None
    status: Literal["draft", "selected", "discarded"] = "draft"
    open_questions: list[Text] = Field(default_factory=list, max_length=10)
    evidence: Evidence = Field(default_factory=Evidence)

    @model_validator(mode="after")
    def selected(self):
        ids = [s.id for s in self.scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError("시나리오 id가 중복됩니다")
        if self.selected_id is not None and self.selected_id not in ids:
            raise ValueError("선택한 시나리오가 없습니다")
        if self.status == "selected":
            chosen = next((s for s in self.scenarios if s.id == self.selected_id), None)
            if not chosen or self.open_questions:
                raise ValueError("미결 질문을 해결하고 시나리오를 선택해야 합니다")
            if not all((chosen.condition, chosen.condition_source, chosen.invalidation, chosen.fallback, chosen.review_on)):
                raise ValueError("선택한 계획에는 조건·확인 근거·중단 조건·미발생 대응·재검토일이 필요합니다")
            if chosen.action in ("buy", "reduce") and (not chosen.account or chosen.budget <= 0):
                raise ValueError("매매 계획에는 계좌와 예산이 필요합니다")
        return self


class Observation(Strict):
    id: Id
    title: Text
    at: datetime
    purpose: Text
    source: Text
    decision_id: Id | None = None
    status: Literal["pending", "observed", "cancelled"] = "pending"
    finding: str = Field(default="", max_length=1000)
    evidence: Evidence = Field(default_factory=Evidence)


class Strategy(Strict):
    goals: list[Goal] = Field(default_factory=list, max_length=20)
    policies: list[Policy] = Field(default_factory=list, max_length=60)
    decisions: list[Decision] = Field(default_factory=list, max_length=50)
    observations: list[Observation] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def references(self):
        for name in ("goals", "policies", "decisions", "observations"):
            rows = getattr(self, name)
            if len({r.id for r in rows}) != len(rows):
                raise ValueError(f"{name}: id가 중복됩니다")
        goals = {g.id for g in self.goals}
        policies = {p.id: p for p in self.policies}
        for row in [*self.policies, *self.decisions]:
            if row.goal_id and row.goal_id not in goals:
                raise ValueError(f"{row.id}: 연결된 목표가 없습니다")
        active = [p.account for p in self.policies if p.status == "confirmed"]
        if len(active) != len(set(active)):
            raise ValueError("같은 계좌의 확정 운용 원칙은 하나입니다. 이전 원칙을 대체하세요")
        for p in self.policies:
            if p.supersedes and (p.supersedes not in policies or p.supersedes == p.id):
                raise ValueError("대체할 원칙이 없습니다")
        for d in self.decisions:
            for s in d.scenarios:
                if s.policy_id and s.policy_id not in policies:
                    raise ValueError(f"{d.id}: 운용 원칙이 없습니다")
                if s.policy_id and s.account != policies[s.policy_id].account:
                    raise ValueError("시나리오와 운용 원칙의 계좌가 다릅니다")
        for o in self.observations:
            if o.decision_id and o.decision_id not in {d.id for d in self.decisions}:
                raise ValueError("관찰에 연결한 결정이 없습니다")
        return self


def allocate(policy: Policy, rows: list[dict], budget: float, fee_rate: float = 0) -> dict:
    """추가 매수로 부족 비중을 줄이는 결정적 근사. 보유 ETF 평가액이 분모, 현금은 제외.

    연속 금액 해를 이분법으로 구하고 정수 주로 내린 뒤 편차가 줄어드는 한 주를 보정한다.
    각 종목을 최대 한 차례씩만 보정하므로 큰 예산에도 실행 시간이 bounded다.
    """
    if policy.status != "confirmed":
        raise ValueError("확정된 운용 원칙이 필요합니다")
    if not policy.buy_only:
        raise ValueError("매도 허용 원칙은 자동 수량 계산 대상이 아닙니다. 축소 대안을 별도로 검토하세요")
    mine = [r for r in rows if r.get("account") == policy.account]
    cash = [r for r in mine if r["kind"] == "cash"]
    if not cash or any(r.get("value") is None for r in cash):
        raise ValueError("계좌 현금을 확인해야 합니다")
    if any(r.get("currency", "KRW") != "KRW" for r in mine):
        raise ValueError("외화 결제·환전 조건을 먼저 확인해야 합니다")
    available = sum(r["value"] for r in cash) - policy.reserve_cash
    if not math.isfinite(budget) or not math.isfinite(fee_rate) or budget < 0 or budget > available + 1e-6 or not 0 <= fee_rate <= .1:
        raise ValueError("사용 가능 현금 또는 비용 범위를 벗어났습니다")
    targets = {(t.market, t.code): t for t in policy.targets}
    held = [r for r in mine if r["kind"] != "cash"]
    if any((r.get("market"), r.get("code")) not in targets for r in held):
        raise ValueError("목표에 없는 보유 종목이 있습니다. 비중의 분모와 포함 종목을 확인하세요")
    by_key = {}
    for r in held:
        k = r.get("market"), r.get("code")
        if k in by_key:
            raise ValueError("계좌 내 종목 중복을 확인하세요")
        by_key[k] = r
    values, prices, quantities = [], [], []
    for t in policy.targets:
        if t.market != "KR":
            raise ValueError("해외 종목은 결제 통화·환전 조건을 확인한 별도 계산이 필요합니다")
        r = by_key.get((t.market, t.code))
        if r is None or r.get("value") is None or r.get("qty") is None or not r.get("price"):
            raise ValueError(f"{t.name}: 수량과 시세가 필요합니다(신규 종목도 0주 잔고로 확인)")
        if r.get("quote_stale"):
            raise ValueError(f"{t.name}: 오래된 시세를 갱신해야 합니다")
        values.append(r["value"])
        prices.append(r["price"])
        quantities.append(r["qty"])
    invest = budget / (1 + fee_rate)
    low, high = 0., sum(values) + invest
    for _ in range(70):
        middle = (low + high) / 2
        cost = sum(max(0, middle * t.weight - v) for t, v in zip(policy.targets, values))
        if cost > invest:
            high = middle
        else:
            low = middle
    qty = [int(max(0, low * t.weight - v) / p) for t, v, p in zip(policy.targets, values, prices)]
    def distance(q):
        after = [v + n * p for v, n, p in zip(values, q, prices)]
        total = sum(after)
        return sum(abs(v / total - t.weight) for v, t in zip(after, policy.targets)) if total else 2.
    for _ in policy.targets:
        spent = sum(n * p for n, p in zip(qty, prices))
        choices = []
        for i, p in enumerate(prices):
            if spent + p <= invest + 1e-8:
                candidate = qty.copy()
                candidate[i] += 1
                if distance(candidate) < distance(qty) - 1e-12:
                    choices.append((distance(candidate), i))
        if not choices:
            break
        qty[min(choices)[1]] += 1
    spent = sum(n * p for n, p in zip(qty, prices))
    after_total, before_total = sum(values) + spent, sum(values)
    result = [{"code": t.code, "market": t.market, "name": t.name, "qty": n, "price": p,
               "amount": n * p, "target": t.weight, "before_qty": q, "after_qty": q + n,
               "before_weight": v / before_total if before_total else None,
               "after_weight": (v + n * p) / after_total if after_total else None,
               "deviation_pp": ((v + n * p) / after_total - t.weight) * 100 if after_total else None}
              for t, n, p, q, v in zip(policy.targets, qty, prices, quantities, values)]
    return {"account": policy.account, "policy_id": policy.id, "method": "부족 비중 추가 매수 근사",
            "denominator": policy.denominator, "orders": result, "budget": budget,
            "spent": spent, "estimated_cost": spent * fee_rate,
            "remaining_cash": available + policy.reserve_cash - spent * (1 + fee_rate),
            "unspent_budget": budget - spent * (1 + fee_rate),
            "total_absolute_deviation_pp": distance(qty) * 100,
            "max_deviation_pp": max(abs(r["deviation_pp"]) for r in result) if after_total else None,
            "execution_ready": False, "limitations": ["정수 수량 근사안이며 최적해를 보장하지 않습니다",
                "참고 시세 기준. 실제 주문 전 거래 가능 종목·계좌 제한·체결 가격을 확인하세요"]}


def review(strategy: Strategy, rows: list[dict], today: date, execution_log=()) -> dict:
    """선택한 계획들의 동시 재원과 재검토일. 조회 시점마다 다시 계산한다."""
    cash, unknown, reserved = {}, set(), {}
    for r in rows:
        if r["kind"] == "cash":
            a = r.get("account")
            if r.get("value") is None:
                unknown.add(a)
            else:
                cash[a] = cash.get(a, 0) + r["value"]
    reserves = {p.account: p.reserve_cash for p in strategy.policies if p.status == "confirmed"}
    decisions = []
    for d in strategy.decisions:
        issues = []
        records = [r for r in execution_log if r.reference == d.id]
        execution_state = records[-1].status if records else "unexecuted"
        s = next((s for s in d.scenarios if s.id == d.selected_id), None)
        if d.status == "selected" and s:
            if s.review_on and s.review_on <= today:
                issues.append("재검토 시점")
            if s.condition_state == "unknown":
                issues.append("조건 확인 필요")
            if s.policy_id and not any(p.id == s.policy_id and p.status == "confirmed" for p in strategy.policies):
                issues.append("운용 원칙 재검토 필요")
            if s.action == "buy" and execution_state != "confirmed":
                reserved[s.account] = reserved.get(s.account, 0) + s.budget
        scenarios = []
        for option in d.scenarios:
            changes, missing = 0., []
            for code, shock in option.shocks.items():
                affected = [r for r in rows if r.get("code") == code and (not option.account or r.get("account") == option.account)]
                if not affected or any(r.get("value") is None for r in affected):
                    missing.append(code)
                else:
                    changes += sum(r["value"] for r in affected) * shock
            scenarios.append({"id": option.id, "stress_change": None if missing else changes if option.shocks else None,
                              "missing": missing, "label": "명시한 가격 충격에 따른 현재 보유 평가 변화(예측 아님)"})
        decisions.append({"id": d.id, "issues": issues, "scenarios": scenarios, "execution_state": execution_state})
    funding = [{"account": a, "reserved": b, "available": None if a in unknown or a not in cash else cash[a] - reserves.get(a, 0),
                "ok": a in cash and a not in unknown and b <= cash[a] - reserves.get(a, 0) + 1e-6}
               for a, b in reserved.items()]
    for d, item in zip(strategy.decisions, decisions):
        selected = next((s for s in d.scenarios if s.id == d.selected_id), None)
        if d.status == "selected" and selected and any(f["account"] == selected.account and not f["ok"] for f in funding):
            item["issues"].append("동시 계획의 재원 확인 필요")
    return {"decisions": decisions, "funding": funding}
