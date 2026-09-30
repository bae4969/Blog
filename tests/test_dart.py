"""OpenDART 공시 분류·쉬운 제목·앞머리 떼기 — DB 없이 판정되는 것만.

⚠️ `classify`(파이썬)와 `_category_sql`(SQL `CASE`)은 같은 규칙표(`RULES`)에서 나오지만 **따로 평가**된다.
   한쪽만 어긋나면 "주요" 칩에서 걸러진 공시가 목록에서는 다른 배지로 찍힌다. 그래서 SQL 을 SQLite 로
   실제로 돌려 파이썬과 대조한다(LIKE·CASE 의미는 MariaDB 와 같다).
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import dart


CASES = [
    ("임원ㆍ주요주주특정증권등소유상황보고서", "holding", "임원·주요주주 지분 변동"),
    ("[기재정정]임원ㆍ주요주주특정증권등소유상황보고서", "holding", "임원·주요주주 지분 변동"),
    ("임원ㆍ주요주주특정증권등거래계획보고서", "holding", "임원·주요주주 거래 계획"),
    ("주식등의대량보유상황보고서(일반)", "holding", "대량보유(5%) 변동"),
    ("투자설명서(채무증권)", "issue", "투자설명서"),
    ("일괄신고추가서류(파생결합증권-주가연계증권)", "issue", "증권 발행 서류"),
    ("주주명부폐쇄기간또는기준일설정", "admin", "주주명부 기준일 설정"),
    ("현금ㆍ현물배당을위한주주명부폐쇄(기준일)결정", "admin", "배당 기준일 설정"),
    ("주주총회소집공고", "admin", "주주총회 소집"),
    ("반기보고서 (2026.06)", "periodic", "반기보고서"),
    ("연결재무제표기준영업(잠정)실적(공정공시)", "earnings", "잠정 실적 발표"),
    ("현금ㆍ현물배당결정", "dividend", "배당 결정"),
    ("현금ㆍ현물배당결정(자회사의 주요경영사항)", "dividend", "배당 결정 (자회사)"),
    ("주요사항보고서(자기주식취득결정)", "buyback", "자사주 취득 결정"),
    ("주요사항보고서(자기주식취득신탁계약체결결정)", "buyback", "자사주 신탁 체결"),
    ("주요사항보고서(유상증자결정)", "financing", "유상증자 결정"),
    ("유상증자결정(종속회사의주요경영사항)", "financing", "유상증자 결정 (자회사)"),
    ("주요사항보고서(전환사채권발행결정)", "financing", "전환사채(CB) 발행"),
    ("단일판매ㆍ공급계약체결", "contract", "공급 계약 체결"),
    ("타법인주식및출자증권처분결정", "mna", "타 회사 지분 처분"),
    ("주요사항보고서(타법인주식및출자증권양수결정)", "mna", "타 회사 지분 취득"),
    ("최대주주변경을수반하는주식담보제공계약체결", "governance", "최대주주 주식 담보 계약"),
    ("풍문또는보도에대한해명(미확정)", "risk", "보도 해명"),
    ("기업설명회(IR)개최(안내공시)", "ir", "IR 개최"),
    ("[기재정정]처음보는서식", "other", "처음보는서식"),
]
#: SQL 대조에 쓰는 원문 — 위 예시 + 규칙표의 글자 그대로
SAMPLES = [n for n, _, _ in CASES] + [n for n, _, _ in dart.RULES]


@pytest.mark.parametrize("name, cat, label", CASES)
def test_분류와_쉬운_제목(name, cat, label):
    assert dart.classify(name) == (cat, label)


def test_규칙마다_자기_글자는_자기가_잡는다():
    """앞 규칙이 뒤 규칙을 삼키지 않는지 — 순서가 뜻인 표라 새 규칙을 잘못된 자리에 넣으면 여기서 걸린다."""
    for needle, cat, label in dart.RULES:
        got = dart.classify(needle)
        assert got[0] == cat, (needle, got)


def test_모든_분류에_배지_글자가_있다():
    assert {c for _, c, _ in dart.RULES} | {"other"} <= set(dart.CATEGORY_LABEL)


def test_SQL_CASE_는_파이썬_분류와_같다():
    case, params = dart._category_sql()
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE t (report_nm TEXT)")
    db.executemany("INSERT INTO t VALUES (?)", [(n,) for n in SAMPLES])
    got = dict(db.execute(f"SELECT report_nm, {case} FROM t", params).fetchall())
    assert {n: got[n] for n in SAMPLES} == {n: dart.classify(n)[0] for n in SAMPLES}


@pytest.mark.parametrize("kind, keep", [
    ("major", lambda c: c not in ("holding", "issue", "admin")),
    ("holding", lambda c: c == "holding"),
    ("key", lambda c: c in dart._KEY),
])
def test_칩별_SQL_조건(kind, keep):
    where, params = dart._kind_sql(kind)
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE t (report_nm TEXT)")
    db.executemany("INSERT INTO t VALUES (?)", [(n,) for n in SAMPLES])
    got = {n for (n,) in db.execute(f"SELECT report_nm FROM t WHERE 1 {where}", params)}
    assert got == {n for n in SAMPLES if keep(dart.classify(n)[0])}


def test_전체는_조건이_없다():
    assert dart._kind_sql("all") == ("", {})


@pytest.mark.parametrize("raw, title, tag", [
    ("[기재정정]사업보고서 (2025.12)", "사업보고서 (2025.12)", "기재정정"),
    ("[발행조건확정] 투자설명서", "투자설명서", "발행조건확정"),
    ("분기보고서 (2026.03)", "분기보고서 (2026.03)", None),
])
def test_앞머리(raw, title, tag):
    assert dart.split_tag(raw) == (title, tag)


def test_등락률은_공시일_이후_첫_거래일():
    from datetime import date
    closes = [(date(2026, 8, 20), 271000.0), (date(2026, 8, 21), 281500.0), (date(2026, 8, 24), 281500.0)]
    assert round(dart._reaction(closes, date(2026, 8, 21)), 2) == 3.87
    assert dart._reaction(closes, date(2026, 8, 22)) == 0.0      # 토요일 공시 → 월요일
    assert dart._reaction(closes, date(2026, 8, 20)) is None     # 직전 종가가 없다
    assert dart._reaction(closes, date(2026, 8, 25)) is None     # 아직 반영 전


def test_원문은_항목표가_없을_때만_본문을_내고_길면_자른다():
    from types import SimpleNamespace as Row
    form = dart._readable(Row(doc_format="xforms", fields_json='[["1. 계약 > 금액(원)", "44,472"], ["", "a | b"]]',
                              body=None))
    assert form["fields"] == [{"name": "1. 계약 > 금액(원)", "value": "44,472"}, {"name": "", "value": "a | b"}]
    assert form["body"] is None and form["body_truncated"] is False
    doc = dart._readable(Row(doc_format="document", fields_json=None, body="가" * (dart.BODY_CAP + 1)))
    assert doc["fields"] == [] and len(doc["body"]) == dart.BODY_CAP and doc["body_truncated"] is True
    assert dart._readable(Row(doc_format="document", fields_json=None, body="짧다"))["body_truncated"] is False


def test_경로와_잘못된_kind():
    paths = set(app.openapi()["paths"])
    assert {"/api/v1/stocks/{code}/fundamentals", "/api/v1/stocks/{code}/disclosures",
            "/api/v1/stocks/{code}/disclosures/{rcept_no}", "/api/v1/stocks/{code}/financials"} <= paths
    with TestClient(app, raise_server_exceptions=False) as c:
        assert c.get("/api/v1/stocks/005930/disclosures?kind=bad").status_code == 422
        assert c.get("/api/v1/stocks/005930/disclosures?size=101").status_code == 422
        assert c.get("/api/v1/stocks/005930/financials?limit=41").status_code == 422
        assert c.get("/api/v1/stocks/005930/disclosures/2026abc").status_code == 422
