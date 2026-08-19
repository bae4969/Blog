"""블로그(FastAPI) — 진입점.

블로그·주식·백테스트·관리자 화면을 **전부 이 앱이 받는다.** PHP 는 2026-08-17 에
걷어냈다(그전 코드는 `php-final` 태그).

인증은 하지 않는다. 중앙 auth(`10.auth`)가 RS256 으로 서명한 토큰을 공개키로 검증만
한다. 블로그는 **비로그인도 읽을 수 있어야** 하므로 미들웨어가 막지 않고, 토큰이 있으면
등급을 올려 볼 수 있는 글이 늘어나는 구조다.
"""

import logging
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.core import blog_user
from app.core.config import settings
from app.core.security import (
    attach_session,
    current_user_or_none,
    fetch_public_key,
    refresh_session,
)
from app.api.auth_v1 import router as api_auth_router
from app.api.backtest_v1 import router as api_backtest_router
from app.api.stocks_v1 import router as api_stocks_router
from app.api.v1 import router as api_v1_router
from app.ui.admin import router as admin_router
from app.ui.backtest import router as backtest_router
from app.ui.routes import router as ui_router
from app.ui.stocks import router as stocks_router

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
    # ⚠️ 기본 경로는 계속 닫아 둔다. 아래에서 **관리자에게만** 같은 것을 내준다 —
    #    스키마는 어떤 자원이 어떤 파라미터를 받는지를 통째로 알려주는 지도라,
    #    인터넷에 그냥 열어 두지 않는다는 방침은 그대로다(인증 API 와 같다).
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


class OptionalAuthMiddleware(BaseHTTPMiddleware):
    """토큰이 있으면 `request.state.user` 에 싣고, 없으면 그냥 통과시킨다.

    ⚠️ 다른 서비스(ai_center·ai_usage)의 미들웨어와 달리 **막지 않는다.** 블로그는 공개
    사이트라 비로그인 방문자가 정상 경로다. 권한은 라우트가 등급으로 판단한다.

    세션이 만료됐는데 기기 신뢰 쿠키가 있으면 **여기서 조용히 갱신한다.** 화면이든 API 든
    한 곳에서 처리되므로 라우트와 JS 를 손댈 필요가 없다 — 클라이언트마다 401 을 잡아
    재시도하게 만들면 fetch 호출 지점을 전부 고쳐야 한다.
    """

    #: 갱신을 시도하지 않을 경로. 정적 파일·헬스체크까지 auth 를 부르면 낭비다.
    _SKIP = ("/healthz", "/favicon.ico", "/robots.txt")
    _SKIP_PREFIX = ("/css/", "/js/", "/res/", "/vendor/", "/uploads/")

    async def dispatch(self, request: Request, call_next):
        user = current_user_or_none(request)
        renewed = None
        if user is None and not self._skip(request.url.path):
            got = await refresh_session(request)
            if got is not None:
                user, token, device_token = got
                renewed = (token, device_token)
                logger.info("세션 자동 갱신: uid=%s", user.uid)

        request.state.user = user
        response = await call_next(request)
        if renewed is not None:
            attach_session(response, *renewed)
        return response

    def _skip(self, path: str) -> bool:
        return path in self._SKIP or path.startswith(self._SKIP_PREFIX)


app.add_middleware(OptionalAuthMiddleware)

# ── 정적 파일 — 옛 PHP 문서루트(`public/`)를 그대로 서빙한다 ──────────────
#
# 지금까지 `/css/*`·`/res/*`·`/vendor/quill/*` 은 **PHP 컨테이너**가 줬다. PHP 를 걷어내면
# 아무도 안 주게 되므로 여기서 받는다. 경로를 바꾸지 않는 이유는 옛 링크·북마크와 PHP 뷰가
# 같은 URL 을 쓰기 때문이다(`/css/blog.css` 등).
#
# ⚠️ `uploads` 는 사용자가 올린 이미지라 **글 본문이 이 URL 을 직접 가리킨다.** 경로를 바꾸면
#    기존 글의 이미지가 전부 깨진다.
# ⚠️ 이 이미지의 파이썬은 `.webp` 를 모른다 — 등록하지 않으면 StaticFiles 가
#    `application/octet-stream` 으로 내보낸다(썸네일이 전부 webp 다).
mimetypes.add_type("image/webp", ".webp")

_PUBLIC = Path(__file__).parent.parent / "public"
for _sub in ("css", "js", "res", "vendor", "uploads"):
    _dir = _PUBLIC / _sub
    if _dir.is_dir():
        app.mount(f"/{_sub}", StaticFiles(directory=_dir), name=f"public-{_sub}")

app.include_router(api_v1_router)      # /api/v1/* — 블로그 읽기
app.include_router(api_stocks_router)   # /api/v1/stocks/* — 종목·캔들·체결
app.include_router(api_backtest_router) # /api/v1/backtest/* — 시뮬레이션·프리셋
app.include_router(api_auth_router)     # /api/v1/auth/token — 화면이 Bearer 를 얻는 창구
app.include_router(ui_router)
app.include_router(admin_router)   # /admin/*
app.include_router(stocks_router)   # /stocks — 목록·상세·차트
app.include_router(backtest_router) # /stocks/api/* — 포트폴리오·프리셋 (엔진·화면은 아직)


# ── API 문서 — 관리자만 ──────────────────────────────────────────────
#
# `/api/v1` 을 만들면서 스키마가 생겼는데, 그걸 볼 수단이 없으면 소비자가 코드를 읽어야
# 한다. 그렇다고 공개하면 위 주석의 이유로 곤란하다 — 그래서 등급으로 가른다.


def _require_admin_docs(request: Request) -> None:
    """관리자(0·1)가 아니면 문서가 **있다는 사실도** 알리지 않는다 — 403 이 아니라 404."""
    if blog_user.level_of(getattr(request.state, "user", None)) > 1:
        raise HTTPException(status.HTTP_404_NOT_FOUND)


@app.get("/api/openapi.json", include_in_schema=False)
async def openapi_schema(request: Request):
    _require_admin_docs(request)
    return JSONResponse(app.openapi())


@app.get("/api/docs", include_in_schema=False)
async def api_docs(request: Request):
    _require_admin_docs(request)
    return get_swagger_ui_html(openapi_url="/api/openapi.json", title=f"{settings.app_name} API")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    return FileResponse(_PUBLIC / "favicon.ico")


@app.get("/robots.txt", include_in_schema=False)
async def robots() -> FileResponse:
    return FileResponse(_PUBLIC / "robots.txt")


@app.get("/healthz", include_in_schema=False)
async def healthz() -> PlainTextResponse:
    return PlainTextResponse("ok")
