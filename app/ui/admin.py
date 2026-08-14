"""관리자 화면 — PHP `AdminController` 를 영역별로 옮기는 중.

지금 옮긴 것: **카테고리**(목록·추가·수정·삭제·순서). 나머지(users·ip-blocks·logs·
cache·wol·stocks·api-settings)는 아직 PHP 가 갖고 있다.

접근 권한은 PHP 와 같다 — `level <= 1`(root·admin). 화면을 숨기는 것과 별개로
**모든 라우트가 다시 검사한다.**
"""

import logging

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import text

from app.core import blog_user, csrf
from app.db.session import db_session
from app.ui.routes import _shell_ctx, templates

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin")

#: 관리자 등급. 낮을수록 권한이 높다(0:root, 1:admin).
_ADMIN_MAX_LEVEL = 1


async def _require_admin(request: Request, db):
    """관리자면 BlogUser, 아니면 None. 호출부가 목록으로 돌려보낸다."""
    me = await blog_user.find(db, getattr(request.state, "user", None))
    if me is None or me.level > _ADMIN_MAX_LEVEL:
        return None
    return me


def _deny(reason: str, to: str = "/blog") -> RedirectResponse:
    logger.warning("관리자 거부: %s", reason)
    return RedirectResponse(to, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/categories", response_class=HTMLResponse, include_in_schema=False)
async def categories(request: Request):
    """카테고리 목록. 글 수를 함께 보여준다 — 글이 있으면 삭제할 수 없어서다."""
    async with db_session() as db:
        me = await _require_admin(request, db)
        if me is None:
            return _deny("not_admin /admin/categories")

        rows = (
            await db.execute(
                text(
                    "SELECT c.category_index, c.category_name, c.category_order, "
                    "       c.category_read_level, c.category_write_level, "
                    "       (SELECT COUNT(*) FROM posting_list p "
                    "          WHERE p.category_index = c.category_index) AS post_count "
                    "FROM category_list c ORDER BY c.category_order"
                )
            )
        ).all()
        ctx = await _shell_ctx(request, db, me.level)

    token = csrf.new_token(request)
    response = templates.TemplateResponse(
        request,
        "admin_categories.html",
        {**ctx, "rows": rows, "csrf_token": token, "msg": request.query_params.get("msg")},
    )
    csrf.attach(response, token)
    return response


@router.post("/categories/create", include_in_schema=False)
async def category_create(
    request: Request,
    csrf_token: str = Form(""),
    name: str = Form(""),
    read_level: int = Form(0),
    write_level: int = Form(0),
):
    """카테고리 추가. 순서는 맨 뒤에 붙인다."""
    if not csrf.valid(request, csrf_token):
        return _deny("csrf_invalid", "/admin/categories")

    name = name.strip()
    if not name:
        return _deny("empty_name", "/admin/categories?msg=이름을+입력하세요")

    async with db_session() as db:
        if await _require_admin(request, db) is None:
            return _deny("not_admin create")
        # `category_order` 가 UNIQUE 라 빈 자리를 찾지 않고 최대값+1 로 붙인다.
        nxt = (await db.execute(text("SELECT IFNULL(MAX(category_order), 0) + 1 FROM category_list"))).scalar()
        await db.execute(
            text(
                "INSERT INTO category_list "
                "(category_name, category_order, category_read_level, category_write_level) "
                "VALUES (:n, :o, :r, :w)"
            ),
            {"n": name, "o": nxt, "r": read_level, "w": write_level},
        )
        await db.commit()

    logger.info("카테고리 추가: %s", name)
    return RedirectResponse("/admin/categories?msg=추가했습니다",
                            status_code=status.HTTP_303_SEE_OTHER)


@router.post("/categories/update", include_in_schema=False)
async def category_update(
    request: Request,
    csrf_token: str = Form(""),
    category_index: int = Form(-1),
    name: str = Form(""),
    read_level: int = Form(0),
    write_level: int = Form(0),
):
    """이름·권한 수정. 순서는 여기서 건드리지 않는다(교환 전용 경로가 따로 있다)."""
    if not csrf.valid(request, csrf_token):
        return _deny("csrf_invalid", "/admin/categories")

    name = name.strip()
    if category_index <= 0 or not name:
        return _deny("invalid_input", "/admin/categories?msg=값을+확인하세요")

    async with db_session() as db:
        if await _require_admin(request, db) is None:
            return _deny("not_admin update")
        await db.execute(
            text(
                "UPDATE category_list SET category_name = :n, "
                "  category_read_level = :r, category_write_level = :w "
                "WHERE category_index = :i"
            ),
            {"n": name, "r": read_level, "w": write_level, "i": category_index},
        )
        await db.commit()

    logger.info("카테고리 수정: id=%s name=%s", category_index, name)
    return RedirectResponse("/admin/categories?msg=수정했습니다",
                            status_code=status.HTTP_303_SEE_OTHER)


@router.post("/categories/delete", include_in_schema=False)
async def category_delete(
    request: Request, csrf_token: str = Form(""), category_index: int = Form(-1)
):
    """삭제 — **글이 하나라도 있으면 거부한다**(PHP `Category::delete` 와 같다).

    글을 먼저 옮기거나 지우게 하려는 의도다. 여기서 CASCADE 로 지우면 글이 통째로
    사라진다.
    """
    if not csrf.valid(request, csrf_token):
        return _deny("csrf_invalid", "/admin/categories")

    async with db_session() as db:
        if await _require_admin(request, db) is None:
            return _deny("not_admin delete")

        used = (
            await db.execute(
                text("SELECT COUNT(*) FROM posting_list WHERE category_index = :i"),
                {"i": category_index},
            )
        ).scalar()
        if used:
            return _deny(
                f"category_in_use id={category_index} posts={used}",
                "/admin/categories?msg=글이+있는+카테고리는+지울+수+없습니다",
            )

        await db.execute(
            text("DELETE FROM category_list WHERE category_index = :i"),
            {"i": category_index},
        )
        await db.commit()

    logger.info("카테고리 삭제: id=%s", category_index)
    return RedirectResponse("/admin/categories?msg=삭제했습니다",
                            status_code=status.HTTP_303_SEE_OTHER)


@router.post("/categories/reorder", include_in_schema=False)
async def category_reorder(
    request: Request,
    csrf_token: str = Form(""),
    category_index: int = Form(-1),
    direction: str = Form(""),
):
    """순서를 한 칸 위/아래로. 이웃과 `category_order` 를 맞바꾼다.

    ⚠️ `category_order` 는 **UNIQUE** 라 두 행을 곧바로 맞바꾸면 중간에 값이 겹쳐
    실패한다. 아무도 안 쓰는 임시값을 거쳐 3단계로 옮긴다(PHP `swapOrder` 와 같다).
    """
    if not csrf.valid(request, csrf_token):
        return _deny("csrf_invalid", "/admin/categories")
    if direction not in ("up", "down"):
        return _deny("bad_direction", "/admin/categories")

    async with db_session() as db:
        if await _require_admin(request, db) is None:
            return _deny("not_admin reorder")

        cur = (
            await db.execute(
                text("SELECT category_order FROM category_list WHERE category_index = :i"),
                {"i": category_index},
            )
        ).scalar()
        if cur is None:
            return _deny(f"not_found id={category_index}", "/admin/categories")

        # 바로 위/아래 이웃 하나만 찾는다. 사이에 빈 번호가 있어도 자연스럽게 건너뛴다.
        if direction == "up":
            sql = ("SELECT category_index, category_order FROM category_list "
                   "WHERE category_order < :o ORDER BY category_order DESC LIMIT 1")
        else:
            sql = ("SELECT category_index, category_order FROM category_list "
                   "WHERE category_order > :o ORDER BY category_order ASC LIMIT 1")
        nb = (await db.execute(text(sql), {"o": cur})).first()
        if nb is None:
            return RedirectResponse("/admin/categories",
                                    status_code=status.HTTP_303_SEE_OTHER)

        nb_index, nb_order = int(nb[0]), int(nb[1])

        # 쓰이지 않는 임시 번호를 찾는다(255 부터 내려가며).
        used = {
            int(r[0]) for r in (
                await db.execute(text("SELECT category_order FROM category_list"))
            ).all()
        }
        tmp = 255
        while tmp in used:
            tmp -= 1

        upd = text("UPDATE category_list SET category_order = :o WHERE category_index = :i")
        await db.execute(upd, {"o": tmp, "i": category_index})
        await db.execute(upd, {"o": cur, "i": nb_index})
        await db.execute(upd, {"o": nb_order, "i": category_index})
        await db.commit()

    logger.info("카테고리 순서 변경: id=%s %s", category_index, direction)
    return RedirectResponse("/admin/categories",
                            status_code=status.HTTP_303_SEE_OTHER)
