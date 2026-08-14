"""관리자 화면 — PHP `AdminController` 를 영역별로 옮기는 중.

지금 옮긴 것: **카테고리**(목록·추가·수정·삭제·순서). 나머지(users·ip-blocks·logs·
cache·wol·stocks·api-settings)는 아직 PHP 가 갖고 있다.

접근 권한은 PHP 와 같다 — `level <= 1`(root·admin). 화면을 숨기는 것과 별개로
**모든 라우트가 다시 검사한다.**
"""

import logging
import re
import socket
from datetime import datetime, timedelta
from ipaddress import ip_address as ip_address_obj

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import text

from app.core import blog_user, csrf
from app.db.session import db_session
from app.ui.routes import _KST, _shell_ctx, templates

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
        {**ctx, "admin_menu": "categories", "rows": rows, "csrf_token": token, "msg": request.query_params.get("msg")},
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


# ── IP 차단 ─────────────────────────────────────────────────────────
#
# 자동 차단(`block_type='auto'`)은 아직 **PHP 미들웨어가** 넣는다. 여기서는 사람이 하는
# 관리(목록·수동 추가·해제·만료 정리)만 다룬다 — 자동 차단 로직까지 옮기면 두 스택이
# 같은 요청을 두 번 세게 된다.

#: 차단할 수 없는 주소. PHP `config/config.php` 의 `ip_block.whitelist` 와 같아야 한다.
#: 여기가 어긋나면 자기 자신이나 내부망을 차단해 서비스에 못 들어가게 된다.
_IP_WHITELIST = {"127.0.0.1", "::1", "172.16.9.1"}
#: 대역 형태는 문자열 비교로 안 되므로 따로 둔다.
_IP_WHITELIST_NETS = ("192.168.135.",)


def _is_whitelisted(ip: str) -> bool:
    return ip in _IP_WHITELIST or ip.startswith(_IP_WHITELIST_NETS)


@router.get("/ip-blocks", response_class=HTMLResponse, include_in_schema=False)
async def ip_blocks(request: Request):
    """차단 목록. 만료된 것도 함께 보여준다 — 정리 버튼의 대상이 보여야 해서다."""
    async with db_session() as db:
        me = await _require_admin(request, db)
        if me is None:
            return _deny("not_admin /admin/ip-blocks")

        rows = (
            await db.execute(
                text(
                    "SELECT blocked_ip_id, ip_address, reason, block_type, blocked_at, "
                    "       expires_at, "
                    "       (expires_at IS NOT NULL AND expires_at <= NOW()) AS expired "
                    "FROM blocked_ip_list ORDER BY blocked_at DESC LIMIT 1000"
                )
            )
        ).all()
        ctx = await _shell_ctx(request, db, me.level)

    token = csrf.new_token(request)
    response = templates.TemplateResponse(
        request,
        "admin_ip_blocks.html",
        {**ctx, "admin_menu": "ip-blocks", "rows": rows, "csrf_token": token, "msg": request.query_params.get("msg")},
    )
    csrf.attach(response, token)
    return response


@router.post("/ip-blocks/add", include_in_schema=False)
async def ip_block_add(
    request: Request,
    csrf_token: str = Form(""),
    ip_address: str = Form(""),
    reason: str = Form(""),
    duration_hours: int = Form(0),
):
    """수동 차단. `duration_hours` 가 0 이면 영구다.

    같은 IP 를 다시 넣으면 덮어쓴다(`ip_address` 가 UNIQUE) — PHP 의 ON DUPLICATE KEY
    UPDATE 와 같은 동작이라, 기간만 바꾸고 싶을 때 지우고 다시 넣지 않아도 된다.
    """
    if not csrf.valid(request, csrf_token):
        return _deny("csrf_invalid", "/admin/ip-blocks")

    ip = ip_address.strip()
    if not ip:
        return _deny("empty_ip", "/admin/ip-blocks?msg=IP+를+입력하세요")
    try:
        ip_address_obj(ip)  # v4·v6 모두 허용. 형식이 틀리면 ValueError.
    except ValueError:
        return _deny(f"invalid_ip {ip}", "/admin/ip-blocks?msg=IP+형식이+올바르지+않습니다")
    if _is_whitelisted(ip):
        # 자기 발등을 찍는 실수를 막는다 — 내부망·루프백을 차단하면 관리 화면에 못 들어온다.
        return _deny(f"whitelisted {ip}", "/admin/ip-blocks?msg=화이트리스트+IP+는+차단할+수+없습니다")

    async with db_session() as db:
        me = await _require_admin(request, db)
        if me is None:
            return _deny("not_admin ip_block.add")

        if duration_hours > 0:
            sql = (
                "INSERT INTO blocked_ip_list "
                "(ip_address, reason, block_type, blocked_at, expires_at, created_by) "
                "VALUES (:ip, :r, 'manual', NOW(), DATE_ADD(NOW(), INTERVAL :h HOUR), :u) "
                "ON DUPLICATE KEY UPDATE reason=VALUES(reason), block_type='manual', "
                "  blocked_at=NOW(), expires_at=DATE_ADD(NOW(), INTERVAL :h HOUR), "
                "  created_by=VALUES(created_by)"
            )
        else:
            sql = (
                "INSERT INTO blocked_ip_list "
                "(ip_address, reason, block_type, blocked_at, expires_at, created_by) "
                "VALUES (:ip, :r, 'manual', NOW(), NULL, :u) "
                "ON DUPLICATE KEY UPDATE reason=VALUES(reason), block_type='manual', "
                "  blocked_at=NOW(), expires_at=NULL, created_by=VALUES(created_by)"
            )
        await db.execute(text(sql),
                         {"ip": ip, "r": reason.strip() or None,
                          "h": duration_hours, "u": me.user_index})
        await db.commit()

    logger.info("IP 차단: %s (%s시간)", ip, duration_hours or "영구")
    return RedirectResponse("/admin/ip-blocks?msg=차단했습니다",
                            status_code=status.HTTP_303_SEE_OTHER)


@router.post("/ip-blocks/remove", include_in_schema=False)
async def ip_block_remove(
    request: Request, csrf_token: str = Form(""), blocked_ip_id: int = Form(-1)
):
    """차단 해제."""
    if not csrf.valid(request, csrf_token):
        return _deny("csrf_invalid", "/admin/ip-blocks")

    async with db_session() as db:
        if await _require_admin(request, db) is None:
            return _deny("not_admin ip_block.remove")
        await db.execute(
            text("DELETE FROM blocked_ip_list WHERE blocked_ip_id = :i"),
            {"i": blocked_ip_id},
        )
        await db.commit()

    logger.info("IP 차단 해제: id=%s", blocked_ip_id)
    return RedirectResponse("/admin/ip-blocks?msg=해제했습니다",
                            status_code=status.HTTP_303_SEE_OTHER)


@router.post("/ip-blocks/clean", include_in_schema=False)
async def ip_block_clean(request: Request, csrf_token: str = Form("")):
    """기간이 지난 차단을 지운다. 영구 차단(`expires_at IS NULL`)은 건드리지 않는다."""
    if not csrf.valid(request, csrf_token):
        return _deny("csrf_invalid", "/admin/ip-blocks")

    async with db_session() as db:
        if await _require_admin(request, db) is None:
            return _deny("not_admin ip_block.clean")
        res = await db.execute(
            text("DELETE FROM blocked_ip_list "
                 "WHERE expires_at IS NOT NULL AND expires_at <= NOW()")
        )
        await db.commit()
        n = res.rowcount

    logger.info("만료 IP 차단 정리: %s건", n)
    return RedirectResponse(f"/admin/ip-blocks?msg={n}건+정리했습니다",
                            status_code=status.HTTP_303_SEE_OTHER)


# ── 로그 뷰어 ───────────────────────────────────────────────────────
#
# `Log` 스키마는 블로그 것이 아니라 **여러 서비스가 함께 쓰는 곳**이다. 여기서는
# 읽기만 한다 — 계정에도 그 스키마 쓰기 권한이 없다.

#: 정렬에 쓸 수 있는 컬럼. **화이트리스트가 아니면 SQL 에 넣지 않는다** —
#: ORDER BY 는 바인딩 파라미터가 안 되므로 문자열로 붙일 수밖에 없고, 그래서 값을
#: 목록으로 못 박는 것이 유일한 방어다.
_LOG_SORTS = ("log_datetime", "log_name", "log_type", "log_function", "log_file")
_LOG_ORDERS = ("ASC", "DESC")
#: 볼 수 있는 로그 테이블. 이것도 같은 이유로 화이트리스트다.
_LOG_TABLES = ("blog_log", "stock_ticker_log")
_LOG_TYPES = ("I", "W", "E", "N")
_LOG_PER_PAGE = 50
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@router.get("/logs", response_class=HTMLResponse, include_in_schema=False)
async def logs(request: Request):
    """로그 조회. 필터가 하나도 없으면 최근 7일로 좁힌다(PHP 와 같은 기본값).

    로그가 수만 건이라 조건 없이 전체를 훑으면 화면도 DB 도 무겁다.
    """
    qp = request.query_params
    table = qp.get("table", "blog_log")
    if table not in _LOG_TABLES:
        table = "blog_log"

    sort = qp.get("sort", "log_datetime")
    if sort not in _LOG_SORTS:
        sort = "log_datetime"
    order = qp.get("order", "DESC").upper()
    if order not in _LOG_ORDERS:
        order = "DESC"

    name = (qp.get("name") or "").strip()[:255]
    q = (qp.get("q") or "").strip()[:200]
    types = [t for t in qp.getlist("type") if t in _LOG_TYPES]
    date_from = qp.get("date_from", "")
    date_to = qp.get("date_to", "")
    if not _DATE_RE.match(date_from or ""):
        date_from = ""
    if not _DATE_RE.match(date_to or ""):
        date_to = ""

    # 아무 조건도 없으면 최근 7일. 사용자가 하나라도 걸면 그 조건만 쓴다.
    if not any((name, q, types, date_from, date_to)):
        date_from = (datetime.now(_KST) - timedelta(days=7)).strftime("%Y-%m-%d")

    where, params = [], {}
    if name:
        where.append("log_name LIKE :name")
        params["name"] = f"%{name}%"
    if q:
        where.append("log_message LIKE :q")
        params["q"] = f"%{q}%"
    if types:
        # IN 절도 바인딩으로 — 값 개수만큼 이름을 만든다.
        keys = []
        for i, t in enumerate(types):
            k = f"t{i}"
            keys.append(f":{k}")
            params[k] = t
        where.append(f"log_type IN ({', '.join(keys)})")
    if date_from:
        where.append("log_datetime >= :dfrom")
        params["dfrom"] = f"{date_from} 00:00:00"
    if date_to:
        where.append("log_datetime <= :dto")
        params["dto"] = f"{date_to} 23:59:59"

    clause = f"WHERE {' AND '.join(where)}" if where else ""
    page = max(1, int(qp.get("page", 1)) if (qp.get("page") or "1").isdigit() else 1)

    async with db_session() as db:
        me = await _require_admin(request, db)
        if me is None:
            return _deny("not_admin /admin/logs")

        total = (
            await db.execute(text(f"SELECT COUNT(*) FROM Log.{table} {clause}"), params)
        ).scalar() or 0
        pages = max(1, (total + _LOG_PER_PAGE - 1) // _LOG_PER_PAGE)
        page = min(page, pages)

        rows = (
            await db.execute(
                text(
                    f"SELECT log_datetime, log_name, log_type, log_message, "
                    f"       log_function, log_file, log_line "
                    f"FROM Log.{table} {clause} "
                    # ⚠️ 정렬 키를 **하나만** 쓰면 안 된다. MariaDB 12.1.2 에서
                    #    `ORDER BY <인덱스 컬럼> DESC LIMIT n` 이 이 테이블에서
                    #    **빈 결과**를 돌려준다(COUNT 는 90인데 SELECT 만 0행). ASC 는
                    #    정상이고 IGNORE INDEX 를 걸어도 정상이라 옵티마이저 문제로 보인다.
                    #    tie-breaker 를 하나 더 붙이면 계획이 바뀌어 제대로 나온다 —
                    #    같은 값이 여럿일 때 쪽 넘김이 흔들리지 않는 효과도 함께 얻는다.
                    f"ORDER BY {sort} {order}, log_name {order} "
                    f"LIMIT {int(_LOG_PER_PAGE)} OFFSET {int((page - 1) * _LOG_PER_PAGE)}"
                ),
                params,
            )
        ).all()
        ctx = await _shell_ctx(request, db, me.level)

    return templates.TemplateResponse(
        request,
        "admin_logs.html",
        {
            **ctx,
            "admin_menu": "logs",
            "rows": rows,
            "table": table, "tables": _LOG_TABLES,
            "sort": sort, "order": order,
            "name": name, "q": q, "types": types,
            "date_from": date_from, "date_to": date_to,
            "page": page, "pages": pages, "total": total,
        },
    )


# ── Wake-on-LAN ─────────────────────────────────────────────────────

#: 매직 패킷을 보낼 포트. 장비마다 듣는 포트가 달라 둘 다 시도한다(PHP 와 같다).
_WOL_PORTS = (9, 7)
_MAC_RE = re.compile(r"^[0-9A-Fa-f]{12}$")


def _magic_packet(mac: str) -> bytes | None:
    """WOL 매직 패킷 — `FF`6개 + MAC 16번. 형식이 틀리면 None."""
    hexs = mac.replace("-", "").replace(":", "").strip()
    if not _MAC_RE.match(hexs):
        return None
    return b"\xff" * 6 + bytes.fromhex(hexs) * 16


@router.get("/wol", response_class=HTMLResponse, include_in_schema=False)
async def wol(request: Request):
    async with db_session() as db:
        me = await _require_admin(request, db)
        if me is None:
            return _deny("not_admin /admin/wol")
        rows = (
            await db.execute(
                text("SELECT wol_device_id, wol_device_name, wol_device_ip_range, "
                     "       wol_device_mac_address FROM wol_device_list "
                     "ORDER BY wol_device_id")
            )
        ).all()
        ctx = await _shell_ctx(request, db, me.level)

    token = csrf.new_token(request)
    response = templates.TemplateResponse(
        request,
        "admin_wol.html",
        {**ctx, "admin_menu": "wol", "rows": rows, "csrf_token": token, "msg": request.query_params.get("msg")},
    )
    csrf.attach(response, token)
    return response


@router.post("/wol/execute", include_in_schema=False)
async def wol_execute(request: Request, csrf_token: str = Form(""), device_id: int = Form(0)):
    """매직 패킷 전송.

    ⚠️ 컨테이너에서 나가는 UDP 브로드캐스트다. 도커 브리지 네트워크에 갇히면 LAN 의
    대상 장비까지 닿지 않는다 — 패킷을 **보내는 데 성공해도 장비가 안 켜질 수 있다**.
    그래서 "전송했다" 로만 알리고 "켜졌다" 고 말하지 않는다.
    """
    if not csrf.valid(request, csrf_token):
        return _deny("csrf_invalid", "/admin/wol")

    async with db_session() as db:
        me = await _require_admin(request, db)
        if me is None:
            return _deny("not_admin wol.execute")
        row = (
            await db.execute(
                text("SELECT wol_device_name, wol_device_ip_range, wol_device_mac_address "
                     "FROM wol_device_list WHERE wol_device_id = :i"),
                {"i": device_id},
            )
        ).first()

    if row is None:
        return _deny(f"device_not_found id={device_id}", "/admin/wol?msg=등록되지+않은+장치입니다")

    name, bcast, mac = row[0], (row[1] or "").strip(), row[2]
    packet = _magic_packet(mac)
    if packet is None:
        return _deny(f"bad_mac {mac}", "/admin/wol?msg=MAC+주소+형식이+올바르지+않습니다")
    try:
        ip_address_obj(bcast)
    except ValueError:
        return _deny(f"bad_broadcast {bcast}", "/admin/wol?msg=브로드캐스트+IP+가+올바르지+않습니다")

    sent, errors = 0, []
    for port in _WOL_PORTS:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                s.settimeout(2)
                s.sendto(packet, (bcast, port))
            sent += 1
        except OSError as exc:
            errors.append(f"{port}번 포트: {exc}")

    if sent:
        logger.info("WOL 전송: %s → %s (%d/%d 포트)", name, bcast, sent, len(_WOL_PORTS))
        return RedirectResponse(f"/admin/wol?msg={name}+에+패킷을+보냈습니다",
                                status_code=status.HTTP_303_SEE_OTHER)
    logger.error("WOL 전송 실패: %s → %s (%s)", name, bcast, " | ".join(errors))
    return RedirectResponse("/admin/wol?msg=패킷+전송에+실패했습니다",
                            status_code=status.HTTP_303_SEE_OTHER)


@router.post("/wol/create", include_in_schema=False)
async def wol_create(
    request: Request,
    csrf_token: str = Form(""),
    name: str = Form(""),
    ip_range: str = Form(""),
    mac_address: str = Form(""),
):
    if not csrf.valid(request, csrf_token):
        return _deny("csrf_invalid", "/admin/wol")
    if not name.strip() or _magic_packet(mac_address) is None:
        return _deny("invalid_input", "/admin/wol?msg=이름과+MAC+주소를+확인하세요")
    try:
        ip_address_obj(ip_range.strip())
    except ValueError:
        return _deny("bad_broadcast", "/admin/wol?msg=브로드캐스트+IP+가+올바르지+않습니다")

    async with db_session() as db:
        if await _require_admin(request, db) is None:
            return _deny("not_admin wol.create")
        await db.execute(
            text("INSERT INTO wol_device_list "
                 "(wol_device_name, wol_device_ip_range, wol_device_mac_address) "
                 "VALUES (:n, :ip, :m)"),
            {"n": name.strip(), "ip": ip_range.strip(), "m": mac_address.strip()},
        )
        await db.commit()

    logger.info("WOL 장치 추가: %s", name)
    return RedirectResponse("/admin/wol?msg=추가했습니다",
                            status_code=status.HTTP_303_SEE_OTHER)


@router.post("/wol/update", include_in_schema=False)
async def wol_update(
    request: Request,
    csrf_token: str = Form(""),
    device_id: int = Form(0),
    name: str = Form(""),
    ip_range: str = Form(""),
    mac_address: str = Form(""),
):
    if not csrf.valid(request, csrf_token):
        return _deny("csrf_invalid", "/admin/wol")
    if not name.strip() or _magic_packet(mac_address) is None:
        return _deny("invalid_input", "/admin/wol?msg=이름과+MAC+주소를+확인하세요")
    try:
        ip_address_obj(ip_range.strip())
    except ValueError:
        return _deny("bad_broadcast", "/admin/wol?msg=브로드캐스트+IP+가+올바르지+않습니다")

    async with db_session() as db:
        if await _require_admin(request, db) is None:
            return _deny("not_admin wol.update")
        await db.execute(
            text("UPDATE wol_device_list SET wol_device_name = :n, "
                 "  wol_device_ip_range = :ip, wol_device_mac_address = :m "
                 "WHERE wol_device_id = :i"),
            {"n": name.strip(), "ip": ip_range.strip(), "m": mac_address.strip(), "i": device_id},
        )
        await db.commit()

    logger.info("WOL 장치 수정: id=%s", device_id)
    return RedirectResponse("/admin/wol?msg=수정했습니다",
                            status_code=status.HTTP_303_SEE_OTHER)


@router.post("/wol/delete", include_in_schema=False)
async def wol_delete(request: Request, csrf_token: str = Form(""), device_id: int = Form(0)):
    if not csrf.valid(request, csrf_token):
        return _deny("csrf_invalid", "/admin/wol")
    async with db_session() as db:
        if await _require_admin(request, db) is None:
            return _deny("not_admin wol.delete")
        await db.execute(
            text("DELETE FROM wol_device_list WHERE wol_device_id = :i"), {"i": device_id}
        )
        await db.commit()

    logger.info("WOL 장치 삭제: id=%s", device_id)
    return RedirectResponse("/admin/wol?msg=삭제했습니다",
                            status_code=status.HTTP_303_SEE_OTHER)


@router.get("", include_in_schema=False)
@router.get("/", include_in_schema=False)
async def admin_home(request: Request):
    """관리자 진입점. PHP 와 같이 로그 화면으로 보낸다(따로 대시보드가 없다)."""
    async with db_session() as db:
        if await _require_admin(request, db) is None:
            return _deny("not_admin /admin")
    return RedirectResponse("/admin/logs", status_code=status.HTTP_303_SEE_OTHER)
