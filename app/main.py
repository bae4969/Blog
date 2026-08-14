"""블로그(FastAPI) — 진입점.

**PHP 를 한 번에 걷어내지 않는다.** 기존 앱(`public/index.php`, 73 라우트)은 그대로 두고,
포팅이 끝난 경로만 Traefik 이 이쪽으로 보낸다. 나머지는 계속 PHP 가 받는다 —
문제가 생기면 그 경로만 되돌리면 되고, 반쯤 포팅된 상태로 서비스가 멈추지 않는다.

지금 이쪽이 받는 것: `/blog`(목록)

인증은 하지 않는다. 중앙 auth(`10.auth`)가 RS256 으로 서명한 토큰을 공개키로 검증만
한다. 블로그는 **비로그인도 읽을 수 있어야** 하므로 미들웨어가 막지 않고, 토큰이 있으면
등급을 올려 볼 수 있는 글이 늘어나는 구조다.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.security import current_user_or_none, fetch_public_key
from app.ui.admin import router as admin_router
from app.ui.routes import router as ui_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await fetch_public_key()
    except Exception:
        logger.warning("auth 공개키를 아직 못 받았다 — 첫 요청에서 다시 시도한다")
    logger.info("blog(api) 기동 — base_domain=%s", settings.base_domain)
    yield


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    # 인증 API 와 같은 방침 — 스키마를 인터넷에 그냥 내주지 않는다.
    openapi_url=None,
)


class OptionalAuthMiddleware(BaseHTTPMiddleware):
    """토큰이 있으면 `request.state.user` 에 싣고, 없으면 그냥 통과시킨다.

    ⚠️ 다른 서비스(ai_center·ai_usage)의 미들웨어와 달리 **막지 않는다.** 블로그는 공개
    사이트라 비로그인 방문자가 정상 경로다. 권한은 라우트가 등급으로 판단한다.
    """

    async def dispatch(self, request: Request, call_next):
        request.state.user = current_user_or_none(request)
        return await call_next(request)


app.add_middleware(OptionalAuthMiddleware)

_STATIC = Path(__file__).parent / "static"
app.mount("/static-api", StaticFiles(directory=_STATIC), name="static-api")

app.include_router(ui_router)
app.include_router(admin_router)   # /admin/* — 지금은 카테고리만


@app.get("/healthz", include_in_schema=False)
async def healthz() -> PlainTextResponse:
    return PlainTextResponse("ok")
