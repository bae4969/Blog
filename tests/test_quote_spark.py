"""홈 지수 카드 — 실제 시간 위치로 정규장 전체를 표시한다."""

from datetime import datetime, timedelta

import pytest

from app.schemas.stock import QuoteOut
from app.ui.quotes import _spark_data


def at(hour, minute=0):
    return datetime(2026, 10, 29, hour, minute)


@pytest.mark.parametrize(("code", "category", "opened", "closed"), [
    ("KOSPI", "INDEX_KR", at(9), at(15, 30)),
    ("KOSDAQ", "INDEX_KR", at(9), at(15, 30)),
    ("KOSPI200", "INDEX_KR", at(9), at(15, 30)),
    ("SPX", "INDEX_EX", at(9, 30), at(16)),
    ("COMP", "INDEX_EX", at(9, 30), at(16)),
    ("NDX", "INDEX_EX", at(9, 30), at(16)),
    ("JPNI225", "INDEX_WORLD", at(9), at(15, 30)),
    ("SHANG", "INDEX_WORLD", at(9, 30), at(15)),
    ("HKHS", "INDEX_WORLD", at(9, 30), at(16, 10)),
    ("TWWT", "INDEX_WORLD", at(9), at(13, 30)),
    ("INBOMBAY", "INDEX_WORLD", at(9, 15), at(15, 30)),
    ("SX5E", "INDEX_WORLD", at(9), at(17, 30)),
    ("GRDAX", "INDEX_WORLD", at(9), at(17, 30)),
    ("GBFTSE", "INDEX_WORLD", at(8), at(16, 30)),
])
def test_개장_직후에는_남은_시간을_비워두고_마감해야_폭을_채운다(code, category, opened, closed):
    points = [(opened, 100.0), (opened + timedelta(minutes=10), 101.0)]
    values, x = _spark_data(code, category, points)
    assert values == [100, 101]
    assert x[0] == 0
    assert x[1] == pytest.approx(10 / ((closed - opened).total_seconds() / 60))
    assert x[1] < 0.04
    assert _spark_data(code, category, points + [(closed, 102.0)])[1][-1] == 1


def test_개장_한_점은_왼쪽에_둔다():
    assert _spark_data("KOSPI", "INDEX_KR", [(at(9), 100)]) == ([100], [0])
    assert _spark_data("INBOMBAY", "INDEX_WORLD", [(at(9, 15), 100)]) == ([100], [0])


def test_점심_휴장은_실제_시간_간격으로_남는다():
    _, x = _spark_data("JPNI225", "INDEX_WORLD", [
        (at(11, 20), 100), (at(11, 30), 101), (at(12, 30), 102),
    ])
    assert x[2] - x[1] == pytest.approx(6 * (x[1] - x[0]))


def test_정규장_밖의_값을_마감_위치에_겹쳐_그리지_않는다():
    assert _spark_data("SPX", "INDEX_EX", [
        (at(9, 20), 99), (at(9, 30), 100), (at(16), 101), (at(16, 30), 102),
    ]) == ([100, 101], [0, 1])


def test_종가_스냅샷뿐인_센섹스는_마감_점_하나다():
    assert _spark_data("INBOMBAY", "INDEX_WORLD", [(at(20), 100)]) == ([100], [1])


def test_환율은_기존_최근_80개_폭_배치를_유지한다():
    points = [(at(0) + timedelta(minutes=i * 10), float(i)) for i in range(145)]
    assert _spark_data("KRWUSD", "FX", points) == (list(range(65, 145)), [])


def test_빈_값은_선이나_가짜_가격으로_채우지_않는다():
    assert _spark_data("KOSPI", "INDEX_KR", []) == ([], [])


def test_API_응답에서도_시간_위치가_남는다():
    row = QuoteOut(code="SPX", name="S&P500", category="INDEX_EX",
                   spark=[100, 101], spark_x=[0, 10 / 390])
    assert row.model_dump()["spark_x"] == [0, 10 / 390]
