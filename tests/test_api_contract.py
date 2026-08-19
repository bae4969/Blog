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
