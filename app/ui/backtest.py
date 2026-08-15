"""백테스트 — 포트폴리오·프리셋 CRUD 와 조회 기간 API.

PHP `StockController` 의 백테스트 계열 중 **DB 작업만** 옮긴 것이다. 시뮬레이션 엔진
(`POST /stocks/api/backtest`, `BacktestService` 1,270줄)과 화면(`/stocks/backtest`)은
아직 `php-final` 태그에만 있다.

## 두 저장소가 소유권을 다르게 본다

- **포트폴리오**(`backtest_portfolio`)는 **IP 로** 주인을 가린다. 로그인 없이 백테스트를
  돌릴 수 있어서다. 이름 수정은 저장할 때와 같은 IP 에서만 된다.
- **프리셋**(`backtest_preset`)은 **로그인 계정으로** 가린다(`user_index`). 그래서 프리셋
  API 는 전부 로그인이 필요하다.

⚠️ IP 는 `request.client.host` 로 얻는다. uvicorn 이 `--proxy-headers` 로 떠 있어
   X-Forwarded-For 가 반영된다 — 이게 없으면 모두가 게이트웨이 IP 하나로 보여
   **아무나 남의 포트폴리오 이름을 고칠 수 있게 된다.**

## `_require_internal`

PHP `BaseController::requireInternalRequest` 를 옮긴 것이다. 이 API 들은 CSRF 토큰이
없다(JSON 본문이라 폼 토큰을 실을 자리가 없다). 대신 `X-Requested-With` 와
Origin·Referer 를 본다 — 브라우저가 교차 출처에서 임의로 붙일 수 없는 값들이다.
"""

import json
import logging
from urllib.parse import urlparse

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core import blog_user
from app.db.session import db_session
from app.ui.stocks import _resolve_is_coin, _resolve_source

logger = logging.getLogger(__name__)
router = APIRouter()

_MAX_PRESETS_PER_USER = 20
_MAX_RANGE_CODES = 15


def _require_internal(request: Request) -> JSONResponse | None:
    """자사 화면에서 온 XHR 인지 확인. 아니면 403 응답을 돌려준다(통과면 None).

    PHP 와 같은 기준이다: `X-Requested-With: XMLHttpRequest` 가 있어야 하고,
    Origin 또는 Referer 의 호스트가 지금 호스트와 같아야 한다. 둘 다 없으면 거절한다.
    """
    if request.headers.get("x-requested-with") != "XMLHttpRequest":
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    host = request.url.hostname
    for header in ("origin", "referer"):
        raw = request.headers.get(header)
        if raw and urlparse(raw).hostname == host:
            return None
    return JSONResponse({"error": "Forbidden"}, status_code=403)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def _json_body(request: Request) -> dict | None:
    """JSON 본문. 객체가 아니면 None — 호출부가 400 을 돌려준다."""
    try:
        body = json.loads(await request.body())
    except (ValueError, UnicodeDecodeError):
        return None
    return body if isinstance(body, dict) else None


async def _me(db, request: Request):
    """로그인한 블로그 계정. ⚠️ `user_index` 는 0 이 실제 계정이라 `is None` 으로 본다."""
    return await blog_user.find(db, getattr(request.state, "user", None))


def _need_login() -> JSONResponse:
    return JSONResponse({"success": False, "error": "로그인이 필요합니다."}, status_code=401)


# ---------------------------------------------------------------------------
# 조회 가능 기간
# ---------------------------------------------------------------------------

async def _candle_date_range(db, code: str, market: str) -> tuple | None:
    """이 종목 캔들의 (첫날, 마지막날). 테이블이 없으면 None."""
    is_coin = await _resolve_is_coin(db, code, market)
    table = await _resolve_source(db, "candle", code, "c" if is_coin else "s")
    if table is None:
        return None
    row = (await db.execute(text(
        "SELECT DATE(MIN(execution_datetime)) AS mn, DATE(MAX(execution_datetime)) AS mx "
        f"FROM `candle`.`{table}`"))).first()
    if not row or row.mn is None or row.mx is None:
        return None
    return row.mn, row.mx


@router.get("/stocks/api/date-range", include_in_schema=False)
async def api_date_range(request: Request):
    """여러 종목을 **함께** 백테스트할 수 있는 기간 = 각 종목 보유 기간의 교집합.

    시작일은 가장 늦은 시작일, 종료일은 가장 이른 종료일을 고른다 — 한 종목이라도
    데이터가 없는 날은 비교가 성립하지 않기 때문이다.
    """
    if (deny := _require_internal(request)) is not None:
        return deny

    codes = [c.strip() for c in (request.query_params.get("codes") or "").split(",") if c.strip()]
    markets = [m.strip() for m in (request.query_params.get("markets") or "").split(",") if m.strip()]
    if not codes:
        return JSONResponse({"success": True, "data": None})
    codes = codes[:_MAX_RANGE_CODES]

    lo = hi = None
    async with db_session() as db:
        for i, code in enumerate(codes):
            rng = await _candle_date_range(db, code, markets[i] if i < len(markets) else "")
            if rng is None:
                continue
            mn, mx = rng
            lo = mn if lo is None or mn > lo else lo
            hi = mx if hi is None or mx < hi else hi

    if lo is None or hi is None or lo > hi:
        return JSONResponse({"success": True, "data": None})
    return JSONResponse(
        {"success": True, "data": {"min": lo.isoformat(), "max": hi.isoformat()}},
        headers={"Cache-Control": "private, max-age=300"},
    )


# ---------------------------------------------------------------------------
# 포트폴리오 — 소유권은 IP 로 가린다
# ---------------------------------------------------------------------------

_PORTFOLIO_LIST_COLS = (
    "portfolio_id, portfolio_name, ranking_score, ranking_grade, display_score, "
    "display_grade, metrics_json, stock_summary, strategy, period_start, period_end, "
    "initial_capital, monthly_dca, updated_at"
)


def _row_to_dict(row, *json_cols: str) -> dict:
    """행을 dict 로. `*_json` 컬럼은 풀어서 접미사 없는 키로 바꾼다(PHP 와 같은 모양)."""
    out = dict(row._mapping)
    for col in json_cols:
        raw = out.pop(col, None)
        key = col[:-5]                                  # config_json → config
        try:
            out[key] = json.loads(raw) if raw else None
        except (ValueError, TypeError):
            out[key] = None
    return out


@router.get("/stocks/api/top-portfolios", include_in_schema=False)
async def api_top_portfolios(request: Request):
    """점수 상위 10개. `/stocks` 사이드바가 서버 렌더로 쓰는 것과 같은 목록이다."""
    if (deny := _require_internal(request)) is not None:
        return deny

    async with db_session() as db:
        rows = (await db.execute(text(
            f"SELECT {_PORTFOLIO_LIST_COLS} FROM backtest_portfolio "
            "ORDER BY ranking_score DESC, updated_at DESC LIMIT 10"))).all()
    return JSONResponse(jsonable([_row_to_dict(r, "metrics_json") for r in rows]))


@router.get("/stocks/api/portfolio", include_in_schema=False)
async def api_portfolio(request: Request):
    """포트폴리오 하나. 저장된 설정(config)까지 준다 — 화면이 폼을 복원하는 데 쓴다."""
    if (deny := _require_internal(request)) is not None:
        return deny

    pid = _int(request.query_params.get("id"))
    if pid <= 0:
        return JSONResponse({"success": False, "error": "Invalid id"}, status_code=400)

    async with db_session() as db:
        row = (await db.execute(text(
            "SELECT portfolio_id, portfolio_name, config_json, display_score, display_grade, "
            "ranking_score, ranking_grade, metrics_json, stock_summary, strategy, "
            "period_start, period_end, initial_capital, monthly_dca, created_at, updated_at "
            "FROM backtest_portfolio WHERE portfolio_id = :id"), {"id": pid})).first()

    if row is None:
        return JSONResponse({"success": False, "error": "Not found"}, status_code=404)
    # ip_address 는 애초에 SELECT 하지 않는다 — 소유자 IP 가 응답에 실리면 안 된다.
    return JSONResponse(jsonable(_row_to_dict(row, "config_json", "metrics_json")))


@router.post("/stocks/api/portfolio/name", include_in_schema=False)
async def api_portfolio_rename(request: Request):
    """이름 수정. **저장할 때와 같은 IP 에서만** 된다(로그인이 없어 IP 가 유일한 단서다)."""
    if (deny := _require_internal(request)) is not None:
        return deny

    body = await _json_body(request)
    if body is None:
        return JSONResponse({"success": False, "error": "Invalid JSON"}, status_code=400)

    pid = _int(body.get("id"))
    name = str(body.get("name") or "").strip()[:100]
    if pid <= 0 or not name:
        return JSONResponse({"success": False, "error": "id and name are required"}, status_code=400)

    ip = _client_ip(request)
    async with db_session() as db:
        owner = (await db.execute(
            text("SELECT ip_address FROM backtest_portfolio WHERE portfolio_id = :id"),
            {"id": pid})).scalar()
        if owner is None or owner != ip:
            logger.warning("포트폴리오 이름 수정 거절: id=%s ip=%s", pid, ip)
            return JSONResponse({"success": False, "error": "수정 권한이 없습니다."}, status_code=403)
        await db.execute(
            text("UPDATE backtest_portfolio SET portfolio_name = :n WHERE portfolio_id = :id"),
            {"n": name, "id": pid})
        await db.commit()

    logger.info("포트폴리오 이름 수정: id=%s name=%s", pid, name)
    return JSONResponse({"success": True})


# ---------------------------------------------------------------------------
# 프리셋 — 소유권은 로그인 계정으로 가린다
# ---------------------------------------------------------------------------

@router.get("/stocks/api/presets", include_in_schema=False)
async def api_presets(request: Request):
    """내 프리셋 목록(최근 수정순). 설정 본문은 주지 않는다 — 목록은 가벼워야 한다."""
    if (deny := _require_internal(request)) is not None:
        return deny

    async with db_session() as db:
        me = await _me(db, request)
        if me is None:
            return _need_login()
        rows = (await db.execute(text(
            "SELECT preset_id, preset_name, stock_summary, strategy, updated_at "
            "FROM backtest_preset WHERE user_index = :u ORDER BY updated_at DESC"),
            {"u": me.user_index})).all()
    return JSONResponse(jsonable([dict(r._mapping) for r in rows]))


@router.get("/stocks/api/preset", include_in_schema=False)
async def api_preset_load(request: Request):
    """프리셋 하나. 남의 것은 못 본다 — user_index 를 WHERE 에 함께 넣는다."""
    if (deny := _require_internal(request)) is not None:
        return deny

    pid = _int(request.query_params.get("id"))
    if pid <= 0:
        return JSONResponse({"success": False, "error": "Invalid id"}, status_code=400)

    async with db_session() as db:
        me = await _me(db, request)
        if me is None:
            return _need_login()
        row = (await db.execute(text(
            "SELECT preset_id, preset_name, config_json, stock_summary, strategy, updated_at "
            "FROM backtest_preset WHERE preset_id = :id AND user_index = :u"),
            {"id": pid, "u": me.user_index})).first()

    if row is None:
        return JSONResponse({"success": False, "error": "프리셋을 찾을 수 없습니다."}, status_code=404)
    return JSONResponse(jsonable(_row_to_dict(row, "config_json")))


def _stock_summary(stocks: list) -> str:
    """"삼성전자 60% + SK하이닉스 40%" 꼴의 한 줄 요약. 5종목까지만 펴고 나머지는 센다.

    ⚠️ 비중은 `:g` 로 찍는다. PHP 는 `round($w, 1)` 한 float 을 문자열에 이어 붙이는데
       PHP 의 float→string 은 20.0 을 `20` 으로 준다. 파이썬 기본 포맷은 `20.0` 이라
       그대로 두면 기존 데이터(`... 20% + ...`)와 모양이 어긋난다.
    """
    parts = [f"{s.get('name') or s.get('code')} {round(float(s.get('weight') or 0), 1):g}%"
             for s in stocks[:5]]
    summary = " + ".join(parts)[:200]
    if len(stocks) > 5:
        summary += f" 외 {len(stocks) - 5}종목"
    return summary


@router.post("/stocks/api/preset/save", include_in_schema=False)
async def api_preset_save(request: Request):
    """프리셋 저장. **같은 이름이면 덮어쓴다**(계정+이름이 UNIQUE)."""
    if (deny := _require_internal(request)) is not None:
        return deny

    body = await _json_body(request)
    if body is None:
        return JSONResponse({"success": False, "error": "Invalid JSON"}, status_code=400)

    name = str(body.get("name") or "").strip()[:100]
    if not name:
        return JSONResponse({"success": False, "error": "프리셋 이름을 입력하세요."}, status_code=400)

    config = body.get("config")
    if not isinstance(config, dict) or not config.get("stocks"):
        return JSONResponse({"success": False, "error": "유효한 설정이 필요합니다."}, status_code=400)

    stocks = config["stocks"] if isinstance(config["stocks"], list) else []
    params = {
        "cfg": json.dumps(config, ensure_ascii=False),
        "sum": _stock_summary(stocks),
        "st": str(config.get("strategy") or "buyhold")[:20],
        "name": name,
    }

    async with db_session() as db:
        me = await _me(db, request)
        if me is None:
            return _need_login()
        params["u"] = me.user_index

        existing = (await db.execute(text(
            "SELECT preset_id FROM backtest_preset WHERE user_index = :u AND preset_name = :name"),
            params)).scalar()
        if existing is not None:
            await db.execute(text(
                "UPDATE backtest_preset SET config_json = :cfg, stock_summary = :sum, "
                "strategy = :st WHERE preset_id = :id"), {**params, "id": existing})
            preset_id = int(existing)
        else:
            n = (await db.execute(text(
                "SELECT COUNT(*) FROM backtest_preset WHERE user_index = :u"), params)).scalar() or 0
            if n >= _MAX_PRESETS_PER_USER:
                return JSONResponse(
                    {"success": False,
                     "error": f"프리셋은 최대 {_MAX_PRESETS_PER_USER}개까지 저장 가능합니다."},
                    status_code=400)
            res = await db.execute(text(
                "INSERT INTO backtest_preset (user_index, preset_name, config_json, "
                "stock_summary, strategy) VALUES (:u, :name, :cfg, :sum, :st)"), params)
            preset_id = int(res.lastrowid)
        await db.commit()

    logger.info("프리셋 저장: user=%s id=%s name=%s", me.user_id, preset_id, name)
    return JSONResponse({"success": True, "presetId": preset_id})


@router.post("/stocks/api/preset/delete", include_in_schema=False)
async def api_preset_delete(request: Request):
    """프리셋 삭제. 남의 것은 못 지운다 — user_index 를 WHERE 에 함께 넣는다."""
    if (deny := _require_internal(request)) is not None:
        return deny

    body = await _json_body(request)
    if body is None:
        return JSONResponse({"success": False, "error": "Invalid JSON"}, status_code=400)

    pid = _int(body.get("id"))
    if pid <= 0:
        return JSONResponse({"success": False, "error": "Invalid id"}, status_code=400)

    async with db_session() as db:
        me = await _me(db, request)
        if me is None:
            return _need_login()
        res = await db.execute(text(
            "DELETE FROM backtest_preset WHERE preset_id = :id AND user_index = :u"),
            {"id": pid, "u": me.user_index})
        await db.commit()

    if res.rowcount <= 0:
        logger.warning("프리셋 삭제 거절: id=%s user=%s", pid, me.user_id)
        return JSONResponse({"success": False, "error": "삭제 권한이 없거나 존재하지 않습니다."},
                            status_code=403)
    logger.info("프리셋 삭제: user=%s id=%s", me.user_id, pid)
    return JSONResponse({"success": True})


def _int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def jsonable(data):
    """`{success, data}` 로 감싸면서 date·datetime·Decimal 을 JSON 이 아는 값으로 바꾼다."""
    from datetime import date, datetime
    from decimal import Decimal

    def conv(v):
        if isinstance(v, datetime):
            return v.strftime("%Y-%m-%d %H:%M:%S")     # DB 가 KST 다 — 변환하지 않는다
        if isinstance(v, date):
            return v.isoformat()
        if isinstance(v, Decimal):
            f = float(v)
            return int(f) if f.is_integer() else f
        if isinstance(v, dict):
            return {k: conv(x) for k, x in v.items()}
        if isinstance(v, list):
            return [conv(x) for x in v]
        return v

    return {"success": True, "data": conv(data)}
