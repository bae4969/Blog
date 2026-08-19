"""`/api/v1/backtest` — 시뮬레이션과 프리셋.

기존 `/stocks/api/*` 의 백테스트 계열을 같은 규약으로 옮긴 것이다. 계산은 `_norm_config`
와 `engine.run` 을 그대로 쓴다 — 검증 로직을 다시 짜면 화면과 결과가 갈라진다.

## ⚠️ 실행이 더 이상 포트폴리오를 저장하지 않는다

옛 `POST /stocks/api/backtest` 는 **부를 때마다 `backtest_portfolio` 에 행을 썼다.**
그래서 memory 에 "운영 백테스트 API 는 검증에 쓰지 말 것" 이라고 적혀 있었다 —
결과를 확인하려고 부르면 데이터가 늘어나는 API 였다.

여기서는 **계산만 한다.** 저장은 저장을 요청했을 때만 일어나는 게 맞다. 화면은 옛
엔드포인트를 계속 쓰므로 지금 동작이 바뀌지는 않는다.

## ⚠️ 포트폴리오 계열은 옮기지 않았다

`/stocks/api/portfolio*` 는 **IP 를 소유권 근거로 쓴다**("저장할 때와 같은 IP 에서만").
그런데 이 서비스는 프록시 뒤에 있어 외부 요청이 전부 게이트웨이 하나(`172.16.9.1`)로
보인다 — 즉 **모두가 같은 주인**이라 누구나 남의 포트폴리오 이름을 바꿀 수 있다.
그대로 옮기면 깨진 모델을 API 로 넓히는 셈이라, 소유권을 계정 기반으로 고친 뒤에 옮긴다.

프리셋(`backtest_preset`)은 `user_index` 로 소유권을 보므로 그대로 옮겼다.
"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.api.deps import bearer_user
from app.core import blog_user
from app.db.session import db_session
from app.services import backtest as engine
from app.ui.backtest import _backtest_slots, _finite, _load_prices, _norm_config

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


@router.post("/run", summary="백테스트 실행 (저장하지 않는다)")
async def run(body: BacktestRequest):
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
    return _finite(result)


@router.get("/presets", response_model=list[PresetSummary], summary="내 프리셋 목록")
async def presets(request: Request):
    async with db_session() as db:
        me = await _me(db, request)
        rows = (await db.execute(text(
            "SELECT preset_id, preset_name, stock_summary, strategy "
            "FROM backtest_preset WHERE user_index = :u ORDER BY updated_at DESC"),
            {"u": me.user_index})).all()
    return [PresetSummary(id=r[0], name=r[1], stock_summary=r[2], strategy=r[3]) for r in rows]


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
