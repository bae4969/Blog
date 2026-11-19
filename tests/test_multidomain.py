"""멀티 도메인 병행 지원 — 도메인 매칭·쿠키 도메인·auth 공개 주소·세션 자동 갱신."""

import time

import pytest
from fastapi.testclient import TestClient

from app import main
from app.api import auth_v1
from app.core.config import settings
from app.core.security import AuthUser


@pytest.fixture(scope="module")
def client():
    with TestClient(app=main.app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def dual_domains(monkeypatch):
    monkeypatch.setattr(settings, "base_domain", "bdda.duckdns.org")
    monkeypatch.setattr(settings, "extra_domains", "onulkit.com")
    monkeypatch.setattr(settings, "auth_public_url", "https://auth.bdda.duckdns.org")


class TestMultiDomainConfig:
    def test_허용_도메인_정규화_중복제거(self, monkeypatch):
        monkeypatch.setattr(settings, "base_domain", " Bdda.DuckDNS.org ")
        monkeypatch.setattr(settings, "extra_domains", " .onulkit.com, onulkit.com  example.net ")
        assert settings.allowed_domains == ("bdda.duckdns.org", "onulkit.com", "example.net")

    @pytest.mark.parametrize("host, expected_domain, expected_cookie, expected_auth", [
        ("blog.bdda.duckdns.org", "bdda.duckdns.org", ".bdda.duckdns.org", "https://auth.bdda.duckdns.org"),
        ("stock.bdda.duckdns.org", "bdda.duckdns.org", ".bdda.duckdns.org", "https://auth.bdda.duckdns.org"),
        ("blogtest.bdda.duckdns.org", "bdda.duckdns.org", ".bdda.duckdns.org", "https://auth.bdda.duckdns.org"),
        ("blog.onulkit.com", "onulkit.com", ".onulkit.com", "https://auth.onulkit.com"),
        ("stock.onulkit.com", "onulkit.com", ".onulkit.com", "https://auth.onulkit.com"),
        ("blogtest.onulkit.com", "onulkit.com", ".onulkit.com", "https://auth.onulkit.com"),
        ("BLOG.ONULKIT.COM:443", "onulkit.com", ".onulkit.com", "https://auth.onulkit.com"),
        ("onulkit.com.", "onulkit.com", ".onulkit.com", "https://auth.onulkit.com"),
    ])
    def test_허용_도메인_분기(self, dual_domains, host, expected_domain, expected_cookie, expected_auth):
        assert settings.domain_for(host) == expected_domain
        assert settings.cookie_domain_for(host) == expected_cookie
        assert settings.auth_public_url_for(host) == expected_auth

    @pytest.mark.parametrize("host", [
        "evil-onulkit.com",
        "onulkit.com.evil.test",
        "localhost:8080",
        "bae-blog:8080",
        "",
    ])
    def test_화이트리스트_밖은_기본_도메인으로_폴백(self, dual_domains, host):
        assert settings.match_domain(host) is None
        assert settings.domain_for(host) == "bdda.duckdns.org"
        assert settings.cookie_domain_for(host) == ".bdda.duckdns.org"
        assert settings.auth_public_url_for(host) == "https://auth.bdda.duckdns.org"


class TestMultiDomainSessionRefresh:
    @pytest.mark.parametrize("host, expected_cookie_domain", [
        ("blog.bdda.duckdns.org", "Domain=.bdda.duckdns.org"),
        ("stock.bdda.duckdns.org", "Domain=.bdda.duckdns.org"),
        ("blog.onulkit.com", "Domain=.onulkit.com"),
        ("stock.onulkit.com", "Domain=.onulkit.com"),
        ("blogtest.onulkit.com", "Domain=.onulkit.com"),
        ("evil-onulkit.com", "Domain=.bdda.duckdns.org"),
    ])
    def test_자동_세션_갱신_쿠키가_요청_도메인_계열로_발급된다(
        self, client, dual_domains, monkeypatch, host, expected_cookie_domain
    ):
        exp = int(time.time()) + 600

        async def renewed(request):
            return AuthUser(uid="u"), "renewed-jwt", "new-device"

        monkeypatch.setattr(main, "refresh_session", renewed)
        monkeypatch.setattr(auth_v1, "verify_token", lambda t: {"sub": "u", "exp": exp})

        r = client.post(
            "/api/v1/auth/token",
            headers={"host": host},
            cookies={settings.device_cookie_name: "old-device"},
        )
        client.cookies.clear()
        assert r.status_code == 200
        set_cookies = r.headers.get_list("set-cookie")
        session_cookie = next(c for c in set_cookies if c.startswith(f"{settings.cookie_name}="))
        device_cookie = next(c for c in set_cookies if c.startswith(f"{settings.device_cookie_name}="))
        assert expected_cookie_domain in session_cookie
        assert expected_cookie_domain in device_cookie
