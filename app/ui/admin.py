"""관리자 화면 — 카테고리·주식 구독·액면분할·WOL.

PHP `AdminController` 에서 옮겨 온 7개 중 셋을 2026-08-18 에 걷어냈다:

- **로그 뷰어** — 블로그는 `Log.blog_log` 에 쓰지 않는다(PHP 시절 이력에서 멈췄고),
  정작 큰 `stock_ticker_log` 는 `23.stock_ticker` 의 것이다. 남의 로그를 블로그가
  들고 있을 이유가 없어 `01.core` 로 넘겼다.
- **사용자 관리** — 등급 소유가 auth 로 간 뒤(2026-08-17) 화면의 `update_level` 은
  **아무도 안 읽는 컬럼**을 쓰고 있었다. 계정 생성·비밀번호는 애초에 여기 없다.
  `user_list` 테이블은 남는다 — `blog_user.find()` 가 auth username → `user_index` 를
  잇고 글의 글쓴이가 그 값을 가리킨다. `user_state`·`user_posting_limit` 집행도 그대로다.
- **IP 차단** — 자동 판정은 처음부터 안 옮겼고(2026-08-15), 수동 차단은 운영·테스트
  모두 0건이었다. 그 0건을 위해 미들웨어가 매 요청 DB 세션을 열고 있었다. 요청 수
  제한은 앞단(Traefik)이 할 일이다.

접근 권한은 PHP 와 같다 — `level <= 1`(root·admin). 화면을 숨기는 것과 별개로
**모든 라우트가 다시 검사한다.**
"""

import logging
import re
import socket
from ipaddress import ip_address as ip_address_obj
from urllib.parse import quote

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import bindparam, text

from app.core import blog_user, csrf
from app.db.session import db_session
from app.ui.routes import _int_arg, _shell_ctx, templates

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


# ── 주식 구독 관리 ──────────────────────────────────────────────────
#
# 여기서 고른 종목이 `KoreaInvest.stock_last_ws_query`·`Bithumb.coin_last_ws_query` 에
# 통째로 갈아끼워지고, **`23.stock_ticker` 가 그걸 읽어 WebSocket 구독을 건다.** 즉 이 화면은
# 블로그 데이터가 아니라 **다른 서비스의 입력**을 만든다 — 저장은 전체 교체(DELETE→INSERT)라
# 트랜잭션 안에서 해야 하고, 실수로 비우면 수집이 멈춘다.
#
# 시장 한도(KR/US 각 400)는 한투 API 의 구독 상한에서 온다. 넘겨 저장하면 ticker 쪽이 깨진다.

_STOCK_MARKETS = ("KR", "US", "COIN")
_KR_MARKETS = ("KOSPI", "KOSDAQ", "KONEX")
_US_MARKETS = ("NYSE", "NASDAQ", "AMEX")
#: 시장별 구독 상한 — PHP `getMarketSubscriptionLimits` 의 기본값과 같다.
_SUB_LIMITS = {"KR": 400, "US": 400}
_STOCK_PER_PAGE = 100
_SELECTION_RE = re.compile(r"^(STOCK|COIN):([A-Za-z0-9._/-]{1,32})$", re.I)


def _norm_market(v: str) -> str:
    v = (v or "").strip().upper()
    return v if v in _STOCK_MARKETS else "KR"


def _selection_market(stock_market: str) -> str:
    """종목의 거래소를 KR/US 로 접는다. PHP `normalizeSelectionMarket` 과 같다(기본 KR)."""
    m = (stock_market or "").strip().upper()
    return "US" if m in _US_MARKETS else "KR"


def _query_key(query_type: str, code: str) -> str:
    """`query` 컬럼(varchar(32)) 용 키 — `{타입}_{코드}`.

    PHP `buildSubscriptionQueryKey` 를 그대로 옮겼다. 코드에 `/`·`.` 이 들어가는 종목이 있어
    `_` 로 바꾸고, 32자를 넘지 않게 **코드 쪽을 자른다**(타입은 보존).
    """
    t = re.sub(r"[^A-Z0-9_]+", "", (query_type or "").strip().upper()).strip("_") or "EX"
    c = re.sub(r"[^A-Z0-9_]+", "", code.upper().replace("/", "_").replace(".", "_")).strip("_") or "UNKNOWN"
    return f"{t}_{c[: max(1, 32 - (len(t) + 1))]}"


def _stock_api_mapping(stock_code: str, stock_market: str) -> tuple[str, str]:
    """한투 WebSocket 구독에 쓰는 (TR 코드, 종목키). 해외는 거래소 접두어가 붙는다."""
    return {
        "NYSE": ("HDFSCNT0", f"DNYS{stock_code}"),
        "NASDAQ": ("HDFSCNT0", f"DNAS{stock_code}"),
        "AMEX": ("HDFSCNT0", f"DAMS{stock_code}"),
    }.get((stock_market or "").upper(), ("H0STCNT0", stock_code))


@router.get("/stocks", response_class=HTMLResponse, include_in_schema=False)
async def stock_subscriptions(request: Request):
    """구독 종목 선택 화면. 이미 구독 중인 종목이 위로 온다."""
    page = max(1, _int_arg(request, "page", 1))
    market = _norm_market(request.query_params.get("market", "KR"))
    search = (request.query_params.get("search") or "").strip()[:50]
    offset = (page - 1) * _STOCK_PER_PAGE

    async with db_session() as db:
        me = await _require_admin(request, db)
        if me is None:
            return _deny("not_admin /admin/stocks")

        params: dict = {"limit": _STOCK_PER_PAGE, "offset": offset}
        if market == "COIN":
            src = ("Bithumb.coin_info ci LEFT JOIN (SELECT DISTINCT coin_code "
                   "FROM Bithumb.coin_last_ws_query) w ON ci.coin_code = w.coin_code")
            code_col, name_cols, prefix = "ci.coin_code", ("ci.coin_name_kr", "ci.coin_name_en"), "COIN"
            cols = ("ci.coin_code AS code, ci.coin_name_kr AS name_kr, ci.coin_name_en AS name_en, "
                    "'Bithumb' AS market, 'COIN' AS stock_type, ci.coin_price AS price, "
                    "(ci.coin_price * ci.coin_amount) AS cap")
            rank = "(ci.coin_price * ci.coin_amount) DESC, "
            where = []
        else:
            src = ("KoreaInvest.stock_info si LEFT JOIN (SELECT DISTINCT stock_code "
                   "FROM KoreaInvest.stock_last_ws_query) w ON si.stock_code = w.stock_code")
            code_col, name_cols, prefix = "si.stock_code", ("si.stock_name_kr", "si.stock_name_en"), "STOCK"
            cols = ("si.stock_code AS code, si.stock_name_kr AS name_kr, si.stock_name_en AS name_en, "
                    "si.stock_market AS market, si.stock_type, si.stock_price AS price, "
                    "si.stock_capitalization AS cap")
            rank = "si.stock_market ASC, si.stock_capitalization DESC, "
            markets = _KR_MARKETS if market == "KR" else _US_MARKETS
            where = [f"si.stock_market IN ({', '.join(repr(m) for m in markets)})"]

        if search:
            # 코드 접두일치 + 이름 부분일치. PHP `appendAdminSearchConditions` 와 같은 형태.
            parts = [f"{code_col} LIKE :code_pre"] + [f"{c} LIKE :name_like" for c in name_cols]
            where.append("(" + " OR ".join(parts) + ")")
            params["code_pre"] = f"{search}%"
            params["name_like"] = f"%{search}%"

        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        reg_col = "w.coin_code" if market == "COIN" else "w.stock_code"
        total = (await db.execute(
            text(f"SELECT COUNT(*) FROM {src} {where_sql}"), params)).scalar() or 0

        order = ""
        if search:
            order = f"CASE WHEN {code_col} LIKE :code_pre THEN 0 ELSE 1 END, "
        # 정렬은 PHP 와 같다 — 등록된 것이 먼저, 그다음 시가총액이 큰 순.
        rows = (await db.execute(text(
            f"SELECT {cols}, CASE WHEN {reg_col} IS NULL THEN 0 ELSE 1 END AS is_registered "
            f"FROM {src} {where_sql} "
            f"ORDER BY {order}is_registered DESC, {rank}{code_col} ASC "
            f"LIMIT :limit OFFSET :offset"), params)).all()

        # 지금 구독 중인 **전체** 선택키. 화면 밖 종목을 hidden 으로 유지하는 데 쓴다 —
        # 저장이 전체 교체라, 이걸 안 실어 보내면 다른 페이지 구독이 전부 해제된다.
        registered = {r[0] for r in (await db.execute(text(
            "SELECT CONCAT('STOCK:', stock_code) FROM KoreaInvest.stock_last_ws_query "
            "UNION SELECT CONCAT('COIN:', coin_code) FROM Bithumb.coin_last_ws_query"))).all()}
        counts = await _registered_counts(db)

        # 선택키 → 시장. "현재 시장 선택 수" 를 세는 데만 쓴다.
        #
        # ⚠️ PHP 는 `stock_info` **전체**(1.8만 종목)를 맵으로 만들어 화면에 실었다 —
        #    JSON 만 438KB 다. 여기서는 **초안에 들어갈 수 있는 것**, 즉 이미 구독 중인
        #    것과 지금 페이지에 보이는 것만 싣는다(~700개). 다른 페이지에서 고른 키는
        #    화면 쪽이 sessionStorage 에 누적해 둔다.
        market_map = {f"COIN:{r[0]}": "COIN" for r in (await db.execute(text(
            "SELECT coin_code FROM Bithumb.coin_last_ws_query"))).all()}
        market_map |= {f"STOCK:{r[0]}": _selection_market(r[1]) for r in (await db.execute(text(
            "SELECT q.stock_code, si.stock_market FROM KoreaInvest.stock_last_ws_query q "
            "JOIN KoreaInvest.stock_info si ON si.stock_code = q.stock_code"))).all()}
        ctx = await _shell_ctx(request, db, me.level)

    on_page = {f"{prefix}:{r.code}" for r in rows}
    keepers = sorted(registered - on_page)
    for r in rows:
        market_map[f"{prefix}:{r.code}"] = "COIN" if prefix == "COIN" else _selection_market(r.market)

    token = csrf.new_token(request)
    response = templates.TemplateResponse(
        request,
        "admin_stocks.html",
        {
            **ctx, "admin_menu": "stocks", "rows": rows, "prefix": prefix,
            "keepers": keepers,
            "registered_codes": sorted(registered), "market_map": market_map,
            # 저장 직후(`?sync=1`)에만 초안을 서버 값으로 덮는다. 안 그러면 방금 저장한
            # 내용이 남은 옛 초안에 다시 덮여 되돌아간다.
            "force_sync": request.query_params.get("sync") == "1",
            "market": market, "markets": _STOCK_MARKETS, "search": search,
            "page": page, "total": total,
            "total_pages": max(1, -(-total // _STOCK_PER_PAGE)),
            "counts": counts, "limits": _SUB_LIMITS,
            "csrf_token": token, "msg": request.query_params.get("msg"),
        },
    )
    csrf.attach(response, token)
    return response


async def _registered_counts(db) -> dict:
    """지금 구독 중인 종목을 KR/US/COIN 으로 세어 준다(한도 표시에 쓴다)."""
    kr = us = 0
    for (mkt,) in (await db.execute(text(
        "SELECT si.stock_market FROM KoreaInvest.stock_last_ws_query q "
        "JOIN KoreaInvest.stock_info si ON si.stock_code = q.stock_code"))).all():
        if _selection_market(mkt) == "US":
            us += 1
        else:
            kr += 1
    coin = (await db.execute(text("SELECT COUNT(*) FROM Bithumb.coin_last_ws_query"))).scalar() or 0
    return {"KR": kr, "US": us, "COIN": int(coin)}


@router.post("/stocks/subscriptions", include_in_schema=False)
async def stock_subscriptions_update(request: Request):
    """구독 종목 전체 교체.

    ⚠️ 화면에 보이는 페이지만 저장하는 게 아니라 **선택 목록 전체가 곧 최종 상태**다(PHP 와
    같다). DELETE 후 INSERT 라 한 트랜잭션으로 묶는다 — 중간에 끊기면 수집이 멈춘다.
    """
    form = await request.form()
    csrf_token = str(form.get("csrf_token", ""))
    market = _norm_market(str(form.get("current_market", "KR")))
    search = str(form.get("current_search", "")).strip()[:50]
    page = max(1, int(str(form.get("current_page", "1")) or 1))
    back = f"/admin/stocks?market={market}&page={page}" + (f"&search={quote(search)}" if search else "")

    if not csrf.valid(request, csrf_token):
        return _deny("csrf_invalid", back)

    stock_codes, coin_codes = set(), set()
    for raw in form.getlist("selected_codes"):
        m = _SELECTION_RE.match(str(raw))
        if not m:
            continue
        (stock_codes if m.group(1).upper() == "STOCK" else coin_codes).add(m.group(2).upper())

    # ⚠️ 빈 제출은 거부한다. 저장은 DELETE 후 INSERT 라 빈 목록이 곧 **전체 구독 해제**이고,
    #    그건 `23.stock_ticker` 의 수집이 멈춘다는 뜻이다. 전부 끊는 것이 목적인 경우는
    #    드문 반면, 화면 JS 가 죽으면 아무것도 안 실려 오는 사고는 실제로 일어날 수 있다.
    if not stock_codes and not coin_codes:
        return _deny("empty_selection", f"{back}&msg=선택한+종목이+없어+저장하지+않았습니다.+"
                                        "전부+해제하려면+관리자에게+문의하세요")

    async with db_session() as db:
        if await _require_admin(request, db) is None:
            return _deny("not_admin stocks_update")

        # 존재하는 종목만 남긴다 — 폼이 조작돼도 없는 코드가 ticker 로 넘어가지 않게.
        valid_stocks: dict[str, str] = {}
        if stock_codes:
            valid_stocks = {r[0].upper(): (r[1] or "").upper() for r in (await db.execute(
                text("SELECT stock_code, stock_market FROM KoreaInvest.stock_info "
                     "WHERE stock_code IN :codes").bindparams(bindparam("codes", expanding=True)),
                {"codes": list(stock_codes)})).all()}
        valid_coins: list[str] = []
        if coin_codes:
            valid_coins = [r[0].upper() for r in (await db.execute(
                text("SELECT coin_code FROM Bithumb.coin_info "
                     "WHERE coin_code IN :codes").bindparams(bindparam("codes", expanding=True)),
                {"codes": list(coin_codes)})).all()]

        kr = sum(1 for m in valid_stocks.values() if m in _KR_MARKETS)
        us = sum(1 for m in valid_stocks.values() if m in _US_MARKETS)
        if kr > _SUB_LIMITS["KR"]:
            return _deny(f"kr_limit:{kr}", f"{back}&msg=한국+종목은+최대+{_SUB_LIMITS['KR']}개까지+저장할+수+있습니다")
        if us > _SUB_LIMITS["US"]:
            return _deny(f"us_limit:{us}", f"{back}&msg=미국+종목은+최대+{_SUB_LIMITS['US']}개까지+저장할+수+있습니다")

        await db.execute(text("DELETE FROM KoreaInvest.stock_last_ws_query"))
        await db.execute(text("DELETE FROM Bithumb.coin_last_ws_query"))
        for code, mkt in valid_stocks.items():
            api_type, api_code = _stock_api_mapping(code, mkt)
            await db.execute(
                text("INSERT INTO KoreaInvest.stock_last_ws_query "
                     "(stock_query, stock_code, query_type, stock_api_type, stock_api_stock_code) "
                     "VALUES (:q, :c, 'EX', :at, :ac)"),
                {"q": _query_key("EX", code), "c": code, "at": api_type, "ac": api_code})
        for code in valid_coins:
            await db.execute(
                text("INSERT INTO Bithumb.coin_last_ws_query "
                     "(coin_query, coin_code, query_type, coin_api_type, coin_api_coin_code) "
                     "VALUES (:q, :c, 'EX', 'transaction', :ac)"),
                {"q": _query_key("EX", code), "c": code, "ac": f"{code}_KRW"})
        await db.commit()

    logger.info("구독 종목 교체: 한국 %s · 미국 %s · 코인 %s", kr, us, len(valid_coins))
    # `sync=1` 로 돌아간다 — 화면이 sessionStorage 초안을 방금 저장한 값으로 덮게 하려는 것이다.
    return RedirectResponse(
        f"{back}&sync=1&msg=저장했습니다.+한국+{kr}건,+미국+{us}건,+코인+{len(valid_coins)}건",
        status_code=status.HTTP_303_SEE_OTHER)


# ── 액면분할/병합 이벤트 ────────────────────────────────────────────
#
# 주식 화면 중 **여기만 `BlogTest` 테이블(`stock_split_events`)로 끝난다.** 나머지
# (`/stocks` 계열·구독 관리)는 `KoreaInvest`·`Bithumb`·`candle`·`tick` 을 봐야 하는데
# `blog_api` 계정에 그 권한이 없어 아직 못 옮긴다.

#: 시장 구분 — DB 가 enum('KR','US','COIN') 이라 이 셋만 받는다.
_SPLIT_MARKETS = ("KR", "US", "COIN")
_SPLIT_PER_PAGE = 50
_SPLIT_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


@router.get("/stock-splits", response_class=HTMLResponse, include_in_schema=False)
async def stock_splits(request: Request):
    """액면분할/병합 이벤트 목록. 최신 이벤트가 위로 온다."""
    page = max(1, _int_arg(request, "page", 1))
    offset = (page - 1) * _SPLIT_PER_PAGE

    async with db_session() as db:
        me = await _require_admin(request, db)
        if me is None:
            return _deny("not_admin /admin/stock-splits")

        total = (await db.execute(text("SELECT COUNT(*) FROM stock_split_events"))).scalar() or 0
        rows = (
            await db.execute(
                text(
                    "SELECT id, stock_code, market, event_date, ratio_from, ratio_to, "
                    "       description, created_at "
                    "FROM stock_split_events "
                    "ORDER BY event_date DESC, id DESC "
                    "LIMIT :limit OFFSET :offset"
                ),
                {"limit": _SPLIT_PER_PAGE, "offset": offset},
            )
        ).all()
        ctx = await _shell_ctx(request, db, me.level)

    token = csrf.new_token(request)
    response = templates.TemplateResponse(
        request,
        "admin_stock_splits.html",
        {
            **ctx,
            "admin_menu": "stock-splits",
            "rows": rows,
            "markets": _SPLIT_MARKETS,
            "page": page,
            "total_pages": max(1, -(-total // _SPLIT_PER_PAGE)),
            "total": total,
            "csrf_token": token,
            "msg": request.query_params.get("msg"),
        },
    )
    csrf.attach(response, token)
    return response


@router.post("/stock-splits/create", include_in_schema=False)
async def stock_split_create(
    request: Request,
    csrf_token: str = Form(""),
    stock_code: str = Form(""),
    market: str = Form(""),
    event_date: str = Form(""),
    ratio_from: int = Form(0),
    ratio_to: int = Form(0),
    description: str = Form(""),
):
    """이벤트 등록. 검증 규칙은 PHP `createSplitEvent` 를 그대로 옮겼다."""
    if not csrf.valid(request, csrf_token):
        return _deny("csrf_invalid", "/admin/stock-splits")

    stock_code = stock_code.strip().upper()
    market = market.strip().upper()
    event_date = event_date.strip()
    # PHP 는 `max(1, (int)...)` 로 0 이하를 1 로 끌어올린다 — 같은 동작을 유지한다.
    ratio_from = max(1, ratio_from)
    ratio_to = max(1, ratio_to)

    if not stock_code or not event_date:
        return _deny("missing_fields", "/admin/stock-splits?msg=종목+코드와+이벤트+일시는+필수입니다")
    if market not in _SPLIT_MARKETS:
        return _deny(f"invalid_market:{market}", "/admin/stock-splits?msg=유효하지+않은+시장입니다")
    if ratio_from == ratio_to:
        return _deny("same_ratio", "/admin/stock-splits?msg=변환+전후+비율이+동일합니다")
    if not _SPLIT_DATE_RE.match(event_date):
        return _deny("invalid_date", "/admin/stock-splits?msg=유효하지+않은+날짜+형식입니다")

    async with db_session() as db:
        if await _require_admin(request, db) is None:
            return _deny("not_admin split_create")
        await db.execute(
            text(
                "INSERT INTO stock_split_events "
                "(stock_code, market, event_date, ratio_from, ratio_to, description) "
                "VALUES (:code, :market, :d, :rf, :rt, :desc)"
            ),
            {
                "code": stock_code, "market": market, "d": event_date[:10],
                "rf": ratio_from, "rt": ratio_to, "desc": description.strip()[:200],
            },
        )
        await db.commit()

    logger.info("분할이벤트 등록: %s %s %s %s:%s", market, stock_code, event_date, ratio_from, ratio_to)
    return RedirectResponse("/admin/stock-splits?msg=등록했습니다",
                            status_code=status.HTTP_303_SEE_OTHER)


@router.post("/stock-splits/delete", include_in_schema=False)
async def stock_split_delete(
    request: Request,
    csrf_token: str = Form(""),
    event_id: int = Form(...),
):
    """이벤트 삭제."""
    if not csrf.valid(request, csrf_token):
        return _deny("csrf_invalid", "/admin/stock-splits")

    async with db_session() as db:
        if await _require_admin(request, db) is None:
            return _deny("not_admin split_delete")
        r = await db.execute(
            text("DELETE FROM stock_split_events WHERE id = :i"), {"i": event_id}
        )
        await db.commit()

    if r.rowcount == 0:
        return _deny("split_not_found", "/admin/stock-splits?msg=이벤트를+찾을+수+없습니다")
    logger.info("분할이벤트 삭제: id=%s", event_id)
    return RedirectResponse("/admin/stock-splits?msg=삭제했습니다",
                            status_code=status.HTTP_303_SEE_OTHER)


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
    # ⚠️ 원본 폼의 필드 이름이 `device_name` 이다 — 화면을 원본 마크업으로 되돌리면서
    #    맞췄다. `name` 으로 받으면 값이 안 들어와 조용히 "이름을 확인하세요" 가 뜬다.
    device_name: str = Form(""),
    ip_range: str = Form(""),
    mac_address: str = Form(""),
):
    if not csrf.valid(request, csrf_token):
        return _deny("csrf_invalid", "/admin/wol")
    if not device_name.strip() or _magic_packet(mac_address) is None:
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
            {"n": device_name.strip(), "ip": ip_range.strip(), "m": mac_address.strip()},
        )
        await db.commit()

    logger.info("WOL 장치 추가: %s", device_name)
    return RedirectResponse("/admin/wol?msg=추가했습니다",
                            status_code=status.HTTP_303_SEE_OTHER)


@router.post("/wol/update", include_in_schema=False)
async def wol_update(
    request: Request,
    csrf_token: str = Form(""),
    device_id: int = Form(0),
    device_name: str = Form(""),
    ip_range: str = Form(""),
    mac_address: str = Form(""),
):
    if not csrf.valid(request, csrf_token):
        return _deny("csrf_invalid", "/admin/wol")
    if not device_name.strip() or _magic_packet(mac_address) is None:
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
            {"n": device_name.strip(), "ip": ip_range.strip(), "m": mac_address.strip(), "i": device_id},
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
    """관리자 진입점. 대시보드가 없어 첫 메뉴로 보낸다(로그 화면을 걷어내기 전엔 그쪽이었다)."""
    async with db_session() as db:
        if await _require_admin(request, db) is None:
            return _deny("not_admin /admin")
    return RedirectResponse("/admin/categories", status_code=status.HTTP_303_SEE_OTHER)
