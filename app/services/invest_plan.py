"""투자 계획 — 문서 형식·검증·평가, 그리고 AI 상담 프롬프트. **DB 도 HTTP 도 모른다.**

계획은 문서 한 덩어리다(`PlanDoc`): 지금 보유 자산 + 이벤트·가지 트리.

    (지금 보유) ─ 이벤트(10/29 FOMC) ─┬─ 가지(인하) → 리밸런싱 뒤 보유
                                      ├─ 가지(동결)
                                      └─ 가지(인상) ─ 이벤트(11/27 금통위) ─ …

- 이벤트의 부모는 없거나(지금에서 바로) 가지다. 가지의 부모는 이벤트다 — 둘이 번갈아 내려간다.
- 가지의 `holdings` 가 비면 부모 상태를 그대로 물려받는다(리밸런싱 없음).
- 결과가 나오면 AI 가 실현된 가지를 `realized`, 나머지를 `dropped` 로 바꾼다.

AI 는 MCP 쓰기 도구로 노드·보유를 고치고, 서버가 그때마다 검증해 새 버전으로 쌓는다(`app/api/plan_ai.py`).
금액은 AI 가 쓰지 않는다 — 수량 × 시세로 여기서 계산한다(`valuate`).
"""

import hashlib
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

AssetClass = Literal["stock", "bond", "cash", "crypto", "other"]
_KST = timezone(timedelta(hours=9))
#: 화면·메일의 자산군 비중 — 주식·채권은 국내/해외로 나눈다(2026-10-11 사용자 요청). 키는 `group()`.
GROUP_LABEL = {"stock_kr": "국내주식", "stock_global": "해외주식", "bond_kr": "국내채권", "bond_global": "해외채권",
               "cash": "현금", "crypto": "코인", "other": "기타"}
AssetType = Literal["cash", "saving", "invest", "pension", "housing"]
TYPE_LABEL = {"cash": "현금성", "saving": "저축성", "invest": "투자성", "pension": "연금성", "housing": "주택"}

_MAX_NODES = 200
_MAX_HOLDINGS = 100
GOLD_CODE = "M04020000"  # 네이버 KRX 금현물, 원/g


class Holding(BaseModel):
    """보유 수량·단위·원통화. 단가는 시세 또는 unit_price, amount는 옛 자료를 읽는 호환 칸이다."""

    kind: AssetClass
    name: str = Field(max_length=100)
    code: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._/-]{1,32}$")
    market: Literal["KR", "US", "COIN"] | None = None
    qty: float | None = Field(default=None, ge=0, allow_inf_nan=False, description="보유 수량 — 원화는 원 수, 외화는 원통화 잔액")
    unit: str | None = Field(default=None, min_length=1, max_length=12, description="수량 단위(주·g·건 등). 현금은 currency")
    unit_price: float | None = Field(default=None, ge=0, allow_inf_nan=False, description="별도 시세가 없는 자산의 단가(currency 기준)")
    amount: float | None = Field(default=None, ge=0, description="옛 입력 평가액(currency 기준). 새 자료는 qty와 unit_price")
    currency: str = Field(default="KRW", pattern=r"^[A-Z]{3}$", description="원통화 ISO 코드. 외화를 원화 환산액으로 저장하지 않는다")
    account: str | None = Field(default=None, max_length=30,
                                description="계좌(ISA·IRP·DC 등) — 같은 종목도 계좌가 다르면 다른 줄. 2026-10-11 에 더했다(옛 문서는 비어 있다)")
    type: AssetType | None = Field(default=None, description="유형(현금성·저축성·투자성·연금성·주택) — 화면 유형별 비중. 2026-10-11")
    region: Literal["KR", "GLOBAL"] | None = Field(default=None,
                                                  description="주식·채권의 투자 대상(상장 시장이 아니다 — 국내 상장 미국 ETF 는 GLOBAL). 비면 market 으로 본다")

    @model_validator(mode="after")
    def _priced_needs_market(self):
        # 시세 환산은 market 으로 고른다(US 면 환율을 곱한다) — 빠지면 100달러가 100원이 됐다(2026-10-14 검토).
        if self.code and self.qty is not None and self.market is None:
            raise ValueError(f"{self.name}: 종목(code+qty)은 market(KR·US·COIN)이 있어야 한다")
        return self


def group(h: Holding) -> str:
    """자산군 비중의 칸 — 주식·채권은 국내/해외로 나눈다. region 이 비면 미국 시장 종목만 해외로 본다."""
    if h.kind not in ("stock", "bond"):
        return h.kind
    region = h.region or ("GLOBAL" if h.market == "US" else "KR")
    return f"{h.kind}_{region.lower()}"


FlowKind = Literal["income", "fixed", "living", "saving"]
FLOW_LABEL = {"income": "수입", "fixed": "고정 지출", "living": "생활비", "saving": "저축·납입"}


class Flow(BaseModel):
    """월 현금흐름 한 줄(2026-10-11). 금액은 한 달 원화. 저축·납입은 `account` 로 어느 계좌에 쌓이는지 적는다."""

    kind: FlowKind
    name: str = Field(max_length=100)
    amount: float = Field(ge=0, description="한 달 금액(원)")
    account: str | None = Field(default=None, max_length=30, description="저축·납입이 쌓이는 계좌(보유의 account 와 같은 이름)")
    note: str = Field(default="", max_length=200)


class Account(BaseModel):
    """계좌 한 줄(2026-10-17) — 보유·납입·부채의 `account` 가 가리키는 대상. 목적·원금·기관·만기를 이름·메모 글이 아니라 칸으로 둔다
    (사용자: "LLM 이 잘 정리할 수 있게 구조적으로"). 월 납입은 여기 두지 않는다 — 현금흐름의 저축·납입 줄(account)이 한 곳이다."""

    name: str = Field(min_length=1, max_length=30, description="계좌 이름 — 보유·현금흐름·부채의 account 와 같은 글자")
    institution: str = Field(default="", max_length=50, description="기관(은행·증권사·회사)")
    type: AssetType | None = Field(default=None, description="유형 — 그 계좌 보유의 type 이 비면 이걸 쓴다")
    purpose: str = Field(default="", max_length=300, description="무슨 돈인가 — 언제 쓰나·어떻게 굴리나")
    principal: float | None = Field(default=None, ge=0, description="넣은 원금(원) — 있으면 원금 대비 손익을 낸다")
    opened: date | None = None
    maturity: date | None = None
    note: str = Field(default="", max_length=300)


class Debt(BaseModel):
    """부채 한 줄(2026-10-17) — 순자산 = 보유 평가 − 부채 잔액. 주거 보증금은 보유에 **전액**, 대출·차입은 여기(사용자 결정 (나))."""

    name: str = Field(min_length=1, max_length=50)
    lender: str = Field(default="", max_length=50)
    balance: float = Field(ge=0, description="남은 원금(원)")
    rate: float | None = Field(default=None, ge=0, le=100, description="연 금리(%) — 모르면 비운다")
    rate_type: Literal["fixed", "variable"] | None = None
    maturity: date | None = Field(default=None, description="만기·다음 연장일")
    account: str | None = Field(default=None, max_length=30, description="담보·연결된 계좌(예: 주거)")
    note: str = Field(default="", max_length=300)


class Link(BaseModel):
    title: str = Field(max_length=100)
    url: str = Field(pattern=r"^https?://\S{1,500}$")


class Execution(BaseModel):
    """실제 잔고 변경으로 확인된 매매 전후 수량. 서버가 채우며 현재 잔고와 별도로 보존한다."""

    before: list[Holding] = Field(max_length=_MAX_HOLDINGS)
    after: list[Holding] = Field(max_length=_MAX_HOLDINGS)


class Node(BaseModel):
    """이벤트·가지 공용. 이벤트 전용 칸(`at`·`about`·`expect`·`links`)과 가지 전용 칸(`condition`·`actions`·`holdings`)이 섞여 있다.

    `about`·`expect`·`links`·`condition` 은 2026-10-10 에 더했다 — 기본값이 있어 옛 버전 문서도 그대로 읽힌다.
    """

    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")
    parent: str | None = None
    kind: Literal["event", "branch"]
    title: str = Field(max_length=100)
    at: datetime | None = Field(default=None, description="이벤트 시작 시각(KST) — 이때 메일이 간다")
    about: str = Field(default="", max_length=2000, description="이벤트 개요 — 주관·무엇을 정하나·왜 중요한가")
    expect: str = Field(default="", max_length=2000, description="이벤트 시장 예상 — 컨센서스·확률·현재 수준")
    links: list[Link] = Field(default_factory=list, max_length=5, description="이벤트 참고 출처")
    condition: str = Field(default="", max_length=300, description="가지를 타는 조건")
    note: str = Field(default="", max_length=2000)
    actions: list[str] = Field(default_factory=list, max_length=20)
    holdings: list[Holding] | None = Field(default=None, max_length=_MAX_HOLDINGS)
    status: Literal["pending", "realized", "dropped"] = "pending"
    executed_at: date | None = Field(default=None, description="가지의 매매를 실제로 한 날(화면 [실행함]) — 2026-10-11")
    base: str | None = Field(default=None, description="가지 보유를 쓸 때의 직전 보유 지문 — 서버가 채운다(`stamp_branches`). 2026-10-14")
    basis: list[Holding] | None = Field(default=None, max_length=_MAX_HOLDINGS, description="계획 작성 당시 기준 보유 — 서버 전용")
    execution: Execution | None = Field(default=None, description="잔고로 확인한 실제 매매 전후 — 서버 전용")


#: 원칙·기억 한 줄 — 앞뒤 공백을 떼고, 빈 줄은 받지 않는다.
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
MAX_RULES, MAX_MEMORY = 30, 50


class PlanDoc(BaseModel):
    as_of: date | None = Field(default=None, description="보유 자산 기준일")
    holdings: list[Holding] = Field(default_factory=list, max_length=_MAX_HOLDINGS)
    nodes: list[Node] = Field(default_factory=list, max_length=_MAX_NODES)
    cashflow: list[Flow] = Field(default_factory=list, max_length=50, description="월 현금흐름 — 2026-10-11 에 더했다(옛 문서는 빈 목록)")
    # 2026-10-14 — 상담·매일 점검 프롬프트에 늘 싣는다. 화면 [원칙·기억] 목록과 상담(rules_set·memory_set) 두 길로 고친다.
    rules: list[Note] = Field(default_factory=list, max_length=MAX_RULES, description="원칙 — AI 가 늘 지킬 규칙")
    memory: list[Note] = Field(default_factory=list, max_length=MAX_MEMORY, description="기억 — 상담에 늘 깔고 갈 사실")
    accounts: list[Account] = Field(default_factory=list, max_length=30, description="계좌 목록 — 2026-10-17(옛 문서는 빈 목록)")
    debts: list[Debt] = Field(default_factory=list, max_length=20, description="부채 — 2026-10-17(옛 문서는 빈 목록)")

    @model_validator(mode="after")
    def _accounts(self):
        """계좌 목록이 있으면 보유(가지 포함)·납입·부채의 account 는 그 이름이어야 한다 — 같은 계좌를 다르게 적어 따로 묶이지 않게.
        목록이 비면(옛 문서) 보지 않는다."""
        if not self.accounts:
            return self
        names = [a.name for a in self.accounts]
        if len(set(names)) != len(names):
            raise ValueError("계좌 이름이 겹친다")
        where = [(f"보유 {h.name}", h.account) for h in self.holdings]
        where += [(f"{n.id} 보유 {h.name}", h.account) for n in self.nodes for h in n.holdings or []]
        where += [(f"납입 {f.name}", f.account) for f in self.cashflow if f.kind == "saving"]
        where += [(f"부채 {d.name}", d.account) for d in self.debts if d.account]
        bad = sorted({f"{w}({a or '계좌 없음'})" for w, a in where if a not in names})
        if bad:
            raise ValueError(f"계좌 목록(accounts)에 없는 계좌: {', '.join(bad[:8])} — 계좌 목록 이름을 그대로 쓴다")
        return self

    @model_validator(mode="after")
    def _tree(self):
        by_id: dict[str, Node] = {}
        for n in self.nodes:
            if n.id in by_id:
                raise ValueError(f"노드 id 가 겹친다: {n.id}")
            by_id[n.id] = n
        for n in self.nodes:
            p = by_id.get(n.parent) if n.parent else None
            if n.parent and p is None:
                raise ValueError(f"{n.id}: 부모 {n.parent} 가 없다")
            if n.kind == "event":
                if p is not None and p.kind != "branch":
                    raise ValueError(f"{n.id}: 이벤트의 부모는 가지여야 한다")
                if n.at is None:
                    raise ValueError(f"{n.id}: 이벤트에는 at(시작 시각)이 있어야 한다")
            elif p is None or p.kind != "event":
                raise ValueError(f"{n.id}: 가지의 부모는 이벤트여야 한다")
            if n.kind == "event" and sum(1 for b in self.nodes
                                         if b.parent == n.id and b.kind == "branch" and b.status == "realized") > 1:
                raise ValueError(f"{n.id}: 실현된 가지는 하나여야 한다")
            # 부모를 따라 올라가 순환을 막는다 — 노드 수보다 깊으면 돌고 있는 것이다.
            cur, hops = n, 0
            while cur.parent:
                cur, hops = by_id[cur.parent], hops + 1
                if hops > len(self.nodes):
                    raise ValueError(f"{n.id}: 부모를 따라가면 순환한다")
        # 화면의 날짜축이 거꾸로 서지 않게 — 다음 이벤트는 앞 이벤트(가지의 부모)보다 늦어야 한다.
        for n in self.nodes:
            if n.kind == "event" and n.parent:
                prev = by_id[by_id[n.parent].parent]
                if _kst(n.at) <= _kst(prev.at):
                    raise ValueError(f"{n.id}: 이벤트 시각이 앞 이벤트 {prev.id} 보다 늦어야 한다")
        return self


def _kst(dt: datetime) -> datetime:
    """시각대가 없으면 KST 로 본다(프롬프트가 +09:00 으로 쓰라고 하지만 빠뜨릴 수 있다)."""
    return dt.replace(tzinfo=_KST) if dt.tzinfo is None else dt


def empty_doc() -> PlanDoc:
    return PlanDoc()


# ---------------------------------------------------------------------------
# 평가 — 수량 × 시세. 시세는 부르는 쪽이 넘긴다(`price_pairs` 로 무엇이 필요한지 알려 준다).
# ---------------------------------------------------------------------------

def _all_holdings(doc: PlanDoc):
    yield from doc.holdings
    for n in doc.nodes:
        yield from n.holdings or []


def canonical(h: Holding) -> Holding:
    """옛 금액 자료를 읽는 어댑터. 명시된 잔액만 수량으로 옮기며 주식 수·외화 잔액을 역산하지 않는다."""
    h = h.model_copy(deep=True)
    if (grams := gold_grams(h)) is not None:
        h.code, h.market, h.qty, h.unit = GOLD_CODE, "KR", grams, "g"
    elif h.kind == "cash":
        unknown_fx = h.currency == "KRW" and re.search(r"원화\s*환산", h.name) and any(s in h.name for s in ("외화", "외환"))
        if unknown_fx and h.qty is None:
            h.unit = "미확인"
            return h
        if h.qty is None:
            h.qty = h.amount
        h.unit, h.unit_price = h.currency, 1.0
    elif h.kind in ("stock", "bond", "crypto") and (h.code or h.kind in ("stock", "crypto")):
        h.unit = h.unit or ("개" if h.market == "COIN" else "주")
    elif h.qty is None and h.amount is not None:
        h.qty, h.unit_price = 1.0, h.amount
        h.unit = h.unit or ("건" if h.type == "housing" else "개")
    if h.qty is not None and h.unit_price is None and h.amount is not None and h.qty > 0:
        h.unit_price = h.amount / h.qty
    if h.qty is not None and h.unit is None:
        h.unit = "건" if h.type == "housing" else "개"
    return h


def as_quantity(h: Holding) -> Holding:
    h = canonical(h)
    if h.qty is not None:
        h.amount = None
    return h


def fx_rate(rates: float | dict | None, currency: str) -> float | None:
    if currency == "KRW":
        return 1.0
    rate = rates.get(currency) if isinstance(rates, dict) else rates if currency == "USD" else None
    return rate if rate is not None and math.isfinite(rate) and rate > 0 else None


def currencies(doc: PlanDoc) -> list[str]:
    return sorted({h.currency for h in _all_holdings(doc) if h.currency != "KRW"}
                  | {"USD"})  # 기존 미국 종목·상담 환율도 함께 유지


def quantity_doc(doc: PlanDoc) -> PlanDoc:
    """API·상담에 보여 주는 통일된 수량 형식. 원본 버전은 수정하지 않는다."""
    result = doc.model_copy(deep=True)
    account_types = {a.name: a.type for a in doc.accounts}
    def convert(holdings):
        rows = [as_quantity(h) for h in holdings]
        for original, h in zip(holdings, rows):
            if original.unit is None and (h.type or account_types.get(h.account)) == "housing":
                h.unit = "건"
        return rows
    result.holdings = convert(result.holdings)
    for n in result.nodes:
        if n.holdings is not None:
            n.holdings = convert(n.holdings)
        if n.basis is not None:
            n.basis = convert(n.basis)
        if n.execution:
            n.execution.before, n.execution.after = convert(n.execution.before), convert(n.execution.after)
    return result


def gold_grams(h: Holding) -> float | None:
    """명시된 KRX 금현물 g 수량. 옛 이름의 g도 읽되 문서에 저장하거나 평가액에서 역산하지 않는다."""
    if h.kind != "other" or h.currency != "KRW" or h.market not in (None, "KR"):
        return None
    if h.code == GOLD_CODE and h.qty is not None:
        return h.qty if math.isfinite(h.qty) else None
    if h.code is not None:
        return None
    match = re.fullmatch(r"KRX\s*금현물\s+(\d+(?:\.\d+)?)\s*g(?:\s*\([^)]*\))?", h.name.strip(), re.IGNORECASE)
    return float(match[1]) if match else None


def price_pairs(doc: PlanDoc) -> tuple[list[str], list[str]]:
    """시세가 필요한 (주식 코드, 코인 코드). 둘을 나누는 이유는 `_latest_quotes` 가 코드로 사전을 만들어서다."""
    stocks, coins = set(), set()
    for h in _all_holdings(doc):
        if gold_grams(h) is not None:
            stocks.add(GOLD_CODE)
        elif h.code and h.code != GOLD_CODE and h.qty is not None:
            (coins if h.market == "COIN" else stocks).add(h.code)
    return sorted(stocks), sorted(coins)


def _value(h: Holding, stock_px: dict, coin_px: dict, usdkrw: float | dict | None) -> tuple[float | None, float | None]:
    """(원화 평가액, 쓴 시세). 값을 낼 수 없으면 평가액이 None — 0 으로 두면 "없음"과 "0원"이 섞인다."""
    h = canonical(h)
    if h.qty == 0:
        return 0.0, (coin_px if h.market == "COIN" else stock_px).get(h.code)
    grams = gold_grams(h)
    if grams is not None and (px := stock_px.get(GOLD_CODE)) is not None:
        return grams * px, px
    if h.code and h.code != GOLD_CODE and h.qty is not None:
        px = (coin_px if h.market == "COIN" else stock_px).get(h.code)
        if px is not None:
            rate = fx_rate(usdkrw, "USD" if h.market == "US" else "KRW")
            return (None if rate is None else h.qty * px * rate), px
    rate = fx_rate(usdkrw, h.currency)
    if h.qty is not None and h.unit_price is not None and rate is not None:
        return h.qty * h.unit_price * rate, None
    if h.amount is not None and rate is not None:
        return h.amount * rate, None
    return None, None


def states(doc: PlanDoc) -> dict[str, list[Holding]]:
    """노드마다 그 시점의 보유. 키 `root` 는 지금. 이벤트는 직전 상태(부모)를 그대로 보인다."""
    by_id = {n.id: n for n in doc.nodes}
    out: dict[str, list[Holding]] = {"root": doc.holdings}

    def of(nid: str | None) -> list[Holding]:
        if nid is None:
            return doc.holdings
        if nid not in out:
            n = by_id[nid]
            parent = by_id.get(n.parent)
            out[nid] = (doc.holdings if n.kind == "event" and parent and parent.execution else
                        n.execution.after if n.execution else n.holdings if n.holdings is not None else of(n.parent))
        return out[nid]

    for n in doc.nodes:
        of(n.id)
    return out


def valuate(doc: PlanDoc, stock_px: dict, coin_px: dict, usdkrw: float | dict | None) -> dict[str, dict]:
    """`{노드 id | "root": {total, rows: [보유 + value·price]}}`. 미래 노드도 **오늘 시세**로 환산한다."""
    out, acc_type = {}, {a.name: a.type for a in doc.accounts}
    debt = sum(d.balance for d in doc.debts)
    for key, hs in states(doc).items():
        rows, total = [], 0.0
        for h in hs:
            v, px = _value(h, stock_px, coin_px, usdkrw)
            c = canonical(h)
            if h.unit is None and (h.type or acc_type.get(h.account)) == "housing":
                c.unit = "건"
            row = {**c.model_dump(), "type": h.type or acc_type.get(h.account), "group": group(h), "value": v, "price": px,
                   "quantity_unit": c.unit or "개", "quantity_missing": c.qty is None,
                   "unit_value_krw": _value(c.model_copy(update={"qty": 1.0, "amount": None}), stock_px, coin_px, usdkrw)[0]
                   if c.qty is not None else None}
            rows.append(row)
            total += v or 0.0
        # net = 순자산(보유 − 부채). 부채는 계획 전체에 하나라 가지마다 같은 값을 뺀다(가지는 대출을 바꾸지 않는다).
        out[key] = {"total": total, "net": total - debt, "rows": rows}
    return out


def account_view(doc: PlanDoc, values: dict[str, dict]) -> list[dict]:
    """계좌 표(2026-10-17) — 계좌마다 지금 평가·원금 대비 손익·월 납입(현금흐름 저축 줄)·부채. 계좌 목록이 비면 빈 목록."""
    rows = values["root"]["rows"]
    out = []
    for a in doc.accounts:
        mine = [r for r in rows if r.get("account") == a.name]
        value = None if any(r["value"] is None for r in mine) else sum(r["value"] for r in mine)
        pnl = value - a.principal if value is not None and a.principal else None
        out.append({**a.model_dump(mode="json"), "value": value, "pnl": pnl,
                    "pnl_pct": pnl / a.principal * 100 if pnl is not None else None,
                    "monthly": sum(f.amount for f in doc.cashflow if f.kind == "saving" and f.account == a.name) or None,
                    "debt": sum(d.balance for d in doc.debts if d.account == a.name) or None})
    return out


def _by_key(rows: list[dict]) -> dict[tuple, dict]:
    """평가 줄을 (계좌, 코드|이름) 으로 합친다 — 수량은 수량이 있는 줄만, 평가액은 하나라도 없으면 None."""
    out: dict[tuple, dict] = {}
    for r in rows:
        k = (r.get("account") or "", r.get("market"), r.get("code") or r["name"], r.get("currency"))
        hit = out.setdefault(k, {**r, "qty": None, "value": 0.0})
        if r.get("qty") is not None:
            hit["qty"] = (hit["qty"] or 0.0) + r["qty"]
        hit["value"] = None if hit["value"] is None or r["value"] is None else hit["value"] + r["value"]
    return out


# ---------------------------------------------------------------------------
# 가지 보유의 재원·기준 (2026-10-14 반론자 검토)
#
# 가지 보유는 "실행 뒤 전체 보유"라 AI 가 현금보다 많이 사도, 잔고가 나중에 바뀌어도 형식 검사로는 안 걸렸다.
#   - 재원: 계좌마다 실행 뒤 평가액 ≤ 실행 전 × (1 + FUND_SLACK). 계좌 사이 이동은 하지 않는다는 규칙을 서버가 지킨다.
#   - 기준: 가지 보유를 쓸 때 직전 보유의 지문을 `base` 에 남기고, 나중에 직전 보유가 달라지면 "다시 짜야 함"(stale).
# ---------------------------------------------------------------------------

#: 시세 오차·수수료 여유. 이보다 크게 늘면 판 것보다 많이 산 것이다.
FUND_SLACK = 0.02


def holdings_stamp(hs: list[Holding]) -> str:
    """보유 목록의 지문 — 줄 순서는 따지지 않는다."""
    def fields(h):
        data = h.model_dump(mode="json")
        # 새 선택 칸이 없는 옛 자료의 지문은 기존과 같아야 버전에서 기준 잔고를 찾을 수 있다.
        for name in ("unit", "unit_price"):
            if data[name] is None:
                data.pop(name)
        return data
    rows = sorted(json.dumps(fields(h), sort_keys=True, ensure_ascii=False) for h in hs)
    return hashlib.sha1("\n".join(rows).encode()).hexdigest()[:16]


def changed_branches(old: PlanDoc, new: PlanDoc) -> list[Node]:
    """보유를 새로 쓰거나 바꾼(또는 부모를 옮긴) 가지."""
    olds = {n.id: n for n in old.nodes}
    return [n for n in new.nodes if n.kind == "branch" and n.holdings is not None
            and (n.id not in olds or olds[n.id].holdings != n.holdings or olds[n.id].parent != n.parent)]


def stamp_branches(old: PlanDoc, new: PlanDoc) -> None:
    """가지의 `base` 는 서버만 쓴다 — 바뀐 가지는 지금의 직전 보유 지문으로, 나머지는 옛 값 그대로(AI 가 보낸 값은 버린다)."""
    olds = {n.id: n for n in old.nodes}
    st = states(new)
    fresh = {n.id for n in changed_branches(old, new)}
    for n in new.nodes:
        if n.kind != "branch":
            continue
        n.base = holdings_stamp(st[n.parent]) if n.id in fresh else (olds[n.id].base if n.id in olds else None)
        n.basis = ([h.model_copy(deep=True) for h in st[n.parent]] if n.id in fresh
                   else olds[n.id].basis if n.id in olds else None)


def stale_branches(doc: PlanDoc) -> set[str]:
    """직전 보유가 가지를 짤 때와 달라진 가지 — 매매표가 엉뚱한 매도·매수를 낼 수 있다. 지문이 없는 옛 가지는 모른다(빼지 않는다)."""
    st = states(doc)
    return {n.id for n in doc.nodes
            if n.kind == "branch" and not n.execution and n.holdings is not None and n.base
            and n.base != holdings_stamp(st[n.parent])}


def _account_totals(rows: list[dict]) -> dict[str, float | None]:
    """계좌 → 평가액 합. 그 계좌에 값을 못 낸 줄이 있으면 None(검사하지 않는다)."""
    out: dict[str, float | None] = {}
    for r in rows:
        k = r.get("account") or ""
        out[k] = None if r["value"] is None or out.get(k, 0.0) is None else out.get(k, 0.0) + r["value"]
    return out


def funding_errors(old: PlanDoc, new: PlanDoc, values: dict[str, dict]) -> list[str]:
    """바뀐 가지마다 계좌별로 판 것보다 많이 샀는지. 옛 가지는 시세가 움직여 걸릴 수 있어 보지 않는다."""
    errs = []
    for n in changed_branches(old, new):
        if n.execution:
            continue
        before, after = _account_totals(values[n.parent]["rows"]), _account_totals(values[n.id]["rows"])
        for acc, a in after.items():
            b = before.get(acc, 0.0)
            if a is None or b is None or a <= b * (1 + FUND_SLACK) + 1:
                continue
            errs.append(f"{n.title}: 계좌 {acc or '(계좌 없음)'} 실행 뒤 {a:,.0f}원 > 실행 전 {b:,.0f}원 — "
                        "그 계좌에서 판 돈과 현금으로만 살 수 있다(산 만큼 현금을 줄이고, 계좌 사이 이동은 하지 않는다)")
    return errs


def trades(doc: PlanDoc, values: dict[str, dict]) -> dict[str, list[dict]]:
    """가지 id → 매매표(2026-10-11) — 직전(부모 이벤트 시점) 보유와 가지의 실행 뒤 보유를 견준다. 가지 보유가 null 이면 매매가 없다.

    한 줄 = `{account, name, code, kind, side: buy|sell, qty|None, value|None}`. 수량 종목은 수량 차이 × 오늘 단가,
    평가액으로 적은 것(현금·예금 등)은 금액 차이. 계좌가 나온 순서로, 계좌 안에서는 매도 → 매수 → 현금 순이다(팔아야 살 돈이 생긴다).
    """
    out = {}
    def confirmed_rows(holdings):
        rows = []
        for h in holdings:
            c = canonical(h)
            rows.append({**c.model_dump(), "quantity_unit": c.unit or "개", "price": None,
                         "value": c.qty if c.kind == "cash" and c.currency == "KRW" else None})
        return rows
    for n in doc.nodes:
        if n.kind != "branch" or n.holdings is None:
            continue
        before = _by_key(confirmed_rows(n.execution.before) if n.execution else values[n.parent]["rows"])
        after = _by_key(confirmed_rows(n.execution.after) if n.execution else values[n.id]["rows"])
        lines = []
        for k in list(before) + [k for k in after if k not in before]:
            b, a = before.get(k), after.get(k)
            ref = a or b
            if all(x is None or x["qty"] is not None for x in (b, a)):
                d = (a["qty"] if a else 0.0) - (b["qty"] if b else 0.0)
                if abs(d) < 1e-9:
                    continue
                # 단가 — 시세가 잡힌 줄을 먼저, 없으면 직전 줄. 시세 없는 종목은 평가액으로 떨어지는데 가지에서 수량만 바꾸고
                # 평가액을 그대로 두면 실행 뒤 줄의 단가가 틀린다(KODEX 미국30년 400→600주에 평가액 그대로).
                src = next((x for x in (a, b) if x and x.get("price") is not None and x["value"] is not None and x["qty"]), None) \
                    or next((x for x in (b, a) if x and x["value"] is not None and x["qty"]), None)
                unit = src["value"] / src["qty"] if src else None
                qty, value = abs(d), (abs(d) * unit if unit is not None else None)
            else:
                if any(x is not None and x["value"] is None for x in (b, a)):
                    continue
                d = (a["value"] if a else 0.0) - (b["value"] if b else 0.0)
                if abs(d) < 1:
                    continue
                qty, value = None, abs(d)
            lines.append({"account": k[0] or None, "name": ref["name"], "code": ref.get("code"), "kind": ref["kind"],
                          "side": "buy" if d > 0 else "sell", "qty": qty, "value": value,
                          "quantity_unit": ref.get("quantity_unit") or ref.get("unit") or "개", "confirmed": bool(n.execution)})
        accounts = list(dict.fromkeys(x["account"] for x in lines))
        lines.sort(key=lambda x: (accounts.index(x["account"]), x["kind"] == "cash", x["side"] == "buy"))
        out[n.id] = lines
    return out


# ---------------------------------------------------------------------------
# 현금흐름 — 월 합계와 이벤트까지의 예상 적립(2026-10-11). 보유 평가에는 섞지 않는다(가지 보유는 "실행 뒤 전체 보유"라서).
# ---------------------------------------------------------------------------

def cashflow_summary(doc: PlanDoc) -> dict | None:
    """`{income, fixed, living, saving, surplus}` — 여유 = 수입 − 지출 − 저축·납입. 현금흐름이 비면 None."""
    if not doc.cashflow:
        return None
    sums = {k: sum(f.amount for f in doc.cashflow if f.kind == k) for k in FLOW_LABEL}
    return {**sums, "surplus": sums["income"] - sums["fixed"] - sums["living"] - sums["saving"]}


def months_between(start: date, end: date) -> int:
    """지나는 달 수(월급일은 따지지 않는다) — 10-11 → 12-10 은 1, 12-11 은 2."""
    return max(0, (end.year - start.year) * 12 + end.month - start.month - (end.day < start.day))


def accruals(doc: PlanDoc, today: date) -> dict[str, dict]:
    """이벤트·가지 id → `{months, total, by_account}` — 기준일부터 그 이벤트까지 저축·납입이 쌓이는 양. 가지는 자기 이벤트 날짜.

    기준일은 보유 기준일(`as_of`), 없으면 오늘. 한 달도 안 지나는 노드와 저축·납입이 없는 문서는 뺀다.
    """
    saving = [f for f in doc.cashflow if f.kind == "saving"]
    if not saving:
        return {}
    start, by_id, out = doc.as_of or today, {n.id: n for n in doc.nodes}, {}
    for n in doc.nodes:
        ev = n if n.kind == "event" else by_id.get(n.parent)
        m = months_between(start, _kst(ev.at).date()) if ev and ev.at else 0
        if m <= 0:
            continue
        by_acc: dict[str, float] = {}
        for f in saving:
            by_acc[f.account or ""] = by_acc.get(f.account or "", 0.0) + f.amount * m
        out[n.id] = {"months": m, "total": sum(by_acc.values()), "by_account": by_acc}
    return out


# ---------------------------------------------------------------------------
# 복기 — 날짜가 지난 이벤트의 가지마다 "그때(이벤트 시각 시세) → 지금(오늘 시세)" 평가(2026-10-10 사용자 요청)
# ---------------------------------------------------------------------------

def on_dropped_path(doc: PlanDoc, node: Node) -> bool:
    """조상 가지(자신이 가지면 자신도) 중 접힌(dropped) 것이 있으면 True — 그 경로는 더 오지 않는다.
    시작 메일·지금 할 일에서 뺀다(접힌 가지 아래 이벤트에도 메일이 갔다, 2026-10-14 검토)."""
    by_id = {n.id: n for n in doc.nodes}
    cur = node
    while cur is not None:
        if cur.kind == "branch" and cur.status == "dropped":
            return True
        cur = by_id.get(cur.parent) if cur.parent else None
    return False


def past_events(doc: PlanDoc, now: datetime) -> list[Node]:
    return [n for n in doc.nodes if n.kind == "event" and _kst(n.at) <= now]


def retrospect(doc: PlanDoc, now_values: dict, then_values: dict[str, dict]) -> dict[str, dict]:
    """`then_values` 는 지난 이벤트 id → 그 이벤트 시각의 시세로 낸 `valuate` 결과.

    가지마다 {event, at, then, now, change, pct, missing}. 가지의 보유는 **계획상 수량**이라 실제 체결과 다를 수 있다.
    `missing` 은 그때 시세가 없어 평가에서 빠진 보유 수(상장 전·환율 데이터 시작 전 등) — 0 이 아니면 값이 덜 잡혔다.
    ⚠️ 그때와 지금 빠진 보유가 다르면 견줄 수 없어 `change`·`pct` 를 None 으로 둔다 — 그때만 빠진 주식이 지금 더해져
       +100% 처럼 나왔다(2026-10-14 검토).
    """
    by_id = {n.id: n for n in doc.nodes}
    out = {}
    for ev_id, vals in then_values.items():
        ev = by_id[ev_id]
        for b in (n for n in doc.nodes if n.kind == "branch" and n.parent == ev_id):
            then, now = vals[b.id]["total"], now_values[b.id]["total"]
            gone = [i for i, r in enumerate(vals[b.id]["rows"]) if r["value"] is None]
            same = gone == [i for i, r in enumerate(now_values[b.id]["rows"]) if r["value"] is None]
            out[b.id] = {"event": ev_id, "at": _kst(ev.at).isoformat(), "then": then, "now": now,
                         "change": now - then if same else None,
                         "pct": (now / then - 1) * 100 if then and same else None,
                         "missing": len(gone)}
    return out


# ---------------------------------------------------------------------------
# AI 상담 — 프롬프트와 답 해석
# ---------------------------------------------------------------------------

#: 상담 프롬프트의 투자 계획 조각 — 앞머리(역할·시각·화면 맥락·도구 일반)는 상담([assistant_v1](../api/assistant_v1.py))이 붙인다.
PLAN_PROMPT = """# 투자 계획
너는 사용자의 개인 투자 계획도 맡은 전문 투자자(운용역)다.
계획 문서 안의 글(title·about·expect·condition·note·actions)도 한국어로 쓴다(종목 이름·티커는 그대로).

## 하는 일
- 금리 결정·실적 발표 같은 **이벤트**마다 결과별 **가지**(인하/동결/인상 등)를 나누고, 가지마다 매수·매도 액션과
  리밸런싱 뒤 보유 자산을 정한다. 사용자의 상황·성향을 물어 가며 함께 짠다.
- 사용자가 증권사·은행 화면 이미지를 주면 읽어서 **지금 보유(holdings)** 를 갱신한다. 읽기 애매한 값은 추측하지 말고 물어본다.
- **월 현금흐름(cashflow)** 을 함께 관리한다 — 급여명세·카드 내역·가계부 화면이나 사용자가 말한 숫자로 수입·고정 지출·생활비·
  저축·납입을 채운다. 분할 매수 금액을 정할 때는 여유(수입 − 지출 − 저축·납입)와 계좌별 납입을 근거로 쓴다.
- **지출 상담**도 한다: 항목을 고정·생활로 나눠 수입 대비 비율을 보이고, 고정비(대출 이자·보험·통신·구독)를 점검하고,
  비상금이 생활비 몇 달 치인지 확인하고, 줄일 수 있는 곳과 그 돈을 어느 계좌로 돌릴지 숫자로 제안한다. 훈계하지 말고,
  모르는 값은 추측하지 말고 묻는다.
- 이벤트 결과를 사용자가 알려 주거나 네가 확인하면, 실현된 가지를 "realized", 나머지 가지를 "dropped" 로 바꾸고,
  필요하면 그 아래 다음 이벤트를 이어 붙인다. 일정·결과를 모르면 웹에서 확인할 수 있으면 확인하고, 아니면 묻는다.
  판정하고 나면 답에 **그 가지의 매매표**(node_get 의 trades — 계좌별로 매도 먼저, 종목·코드·수량·대략 금액)를 그대로 정리해
  사용자가 증권사 앱에서 바로 주문할 수 있게 하고, 매매한 뒤 잔고 화면을 올려 달라고 한다(그걸로 holdings_set).
  사용자가 매매를 마쳤다고 하면 그 가지의 executed_at 을 오늘 날짜로 node_update 한다.
- **가지는 바로 주문할 수 있게** 만든다 — 매매가 있는 가지는 holdings(실행 뒤 전체 보유)를 반드시 채운다(서버가 직전 보유와
  견줘 매매표를 만든다). actions 는 "ISA · KODEX 미국30년국채액티브(H) 484790 · 200주 매수(약 160만 원)" 처럼
  계좌·종목·코드·수량(또는 금액)을 적고, "일부"·"적당히" 같은 말은 쓰지 않는다. 수량은 quotes_get 의 종가와 그 계좌의 현금으로 정하고,
  산 만큼 그 계좌 현금을 줄인다(계좌 사이 이동은 하지 않는다). 서버가 계좌마다 실행 뒤 평가액이 실행 전보다 2% 넘게 크면
  "재원 초과"로 거절한다 — 그러면 수량을 줄여 다시 쓴다. 주문은 서버 매매표(trades)가 정하고 actions 는 메모로 보인다.
- plan_get 의 `stale` 은 잔고가 바뀌어 매매표가 틀어진 가지다 — 상담 때 보이면 그 가지의 holdings 를 지금 보유 기준으로
  다시 짜자고 제안한다(시키면 node_update).

## 계획 도구(MCP `blog`)
- 조회: node_get(노드 하나의 모든 칸과 그 시점 평가·복기), plan_get(지금 계획 전체와 노드별 평가 — 오늘 시세 원화 환산·환율, 그리고 retro: 지난 이벤트의 가지마다
  그때(이벤트 시각 시세)→지금 평가와 변화 — "지난 대응이 어땠나"는 이걸로 답한다), plan_revisions / plan_revision_get(버전 이력과 그때의 보유),
  quotes_get(종목 최신 종가·등락률·원/달러 환율), stock_search(이름으로 종목 코드 찾기).
- 쓰기: node_add(노드 하나 추가), node_update(노드 칸 고치기 — 바꿀 칸만), node_delete(노드와 그 아래 삭제),
  holdings_set(지금 보유 통째로), cashflow_set(월 현금흐름 통째로), accounts_set(계좌 목록 통째로), debts_set(부채 통째로),
  rules_set(원칙 통째로), memory_set(기억 통째로).
  **계획을 바꾸는 길은 이 도구뿐이다.** 쓸 때마다 서버가 검증해 새 버전으로 저장한다.
  거부되면 돌려준 이유를 보고 고쳐 다시 부른다. 사용자가 바꾸라고 하지 않았으면 쓰지 않는다.
- 여러 노드를 만들 때는 부모부터(이벤트 → 그 가지 → 다음 이벤트) 차례로 node_add 한다.

## 원칙·기억
- **원칙**은 사용자가 정한 행동 규칙이다. 가지·액션·권유는 원칙을 어기지 않는다. 사용자가 원칙에 어긋나는 걸 시키면
  그 원칙을 들어 한 번 묻고, 그래도 하라면 따르며 원칙을 고칠지도 묻는다.
- **기억**은 사용자에 대한 사실·상황·선호다(만기·상여 시기·답 형식 등). 답과 계획에 반영한다.
- rules_set·memory_set 은 사용자가 "기억해·원칙으로 해·잊어·빼"처럼 **시킨 상담에서만 열린다**(서버가 막는다). 그때만 — 지금 목록에 더하거나 빼서
  통째로 보낸다(다른 줄은 그대로). 대화에서 남길 만한 게 보이면 "원칙(기억)으로 남길까요?" 하고 묻기만 한다.
- **이번 상담: {gate}**
- 한 줄에 하나, 짧게(300자 이내, 원칙 최대 30줄·기억 50줄). 기억의 날짜는 "2027-03"처럼 절대 날짜로 쓴다("내년" 금지).
  하지 말 것·해야 할 것은 원칙, 사실·상황·선호는 기억이다. 사용자는 화면 목록에서도 직접 고친다.

{notes}

## 계획 문서 형식(JSON)
{{"as_of": "YYYY-MM-DD"(보유 기준일), "accounts": [계좌], "holdings": [보유], "debts": [부채], "nodes": [노드], "cashflow": [현금흐름]}}
- **사실은 칸에 적는다** — 계좌의 기관·목적·원금·만기, 대출의 잔액·금리·만기를 이름(name)이나 메모(note) 글에 숨기지 않는다.
  모르는 칸은 비우고(추측 금지) 사용자에게 묻는다. 그래야 서버가 원금 대비 손익·순자산을 계산하고 다음 상담이 그대로 읽는다.
- 계좌: {{"name": 이름, "institution": 기관, "type": "cash|saving|invest|pension|housing", "purpose": 무슨 돈인가(언제 쓰나·어떻게 굴리나),
  "principal": 넣은 원금(원)|null, "opened": "YYYY-MM-DD"|null, "maturity": "YYYY-MM-DD"|null, "note": 메모}}
  - 통장·증권 계좌 하나가 한 줄이다(예: "신한 주계좌", "NH1934 파킹", "ISA", "IRP", "DC", "금현물", "주거"). 여러 통장을 한 줄로 합치지 않는다.
  - 목록이 있으면 보유·가지 보유·저축 납입·부채의 account 는 **이 목록의 name 그대로**여야 저장된다(서버가 거절한다).
    계좌를 새로 만들면 accounts_set 을 먼저, 그다음 보유를 고친다. 이름을 바꿀 땐 새 이름을 더한 목록 → 보유(가지 포함)를 새 이름으로 →
    옛 이름을 뺀 목록 순서로 쓴다(옛 이름을 쓰는 보유가 남아 있으면 거절된다).
  - 월 납입은 계좌가 아니라 현금흐름의 saving 줄(account)에 적는다.
- 부채: {{"name": 이름, "lender": 빌린 곳, "balance": 남은 원금(원), "rate": 연 %|null, "rate_type": "fixed|variable"|null,
  "maturity": 만기·다음 연장일 "YYYY-MM-DD"|null, "account": 연결된 계좌(예: 주거)|null, "note": 상환 방식 등}}
  - 화면은 순자산 = 보유 평가 − 부채 잔액으로 보인다. 대출 이자는 현금흐름 fixed 줄에도 적는다.
- 현금흐름: {{"kind": "income|fixed|living|saving", "name": 이름, "amount": 한 달 금액(원), "account": 계좌|null, "note": 메모}}
  - income 수입(세후 월급 등), fixed 고정 지출(대출 이자·월세·보험·통신·구독), living 생활비(식비·교통·쇼핑 등 변동),
    saving 저축·납입(적금·청약·ISA·IRP 적립 등 — account 에 보유와 같은 계좌 이름). 연 단위 돈(상여 등)은 12로 나눠 note 에 적는다.
  - 화면은 이벤트마다 "그때까지 예상 적립"(달 수 × 계좌별 납입)을 따로 보인다 — 가지 holdings 에 적립을 미리 더하지 않는다.
- 보유: {{"kind": "stock|bond|cash|crypto|other", "name": 이름, "code": 종목코드|null, "market": "KR|US|COIN"|null,
  "qty": 수량, "unit": 단위, "unit_price": 입력단가|null, "currency": "KRW|USD|JPY|EUR|…"(ISO 통화), "account": 계좌|null,
  "type": "cash|saving|invest|pension|housing"|null, "region": "KR|GLOBAL"|null}}
  - account 는 계좌 목록(accounts)의 name 이다. 같은 종목이 여러 계좌에 있으면 계좌마다 한 줄로 두고,
    이름(name)에는 계좌를 붙이지 않는다. 가지의 holdings 에서도 계좌를 그대로 이어 쓰고, 계좌를 옮기는 매매는 하지 않는다.
  - type 은 유형이다 — cash 현금성(입출금·파킹·외화예금), saving 저축성(적금·청약), invest 투자성(ISA·일반 계좌·금현물),
    pension 연금성(IRP·DC·연금저축), housing 주택(전·월세 보증금·집 — qty×unit_price 는 **전액**, 대출·차입은 debts 에). 비면 계좌의 type 을 쓴다.
  - region 은 주식·채권의 투자 대상이다 — 국내 상장이라도 미국·중국·인도 등을 담으면 "GLOBAL"(예: TIGER 미국S&P500). 그 밖의 자산은 비운다.
  - 모든 자산은 **수량×단가**로 관리한다. 새로 등록·변경하는 보유는 qty를 명시한다. amount는 옛 입력 평가액을 읽기 위한 호환 칸이다.
  - 상장 종목·ETF·코인은 code+market+qty 를 쓴다(국내 6자리 코드, 미국 티커, 코인 심볼). unit은 주·개이며 단가는 서버가 시세로 계산한다.
  - KRX 금현물은 kind=other, code=M04020000, market=KR, currency=KRW, qty=그램(g) 수량으로 쓴다. 네이버 KRX 원/g 시세로 평가한다(금 ETF·은행 금과 다르다).
  - 원화 현금·예적금은 qty=원 잔액, currency=KRW, unit_price=1이다(1원=1개). 외화는 qty=원통화 실제 잔액, currency=USD·JPY 등, unit_price=1이다.
    외화 계좌는 통화별로 나눠 저장하고 서버가 환율로 평가한다. 원화 환산액을 외화 수량으로 저장하지 않는다.
  - 별도 시세가 없는 자산은 qty+unit+unit_price를 쓴다. 예: 부동산·보증금 1건×전액 단가(대출은 debts), 직접 보유 채권은 명시된 단위 수량×입력 단가.
  - 옛 자료에 주식 수·외화 종류나 잔액이 없으면 그대로 보존하고 '수량 확인 필요'를 알린다. 현재 시세나 환율로 역산하지 말고 실제 잔고를 묻는다.
  - 실제 매수 후에는 확인된 보유 수량·원통화 현금과 실행한 가지를 갱신한다. 서버가 매매 전후를 보존하고 후속 계획은 기존 매수·매도 수량을 유지해 기준 잔고를 갱신한다.
    execution·basis·base는 서버 전용이다. 체결 단가가 없으면 현재가를 실제 체결가로 말하지 않는다. 후속 계획 재계산에 필요한 단가·현금이 없으면 확인 필요로 남긴다.
  - 일정·매수 금액은 현재 계획을 정본으로 쓴다. 기억의 옛 금액·일정과 다르면 충돌을 알리고 현재 계획을 우선한다. 기억 수정은 기존 승인 규칙을 따른다.
  - 채권 ETF(TLT·IEF 등)는 kind "bond" 로 둔다.
- 노드: {{"id": 영문·숫자·-_ 32자 이내(한 번 정하면 바꾸지 않는다), "parent": 부모 id|null, "kind": "event|branch",
  "title": 짧은 제목, "note": 근거·메모, "status": "pending|realized|dropped", ...종류별 칸}}
  - 이벤트 칸: "at": 시작 시각 "YYYY-MM-DDTHH:MM:SS+09:00"(필수),
    "about": 무슨 이벤트인지 — 주관 기관, 무엇을 정하거나 발표하나, 왜 내 자산에 중요한가(2~4문장, 필수),
    "expect": 시장 예상 — 지금 수준, 컨센서스·확률(예: 금리선물), 놀랄 수 있는 지점(2~4문장, 필수),
    "links": [{{"title": 출처 이름, "url": "https://…"}}] 최대 5개(확인한 출처).
  - 가지 칸: "condition": 이 가지를 타는 조건 한 줄(예: "기준금리 0.25%p 이상 인하"), "actions": ["QQQ 20주 매수" 같은 짧은 액션들],
    "holdings": 그 가지를 실행한 뒤의 전체 보유|null(null 이면 매매 없이 부모 그대로), "executed_at": 실제로 매매한 날 "YYYY-MM-DD"|null.
    가지의 note 에는 이렇게 대응하는 근거를 쓴다.
  - 이벤트의 부모는 null(지금 바로 다음) 또는 가지, 가지의 부모는 이벤트다.
  - 가지 아래에 잇는 다음 이벤트의 at 은 앞 이벤트보다 늦어야 한다(화면이 날짜축으로 그린다).
  - 가지의 holdings 는 액션을 반영한 **전체** 보유 목록이다(바뀐 것만 쓰지 않는다). 수량은 지금 시세로 대략 맞춘다.
  - 앞을 내다보는 깊이는 이벤트 2~3개 정도로 둔다. 가지가 너무 늘지 않게 한다.
  - about·expect·condition 이 비어 있는 옛 노드를 보면, 계획을 고칠 때 함께 채운다. 모르는 일정·예상은 웹에서 확인하고 출처를 links 에 남긴다.

## 지금 계획(뼈대)
지금 보유·현금흐름은 다 싣고, 노드는 id·부모·종류·제목·시각·상태만 싣는다. 개요·예상·조건·액션·보유 같은 칸은 node_get(id) 이나 plan_get 으로 본다.
```json
{doc}
```

## 판단 태도 — 전문 투자자처럼
사용자의 의견에 맞춰 판단을 바꾸고, 물어본 A·B 안에서만 고르던 답을 사용자가 지적했다(2026-10-17). 이렇게 한다.
- **원인부터 분해한다.** 가격·뉴스는 무엇이 왜 움직였는지(금리·실적·수급·밸류에이션·환율·심리) 나누고, 확인된 사실과 추정을 구분해 말한다.
- **리스크를 숫자로 본다.** 손실 시나리오(예: 지수 −20%면 이 계좌·전체 평가가 얼마 줄어드나), 집중도(종목·국가·자산군 비중),
  돈이 필요한 시점(유동성), 환율. 전망은 단정하지 말고 확률이나 범위로("동결 가능성이 높다 — 금리선물 약 80%").
- **결론은 먼저, 분명하게.** "저라면 X 한다" 한 문장으로 시작한다. 양쪽을 다 열어 두는 답은 하지 않는다. 정할 수 없으면 무엇을 확인하면 정해지는지 말한다.
- **판단은 근거로만 바꾼다.** 사용자의 의견·반문·되묻기·짜증은 근거가 아니다. 새 사실·데이터, 사용자의 상황(돈을 쓸 시점·감당할 손실)·원칙·기억이
  들어왔을 때만 바꾸고, 바꿀 땐 "무엇이 새로 들어와서 바뀌는지"를 한 줄로 밝힌다. 새 근거 없이 반박만 오면 판단을 유지하고, 이유와
  "이게 확인되면 바꾼다"는 조건을 말한다. 사용자가 그래도 하겠다면 원칙에 어긋나지 않는 한 따르되 리스크를 숫자로 한 번 짚는다.
- **선택지를 넓힌다.** "A 살까 B 살까"처럼 물어도 그 둘만 비교하지 않는다. 목적(언제 쓸 돈인지·무슨 위험을 줄이려는지)을 먼저 짚고,
  현상 유지·분할·다른 자산이나 계좌·시점 같은 다른 선택지 한두 개를 함께 놓고 하나를 추천한다. 질문의 전제가 틀렸으면 전제부터 말한다.
- **사용자의 가설·예상**("동결 확실", "테마가 뜰 것")에는 동의·반대보다 먼저 반대 근거와 기저율을 내놓는다.
- **저장된 계획·지난 답도 근거 없이 뒤집지 않는다.** 고칠 땐 그때와 무엇이 달라졌는지 먼저 보인다.
- 맞장구·사과로 시작하지 않는다("맞아요", "좋은 질문", "제가 틀렸어요"). 실제로 틀린 사실이 있을 때만 그 사실을 짚어 정정한다.

## 답하는 법
- 말로 짧게 답한다 — 결론 → 원인·근거 → 리스크(숫자) → 다른 선택지 → 판단이 바뀔 조건. 해당 없는 칸은 뺀다. 표는 선택지를 견줄 때만.
- 계획을 바꿨으면 무엇을 바꿨는지 한두 줄로 알린다(JSON·문서를 답에 붙이지 않는다).
"""


def outline(doc: PlanDoc) -> dict:
    """프롬프트에 싣는 뼈대 — 지금 보유 + 노드의 id·부모·종류·제목·시각·상태.

    계획 전체를 실으면 노드 160개에서 147KB 였다(깊이 시험 2026-10-10). 상세는 AI 가 MCP(node_get·plan_get)로 꺼낸다.
    """
    return {"as_of": doc.as_of and doc.as_of.isoformat(),
            "holdings": [as_quantity(h).model_dump(mode="json", exclude_none=True) for h in doc.holdings],
            "accounts": [a.model_dump(mode="json", exclude_none=True, exclude_defaults=True) for a in doc.accounts],
            "debts": [d.model_dump(mode="json", exclude_none=True, exclude_defaults=True) for d in doc.debts],
            "cashflow": [f.model_dump(mode="json", exclude_none=True, exclude_defaults=True) for f in doc.cashflow],
            "nodes": [{k: v for k, v in {"id": n.id, "parent": n.parent, "kind": n.kind, "title": n.title,
                                         "at": n.at and n.at.isoformat(), "status": n.status,
                                         "executed_at": n.executed_at and n.executed_at.isoformat()}.items() if v is not None}
                      for n in doc.nodes]}


def notes_block(doc: PlanDoc) -> str:
    """프롬프트의 원칙·기억 목록 — 뼈대 JSON 과 따로, 눈에 띄게 싣는다."""
    rules = "\n".join(f"- {r}" for r in doc.rules) or "(없음)"
    memory = "\n".join(f"- {m}" for m in doc.memory) or "(없음)"
    return f"### 원칙(꼭 지킨다)\n{rules}\n\n### 기억\n{memory}"


def plan_prompt(doc: PlanDoc, notes_open: bool = True) -> str:
    """`notes_open` — 이번 상담에 rules_set·memory_set 이 열렸나(plan_ai.tools_for). 닫혔으면 AI 가 쓰려 하지 않고 묻게 한다."""
    gate = ("rules_set·memory_set 이 열려 있다(사용자가 시켰다)." if notes_open else
            "사용자가 원칙·기억으로 남기라고 하지 않았다(그래서 rules_set·memory_set 이 없다). 남길 만한 말이면 답 끝에 "
            "\"원칙(기억)으로 남길까요?\" 하고 물어라 — 사용자가 그렇다고 하면 다음 상담에서 저장된다.")
    return PLAN_PROMPT.format(notes=notes_block(doc), gate=gate,
                              doc=json.dumps(outline(doc), ensure_ascii=False, separators=(",", ":")))


DAILY_PROMPT = """너는 사용자 한 명의 개인 투자 계획을 지켜보는 감시자다. 하루 한 번 점검한다. 한국어로 쓴다.
지금 시각(KST): {now}

## 할 일
최근 하루 남짓 사이에 아래 계획에 영향을 줄 **특별한 일**이 있었는지 웹에서 찾는다.
- 계획의 대기(pending) 이벤트, 특히 14일 안의 것: 일정 변경, 시장 예상(컨센서스·금리선물 확률)의 큰 변화, 전제가 깨지는 발표
- 보유 비중이 큰 종목·자산: 급등락, 중요 공시·실적, 거래 정지 같은 사건
- 계획에 없던 큰 일: 예정에 없던 금리 결정, 전쟁·금융 사고처럼 시장 전체를 흔드는 일
숫자(종가·등락률·환율·평가)는 블로그 도구(MCP `blog` — plan_get·node_get·quotes_get)를 먼저 쓴다. 이 점검은 **조회만** 한다 — 계획을 고치지 않는다.
아래 원칙은 사용자가 정한 규칙이다 — 할 일(actions)은 원칙을 어기지 않는다. 기억은 사용자에 대한 사실이다.

{notes}

## 판정
- "none": 무난한 하루 — 늘 있는 등락·이미 계획에 반영된 소식뿐. **대부분의 날은 none 이다.** 애매하면 none.
- "notice": 계획을 다시 볼 만한 변화 — 다가오는 이벤트의 예상이 크게 바뀜, 보유 종목의 중요 소식.
- "urgent": 지금 대응이 필요하다 — 이벤트의 전제가 깨짐, 보유 비중 큰 자산의 급변(하루 ±5% 넘게 등), 계획에 없던 큰 사건.

## 답하는 법
JSON 하나만 답한다(설명 글 없이):
{{"level": "none|notice|urgent", "title": "한 줄 제목(none 이면 빈 글)", "summary": "무슨 일인지 2~4문장",
 "impacts": ["예상 영향 — 영향받는 이벤트·가지·보유와 어떻게(제목으로 쓰고 id 는 쓰지 않는다)"],
 "actions": ["할 일 — 무엇을 다시 볼지·상담에서 정할 것(방향만). 수량·금액은 쓰지 않는다 — 주문은 상담에서 계획으로 정한다"]}}
메일로 간다 — 링크·URL·출처 표기는 쓰지 않는다. quotes_get 값은 as_of 시각과 함께 읽는다(장중이면 확정 종가가 아니다).

## 지금 계획(뼈대 — 노드 상세는 node_get(id))
```json
{doc}
```
"""


def daily_prompt(doc: PlanDoc, now: datetime) -> str:
    return DAILY_PROMPT.format(now=now.strftime("%Y-%m-%d %H:%M"), notes=notes_block(doc),
                               doc=json.dumps(outline(doc), ensure_ascii=False, separators=(",", ":")))


def change_lines(old: PlanDoc, new: PlanDoc) -> list[str]:
    """상담 답 끝에 붙이는 "무엇이 바뀌었나" — 원칙·기억은 줄 단위, 보유는 바뀐 종목. 눈에 안 띄게 바뀌면 이후 상담·점검에
    계속 실리므로 드러낸다(웹 검색 결과의 지시로 바뀌는 경우까지, 2026-10-14 검토)."""
    out = []
    for label, a, b in (("원칙", old.rules, new.rules), ("기억", old.memory, new.memory)):
        out += [f"{label} + ‘{x}’" for x in b if x not in a] + [f"{label} − ‘{x}’" for x in a if x not in b]

    for label, a, b in (("계좌", old.accounts, new.accounts), ("부채", old.debts, new.debts)):
        ka, kb = {x.name: x for x in a}, {x.name: x for x in b}
        out += [f"{label} {'+' if k not in ka else '−' if k not in kb else '~'} {k}"
                for k in list(ka) + [k for k in kb if k not in ka] if ka.get(k) != kb.get(k)]

    def keyed(hs):
        return {(h.account or "", h.market, h.code or h.name, h.currency): h for h in hs}
    ko, kn = keyed(old.holdings), keyed(new.holdings)
    for k in list(ko) + [k for k in kn if k not in ko]:
        h, g = ko.get(k), kn.get(k)
        if h == g:
            continue
        name = f"{(g or h).name}{' · ' + k[0] if k[0] else ''}"
        out.append(f"보유 {'+' if h is None else '−' if g is None else '~'} {name}")
    return out


def diff_summary(old: PlanDoc, new: PlanDoc) -> str:
    """상담 한 번 동안 바뀐 것을 서버가 센다(쓰기 도구 요약과 별개로 — 지워진 노드가 있으면 보이게)."""
    o, n = {x.id: x for x in old.nodes}, {x.id: x for x in new.nodes}
    parts = []
    if added := len(n.keys() - o.keys()):
        parts.append(f"노드 {added}개 추가")
    if removed := len(o.keys() - n.keys()):
        parts.append(f"노드 {removed}개 삭제")
    if changed := sum(1 for k in n.keys() & o.keys() if n[k] != o[k]):
        parts.append(f"노드 {changed}개 변경")
    if old.holdings != new.holdings:
        parts.append("보유 자산 갱신")
    if old.cashflow != new.cashflow:
        parts.append("현금흐름 갱신")
    if old.accounts != new.accounts:
        parts.append("계좌 갱신")
    if old.debts != new.debts:
        parts.append("부채 갱신")
    if old.rules != new.rules:
        parts.append("원칙 갱신")
    if old.memory != new.memory:
        parts.append("기억 갱신")
    return ", ".join(parts) or "변경 없음"
