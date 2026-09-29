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

KINDS = ("major", "holding", "all")

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
