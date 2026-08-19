"""`/api/v1/stocks` — 종목·캔들·체결.

기존 `/stocks/api/*` 와 **같은 헬퍼**(`_stock_page`·`candle_rows`)를 쓴다. 쿼리를 다시
짜면 화면과 API 가 조용히 갈라진다 — 액면분할 소급 보정 같은 것이 한쪽에만 적용되면
같은 종목의 차트가 두 곳에서 다르게 보인다.

옛 API 와 다른 점은 셋이다:

1. `require_internal` 을 걸지 않는다 — 그쪽은 브라우저 전용이라 앱·스크립트가 못 붙었다.
   종목 데이터는 화면도 비로그인에 열려 있는 **공개 데이터**라 토큰도 요구하지 않는다.
2. 컬럼 이름을 그대로 내보내지 않는다(`execution_min` → `low`).
3. 실패를 HTTP 상태코드로 말한다. 옛 API 는 200 에 `{success: false}` 를 담았다.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import text

from app.db.session import db_session
from app.schemas.stock import Candle, Execution, StockOut
from app.schemas import Page
from app.ui.stocks import (
    _KST,
    _latest_closes,
    _norm_market,
    _prefix_of,
    _resolve_is_coin,
    _resolve_source,
    _stock_page,
    _TIMEFRAMES,
    candle_rows,
)

router = APIRouter(prefix="/api/v1/stocks", tags=["stock"])

_MAX_SIZE = 100
_MAX_CANDLES = 1000
_MAX_EXECUTIONS = 500


def _f(v) -> float | None:
    return None if v is None else float(v)


@router.get("", response_model=Page[StockOut], summary="종목 목록·검색")
async def stocks(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=_MAX_SIZE),
    market: str | None = Query(None, description="KR·US·COIN. 비우면 전부"),
    q: str | None = Query(None, max_length=50, description="종목명·코드 부분검색"),
):
    async with db_session() as db:
        total, rows = await _stock_page(db, _norm_market(market) or "", (q or "").strip(), page)
        # ⚠️ `stock_info.stock_price` 는 **갱신이 늦다.** 화면은 `candle` 의 최신 종가를
        #    씌워서 그리는데 API 가 그 단계를 빼먹어, 같은 종목이 화면과 API 에서 다른
        #    값으로 나갔다(2026-08-19 실측: 5/5 불일치. DB 로 판정하니 화면이 맞았다 —
        #    tick 의 최신 체결가와 종가가 같고 stock_price 만 옛값이었다).
        closes = await _latest_closes(db, [(r.code, _prefix_of(r)) for r in rows])

    pages = max(1, (total + size - 1) // size)
    items = [
        StockOut(code=r.code, name_kr=r.name_kr, name_en=r.name_en, market=r.market,
                 type=r.stock_type, price=_f(closes.get(r.code, r.price)),
                 market_cap=_f(r.cap), quantity=_f(r.quantity))
        for r in rows[:size]
    ]
    return Page[StockOut](items=items, total=total, page=page, size=size, pages=pages)


@router.get("/{code}/candles", response_model=list[Candle], summary="캔들")
async def candles(
    code: str,
    market: str | None = Query(None),
    timeframe: str = Query("1h", description=f"{', '.join(_TIMEFRAMES)}"),
    limit: int = Query(500, ge=1, le=_MAX_CANDLES),
    days: int = Query(30, ge=1, le=3650, description="지금부터 거슬러 올라갈 일수"),
):
    if timeframe not in _TIMEFRAMES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"timeframe 은 {_TIMEFRAMES} 중 하나여야 합니다")
    # ⚠️ **반드시 KST 로 잰다.** 컨테이너 시계는 UTC 인데 DB 안의 시각은 전부 KST 다
    #    (`db/session.py` 가 세션 TZ 를 +09:00 으로 못박는다). `datetime.now()` 를 쓰면
    #    조회 구간이 9시간 어긋나 화면과 다른 캔들이 나간다 — 실제로 그렇게 짰다가
    #    옛 API 와 종가·저가가 달라져서 잡았다(2026-08-19).
    end = datetime.now(_KST).replace(tzinfo=None, second=0, microsecond=0)
    start = end - timedelta(days=days)

    async with db_session() as db:
        rows = await candle_rows(db, code[:32], _norm_market(market), start, end, limit, timeframe)

    return [
        Candle(
            at=r["execution_datetime"],
            open=_f(r["execution_open"]), close=_f(r["execution_close"]),
            low=_f(r["execution_min"]), high=_f(r["execution_max"]),
            ask_volume=_f(r["execution_ask_volume"]),
            bid_volume=_f(r["execution_bid_volume"]),
            non_volume=_f(r["execution_non_volume"]),
            volume=sum(float(r[k] or 0) for k in
                       ("execution_ask_volume", "execution_bid_volume", "execution_non_volume")),
        )
        for r in rows
    ]


@router.get("/{code}/executions", response_model=list[Execution], summary="최근 체결")
async def executions(
    code: str,
    market: str | None = Query(None),
    limit: int = Query(100, ge=1, le=_MAX_EXECUTIONS),
):
    code = code[:32]
    async with db_session() as db:
        is_coin = await _resolve_is_coin(db, code, _norm_market(market))
        table = await _resolve_source(db, "tick", code, "c" if is_coin else "s")
        if table is None:
            # ⚠️ 종목은 있는데 체결 테이블이 아직 없을 수 있다(수집 전). 그건 404 가 아니라
            #    "아직 아무것도 없음" 이므로 빈 목록이다.
            return []
        rows = (await db.execute(text(
            "SELECT execution_datetime, execution_price, execution_non_volume, "
            f"execution_ask_volume, execution_bid_volume FROM `tick`.`{table}` "
            "ORDER BY execution_datetime DESC LIMIT :limit"), {"limit": limit})).all()

    return [
        Execution(at=r.execution_datetime, price=_f(r.execution_price),
                  non_volume=_f(r.execution_non_volume),
                  ask_volume=_f(r.execution_ask_volume),
                  bid_volume=_f(r.execution_bid_volume))
        for r in rows
    ]
