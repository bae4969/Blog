"""CSRF 토큰 — double submit cookie 방식.

PHP 는 세션에 토큰을 넣고 대조하는데 이 서비스에는 서버 세션이 없다. 대신 같은 값을
**쿠키와 폼 양쪽**에 실어 보내고 서버에서 두 값을 비교한다. 공격자는 남의 도메인에서
폼을 제출할 수는 있어도 그 사람의 쿠키 **값을 읽을 수는 없으므로** 같은 값을 폼에 넣지
못한다.

쿠키에 `httponly` 를 걸지 않는다 — 폼을 JS 로 만드는 경우까지 감안한 관례다. 대신
`samesite=strict` 로 cross-site 요청에는 쿠키가 아예 안 실리게 해 이중으로 막는다.
"""

import hmac
import secrets

from fastapi import Request, Response

COOKIE = "csrf_token"
FIELD = "csrf_token"


def new_token(request: Request) -> str:
    """이번 폼에 쓸 토큰. 이미 쿠키가 있으면 재사용한다 — 탭을 여러 개 열어 두었을 때
    나중에 연 탭이 토큰을 갈아 끼워 먼저 연 탭의 제출이 깨지는 걸 막는다."""
    return request.cookies.get(COOKIE) or secrets.token_urlsafe(32)


def attach(response: Response, token: str) -> None:
    """응답에 토큰 쿠키를 심는다. 폼에 넣은 값과 **같아야** 한다."""
    response.set_cookie(
        COOKIE,
        token,
        max_age=3600,
        httponly=False,  # 위 docstring 참조
        samesite="strict",
        secure=True,
    )


def valid(request: Request, submitted: str | None) -> bool:
    """폼에 실려 온 값이 쿠키와 같은가. 타이밍 차이를 없애려 상수 시간으로 비교한다."""
    cookie = request.cookies.get(COOKIE)
    if not cookie or not submitted:
        return False
    return hmac.compare_digest(cookie, submitted)
