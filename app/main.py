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
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core import ip_block
from app.core.security import (
    attach_session,
    current_user_or_none,
    fetch_public_key,
    refresh_session,
)
from app.db.session import db_session
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
    docs_url=None,
    redoc_url=None,
    # 인증 API 와 같은 방침 — 스키마를 인터넷에 그냥 내주지 않는다.
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


class BlockedIpMiddleware(BaseHTTPMiddleware):
    """차단된 IP 를 앱에 들이지 않는다.

    ⚠️ **인증보다 먼저 돌아야 한다.** Starlette 은 나중에 add 한 미들웨어가 바깥쪽이므로
       이 클래스를 `OptionalAuthMiddleware` **뒤에** 등록한다.
    ⚠️ `/healthz` 는 통과시킨다 — 컨테이너 헬스체크가 막히면 앱이 죽은 것으로 오인된다.
    ⚠️ IP 는 `request.client.host` 로 얻는다. uvicorn 이 `--proxy-headers` 로 떠 있어
       X-Forwarded-For 가 반영된다 — 없으면 모두가 게이트웨이 하나로 보여 전부 막힌다.
    """

    async def dispatch(self, request: Request, call_next):
        if request.url.path != "/healthz":
            ip = request.client.host if request.client else None
            try:
                async with db_session() as db:
                    blocked = await ip_block.is_blocked(db, ip)
            except Exception:
                # DB 가 흔들릴 때 사이트를 통째로 막지 않는다 — 차단은 부가 기능이다.
                logger.exception("차단 IP 조회 실패 — 통과시킨다")
                blocked = False
            if blocked:
                logger.warning("차단된 IP 접근: %s %s", ip, request.url.path)
                return PlainTextResponse("Forbidden", status_code=403)
        return await call_next(request)


app.add_middleware(OptionalAuthMiddleware)
app.add_middleware(BlockedIpMiddleware)   # 바깥쪽 — 인증보다 먼저 돈다

# ── 정적 파일 — 옛 PHP 문서루트(`public/`)를 그대로 서빙한다 ──────────────
#
# 지금까지 `/css/*`·`/res/*`·`/vendor/quill/*` 은 **PHP 컨테이너**가 줬다. PHP 를 걷어내면
# 아무도 안 주게 되므로 여기서 받는다. 경로를 바꾸지 않는 이유는 옛 링크·북마크와 PHP 뷰가
# 같은 URL 을 쓰기 때문이다(`/css/blog.css` 등).
#
# ⚠️ `uploads` 는 사용자가 올린 이미지라 **글 본문이 이 URL 을 직접 가리킨다.** 경로를 바꾸면
#    기존 글의 이미지가 전부 깨진다.
_PUBLIC = Path(__file__).parent.parent / "public"
for _sub in ("css", "js", "res", "vendor", "uploads"):
    _dir = _PUBLIC / _sub
    if _dir.is_dir():
        app.mount(f"/{_sub}", StaticFiles(directory=_dir), name=f"public-{_sub}")

app.include_router(ui_router)
app.include_router(admin_router)   # /admin/*
app.include_router(stocks_router)   # /stocks — 목록·상세·차트
app.include_router(backtest_router) # /stocks/api/* — 포트폴리오·프리셋 (엔진·화면은 아직)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    return FileResponse(_PUBLIC / "favicon.ico")


@app.get("/robots.txt", include_in_schema=False)
async def robots() -> FileResponse:
    return FileResponse(_PUBLIC / "robots.txt")


@app.get("/healthz", include_in_schema=False)
async def healthz() -> PlainTextResponse:
    return PlainTextResponse("ok")
