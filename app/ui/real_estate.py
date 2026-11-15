"""계층형 전국 아파트 실거래 분석 화면."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from app.core import blog_user
from app.db.session import db_session
from app.ui.routes import _shell_ctx, templates

router = APIRouter()


@router.get('/real-estate', response_class=HTMLResponse)
async def real_estate(request: Request):
    level = blog_user.level_of(getattr(request.state, 'user', None))
    async with db_session() as db:
        ctx = await _shell_ctx(request, db, level)
    return templates.TemplateResponse(request, 'real_estate.html', {
        **ctx, 'is_stock_page': True, 'hide_sidebar': True,
    })
