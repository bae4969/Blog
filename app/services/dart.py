"""OpenDART 데이터 — `25.dart` 가 채우는 `Dart` 스키마를 읽는다(쓰기 권한은 없다).

화면(`stocks_show`)과 API(`/api/v1/stocks/{code}/…`)가 **같은 함수**를 쓴다 — 한쪽만 고치면
같은 종목의 지표가 두 곳에서 달라진다.

⚠️ 한국 **보통주**만 이어진다. `corp_info.stock_code` 에는 우선주(`005935`)·ETF·ETN 이 없다.
⚠️ `valuation` 뷰는 `stock_info.stock_price` 로 계산하는데 그 값은 **갱신이 늦다**(며칠 묵기도 한다).
   화면이 쓰는 최신 종가와의 비율로 다시 맞춘다 — 시가총액이 `가격 × 주식수` 라 비례한다.
"""

import re
from datetime import date, datetime, time, timedelta

from sqlalchemy import text

DART_VIEWER = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="

#: 공시 분류 규칙 — (원문에 들어 있는 글자, 분류, 쉬운 제목). **위에서부터 처음 맞는 것**이 이긴다.
#: 법정 서식 이름(`주요사항보고서(자기주식취득결정)`)은 아무도 안 읽는다 — 무슨 일인지를 한눈에 보이게 바꾼다.
#: 2026-09-29 기준 상장사 공시 상위 90종을 보고 만들었다. 모르는 서식은 `other` 로 원문 그대로 보인다.
#: ⚠️ 순서가 뜻이다. 더 긴(구체적인) 글자를 앞에 둔다 — `배당을위한주주명부폐쇄` 가 `배당결정` 보다,
#:    `자기주식취득신탁` 이 `자기주식취득` 보다 앞이다.
RULES: tuple[tuple[str, str, str], ...] = (
    # 지분 신고 — 공시의 절반 가까이(사외이사의 수백 주 매수까지). "주요" 에서 뺀다.
    ("임원ㆍ주요주주특정증권등거래계획", "holding", "임원·주요주주 거래 계획"),
    ("임원ㆍ주요주주특정증권등", "holding", "임원·주요주주 지분 변동"),
    ("주식등의대량보유상황보고서", "holding", "대량보유(5%) 변동"),
    ("최대주주등소유주식변동신고서", "holding", "최대주주 지분 변동"),
    # 증권 발행 서류 — 채권·파생결합증권 발행마다 쏟아진다. "전체" 에서만.
    ("투자설명서", "issue", "투자설명서"),
    ("일괄신고", "issue", "증권 발행 서류"),
    ("증권발행실적보고서", "issue", "증권 발행 실적"),
    ("증권신고서", "issue", "증권신고서"),
    ("발행결과", "issue", "증권 발행 결과"),
    ("소액공모", "issue", "소액공모 서류"),
    # 행정 — 주총 소집·명부 폐쇄 같은 절차 안내. "주요" 에서 빼고 "전체" 에서 흐리게.
    ("배당을위한주주명부폐쇄", "admin", "배당 기준일 설정"),
    ("주주명부폐쇄", "admin", "주주명부 기준일 설정"),
    ("주주총회소집", "admin", "주주총회 소집"),
    ("의결권대리행사권유", "admin", "의결권 위임 권유"),
    ("주주총회집중일", "admin", "주총 집중일 개최 사유"),
    ("대규모기업집단현황", "admin", "기업집단 현황"),
    ("지급수단별ㆍ지급기간별", "admin", "하도급 대금 지급 현황"),
    ("기업지배구조보고서", "admin", "지배구조 보고서"),
    ("동일인등출자계열회사", "admin", "계열사 거래"),
    ("특수관계인", "admin", "특수관계인 거래"),
    ("지속가능경영보고서", "admin", "지속가능경영 보고서"),
    ("결산실적공시예고", "admin", "실적 발표 예고"),
    ("신탁계약에의한취득상황", "admin", "자사주 신탁 취득 현황"),
    ("독립이사", "admin", "사외이사 선임·퇴임"),
    ("사외이사", "admin", "사외이사 선임·퇴임"),
    ("주식매수선택권", "admin", "스톡옵션 부여"),
    ("소속부변경", "admin", "소속부 변경"),
    ("본점소재지변경", "admin", "본점 이전"),
    ("기타시장안내", "admin", "시장 안내"),
    # 실적·정기보고서
    ("영업(잠정)실적", "earnings", "잠정 실적 발표"),
    ("매출액또는손익구조", "earnings", "실적 크게 변동"),
    ("사업보고서", "periodic", "사업보고서"),
    ("반기보고서", "periodic", "반기보고서"),
    ("분기보고서", "periodic", "분기보고서"),
    ("감사보고서제출", "periodic", "감사보고서 제출"),
    # 배당
    ("현금ㆍ현물배당결정", "dividend", "배당 결정"),
    ("무상증자결정", "dividend", "무상증자 결정"),
    # 자사주
    ("자기주식취득신탁계약해지", "buyback", "자사주 신탁 해지"),
    ("자기주식취득신탁계약체결", "buyback", "자사주 신탁 체결"),
    ("신탁계약해지결과", "buyback", "자사주 신탁 해지 완료"),
    ("자기주식취득결과", "buyback", "자사주 취득 완료"),
    ("자기주식처분결과", "buyback", "자사주 처분 완료"),
    ("자기주식취득결정", "buyback", "자사주 취득 결정"),
    ("자기주식처분결정", "buyback", "자사주 처분 결정"),
    ("주식소각결정", "buyback", "주식 소각 결정"),
    # 자금 조달·자본 변동
    ("유상증자결정", "financing", "유상증자 결정"),
    ("자기전환사채매도", "financing", "보유 전환사채 매도"),
    ("자기전환사채만기전취득", "financing", "전환사채 조기 취득"),
    ("만기전사채취득", "financing", "사채 조기 취득"),
    ("전환사채권발행결정", "financing", "전환사채(CB) 발행"),
    ("신주인수권부사채권발행결정", "financing", "신주인수권부사채(BW) 발행"),
    ("교환사채권발행결정", "financing", "교환사채(EB) 발행"),
    ("전환청구권행사", "financing", "전환사채 주식 전환"),
    ("전환가액의조정", "financing", "전환가액 조정"),
    ("감자결정", "financing", "감자 결정"),
    ("주식병합결정", "financing", "주식 병합 결정"),
    ("주식분할결정", "financing", "주식 분할 결정"),
    ("단기차입금증가", "financing", "단기 차입 증가"),
    ("자금차입", "financing", "자금 차입"),
    # 계약
    ("단일판매ㆍ공급계약해지", "contract", "공급 계약 해지"),
    ("단일판매ㆍ공급계약", "contract", "공급 계약 체결"),
    # 투자·M&A
    ("타법인주식및출자증권처분", "mna", "타 회사 지분 처분"),
    ("타법인주식및출자증권", "mna", "타 회사 지분 취득"),
    ("회사합병결정", "mna", "합병 결정"),
    ("회사분할합병결정", "mna", "분할합병 결정"),
    ("회사분할결정", "mna", "회사 분할 결정"),
    ("영업양수", "mna", "영업 양수"),
    ("영업양도", "mna", "영업 양도"),
    ("유형자산양수", "mna", "유형자산 양수"),
    ("유형자산양도", "mna", "유형자산 양도"),
    ("신규시설투자", "mna", "신규 시설 투자"),
    # 지배구조
    ("최대주주변경을수반하는주식양수도", "governance", "경영권 매각 계약"),
    ("최대주주변경을수반하는주식담보", "governance", "최대주주 주식 담보 계약"),
    ("최대주주변경", "governance", "최대주주 변경"),
    ("대표이사", "governance", "대표이사 변경"),
    ("정기주주총회결과", "governance", "정기주총 결과"),
    ("임시주주총회결과", "governance", "임시주총 결과"),
    # 주의
    ("주권매매거래정지해제", "risk", "거래정지 해제"),
    ("주권매매거래정지", "risk", "거래 정지"),
    ("풍문또는보도", "risk", "보도 해명"),
    ("소송등", "risk", "소송"),
    ("불성실공시", "risk", "불성실공시 지정"),
    ("관리종목", "risk", "관리종목"),
    ("상장폐지", "risk", "상장폐지"),
    ("회생절차", "risk", "회생 절차"),
    ("횡령", "risk", "횡령·배임"),
    ("배임", "risk", "횡령·배임"),
    ("채무보증", "risk", "채무 보증"),
    ("담보제공", "risk", "담보 제공"),
    ("금전대여", "risk", "금전 대여"),
    # 알림·IR
    ("기업가치제고계획", "ir", "밸류업 계획"),
    ("기업설명회(IR)개최결과", "ir", "IR 결과"),
    ("기업설명회", "ir", "IR 개최"),
    ("투자판단관련주요경영사항", "management", "주요 경영사항"),
    ("수시공시의무관련사항", "management", "공정공시"),
    ("기타경영사항", "management", "기타 경영사항"),
)

#: 분류 → 배지 글자
CATEGORY_LABEL = {
    "earnings": "실적", "periodic": "정기보고서", "dividend": "배당", "buyback": "자사주",
    "financing": "자금조달", "contract": "계약", "mna": "투자·M&A", "governance": "지배구조",
    "risk": "주의", "ir": "IR", "management": "경영", "other": "기타",
    "holding": "지분", "issue": "발행", "admin": "행정",
}

#: 칩(kind)별로 보이는 분류. `major` 는 지분·발행·행정을 뺀 전부, `key` 는 차트에 점을 찍는 것 — 주가에 직접 닿는 것만
#: ("주요" 는 삼성전자만 해도 1년 120건이라 봉마다 점이 붙는다).
_EXCLUDED_FROM_MAJOR = ("holding", "issue", "admin")
_KEY = ("earnings", "periodic", "dividend", "buyback", "financing", "contract", "mna")

KINDS = ("major", "holding", "all", "key")

_TAG = re.compile(r"^\[([^\]]+)\]\s*")
_SUBSIDIARY = ("자회사", "종속회사")


def classify(report_nm: str) -> tuple[str, str]:
    """`(분류, 쉬운 제목)`. 자회사 공시면 제목 뒤에 `(자회사)` 를 붙인다. SQL(`_category_sql`)과 같은 규칙이다."""
    title, _ = split_tag(report_nm)
    for needle, cat, label in RULES:
        if needle in title:
            if any(k in title for k in _SUBSIDIARY):
                label += " (자회사)"
            return cat, label
    return "other", title


def split_tag(report_nm: str) -> tuple[str, str | None]:
    """`[기재정정]사업보고서` → `('사업보고서', '기재정정')`. 앞머리가 없으면 `None`."""
    m = _TAG.match(report_nm)
    return (report_nm[m.end():], m.group(1)) if m else (report_nm, None)


def _category_sql() -> tuple[str, dict]:
    """`classify` 의 분류를 SQL `CASE` 로 — 첫 번째로 맞는 규칙이 이기는 것까지 같다."""
    whens = " ".join(f"WHEN report_nm LIKE :r{i} THEN :c{i}" for i in range(len(RULES)))
    params = {f"r{i}": f"%{n}%" for i, (n, _, _) in enumerate(RULES)}
    params |= {f"c{i}": c for i, (_, c, _) in enumerate(RULES)}
    return f"(CASE {whens} ELSE 'other' END)", params


def _kind_sql(kind: str) -> tuple[str, dict]:
    if kind == "all":
        return "", {}
    case, params = _category_sql()
    cats = {"holding": ("holding",), "key": _KEY}.get(kind)
    if cats:
        names = [f"k{i}" for i in range(len(cats))]
        return f"AND {case} IN (" + ", ".join(":" + n for n in names) + ")", params | dict(zip(names, cats))
    names = [f"x{i}" for i in range(len(_EXCLUDED_FROM_MAJOR))]
    return (f"AND {case} NOT IN (" + ", ".join(":" + n for n in names) + ")",
            params | dict(zip(names, _EXCLUDED_FROM_MAJOR)))


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


def _won(v: float) -> str:
    """원 → "1.2조원" · "3,400억원" · "5,000만원"."""
    a = abs(v)
    if a >= 1e12:
        return f"{v / 1e12:,.2f}".rstrip("0").rstrip(".") + "조원"
    if a >= 1e8:
        return f"{v / 1e8:,.0f}억원"
    return f"{v / 1e4:,.0f}만원"


_TREASURY = {"acquire": "취득 예정", "dispose": "처분 예정", "trust_open": "신탁 계약", "trust_close": "신탁 해지"}


def _detail(r) -> str | None:
    """자사주·지분 표에서 **같은 접수번호**로 이어 붙인 한 줄. 25.dart 가 아직 못 받은 공시면 없다."""
    if r.t_type:
        parts = [_won(float(r.t_amount))] if r.t_amount else []
        if r.t_shares:
            parts.append(f"{r.t_shares:,}주")
        return " · ".join(parts + [_TREASURY[r.t_type]])
    if r.i_repror:
        who = f"{r.i_repror}({r.i_position})" if r.i_position else r.i_repror
        return f"{who} {r.i_change:+,}주" if r.i_change is not None else who
    if r.m_repror:
        if r.m_ratio is None:
            return r.m_repror
        chg = f" ({float(r.m_ratio_change):+.2f}%p)" if r.m_ratio_change is not None else ""
        return f"{r.m_repror} {float(r.m_ratio):.2f}%{chg}"
    return None


def _effective_day(r) -> date:
    """주가가 반응할 날. 장 마감(15:30) 뒤 공시는 다음 날부터 반영된다.

    ⚠️ DART 는 접수 **시각**을 주지 않는다. 1분 폴링으로 찾은 행(`collect_mode='poll'`)의 `collected_at` 만
       시각으로 믿을 수 있다(2026-09-29 부터). 나머지는 공시일 그대로 — 주말이면 다음 거래일 봉이 잡힌다.
    """
    at = r.collected_at
    if r.collect_mode == "poll" and at and at.date() == r.rcept_dt and at.time() >= time(15, 30):
        return r.rcept_dt + timedelta(days=1)
    return r.rcept_dt


async def _daily_closes(db, code: str, since: date) -> list[tuple[date, float]]:
    """날짜별 마지막 종가(액면분할 보정). 10분봉을 파이썬으로 모으지 않고 SQL 에서 하루 한 줄로 줄인다."""
    from app.ui.stocks import _apply_split_adjustment, _resolve_source, _split_events  # 순환 import 회피

    table = await _resolve_source(db, "candle", code, "s")
    if table is None:
        return []
    rows = (await db.execute(text(
        "SELECT DATE(execution_datetime) AS d, "
        "       SUBSTRING_INDEX(GROUP_CONCAT(execution_close ORDER BY execution_datetime DESC), ',', 1) AS c "
        f"FROM `candle`.`{table}` WHERE execution_datetime >= :s GROUP BY d ORDER BY d"),
        {"s": since})).all()
    adj = _apply_split_adjustment(
        [{"execution_datetime": datetime.combine(r.d, time()), "execution_close": float(r.c),
          "execution_open": 0.0, "execution_min": 0.0, "execution_max": 0.0,
          "execution_non_volume": 0.0, "execution_ask_volume": 0.0, "execution_bid_volume": 0.0}
         for r in rows],
        await _split_events(db, code, "KR"))
    return [(r["execution_datetime"].date(), r["execution_close"]) for r in adj]


def _reaction(closes: list[tuple[date, float]], day: date) -> float | None:
    """`day` 이후 첫 거래일의 등락률(%) — 직전 거래일 종가 대비."""
    for j, (d, c) in enumerate(closes):
        if d >= day:
            if j == 0 or not closes[j - 1][1]:
                return None
            return (c / closes[j - 1][1] - 1) * 100
    return None


async def disclosures(db, code: str, kind: str, page: int, size: int) -> tuple[int, list[dict]]:
    where, params = _kind_sql(kind)
    params |= {"c": code}
    total = (await db.execute(text(
        f"SELECT COUNT(*) FROM Dart.disclosure WHERE stock_code = :c {where}"), params)).scalar() or 0
    rows = (await db.execute(text(
        "SELECT d.rcept_no, d.rcept_dt, d.report_nm, d.flr_nm, d.collected_at, d.collect_mode, "
        "       t.event_type AS t_type, t.amount AS t_amount, t.shares_common AS t_shares, "
        "       i.repror AS i_repror, i.position AS i_position, i.shares_change AS i_change, "
        "       m.repror AS m_repror, m.ratio AS m_ratio, m.ratio_change AS m_ratio_change "
        "FROM Dart.disclosure d "
        "LEFT JOIN Dart.treasury_event t ON t.rcept_no = d.rcept_no "
        "LEFT JOIN Dart.insider_holding i ON i.rcept_no = d.rcept_no "
        "LEFT JOIN Dart.major_holding m ON m.rcept_no = d.rcept_no "
        f"WHERE d.stock_code = :c {where} ORDER BY d.rcept_dt DESC, d.rcept_no DESC "
        "LIMIT :limit OFFSET :offset"),
        params | {"limit": size, "offset": (page - 1) * size})).all()
    closes = await _daily_closes(db, code, min(r.rcept_dt for r in rows) - timedelta(days=15)) if rows else []
    items = []
    for r in rows:
        title, tag = split_tag(r.report_nm)
        cat, label = classify(r.report_nm)
        items.append({"rcept_no": r.rcept_no, "date": r.rcept_dt, "title": title, "tag": tag,
                      "label": label, "category": cat, "category_label": CATEGORY_LABEL[cat],
                      "detail": _detail(r), "reaction": _reaction(closes, _effective_day(r)),
                      "filer": r.flr_nm, "url": DART_VIEWER + r.rcept_no})
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
        cat, label = classify(r.report_nm)
        out.append({"code": r.stock_code, "name": r.stock_name_kr, "date": r.rcept_dt,
                    "title": title, "tag": tag, "label": label, "category": cat,
                    "category_label": CATEGORY_LABEL[cat]})
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
