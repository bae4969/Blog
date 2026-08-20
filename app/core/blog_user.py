"""중앙 auth 계정 ↔ 옛 블로그 계정 잇기.

글은 `posting_list.user_index` 로 글쓴이를 가리키는데, 중앙 auth 는 `username` 만 준다.
둘을 잇는 곳은 여기 하나뿐이다 — 계정 이관이 끝나면 이 모듈째로 사라진다.

⚠️ `user_index` 는 **0 이 실제 계정이다**(bae4969). `if user_index:` 로 검사하면 그
계정만 조용히 빠진다 — 반드시 `is None` 으로 볼 것.
"""

from dataclasses import dataclass

from sqlalchemy import text

from app.core.config import settings
from app.core.security import AuthUser


@dataclass
class BlogUser:
    """블로그 쪽에서 본 글쓴이."""

    user_index: int
    user_id: str
    level: int
    posting_count: int
    posting_limit: int

    @property
    def is_limited(self) -> bool:
        """작성 제한에 걸렸나 — PHP `getPostingLimitInfo` 와 같은 기준."""
        return self.posting_count >= self.posting_limit


def level_of(user: AuthUser | None) -> int:
    """중앙 auth 의 역할 → 옛 블로그 등급.

    ⚠️ **등급은 낮을수록 권한이 높다.** auth 는 role 문자열(root/admin/…)을 주고 블로그는
    숫자를 쓰므로 여기서 한 번만 옮긴다. 비로그인은 4(visitor) — PHP `Auth.php:122` 와 같다.

    화면(`app/ui`)과 API(`app/api`)가 **같은 값을 봐야** 한 쪽에서만 보이는 글이 생기지
    않는다. 그래서 UI 모듈이 아니라 여기 둔다 — 원래 `ui/routes.py` 에 있어서 이 모듈이
    순환 임포트를 피하려고 함수 안에서 가져오고 있었다.
    """
    if user is None:
        return settings.anonymous_level
    if "root" in user.roles:
        return 0
    if "admin" in user.roles:
        return 1
    if "manager" in user.roles:
        return 2
    if "member" in user.roles:
        return 3
    return settings.anonymous_level


async def find(db, user: AuthUser | None) -> BlogUser | None:
    """로그인한 auth 계정에 대응하는 블로그 계정. 없으면 None(글을 못 쓴다).

    아직 옛 `user_list` 에 없는 auth 계정은 글을 쓸 수 없다. 계정 이관이 끝나기 전까지
    새 사용자를 받으려면 그쪽에 행을 만들어 줘야 한다.

    ⚠️ **등급은 `user_list.user_level` 이 아니라 auth 토큰의 역할에서 온다**(2026-08-17).
       두 곳이 같은 0~4 체계를 들고 있어 진실의 원천이 둘이었다 — 지금은 사용자가 하나뿐이라
       우연히 일치했을 뿐, 어긋나면 화면(역할 기준)과 쓰기 권한(user_level 기준)이 따로
       놀았다. auth 가 "누구인가와 등급" 을 책임지므로 그쪽을 따른다.
       `user_state`·글 수·글 제한은 블로그 도메인 데이터라 여기 남는다.
    """
    if user is None:
        return None
    row = (
        await db.execute(
            text(
                "SELECT user_index, user_id, "
                "       user_posting_count, user_posting_limit "
                "FROM user_list WHERE user_id = :u AND user_state = 0"
            ),
            {"u": user.uid},
        )
    ).first()
    if row is None:
        return None
    return BlogUser(
        user_index=int(row[0]),
        user_id=row[1],
        level=level_of(user),
        posting_count=int(row[2]),
        posting_limit=int(row[3]),
    )


async def can_write_category(db, level: int, category_index: int) -> bool:
    """이 등급이 그 카테고리에 쓸 수 있나.

    ⚠️ 등급은 낮을수록 권한이 높다 — 조건이 `category_write_level >= 내 등급` 이다
    (PHP `Post::create` 와 같다). 부등호를 뒤집으면 아무 카테고리에나 쓸 수 있게 된다.
    """
    n = (
        await db.execute(
            text(
                "SELECT COUNT(*) FROM category_list "
                "WHERE category_write_level >= :lv AND category_index = :c"
            ),
            {"lv": level, "c": category_index},
        )
    ).scalar()
    return bool(n)
