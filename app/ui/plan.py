"""투자 계획 화면 `/stocks/plan` — root(레벨 0) 본인 전용. 껍데기만 그린다.

트리·상세·상담은 전부 `/js/plan.js` 가 `/api/v1/plan/*`(Bearer)을 불러 그린다([plan_v1](../api/plan_v1.py)).
다른 사람에게는 화면이 있다는 사실도 알리지 않는다(404 — API 와 같다).
"""

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse

from app.db.session import db_session
from app.ui.routes import _shell_ctx, templates
from app.ui.stocks import _level

router = APIRouter()


@router.get("/stocks/plan", response_class=HTMLResponse, include_in_schema=False)
async def plan_page(request: Request):
    level = _level(request)
    if level != 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    async with db_session() as db:
        ctx = await _shell_ctx(request, db, level)
    return templates.TemplateResponse(
        request, "stocks_plan.html", {**ctx, "is_stock_page": True, "hide_sidebar": True})
