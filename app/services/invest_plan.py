"""투자 계획 — 문서 형식·검증·평가, 그리고 AI 상담 프롬프트. **DB 도 HTTP 도 모른다.**

계획은 문서 한 덩어리다(`PlanDoc`): 지금 보유 자산 + 이벤트·가지 트리.

    (지금 보유) ─ 이벤트(10/29 FOMC) ─┬─ 가지(인하) → 리밸런싱 뒤 보유
                                      ├─ 가지(동결)
                                      └─ 가지(인상) ─ 이벤트(11/27 금통위) ─ …

- 이벤트의 부모는 없거나(지금에서 바로) 가지다. 가지의 부모는 이벤트다 — 둘이 번갈아 내려간다.
- 가지의 `holdings` 가 비면 부모 상태를 그대로 물려받는다(리밸런싱 없음).
- 결과가 나오면 AI 가 실현된 가지를 `realized`, 나머지를 `dropped` 로 바꾼다.

AI 는 MCP 쓰기 도구로 노드·보유를 고치고, 서버가 그때마다 검증해 새 버전으로 쌓는다(`app/api/plan_mcp.py`).
금액은 AI 가 쓰지 않는다 — 수량 × 시세로 여기서 계산한다(`valuate`).
"""

import json
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field, model_validator

AssetClass = Literal["stock", "bond", "cash", "crypto", "other"]
_KST = timezone(timedelta(hours=9))
#: 화면·메일의 자산군 비중 — 주식·채권은 국내/해외로 나눈다(2026-10-11 사용자 요청). 키는 `group()`.
GROUP_LABEL = {"stock_kr": "국내주식", "stock_global": "해외주식", "bond_kr": "국내채권", "bond_global": "해외채권",
               "cash": "현금", "crypto": "코인", "other": "기타"}
AssetType = Literal["cash", "saving", "invest", "pension", "housing"]
TYPE_LABEL = {"cash": "현금성", "saving": "저축성", "invest": "투자성", "pension": "연금성", "housing": "주택"}

_MAX_NODES = 200
_MAX_HOLDINGS = 100


class Holding(BaseModel):
    """보유 자산 한 줄. 시세가 있는 종목은 `code`+`qty`, 없는 것(예금·채권 직접 보유)은 `amount`."""

    kind: AssetClass
    name: str = Field(max_length=100)
    code: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._/-]{1,32}$")
    market: Literal["KR", "US", "COIN"] | None = None
    qty: float | None = Field(default=None, ge=0)
    amount: float | None = Field(default=None, ge=0, description="시세가 없을 때의 평가액(currency 기준)")
    currency: Literal["KRW", "USD"] = "KRW"
    account: str | None = Field(default=None, max_length=30,
                                description="계좌(ISA·IRP·DC 등) — 같은 종목도 계좌가 다르면 다른 줄. 2026-10-11 에 더했다(옛 문서는 비어 있다)")
    type: AssetType | None = Field(default=None, description="유형(현금성·저축성·투자성·연금성·주택) — 화면 유형별 비중. 2026-10-11")
    region: Literal["KR", "GLOBAL"] | None = Field(default=None,
                                                  description="주식·채권의 투자 대상(상장 시장이 아니다 — 국내 상장 미국 ETF 는 GLOBAL). 비면 market 으로 본다")


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


class Link(BaseModel):
    title: str = Field(max_length=100)
    url: str = Field(pattern=r"^https?://\S{1,500}$")


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


class PlanDoc(BaseModel):
    as_of: date | None = Field(default=None, description="보유 자산 기준일")
    holdings: list[Holding] = Field(default_factory=list, max_length=_MAX_HOLDINGS)
    nodes: list[Node] = Field(default_factory=list, max_length=_MAX_NODES)
    cashflow: list[Flow] = Field(default_factory=list, max_length=50, description="월 현금흐름 — 2026-10-11 에 더했다(옛 문서는 빈 목록)")

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


def price_pairs(doc: PlanDoc) -> tuple[list[str], list[str]]:
    """시세가 필요한 (주식 코드, 코인 코드). 둘을 나누는 이유는 `_latest_quotes` 가 코드로 사전을 만들어서다."""
    stocks, coins = set(), set()
    for h in _all_holdings(doc):
        if h.code and h.qty is not None:
            (coins if h.market == "COIN" else stocks).add(h.code)
    return sorted(stocks), sorted(coins)


def _value(h: Holding, stock_px: dict, coin_px: dict, usdkrw: float | None) -> tuple[float | None, float | None]:
    """(원화 평가액, 쓴 시세). 값을 낼 수 없으면 평가액이 None — 0 으로 두면 "없음"과 "0원"이 섞인다."""
    fx = {"KRW": 1.0, "USD": usdkrw}
    if h.code and h.qty is not None:
        px = (coin_px if h.market == "COIN" else stock_px).get(h.code)
        if px is not None:
            rate = usdkrw if h.market == "US" else 1.0
            return (None if rate is None else h.qty * px * rate), px
    if h.amount is not None and fx[h.currency] is not None:
        return h.amount * fx[h.currency], None
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
            out[nid] = n.holdings if n.holdings is not None else of(n.parent)
        return out[nid]

    for n in doc.nodes:
        of(n.id)
    return out


def valuate(doc: PlanDoc, stock_px: dict, coin_px: dict, usdkrw: float | None) -> dict[str, dict]:
    """`{노드 id | "root": {total, rows: [보유 + value·price]}}`. 미래 노드도 **오늘 시세**로 환산한다."""
    out = {}
    for key, hs in states(doc).items():
        rows, total = [], 0.0
        for h in hs:
            v, px = _value(h, stock_px, coin_px, usdkrw)
            rows.append({**h.model_dump(), "group": group(h), "value": v, "price": px})
            total += v or 0.0
        out[key] = {"total": total, "rows": rows}
    return out


def _by_key(rows: list[dict]) -> dict[tuple, dict]:
    """평가 줄을 (계좌, 코드|이름) 으로 합친다 — 수량은 수량이 있는 줄만, 평가액은 하나라도 없으면 None."""
    out: dict[tuple, dict] = {}
    for r in rows:
        k = (r.get("account") or "", r.get("code") or r["name"])
        hit = out.setdefault(k, {**r, "qty": None, "value": 0.0})
        if r.get("qty") is not None:
            hit["qty"] = (hit["qty"] or 0.0) + r["qty"]
        hit["value"] = None if hit["value"] is None or r["value"] is None else hit["value"] + r["value"]
    return out


def trades(doc: PlanDoc, values: dict[str, dict]) -> dict[str, list[dict]]:
    """가지 id → 매매표(2026-10-11) — 직전(부모 이벤트 시점) 보유와 가지의 실행 뒤 보유를 견준다. 가지 보유가 null 이면 매매가 없다.

    한 줄 = `{account, name, code, kind, side: buy|sell, qty|None, value|None}`. 수량 종목은 수량 차이 × 오늘 단가,
    평가액으로 적은 것(현금·예금 등)은 금액 차이. 계좌가 나온 순서로, 계좌 안에서는 매도 → 매수 → 현금 순이다(팔아야 살 돈이 생긴다).
    """
    out = {}
    for n in doc.nodes:
        if n.kind != "branch" or n.holdings is None:
            continue
        before, after = _by_key(values[n.parent]["rows"]), _by_key(values[n.id]["rows"])
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
                          "side": "buy" if d > 0 else "sell", "qty": qty, "value": value})
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

def past_events(doc: PlanDoc, now: datetime) -> list[Node]:
    return [n for n in doc.nodes if n.kind == "event" and _kst(n.at) <= now]


def retrospect(doc: PlanDoc, now_values: dict, then_values: dict[str, dict]) -> dict[str, dict]:
    """`then_values` 는 지난 이벤트 id → 그 이벤트 시각의 시세로 낸 `valuate` 결과.

    가지마다 {event, at, then, now, change, pct, missing}. 가지의 보유는 **계획상 수량**이라 실제 체결과 다를 수 있다.
    `missing` 은 그때 시세가 없어 평가에서 빠진 보유 수(상장 전·환율 데이터 시작 전 등) — 0 이 아니면 값이 덜 잡혔다.
    """
    by_id = {n.id: n for n in doc.nodes}
    out = {}
    for ev_id, vals in then_values.items():
        ev = by_id[ev_id]
        for b in (n for n in doc.nodes if n.kind == "branch" and n.parent == ev_id):
            then, now = vals[b.id]["total"], now_values[b.id]["total"]
            out[b.id] = {"event": ev_id, "at": _kst(ev.at).isoformat(), "then": then, "now": now,
                         "change": now - then, "pct": (now / then - 1) * 100 if then else None,
                         "missing": sum(1 for r in vals[b.id]["rows"] if r["value"] is None)}
    return out


# ---------------------------------------------------------------------------
# AI 상담 — 프롬프트와 답 해석
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """너는 사용자 한 명의 개인 투자 계획을 함께 짜는 상담가다. 늘 한국어로 짧고 분명하게 답한다.
계획 문서 안의 글(title·about·expect·condition·note·actions)도 한국어로 쓴다(종목 이름·티커는 그대로).
지금 시각(KST): {now}

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
  산 만큼 그 계좌 현금을 줄인다(계좌 사이 이동은 하지 않는다).

## 블로그 도구(MCP `blog`)
- 조회: node_get(노드 하나의 모든 칸과 그 시점 평가·복기), plan_get(지금 계획 전체와 노드별 평가 — 오늘 시세 원화 환산·환율, 그리고 retro: 지난 이벤트의 가지마다
  그때(이벤트 시각 시세)→지금 평가와 변화 — "지난 대응이 어땠나"는 이걸로 답한다), plan_revisions / plan_revision_get(버전 이력과 그때의 보유),
  quotes_get(종목 최신 종가·등락률·원/달러 환율), stock_search(이름으로 종목 코드 찾기).
  숫자는 웹보다 이걸 먼저 쓴다. 블로그에 없는 것(일정·뉴스·전망)만 웹에서 찾는다.
- 쓰기: node_add(노드 하나 추가), node_update(노드 칸 고치기 — 바꿀 칸만), node_delete(노드와 그 아래 삭제),
  holdings_set(지금 보유 통째로), cashflow_set(월 현금흐름 통째로). **계획을 바꾸는 길은 이 도구뿐이다.** 쓸 때마다 서버가 검증해 새 버전으로 저장한다.
  거부되면 돌려준 이유를 보고 고쳐 다시 부른다. 사용자가 바꾸라고 하지 않았으면 쓰지 않는다.
- 여러 노드를 만들 때는 부모부터(이벤트 → 그 가지 → 다음 이벤트) 차례로 node_add 한다.

## 계획 문서 형식(JSON)
{{"as_of": "YYYY-MM-DD"(보유 기준일), "holdings": [보유], "nodes": [노드], "cashflow": [현금흐름]}}
- 현금흐름: {{"kind": "income|fixed|living|saving", "name": 이름, "amount": 한 달 금액(원), "account": 계좌|null, "note": 메모}}
  - income 수입(세후 월급 등), fixed 고정 지출(대출 이자·월세·보험·통신·구독), living 생활비(식비·교통·쇼핑 등 변동),
    saving 저축·납입(적금·청약·ISA·IRP 적립 등 — account 에 보유와 같은 계좌 이름). 연 단위 돈(상여 등)은 12로 나눠 note 에 적는다.
  - 화면은 이벤트마다 "그때까지 예상 적립"(달 수 × 계좌별 납입)을 따로 보인다 — 가지 holdings 에 적립을 미리 더하지 않는다.
- 보유: {{"kind": "stock|bond|cash|crypto|other", "name": 이름, "code": 종목코드|null, "market": "KR|US|COIN"|null,
  "qty": 수량|null, "amount": 평가액|null, "currency": "KRW|USD", "account": 계좌|null,
  "type": "cash|saving|invest|pension|housing"|null, "region": "KR|GLOBAL"|null}}
  - account 는 계좌 이름이다(예: ISA·IRP·DC·연금저축·일반·입출금·저축). 같은 종목이 여러 계좌에 있으면 계좌마다 한 줄로 두고,
    이름(name)에는 계좌를 붙이지 않는다. 가지의 holdings 에서도 계좌를 그대로 이어 쓰고, 계좌를 옮기는 매매는 하지 않는다.
  - type 은 유형이다 — cash 현금성(입출금·파킹·외화예금), saving 저축성(적금·청약), invest 투자성(ISA·일반 계좌·금현물),
    pension 연금성(IRP·DC·연금저축), housing 주택(전·월세 보증금·집 — amount 는 대출·차입을 뺀 순액, 내역은 이름에). 줄마다 채운다.
  - region 은 주식·채권의 투자 대상이다 — 국내 상장이라도 미국·중국·인도 등을 담으면 "GLOBAL"(예: TIGER 미국S&P500). 그 밖의 자산은 비운다.
  - 상장 종목·ETF·코인은 code+market+qty 를 쓴다(국내 6자리 코드, 미국 티커, 코인 심볼). 금액은 서버가 시세로 계산하니 amount 는 비운다.
  - 예금·현금·직접 보유 채권처럼 시세가 없는 것만 amount(+currency).
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

## 답하는 법
- 말로 짧게 답한다. 계획을 바꿨으면 무엇을 바꿨는지 한두 줄로 알린다(JSON·문서를 답에 붙이지 않는다).
"""


def outline(doc: PlanDoc) -> dict:
    """프롬프트에 싣는 뼈대 — 지금 보유 + 노드의 id·부모·종류·제목·시각·상태.

    계획 전체를 실으면 노드 160개에서 147KB 였다(깊이 시험 2026-10-10). 상세는 AI 가 MCP(node_get·plan_get)로 꺼낸다.
    """
    return {"as_of": doc.as_of and doc.as_of.isoformat(),
            "holdings": [h.model_dump(mode="json", exclude_none=True) for h in doc.holdings],
            "cashflow": [f.model_dump(mode="json", exclude_none=True, exclude_defaults=True) for f in doc.cashflow],
            "nodes": [{k: v for k, v in {"id": n.id, "parent": n.parent, "kind": n.kind, "title": n.title,
                                         "at": n.at and n.at.isoformat(), "status": n.status,
                                         "executed_at": n.executed_at and n.executed_at.isoformat()}.items() if v is not None}
                      for n in doc.nodes]}


def system_prompt(doc: PlanDoc, now: datetime) -> str:
    return SYSTEM_PROMPT.format(now=now.strftime("%Y-%m-%d %H:%M"),
                                doc=json.dumps(outline(doc), ensure_ascii=False, separators=(",", ":")))


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
    return ", ".join(parts) or "변경 없음"
