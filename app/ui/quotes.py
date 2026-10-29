"""주식 대시보드의 지수·환율 데이터와 `/quotes/view` 상세 화면.

수집 대상은 코드가 아니라 **DB 가 정한다**(`23.stock_ticker` 와 같은 규약):

    KoreaInvest.quote_info             카탈로그 — 지수 522·환율 36 (주간 마스터 싱크)
    KoreaInvest.quote_last_rest_query  실제로 모으는 것. `quote_query` 가 곧 테이블명

시세는 종목과 **같은 `candle`·`tick` 스키마**에 접두사만 달리해 들어간다
(`iKOSPI`·`fKRWUSD`). 그래서 등락률·스파크라인 계산은 종목과 같은 모양이다.
"""

import json
import logging
import re
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import text

from app.db.session import db_session
from app.ui.routes import _shell_ctx, templates
from app.ui.stocks import (
    _ROLLING_PREFIXES,
    _change_base_sql,
    _day_stats,
    _latest_quotes,
    _prev_close_sql,
    _level,
    _resolve_source,
    _SAFE_TABLE,
)

logger = logging.getLogger(__name__)
router = APIRouter()

#: 스파크라인에 실을 최대 점 개수. 환율은 하루 130점(10분봉)이라 그대로 두면 카드 폭에
#: 비해 과하다. 뒤에서부터 이만큼만 남긴다.
_SPARK_POINTS = 80

# 홈 카드의 X축은 정규장 전체다. 한투 분봉은 각 시장의 현지시각이므로 KST/UTC 로
# 변환하지 않는다(미국·유럽의 서머타임에도 현지 개장·마감 시각은 같다).
# 한국·미국은 분류 공통, 세계지수는 현재 수집 중인 시장별로 지정한다.
# 정규장 기준이며 휴일별 조기 폐장 달력은 적용하지 않는다.
_INDEX_SESSIONS = {
    "INDEX_KR": (9 * 60, 15 * 60 + 30),
    "INDEX_EX": (9 * 60 + 30, 16 * 60),
    "JPNI225": (9 * 60, 15 * 60 + 30),
    "SHANG": (9 * 60 + 30, 15 * 60),
    "HKHS": (9 * 60 + 30, 16 * 60 + 10),  # 종가 경매 포함
    "TWWT": (9 * 60, 13 * 60 + 30),
    "INBOMBAY": (9 * 60 + 15, 15 * 60 + 30),
    "SX5E": (9 * 60, 17 * 60 + 30),
    "GRDAX": (9 * 60, 17 * 60 + 30),
    "GBFTSE": (8 * 60, 16 * 60 + 30),
}


def _spark_data(code: str, category: str, points: list[tuple[datetime, float]]) -> tuple[list[float], list[float]]:
    """종가와 X축 위치(개장 0~마감 1). 미래 가격을 채우지 않는다."""
    session = _INDEX_SESSIONS.get(category) or _INDEX_SESSIONS.get(code)
    if session is None:
        return [value for _, value in points[-_SPARK_POINTS:]], []

    # SENSEX 는 분봉 없이 KST 20시 종가 스냅샷 하나만 온다. 장중 선을 꾸미지 않고
    # 마감 위치에 점 하나를 놓는다. 분봉이 생기면 아래의 실제 시각 계산을 쓴다.
    if code == "INBOMBAY" and len(points) == 1 and points[0][0].hour == 20:
        return [points[0][1]], [1.0]

    opened, closed = session
    trading_points = [(at.hour * 60 + at.minute, value) for at, value in points
                      if opened <= at.hour * 60 + at.minute <= closed][-_SPARK_POINTS:]
    return ([value for _, value in trading_points],
            [(minute - opened) / (closed - opened) for minute, _ in trading_points])

#: 화면에 쓸 지수 이름. `quote_info` 는 **업종 카탈로그** 기준이라 코스피 종합지수가
#: "종합" 으로 들어 있다(카탈로그로서는 맞는 이름이다). 여기 없으면 `quote_info` 이름으로
#: 폴백하므로, 수집 대상이 늘어도 화면에는 자동으로 뜬다.
_INDEX_LABEL = {
    "KOSPI": "코스피",
    "KOSDAQ": "코스닥",
    "KOSPI200": "코스피 200",
    "JPNI225": "닛케이 225",
    "SHANG": "상해종합",
    "HKHS": "항셍",
    "TWWT": "대만 가권",
    "INBOMBAY": "인도 SENSEX",
    "SX5E": "유로스톡스 50",
    "GRDAX": "독일 DAX",
    "GBFTSE": "영국 FTSE 100",
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
    "INDEX_EX": "미국지수",
    "INDEX_WORLD": "세계지수",
    "FX": "환율",
}

#: `/stocks` 지수·환율 카드 표시 순서. 미지정 항목은 같은 분류 뒤에 코드순으로 둔다.
_QUOTE_DISPLAY_ORDER = {
    "INDEX_KR": ("KOSPI", "KOSPI200", "KOSDAQ"),
    "INDEX_EX": ("SPX", "COMP", "NDX"),
    "INDEX_WORLD": ("JPNI225", "SHANG", "HKHS", "TWWT", "INBOMBAY", "SX5E", "GRDAX", "GBFTSE"),
    "FX": ("KRWUSD", "KRWEUR", "KRWGBP", "KRWJPY", "KRWCNY", "KRWINR",
           "KRWAUD", "KRWCAD", "KRWCHF", "KRWHKD", "KRWSGD", "KRWTWD"),
}


# ── 주식 홈 지수·환율 카드 구성(2026-10-13) ──────────────────────────────
#
# 넓은 화면은 6장 한 줄이 세트 단위로 넘어가고, 모바일은 **앞 두 세트를 지수로, 마지막 세트를 환율로**
# 한 장씩 넘긴다(`quotes.js` renderQuotes). 그래서 세트는 셋, 한 세트 6장, 앞 둘은 지수·셋째는 환율이어야 한다.
# 관리자 화면(`/admin/quotes`)에서 고르고 순서를 바꾸며, `app_setting` 의 `quote_card_sets`(JSON)에 둔다.
# 설정이 없거나 깨졌으면 아래 기본값 — 예전 `quotes.js` 의 `CARD_SETS` 그대로다(동작 불변).
# 여기 없는 것은 수집만 하고 카드로는 안 띄운다.

CARD_SETS_DEFAULT: list[list[str]] = [
    ["KOSPI", "KOSDAQ", "SPX", "NDX", "JPNI225", "SX5E"],
    ["SHANG", "HKHS", "TWWT", "INBOMBAY", "GRDAX", "GBFTSE"],
    ["KRWUSD", "KRWEUR", "KRWGBP", "KRWJPY", "KRWCNY", "KRWINR"],
]
CARD_SET_SIZE = 6
#: 세트마다 고를 수 있는 분류 — 모바일 제약(앞 둘 지수, 마지막 환율).
CARD_SET_KINDS: list[tuple[str, ...]] = [("INDEX_KR", "INDEX_EX", "INDEX_WORLD")] * 2 + [("FX",)]
_CARD_KEY = "quote_card_sets"


def _card_shape_ok(sets) -> bool:
    return (isinstance(sets, list) and len(sets) == len(CARD_SETS_DEFAULT)
            and all(isinstance(s, list) and all(isinstance(c, str) and _SAFE_QUERY.fullmatch(c) for c in s)
                    for s in sets))


async def card_sets(db) -> list[list[str]]:
    """저장된 카드 구성. 없거나 모양이 깨졌으면 기본값. (구독이 끊긴 코드는 화면이 시세 없음으로 건너뛴다.)"""
    raw = (await db.execute(text("SELECT setting_value FROM app_setting WHERE setting_key = :k"),
                            {"k": _CARD_KEY})).scalar()
    try:
        sets = json.loads(raw) if raw else None
    except ValueError:
        sets = None
    return sets if _card_shape_ok(sets) else [list(s) for s in CARD_SETS_DEFAULT]


async def save_card_sets(db, sets: list[list[str]]) -> None:
    await db.execute(text(
        "INSERT INTO app_setting (setting_key, setting_value) VALUES (:k, :v) "
        "ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)"),
        {"k": _CARD_KEY, "v": json.dumps(sets)})
    await db.commit()


async def subscribed_quotes(db) -> list[dict]:
    """구독 중인(수집 대상) 지수·환율 — 카드로 고를 수 있는 것. 코드·이름·분류."""
    rows = (await db.execute(text(
        "SELECT L.quote_query, L.query_type, I.quote_name_kr "
        "FROM KoreaInvest.quote_last_rest_query L "
        "JOIN KoreaInvest.quote_info I ON L.quote_code = I.quote_code"))).all()
    out = [{"code": q, "name": _quote_label(q, t, n), "category": t}
           for q, t, n in rows if q and _SAFE_QUERY.fullmatch(q)]
    out.sort(key=_quote_sort_key)
    return out


def card_set_errors(sets, subscribed: dict[str, str]) -> dict[int, str]:
    """세트 번호 → 오류(화면이 그 세트 아래에 띄운다). 비면 저장해도 된다.
    `subscribed` = 코드 → 분류. 화면(`quote_cards_admin.js`)도 같은 규칙으로 먼저 검사한다."""
    if not _card_shape_ok(sets):
        return {0: "카드 구성 형식이 아닙니다"}
    errors: dict[int, str] = {}
    seen: set[str] = set()
    for i, codes in enumerate(sets):
        kinds = CARD_SET_KINDS[i]
        if len(codes) != CARD_SET_SIZE:
            errors[i] = f"카드를 {CARD_SET_SIZE}장 골라야 합니다(지금 {len(codes)}장)"
            continue
        for c in codes:
            if c not in subscribed:
                errors[i] = f"구독하지 않은 항목은 고를 수 없습니다: {c}"
                break
            if subscribed[c] not in kinds:
                errors[i] = ("이 세트는 환율만 고를 수 있습니다" if kinds == ("FX",)
                             else "이 세트는 지수만 고를 수 있습니다") + f": {c}"
                break
            if c in seen:
                errors[i] = f"다른 세트에 이미 있습니다: {c}"
                break
            seen.add(c)
    return errors


def _quote_sort_key(item: dict) -> tuple[int, int, str]:
    category = item["category"]
    codes = _QUOTE_DISPLAY_ORDER.get(category, ())
    try:
        rank = codes.index(item["code"])
    except ValueError:
        rank = len(codes)
    category_rank = {"INDEX_KR": 0, "INDEX_EX": 1, "INDEX_WORLD": 2, "FX": 3}.get(category, 4)
    return category_rank, rank, item["code"]


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

    ⚠️ 등락률 기준일은 `CURDATE()` 가 아니라 **그 테이블의 마지막 캔들 날짜**다. 미국·세계지수는
       `execution_datetime` 이 현지시각(ET)이라 KST 의 오늘로 자르면 어긋난다
       (`app.ui.stocks._heatmap_rows` 와 같은 이유). 환율은 24시간 전과 견주고 스파크라인도 24시간이다.
    """
    rows = (await db.execute(text(
        "SELECT L.quote_query, L.query_type, I.quote_name_kr "
        "FROM KoreaInvest.quote_last_rest_query L "
        "JOIN KoreaInvest.quote_info I ON L.quote_code = I.quote_code "
        "ORDER BY FIELD(L.query_type, 'INDEX_KR', 'INDEX_EX', 'INDEX_WORLD', 'FX'), L.quote_query"))).all()
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
        f"{_prev_close_sql(p['table'])} AS prev_price, "
        f"(SELECT MAX(execution_datetime) FROM `candle`.`{p['table']}`) AS at "
        f"FROM DUAL"
        for p in picked
    )
    stat = {r[0]: r for r in (await db.execute(text(latest))).all()}

    series = "\nUNION ALL\n".join(
        f"SELECT '{p['code']}' AS code, execution_datetime AS at, execution_close AS close "
        f"FROM `candle`.`{p['table']}` WHERE execution_datetime >= {_change_base_sql(p['table'])}"
        for p in picked
    )
    spark: dict[str, list[tuple[datetime, float]]] = {}
    for code, at, close in (await db.execute(text(series + "\nORDER BY code, at"))).all():
        if close is not None:
            spark.setdefault(code, []).append((at, float(close)))

    out: list[dict] = []
    for p in picked:
        row = stat.get(p["code"])
        if row is None or row[1] is None:
            continue
        price = float(row[1])
        prev_price = None if row[2] is None else float(row[2])
        spark_values, spark_x = _spark_data(p["code"], p["category"], spark.get(p["code"], []))
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
            "spark": spark_values,
            "spark_x": spark_x,
        })
    out.sort(key=_quote_sort_key)
    return out


@router.get("/quotes/view", response_class=HTMLResponse, include_in_schema=False)
async def quotes_show(request: Request):
    """지수·환율 상세 차트. 캔들은 화면이 뜬 뒤 공개 API에서 읽는다."""
    code = (request.query_params.get("code") or "").strip().upper()[:32]
    if not code:
        return RedirectResponse("/stocks", status_code=303)

    async with db_session() as db:
        item = await _quote_meta(db, code)
        if item is None or item["table"] is None:
            return RedirectResponse("/stocks", status_code=303)
        latest = (await _latest_quotes(db, [(item["code"], item["prefix"])])).get(item["code"])
        item["price"] = (latest or {}).get("close")
        item["prev_price"] = (latest or {}).get("prev_close")
        item["change_pct"] = (latest or {}).get("change_pct")
        item["rolling"] = item["prefix"] in _ROLLING_PREFIXES
        # 종목 상세와 같은 "시세" 칸 — 지수·환율엔 거래량·체결이 없어(0) 시·고·저와 52주 범위만 쓴다.
        # 액면분할이 없으니 보정 이벤트는 비운다.
        stats = await _day_stats(db, item["table"], [])
        ctx = await _shell_ctx(request, db, _level(request))

    return templates.TemplateResponse(
        request,
        "quotes_show.html",
        {**ctx, "is_stock_page": True, "hide_sidebar": True,
         "item": item, "stats": stats},
    )
