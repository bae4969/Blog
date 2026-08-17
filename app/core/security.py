"""인증 — **검증 전용**.

이 서비스는 계정을 다루지 않고 토큰을 발급하지도 않는다. 중앙 인증(`10.auth`)이 RS256
개인키로 서명한 토큰을 **공개키로 확인만** 한다. 그래서 개인키가 없고, 이 서비스가
뚫려도 토큰을 위조할 수 없다.

공개키는 기동 시 한 번 받아 캐시한다 — 검증에 auth 를 부르지 않으므로 auth 가 잠시
죽어도 이미 로그인한 사용자는 계속 쓸 수 있다.
"""

import logging
from dataclasses import dataclass, field

import httpx
import jwt
from fastapi import HTTPException, Request, status

from app.core.config import settings

logger = logging.getLogger(__name__)

# SECURITY: algorithms 를 명시해 alg=none 과 알고리즘 혼동 공격을 차단한다.
_ALGORITHM = "RS256"

ROLE_USER = "user"
ROLE_ADMIN = "admin"

_verify_key: str | None = None


@dataclass
class AuthUser:
    uid: str
    roles: list[str] = field(default_factory=list)
    cn: str | None = None
    mail: str | None = None
    totp_pending: bool = False

    @property
    def role(self) -> str:
        return self.roles[0] if self.roles else "user"

    @property
    def is_admin(self) -> bool:
        return ROLE_ADMIN in self.roles


class TokenError(Exception):
    pass


async def fetch_public_key(*, force: bool = False) -> str:
    """auth 에서 검증용 공개키를 받아 캐시한다."""
    global _verify_key
    if _verify_key and not force:
        return _verify_key

    url = f"{settings.auth_base_url}/api/auth/public-key"
    async with httpx.AsyncClient(timeout=5.0) as cl:
        r = await cl.get(url)
        r.raise_for_status()
    _verify_key = r.text
    logger.info("auth 공개키를 받았다 (%s)", url)
    return _verify_key


def verify_token(token: str) -> dict:
    if not _verify_key:
        raise TokenError("verify key not loaded")
    try:
        return jwt.decode(token, _verify_key, algorithms=[_ALGORITHM])
    except jwt.ExpiredSignatureError as e:
        raise TokenError("expired") from e
    except jwt.InvalidTokenError as e:
        raise TokenError("invalid") from e


def auth_user_from_payload(payload: dict) -> AuthUser:
    return AuthUser(
        uid=payload.get("sub", ""),
        roles=list(payload.get("roles", [])),
        cn=payload.get("cn"),
        mail=payload.get("mail"),
        totp_pending=bool(payload.get("totp_pending")),
    )


def current_user_or_none(request: Request) -> AuthUser | None:
    token = request.cookies.get(settings.cookie_name)
    if not token:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
    if not token:
        return None
    try:
        return auth_user_from_payload(verify_token(token))
    except TokenError:
        return None


#: 새로 받은 세션 쿠키의 수명. auth 의 `jwt_expire_minutes`(10분)와 맞춘다 — 길게 주면
#: 브라우저가 이미 죽은 토큰을 계속 보내게 된다.
_SESSION_MAX_AGE = 10 * 60
#: 기기 쿠키는 장기 자격증명이다. auth 와 같은 값(브라우저 상한).
_DEVICE_MAX_AGE = 400 * 24 * 3600


async def refresh_session(request: Request) -> tuple[AuthUser, str, str | None] | None:
    """만료된 세션을 **기기 신뢰 쿠키로** 되살린다. 실패하면 None.

    ## 왜 필요한가

    auth 세션은 10분이다. 다른 서비스는 만료될 때마다 `/api/auth/device-refresh` 를 불러
    조용히 새 토큰을 받아 가는데 **블로그만 그걸 안 하고 있었다**(2026-08-17 발견).
    그래서 화면을 열고 10분이 지나면 로그인이 필요한 동작이 전부 401 이 났다 — 브라우저엔
    기기 신뢰 쿠키가 멀쩡히 있고 화면도 "로그인됨" 으로 보이는데도 그랬다.

    ⚠️ 기기 토큰은 **쓸 때마다 회전한다.** 여기서 받은 새 값을 반드시 응답 쿠키로 돌려
       줘야 브라우저가 다음에 쓸 수 있다. 돌려주지 않으면 그 브라우저의 신뢰가 죽는다.
       (auth 쪽에 60초 유예가 있어 탭이 겹쳐도 한 번은 버틴다 — 그래도 돌려주는 게 맞다.)
    ⚠️ auth 가 죽어 있어도 화면은 떠야 하므로 **예외는 삼키고 비로그인으로 넘긴다.**
    """
    device = request.cookies.get(settings.device_cookie_name)
    if not device:
        return None
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            res = await client.post(
                f"{settings.auth_base_url}/api/auth/device-refresh",
                cookies={settings.device_cookie_name: device},
            )
        if res.status_code != 200:
            return None
        body = res.json()
        token = body.get("token")
        if not token:
            return None
        return auth_user_from_payload(verify_token(token)), token, body.get("device_token")
    except (httpx.HTTPError, TokenError, ValueError) as exc:
        logger.warning("세션 자동 갱신 실패 — 비로그인으로 진행한다: %s", exc)
        return None


def attach_session(response, token: str, device_token: str | None) -> None:
    """갱신한 토큰을 쿠키로 심는다 — auth 와 **같은 속성**이어야 덮어써진다."""
    common = {"domain": settings.cookie_domain, "path": "/",
              "httponly": True, "secure": True, "samesite": "lax"}
    response.set_cookie(settings.cookie_name, token, max_age=_SESSION_MAX_AGE, **common)
    if device_token:
        response.set_cookie(settings.device_cookie_name, device_token,
                            max_age=_DEVICE_MAX_AGE, **common)


def require_auth(request: Request) -> AuthUser:
    """로그인 필수. 미인증이면 401 — UI 경로의 리다이렉트는 미들웨어가 맡는다."""
    user = getattr(request.state, "user", None) or current_user_or_none(request)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required"
        )
    return user


def require_admin(request: Request) -> AuthUser:
    user = require_auth(request)
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin only")
    return user
