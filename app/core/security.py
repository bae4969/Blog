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
