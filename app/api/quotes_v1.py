"""`/api/v1/quotes` — 지수·환율.

화면(`/quotes`)과 **같은 헬퍼**(`_quote_rows`)를 쓴다. 종목 API 와 같은 이유다 — 쿼리를
따로 짜면 등락률 기준일 같은 것이 한쪽에만 반영돼 두 곳이 조용히 갈라진다.

종목 API 와 마찬가지로 **공개 데이터**라 토큰을 요구하지 않는다.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, status

from app.db.session import db_session
from app.schemas.stock import Candle, QuoteOut
from app.ui.quotes import _quote_meta, _quote_rows
from app.ui.stocks import _fetch_candles, _KST, _TIMEFRAMES

router = APIRouter(prefix="/api/v1/quotes", tags=["stock"])

_MAX_CANDLES = 1000


@router.get("", response_model=list[QuoteOut], summary="지수·환율")
async def quotes():
    """수집 중인 지수·환율 전부. 국내지수 → 해외지수 → 환율 순.

    ⚠️ `at` 의 시간대가 종류마다 다르다 — 국내지수·환율은 KST, 해외지수는 **현지시각**
       이다(`23.stock_ticker` 가 한투 응답의 현지시각을 그대로 저장한다). 화면에 "몇 시
       기준"을 함께 띄울 때 이걸 KST 로 오해하면 안 된다.
    """
    async with db_session() as db:
        rows = await _quote_rows(db)
    return [QuoteOut(**r) for r in rows]


def _kst_naive(v: datetime) -> datetime:
    if v.tzinfo is not None:
        v = v.astimezone(_KST).replace(tzinfo=None)
    return v.replace(second=0, microsecond=0)


@router.get("/{code}/candles", response_model=list[Candle], summary="지수·환율 캔들")
async def candles(
    code: str,
    timeframe: str = Query("1h", description=f"{', '.join(_TIMEFRAMES)}"),
    limit: int = Query(500, ge=1, le=_MAX_CANDLES),
    days: int = Query(30, ge=1, le=3650),
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
):
    if timeframe not in _TIMEFRAMES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"timeframe 은 {_TIMEFRAMES} 중 하나여야 합니다")
    end = _kst_naive(end) if end else datetime.now(_KST).replace(tzinfo=None, second=0, microsecond=0)
    start = _kst_naive(start) if start else end - timedelta(days=days)
    if start >= end:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "start 는 end 보다 앞서야 합니다")

    async with db_session() as db:
        item = await _quote_meta(db, code[:32].upper())
        if item is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "수집 중인 지수·환율이 아닙니다")
        if item["table"] is None:
            return []
        rows = await _fetch_candles(
            db, item["table"], start, end, limit, timeframe,
            item["category"] == "INDEX_KR", [],
        )

    return [
        Candle(
            at=r["execution_datetime"],
            open=float(r["execution_open"]), close=float(r["execution_close"]),
            low=float(r["execution_min"]), high=float(r["execution_max"]),
            ask_volume=float(r["execution_ask_volume"] or 0),
            bid_volume=float(r["execution_bid_volume"] or 0),
            non_volume=float(r["execution_non_volume"] or 0),
            volume=sum(float(r[k] or 0) for k in
                       ("execution_ask_volume", "execution_bid_volume", "execution_non_volume")),
        )
        for r in rows
    ]
