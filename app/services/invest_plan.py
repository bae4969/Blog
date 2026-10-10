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
CLASS_LABEL = {"stock": "주식", "bond": "채권", "cash": "현금", "crypto": "코인", "other": "기타"}

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


class PlanDoc(BaseModel):
    as_of: date | None = Field(default=None, description="보유 자산 기준일")
    holdings: list[Holding] = Field(default_factory=list, max_length=_MAX_HOLDINGS)
    nodes: list[Node] = Field(default_factory=list, max_length=_MAX_NODES)

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
            rows.append({**h.model_dump(), "value": v, "price": px})
            total += v or 0.0
        out[key] = {"total": total, "rows": rows}
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
- 이벤트 결과를 사용자가 알려 주거나 네가 확인하면, 실현된 가지를 "realized", 나머지 가지를 "dropped" 로 바꾸고,
  필요하면 그 아래 다음 이벤트를 이어 붙인다. 일정·결과를 모르면 웹에서 확인할 수 있으면 확인하고, 아니면 묻는다.

## 블로그 도구(MCP `blog`)
- 조회: plan_get(지금 계획과 노드별 평가 — 오늘 시세 원화 환산·환율), plan_revisions / plan_revision_get(버전 이력과 그때의 보유),
  quotes_get(종목 최신 종가·등락률·원/달러 환율), stock_search(이름으로 종목 코드 찾기).
  숫자는 웹보다 이걸 먼저 쓴다. 블로그에 없는 것(일정·뉴스·전망)만 웹에서 찾는다.
- 쓰기: node_add(노드 하나 추가), node_update(노드 칸 고치기 — 바꿀 칸만), node_delete(노드와 그 아래 삭제),
  holdings_set(지금 보유 통째로). **계획을 바꾸는 길은 이 도구뿐이다.** 쓸 때마다 서버가 검증해 새 버전으로 저장한다.
  거부되면 돌려준 이유를 보고 고쳐 다시 부른다. 사용자가 바꾸라고 하지 않았으면 쓰지 않는다.
- 여러 노드를 만들 때는 부모부터(이벤트 → 그 가지 → 다음 이벤트) 차례로 node_add 한다.

## 계획 문서 형식(JSON)
{{"as_of": "YYYY-MM-DD"(보유 기준일), "holdings": [보유], "nodes": [노드]}}
- 보유: {{"kind": "stock|bond|cash|crypto|other", "name": 이름, "code": 종목코드|null, "market": "KR|US|COIN"|null,
  "qty": 수량|null, "amount": 평가액|null, "currency": "KRW|USD"}}
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
    "holdings": 그 가지를 실행한 뒤의 전체 보유|null(null 이면 부모 그대로). 가지의 note 에는 이렇게 대응하는 근거를 쓴다.
  - 이벤트의 부모는 null(지금 바로 다음) 또는 가지, 가지의 부모는 이벤트다.
  - 가지 아래에 잇는 다음 이벤트의 at 은 앞 이벤트보다 늦어야 한다(화면이 날짜축으로 그린다).
  - 가지의 holdings 는 액션을 반영한 **전체** 보유 목록이다(바뀐 것만 쓰지 않는다). 수량은 지금 시세로 대략 맞춘다.
  - 앞을 내다보는 깊이는 이벤트 2~3개 정도로 둔다. 가지가 너무 늘지 않게 한다.
  - about·expect·condition 이 비어 있는 옛 노드를 보면, 계획을 고칠 때 함께 채운다. 모르는 일정·예상은 웹에서 확인하고 출처를 links 에 남긴다.

## 지금 계획 문서
```json
{doc}
```

## 답하는 법
- 말로 짧게 답한다. 계획을 바꿨으면 무엇을 바꿨는지 한두 줄로 알린다(JSON·문서를 답에 붙이지 않는다).
"""


def system_prompt(doc: PlanDoc, now: datetime) -> str:
    return SYSTEM_PROMPT.format(now=now.strftime("%Y-%m-%d %H:%M"),
                                doc=json.dumps(doc.model_dump(mode="json"), ensure_ascii=False, indent=1))


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
    return ", ".join(parts) or "변경 없음"
