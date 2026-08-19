"""`/api/v1` 계약 — **DB 없이** 확인할 수 있는 것들.

CI 러너에는 DB 가 없다. 그래서 여기서는 핸들러에 닿기 **전에** 판정되는 것만 다룬다:

- 파라미터 검증(FastAPI 가 핸들러 호출 전에 422 를 낸다)
- 라우트가 실제로 등록됐는지
- 문서 노출 정책(등급만 보고 판단하므로 DB 를 안 탄다)

DB 를 타는 응답 내용은 여기서 못 본다 — 그건 실제 환경에서 확인한다.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    # ⚠️ lifespan 을 켜면 기동 시 auth 공개키를 받으러 나간다 — CI 에서는 닿지 않는다.
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestRoutesExist:
    """라우트가 사라지면 소비자가 조용히 깨진다. 경로 자체를 못 박는다.

    ⚠️ `app.routes` 를 훑지 않는다. FastAPI 버전에 따라 `.path` 없는 객체가 섞여
       (`_IncludedRouter`) 테스트가 라이브러리 버전에 휘둘린다 — CI 러너는 컨테이너보다
       최신 버전을 깔기 때문에 실제로 여기서 깨졌다. 소비자가 보는 것과 같은
       **OpenAPI 스키마**를 본다.
    """

    def test_등록된_경로(self):
        paths = set(app.openapi()["paths"])
        assert {"/api/v1/posts", "/api/v1/posts/{post_id}", "/api/v1/categories"} <= paths

    def test_화면_라우트는_스키마에_안_들어간다(self):
        """`include_in_schema=False` 로 감춰 둔 것들 — 문서가 화면 URL 로 지저분해지지 않게."""
        paths = set(app.openapi()["paths"])
        assert not any(p.startswith(("/admin", "/blog", "/reader")) for p in paths)


class TestValidation:
    """핸들러에 닿기 전에 걸러야 하는 입력들 — DB 를 안 탄다."""

    @pytest.mark.parametrize("url", [
        "/api/v1/posts?size=101",   # 상한 초과. 없으면 한 번에 전부 긁어간다
        "/api/v1/posts?size=0",
        "/api/v1/posts?page=0",     # 쪽은 1부터
        "/api/v1/posts?page=-1",
        "/api/v1/posts/abc",        # 글 번호는 정수
    ])
    def test_잘못된_입력은_422(self, client, url):
        assert client.get(url).status_code == 422

    def test_상한값은_통과한다(self, client):
        """경계값이 막히면 안 된다 — 422 만 아니면 된다(그 뒤는 DB 가 필요)."""
        assert client.get("/api/v1/posts?size=100&page=1").status_code != 422


class TestDocsAreAdminOnly:
    """스키마는 어떤 자원이 무엇을 받는지 알려주는 지도라 공개하지 않는다.

    ⚠️ 403 이 아니라 **404** 여야 한다 — 403 은 "여기 뭔가 있다"를 알려준다.
    """

    @pytest.mark.parametrize("url", ["/api/docs", "/api/openapi.json"])
    def test_비로그인은_404(self, client, url):
        assert client.get(url).status_code == 404

    @pytest.mark.parametrize("url", ["/docs", "/redoc", "/openapi.json"])
    def test_기본_경로는_열려_있지_않다(self, client, url):
        assert client.get(url).status_code == 404


class TestStockRoutes:
    """`/api/v1/stocks/*` 도 같은 규약을 따르는지."""

    def test_등록된_경로(self):
        paths = set(app.openapi()["paths"])
        assert {"/api/v1/stocks",
                "/api/v1/stocks/{code}/candles",
                "/api/v1/stocks/{code}/executions"} <= paths

    @pytest.mark.parametrize("url", [
        "/api/v1/stocks?size=101",
        "/api/v1/stocks?page=0",
        "/api/v1/stocks/005930/candles?limit=1001",   # 한 번에 전부 긁어가지 못하게
        "/api/v1/stocks/005930/candles?days=0",
        "/api/v1/stocks/005930/executions?limit=501",
    ])
    def test_잘못된_입력은_422(self, client, url):
        assert client.get(url).status_code == 422


class TestCandleTimeBase:
    """⚠️ 캔들 조회 구간은 **KST 로** 재야 한다.

    컨테이너 시계는 UTC 인데 DB 안의 시각은 전부 KST 다(`db/session.py` 가 세션 TZ 를
    +09:00 으로 못박는다). `datetime.now()` 로 재면 구간이 9시간 밀려 화면과 다른 캔들이
    나간다 — 2026-08-19 에 실제로 그렇게 짰다가 옛 API 와 종가·저가가 달라져서 잡았다.
    """

    def test_KST_기준시를_쓴다(self):
        import inspect

        from app.api import stocks_v1

        src = inspect.getsource(stocks_v1.candles)
        assert "_KST" in src, "캔들 구간을 KST 로 재지 않는다 — 9시간 어긋난다"

    def test_기준시가_UTC_보다_9시간_앞선다(self):
        from datetime import datetime, timedelta, timezone

        from app.ui.stocks import _KST

        assert _KST == timezone(timedelta(hours=9))
        gap = datetime.now(_KST).replace(tzinfo=None) - datetime.now(timezone.utc).replace(tzinfo=None)
        assert timedelta(hours=8, minutes=59) < gap < timedelta(hours=9, minutes=1)


class TestWriteIsBearerOnly:
    """⚠️ 쓰기는 **Bearer 토큰만** 받는다 — 이게 CSRF 방어의 전부다.

    쿠키는 브라우저가 요청마다 알아서 붙이므로, 쿠키 인증 쓰기를 열면 남의 사이트가
    사용자의 쿠키를 업고 글을 쓰게 할 수 있다. `Authorization` 헤더는 자동으로 붙지
    않으니 Bearer 전용이면 그 위험 자체가 없다.

    ⚠️ 이 테스트가 깨지면 **쿠키로 쓰기가 뚫린 것**이다. DB 없이 401 에서 판정되므로
       CI 에서도 돈다.
    """

    WRITES = [
        ("post", "/api/v1/posts"),
        ("patch", "/api/v1/posts/1"),
        ("delete", "/api/v1/posts/1"),
        ("post", "/api/v1/posts/1/restore"),
    ]

    @staticmethod
    def _send(client, method, url, **kw):
        # ⚠️ `client.delete(json=...)` 는 httpx 시그니처상 못 쓴다(DELETE 는 본문이
        #    없다고 본다). 네 메서드를 한 줄로 다루려면 request() 를 써야 한다.
        return client.request(method.upper(), url, json={"title": "x", "category_id": 1}, **kw)

    @pytest.mark.parametrize("method,url", WRITES)
    def test_토큰_없으면_401(self, client, method, url):
        assert self._send(client, method, url).status_code == 401

    @pytest.mark.parametrize("method,url", WRITES)
    def test_쿠키만으로는_401(self, client, method, url):
        """세션 쿠키가 있어도 헤더가 없으면 거절한다."""
        # ⚠️ 쿠키·헤더 값은 ASCII 여야 한다 — 한글을 넣으면 httpx 가 인코딩에서 죽는다.
        assert self._send(client, method, url, cookies={"session": "dummy"}).status_code == 401

    @pytest.mark.parametrize("method,url", WRITES)
    def test_401_은_WWW_Authenticate_를_준다(self, client, method, url):
        assert self._send(client, method, url).headers.get("www-authenticate") == "Bearer"

    def test_읽기는_토큰_없이도_401_이_아니다(self, client):
        """읽기까지 막으면 공개 블로그가 아니게 된다 — 여기서 401 이면 회귀다."""
        assert client.get("/api/v1/posts").status_code != 401


class TestWriteSchema:
    """입력 검증 — 핸들러(=DB)에 닿기 전에 걸러야 하는 것들."""

    @pytest.mark.parametrize("body", [
        {},                                    # category_id 없음
        {"category_id": 1},                    # title 없음
        {"title": "", "category_id": 1},       # 빈 제목
        {"title": "x" * 256, "category_id": 1},  # 제목 상한 초과
    ])
    def test_잘못된_본문은_422(self, client, body):
        r = client.post("/api/v1/posts", json=body,
                        headers={"Authorization": "Bearer dummy-token"})
        assert r.status_code == 422
