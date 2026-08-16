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

## 내부요청 가드

여기 API 들은 CSRF 토큰이 없다(JSON 본문이라 폼 토큰을 실을 자리가 없다). 대신
`app.core.csrf.require_internal` 로 `X-Requested-With` 와 Origin·Referer 를 본다 —
PHP `BaseController::requireInternalRequest` 와 같은 기준이다.
"""

import asyncio
import hashlib
import json
import logging
import math
import re
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import text

from app.core import blog_user
from app.core.csrf import require_internal
from app.db.session import db_session
from app.services import backtest as engine
from app.ui.routes import _shell_ctx, templates
from app.ui.stocks import _level, _resolve_is_coin, _resolve_source, candle_rows

logger = logging.getLogger(__name__)
router = APIRouter()

_MAX_PRESETS_PER_USER = 20
_MAX_RANGE_CODES = 15


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


@router.get("/stocks/backtest", response_class=HTMLResponse, include_in_schema=False)
async def backtest_page(request: Request):
    """백테스팅 화면. 폼만 서버가 그리고 계산·차트는 전부 `/js/backtest.js` 가 한다.

    `?portfolio=<id>` 로 들어오면 그 설정을 복원하는데, 그것도 JS 가
    `/stocks/api/portfolio` 를 불러 처리한다 — 서버는 여기서 아무것도 읽지 않는다.
    """
    async with db_session() as db:
        ctx = await _shell_ctx(request, db, _level(request))
    return templates.TemplateResponse(
        request, "stocks_backtest.html",
        {**ctx, "is_stock_page": True, "hide_sidebar": True})


@router.get("/stocks/api/date-range", include_in_schema=False)
async def api_date_range(request: Request):
    """여러 종목을 **함께** 백테스트할 수 있는 기간 = 각 종목 보유 기간의 교집합.

    시작일은 가장 늦은 시작일, 종료일은 가장 이른 종료일을 고른다 — 한 종목이라도
    데이터가 없는 날은 비교가 성립하지 않기 때문이다.
    """
    if (deny := require_internal(request)) is not None:
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
    if (deny := require_internal(request)) is not None:
        return deny

    async with db_session() as db:
        rows = (await db.execute(text(
            f"SELECT {_PORTFOLIO_LIST_COLS} FROM backtest_portfolio "
            "ORDER BY ranking_score DESC, updated_at DESC LIMIT 10"))).all()
    return JSONResponse(jsonable([_row_to_dict(r, "metrics_json") for r in rows]))


@router.get("/stocks/api/portfolio", include_in_schema=False)
async def api_portfolio(request: Request):
    """포트폴리오 하나. 저장된 설정(config)까지 준다 — 화면이 폼을 복원하는 데 쓴다."""
    if (deny := require_internal(request)) is not None:
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
    if (deny := require_internal(request)) is not None:
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
    if (deny := require_internal(request)) is not None:
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
    if (deny := require_internal(request)) is not None:
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
    if (deny := require_internal(request)) is not None:
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
    if (deny := require_internal(request)) is not None:
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


# ---------------------------------------------------------------------------
# 시뮬레이션 엔진
# ---------------------------------------------------------------------------

_MAX_STOCKS = 10
_MAX_BENCHMARKS = 5
_MAX_SIGNAL_RULES = 20
_MAX_YEARS = 30
_STRATEGIES = ("buyhold", "rebalance", "signal")
_REBALANCE_PERIODS = ("monthly", "quarterly", "semiannual", "annual")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 백테스트는 CPU 를 오래 문다. PHP 는 파일 잠금으로 동시 2건까지만 돌렸다 — 여기서도
# 같은 수로 막는다. ⚠️ 계산은 `to_thread` 로 뺀다. 이벤트 루프에서 그대로 돌리면
# 한 건이 도는 동안 블로그 화면까지 전부 멈춘다.
_backtest_slots = asyncio.Semaphore(2)


def _f(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _s(v, fallback: str = "") -> str:
    """PHP `sanitizeInput` 자리 — 문자열로 좁히고 앞뒤 공백을 턴다."""
    return str(v).strip() if isinstance(v, (str, int, float)) else fallback


def _norm_config(body: dict) -> tuple[dict | None, str | None]:
    """입력을 검증·정제한다. (설정, 오류메시지) — 오류가 있으면 설정이 None."""
    stocks_in = body.get("stocks")
    if not stocks_in or not isinstance(stocks_in, list):
        return None, "stocks is required"
    start, end = body.get("startDate"), body.get("endDate")
    if not start or not end:
        return None, "startDate and endDate are required"
    if len(stocks_in) > _MAX_STOCKS:
        return None, f"Maximum {_MAX_STOCKS} stocks allowed"
    benchmarks_in = body.get("benchmarks") or []
    if isinstance(benchmarks_in, list) and len(benchmarks_in) > _MAX_BENCHMARKS:
        return None, f"Maximum {_MAX_BENCHMARKS} benchmarks allowed"
    if not _DATE_RE.match(str(start)) or not _DATE_RE.match(str(end)):
        return None, "Invalid date format"
    if str(start) >= str(end):
        return None, "startDate must be before endDate"
    strategy = body.get("strategy") or "buyhold"
    if strategy not in _STRATEGIES:
        return None, "Invalid strategy"

    d0 = datetime.strptime(str(start), "%Y-%m-%d")
    d1 = datetime.strptime(str(end), "%Y-%m-%d")
    if (d1 - d0).total_seconds() / (365.25 * 86400) > _MAX_YEARS:
        return None, f"최대 {_MAX_YEARS}년까지 시뮬레이션 가능합니다."

    fees_in = body.get("fees") or {}
    defer_in = body.get("dcaDefer") or {}
    return {
        "stocks": [{"code": _s(s.get("code")), "name": _s(s.get("name"), _s(s.get("code"))),
                    "market": _s(s.get("market")), "weight": _f(s.get("weight"))}
                   for s in stocks_in[:_MAX_STOCKS] if isinstance(s, dict)],
        "benchmarks": [{"code": _s(b.get("code")), "market": _s(b.get("market")),
                        "name": _s(b.get("name"), _s(b.get("code")))}
                       for b in (benchmarks_in or [])[:_MAX_BENCHMARKS] if isinstance(b, dict)],
        "startDate": str(start), "endDate": str(end), "strategy": strategy,
        "rebalancePeriod": (body.get("rebalancePeriod")
                            if body.get("rebalancePeriod") in _REBALANCE_PERIODS else "quarterly"),
        "signalRules": [{"indicator": _s(r.get("indicator")), "targetCode": _s(r.get("targetCode"))}
                        for r in (body.get("signalRules") or [])[:_MAX_SIGNAL_RULES]
                        if isinstance(r, dict)],
        "signalCombine": body.get("signalCombine") if body.get("signalCombine") in ("and", "or") else "or",
        "initialCapital": _clamp(_f(body.get("initialCapital")), 0, 1e12),
        "monthlyDCA": _clamp(_f(body.get("monthlyDCA")), 0, 1e10),
        "dcaDefer": {"enabled": bool(defer_in.get("enabled")),
                     "indicator": _s(defer_in.get("indicator"), "none") or "none"},
        "fees": {"KR": _clamp(_f(fees_in.get("KR"), 0.015), 0, 10),
                 "US": _clamp(_f(fees_in.get("US"), 0.2), 0, 10),
                 "COIN": _clamp(_f(fees_in.get("COIN"), 0.015), 0, 10)},
        "riskFreeRate": _clamp(_f(body.get("riskFreeRate"), 3), 0, 100),
    }, None


def _config_hash(stocks: list, strategy: str) -> str:
    """같은 조합을 다시 돌리면 새 행을 만들지 않고 덮어쓰기 위한 키(IP 와 짝을 이룬다)."""
    parts = sorted(f"{s['code']}:{engine._php_round(s['weight'], 2):g}" for s in stocks)
    return hashlib.md5(("|".join(parts) + "|" + strategy).encode()).hexdigest()


def _portfolio_name(stocks: list) -> str:
    names = [s.get("name") or s["code"] for s in stocks]
    if len(names) <= 3:
        return " · ".join(names)
    return " · ".join(names[:3]) + f" 외 {len(names) - 3}종목"


def _full_summary(stocks: list) -> str:
    """포트폴리오용 요약 — 프리셋과 달리 **전 종목**을 펴고 200자에서 자른다(PHP 그대로)."""
    return " + ".join(f"{s.get('name') or s['code']} {engine._php_round(s['weight'], 1):g}%"
                      for s in stocks)[:200]


async def _load_prices(db, config: dict) -> tuple[dict, dict]:
    """포트폴리오·벤치마크 종목의 일봉을 읽어 `{코드: {dates, ohlcv}}` 로 만든다.

    시작일보다 120일 앞에서부터 읽는다 — 이동평균·MACD 가 워밍업할 구간이 필요하다.
    """
    start = datetime.strptime(engine.warmup_start(config["startDate"]), "%Y-%m-%d")
    end = datetime.strptime(config["endDate"], "%Y-%m-%d").replace(hour=23, minute=59)

    async def fetch(items):
        out = {}
        for it in items:
            if not it["code"]:
                continue
            rows = await candle_rows(db, it["code"], it.get("market") or "", start, end, 15000, "1d")
            out[it["code"]] = engine.build_series(rows)
        return out

    return await fetch(config["stocks"]), await fetch(config["benchmarks"])


@router.post("/stocks/api/backtest", include_in_schema=False)
async def api_backtest(request: Request):
    """백테스트를 돌리고 결과를 돌려준다. 결과는 포트폴리오로도 자동 저장된다."""
    if (deny := require_internal(request)) is not None:
        return deny

    body = await _json_body(request)
    if body is None:
        return JSONResponse({"success": False, "error": "Invalid JSON"}, status_code=400)

    config, err = _norm_config(body)
    if config is None:
        return JSONResponse({"success": False, "error": err}, status_code=400)

    if _backtest_slots.locked():
        return JSONResponse({"success": False, "error": "서버가 바쁩니다. 잠시 후 다시 시도해주세요."},
                            status_code=503)

    async with _backtest_slots:
        async with db_session() as db:
            stock_data, bmk_data = await _load_prices(db, config)
        # 순수 계산이라 DB 연결을 쥔 채로 돌지 않는다.
        result = await asyncio.to_thread(engine.run, config, stock_data, bmk_data)

    if result is None:
        return JSONResponse({"success": False,
                             "error": "No data available for the selected stocks and period"},
                            status_code=404)

    portfolio_id = portfolio_name = None
    try:
        portfolio_id, portfolio_name = await _save_portfolio(request, config, result)
    except Exception:                                   # 저장이 실패해도 결과는 돌려준다
        logger.exception("포트폴리오 저장 실패")

    return JSONResponse(
        {"success": True, "data": _finite(result),
         "portfolioId": portfolio_id, "portfolioName": portfolio_name},
        headers={"Cache-Control": "private, no-cache"})


async def _save_portfolio(request: Request, config: dict, result: dict) -> tuple[int, str]:
    """같은 IP + 같은 종목조합이면 덮어쓰고, 아니면 새로 만든다."""
    name = _portfolio_name(config["stocks"])
    score = engine.compute_score(result["metrics"])
    params = {
        "name": name, "ip": _client_ip(request),
        "hash": _config_hash(config["stocks"], config["strategy"]),
        "cfg": json.dumps(config, ensure_ascii=False),
        "ds": score["score"], "dg": score["grade"],
        "rs": result["rankingScore"], "rg": result["rankingGrade"],
        "metrics": json.dumps(_finite(result["metrics"]), ensure_ascii=False),
        "summary": _full_summary(config["stocks"]), "strategy": config["strategy"],
        "ps": config["startDate"], "pe": config["endDate"],
        "cap": int(config["initialCapital"]), "dca": int(config["monthlyDCA"]),
    }
    async with db_session() as db:
        existing = (await db.execute(text(
            "SELECT portfolio_id FROM backtest_portfolio "
            "WHERE ip_address = :ip AND config_hash = :hash"), params)).scalar()
        if existing is not None:
            await db.execute(text(
                "UPDATE backtest_portfolio SET portfolio_name = :name, config_json = :cfg, "
                "display_score = :ds, display_grade = :dg, ranking_score = :rs, "
                "ranking_grade = :rg, metrics_json = :metrics, stock_summary = :summary, "
                "strategy = :strategy, period_start = :ps, period_end = :pe, "
                "initial_capital = :cap, monthly_dca = :dca WHERE portfolio_id = :id"),
                {**params, "id": existing})
            pid = int(existing)
        else:
            res = await db.execute(text(
                "INSERT INTO backtest_portfolio (portfolio_name, ip_address, config_hash, "
                "config_json, display_score, display_grade, ranking_score, ranking_grade, "
                "metrics_json, stock_summary, strategy, period_start, period_end, "
                "initial_capital, monthly_dca) VALUES (:name, :ip, :hash, :cfg, :ds, :dg, "
                ":rs, :rg, :metrics, :summary, :strategy, :ps, :pe, :cap, :dca)"), params)
            pid = int(res.lastrowid)
        await db.commit()
    logger.info("백테스트 저장: id=%s score=%s %s", pid, result["rankingScore"], name)
    return pid, name


def _finite(v):
    """`inf`·`nan` 을 None 으로. 소르티노는 하방 변동이 없으면 무한대가 나오는데,
    그대로 내보내면 표준 JSON 이 아니라 브라우저가 파싱하다 죽는다."""
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if isinstance(v, dict):
        return {k: _finite(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_finite(x) for x in v]
    return v


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
