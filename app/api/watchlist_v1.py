"""`/api/v1/watchlist` — 관심 종목(2026-09-23).

계정마다 서버에 저장한다(`stock_watchlist`) — 사용자가 **기기끼리 맞춰지는 쪽**을 골랐다.
화면은 `/api/v1/auth/token` 으로 Bearer 를 받아 부른다(백테스트 프리셋과 같은 길).

⚠️ **읽기도 Bearer 다.** 개인 데이터라 프리셋과 같은 규칙을 따른다(`_me`) — 쿠키로 열면
   남의 사이트가 목록을 읽게 할 수는 없어도(동일 출처 정책), 규칙이 둘이 되면 어느 쪽이
   맞는지 매번 따져야 한다. 쓰기는 말할 것도 없이 Bearer 전용이다([deps](deps.py)).
⚠️ 시장 묶음(KR·US·COIN)을 키에 넣는다 — 주식과 코인의 코드가 겹칠 수 있다.
"""

import re

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text

from app.api.deps import bearer_user
from app.core import blog_user
from app.db.session import db_session
from app.ui.stocks import _latest_quotes, _norm_market, _resolve_is_coin, _US_MARKETS

router = APIRouter(prefix="/api/v1/watchlist", tags=["watchlist"])

#: 한 계정의 상한. 없으면 목록을 부를 때마다 수백 종목의 시세를 모으게 된다.
_MAX_ITEMS = 50
_SAFE_CODE = re.compile(r"[A-Za-z0-9._/-]{1,32}")


class WatchItem(BaseModel):
    code: str
    name_kr: str | None = None
    market: str = Field(description="시장 묶음 KR·US·COIN")
    price: float | None = None
    prev_price: float | None = Field(default=None, description="직전 거래일 종가")
    change_pct: float | None = Field(default=None, description="등락률(%). 직전 종가가 없으면 null")


async def _me(db, request: Request):
    me = await blog_user.find(db, bearer_user(request))
    if me is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "블로그 계정이 연결되지 않았습니다")
    return me


def _code_arg(code: str) -> str:
    if not _SAFE_CODE.fullmatch(code):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "종목 코드 형식이 아닙니다")
    return code


def _market_arg(v: str | None) -> str:
    m = _norm_market(v)
    if v and not m:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "market 은 KR·US·COIN 중 하나여야 합니다")
    return m


@router.get("", response_model=list[WatchItem], summary="내 관심 종목")
async def watchlist(request: Request):
    """담은 순서대로. 이름과 시세(마지막 거래일 기준)를 붙여 준다 — 목록·히트맵과 같은 헬퍼다."""
    async with db_session() as db:
        me = await _me(db, request)
        rows = (await db.execute(text(
            "SELECT market, stock_code FROM stock_watchlist WHERE user_index = :u "
            "ORDER BY created_at, stock_code LIMIT :n"), {"u": me.user_index, "n": _MAX_ITEMS})).all()
        if not rows:
            return []

        stock_codes = [c for m, c in rows if m != "COIN"]
        coin_codes = [c for m, c in rows if m == "COIN"]
        names: dict[tuple[str, str], str] = {}
        if stock_codes:
            for c, n in (await db.execute(text(
                    "SELECT stock_code, stock_name_kr FROM KoreaInvest.stock_info WHERE stock_code IN :c")
                    .bindparams(bindparam("c", expanding=True)), {"c": stock_codes})).all():
                names[("S", c)] = n
        if coin_codes:
            for c, n in (await db.execute(text(
                    "SELECT coin_code, coin_name_kr FROM Bithumb.coin_info WHERE coin_code IN :c")
                    .bindparams(bindparam("c", expanding=True)), {"c": coin_codes})).all():
                names[("C", c)] = n
        # ⚠️ `_latest_quotes` 는 코드로 사전을 만든다 — 주식·코인을 한 번에 넘기면 겹치는 코드가
        #    서로를 덮는다. 따로 부른다.
        sq = await _latest_quotes(db, [(c, "s") for c in stock_codes])
        cq = await _latest_quotes(db, [(c, "c") for c in coin_codes])

    out = []
    for market, code in rows:
        coin = market == "COIN"
        q = (cq if coin else sq).get(code) or {}
        out.append(WatchItem(code=code, name_kr=names.get(("C" if coin else "S", code)), market=market,
                             price=q.get("close"), prev_price=q.get("prev_close"),
                             change_pct=q.get("change_pct")))
    return out


@router.put("/{code}", status_code=status.HTTP_204_NO_CONTENT, summary="관심 종목에 담기")
async def add(request: Request, code: str, market: str | None = Query(None, description="KR·US·COIN")):
    """이미 담겨 있으면 그대로 둔다(멱등). 없는 종목은 404, 상한을 넘으면 409."""
    code = _code_arg(code)
    m = _market_arg(market)
    async with db_session() as db:
        me = await _me(db, request)
        if await _resolve_is_coin(db, code, m):
            found = (await db.execute(text("SELECT 1 FROM Bithumb.coin_info WHERE coin_code = :c"),
                                      {"c": code})).first()
            group = "COIN"
        else:
            found = (await db.execute(text("SELECT stock_market FROM KoreaInvest.stock_info "
                                           "WHERE stock_code = :c"), {"c": code})).first()
            group = "US" if found and found[0] in _US_MARKETS else "KR"
        if not found:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "없는 종목입니다")

        count = (await db.execute(text("SELECT COUNT(*) FROM stock_watchlist WHERE user_index = :u"),
                                  {"u": me.user_index})).scalar()
        exists = (await db.execute(text(
            "SELECT 1 FROM stock_watchlist WHERE user_index = :u AND market = :m AND stock_code = :c"),
            {"u": me.user_index, "m": group, "c": code})).first()
        if not exists:
            if count >= _MAX_ITEMS:
                raise HTTPException(status.HTTP_409_CONFLICT, f"관심 종목은 {_MAX_ITEMS}개까지 담을 수 있습니다")
            await db.execute(text(
                "INSERT INTO stock_watchlist (user_index, market, stock_code) VALUES (:u, :m, :c)"),
                {"u": me.user_index, "m": group, "c": code})
            await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{code}", status_code=status.HTTP_204_NO_CONTENT, summary="관심 종목에서 빼기")
async def remove(request: Request, code: str, market: str | None = Query(None, description="KR·US·COIN")):
    """없어도 204(멱등). `market=COIN` 이 아니면 주식(KR·US) 쪽을 지운다."""
    code = _code_arg(code)
    m = _market_arg(market)
    async with db_session() as db:
        me = await _me(db, request)
        groups = ["COIN"] if m == "COIN" else ["KR", "US"]
        await db.execute(text(
            "DELETE FROM stock_watchlist WHERE user_index = :u AND stock_code = :c AND market IN :g")
            .bindparams(bindparam("g", expanding=True)), {"u": me.user_index, "c": code, "g": groups})
        await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
