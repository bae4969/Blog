"""설정 — 환경변수(.env.api) → Settings.

⚠️ 기존 PHP 의 `config/database.php` 와 **같은 DB(`Blog`)** 를 본다. 이 프로젝트는
테스트본이지만 데이터는 운영과 공유한다 — 포팅 중 쓰기 경로를 건드릴 때 주의할 것.
지금 단계(읽기 전용 목록·상세)에서는 문제되지 않는다.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # PHP 쪽 .env 와 섞이지 않게 파일명을 나눈다.
    model_config = SettingsConfigDict(
        env_file=".env.api", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Developer Blog"
    debug: bool = False

    base_domain: str = Field(default="bdda.duckdns.org", alias="BASE_DOMAIN")

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
        default="https://auth.bdda.duckdns.org", alias="AUTH_PUBLIC_URL"
    )
    cookie_name: str = "session"

    # ── 권한 ──────────────────────────────────────────────────────
    # PHP 규약을 그대로 따른다: level 은 **낮을수록** 권한이 높다(0:root … 4:visitor).
    # 비로그인은 4 로 본다(`src/Core/Auth.php:122`).
    anonymous_level: int = 4

    # 목록 한 쪽에 몇 개(PHP 의 perPage=10 과 맞춘다 — 페이지 번호가 어긋나면 안 된다).
    posts_per_page: int = 10

    # ── 화면 표시값 ───────────────────────────────────────────────
    # PHP `config/config.php` 와 같은 값이다. 지금은 두 곳에 있으니, 바꿀 때 함께 고칠 것.
    contact_email: str = Field(default="bae4969@naver.com", alias="CONTACT_EMAIL")
    github_url: str = Field(default="https://github.com/bae4969", alias="GITHUB_URL")

    docs_enabled: bool = Field(default=False, alias="DOCS_ENABLED")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
