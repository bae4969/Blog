"""등급 매핑 — 화면과 API 가 **같은 값**을 봐야 한다.

한쪽만 어긋나면 화면엔 안 보이는 글이 API 로는 나가거나 그 반대가 된다. 그래서 매핑은
`app/core/blog_user.py` 한 곳에 있고, 여기서 그 값을 못 박는다.

⚠️ **숫자가 낮을수록 권한이 높다.** 부등호를 뒤집는 실수가 곧 정보 노출이다.
"""

import pytest

from app.core.blog_user import level_of
from app.core.security import AuthUser


def _user(*roles):
    return AuthUser(uid="tester", roles=list(roles))


@pytest.mark.parametrize("roles,expected", [
    (("user", "root"), 0),
    (("user", "admin"), 1),
    (("user", "poster"), 2),
    (("user", "member"), 3),
    (("user",), 4),          # 역할이 없으면 방문자와 같다
    (("user", "unknown"), 4),
])
def test_역할이_등급으로(roles, expected):
    assert level_of(_user(*roles)) == expected


def test_비로그인은_방문자():
    assert level_of(None) == 4


def test_등급은_낮을수록_높은_권한():
    """규약 자체를 못 박는다 — 이게 뒤집히면 모든 where 절의 뜻이 바뀐다."""
    assert level_of(_user("user", "root")) < level_of(_user("user", "admin"))
    assert level_of(_user("user", "admin")) < level_of(None)


def test_여러_역할이_있으면_가장_높은_것을_따른다():
    assert level_of(_user("user", "member", "admin")) == 1
