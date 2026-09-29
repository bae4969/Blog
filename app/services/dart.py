"""OpenDART 데이터 — `25.dart` 가 채우는 `Dart` 스키마를 읽는다(쓰기 권한은 없다).

화면(`stocks_show`)과 API(`/api/v1/stocks/{code}/…`)가 **같은 함수**를 쓴다 — 한쪽만 고치면
같은 종목의 지표가 두 곳에서 달라진다.

⚠️ 한국 **보통주**만 이어진다. `corp_info.stock_code` 에는 우선주(`005935`)·ETF·ETN 이 없다.
⚠️ `valuation` 뷰는 `stock_info.stock_price` 로 계산하는데 그 값은 **갱신이 늦다**(며칠 묵기도 한다).
   화면이 쓰는 최신 종가와의 비율로 다시 맞춘다 — 시가총액이 `가격 × 주식수` 라 비례한다.
"""

import re

from sqlalchemy import text

DART_VIEWER = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="

#: 지분 신고 — 공시의 절반 가까이가 이것이라(사외이사의 수백 주 매수까지) "주요" 에서 뺀다.
_HOLDING = ("임원ㆍ주요주주특정증권등", "주식등의대량보유상황보고서", "최대주주등소유주식변동신고서")
#: 증권 발행 서류 — 채권·파생결합증권 발행마다 쏟아진다. 어디에도 넣지 않고 "전체" 에서만 보인다.
_ISSUE = ("투자설명서", "일괄신고추가서류", "증권발행실적보고서")

#: 차트에 찍는 공시 — "주요" 는 삼성전자만 해도 1년 120건이라 봉마다 점이 붙는다. 주가에 직접 닿는 것만.
_KEY = ("사업보고서", "반기보고서", "분기보고서", "영업(잠정)실적", "매출액또는손익구조",
        "주요사항보고서", "현금ㆍ현물배당결정", "단일판매ㆍ공급계약")

KINDS = ("major", "holding", "all", "key")

_TAG = re.compile(r"^\[([^\]]+)\]\s*")


def classify(report_nm: str) -> str:
    """`holding`·`issue`·`major` 중 하나. SQL 조건(`_kind_sql`)과 같은 규칙이다."""
    if any(k in report_nm for k in _HOLDING):
        return "holding"
    if any(k in report_nm for k in _ISSUE):
        return "issue"
    return "major"


def split_tag(report_nm: str) -> tuple[str, str | None]:
    """`[기재정정]사업보고서` → `('사업보고서', '기재정정')`. 앞머리가 없으면 `None`."""
    m = _TAG.match(report_nm)
    return (report_nm[m.end():], m.group(1)) if m else (report_nm, None)


def _kind_sql(kind: str) -> tuple[str, dict]:
    if kind == "key":
        return ("AND (" + " OR ".join(f"report_nm LIKE :k{i}" for i in range(len(_KEY))) + ")",
                {f"k{i}": f"%{k}%" for i, k in enumerate(_KEY)})
    hold = [f"report_nm LIKE :h{i}" for i in range(len(_HOLDING))]
    issue = [f"report_nm LIKE :s{i}" for i in range(len(_ISSUE))]
    params = {f"h{i}": f"%{k}%" for i, k in enumerate(_HOLDING)}
    if kind == "holding":
        return "AND (" + " OR ".join(hold) + ")", params
    if kind == "major":
        params |= {f"s{i}": f"%{k}%" for i, k in enumerate(_ISSUE)}
        return "AND NOT (" + " OR ".join(hold + issue) + ")", params
    return "", {}


async def has_corp(db, code: str) -> bool:
    return (await db.execute(text("SELECT 1 FROM Dart.corp_info WHERE stock_code = :c LIMIT 1"),
                             {"c": code})).first() is not None


async def fundamentals(db, code: str, price: float | None) -> dict | None:
    """PER·PBR·배당. 이어지는 법인이 없거나 재무가 없으면 `None`.

    `price` 는 화면에 보이는 최신 종가 — 비우면 뷰의 값을 그대로 쓴다.
    """
    r = (await db.execute(text(
        "SELECT stock_price, bsns_year, quarter, fs_div, period_end, net_income_ttm, per, pbr, "
        "       dividend_year, net_income_controlling, per_controlling, dps_common, dividend_yield "
        "FROM Dart.valuation WHERE stock_code = :c LIMIT 1"), {"c": code})).first()
    if r is None:
        return None
    k = float(price) / float(r.stock_price) if price and r.stock_price else 1.0

    def scaled(v, mul=True):
        return None if v is None else (float(v) * k if mul else float(v) / k)

    return {
        "bsns_year": r.bsns_year, "quarter": r.quarter, "fs_div": r.fs_div, "period_end": r.period_end,
        "net_income_ttm": r.net_income_ttm, "per": scaled(r.per), "pbr": scaled(r.pbr),
        "dividend_year": r.dividend_year, "net_income_controlling": r.net_income_controlling,
        "per_controlling": scaled(r.per_controlling),
        "dps": None if r.dps_common is None else float(r.dps_common),
        "dividend_yield": scaled(r.dividend_yield, mul=False),
    }


async def disclosures(db, code: str, kind: str, page: int, size: int) -> tuple[int, list[dict]]:
    where, params = _kind_sql(kind)
    params |= {"c": code}
    total = (await db.execute(text(
        f"SELECT COUNT(*) FROM Dart.disclosure WHERE stock_code = :c {where}"), params)).scalar() or 0
    rows = (await db.execute(text(
        "SELECT rcept_no, rcept_dt, report_nm, flr_nm FROM Dart.disclosure "
        f"WHERE stock_code = :c {where} ORDER BY rcept_dt DESC, rcept_no DESC "
        "LIMIT :limit OFFSET :offset"),
        params | {"limit": size, "offset": (page - 1) * size})).all()
    items = []
    for r in rows:
        title, tag = split_tag(r.report_nm)
        items.append({"rcept_no": r.rcept_no, "date": r.rcept_dt, "title": title, "tag": tag,
                      "filer": r.flr_nm, "kind": classify(r.report_nm),
                      "url": DART_VIEWER + r.rcept_no})
    return total, items



async def recent_subscribed(db, limit: int) -> list[dict]:
    """구독 중인 종목(메인 화면의 순위·히트맵과 같은 범위)의 최근 **주요** 공시.

    ⚠️ 날짜로 먼저 자른다 — 없으면 구독 종목 1년치(약 2만 건)를 다 모아 정렬해 110ms 가 걸렸다.
       `idx_stock_code(stock_code, rcept_dt)` 를 범위로 타게 한다. DB 세션이 KST 라 `CURDATE()` 가 맞다.
    """
    where, params = _kind_sql("major")
    rows = (await db.execute(text(
        "SELECT d.rcept_no, d.rcept_dt, d.report_nm, d.stock_code, s.stock_name_kr "
        "FROM Dart.disclosure d JOIN KoreaInvest.stock_info s ON s.stock_code = d.stock_code "
        "WHERE d.stock_code IN (SELECT DISTINCT stock_code FROM KoreaInvest.stock_last_ws_query) "
        "  AND d.rcept_dt >= CURDATE() - INTERVAL 14 DAY "
        f"{where} ORDER BY d.rcept_dt DESC, d.rcept_no DESC LIMIT :limit"),
        params | {"limit": limit})).all()
    out = []
    for r in rows:
        title, tag = split_tag(r.report_nm)
        out.append({"code": r.stock_code, "name": r.stock_name_kr, "date": r.rcept_dt,
                    "title": title, "tag": tag})
    return out

_FIN = ("revenue", "operating_income", "net_income")


async def financials(db, code: str, limit: int) -> tuple[str, list[dict]] | None:
    """분기 실적 — 3개월 값과 전년 같은 분기 대비 증감률. 최근 `limit` 분기, 오래된 순.

    ⚠️ 원본(`fin_summary`)은 **연초부터의 누적**이다. 분기 값은 직전 분기 누적을 뺀다(4분기 = 연간 − 3분기).
       직전 분기가 없으면 그 분기는 비운다 — 누적을 3개월로 착각해 보여 주지 않는다.
    ⚠️ 연결·개별을 섞지 않는다. 최신 분기에 연결이 있으면 연결, 없으면 개별 하나로 간다(`valuation` 과 같다).
    """
    rows = (await db.execute(text(
        "SELECT f.bsns_year, f.quarter, f.fs_div, f.period_end, f.revenue_ytd, "
        "       f.operating_income_ytd, f.net_income_ytd "
        "FROM Dart.fin_summary f JOIN Dart.corp_info c ON c.corp_code = f.corp_code "
        "WHERE c.stock_code = :c ORDER BY f.bsns_year, f.quarter"), {"c": code})).all()
    if not rows:
        return None
    last = max((r.bsns_year, r.quarter) for r in rows)
    fs = "CFS" if any((r.bsns_year, r.quarter) == last and r.fs_div == "CFS" for r in rows) else "OFS"
    ytd = {(r.bsns_year, r.quarter): r for r in rows if r.fs_div == fs}

    def quarter_value(y, q, k):
        cur = ytd.get((y, q))
        cur = getattr(cur, k + "_ytd") if cur else None
        if cur is None or q == 1:
            return cur
        prev = ytd.get((y, q - 1))
        prev = getattr(prev, k + "_ytd") if prev else None
        return None if prev is None else cur - prev

    out = []
    for (y, q), r in sorted(ytd.items()):
        item = {"year": y, "quarter": q, "period_end": r.period_end}
        for k in _FIN:
            v, p = quarter_value(y, q, k), quarter_value(y - 1, q, k)
            item[k] = v
            # 기준이 0 이하(적자)면 증감률은 뜻이 없다 — 흑자전환 여부는 두 값으로 본다.
            item[k + "_yoy"] = (v - p) / p * 100 if v is not None and p and p > 0 else None
        out.append(item)
    return fs, out[-limit:]
