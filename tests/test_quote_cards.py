"""주식 홈 지수·환율 카드 구성(2026-10-13) — DB 없이 볼 수 있는 검증 규칙과 경로.

세트 셋 · 6장씩 · 앞 둘은 지수 · 마지막은 환율(모바일이 그렇게 넘긴다) · 구독 중인 것만 · 겹치지 않게.
화면(`quote_cards_admin.js`)도 같은 규칙으로 먼저 검사한다 — 둘이 갈라지면 여기서 잡는다.
"""

from app.main import app
from app.ui.quotes import CARD_SETS_DEFAULT, card_set_errors

# 기본 구성이 전부 구독돼 있다고 치고, 여분을 하나씩 더 둔다.
SUB = {c: ("FX" if c.startswith("KRW") else "INDEX_KR") for s in CARD_SETS_DEFAULT for c in s}
SUB.update({"KOSPI200": "INDEX_KR", "KRWAUD": "FX"})


def sets(*changes):
    out = [list(s) for s in CARD_SETS_DEFAULT]
    for i, j, code in changes:
        out[i][j] = code
    return out


def test_기본_구성은_통과한다():
    assert card_set_errors(sets(), SUB) == {}


def test_여섯_장이_아니면_그_세트에_오류():
    s = sets(); s[1].pop()
    assert list(card_set_errors(s, SUB)) == [1]


def test_구독하지_않은_항목은_고를_수_없다():
    assert "구독하지 않은" in card_set_errors(sets((0, 0, "NOPE")), SUB)[0]


def test_지수_세트에_환율을_넣으면_안_된다():
    assert "지수만" in card_set_errors(sets((0, 0, "KRWAUD")), SUB)[0]


def test_환율_세트에_지수를_넣으면_안_된다():
    assert "환율만" in card_set_errors(sets((2, 0, "KOSPI200")), SUB)[2]


def test_세트끼리_겹치면_안_된다():
    assert "이미" in card_set_errors(sets((1, 0, "KOSPI")), SUB)[1]


def test_모양이_깨지면_거절():
    for bad in (None, [], [[]] * 2, "x", [["a b"]] * 3):
        assert card_set_errors(bad, SUB)


def test_경로가_등록돼_있다():
    paths = set(app.openapi()["paths"])
    assert "/api/v1/quotes/cards" in paths
