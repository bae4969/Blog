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
def single_domain(monkeypatch):
    monkeypatch.setattr(settings, "base_domain", "onulkit.com")
    monkeypatch.setattr(settings, "extra_domains", "")
    monkeypatch.setattr(settings, "auth_public_url", "https://auth.onulkit.com")


@pytest.fixture()
def dual_domains(monkeypatch):
    monkeypatch.setattr(settings, "base_domain", "onulkit.com")
    monkeypatch.setattr(settings, "extra_domains", "example.net")
    monkeypatch.setattr(settings, "auth_public_url", "https://auth.onulkit.com")


class TestMultiDomainConfig:
    def test_허용_도메인_정규화_중복제거(self, monkeypatch):
        monkeypatch.setattr(settings, "base_domain", " Onulkit.COM ")
        monkeypatch.setattr(settings, "extra_domains", " .onulkit.com, example.net  example.org ")
        assert settings.allowed_domains == ("onulkit.com", "example.net", "example.org")

    @pytest.mark.parametrize("host", [
        "blog.onulkit.com",
        "stock.onulkit.com",
        "blogtest.onulkit.com",
        "BLOG.ONULKIT.COM:443",
        "onulkit.com.",
    ])
    def test_단일_도메인_매칭(self, single_domain, host):
        assert settings.allowed_domains == ("onulkit.com",)
        assert settings.domain_for(host) == "onulkit.com"
        assert settings.cookie_domain_for(host) == ".onulkit.com"
        assert settings.auth_public_url_for(host) == "https://auth.onulkit.com"

    @pytest.mark.parametrize("host, expected_domain, expected_cookie, expected_auth", [
        ("blog.onulkit.com", "onulkit.com", ".onulkit.com", "https://auth.onulkit.com"),
        ("stock.onulkit.com", "onulkit.com", ".onulkit.com", "https://auth.onulkit.com"),
        ("blogtest.onulkit.com", "onulkit.com", ".onulkit.com", "https://auth.onulkit.com"),
        ("blog.example.net", "example.net", ".example.net", "https://auth.example.net"),
        ("BLOG.EXAMPLE.NET:443", "example.net", ".example.net", "https://auth.example.net"),
        ("example.net.", "example.net", ".example.net", "https://auth.example.net"),
    ])
    def test_허용_도메인_분기(self, dual_domains, host, expected_domain, expected_cookie, expected_auth):
        assert settings.domain_for(host) == expected_domain
        assert settings.cookie_domain_for(host) == expected_cookie
        assert settings.auth_public_url_for(host) == expected_auth

    @pytest.mark.parametrize("host", [
        "blog.bdda.duckdns.org",
        "evil-onulkit.com",
        "onulkit.com.evil.test",
        "localhost:8080",
        "bae-blog:8080",
        "",
    ])
    def test_화이트리스트_밖은_기본_도메인으로_폴백(self, single_domain, host):
        assert settings.match_domain(host) is None
        assert settings.domain_for(host) == "onulkit.com"
        assert settings.cookie_domain_for(host) == ".onulkit.com"
        assert settings.auth_public_url_for(host) == "https://auth.onulkit.com"


class TestMultiDomainSessionRefresh:
    @pytest.mark.parametrize("host, expected_cookie_domain", [
        ("blog.onulkit.com", "Domain=.onulkit.com"),
        ("stock.onulkit.com", "Domain=.onulkit.com"),
        ("blogtest.onulkit.com", "Domain=.onulkit.com"),
        ("blog.example.net", "Domain=.example.net"),
        ("blog.bdda.duckdns.org", "Domain=.onulkit.com"),
        ("evil-onulkit.com", "Domain=.onulkit.com"),
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
