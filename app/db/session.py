"""비동기 DB 세션 — MariaDB (aiomysql).

⚠️ 이 스키마(`Blog`)는 **운영 블로그와 공유**한다. PHP 쪽(`config/database.php`)이 같은
곳을 본다. 포팅이 끝나기 전까지 두 스택이 같은 테이블을 동시에 읽으므로, 쓰기를 넣을
때는 PHP 쪽 동작과 충돌하지 않는지 먼저 확인할 것.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


def _pin_session_defaults(dbapi_conn, _record) -> None:
    """새 커넥션마다 세션 타임존(UTC)과 격리 수준(READ COMMITTED)을 고정한다.

    **타임존** — MariaDB 에는 tz-aware 타입이 없고 서버의 `@@global.time_zone` 은
    SYSTEM(이 NAS 는 Asia/Seoul)이다. 고정하지 않으면 DB 가 채우는 시각과 앱이 만드는
    시각이 **9시간 어긋난다.** 글 작성·수정 시각을 다루므로 반드시 맞춰 둔다.

    ⚠️ PHP 쪽은 이 설정을 하지 않아 `posting_*_datetime` 이 **KST 로 저장**돼 있다.
    화면에 뿌릴 때 UTC 로 착각해 변환하면 9시간이 밀린다 — 이 컬럼들은 이미 현지
    시각이라고 보고 그대로 쓴다.

    **격리 수준** — MariaDB 11.6+ 는 `innodb_snapshot_isolation` 이 기본 ON 이라
    "읽은 행이 그 뒤 바뀌었으면 쓰기 거부"(1020)를 던진다. 읽고 이어서 쓰는 경로
    (조회수 증가 등)가 그 조합에 걸릴 수 있어 READ COMMITTED 로 맞춘다.
    """
    cur = dbapi_conn.cursor()
    cur.execute("SET SESSION time_zone = '+00:00'")
    cur.execute("SET SESSION transaction_isolation = 'READ-COMMITTED'")
    cur.close()


def make_engine(url: str, **kwargs):
    """세션 기본값(UTC·READ COMMITTED)이 걸린 async 엔진.

    ⚠️ `_pin_session_defaults` 는 **엔진 단위 이벤트**라 다른 곳에서
    `create_async_engine` 을 직접 부르면 조용히 빠진다(테스트가 실제로 그랬다).
    엔진을 만드는 길을 이 함수 하나로 묶어 막는다.
    """
    eng = create_async_engine(url, **kwargs)
    event.listen(eng.sync_engine, "connect", _pin_session_defaults)
    return eng


engine = make_engine(
    settings.database_url,
    echo=settings.debug,
    # pool_pre_ping 은 쓰지 않는다 — SQLAlchemy 2.0.48 + aiomysql 조합에서
    # do_ping 이 `ping()` 을 인자 없이 불러 매 체크아웃마다 TypeError 로 죽는다.
    # MySQL 계열 표준인 pool_recycle 로 대체한다(기본 wait_timeout 28800s 보다 짧게).
    pool_recycle=3600,
)

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """모든 ORM 모델의 베이스."""


@asynccontextmanager
async def db_session() -> AsyncIterator[AsyncSession]:
    """공용 async 세션. 자동 commit 을 넣지 않는다 — 호출부가 명시적으로 커밋한다
    (실패 카운트처럼 예외 직전에 커밋해야 하는 경로가 있다)."""
    async with AsyncSessionLocal() as session:
        yield session


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI Depends — 요청 단위 세션. 정상 종료 시 commit, 예외 시 rollback."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
