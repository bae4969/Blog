"""종목·시장·관심 종목·백테스트를 상담 AI 가 조회하는 MCP 도구(2026-10-19). **조회만** 한다.

화면이 쓰는 API 함수([stocks_v1](stocks_v1.py)·[quotes_v1](quotes_v1.py))를 그대로 부른다 — 같은 값이 화면과 AI 에
다르게 나가지 않게(옛 `stock_price` 가 늦어 화면과 API 가 갈렸던 일, 2026-08-19). 개인 데이터(관심 종목·백테스트
포트폴리오)는 그 API 가 Bearer 요청을 받아서, 토큰이 묶인 사람(`user_index`)으로 직접 읽는다.

⚠️ 큰 응답은 줄여 낸다 — 캔들은 최대 200개·줄 하나를 배열로, 히트맵은 시총 상위·등락 상하위만. 답 하나가 수십 KB 를
   넘으면 다음 도구 호출과 답이 느려진다.
"""

import json
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import bindparam, text

from app.api import quotes_v1, stocks_v1
from app.api.mcp import RO, obj
from app.ui.stocks import _latest_quotes, _stock_page

WRITE_TOOLS: tuple = ()

_MARKET = {"type": "string", "enum": ["KR", "US", "COIN"]}
_TF = {"type": "string", "enum": ["1h", "3h", "6h", "1d", "1w", "1M"], "description": "봉 하나의 길이(기본 1d)"}

TOOLS = [
    {"annotations": RO, "name": "quotes_get", "description": "종목 최신 종가·직전 종가·등락률과 그 값의 시각(as_of — 마지막 10분봉, KR·COIN 은 KST·US 는 미국 동부 현지시각). 장중이면 확정 종가가 아니다. market 은 KR·US·COIN. 원/달러 환율도 함께 준다.",
     "inputSchema": obj({"items": {"type": "array", "maxItems": 30, "items": obj(
         {"code": {"type": "string"}, "market": _MARKET}, ["code", "market"])}}, ["items"])},
    {"annotations": RO, "name": "stock_search", "description": "종목 이름·코드로 검색(최대 10개) — 코드를 모를 때 쓴다. market 을 비우면 한국+미국.",
     "inputSchema": obj({"q": {"type": "string"}, "market": _MARKET}, ["q"])},
    {"annotations": RO, "name": "stock_candles",
     "description": "종목 캔들(시가·고가·저가·종가·거래량) — 줄마다 [시각, 시가, 고가, 저가, 종가, 거래량], 오래된 순, 최대 200개. "
                    "시각은 KR·COIN KST·US 현지(ET). 시세는 구독 종목만, 대개 2024년부터다.",
     "inputSchema": obj({"code": {"type": "string"}, "market": _MARKET, "timeframe": _TF,
                         "days": {"type": "integer", "minimum": 1, "maximum": 3650, "description": "지금부터 며칠(기본 90)"}},
                        ["code"])},
    {"annotations": RO, "name": "stock_fundamentals",
     "description": "한국 보통주 투자지표 — 최신 종가 기준 PER(최근 4분기·지배주주)·PBR·배당(OpenDART). ETF·우선주·해외는 없다.",
     "inputSchema": obj({"code": {"type": "string"}}, ["code"])},
    {"annotations": RO, "name": "stock_financials",
     "description": "한국 보통주 분기 실적(매출·영업이익·순이익, 3개월, 오래된 순, 2023년부터 — OpenDART).",
     "inputSchema": obj({"code": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 12}}, ["code"])},
    {"annotations": RO, "name": "stock_disclosures",
     "description": "한국 종목 공시 목록(최신순 10개씩, 2025-09-29부터). kind: major 주요(기본)·holding 지분 신고·all 전체·key 핵심.",
     "inputSchema": obj({"code": {"type": "string"}, "kind": {"type": "string", "enum": ["major", "holding", "all", "key"]},
                         "page": {"type": "integer", "minimum": 1}}, ["code"])},
    {"annotations": RO, "name": "stock_disclosure_get",
     "description": "공시 한 건의 읽기 쉬운 원문(항목·값)과 AI 요약(사실만). rcept_no 는 stock_disclosures 의 접수번호 14자리.",
     "inputSchema": obj({"code": {"type": "string"}, "rcept_no": {"type": "string"}}, ["code", "rcept_no"])},
    {"annotations": RO, "name": "market_top",
     "description": "시장별 거래대금 상위 종목(최근 30일 합계, 최대 30개) — 종가·등락률 포함.",
     "inputSchema": obj({"market": _MARKET, "limit": {"type": "integer", "minimum": 1, "maximum": 30}})},
    {"annotations": RO, "name": "market_heatmap",
     "description": "시장 전체 흐름 — 구독 종목의 시가총액 상위 30개와 등락률 상위·하위 10개씩(업종 포함), 상승·하락 종목 수.",
     "inputSchema": obj({"market": _MARKET})},
    {"annotations": RO, "name": "index_quotes",
     "description": "지수(국내·미국·세계)·환율 최신값 전부. ⚠️ 시각은 국내지수·환율 KST, 미국·세계지수 현지시각.",
     "inputSchema": obj()},
    {"annotations": RO, "name": "index_candles",
     "description": "지수·환율 캔들 — 줄마다 [시각, 시가, 고가, 저가, 종가], 오래된 순, 최대 200개. code 는 index_quotes 의 code.",
     "inputSchema": obj({"code": {"type": "string"}, "timeframe": _TF,
                         "days": {"type": "integer", "minimum": 1, "maximum": 3650}}, ["code"])},
    {"annotations": RO, "name": "watchlist_get", "description": "사용자의 관심 종목(정한 순서) — 코드·시장·이름·최신 종가·등락률.",
     "inputSchema": obj()},
    {"annotations": RO, "name": "backtest_portfolios",
     "description": "사용자의 백테스트 포트폴리오 목록(이름·점수·등급·종목 요약·전략·공개 여부·실행 여부 ran) — 실행하면 자동 저장되고 화면 ☆ 목록에서 관리한다.",
     "inputSchema": obj()},
    {"annotations": RO, "name": "backtest_portfolio_get", "description": "백테스트 포트폴리오 하나의 설정 전체(종목·비중·전략·규칙)와 지표.",
     "inputSchema": obj({"id": {"type": "integer"}}, ["id"])},
]

_MAX_ROWS = 200
_MAX_TEXT = 4000
_KST = timezone(timedelta(hours=9))


def _dump(v):
    """Pydantic 응답 → JSON 으로 낼 값."""
    if isinstance(v, list):
        return [_dump(x) for x in v]
    return v.model_dump(mode="json") if hasattr(v, "model_dump") else v


def _clip(v):
    """긴 글(공시 원문 등)은 잘라 낸다 — 한 칸이 수만 자일 수 있다."""
    if isinstance(v, str):
        return v if len(v) <= _MAX_TEXT else v[:_MAX_TEXT] + " …(잘림)"
    if isinstance(v, list):
        return [_clip(x) for x in v]
    if isinstance(v, dict):
        return {k: _clip(x) for k, x in v.items()}
    return v


async def _api(fn, *args):
    """화면 API 함수를 그대로 부른다 — 거절(HTTPException)은 AI 에게 이유로 돌려준다."""
    try:
        return _dump(await fn(*args))
    except HTTPException as e:
        raise ValueError(str(e.detail)) from e


def _rows(candles: list[dict], volume: bool, days: int) -> list[list]:
    """⚠️ 캔들 헬퍼는 개수(limit)를 채우려고 구간을 넓혀 간다(`_fetch_candles`) — 물은 기간 밖은 잘라 낸다."""
    since = (datetime.now(_KST) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    keys = ("at", "open", "high", "low", "close") + (("volume",) if volume else ())
    return [[c[k] for k in keys] for c in candles if str(c["at"]) >= since][-_MAX_ROWS:]


async def call(db, user_index: int, name: str, args: dict):
    code = str(args.get("code", "")).strip()[:32]
    tf, days = args.get("timeframe") or "1d", int(args.get("days") or 90)
    if name == "quotes_get":
        items = args.get("items") or []
        stocks = [i["code"] for i in items if i.get("market") != "COIN"]
        coins = [i["code"] for i in items if i.get("market") == "COIN"]
        sq = await _latest_quotes(db, [(c, "s") for c in stocks])
        cq = await _latest_quotes(db, [(c, "c") for c in coins])
        def one(i):
            q = dict((cq if i.get("market") == "COIN" else sq).get(i["code"]) or {"close": None})
            if q.get("as_of"):
                q["as_of"] = f"{q['as_of']:%Y-%m-%d %H:%M} {'ET' if i.get('market') == 'US' else 'KST'}"
            return {"code": i["code"], "market": i.get("market"), **q}
        fx = (await _latest_quotes(db, [("KRWUSD", "f")])).get("KRWUSD")
        return {"usdkrw": fx["close"] if fx else None, "quotes": [one(i) for i in items]}
    if name == "stock_search":
        q = str(args.get("q", "")).strip()[:50]
        if not q:
            raise ValueError("q 가 비었습니다")
        _, rows = await _stock_page(db, args.get("market") or "", q, 1, 10)
        return [{"code": r.code, "name_kr": r.name_kr, "name_en": r.name_en, "market": r.market} for r in rows]
    if name == "stock_candles":
        rows = await _api(stocks_v1.candles, code, args.get("market"), tf, _MAX_ROWS, days, None, None)
        return {"code": code, "timeframe": tf, "columns": ["at", "open", "high", "low", "close", "volume"],
                "rows": _rows(rows, True, days)}
    if name == "stock_fundamentals":
        return await _api(stocks_v1.fundamentals, code)
    if name == "stock_financials":
        return await _api(stocks_v1.financials, code, min(int(args.get("limit") or 8), 12))
    if name == "stock_disclosures":
        page = await _api(stocks_v1.disclosures, code, args.get("kind") or "major", int(args.get("page") or 1), 10)
        return {"total": page["total"], "page": page["page"], "pages": page["pages"],
                "items": [{k: d.get(k) for k in ("rcept_no", "date", "label", "title", "tag", "category_label")}
                          for d in page["items"]]}
    if name == "stock_disclosure_get":
        rcept = str(args.get("rcept_no", "")).strip()
        if not (len(rcept) == 14 and rcept.isdigit()):
            raise ValueError("rcept_no 는 숫자 14자리입니다")
        return _clip(await _api(stocks_v1.disclosure_detail, code, rcept))
    if name == "market_top":
        return await _api(stocks_v1.top, args.get("market") or "KR", min(int(args.get("limit") or 10), 30))
    if name == "market_heatmap":
        items = await _api(stocks_v1.heatmap, args.get("market") or "KR")
        keep = ("code", "name_kr", "category_name", "market_cap", "price", "change_pct")
        slim = [{k: i.get(k) for k in keep} for i in items]
        moved = sorted((i for i in slim if i["change_pct"] is not None), key=lambda i: i["change_pct"])
        return {"count": len(slim), "up": sum(1 for i in moved if i["change_pct"] > 0),
                "down": sum(1 for i in moved if i["change_pct"] < 0),
                "top_cap": slim[:30], "gainers": moved[::-1][:10], "losers": moved[:10]}
    if name == "index_quotes":   # 스파크라인(종가 열)은 뺀다 — 그것만으로 17KB 였다
        return [{k: v for k, v in q.items() if k != "spark"} for q in await _api(quotes_v1.quotes)]
    if name == "index_candles":
        rows = await _api(quotes_v1.candles, code.upper(), tf, _MAX_ROWS, days, None, None)
        return {"code": code.upper(), "timeframe": tf, "columns": ["at", "open", "high", "low", "close"],
                "rows": _rows(rows, False, days)}
    if name == "watchlist_get":
        rows = (await db.execute(text(
            "SELECT market, stock_code FROM stock_watchlist WHERE user_index = :u "
            "ORDER BY sort_order IS NULL, sort_order, created_at, stock_code"), {"u": user_index})).all()
        stocks = [r.stock_code for r in rows if r.market != "COIN"]
        coins = [r.stock_code for r in rows if r.market == "COIN"]
        # ⚠️ 이름은 따로 읽는다 — 다른 스키마 표와 조인하면 정렬 규칙(collation)이 달라 1267 로 실패했다
        names = {}
        for sql, codes, kind in (("SELECT stock_code, stock_name_kr FROM KoreaInvest.stock_info WHERE stock_code IN :c", stocks, "s"),
                                 ("SELECT coin_code, coin_name_kr FROM Bithumb.coin_info WHERE coin_code IN :c", coins, "c")):
            if codes:
                for c, n in (await db.execute(text(sql).bindparams(bindparam("c", expanding=True)), {"c": codes})).all():
                    names[(kind, c)] = n
        # ⚠️ `_latest_quotes` 는 코드로 사전을 만든다 — 주식·코인을 한 번에 넘기면 겹치는 코드가 서로를 덮는다(watchlist_v1)
        sq = await _latest_quotes(db, [(c, "s") for c in stocks])
        cq = await _latest_quotes(db, [(c, "c") for c in coins])
        out = []
        for r in rows:
            kind = "c" if r.market == "COIN" else "s"
            q = (cq if kind == "c" else sq).get(r.stock_code) or {}
            out.append({"code": r.stock_code, "market": r.market, "name": names.get((kind, r.stock_code)),
                        "close": q.get("close"), "change_pct": q.get("change_pct")})
        return out
    if name == "backtest_portfolios":
        rows = (await db.execute(text(
            "SELECT portfolio_id, portfolio_name, is_public, ranking_score, ranking_grade, stock_summary, strategy, "
            "metrics_json <> '{}' AS ran FROM backtest_portfolio WHERE user_index = :u ORDER BY updated_at DESC LIMIT 50"),
            {"u": user_index})).all()
        return [{"id": r.portfolio_id, "name": r.portfolio_name, "public": bool(r.is_public), "score": r.ranking_score,
                 "grade": r.ranking_grade, "stocks": r.stock_summary, "strategy": r.strategy, "ran": bool(r.ran)} for r in rows]
    if name == "backtest_portfolio_get":
        row = (await db.execute(text(
            "SELECT portfolio_name, config_json, metrics_json FROM backtest_portfolio WHERE portfolio_id = :id AND user_index = :u"),
            {"id": int(args.get("id", 0)), "u": user_index})).first()
        if row is None:
            raise ValueError("없는 포트폴리오입니다")
        return {"name": row.portfolio_name, "config": json.loads(row.config_json) if row.config_json else None,
                "metrics": json.loads(row.metrics_json) if row.metrics_json and row.metrics_json != "{}" else None}
    raise ValueError(f"모르는 도구: {name}")
