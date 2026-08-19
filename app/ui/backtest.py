"""백테스트 — **화면과 계산 도우미만** 남은 모듈.

여기에 있던 JSON API 아홉 개(`/stocks/api/{backtest,portfolio*,preset*,date-range}`)는
2026-08-19 에 `app/api/backtest_v1.py`(`/api/v1/backtest/*`)로 옮기고 지웠다. 옛것은
`require_internal`(`X-Requested-With` + Origin/Referer)을 요구해 **브라우저 전용**이라
앱·스크립트가 원리적으로 못 붙었고, 실패를 200 에 `{success:false}` 로 실었다.

지금 이 파일이 갖는 것:

- `/stocks/backtest` 화면(껍데기만 그린다 — 계산·차트는 `/js/backtest.js` 가 한다)
- API 와 **함께 쓰는 계산 도우미** — `_norm_config`·`_load_prices`·`_save_portfolio`·
  `_candle_date_range`·`_stock_summary`·`_finite`·`_backtest_slots`.
  `backtest_v1` 이 이걸 임포트해 쓴다. 검증·정규화를 다시 짜면 화면과 결과가 갈라진다.

## 소유권은 계정이다

- **포트폴리오**(`backtest_portfolio`) — 로그인해서 돌린 것은 `user_index` 가 주인이고
  **비공개로 시작**한다. 비로그인 것은 주인이 없어 **공개 고정**이다(아무도 못 고친다).
- **프리셋**(`backtest_preset`) — `user_index` 로 가린다. 전부 로그인이 필요하다.

⚠️ 예전에는 포트폴리오를 **IP 로** 갈랐다. 그런데 앞단(NPM)이 진짜 클라이언트 IP 를 안
   넘겨 **외부 요청이 전부 게이트웨이 하나로 보였다** — 즉 모두가 같은 주인이라 누구나
   남의 포트폴리오 이름을 고칠 수 있었다. 그래서 계정 기준으로 바꿨다.
"""

import asyncio
import hashlib
import json
import logging
import math
import re
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import text

from app.core import blog_user
from app.db.session import db_session
from app.services import backtest as engine
from app.ui.routes import _shell_ctx, templates
from app.ui.stocks import _level, _resolve_is_coin, _resolve_source, candle_rows

logger = logging.getLogger(__name__)
router = APIRouter()

_MAX_PRESETS_PER_USER = 20
_MAX_RANGE_CODES = 15


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
    `/api/v1/backtest/portfolios/{id}` 를 불러 처리한다 — 서버는 여기서 아무것도 읽지 않는다.
    """
    async with db_session() as db:
        ctx = await _shell_ctx(request, db, _level(request))
    return templates.TemplateResponse(
        request, "stocks_backtest.html",
        {**ctx, "is_stock_page": True, "hide_sidebar": True})


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


async def _owner_index(request: Request) -> int | None:
    """이 요청의 포트폴리오 주인. 로그인 안 했으면 None."""
    user = getattr(request.state, "user", None)
    if user is None:
        return None
    async with db_session() as db:
        me = await blog_user.find(db, user)
    return None if me is None else me.user_index


async def _save_portfolio(request: Request, config: dict, result: dict) -> tuple[int, str, bool, bool]:
    """백테스트 결과를 포트폴리오로 남긴다.

    ⚠️ **소유권은 계정이다(2026-08-19).** 예전에는 `ip_address` 로 갈랐는데, 앞단(NPM)이
       진짜 클라이언트 IP 를 안 넘겨 **외부 요청이 전부 게이트웨이 하나로 보였다** —
       즉 모두가 같은 주인이라 누구나 남의 포트폴리오 이름을 바꿀 수 있었다.

    - 로그인 상태 → `user_index` 를 주인으로 두고 **비공개**로 시작한다. 남의 투자
      조합이 랭킹에 그냥 뜨는 것은 저장의 부작용이지 의도가 아니었다.
    - 비로그인 → 주인이 없으므로 **공개 고정**이다. 랭킹은 이쪽으로 채워진다.

    같은 주인 + 같은 종목조합이면 덮어쓴다(주인이 없으면 IP 대신 조합만 본다).
    """
    name = _portfolio_name(config["stocks"])
    owner = await _owner_index(request)
    score = engine.compute_score(result["metrics"])
    params = {
        "name": name,
        "owner": owner, "pub": 0 if owner is not None else 1,
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
        # ⚠️ 주인이 있으면 주인 기준으로, 없으면(비로그인) 조합만 보고 합친다.
        #    옛 `ip_address` 기준은 쓰지 않는다 — 모두가 같은 IP 라 남의 것을 덮어썼다.
        existing = (await db.execute(text(
            "SELECT portfolio_id FROM backtest_portfolio WHERE config_hash = :hash AND "
            + ("user_index = :owner" if owner is not None else "user_index IS NULL")),
            params)).scalar()
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
                # ⚠️ `ip_address` 는 더 이상 쓰지 않는다 — 소유권 근거에서 빠졌고,
                #    앞단이 진짜 IP 를 안 넘겨 게이트웨이만 쌓이던 값이다. 쓸모없는
                #    개인정보를 계속 모으지 않는다(옛 행은 그대로 둔다).
                "INSERT INTO backtest_portfolio (portfolio_name, user_index, is_public, "
                "config_hash, "
                "config_json, display_score, display_grade, ranking_score, ranking_grade, "
                "metrics_json, stock_summary, strategy, period_start, period_end, "
                "initial_capital, monthly_dca) VALUES (:name, :owner, :pub, :hash, "
                ":cfg, :ds, :dg, "
                ":rs, :rg, :metrics, :summary, :strategy, :ps, :pe, :cap, :dca)"), params)
            pid = int(res.lastrowid)
        await db.commit()
    logger.info("백테스트 저장: id=%s score=%s owner=%s %s", pid, result["rankingScore"], owner, name)
    # 화면이 토글을 보여줄지 판단하려면 **내 것인지**와 현재 공개 여부가 필요하다.
    return pid, name, owner is not None, bool(params["pub"])


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


