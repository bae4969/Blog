"""API 의존성 — 쓰기는 **Bearer 토큰으로만** 받는다.

## 왜 쿠키를 안 받나 (CSRF)

쿠키는 브라우저가 **요청마다 알아서 붙인다.** 그래서 남의 사이트에 심어 둔 폼이나
스크립트가 사용자의 쿠키를 업고 우리 API 에 쓰기를 날릴 수 있고, 그걸 막으려면 CSRF
토큰 같은 장치를 따로 둬야 한다(화면의 폼은 double submit cookie 로 그렇게 한다).

`Authorization` 헤더는 다르다. **브라우저가 자동으로 붙이지 않는다.** 남의 페이지에서
우리 API 로 요청을 보내도 토큰이 실리지 않으므로 CSRF 가 원리적으로 성립하지 않는다.
그래서 쓰기는 Bearer 만 받는다 — 소비자는 앱·스크립트고, 그쪽은 토큰을 직접 싣는다.

⚠️ 읽기(GET)는 쿠키도 받는다. 화면과 같은 사람으로 보여야 등급별로 보이는 글이
   일치하고, 읽기에는 CSRF 위험이 없다.
"""

from fastapi import HTTPException, Request, status

from app.core import blog_user
from app.core.blog_user import BlogUser
from app.core.security import AuthUser


def bearer_user(request: Request) -> AuthUser:
    """`Authorization: Bearer <jwt>` 로 인증된 사용자. 없거나 틀리면 401.

    ⚠️ **쿠키는 보지 않는다.** `request.state.user` 는 미들웨어가 쿠키로도 채우므로
       그걸 쓰면 쿠키 인증 쓰기가 열려 CSRF 구멍이 된다 — 헤더가 있었는지 직접 본다.
    """
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "쓰기에는 Authorization: Bearer 토큰이 필요합니다(쿠키는 받지 않습니다)",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = getattr(request.state, "user", None)
    if user is None:
        # 헤더는 있는데 state 가 비었다 = 토큰이 만료·위조됐다는 뜻이다.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "토큰이 유효하지 않습니다",
                            headers={"WWW-Authenticate": "Bearer"})
    return user


async def writer(db, request: Request) -> BlogUser:
    """글을 쓸 수 있는 사람인가. 화면(`/writer.php`)과 같은 두 관문을 통과해야 한다."""
    user = bearer_user(request)
    me = await blog_user.find(db, user)
    if me is None:
        # auth 계정은 있지만 `user_list` 에 행이 없다 — 아직 블로그 사용자가 아니다.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "블로그 계정이 연결되지 않았습니다")
    if me.is_limited:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            f"작성 제한에 걸렸습니다({me.posting_count}/{me.posting_limit})")
    return me
