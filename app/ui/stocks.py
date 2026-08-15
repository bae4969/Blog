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
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
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
            **ctx, "is_stock_page": True, "hide_sidebar": True,
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
                "ci.coin_price * ci.coin_amount AS cap, ci.coin_amount AS quantity")
        order, code_col = "cap DESC", "ci.coin_code"
        name_cols = ("ci.coin_name_kr", "ci.coin_name_en")
    else:
        src = ("KoreaInvest.stock_info si INNER JOIN (SELECT DISTINCT stock_code "
               "FROM KoreaInvest.stock_last_ws_query) w ON si.stock_code = w.stock_code")
        cols = ("si.stock_code AS code, si.stock_name_kr AS name_kr, si.stock_name_en AS name_en, "
                "si.stock_market AS market, si.stock_type AS stock_type, "
                "si.stock_price AS price, si.stock_capitalization AS cap, si.stock_count AS quantity")
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


# ---------------------------------------------------------------------------
# 차트 — 캔들 파이프라인
#
# 순서를 지켜야 한다: 정규장 필터 → 분할보정 → 타임프레임 집계. 집계를 먼저 하면
# 보정계수가 그룹 경계에서 뭉개지고, 필터를 나중에 하면 장외 분봉이 그룹에 섞인다.
# PHP `fetchCandlesWithExpansion` 과 같은 순서다.
# ---------------------------------------------------------------------------

_MIN_RE = re.compile(r"^(\d+)m$")
_HOUR_RE = re.compile(r"^(\d+)h$")
_TIMEFRAMES = ("raw", "10m", "30m", "1h", "3h", "6h", "1d", "1w", "1M")


def _num(v):
    """DB 의 double 을 JSON 숫자로. 정수면 정수로 찍어 PHP 응답과 모양을 맞춘다."""
    if v is None:
        return None
    f = float(v)
    return int(f) if f.is_integer() else f


def _is_sub_daily(tf: str) -> bool:
    """분봉·시간봉이면 True. 일봉 이상(1d/1w/1M)은 False."""
    return bool(_MIN_RE.match(tf) or _HOUR_RE.match(tf))


def _filter_regular_hours(rows: list) -> list:
    """KR 정규장(평일 9:00~15:30)만 남긴다. 일중 봉에만 쓴다."""
    out = []
    for r in rows:
        dt = r["execution_datetime"]
        if dt.isoweekday() > 5:
            continue
        if dt.hour < 9 or dt.hour > 15 or (dt.hour == 15 and dt.minute > 30):
            continue
        out.append(r)
    return out


def _adjustment_factor(events: list, dt: datetime) -> float:
    """이 캔들 시점의 분할 보정계수 — 시점 **이후**에 일어난 이벤트만 누적한다."""
    factor = 1.0
    for ev in events:
        if dt.date() < ev["event_date"]:
            factor *= ev["ratio_from"] / ev["ratio_to"]
    return factor


def _apply_split_adjustment(rows: list, events: list) -> list:
    """분할·병합 소급 보정. 가격은 ×factor, 거래량은 ÷factor, 거래대금은 그대로.

    거래대금을 건드리지 않는 것은 그게 **당시 실제로 오간 돈**이기 때문이다(PHP 와 같다).
    """
    if not events or not rows:
        return rows
    for r in rows:
        f = _adjustment_factor(events, r["execution_datetime"])
        if abs(f - 1.0) < 1e-12:
            continue
        inv = 1.0 / f
        for k in ("execution_open", "execution_close", "execution_min", "execution_max"):
            r[k] *= f
        for k in ("execution_non_volume", "execution_ask_volume", "execution_bid_volume"):
            r[k] *= inv
    return rows


def _group_key(dt: datetime, tf: str):
    """집계 버킷 키. 분·시간은 내림 정렬한 구간, 주는 ISO 주차(연 경계가 정확하다)."""
    m = _MIN_RE.match(tf)
    if m and int(m.group(1)) > 0:
        step = int(m.group(1))
        return dt.replace(minute=dt.minute // step * step, second=0, microsecond=0)
    h = _HOUR_RE.match(tf)
    if h and int(h.group(1)) > 0:
        step = int(h.group(1))
        return dt.replace(hour=dt.hour // step * step, minute=0, second=0, microsecond=0)
    if tf == "1d":
        return dt.date()
    if tf == "1w":
        return dt.isocalendar()[:2]
    if tf == "1M":
        return (dt.year, dt.month)
    return dt


def _merge_candles(group: list) -> dict:
    """한 버킷을 캔들 하나로. 시가=첫 봉, 종가=끝 봉, 고저는 극값, 나머지는 합."""
    return {
        # 버킷 시작 시각이 아니라 **그 버킷의 첫 봉 시각**이다(PHP 와 같다).
        "execution_datetime": group[0]["execution_datetime"],
        "execution_open": group[0]["execution_open"],
        "execution_close": group[-1]["execution_close"],
        "execution_min": min(r["execution_min"] for r in group),
        "execution_max": max(r["execution_max"] for r in group),
        **{
            k: sum(r[k] for r in group)
            for k in ("execution_non_volume", "execution_ask_volume", "execution_bid_volume",
                      "execution_non_amount", "execution_ask_amount", "execution_bid_amount")
        },
    }


def _aggregate(rows: list, tf: str) -> list:
    """연속한 같은 키끼리 묶는다. `10m`·`raw` 는 원본이 이미 10분봉이라 그대로 둔다."""
    if not rows or tf in ("10m", "raw"):
        return rows
    out, cur_key, group = [], None, []
    for r in rows:
        key = _group_key(r["execution_datetime"], tf)
        if key != cur_key:
            if group:
                out.append(_merge_candles(group))
            cur_key, group = key, []
        group.append(r)
    if group:
        out.append(_merge_candles(group))
    return out


def _expand_start(start: datetime, tf: str, is_kr: bool) -> datetime:
    """limit 을 못 채웠을 때 조회 시작일을 몇 영업일 더 뒤로 민다.

    타임프레임마다 하루에 담기는 봉 수가 달라 밀 폭이 다르다 — KR 정규장은 6.5시간,
    US 는 프리마켓 포함 16시간이라 같은 봉 수를 채우는 데 KR 이 날짜를 더 먹는다.
    """
    if _MIN_RE.match(tf):
        days = 12 if is_kr else 5
    elif _HOUR_RE.match(tf):
        days = 10 if is_kr else 4
    else:
        days = {"1d": 60, "1w": 300, "1M": 1260}.get(tf, 12 if is_kr else 5)

    moved = 0
    while moved < days:
        start -= timedelta(days=1)
        if start.isoweekday() <= 5:
            moved += 1
    return start.replace(hour=9 if is_kr else 4, minute=0, second=0, microsecond=0)


async def _resolve_source(db, schema: str, code: str, prefix: str) -> str | None:
    """`candle`·`tick` 스키마에서 이 종목의 실제 테이블명. 없으면 None."""
    cands = _candle_candidates(code, prefix)
    row = (await db.execute(
        text("SELECT TABLE_NAME FROM information_schema.TABLES "
             "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME IN :names LIMIT 1")
        .bindparams(bindparam("names", expanding=True)),
        {"schema": schema, "names": cands},
    )).first()
    if not row:
        return None
    tbl = row[0]
    # 테이블명은 바인딩할 수 없어 문자열로 붙는다. information_schema 가 돌려준 값이지만
    # 식별자 문법을 한 번 더 확인하고 쓴다.
    return tbl if re.fullmatch(r"[A-Za-z0-9_]+", tbl) else None


async def _resolve_is_coin(db, code: str, market: str) -> bool:
    """코인인지 판별. market 힌트가 있으면 그걸 믿고, 없으면 주식을 우선한다.

    주식과 코인의 코드가 겹치는 경우가 있어 `stock_info` 존재 여부를 먼저 본다.
    """
    if market == "COIN":
        return True
    if market:
        return False
    exists = (await db.execute(
        text("SELECT 1 FROM KoreaInvest.stock_info WHERE stock_code = :c LIMIT 1"),
        {"c": code})).first()
    if exists:
        return False
    return bool((await db.execute(
        text("SELECT 1 FROM Bithumb.coin_info WHERE coin_code = :c LIMIT 1"),
        {"c": code})).first())


async def _split_events(db, code: str, market: str) -> list:
    rows = (await db.execute(
        text("SELECT event_date, ratio_from, ratio_to FROM stock_split_events "
             "WHERE stock_code = :c AND market = :m ORDER BY event_date ASC"),
        {"c": code, "m": market})).all()
    return [{"event_date": r.event_date, "ratio_from": int(r.ratio_from),
             "ratio_to": int(r.ratio_to)} for r in rows]


_CANDLE_COLS = ("execution_datetime, execution_open, execution_close, execution_min, execution_max, "
                "execution_non_volume, execution_ask_volume, execution_bid_volume, "
                "execution_non_amount, execution_ask_amount, execution_bid_amount")


async def _fetch_candles(db, table: str, start: datetime, end: datetime, limit: int,
                         tf: str, is_kr: bool, events: list) -> list:
    """범위를 넓혀 가며 limit 만큼 캔들을 모은다(최대 5회 확장).

    ⚠️ PHP 는 gzip 파일 캐시 때문에 **하루씩 끊어** 조회했지만, 포팅본은 캐시가 없으므로
       한 번의 범위 조회로 바꿨다. 결과는 같고 쿼리 수만 준다.
    """
    cur_start, prev_count = start, 0

    for attempt in range(6):
        rows = [dict(r._mapping) for r in (await db.execute(
            text(f"SELECT {_CANDLE_COLS} FROM `candle`.`{table}` "
                 "WHERE execution_datetime BETWEEN :s AND :e ORDER BY execution_datetime ASC"),
            {"s": cur_start, "e": end})).all()]

        if is_kr and _is_sub_daily(tf):
            rows = _filter_regular_hours(rows)
        rows = _aggregate(_apply_split_adjustment(rows, events), tf)

        if len(rows) >= limit:
            return rows[-limit:]
        # 넓혀도 새 캔들이 안 나오면 그 종목엔 더 없는 것이다 — 멈춘다.
        if attempt > 0 and len(rows) <= prev_count:
            return rows
        prev_count = len(rows)
        cur_start = _expand_start(cur_start, tf, is_kr)

    return rows


def _parse_dt(v: str | None, default: datetime) -> datetime:
    """`YYYY-MM-DD HH:MM:SS` 를 받는다. 초는 버린다(PHP 도 분 단위로 정규화했다)."""
    if not v:
        return default
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(v.strip()[:19], fmt).replace(second=0, microsecond=0)
        except ValueError:
            continue
    return default


@router.get("/stocks/api/candle", include_in_schema=False)
async def stocks_api_candle(request: Request):
    """차트용 캔들 JSON. 화면이 그린 뒤 비동기로 부른다."""
    code = (request.query_params.get("code") or "").strip()[:32]
    if not code:
        return JSONResponse({"error": "Stock code is required"}, status_code=400)

    now = datetime.now(_KST).replace(tzinfo=None, second=0, microsecond=0)
    start = _parse_dt(request.query_params.get("start"), now - timedelta(days=30))
    end = _parse_dt(request.query_params.get("end"), now)
    limit = min(1000, max(1, _int_arg(request, "limit", 500)))
    tf = (request.query_params.get("timeframe") or "1h").strip()
    if tf not in _TIMEFRAMES:
        tf = "1h"
    market = _norm_market(request.query_params.get("market"))

    async with db_session() as db:
        is_coin = await _resolve_is_coin(db, code, market)
        table = await _resolve_source(db, "candle", code, "c" if is_coin else "s")
        if table is None:
            return JSONResponse({"success": True, "data": [], "count": 0})

        events = await _split_events(db, code, "COIN" if is_coin else (market or "KR"))
        is_kr = not is_coin and market in ("KR", "")
        rows = await _fetch_candles(db, table, start, end, limit, tf, is_kr, events)

    data = [
        {k: (v.strftime("%Y-%m-%d %H:%M:%S") if k == "execution_datetime" else _num(v))
         for k, v in r.items()}
        for r in rows
    ]
    return JSONResponse({"success": True, "data": data, "count": len(data)},
                        headers={"Cache-Control": "private, max-age=60"})


@router.get("/stocks/api/executions", include_in_schema=False)
async def stocks_api_executions(request: Request):
    """최근 체결 JSON. `tick` 스키마의 종목별 테이블을 최신순으로 읽는다."""
    code = (request.query_params.get("code") or "").strip()[:32]
    if not code:
        return JSONResponse({"error": "Stock code is required"}, status_code=400)

    limit = min(200, max(1, _int_arg(request, "limit", 100)))
    market = _norm_market(request.query_params.get("market"))

    async with db_session() as db:
        is_coin = await _resolve_is_coin(db, code, market)
        table = await _resolve_source(db, "tick", code, "c" if is_coin else "s")
        if table is None:
            return JSONResponse({"success": True, "data": [], "count": 0})
        rows = (await db.execute(text(
            "SELECT execution_datetime, execution_price, execution_non_volume, "
            f"execution_ask_volume, execution_bid_volume FROM `tick`.`{table}` "
            "ORDER BY execution_datetime DESC LIMIT :limit"), {"limit": limit})).all()

    data = [
        {"execution_datetime": r.execution_datetime.strftime("%Y-%m-%d %H:%M:%S"),
         "execution_price": _num(r.execution_price),
         "execution_non_volume": _num(r.execution_non_volume),
         "execution_ask_volume": _num(r.execution_ask_volume),
         "execution_bid_volume": _num(r.execution_bid_volume)}
        for r in rows
    ]
    return JSONResponse({"success": True, "data": data, "count": len(data)},
                        headers={"Cache-Control": "private, max-age=10"})


@router.get("/stocks/view", response_class=HTMLResponse, include_in_schema=False)
async def stocks_show(request: Request):
    """종목 상세. 캔들·체결은 싣지 않고 화면이 뜬 뒤 API 로 채운다(PHP 와 같다)."""
    code = (request.query_params.get("code") or "").strip()[:32]
    if not code:
        return RedirectResponse("/stocks", status_code=303)
    market = _norm_market(request.query_params.get("market"))

    async with db_session() as db:
        stock = None
        if market == "COIN":
            stock = await _coin_by_code(db, code)
        if stock is None:
            stock = (await db.execute(
                text("SELECT stock_code, stock_name_kr, stock_name_en, stock_market, stock_type, "
                     "stock_price, stock_capitalization, stock_count, stock_update "
                     "FROM KoreaInvest.stock_info WHERE stock_code = :c"), {"c": code})).first()
        if stock is None and market != "COIN":
            stock = await _coin_by_code(db, code)
        if stock is None:
            return RedirectResponse("/stocks", status_code=303)

        stock = dict(stock._mapping) if hasattr(stock, "_mapping") else dict(stock)
        is_coin = stock["stock_type"] == "COIN"
        table = await _resolve_source(db, "candle", code, "c" if is_coin else "s")
        if table:
            # stock_info 의 현재가는 갱신이 늦다 — 캔들의 최신 종가로 덮는다(PHP 와 같다).
            close = (await db.execute(text(
                f"SELECT execution_close FROM `candle`.`{table}` "
                "ORDER BY execution_datetime DESC LIMIT 1"))).scalar()
            if close is not None:
                stock["stock_price"] = float(close)
        ctx = await _shell_ctx(request, db, _level(request))

    return templates.TemplateResponse(
        request, "stocks_show.html",
        {**ctx, "is_stock_page": True, "hide_sidebar": True,
         "stock": stock, "is_coin": is_coin,
         "is_us": stock["stock_market"] in _US_MARKETS},
    )


async def _coin_by_code(db, code: str):
    """코인을 주식과 같은 컬럼 이름으로 돌려준다 — 화면이 한 벌만 알면 되게."""
    return (await db.execute(text(
        "SELECT coin_code AS stock_code, coin_name_kr AS stock_name_kr, "
        "coin_name_en AS stock_name_en, 'COIN' AS stock_market, 'COIN' AS stock_type, "
        "coin_price AS stock_price, coin_price * coin_amount AS stock_capitalization, "
        "coin_amount AS stock_count, coin_update AS stock_update "
        "FROM Bithumb.coin_info WHERE coin_code = :c"), {"c": code})).first()


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
