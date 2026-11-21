"""설정 — 환경변수(.env.api) → Settings.

⚠️ 기존 PHP 의 `config/database.php` 와 **같은 DB(`Blog`)** 를 본다. 이 프로젝트는
테스트본이지만 데이터는 운영과 공유한다 — 포팅 중 쓰기 경로를 건드릴 때 주의할 것.
지금 단계(읽기 전용 목록·상세)에서는 문제되지 않는다.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _normalize_domain(value: str) -> str:
    """도메인 문자열 정규화 — 소문자·앞뒤 공백과 점 제거."""
    return value.strip().strip(".").lower()


def _extract_host(request_or_host) -> str:
    """Request 또는 호스트 문자열에서 포트·끝 점을 뗀 소문자 호스트명을 꺼낸다."""
    if request_or_host is None:
        return ""
    if isinstance(request_or_host, str):
        raw = request_or_host
    else:
        raw = request_or_host.headers.get("host", "") or (request_or_host.url.hostname or "")
    raw = raw.strip().lower()
    if not raw:
        return ""
    if raw.startswith("["):
        end = raw.find("]")
        return raw[1:end] if end != -1 else raw
    return raw.split(":", 1)[0].rstrip(".")


class Settings(BaseSettings):
    # PHP 쪽 .env 와 섞이지 않게 파일명을 나눈다.
    model_config = SettingsConfigDict(
        env_file=".env.api", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Developer Notes"
    debug: bool = False

    # 환경마다 다른 값은 .env.api 에서 받는다 — 공개 저장소라 기본값은 예시만 둔다.
    base_domain: str = Field(default="example.com", alias="BASE_DOMAIN")
    # 병행 운영할 추가 상위 도메인(쉼표·공백 구분, 예: "onulkit.com"). 10.auth 와 같은 규약.
    extra_domains: str = Field(default="", alias="EXTRA_DOMAINS")

    @property
    def allowed_domains(self) -> tuple[str, ...]:
        """허용된 상위 도메인 화이트리스트(주 도메인 우선, 중복 제거)."""
        raw_items = [self.base_domain, *self.extra_domains.replace(",", " ").split()]
        seen: list[str] = []
        for item in raw_items:
            domain = _normalize_domain(item)
            if domain and domain not in seen:
                seen.append(domain)
        return tuple(seen)

    def match_domain(self, host: str | None) -> str | None:
        """호스트가 허용 도메인 중 하나(자신 또는 서브도메인)에 속하면 그 상위 도메인."""
        normalized = _extract_host(host)
        if not normalized:
            return None
        matches = [
            d for d in self.allowed_domains if normalized == d or normalized.endswith(f".{d}")
        ]
        return max(matches, key=len) if matches else None

    def domain_for(self, request_or_host=None) -> str:
        """요청 호스트에 대응하는 상위 도메인. 화이트리스트 밖(내부 호출 등)이면 `BASE_DOMAIN`."""
        matched = self.match_domain(_extract_host(request_or_host))
        return matched or _normalize_domain(self.base_domain)

    # ── 데이터베이스 ──────────────────────────────────────────────
    # 운영 블로그와 같은 스키마다. 읽기만 하는 동안은 계정에 SELECT 만 줘도 된다.
    database_url: str = Field(
        default="mariadb+aiomysql://blog_ro:changeme@mariadb:3306/Blog",
        alias="DATABASE_URL",
    )

    # ── 중앙 인증 (10.auth) ───────────────────────────────────────
    # 이 서비스는 로그인을 처리하지 않는다. auth 가 RS256 으로 서명한 토큰을 공개키로
    # **검증만** 한다. ⚠️ base 는 컨테이너 이름(서버 간), public 은 브라우저를 보낼 주소.
    auth_base_url: str = Field(default="http://bae-auth:8080", alias="AUTH_BASE_URL")
    auth_public_url: str = Field(
        default="https://auth.example.com", alias="AUTH_PUBLIC_URL"
    )
    cookie_name: str = "session"
    #: 기기 신뢰(자동 로그인) 쿠키. 세션이 만료됐을 때 이 값으로 조용히 새 세션을 받는다.
    device_cookie_name: str = "device_refresh"
    #: 쿠키를 심을 도메인. 서브도메인이 공유해야 하므로 앞에 점을 붙인다(auth 와 같은 규약).
    @property
    def cookie_domain(self) -> str:
        return f".{_normalize_domain(self.base_domain)}"

    def cookie_domain_for(self, request_or_host=None) -> str:
        """요청 호스트 계열의 쿠키 도메인(예: `.onulkit.com`)."""
        return f".{self.domain_for(request_or_host)}"

    def auth_public_url_for(self, request_or_host=None) -> str:
        """요청 호스트 계열의 브라우저용 auth 주소. 화이트리스트 밖이면 `AUTH_PUBLIC_URL`."""
        matched = self.match_domain(_extract_host(request_or_host))
        if matched:
            return f"https://auth.{matched}"
        return self.auth_public_url.rstrip("/")

    # ── 권한 ──────────────────────────────────────────────────────
    # PHP 규약을 그대로 따른다: level 은 **낮을수록** 권한이 높다(0:root … 4:visitor).
    # 비로그인은 4 로 본다(`src/Core/Auth.php:122`).
    anonymous_level: int = 4

    # 목록 한 쪽에 몇 개(PHP 의 perPage=10 과 맞춘다 — 페이지 번호가 어긋나면 안 된다).
    posts_per_page: int = 10

    # ── 화면 표시값 ───────────────────────────────────────────────
    # 실제 값은 .env.api(CONTACT_EMAIL) — 공개 저장소라 기본값은 비워 둔다.
    contact_email: str = Field(default="", alias="CONTACT_EMAIL")
    github_url: str = Field(default="https://github.com/bae4969", alias="GITHUB_URL")

    docs_enabled: bool = Field(default=False, alias="DOCS_ENABLED")

    # ── AI CLI (codex · agy) ─────────────────────────────────────
    # 블로그 컨테이너 안에서 `codex exec` 또는 `agy -p=` 를 부른다(app/services/{codex,agy,ai}_runner.py).
    # 로그인은 관리자 › 외부 연동에서 하며 codex 는 `CODEX_HOME/auth.json`, agy 는 `AGY_HOME` 아래에 남는다.
    codex_bin: str = Field(default="codex", alias="CODEX_BIN")
    codex_home: str = Field(default="", alias="CODEX_HOME")
    agy_bin: str = Field(default="", alias="AGY_BIN")
    agy_home: str = Field(default="", alias="AGY_HOME")
    # 상담 중 AI CLI 가 붙는 블로그 MCP — 같은 컨테이너의 앱 자신(uvicorn 8080).
    plan_mcp_url: str = Field(default="http://127.0.0.1:8080/mcp", alias="PLAN_MCP_URL")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
