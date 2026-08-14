"""화면 라우트 — 지금은 블로그 목록 하나뿐이다.

PHP 에서 넘어오는 중이라 **경로와 쿼리 파라미터를 그대로 유지**한다
(`?page=`, `?category_index=`, `?search_string=`). 이름을 바꾸면 기존 링크·북마크가
깨지고, 포팅 중에는 같은 사이트 안에서 두 스택이 서로의 URL 을 참조한다.
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, text

from app.core.config import settings
from app.core.sanitize import (
    clean_title,
    has_image,
    insert_thumbnail,
    make_summary,
    sanitize,
    sanitize_for_save,
    validate_thumbnail,
)
from app.core import blog_user, csrf
from app.core.security import AuthUser
from app.db.models import Category, Post, User
from app.db.session import db_session

logger = logging.getLogger(__name__)
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


@router.get("/", include_in_schema=False)
@router.get("/index.php", include_in_schema=False)
async def root_by_subdomain(request: Request) -> RedirectResponse:
    """사이트 루트 — 서브도메인을 보고 블로그/주식으로 보낸다.

    세 도메인(`blog`·`stock`·…)이 한 서버를 가리키므로 진입점에서 갈라야 한다.
    PHP `HomeController::redirectBySubdomain` 을 그대로 옮겼다 — 쿼리스트링을 붙여 넘기고
    상태코드도 302 로 맞춘다(PHP `View::redirect` 와 같다).

    `/stocks` 는 아직 PHP 가 갖고 있지만 경로가 달라 Traefik 이 알아서 그쪽으로 보낸다.
    """
    host = request.headers.get("host", "localhost").split(":")[0]
    subdomain = host.split(".")[0]
    target = "/stocks" if subdomain == "stock" else "/blog"
    if request.url.query:
        target += f"?{request.url.query}"
    return RedirectResponse(target, status_code=status.HTTP_302_FOUND)


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
                    # 소유자 판정에 쓴다 — 빠뜨리면 버튼 조건에서 KeyError 가 난다.
                    Post.user_index,
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

        # 어떤 버튼을 보일지 — 서버가 판단한다. 화면에서 숨기는 것만으로는 부족해서
        # 각 POST 라우트가 같은 조건을 한 번 더 검사한다.
        me = await blog_user.find(db, user)
        is_owner = me is not None and row.user_index == me.user_index
        can_moderate = is_owner or (
            me is not None
            and await blog_user.can_write_category(db, me.level, row.category_index)
        )

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

    csrf_token = csrf.new_token(request)
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
            "is_owner": is_owner,
            "can_moderate": can_moderate,
            "csrf_token": csrf_token,
            "auth_public_url": settings.auth_public_url,
            "contact_email": settings.contact_email,
            "github_url": settings.github_url,
        },
    )
    csrf.attach(response, csrf_token)
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



async def _shell_ctx(request: Request, db, level: int, category_id: int | None = None) -> dict:
    """레이아웃(헤더·사이드바·푸터)이 쓰는 공통 값. 화면마다 반복하지 않으려고 모았다."""
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
    return {
        "user": getattr(request.state, "user", None),
        "level": level,
        "categories": categories,
        "category_id": category_id,
        "search": "",
        "visitor_count": visitor_count,
        "auth_public_url": settings.auth_public_url,
        "contact_email": settings.contact_email,
        "github_url": settings.github_url,
    }


# ══════════════════════════════════════════════════════════════════
#  쓰기 경로 — 여기부터는 DB 를 바꾼다.
#
#  ⚠️ 대상 스키마는 `BlogTest` 다(운영 `Blog` 와 분리, 2026-08-14). 계정에도 운영 권한이
#     없다. 그래도 배포 때 `DATABASE_URL` 이 운영을 가리키지 않는지 확인할 것.
# ══════════════════════════════════════════════════════════════════


@router.get("/writer.php", response_class=HTMLResponse, include_in_schema=False)
async def writer_form(request: Request):
    """새 글 폼. 작성 제한에 걸렸으면 열지 않는다(PHP `createForm` 과 같은 기준)."""
    async with db_session() as db:
        me = await blog_user.find(db, getattr(request.state, "user", None))
        if me is None or me.is_limited:
            if me is not None:
                logger.warning(
                    "글쓰기 거부: user=%s count=%s limit=%s",
                    me.user_id, me.posting_count, me.posting_limit,
                )
            return RedirectResponse("/blog", status_code=status.HTTP_303_SEE_OTHER)

        ctx = await _shell_ctx(request, db, me.level)
        # 쓸 수 있는 카테고리만 고르게 한다 — 목록 밖이면 저장 단계에서 거부된다.
        writable = (
            await db.execute(
                select(Category)
                .where(Category.category_write_level >= me.level)
                .order_by(Category.category_order)
            )
        ).scalars().all()

    selected = _int_arg(request, "category_index", -1)
    selected = selected if selected > 0 else None
    token = csrf.new_token(request)
    response = templates.TemplateResponse(
        request,
        "blog_editor.html",
        {
            **ctx,
            "categories": writable,       # 에디터의 선택 목록은 '쓰기 가능'만
            "is_edit": False,
            "post": None,
            "selected_category": selected,
            "cancel_query": f"?category_index={selected}" if selected else "",
            "csrf_token": token,
        },
    )
    csrf.attach(response, token)
    return response


@router.get("/post/edit/{post_id}", response_class=HTMLResponse, include_in_schema=False)
async def edit_form(request: Request, post_id: int):
    """수정 폼. **본인 글만** 연다(PHP `editForm` 과 같다)."""
    async with db_session() as db:
        me = await blog_user.find(db, getattr(request.state, "user", None))
        if me is None:
            return RedirectResponse("/blog", status_code=status.HTTP_303_SEE_OTHER)

        row = (
            await db.execute(
                select(Post).where(Post.posting_index == post_id)
            )
        ).scalars().first()
        # 남의 글은 수정 폼조차 열지 않는다. 관리자도 마찬가지 — PHP 가 그렇다
        # (관리자에게는 숨김/복구/영구삭제가 따로 있다).
        if row is None or row.user_index != me.user_index:
            return RedirectResponse("/blog", status_code=status.HTTP_303_SEE_OTHER)

        ctx = await _shell_ctx(request, db, me.level, row.category_index)
        writable = (
            await db.execute(
                select(Category)
                .where(Category.category_write_level >= me.level)
                .order_by(Category.category_order)
            )
        ).scalars().all()

    token = csrf.new_token(request)
    response = templates.TemplateResponse(
        request,
        "blog_editor.html",
        {
            **ctx,
            "categories": writable,
            "is_edit": True,
            "post": row,
            "selected_category": row.category_index,
            "cancel_query": f"?category_index={row.category_index}",
            "csrf_token": token,
        },
    )
    csrf.attach(response, token)
    return response


def _reject(msg: str, to: str = "/blog") -> RedirectResponse:
    """쓰기 거부 — 이유를 로그에만 남기고 사용자는 목록으로 보낸다.

    화면에 이유를 세세히 알리지 않는다. 남의 글 id 를 넣어 보는 식의 탐색에
    "권한 없음"과 "없는 글"이 서로 다른 답을 주면 그 자체가 정보가 된다.
    """
    logger.warning("쓰기 거부: %s", msg)
    return RedirectResponse(to, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/writer.php", include_in_schema=False)
async def writer_create(
    request: Request,
    csrf_token: str = Form(""),
    title: str = Form(""),
    content: str = Form(""),
    thumbnail: str = Form(""),
    category_index: int = Form(-1),
):
    """새 글 저장. PHP `PostController::create` + `Post::create` 를 합친 것."""
    if not csrf.valid(request, csrf_token):
        return _reject("csrf_invalid", "/writer.php")

    async with db_session() as db:
        me = await blog_user.find(db, getattr(request.state, "user", None))
        if me is None:
            return _reject("not_a_blog_user")
        if me.is_limited:
            return _reject(f"posting_limit user={me.user_id} {me.posting_count}/{me.posting_limit}")

        clean_t = clean_title(title)
        if not clean_t or not content.strip() or category_index <= 0:
            return _reject("validation_error", "/writer.php")
        if not await blog_user.can_write_category(db, me.level, category_index):
            return _reject(f"category_denied user={me.user_id} cat={category_index}")

        body = sanitize_for_save(content)
        summary = make_summary(body)
        thumb = validate_thumbnail(thumbnail)

        res = await db.execute(
            text(
                "INSERT INTO posting_list "
                "(posting_title, posting_content, posting_summary, posting_thumbnail, "
                " category_index, user_index, posting_first_post_datetime) "
                "VALUES (:t, :c, :s, :th, :cat, :u, NOW())"
            ),
            {"t": clean_t, "c": body, "s": summary, "th": thumb,
             "cat": category_index, "u": me.user_index},
        )
        new_id = res.lastrowid
        # 작성 수를 함께 올린다 — 이게 빠지면 제한이 영원히 안 걸린다.
        await db.execute(
            text("UPDATE user_list SET user_posting_count = user_posting_count + 1 "
                 "WHERE user_index = :u"),
            {"u": me.user_index},
        )
        await db.commit()

    logger.info("글 작성: user=%s id=%s cat=%s", me.user_id, new_id, category_index)
    return RedirectResponse(f"/reader.php?posting_index={new_id}",
                            status_code=status.HTTP_303_SEE_OTHER)


@router.post("/post/update/{post_id}", include_in_schema=False)
async def post_update(
    request: Request,
    post_id: int,
    csrf_token: str = Form(""),
    title: str = Form(""),
    content: str = Form(""),
    thumbnail: str = Form(""),
    category_index: int = Form(-1),
):
    """글 수정. 본인 글만. 작성 수는 건드리지 않는다(새 글이 아니다)."""
    if not csrf.valid(request, csrf_token):
        return _reject("csrf_invalid", f"/post/edit/{post_id}")

    async with db_session() as db:
        me = await blog_user.find(db, getattr(request.state, "user", None))
        if me is None:
            return _reject("not_a_blog_user")

        owner = (
            await db.execute(
                text("SELECT user_index FROM posting_list WHERE posting_index = :i"),
                {"i": post_id},
            )
        ).scalar()
        if owner is None or int(owner) != me.user_index:
            return _reject(f"not_owner user={me.user_id} post={post_id}")

        clean_t = clean_title(title)
        if not clean_t or not content.strip() or category_index <= 0:
            return _reject("validation_error", f"/post/edit/{post_id}")
        if not await blog_user.can_write_category(db, me.level, category_index):
            return _reject(f"category_denied user={me.user_id} cat={category_index}")

        body = sanitize_for_save(content)
        await db.execute(
            text(
                "UPDATE posting_list SET posting_title = :t, posting_content = :c, "
                "  posting_summary = :s, posting_thumbnail = :th, category_index = :cat, "
                "  posting_last_edit_datetime = NOW() "
                "WHERE posting_index = :i"
            ),
            {"t": clean_t, "c": body, "s": make_summary(body),
             "th": validate_thumbnail(thumbnail), "cat": category_index, "i": post_id},
        )
        await db.commit()

    logger.info("글 수정: user=%s id=%s", me.user_id, post_id)
    return RedirectResponse(f"/reader.php?posting_index={post_id}",
                            status_code=status.HTTP_303_SEE_OTHER)


async def _state_change(request: Request, post_id: int, csrf_token: str,
                        *, new_state: int, need_admin: bool = False):
    """숨김(1)·복구(0) 공통 처리. 권한 기준은 PHP `enable`/`disable` 과 같다:
    **본인 글이거나** 그 카테고리에 쓰기 권한이 있으면 된다.
    """
    if not csrf.valid(request, csrf_token):
        return _reject("csrf_invalid", f"/reader.php?posting_index={post_id}")

    async with db_session() as db:
        me = await blog_user.find(db, getattr(request.state, "user", None))
        if me is None:
            return _reject("not_a_blog_user")
        if need_admin and me.level > 1:
            return _reject(f"admin_only user={me.user_id} level={me.level}")

        row = (
            await db.execute(
                text("SELECT user_index, category_index FROM posting_list "
                     "WHERE posting_index = :i"),
                {"i": post_id},
            )
        ).first()
        if row is None:
            return _reject(f"not_found post={post_id}")

        owner, cat = int(row[0]), int(row[1])
        allowed = owner == me.user_index or await blog_user.can_write_category(db, me.level, cat)
        if not allowed:
            return _reject(f"denied user={me.user_id} post={post_id}")

        await db.execute(
            text("UPDATE posting_list SET posting_state = :s WHERE posting_index = :i"),
            {"s": new_state, "i": post_id},
        )
        await db.commit()

    logger.info("글 상태 변경: user=%s id=%s state=%s", me.user_id, post_id, new_state)
    return RedirectResponse(f"/reader.php?posting_index={post_id}" if new_state == 0 else "/blog",
                            status_code=status.HTTP_303_SEE_OTHER)


@router.post("/post/disable/{post_id}", include_in_schema=False)
async def post_disable(request: Request, post_id: int, csrf_token: str = Form("")):
    """글 숨김. 지우지 않고 `posting_state=1` 로 둔다 — 관리자가 복구할 수 있다."""
    return await _state_change(request, post_id, csrf_token, new_state=1)


@router.post("/post/enable/{post_id}", include_in_schema=False)
async def post_enable(request: Request, post_id: int, csrf_token: str = Form("")):
    """숨긴 글 복구."""
    return await _state_change(request, post_id, csrf_token, new_state=0)


@router.post("/post/hard-delete/{post_id}", include_in_schema=False)
async def post_hard_delete(request: Request, post_id: int, csrf_token: str = Form("")):
    """영구 삭제 — **관리자(level<=1)만**. 되돌릴 수 없다(PHP 와 같은 기준)."""
    if not csrf.valid(request, csrf_token):
        return _reject("csrf_invalid", f"/reader.php?posting_index={post_id}")

    async with db_session() as db:
        me = await blog_user.find(db, getattr(request.state, "user", None))
        if me is None or me.level > 1:
            return _reject(f"admin_only post={post_id}")

        owner = (
            await db.execute(
                text("SELECT user_index FROM posting_list WHERE posting_index = :i"),
                {"i": post_id},
            )
        ).scalar()
        if owner is None:
            return _reject(f"not_found post={post_id}")

        await db.execute(
            text("DELETE FROM posting_list WHERE posting_index = :i"), {"i": post_id}
        )
        # 글이 사라졌으니 작성 수도 되돌린다 — 안 그러면 제한이 잘못 걸린다.
        await db.execute(
            text("UPDATE user_list SET user_posting_count = GREATEST(user_posting_count - 1, 0) "
                 "WHERE user_index = :u"),
            {"u": int(owner)},
        )
        await db.commit()

    logger.warning("글 영구 삭제: user=%s id=%s", me.user_id, post_id)
    return RedirectResponse("/blog", status_code=status.HTTP_303_SEE_OTHER)
