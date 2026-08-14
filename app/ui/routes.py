"""화면 라우트 — 지금은 블로그 목록 하나뿐이다.

PHP 에서 넘어오는 중이라 **경로와 쿼리 파라미터를 그대로 유지**한다
(`?page=`, `?category_index=`, `?search_string=`). 이름을 바꾸면 기존 링크·북마크가
깨지고, 포팅 중에는 같은 사이트 안에서 두 스택이 서로의 URL 을 참조한다.
"""

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, text

from app.core.config import settings
from app.core.sanitize import has_image, insert_thumbnail, sanitize
from app.core.security import AuthUser
from app.db.models import Category, Post, User
from app.db.session import db_session

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))
# 부팅 시각 기준 캐시버스터. 넣지 않으면 `?v=` 가 빈 문자열로 렌더돼 캐시가 안 깨진다.
templates.env.globals["static_v"] = str(int(time.time()))

#: 조회수 중복 방지의 "오늘"을 판정하는 기준 시간대. PHP 의 `date("Y-m-d")` 는 서버
#: 로컬(KST)이라 UTC 로 재면 자정 근처에서 하루가 어긋난다.
_KST = timezone(timedelta(hours=9))


def _user_level(user: AuthUser | None) -> int:
    """중앙 auth 의 역할 → 옛 블로그 등급.

    ⚠️ 등급은 낮을수록 권한이 높다. auth 는 role 문자열(root/admin/…)을 주고 블로그는
    숫자를 쓰므로 여기서 한 번만 옮긴다. 비로그인은 4(visitor) — PHP `Auth.php:122` 와 같다.
    """
    if user is None:
        return settings.anonymous_level
    if "root" in user.roles:
        return 0
    if "admin" in user.roles:
        return 1
    if "poster" in user.roles:
        return 2
    if "member" in user.roles:
        return 3
    return settings.anonymous_level


@router.get("/blog", response_class=HTMLResponse, include_in_schema=False)
async def blog_index(request: Request):
    """글 목록. 로그인하지 않아도 볼 수 있다(공개 카테고리만).

    권한 규칙은 PHP `Post::getMetaAllFromDb` 를 그대로 옮겼다:
      · `category_read_level >= 내 등급` 인 카테고리만
      · 등급이 2 이상(일반)이면 `posting_state = 0`(공개)만
    """
    user: AuthUser | None = getattr(request.state, "user", None)
    level = _user_level(user)

    page = max(1, _int_arg(request, "page", 1))
    category_id = _int_arg(request, "category_index", -1)
    category_id = category_id if category_id > 0 else None
    search = (request.query_params.get("search_string") or "").strip()

    per_page = settings.posts_per_page

    async with db_session() as db:
        where = [Category.category_read_level >= level]
        if level > 1:
            where.append(Post.posting_state == 0)
        if category_id is not None:
            where.append(Post.category_index == category_id)
        if search:
            where.append(Post.posting_title.like(f"%{search}%"))

        total = (
            await db.execute(
                select(func.count())
                .select_from(Post)
                .join(Category, Category.category_index == Post.category_index)
                .where(*where)
            )
        ).scalar() or 0

        pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, pages)

        rows = (
            await db.execute(
                # 본문(posting_content)은 빼고 읽는다 — 목록에 필요 없고 mediumtext 라 무겁다.
                select(
                    Post.posting_index,
                    Post.posting_title,
                    Post.posting_summary,
                    Post.posting_thumbnail,
                    Post.posting_read_cnt,
                    Post.posting_state,
                    Post.posting_first_post_datetime,
                    Category.category_name,
                    Category.category_index,
                    User.user_id,
                )
                .select_from(Post)
                .join(Category, Category.category_index == Post.category_index)
                .outerjoin(User, User.user_index == Post.user_index)
                .where(*where)
                .order_by(Post.posting_index.desc())
                .limit(per_page)
                .offset((page - 1) * per_page)
            )
        ).all()

        categories = (
            await db.execute(
                select(Category)
                .where(Category.category_read_level >= level)
                .order_by(Category.category_order)
            )
        ).scalars().all()

        # 방문자 수 — PHP `User::getVisitorCount()` 와 같은 값을 읽는다. **주 단위**
        # 집계이고 키는 `YYYY` + 2자리 주차다(`date("Y") . str_pad(date("W"),2,'0')`).
        # ⚠️ MariaDB 의 WEEK 모드를 맞춰야 한다. PHP 의 `date("W")` 는 ISO-8601 주차라
        #    `WEEK(NOW(), 3)` 에 대응한다 — 모드를 빼면 연말·연초에 한 주가 어긋난다.
        #
        # ⚠️ **읽기만** 한다. PHP 는 여기서 `updateVisitorCount()` 로 카운트를 올리는데
        #    이 서비스 계정에는 SELECT 밖에 없다(운영 데이터를 공유하는 상태라 쓰기를
        #    함부로 열지 않았다). 집계가 덜 오르는 것과 운영 테이블에 잘못 쓰는 것 중에는
        #    전자가 낫다 — 쓰기 경로를 포팅할 때 함께 처리한다.
        visitor_count = (
            await db.execute(
                text(
                    "SELECT visit_count FROM weekly_visitors "
                    "WHERE year_week = CONCAT(YEAR(NOW()), LPAD(WEEK(NOW(), 3), 2, '0'))"
                )
            )
        ).scalar() or 0

    return templates.TemplateResponse(
        request,
        "blog_index.html",
        {
            "user": user,
            "level": level,
            "posts": rows,
            "categories": categories,
            "category_id": category_id,
            "search": search,
            "page": page,
            "pages": pages,
            "total": total,
            "visitor_count": visitor_count,
            "auth_public_url": settings.auth_public_url,
            "contact_email": settings.contact_email,
            "github_url": settings.github_url,
        },
    )


def _int_arg(request: Request, key: str, default: int) -> int:
    """쿼리 파라미터를 정수로. 이상한 값이 와도 500 을 내지 않는다."""
    try:
        return int(request.query_params.get(key, default))
    except (TypeError, ValueError):
        return default


#: 조회수 중복 방지 쿠키. PHP 는 세션에 `post_read_<id>_<날짜>` 를 넣어 하루 한 번만
#: 올리는데, 이 서비스에는 서버 세션이 없어 같은 뜻의 쿠키를 쓴다.
_READ_COOKIE = "post_read"


@router.get("/reader.php", response_class=HTMLResponse, include_in_schema=False)
async def post_detail(request: Request):
    """글 상세. 경로를 `/reader.php` 그대로 둔다 — 목록의 링크와 기존 북마크가 이걸 쓴다.

    권한 규칙은 PHP `Post::getDetailById` 와 같다:
      · `category_read_level >= 내 등급`
      · 등급이 2 이상이면 `posting_state = 0`(공개)만
    없거나 권한이 없으면 목록으로 보낸다(존재 여부를 알려주지 않는다).
    """
    user: AuthUser | None = getattr(request.state, "user", None)
    level = _user_level(user)
    post_id = _int_arg(request, "posting_index", -1)

    if post_id <= 0:
        return RedirectResponse("/blog", status_code=status.HTTP_303_SEE_OTHER)

    async with db_session() as db:
        where = [
            Category.category_read_level >= level,
            Post.posting_index == post_id,
        ]
        if level > 1:
            where.append(Post.posting_state == 0)

        row = (
            await db.execute(
                select(
                    Post.posting_index,
                    Post.posting_title,
                    Post.posting_content,
                    Post.posting_thumbnail,
                    Post.posting_read_cnt,
                    Post.posting_state,
                    Post.posting_first_post_datetime,
                    Post.posting_last_edit_datetime,
                    Post.category_index,
                    Category.category_name,
                    User.user_id,
                )
                .select_from(Post)
                .outerjoin(Category, Category.category_index == Post.category_index)
                .outerjoin(User, User.user_index == Post.user_index)
                .where(*where)
            )
        ).first()

        if row is None:
            return RedirectResponse("/blog", status_code=status.HTTP_303_SEE_OTHER)

        categories = (
            await db.execute(
                select(Category)
                .where(Category.category_read_level >= level)
                .order_by(Category.category_order)
            )
        ).scalars().all()

        visitor_count = (
            await db.execute(
                text(
                    "SELECT visit_count FROM weekly_visitors "
                    "WHERE year_week = CONCAT(YEAR(NOW()), LPAD(WEEK(NOW(), 3), 2, '0'))"
                )
            )
        ).scalar() or 0

        # 조회수 — 같은 글을 하루 한 번만 센다(PHP 와 같은 기준). 쿠키에 오늘 본 글 id 를
        # 모아 둔다. 세션이 없어 위조가 가능하지만, 위조해도 **덜 세질 뿐** 부풀릴 수는
        # 없다(쿠키에 넣으면 증가를 건너뛴다). 조회수는 그 정도 정확도면 충분하다.
        today = datetime.now(_KST).strftime("%Y-%m-%d")
        seen_raw = request.cookies.get(_READ_COOKIE, "")
        seen_day, _, seen_ids = seen_raw.partition("|")
        seen = set(seen_ids.split(",")) if seen_day == today and seen_ids else set()
        counted = str(post_id) not in seen

        if counted:
            await db.execute(
                text(
                    "UPDATE posting_list SET posting_read_cnt = posting_read_cnt + 1 "
                    "WHERE posting_index = :i"
                ),
                {"i": post_id},
            )
            await db.commit()

    content = sanitize(row.posting_content)
    # 본문에 이미지가 하나도 없을 때만 썸네일을 끼워 넣는다(PHP 와 같은 규칙).
    if row.posting_thumbnail and not has_image(content):
        content = insert_thumbnail(content, row.posting_thumbnail)

    response = templates.TemplateResponse(
        request,
        "blog_show.html",
        {
            "user": user,
            "level": level,
            "post": row,
            "content": content,
            # 조회수는 방금 올린 값을 화면에 반영한다(다시 읽지 않는다).
            "read_cnt": (row.posting_read_cnt or 0) + (1 if counted else 0),
            "categories": categories,
            "category_id": row.category_index,
            "search": "",
            "visitor_count": visitor_count,
            "auth_public_url": settings.auth_public_url,
            "contact_email": settings.contact_email,
            "github_url": settings.github_url,
        },
    )
    if counted:
        seen.add(str(post_id))
        response.set_cookie(
            _READ_COOKIE,
            f"{today}|{','.join(sorted(seen))}",
            max_age=86400,
            httponly=True,
            samesite="lax",
        )
    return response
