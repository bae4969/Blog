"""`/api/v1/quotes` — 지수·환율.

화면(`/quotes`)과 **같은 헬퍼**(`_quote_rows`)를 쓴다. 종목 API 와 같은 이유다 — 쿼리를
따로 짜면 등락률 기준일 같은 것이 한쪽에만 반영돼 두 곳이 조용히 갈라진다.

종목 API 와 마찬가지로 **공개 데이터**라 토큰을 요구하지 않는다.
"""

from fastapi import APIRouter

from app.db.session import db_session
from app.schemas.stock import QuoteOut
from app.ui.quotes import _quote_rows

router = APIRouter(prefix="/api/v1/quotes", tags=["stock"])


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
