"""네이버 화면이 사용하는 KRX 금현물 시세. 원/g·거래소·종목을 확인하고 API 조회 간격을 지킨다."""

import asyncio
import logging
import math
from datetime import datetime, timedelta, timezone
from time import monotonic

import httpx

from app.services.invest_plan import GOLD_CODE

URL = f"https://polling.finance.naver.com/api/realtime/marketindex/metals/{GOLD_CODE}"
_KST = timezone(timedelta(hours=9))
_quote: dict | None = None
_next_fetch = 0.0
_interval = 30.0
_lock = asyncio.Lock()
logger = logging.getLogger(__name__)


def _number(value) -> float:
    number = float(str(value).replace(",", ""))
    if not math.isfinite(number):
        raise ValueError("유효하지 않은 금 시세")
    return number


def parse_quote(body: dict) -> tuple[dict, float]:
    if not isinstance(body, dict):
        raise ValueError("금 시세 응답이 객체가 아닙니다")
    row = next(q for q in body["datas"] if isinstance(q, dict) and q.get("reutersCode") == GOLD_CODE)
    if row["stockExchangeType"]["code"] != "KRX" or row["unit"] != "원/g":
        raise ValueError("KRX 원/g 시세가 아닙니다")
    price = _number(row.get("closePriceRaw") or row["closePrice"])
    previous = None
    if row.get("fluctuations") not in (None, "", "-"):
        previous = price - _number(row["fluctuations"])
    if price <= 0 or previous is not None and previous <= 0:
        raise ValueError("금 시세는 양수여야 합니다")
    at = datetime.fromisoformat(row["localTradedAt"])
    if at.tzinfo is None:
        raise ValueError("금 시세 기준시각에 시간대가 없습니다")
    interval = max(30.0, _number(body.get("pollingInterval", 30000)) / 1000)
    return {"close": price, "prev_close": previous,
            "change_pct": (price / previous - 1) * 100 if previous else None,
            "as_of": at.astimezone(_KST).replace(tzinfo=None), "source": "naver_krx_gold",
            "unit": "원/g", "quantity_unit": "g", "market_status": row.get("marketStatus"), "stale": False}, interval


async def _fetch() -> dict:
    async with httpx.AsyncClient(timeout=3.0) as client:
        response = await client.get(URL)
        response.raise_for_status()
        return response.json()


async def quote() -> dict:
    """30초와 서버 pollingInterval 중 긴 간격으로 공유 캐시. 실패하면 기준시각을 유지하고 지연 표시한다."""
    global _quote, _next_fetch, _interval
    if monotonic() < _next_fetch and _quote is not None:
        return dict(_quote)
    async with _lock:
        if monotonic() < _next_fetch and _quote is not None:
            return dict(_quote)
        try:
            fresh, interval = parse_quote(await _fetch())
        except (httpx.HTTPError, ValueError, KeyError, TypeError, StopIteration, OverflowError) as exc:
            _quote = {**(_quote or {"close": None, "prev_close": None, "change_pct": None, "as_of": None,
                                    "source": "naver_krx_gold", "unit": "원/g", "quantity_unit": "g"}), "stale": True}
            logger.warning("네이버 KRX 금현물 조회 실패: %s", type(exc).__name__)
        else:
            _quote, _interval = fresh, interval
        _next_fetch = monotonic() + _interval
        return dict(_quote)


async def add_quote(codes: list[str], quotes: dict) -> None:
    """금현물이 필요한 조회만 외부 시세를 요청한다."""
    if GOLD_CODE in codes:
        quotes[GOLD_CODE] = await quote()
