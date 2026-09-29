"""OpenDART 공시 분류·앞머리 떼기 — DB 없이 판정되는 것만.

⚠️ `classify` 와 SQL 조건(`_kind_sql`)은 같은 규칙이어야 한다. 한쪽만 고치면 "주요" 칩에
   걸러진 공시가 목록에서는 `kind=holding` 으로 찍히는 식으로 어긋난다.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import dart


@pytest.mark.parametrize("name, kind", [
    ("임원ㆍ주요주주특정증권등소유상황보고서", "holding"),
    ("[기재정정]임원ㆍ주요주주특정증권등소유상황보고서", "holding"),
    ("임원ㆍ주요주주특정증권등거래계획보고서", "holding"),
    ("주식등의대량보유상황보고서(일반)", "holding"),
    ("최대주주등소유주식변동신고서", "holding"),
    ("투자설명서(채무증권)", "issue"),
    ("일괄신고추가서류(파생결합증권-주가연계증권)", "issue"),
    ("증권발행실적보고서", "issue"),
    ("반기보고서 (2026.06)", "major"),
    ("주요사항보고서(자기주식취득결정)", "major"),
    ("현금ㆍ현물배당결정", "major"),
])
def test_분류(name, kind):
    assert dart.classify(name) == kind


@pytest.mark.parametrize("kind, needles", [
    ("holding", dart._HOLDING),
    ("major", dart._HOLDING + dart._ISSUE),
])
def test_SQL_조건이_분류_목록을_다_쓴다(kind, needles):
    where, params = dart._kind_sql(kind)
    assert sorted(params.values()) == sorted(f"%{n}%" for n in needles)
    assert where.count("LIKE") == len(needles)


def test_차트용_핵심은_KEY_목록만_쓴다():
    where, params = dart._kind_sql("key")
    assert sorted(params.values()) == sorted(f"%{n}%" for n in dart._KEY)
    assert "NOT" not in where


def test_전체는_조건이_없다():
    assert dart._kind_sql("all") == ("", {})


@pytest.mark.parametrize("raw, title, tag", [
    ("[기재정정]사업보고서 (2025.12)", "사업보고서 (2025.12)", "기재정정"),
    ("[발행조건확정] 투자설명서", "투자설명서", "발행조건확정"),
    ("분기보고서 (2026.03)", "분기보고서 (2026.03)", None),
])
def test_앞머리(raw, title, tag):
    assert dart.split_tag(raw) == (title, tag)


def test_경로와_잘못된_kind():
    paths = set(app.openapi()["paths"])
    assert {"/api/v1/stocks/{code}/fundamentals", "/api/v1/stocks/{code}/disclosures",
            "/api/v1/stocks/{code}/financials"} <= paths
    with TestClient(app, raise_server_exceptions=False) as c:
        assert c.get("/api/v1/stocks/005930/disclosures?kind=bad").status_code == 422
        assert c.get("/api/v1/stocks/005930/disclosures?size=101").status_code == 422
        assert c.get("/api/v1/stocks/005930/financials?limit=41").status_code == 422
