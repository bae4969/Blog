"""`/api/v1` — 블로그 읽기.

⚠️ **접근 규칙은 화면과 한 글자도 다르면 안 된다.** 한쪽에서만 보이는 글이 생기면
그게 곧 정보 노출이다. 그래서 `app/ui/routes.py` 의 목록·상세와 **같은 where 절**을 쓴다:

- `Category.category_read_level >= level` — 카테고리가 요구하는 등급을 넘어야 읽는다.
  등급은 **낮을수록 권한이 높다**(`blog_user.level_of`).
- `level > 1` 이면 `posting_state == 0` — 관리자(0·1)가 아니면 숨긴 글은 안 보인다.
"""

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, select

from app.core import blog_user, thumbnail
from app.core.sanitize import sanitize
from app.db.models import Category, Post, User
from app.db.session import db_session
from app.schemas import CategoryOut, Page, PostDetail, PostSummary

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
                Post.posting_thumbnail, Post.posting_read_cnt,
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
