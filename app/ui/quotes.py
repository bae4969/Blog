"""`/quotes` — 지수·환율 화면과 그 데이터 헬퍼.

주식 목록과 **다른 화면으로 뗀 이유**는 성격이 다르기 때문이다. `/stocks` 는 "개별 종목을
찾는" 화면이고(검색·페이저·구독 목록), 여기는 "시장 전체가 지금 어떤가"를 한눈에 보는
화면이다.

수집 대상은 코드가 아니라 **DB 가 정한다**(`23.stock_ticker` 와 같은 규약):

    KoreaInvest.quote_info             카탈로그 — 지수 522·환율 36 (주간 마스터 싱크)
    KoreaInvest.quote_last_rest_query  실제로 모으는 것. `quote_query` 가 곧 테이블명

시세는 종목과 **같은 `candle`·`tick` 스키마**에 접두사만 달리해 들어간다
(`iKOSPI`·`fKRWUSD`). 그래서 등락률·스파크라인 계산은 종목과 같은 모양이다.
"""

import logging
import re

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import text

from app.db.session import db_session
from app.ui.routes import _shell_ctx, templates
from app.ui.stocks import (
    _default_market,
    _latest_quotes,
    _level,
    _resolve_source,
    _SAFE_TABLE,
)

logger = logging.getLogger(__name__)
router = APIRouter()

#: 스파크라인에 실을 최대 점 개수. 환율은 하루 130점(10분봉)이라 그대로 두면 카드 폭에
#: 비해 과하다. 뒤에서부터 이만큼만 남긴다.
_SPARK_POINTS = 80

#: 화면에 쓸 지수 이름. `quote_info` 는 **업종 카탈로그** 기준이라 코스피 종합지수가
#: "종합" 으로 들어 있다(카탈로그로서는 맞는 이름이다). 여기 없으면 `quote_info` 이름으로
#: 폴백하므로, 수집 대상이 늘어도 화면에는 자동으로 뜬다.
_INDEX_LABEL = {
    "KOSPI": "코스피",
    "KOSDAQ": "코스닥",
    "KOSPI200": "코스피 200",
}

#: 환율 라벨 조립용 통화명. `quote_query` 가 `KRW`+통화코드 꼴이다.
#:
#: ⚠️ **여기 없는 통화는 `quote_info` 이름으로 폴백하는데, 그게 틀릴 수 있다.** 카탈로그는
#:    인도/인도네시아 이름이 서로 뒤바뀌어 있다(`FXINR` = "루피아/달러 인도네시아",
#:    `FXIDR` = "루피/달러 인도"). ISO 4217 로는 INR 이 인도 루피, IDR 이 인도네시아
#:    루피아다 — 코드가 맞고 이름이 틀렸다. 그래서 구독하는 통화는 여기 꼭 넣는다.
_CURRENCY_KR = {
    "KRW": "원", "USD": "달러", "JPY": "엔", "EUR": "유로", "CNY": "위안",
    "GBP": "파운드", "INR": "루피", "IDR": "루피아",
    "AUD": "호주달러", "CAD": "캐나다달러", "CHF": "프랑",
    "HKD": "홍콩달러", "TWD": "대만달러", "SGD": "싱가포르달러",
}

_SAFE_QUERY = re.compile(r"[A-Za-z0-9_]+")

_CATEGORY_LABEL = {
    "INDEX_KR": "국내지수",
    "INDEX_EX": "해외지수",
    "FX": "환율",
}


def _fx_label(quote_query: str) -> str | None:
    """`KRWUSD` → `원/달러`.

    ⚠️ `quote_info` 이름을 쓰면 **틀린다.** 크로스 환산 환율은 `quote_code` 가 환산에 쓰는
       재료라(`KRWEUR` 의 코드는 `FXEUR` = "달러/유로") 실제 저장값과 이름이 다르다.
    """
    if len(quote_query) != 6:
        return None
    base, quote = quote_query[:3], quote_query[3:]
    if base not in _CURRENCY_KR or quote not in _CURRENCY_KR:
        return None
    return f"{_CURRENCY_KR[base]}/{_CURRENCY_KR[quote]}"


def _quote_label(quote_query: str, query_type: str, name_kr: str | None) -> str:
    label = (_fx_label(quote_query) if query_type == "FX" else _INDEX_LABEL.get(quote_query))
    return label or name_kr or quote_query


async def _quote_meta(db, code: str) -> dict | None:
    """수집 중인 지수·환율 하나와 실제 캔들 테이블을 찾는다."""
    if not code or not _SAFE_QUERY.fullmatch(code):
        return None
    row = (await db.execute(text(
        "SELECT L.quote_query, L.query_type, I.quote_name_kr "
        "FROM KoreaInvest.quote_last_rest_query L "
        "JOIN KoreaInvest.quote_info I ON L.quote_code = I.quote_code "
        "WHERE L.quote_query = :code LIMIT 1"), {"code": code})).first()
    if row is None:
        return None
    quote_query, query_type, name_kr = row
    prefix = "f" if query_type == "FX" else "i"
    return {
        "code": quote_query,
        "name": _quote_label(quote_query, query_type, name_kr),
        "category": query_type,
        "category_label": _CATEGORY_LABEL.get(query_type, query_type),
        "prefix": prefix,
        "table": await _resolve_source(db, "candle", quote_query, prefix),
    }


async def _quote_rows(db) -> list[dict]:
    """수집 중인 지수·환율 전부. 카드 한 장 = 한 행.

    ⚠️ 등락률 기준일은 `CURDATE()` 가 아니라 **그 테이블의 마지막 캔들 날짜**다. 해외지수는
       `execution_datetime` 이 현지시각(ET)이라 KST 의 오늘로 자르면 어긋난다
       (`app.ui.stocks._heatmap_rows` 와 같은 이유).
    """
    rows = (await db.execute(text(
        "SELECT L.quote_query, L.query_type, I.quote_name_kr "
        "FROM KoreaInvest.quote_last_rest_query L "
        "JOIN KoreaInvest.quote_info I ON L.quote_code = I.quote_code "
        "ORDER BY FIELD(L.query_type, 'INDEX_KR', 'INDEX_EX', 'FX'), L.quote_query"))).all()
    if not rows:
        return []

    tables = {
        t for (t,) in (await db.execute(text(
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = 'candle' AND (TABLE_NAME LIKE 'i%' OR TABLE_NAME LIKE 'f%')"))).all()
        if _SAFE_TABLE.fullmatch(t)
    }

    picked: list[dict] = []
    for quote_query, query_type, name_kr in rows:
        if not quote_query or not _SAFE_QUERY.fullmatch(quote_query):
            continue
        is_fx = query_type == "FX"
        table = ("f" if is_fx else "i") + quote_query
        # 수집 대상에 막 추가돼 아직 테이블이 없을 수 있다 — 파티션은 ticker 가 만든다.
        if table not in tables:
            continue
        picked.append({
            "code": quote_query,
            "name": _quote_label(quote_query, query_type, name_kr),
            "category": query_type,
            "table": table,
        })
    if not picked:
        return []

    latest = "\nUNION ALL\n".join(
        f"SELECT '{p['code']}' AS code, "
        f"(SELECT execution_close FROM `candle`.`{p['table']}` "
        f" ORDER BY execution_datetime DESC LIMIT 1) AS price, "
        f"(SELECT execution_close FROM `candle`.`{p['table']}` WHERE execution_datetime < "
        f" (SELECT DATE(MAX(execution_datetime)) FROM `candle`.`{p['table']}`) "
        f" ORDER BY execution_datetime DESC LIMIT 1) AS prev_price, "
        f"(SELECT MAX(execution_datetime) FROM `candle`.`{p['table']}`) AS at "
        f"FROM DUAL"
        for p in picked
    )
    stat = {r[0]: r for r in (await db.execute(text(latest))).all()}

    series = "\nUNION ALL\n".join(
        f"SELECT '{p['code']}' AS code, execution_datetime AS at, execution_close AS close "
        f"FROM `candle`.`{p['table']}` WHERE execution_datetime >= "
        f"(SELECT DATE(MAX(execution_datetime)) FROM `candle`.`{p['table']}`)"
        for p in picked
    )
    spark: dict[str, list] = {}
    for code, at, close in (await db.execute(text(series + "\nORDER BY code, at"))).all():
        if close is not None:
            spark.setdefault(code, []).append(float(close))

    out: list[dict] = []
    for p in picked:
        row = stat.get(p["code"])
        if row is None or row[1] is None:
            continue
        price = float(row[1])
        prev_price = None if row[2] is None else float(row[2])
        out.append({
            "code": p["code"],
            "name": p["name"],
            "category": p["category"],
            "price": price,
            "prev_price": prev_price,
            # ⚠️ 수집이 2026-09-02 에 시작돼 **처음 하루는 직전 거래일이 없다.** 0% 로
            #    채우면 "보합"으로 읽히므로 없는 채로 내보내고 화면이 `-` 를 띄운다.
            "change_pct": None if not prev_price else (price / prev_price - 1) * 100,
            "at": row[3],
            "spark": spark.get(p["code"], [])[-_SPARK_POINTS:],
        })
    return out


@router.get("/quotes", response_class=HTMLResponse, include_in_schema=False)
async def quotes_index(request: Request):
    """지수·환율 + 종목 히트맵의 **껍데기**. 내용은 `/js/quotes.js` 가 API 로 채운다
    (`/api/v1/quotes`·`/api/v1/stocks/heatmap`).

    `/stocks` 와 같이 여기서는 데이터 쿼리를 돌리지 않는다 — 히트맵은 구독 종목 캔들
    테이블을 UNION ALL 로 훑으므로, 화면이 아직 안 쓰는데 매번 도는 일이 없게 한다.
    """
    async with db_session() as db:
        ctx = await _shell_ctx(request, db, _level(request))

    return templates.TemplateResponse(
        request,
        "quotes_index.html",
        {
            # `is_stock_page` 는 장식이 아니다 — layout 이 이걸로 좌상단 라벨("주식")과
            # body 클래스를 정한다. 지수·환율은 주식 계열 화면이라 같이 묶는다.
            **ctx, "is_stock_page": True, "hide_sidebar": True,
            "default_market": _default_market(),
        },
    )


@router.get("/quotes/view", response_class=HTMLResponse, include_in_schema=False)
async def quotes_show(request: Request):
    """지수·환율 상세 차트. 캔들은 화면이 뜬 뒤 공개 API에서 읽는다."""
    code = (request.query_params.get("code") or "").strip().upper()[:32]
    if not code:
        return RedirectResponse("/quotes", status_code=303)

    async with db_session() as db:
        item = await _quote_meta(db, code)
        if item is None or item["table"] is None:
            return RedirectResponse("/quotes", status_code=303)
        latest = (await _latest_quotes(db, [(item["code"], item["prefix"])])).get(item["code"])
        item["price"] = (latest or {}).get("close")
        item["prev_price"] = (latest or {}).get("prev_close")
        item["change_pct"] = (latest or {}).get("change_pct")
        ctx = await _shell_ctx(request, db, _level(request))

    return templates.TemplateResponse(
        request,
        "quotes_show.html",
        {**ctx, "is_stock_page": True, "hide_sidebar": True, "item": item},
    )
