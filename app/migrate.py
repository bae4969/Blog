"""DB 마이그레이션 — 컨테이너가 뜰 때 **앱보다 먼저** 돈다(Dockerfile `CMD`).

    python -m app.migrate

`app/migrations/NNNN_이름.sql` 중 아직 적용하지 않은 것을 번호 순서대로 적용하고
`schema_migrations` 에 적어 둔다. 실패하면 0 이 아닌 값으로 끝나 컨테이너가 뜨지 않고,
NAS 배포 스크립트가 건강 검사에서 걸러 **옛 이미지로 되돌린다.**

## 왜 여기서 하나 (2026-09-23)

CI/CD 에서 하려면 러너에 DDL 권한을 줘야 한다 — 러너의 배포 키는 재시작 스크립트 하나만 돌게
묶여 있고, 그 구멍을 새로 낼 이유가 없다. 코드와 그 코드가 기대하는 스키마가 **같은 이미지로**
함께 움직이므로 "머지 전에 DDL 을 먼저" 같은 손 순서도 사라진다.

## 규칙 — 어기면 되돌리기가 깨진다

- **더하기만 한다**(새 테이블·새 컬럼·기본값 있는 컬럼·데이터 채우기). 지우기·이름 바꾸기·좁히기는
  하지 않는다. 배포가 실패하면 **이미지만 옛것으로 돌아가고 DB 는 그대로**라, 옛 코드가 새 스키마에서
  돌 수 있어야 한다. `tests/test_migrate.py` 가 파일을 훑어 막는다.
- **다시 돌려도 안전하게** 쓴다(`IF NOT EXISTS`). MariaDB 의 DDL 은 트랜잭션으로 묶이지 않아서, 한
  파일의 중간에서 죽으면 앞 문장은 이미 적용돼 있다 — 기록은 파일이 끝까지 성공했을 때만 남기므로
  다음 시작 때 **처음부터 다시** 돈다.
- 이미 적용된 파일은 고치지 않는다. 고칠 일이 있으면 새 번호로 낸다(체크섬이 달라지면 경고한다).

## 계정

`MIGRATE_DATABASE_URL` — 마이그레이션 전용 `blog_migrate`(CREATE·ALTER·INDEX·SELECT·INSERT·UPDATE,
`Blog`·`BlogTest` 에만). 앱 계정 `blog_api` 에는 여전히 DDL 이 없다. ⚠️ Dockerfile 이 앱을 띄우기
전에 이 값을 **환경에서 지운다** — 떠 있는 앱은 이 계정을 모른다.

값이 없으면:
- `DATABASE_URL` 도 없으면(CI·로컬) 그냥 건너뛴다.
- `DATABASE_URL` 이 있으면 앱 계정으로 **읽기만** 해서 적용 안 된 것이 있는지 본다. 있으면 앱을 띄우지
  않는다 — 운영 `.env.api` 에 이 줄을 빠뜨린 채 배포하면 새 코드가 옛 스키마에서 500 을 내는 대신
  배포가 실패해 옛 이미지로 돌아간다.
"""

import asyncio
import hashlib
import logging
import os
import re
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine

logger = logging.getLogger("migrate")

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
#: 파일 이름 — 네 자리 번호 + 소문자·숫자·밑줄. 번호가 곧 적용 순서다.
_NAME = re.compile(r"^\d{4}_[a-z0-9_]+\.sql$")

_LEDGER = (
    "CREATE TABLE IF NOT EXISTS schema_migrations ("
    " name VARCHAR(100) NOT NULL PRIMARY KEY,"
    " checksum CHAR(64) NOT NULL,"
    " applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
)


def split_sql(src: str) -> list[str]:
    """SQL 파일 → 문장들. `--`·`/* */` 주석을 걷고 따옴표 밖의 `;` 로 자른다.

    ⚠️ 드라이버에 여러 문장을 한 번에 보내지 않는다(다중 문장 모드를 켜야 하고, 켜면 어느
       문장에서 실패했는지 흐려진다).
    """
    out, cur, i, quote = [], [], 0, None
    while i < len(src):
        c = src[i]
        if quote:
            cur.append(c)
            if c == "\\" and i + 1 < len(src):
                cur.append(src[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in ("'", '"', "`"):
            quote = c
            cur.append(c)
        elif src.startswith("--", i):
            nl = src.find("\n", i)
            i = len(src) if nl < 0 else nl
            continue
        elif src.startswith("/*", i):
            end = src.find("*/", i + 2)
            i = len(src) if end < 0 else end + 2
            continue
        elif c == ";":
            stmt = "".join(cur).strip()
            if stmt:
                out.append(stmt)
            cur = []
        else:
            cur.append(c)
        i += 1
    stmt = "".join(cur).strip()
    if stmt:
        out.append(stmt)
    return out


def migration_files(directory: Path = MIGRATIONS_DIR) -> list[Path]:
    """적용 대상 파일을 번호 순서로. 이름 규칙에 안 맞는 파일이 있으면 멈춘다(오타를 조용히 넘기지 않게)."""
    files = sorted(p for p in directory.glob("*.sql"))
    bad = [p.name for p in files if not _NAME.match(p.name)]
    if bad:
        raise SystemExit(f"마이그레이션 파일 이름이 규칙(NNNN_이름.sql)에 맞지 않는다: {bad}")
    return files


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def run(url: str, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """아직 안 한 것을 적용하고 적용한 이름들을 돌려준다."""
    files = migration_files(directory)
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT")
    done: list[str] = []
    try:
        async with engine.connect() as conn:
            await conn.exec_driver_sql(_LEDGER)
            rows = (await conn.exec_driver_sql("SELECT name, checksum FROM schema_migrations")).all()
            applied = {name: digest for name, digest in rows}
            for path in files:
                digest = checksum(path)
                if path.name in applied:
                    if applied[path.name] != digest:
                        logger.warning("이미 적용된 %s 가 그 뒤 바뀌었다 — 다시 적용하지 않는다", path.name)
                    continue
                logger.info("적용: %s", path.name)
                # ⚠️ `exec_driver_sql` 로 보낸다 — `text()` 는 `:이름` 을 바인드 자리로 읽어
                #    주석·문자열 속 콜론이 깨진다.
                # ⚠️ `%` 는 `%%` 로 보낸다 — aiomysql 은 인자가 없어도 문장을 `%` 서식으로 한 번
                #    돌려서 `LIKE '%…'` 같은 글자가 "not enough arguments" 로 죽는다(실측).
                for stmt in split_sql(path.read_text(encoding="utf-8")):
                    await conn.exec_driver_sql(stmt.replace("%", "%%"))
                await conn.exec_driver_sql(
                    "INSERT INTO schema_migrations (name, checksum) VALUES (%s, %s)", (path.name, digest))
                done.append(path.name)
    finally:
        await engine.dispose()
    return done


async def pending_names(url: str, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """적용 안 된 파일 이름. 읽기만 한다(앱 계정으로 부른다). 기록 테이블이 없으면 전부 안 된 것이다."""
    files = migration_files(directory)
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            try:
                applied = {r[0] for r in (await conn.exec_driver_sql("SELECT name FROM schema_migrations")).all()}
            except Exception:
                applied = set()
    finally:
        await engine.dispose()
    return [p.name for p in files if p.name not in applied]


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[migrate] %(message)s")
    url = os.environ.get("MIGRATE_DATABASE_URL", "").strip()
    if not url:
        app_url = os.environ.get("DATABASE_URL", "").strip()
        if not app_url:
            logger.info("MIGRATE_DATABASE_URL·DATABASE_URL 이 없다 — 건너뛴다")
            return 0
        try:
            pending = asyncio.run(pending_names(app_url))
        except SystemExit:
            raise
        except Exception:
            logger.exception("적용 여부를 확인하지 못했다 — 앱을 띄우지 않는다")
            return 1
        if pending:
            logger.error("적용 안 된 마이그레이션이 있는데 MIGRATE_DATABASE_URL 이 없다 — 앱을 띄우지 않는다: %s",
                         ", ".join(pending))
            return 1
        logger.info("MIGRATE_DATABASE_URL 이 없지만 적용할 것도 없다")
        return 0
    try:
        done = asyncio.run(run(url))
    except SystemExit:
        raise
    except Exception:
        logger.exception("실패 — 앱을 띄우지 않는다")
        return 1
    logger.info("완료 — 새로 적용 %d개%s", len(done), (": " + ", ".join(done)) if done else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
