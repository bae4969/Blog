"""설치형 앱(PWA) — manifest 와 서비스워커가 **설치 조건대로** 나가는지. DB 없이 본다.

⚠️ 둘 다 조용히 깨진다. manifest 값 하나(`display`)가 어긋나도 화면은 멀쩡하고 "설치" 만 안
   뜬다. 서비스워커가 캐시되는 헤더로 나가면 고쳐도 브라우저가 옛 것을 계속 쓴다.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    # ⚠️ lifespan 을 켜면 기동 시 auth 공개키를 받으러 나간다 — CI 에서는 닿지 않는다.
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestServiceWorker:
    def test_루트에서_캐시_없이_나간다(self, client):
        """범위가 파일 경로까지라 루트여야 하고, 캐시되면 갱신이 늦어진다."""
        r = client.get("/sw.js")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/javascript")
        assert r.headers["cache-control"] == "no-cache"


class TestManifest:
    @pytest.fixture(scope="class")
    def manifest(self, client):
        r = client.get("/site.webmanifest")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/manifest+json")
        return r.json()

    def test_설치형으로_열린다(self, manifest):
        assert manifest["display"] == "standalone"   # "browser" 면 설치가 안 뜬다
        assert manifest["start_url"] == "/blog"
        assert manifest["scope"] == "/"

    def test_아이콘(self, client, manifest):
        """192·512(any)와 512 maskable 이 있고, 실제로 받아진다."""
        icons = {(i["sizes"], i["purpose"]): i["src"] for i in manifest["icons"]}
        assert {("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")} <= set(icons)
        for src in icons.values():
            r = client.get(src)
            assert r.status_code == 200, src
            assert r.headers["content-type"] == "image/png", src
