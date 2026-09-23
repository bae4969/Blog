"""사이트 진입점 — `/` 가 도메인을 보고 어디로 보내는지. DB 없이 본다.

2026-09-23 주식이 메인이 됐다. `blog.` 로 들어온 사람만 블로그로 가고, 나머지는 전부
주식으로 간다. 이 값이 뒤집히면 운영 첫 화면이 조용히 바뀐다.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    # ⚠️ lifespan 을 켜면 기동 시 auth 공개키를 받으러 나간다 — CI 에서는 닿지 않는다.
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.mark.parametrize("host, target", [
    ("blog.bdda.duckdns.org", "/blog"),
    ("stock.bdda.duckdns.org", "/stocks"),
    ("blogtest.bdda.duckdns.org", "/stocks"),   # `blog` 로 시작해도 `blog` 는 아니다
    ("localhost:8080", "/stocks"),
])
def test_루트는_도메인별로_나뉜다(client, host, target):
    r = client.get("/", headers={"host": host}, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == target


def test_쿼리를_실어_보낸다(client):
    r = client.get("/?market=US", headers={"host": "stock.bdda.duckdns.org"}, follow_redirects=False)
    assert r.headers["location"] == "/stocks?market=US"
