"""`/api/v1` — 블로그 읽기.

⚠️ **접근 규칙은 화면과 한 글자도 다르면 안 된다.** 한쪽에서만 보이는 글이 생기면
그게 곧 정보 노출이다. 그래서 `app/ui/routes.py` 의 목록·상세와 **같은 where 절**을 쓴다:

- `Category.category_read_level >= level` — 카테고리가 요구하는 등급을 넘어야 읽는다.
  등급은 **낮을수록 권한이 높다**(`blog_user.level_of`).
- `level > 1` 이면 `posting_state == 0` — 관리자(0·1)가 아니면 숨긴 글은 안 보인다.
"""

import logging

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, select, text

from app.api.deps import writer
from app.core import blog_user, thumbnail
from app.core.sanitize import (
    clean_title,
    make_summary,
    sanitize,
    sanitize_for_save,
    validate_thumbnail,
)
from app.db.models import Category, Post, User
from app.db.session import db_session
from app.schemas import CategoryOut, Page, PostCreate, PostDetail, PostSummary, PostUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["blog"])

#: 한 쪽에 담을 최대 건수. 화면(10)보다 넉넉하되 상한을 둔다 — 없으면 한 번에 전부
#: 긁어가는 요청이 DB 를 붙든다.
_MAX_SIZE = 100


def _level(request: Request) -> int:
    return blog_user.level_of(getattr(request.state, "user", None))


def _summary(row) -> PostSummary:
    return PostSummary(
        id=row.posting_index,
        title=row.posting_title,
        summary=row.posting_summary,
        # DB 값(경로 또는 base64)이 아니라 바로 쓸 수 있는 URL 로 바꿔 내보낸다.
        thumbnail_url=thumbnail.src(row.posting_thumbnail) or None,
        category=(
            CategoryOut(id=row.category_index, name=row.category_name, order=0)
            if row.category_index is not None else None
        ),
        author=row.user_id,
        read_count=row.posting_read_cnt,
        is_hidden=bool(getattr(row, 'posting_state', 0)),
        created_at=row.posting_first_post_datetime,
        updated_at=row.posting_last_edit_datetime,
    )


@router.get("/categories", response_model=list[CategoryOut], summary="읽을 수 있는 카테고리")
async def categories(request: Request):
    level = _level(request)
    async with db_session() as db:
        rows = (await db.execute(
            select(Category)
            .where(Category.category_read_level >= level)
            .order_by(Category.category_order)
        )).scalars().all()
    return [CategoryOut(id=c.category_index, name=c.category_name, order=c.category_order)
            for c in rows]


@router.get("/posts", response_model=Page[PostSummary], summary="글 목록")
async def posts(
    request: Request,
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=_MAX_SIZE),
    category: int | None = Query(None, description="카테고리 번호로 거른다"),
    q: str | None = Query(None, max_length=100, description="제목 부분검색"),
):
    level = _level(request)
    async with db_session() as db:
        where = [Category.category_read_level >= level]
        if level > 1:
            where.append(Post.posting_state == 0)
        if category is not None:
            where.append(Post.category_index == category)
        if q:
            where.append(Post.posting_title.like(f"%{q}%"))

        total = (await db.execute(
            select(func.count()).select_from(Post)
            .join(Category, Category.category_index == Post.category_index)
            .where(*where)
        )).scalar() or 0

        pages = max(1, (total + size - 1) // size)
        page = min(page, pages)

        rows = (await db.execute(
            # 본문은 빼고 읽는다 — 목록에 필요 없고 mediumtext 라 무겁다.
            select(
                Post.posting_index, Post.posting_title, Post.posting_summary,
                Post.posting_thumbnail, Post.posting_read_cnt, Post.posting_state,
                Post.posting_first_post_datetime, Post.posting_last_edit_datetime,
                Category.category_name, Category.category_index, User.user_id,
            )
            .select_from(Post)
            .join(Category, Category.category_index == Post.category_index)
            .outerjoin(User, User.user_index == Post.user_index)
            .where(*where)
            .order_by(Post.posting_index.desc())
            .limit(size).offset((page - 1) * size)
        )).all()

    return Page[PostSummary](
        items=[_summary(r) for r in rows],
        total=total, page=page, size=size, pages=pages,
    )


@router.get("/posts/{post_id}", response_model=PostDetail, summary="글 상세")
async def post(request: Request, post_id: int):
    level = _level(request)
    async with db_session() as db:
        where = [Category.category_read_level >= level, Post.posting_index == post_id]
        if level > 1:
            where.append(Post.posting_state == 0)

        row = (await db.execute(
            select(
                Post.posting_index, Post.posting_title, Post.posting_summary,
                Post.posting_content, Post.posting_thumbnail, Post.posting_read_cnt,
                Post.posting_state,
                Post.posting_first_post_datetime, Post.posting_last_edit_datetime,
                Category.category_name, Category.category_index, User.user_id,
            )
            .select_from(Post)
            .outerjoin(Category, Category.category_index == Post.category_index)
            .outerjoin(User, User.user_index == Post.user_index)
            .where(*where)
        )).first()

    if row is None:
        # ⚠️ 등급이 모자라 못 읽는 경우도 404 다. 403 을 주면 "그 번호의 글은 있다"는
        #    사실이 새어 나간다 — 화면도 목록으로 돌려보내며 존재를 알리지 않는다.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "글을 찾을 수 없습니다")

    base = _summary(row)
    # ⚠️ DB 에는 정화 전 원본이 들어 있다. 여기서 거르지 않으면 그대로 XSS 가 된다
    #    (화면도 출력 시점에 `sanitize()` 를 거친다).
    return PostDetail(**base.model_dump(), content=sanitize(row.posting_content))


# ── 쓰기 ─────────────────────────────────────────────────────────────
#
# ⚠️ **Bearer 토큰만 받는다.** 이유는 `app/api/deps.py` 참조 — 쿠키를 받으면 CSRF 를
#    따로 막아야 하는데, 브라우저는 Authorization 헤더를 자동으로 붙이지 않으므로
#    Bearer 전용이면 그 위험 자체가 없다.
#
# 권한 규칙은 화면과 같다. 다르면 API 로 우회해 화면에서 못 하는 일을 하게 된다:
#   작성 — 블로그 계정 있음 + 작성 제한 안 걸림 + 카테고리 쓰기 등급 통과
#   수정 — **소유자만**(관리자도 남의 글은 못 고친다. 화면이 그렇다)
#   숨김·복구 — 소유자 **또는** 그 카테고리에 쓸 수 있는 등급


async def _load_for_write(db, post_id: int):
    row = (await db.execute(
        text("SELECT user_index, category_index FROM posting_list WHERE posting_index = :i"),
        {"i": post_id},
    )).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "글을 찾을 수 없습니다")
    return int(row[0]), int(row[1])


async def _check_category(db, level: int, category_id: int) -> None:
    if not await blog_user.can_write_category(db, level, category_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "그 카테고리에 쓸 수 있는 등급이 아닙니다")


@router.post("/posts", response_model=PostDetail, status_code=status.HTTP_201_CREATED,
             summary="글 작성")
async def create_post(request: Request, body: PostCreate):
    async with db_session() as db:
        me = await writer(db, request)
        await _check_category(db, me.level, body.category_id)

        title = clean_title(body.title)
        if not title:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "제목이 비었습니다")
        content = sanitize_for_save(body.content)
        thumb = thumbnail.store(validate_thumbnail(body.thumbnail))

        res = await db.execute(
            text("INSERT INTO posting_list "
                 "(posting_title, posting_content, posting_summary, posting_thumbnail, "
                 " category_index, user_index, posting_first_post_datetime) "
                 "VALUES (:t, :c, :s, :th, :cat, :u, NOW())"),
            {"t": title, "c": content, "s": make_summary(content), "th": thumb,
             "cat": body.category_id, "u": me.user_index},
        )
        new_id = res.lastrowid
        # 작성 수를 함께 올린다 — 이게 빠지면 제한이 영원히 안 걸린다(화면과 같다).
        await db.execute(
            text("UPDATE user_list SET user_posting_count = user_posting_count + 1 "
                 "WHERE user_index = :u"),
            {"u": me.user_index},
        )
        await db.commit()

    logger.info("API 글 작성: user=%s id=%s", me.user_id, new_id)
    return await post(request, new_id)


@router.patch("/posts/{post_id}", response_model=PostDetail, summary="글 수정")
async def update_post(request: Request, post_id: int, body: PostUpdate):
    async with db_session() as db:
        me = await writer(db, request)
        owner, current_cat = await _load_for_write(db, post_id)
        # ⚠️ 소유자만. 화면도 관리자에게 남의 글 수정 폼을 열어 주지 않는다.
        if owner != me.user_index:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "자기 글만 수정할 수 있습니다")

        cat = body.category_id if body.category_id is not None else current_cat
        await _check_category(db, me.level, cat)

        sets, params = ["category_index = :cat"], {"cat": cat, "i": post_id}
        if body.title is not None:
            title = clean_title(body.title)
            if not title:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "제목이 비었습니다")
            sets.append("posting_title = :t"); params["t"] = title
        if body.content is not None:
            content = sanitize_for_save(body.content)
            sets += ["posting_content = :c", "posting_summary = :s"]
            params |= {"c": content, "s": make_summary(content)}
        if body.thumbnail is not None:
            sets.append("posting_thumbnail = :th")
            params["th"] = thumbnail.store(validate_thumbnail(body.thumbnail))

        # 여기서는 수정 시각을 **일부러 갱신한다** — 실제로 글을 고친 것이므로.
        sets.append("posting_last_edit_datetime = NOW()")
        await db.execute(
            text(f"UPDATE posting_list SET {', '.join(sets)} WHERE posting_index = :i"), params)
        await db.commit()

    logger.info("API 글 수정: user=%s id=%s", me.user_id, post_id)
    return await post(request, post_id)


async def _set_state(request: Request, post_id: int, new_state: int) -> None:
    async with db_session() as db:
        me = await writer(db, request)
        owner, cat = await _load_for_write(db, post_id)
        # 숨김·복구는 소유자가 아니어도 그 카테고리에 쓸 수 있으면 된다(화면과 같다).
        if owner != me.user_index and not await blog_user.can_write_category(db, me.level, cat):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "이 글을 다룰 권한이 없습니다")
        await db.execute(
            # ⚠️ 수정 시각을 자기 값으로 다시 넣어 자동갱신을 막는다 — 상태를 바꾼 것이지
            #    글을 고친 것이 아니다(`ON UPDATE current_timestamp()`).
            text("UPDATE posting_list SET posting_state = :s, "
                 "  posting_last_edit_datetime = posting_last_edit_datetime "
                 "WHERE posting_index = :i"),
            {"s": new_state, "i": post_id},
        )
        await db.commit()
    logger.info("API 글 상태: user=%s id=%s state=%s", me.user_id, post_id, new_state)


@router.delete("/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT, summary="글 숨김")
async def hide_post(request: Request, post_id: int):
    """⚠️ **지우지 않는다.** `posting_state=1` 로 숨길 뿐이라 복구할 수 있다(화면과 같다)."""
    await _set_state(request, post_id, 1)


@router.post("/posts/{post_id}/restore", status_code=status.HTTP_204_NO_CONTENT,
             summary="숨긴 글 복구")
async def restore_post(request: Request, post_id: int):
    await _set_state(request, post_id, 0)
