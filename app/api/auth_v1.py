"""`/api/v1/auth` — 화면이 `/api/v1` 을 쓰기 위한 토큰 창구.

## 왜 이게 필요한가

`/api/v1` 의 쓰기(그리고 개인 데이터 읽기)는 **Bearer 전용**이다. 쿠키는 브라우저가
요청마다 알아서 붙여서 CSRF 가 성립하지만, `Authorization` 헤더는 남의 사이트가 붙일 수
없기 때문이다([deps](deps.py) 참조).

그런데 **인증 쿠키는 `httponly` 라 JS 가 읽을 수 없다.** 그래서 화면은 `/api/v1` 을 부를
방법이 아예 없었다 — 프리셋 목록조차 못 읽었다. 여기가 그 다리다: 쿠키 세션을 가진
사람에게 지금 세션의 토큰을 **본문으로** 건넨다.

## 왜 이래도 CSRF 가 안 뚫리나

남의 사이트가 이 엔드포인트를 부르게 만들 수는 있다(쿠키는 실린다). 하지만 **응답을 읽을
수 없다** — 동일 출처 정책이 막고, 이 서버는 CORS 허용 헤더를 내보내지 않는다. 토큰을
손에 넣지 못하므로 그 다음 쓰기 요청을 만들 수 없다.

## 무엇을 건네나

세션 쿠키에 든 **그 JWT 를 그대로** 준다. 이 서비스는 토큰을 발급하지 않는다(중앙 인증이
RS256 으로 서명한다) — 새로 만들 열쇠가 없다.

⚠️ 즉 **XSS 가 있으면 토큰이 새어 나간다.** 다만 그 피해는 두 가지로 묶여 있다:

- 세션 토큰의 수명이 **10분**이다(`_SESSION_MAX_AGE`, auth 의 만료와 맞춰 둔 값).
- 갱신에 쓰는 **기기 쿠키는 여기서 안 준다.** `httponly` 로 남으므로, 새어 나간 토큰으로
  세션을 이어 붙일 수 없다.

XSS 가 있으면 어차피 그 페이지에서 쿠키를 업고 요청을 보낼 수 있으니, 이 창구가 새로
여는 것은 "10분짜리 토큰을 밖으로 들고 나갈 수 있다" 는 정도다.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.security import TokenError, verify_token

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class SessionToken(BaseModel):
    """`Authorization: Bearer <access_token>` 으로 그대로 쓰면 된다."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="남은 수명(초). 이보다 앞서 다시 받아야 한다")


@router.post("/token", response_model=SessionToken, summary="세션 쿠키 → Bearer 토큰")
async def session_token(request: Request, response: Response):
    """로그인 쿠키를 가진 사람에게 지금 세션의 토큰을 준다.

    ⚠️ **쿠키만 본다.** 이미 Bearer 로 부르는 소비자는 토큰이 있으므로 여기 올 일이 없고,
       헤더를 받아 주면 남의 토큰을 되돌려 주는 통로가 하나 더 생길 뿐이다.
    """
    token = request.cookies.get(settings.cookie_name)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "로그인이 필요합니다")

    try:
        payload = verify_token(token)
    except TokenError:
        # 쿠키는 있는데 만료·위조다. 화면은 이걸 보고 다시 로그인시키면 된다.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "세션이 만료되었습니다")

    exp = payload.get("exp")
    now = int(datetime.now(timezone.utc).timestamp())
    remaining = max(0, int(exp) - now) if exp else 0

    # ⚠️ 자격증명이다. 중간 캐시에 남으면 다음 사람이 받아 갈 수 있다.
    response.headers["Cache-Control"] = "no-store"
    return SessionToken(access_token=token, expires_in=remaining)
