"""주식 화면 — PHP `StockController` 를 옮기는 중.

지금 옮긴 것: 목록(`/stocks`)·검색 API(`/stocks/api/search`).
아직 PHP(`php-final` 태그)에만 있는 것: 상세·차트(`/stocks/view`)·백테스트 계열.

## 이 화면이 보는 데이터

`KoreaInvest.stock_info`·`Bithumb.coin_info` 가 종목 메타를, `candle` 스키마의 **종목별
테이블**(`s005930`·`cBTC` 꼴, 588개)이 시세를 든다. 목록에 나오는 것은 `stock_info` 전체가
아니라 **구독 중인 종목만**이다(`*_last_ws_query` 와 INNER JOIN) — 시세가 쌓이는 종목만
보여주기 위해서다.

## PHP 와 다르게 한 곳 — 최신 종가 조회

PHP 는 종목마다 `information_schema` 조회 + 종가 조회를 따로 돌리고(50종목이면 100 쿼리)
파일 캐시로 버텼다. 포팅본은 캐시가 없으므로 **두 번의 배치 쿼리로 묶었다**:
후보 테이블명을 한 번에 조회하고, 찾은 테이블들을 `UNION ALL` 로 한 번에 읽는다.
결과는 같고 쿼리 수만 100 → 2 로 준다.
"""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import bindparam, text

from app.db.session import db_session
from app.ui.routes import _int_arg, _shell_ctx, templates

logger = logging.getLogger(__name__)
router = APIRouter()

_KST = timezone(timedelta(hours=9))
_MARKETS = ("KR", "US", "COIN")
_KR_MARKETS = ("KOSPI", "KOSDAQ", "KONEX")
_US_MARKETS = ("NYSE", "NASDAQ", "AMEX")
_PER_PAGE = 50


def _default_market() -> str:
    """시장이 지정되지 않았을 때의 기본 탭.

    한국장이 열려 있을 만한 시간(평일 08~18시 KST)이면 KR, 아니면 US.
    PHP `getDefaultMarketByMarketHours` 와 같은 기준이다 — 정확한 장 시간이 아니라
    "지금 뭘 보고 싶을까"에 대한 어림이다.
    """
    now = datetime.now(_KST)
    return "KR" if now.isoweekday() <= 5 and 8 <= now.hour < 18 else "US"


def _norm_market(v: str | None) -> str:
    v = (v or "").strip().upper()
    return v if v in _MARKETS else ""


def _candle_candidates(code: str, prefix: str) -> list[str]:
    """`candle` 스키마에서 이 종목의 테이블이 될 수 있는 이름들.

    종목 코드에 `.`·`/` 가 들어가는 경우가 있어(해외 종목) 세 가지 표기를 모두 후보로 둔다.
    PHP `resolveCandleSource` 와 같다.
    """
    up = code.upper()
    return list(dict.fromkeys([
        prefix + up,
        prefix + up.replace(".", "_").replace("/", "_"),
        prefix + up.replace(".", "").replace("/", ""),
    ]))


async def _latest_closes(db, rows) -> dict[str, float]:
    """종목 코드 → 최신 종가. 없는 종목은 키가 없다.

    PHP 의 N+1 을 배치 두 번으로 바꾼 곳이다(모듈 docstring 참조).
    """
    if not rows:
        return {}

    # 후보 테이블명 → 종목코드 역인덱스
    want: dict[str, str] = {}
    for r in rows:
        prefix = "c" if (getattr(r, "stock_type", None) == "COIN" or getattr(r, "market", "") == "COIN") else "s"
        for cand in _candle_candidates(r.code, prefix):
            want.setdefault(cand, r.code)
    if not want:
        return {}

    found = (await db.execute(
        text("SELECT TABLE_NAME FROM information_schema.TABLES "
             "WHERE TABLE_SCHEMA = 'candle' AND TABLE_NAME IN :names")
        .bindparams(bindparam("names", expanding=True)),
        {"names": list(want)},
    )).all()
    if not found:
        return {}

    # 종목당 테이블 하나만 쓴다(PHP 도 LIMIT 1 로 하나만 고른다).
    picked: dict[str, str] = {}
    for (tbl,) in found:
        picked.setdefault(want[tbl], tbl)

    # 테이블명은 바인딩할 수 없어 문자열로 붙인다 — information_schema 가 돌려준 실제
    # 테이블명이라 임의 입력이 아니지만, 그래도 식별자 문법을 한 번 더 확인한다.
    parts = [
        f"SELECT '{code}' AS code, (SELECT execution_close FROM `candle`.`{tbl}` "
        f"ORDER BY execution_datetime DESC LIMIT 1) AS close_price"
        for code, tbl in picked.items()
        if tbl.replace("_", "").isalnum() and code.replace("_", "").replace(".", "").replace("/", "").isalnum()
    ]
    if not parts:
        return {}

    out: dict[str, float] = {}
    for code, close in (await db.execute(text(" UNION ALL ".join(parts)))).all():
        if close is not None:
            out[code] = float(close)
    return out


@router.get("/stocks", response_class=HTMLResponse, include_in_schema=False)
async def stocks_index(request: Request):
    """종목 목록. 구독 중인 종목만 시가총액 순으로 보여준다."""
    market = _norm_market(request.query_params.get("market")) or _default_market()
    search = (request.query_params.get("search") or "").strip()[:50]
    page = max(1, _int_arg(request, "page", 1))

    async with db_session() as db:
        total, rows = await _stock_page(db, market, search, page)
        total_pages = max(1, -(-total // _PER_PAGE))
        if page > total_pages:                       # PHP 와 같이 범위를 넘으면 마지막 페이지로
            page = total_pages
            total, rows = await _stock_page(db, market, search, page)

        closes = await _latest_closes(db, rows)
        stats = (await db.execute(text(
            "SELECT CASE WHEN si.stock_market IN :kr THEN 'KR' "
            "            WHEN si.stock_market IN :us THEN 'US' ELSE 'ETC' END AS grp, "
            "       CASE WHEN si.stock_market IN :kr THEN '한국' "
            "            WHEN si.stock_market IN :us THEN '미국' ELSE '기타' END AS label, "
            "       COUNT(*) AS cnt, SUM(si.stock_capitalization) AS cap "
            "FROM KoreaInvest.stock_info si "
            "INNER JOIN (SELECT DISTINCT stock_code FROM KoreaInvest.stock_last_ws_query) w "
            "  ON si.stock_code = w.stock_code "
            "GROUP BY grp, label "
            "UNION ALL "
            "SELECT 'COIN', '코인', COUNT(*), SUM(ci.coin_price * ci.coin_amount) "
            "FROM Bithumb.coin_info ci "
            "INNER JOIN (SELECT DISTINCT coin_code FROM Bithumb.coin_last_ws_query) c "
            "  ON ci.coin_code = c.coin_code "
            "ORDER BY FIELD(grp, 'KR', 'US', 'COIN', 'ETC')")
            .bindparams(bindparam("kr", expanding=True), bindparam("us", expanding=True)),
            {"kr": list(_KR_MARKETS), "us": list(_US_MARKETS)})).all()
        portfolios = (await db.execute(text(
            "SELECT portfolio_id, portfolio_name, ranking_score, ranking_grade "
            "FROM backtest_portfolio ORDER BY ranking_score DESC, updated_at DESC LIMIT 10"))).all()
        ctx = await _shell_ctx(request, db, _level(request))

    return templates.TemplateResponse(
        request,
        "stocks_index.html",
        {
            **ctx, "is_stock_page": True,
            "rows": rows, "closes": closes, "stats": stats, "portfolios": portfolios,
            "market": market, "markets": _MARKETS, "search": search,
            "page": page, "total": total, "total_pages": total_pages,
        },
    )


def _level(request: Request) -> int:
    from app.ui.routes import _user_level
    return _user_level(getattr(request.state, "user", None))


async def _stock_page(db, market: str, search: str, page: int):
    """(전체 건수, 해당 페이지 행). 코인과 주식은 테이블이 달라 쿼리를 나눈다."""
    params: dict = {"limit": _PER_PAGE, "offset": (page - 1) * _PER_PAGE}
    where: list[str] = []

    if market == "COIN":
        src = ("Bithumb.coin_info ci INNER JOIN (SELECT DISTINCT coin_code "
               "FROM Bithumb.coin_last_ws_query) w ON ci.coin_code = w.coin_code")
        cols = ("ci.coin_code AS code, ci.coin_name_kr AS name_kr, ci.coin_name_en AS name_en, "
                "'COIN' AS market, 'COIN' AS stock_type, ci.coin_price AS price, "
                "ci.coin_price * ci.coin_amount AS cap")
        order, code_col = "cap DESC", "ci.coin_code"
        name_cols = ("ci.coin_name_kr", "ci.coin_name_en")
    else:
        src = ("KoreaInvest.stock_info si INNER JOIN (SELECT DISTINCT stock_code "
               "FROM KoreaInvest.stock_last_ws_query) w ON si.stock_code = w.stock_code")
        cols = ("si.stock_code AS code, si.stock_name_kr AS name_kr, si.stock_name_en AS name_en, "
                "si.stock_market AS market, si.stock_type AS stock_type, "
                "si.stock_price AS price, si.stock_capitalization AS cap")
        order, code_col = "si.stock_capitalization DESC", "si.stock_code"
        name_cols = ("si.stock_name_kr", "si.stock_name_en")
        if market in ("KR", "US"):
            ms = _KR_MARKETS if market == "KR" else _US_MARKETS
            where.append(f"si.stock_market IN ({', '.join(repr(m) for m in ms)})")

    if search:
        where.append("(" + " OR ".join([f"{code_col} LIKE :q"] + [f"{c} LIKE :q" for c in name_cols]) + ")")
        params["q"] = f"%{search}%"

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    total = (await db.execute(text(f"SELECT COUNT(*) FROM {src} {where_sql}"), params)).scalar() or 0
    rows = (await db.execute(text(
        f"SELECT {cols} FROM {src} {where_sql} ORDER BY {order} LIMIT :limit OFFSET :offset"), params)).all()
    return int(total), rows


@router.get("/stocks/api/search", include_in_schema=False)
async def stocks_api_search(request: Request):
    """종목 검색 JSON. 차트 화면의 종목 선택 콤보박스가 쓴다."""
    search = (request.query_params.get("q") or "").strip()[:50]
    market = _norm_market(request.query_params.get("market"))
    limit = min(100, max(1, _int_arg(request, "limit", 20)))

    async with db_session() as db:
        _, rows = await _stock_page(db, market or "", search, 1)

    data = [
        {
            "stock_code": r.code,
            "stock_name_kr": r.name_kr,
            "stock_name_en": r.name_en,
            "stock_market": r.market,
            "stock_price": float(r.price) if r.price is not None else None,
        }
        for r in rows[:limit]
    ]
    return JSONResponse({"success": True, "data": data, "count": len(data)})
