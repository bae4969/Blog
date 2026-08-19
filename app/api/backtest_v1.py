"""`/api/v1/backtest` — 시뮬레이션과 프리셋.

기존 `/stocks/api/*` 의 백테스트 계열을 같은 규약으로 옮긴 것이다. 계산은 `_norm_config`
와 `engine.run` 을 그대로 쓴다 — 검증 로직을 다시 짜면 화면과 결과가 갈라진다.

## ⚠️ 실행이 더 이상 포트폴리오를 저장하지 않는다

옛 `POST /stocks/api/backtest` 는 **부를 때마다 `backtest_portfolio` 에 행을 썼다.**
그래서 memory 에 "운영 백테스트 API 는 검증에 쓰지 말 것" 이라고 적혀 있었다 —
결과를 확인하려고 부르면 데이터가 늘어나는 API 였다.

여기서는 **계산만 한다.** 저장은 저장을 요청했을 때만 일어나는 게 맞다. 화면은 옛
엔드포인트를 계속 쓰므로 지금 동작이 바뀌지는 않는다.

## 포트폴리오 — 소유권을 계정으로 바꾸고 공개/비공개를 나눴다

옛 `/stocks/api/portfolio*` 는 **IP 를 소유권 근거로 썼다**("저장할 때와 같은 IP 에서만").
그런데 앞단(NPM)이 진짜 클라이언트 IP 를 안 넘겨 **외부 요청이 전부 게이트웨이 하나로
보인다** — 즉 모두가 같은 주인이라 누구나 남의 포트폴리오 이름을 바꿀 수 있었다.

    로그인해서 돌린 것   user_index = 나,  **비공개로 시작** (공개는 눌러서)
    비로그인이 돌린 것   user_index = NULL, **공개 고정** (주인이 없어 못 고친다)

⚠️ 백테스트는 **돌리기만 해도 저장된다.** 그래서 로그인 사용자의 것을 비공개로 두지
   않으면 투자 조합이 본인도 모르게 랭킹에 뜬다 — 실제로 그렇게 돌고 있었다.

프리셋(`backtest_preset`)은 원래 `user_index` 로 소유권을 봐서 그대로 옮겼다.
"""

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.api.deps import bearer_user
from app.core import blog_user
from app.db.session import db_session
from app.services import backtest as engine
from app.ui.backtest import (
    _backtest_slots,
    _candle_date_range,
    _finite,
    _load_prices,
    _MAX_PRESETS_PER_USER,
    _MAX_RANGE_CODES,
    _norm_config,
    _save_portfolio,
    _stock_summary,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/backtest", tags=["backtest"])


class BacktestRequest(BaseModel):
    """옛 API 와 같은 입력이다 — 화면 JS 가 만드는 것을 그대로 받는다."""

    stocks: list[dict] = Field(description="종목별 코드·시장·비중")
    startDate: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    endDate: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    strategy: str = "buyhold"
    benchmarks: list[dict] = Field(default_factory=list)


class PresetSummary(BaseModel):
    id: int
    name: str
    stock_summary: str | None = None
    strategy: str | None = None


async def _me(db, request: Request):
    me = await blog_user.find(db, bearer_user(request))
    if me is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "블로그 계정이 연결되지 않았습니다")
    return me


@router.get("/date-range", summary="함께 백테스트할 수 있는 기간")
async def date_range(
    codes: str = Query(description="쉼표로 구분한 종목 코드"),
    markets: str = Query("", description="코드와 같은 순서의 시장. 모자라면 빈 값 취급"),
):
    """여러 종목을 **함께** 돌릴 수 있는 기간 = 각 종목 보유 기간의 교집합.

    시작일은 가장 늦은 시작일, 종료일은 가장 이른 종료일이다 — 한 종목이라도 데이터가
    없는 날은 비교가 성립하지 않는다. 겹치는 구간이 없으면 `null` 이다(오류가 아니다).
    """
    code_list = [c.strip() for c in codes.split(",") if c.strip()][:_MAX_RANGE_CODES]
    market_list = [m.strip() for m in markets.split(",") if m.strip()]
    if not code_list:
        return {"min": None, "max": None}

    lo = hi = None
    async with db_session() as db:
        for i, code in enumerate(code_list):
            rng = await _candle_date_range(db, code, market_list[i] if i < len(market_list) else "")
            if rng is None:
                continue
            mn, mx = rng
            lo = mn if lo is None or mn > lo else lo
            hi = mx if hi is None or mx < hi else hi

    if lo is None or hi is None or lo > hi:
        return {"min": None, "max": None}
    return {"min": lo.isoformat(), "max": hi.isoformat()}


@router.post("/run", summary="백테스트 실행")
async def run(request: Request, body: BacktestRequest,
              save: bool = Query(False, description="결과를 포트폴리오로 남긴다")):
    """⚠️ 기본은 **저장하지 않는다.** 옛 `POST /stocks/api/backtest` 는 부를 때마다
    `backtest_portfolio` 에 행을 써서, 결과를 확인하려고 부르면 데이터가 늘어났다.

    `save=true` 면 남긴다. 화면이 그걸 쓴다 — 랭킹이 이 저장으로 채워지기 때문이다.

    ⚠️ **점수는 서버가 계산한 것만 저장한다.** 클라이언트가 결과를 만들어 보내는 구조로
       두면 아무나 만점짜리 포트폴리오를 랭킹에 밀어 넣을 수 있다.

    소유권은 `Authorization` 헤더가 있으면 그 계정이고(비공개로 시작), 없으면 주인 없는
    공개 항목이 된다.
    """
    config, err = _norm_config(body.model_dump())
    if config is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, err)

    if _backtest_slots.locked():
        # 계산이 무거워 동시 실행 수를 제한한다. 큐에 쌓지 않고 바로 알린다.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "서버가 바쁩니다. 잠시 후 다시 시도해주세요")

    async with _backtest_slots:
        async with db_session() as db:
            stock_data, bmk_data = await _load_prices(db, config)
        # 순수 계산이라 DB 연결을 쥔 채로 돌지 않는다.
        result = await asyncio.to_thread(engine.run, config, stock_data, bmk_data)

    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "선택한 종목·기간에 데이터가 없습니다")

    # ⚠️ `_finite` 를 거쳐야 한다 — NaN·Infinity 는 JSON 표준이 아니라 소비자가 파싱에서
    #    죽는다(수익률 계산에서 0 나누기가 나올 수 있다).
    #
    # ⚠️ 결과를 한 겹 더 감싸지 않는다(`{"result": ...}`). 이 엔드포인트는 이미 2.5.0 으로
    #    나갔고, 모양을 바꾸면 밖에서 쓰던 소비자가 깨진다. `portfolio` 키만 **덧붙인다**
    #    — 엔진 결과에는 그 이름이 없다(dailySeries·metrics·annualReturns·tradeSummary·
    #    benchmarks·rankingScore·rankingGrade).
    out = _finite(result)
    if save:
        try:
            pid, pname, mine, is_public = await _save_portfolio(request, config, result)
            out["portfolio"] = {"id": pid, "name": pname, "mine": mine, "is_public": is_public}
        except Exception:
            # ⚠️ 저장이 실패해도 계산 결과는 돌려준다 — 사용자가 기다린 것은 그쪽이다.
            #    그래서 **저장이 깨져도 200 이다.** 이 경로를 건드렸으면 응답이 아니라
            #    `portfolio` 가 채워지는지와 로그를 봐야 한다(2026-08-19 에 실제로
            #    INSERT 에서 컬럼 하나가 빠진 변경이 여기서 조용히 삼켜질 뻔했다).
            logger.exception("포트폴리오 저장 실패")
    return out


@router.get("/presets", response_model=list[PresetSummary], summary="내 프리셋 목록")
async def presets(request: Request):
    async with db_session() as db:
        me = await _me(db, request)
        rows = (await db.execute(text(
            "SELECT preset_id, preset_name, stock_summary, strategy "
            "FROM backtest_preset WHERE user_index = :u ORDER BY updated_at DESC"),
            {"u": me.user_index})).all()
    return [PresetSummary(id=r[0], name=r[1], stock_summary=r[2], strategy=r[3]) for r in rows]


class PresetDetail(PresetSummary):
    config: dict | None = None


class PresetSave(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    config: dict = Field(description="화면 폼 전체. `stocks` 가 비면 거절한다")


@router.get("/presets/{preset_id}", response_model=PresetDetail, summary="프리셋 하나")
async def preset(request: Request, preset_id: int):
    """⚠️ 남의 것은 못 본다 — `user_index` 를 WHERE 에 함께 넣는다."""
    async with db_session() as db:
        me = await _me(db, request)
        row = (await db.execute(text(
            "SELECT preset_id, preset_name, config_json, stock_summary, strategy "
            "FROM backtest_preset WHERE preset_id = :id AND user_index = :u"),
            {"id": preset_id, "u": me.user_index})).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "프리셋을 찾을 수 없습니다")
    try:
        config = json.loads(row[2]) if row[2] else None
    except (ValueError, TypeError):
        config = None
    return PresetDetail(id=row[0], name=row[1], config=config,
                        stock_summary=row[3], strategy=row[4])


@router.post("/presets", response_model=PresetSummary, status_code=status.HTTP_201_CREATED,
             summary="프리셋 저장")
async def save_preset(request: Request, body: PresetSave):
    """⚠️ **같은 이름이면 덮어쓴다**(계정+이름이 UNIQUE). 새로 만드는 것만 개수 상한에 걸린다."""
    stocks = body.config.get("stocks")
    if not isinstance(stocks, list) or not stocks:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "설정에 종목이 있어야 합니다")

    name = body.name.strip()[:100]
    params = {
        "cfg": json.dumps(body.config, ensure_ascii=False),
        "sum": _stock_summary(stocks),
        "st": str(body.config.get("strategy") or "buyhold")[:20],
        "name": name,
    }

    async with db_session() as db:
        me = await _me(db, request)
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
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"프리셋은 최대 {_MAX_PRESETS_PER_USER}개까지 저장할 수 있습니다")
            res = await db.execute(text(
                "INSERT INTO backtest_preset (user_index, preset_name, config_json, "
                "stock_summary, strategy) VALUES (:u, :name, :cfg, :sum, :st)"), params)
            preset_id = int(res.lastrowid)
        await db.commit()

    logger.info("프리셋 저장: user=%s id=%s name=%s", me.user_id, preset_id, name)
    return PresetSummary(id=preset_id, name=name, stock_summary=params["sum"],
                         strategy=params["st"])


@router.delete("/presets/{preset_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="프리셋 삭제")
async def delete_preset(request: Request, preset_id: int):
    async with db_session() as db:
        me = await _me(db, request)
        # ⚠️ `user_index` 를 WHERE 에 함께 넣는다 — 소유권 검사와 삭제가 한 문장이라야
        #    그 사이에 끼어들 틈이 없다. 남의 것은 rowcount 0 으로 떨어진다.
        res = await db.execute(text(
            "DELETE FROM backtest_preset WHERE preset_id = :p AND user_index = :u"),
            {"p": preset_id, "u": me.user_index})
        await db.commit()
    if res.rowcount == 0:
        # 남의 것이어도 404 다 — 403 을 주면 그 번호가 존재한다는 사실이 새어 나간다.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "프리셋을 찾을 수 없습니다")


class PortfolioOut(BaseModel):
    id: int
    name: str
    is_public: bool
    ranking_score: float | None = None
    ranking_grade: str | None = None
    stock_summary: str | None = None


class PortfolioPatch(BaseModel):
    """공개 여부와 이름. **준 것만** 바꾼다(둘 다 비우면 422)."""

    is_public: bool | None = None
    name: str | None = Field(default=None, min_length=1, max_length=100)


class PortfolioDetail(PortfolioOut):
    """폼 복원용 — 저장된 설정까지 준다."""

    mine: bool
    config: dict | None = None
    metrics: dict | None = None
    display_score: float | None = None
    display_grade: str | None = None
    strategy: str | None = None
    period_start: str | None = None
    period_end: str | None = None


@router.get("/portfolios", response_model=list[PortfolioOut], summary="내 포트폴리오")
async def portfolios(request: Request):
    """⚠️ **내 것만** 준다. 비로그인이 돌린 것(주인 없음)은 여기 안 나온다 — 공개 랭킹에만 뜬다."""
    async with db_session() as db:
        me = await _me(db, request)
        rows = (await db.execute(text(
            "SELECT portfolio_id, portfolio_name, is_public, ranking_score, ranking_grade, "
            "stock_summary FROM backtest_portfolio WHERE user_index = :u "
            "ORDER BY updated_at DESC"), {"u": me.user_index})).all()
    return [PortfolioOut(id=r[0], name=r[1], is_public=bool(r[2]), ranking_score=r[3],
                         ranking_grade=r[4], stock_summary=r[5]) for r in rows]


@router.get("/portfolios/{portfolio_id}", response_model=PortfolioDetail,
            summary="포트폴리오 하나")
async def portfolio(request: Request, portfolio_id: int):
    """저장된 설정(`config`)까지 준다 — 화면이 폼을 복원하는 데 쓴다.

    ⚠️ **공개된 것이거나 내 것일 때만** 준다. id 는 랭킹에 그대로 노출되므로, 소유권을
       안 보면 번호만 알아도 남의 투자 조합 전체를 읽을 수 있다.

    토큰은 **있으면 쓰고 없으면 만다** — 랭킹에서 넘어온 비로그인 방문자도 공개분은 볼 수
    있어야 한다. 토큰이 있을 때만 "내 것" 판정과 비공개 열람이 켜진다.
    """
    me = None
    if request.headers.get("authorization", "").lower().startswith("bearer "):
        async with db_session() as db:
            me = (await _me(db, request)).user_index

    async with db_session() as db:
        row = (await db.execute(text(
            "SELECT portfolio_id, portfolio_name, user_index, is_public, config_json, "
            "display_score, display_grade, ranking_score, ranking_grade, metrics_json, "
            "stock_summary, strategy, period_start, period_end "
            "FROM backtest_portfolio WHERE portfolio_id = :id AND "
            "(is_public = 1 OR (user_index IS NOT NULL AND user_index = :me))"),
            {"id": portfolio_id, "me": me})).first()

    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "포트폴리오를 찾을 수 없습니다")

    def _json(raw):
        try:
            return json.loads(raw) if raw else None
        except (ValueError, TypeError):
            return None

    # ⚠️ `user_index` 자체는 내보내지 않는다 — 화면에 필요한 것은 "내 것인가" 뿐이다.
    owner = row[2]
    return PortfolioDetail(
        id=row[0], name=row[1], is_public=bool(row[3]), config=_json(row[4]),
        display_score=row[5], display_grade=row[6], ranking_score=row[7],
        ranking_grade=row[8], metrics=_json(row[9]), stock_summary=row[10],
        strategy=row[11],
        period_start=str(row[12]) if row[12] else None,
        period_end=str(row[13]) if row[13] else None,
        mine=owner is not None and me is not None and owner == me,
    )


@router.patch("/portfolios/{portfolio_id}", response_model=PortfolioOut,
              summary="공개 여부·이름 수정")
async def update_portfolio(request: Request, portfolio_id: int, body: PortfolioPatch):
    """공개로 바꾸면 `/stocks` 사이드바 랭킹에 뜬다.

    ⚠️ 백테스트는 **돌리기만 해도 저장**된다. 그래서 로그인 사용자의 것은 비공개로
       시작하고, 공개는 여기서 명시적으로 눌러야 한다 — 투자 조합이 본인도 모르게
       노출되던 것이 이 구조를 만든 이유다.

    ⚠️ 주인이 없는 포트폴리오(비로그인이 돌린 것)는 **아무도 못 고친다.** 옛 IP 기준은
       모두를 같은 주인으로 만들어 남의 것도 고칠 수 있었다.
    """
    sets, params = [], {"id": portfolio_id}
    if body.is_public is not None:
        sets.append("is_public = :p")
        params["p"] = 1 if body.is_public else 0
    if body.name is not None:
        sets.append("portfolio_name = :n")
        params["n"] = body.name.strip()[:100]
    if not sets:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "is_public 또는 name 중 하나는 있어야 합니다")

    async with db_session() as db:
        me = await _me(db, request)
        params["u"] = me.user_index
        # 소유권 검사와 갱신을 한 문장에 둔다 — 남의 것은 rowcount 0 으로 떨어진다.
        res = await db.execute(text(
            f"UPDATE backtest_portfolio SET {', '.join(sets)} "
            "WHERE portfolio_id = :id AND user_index = :u"), params)
        if res.rowcount == 0:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "포트폴리오를 찾을 수 없습니다")
        await db.commit()
        row = (await db.execute(text(
            "SELECT portfolio_id, portfolio_name, is_public, ranking_score, ranking_grade, "
            "stock_summary FROM backtest_portfolio WHERE portfolio_id = :id"),
            {"id": portfolio_id})).first()
    return PortfolioOut(id=row[0], name=row[1], is_public=bool(row[2]), ranking_score=row[3],
                        ranking_grade=row[4], stock_summary=row[5])
