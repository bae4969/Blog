"""DB 마이그레이션(`app/migrate.py`) — DB 없이 볼 수 있는 것.

⚠️ 가장 중요한 것은 `TestAdditiveOnly` 다. 배포가 실패하면 **이미지만 옛것으로 돌아가고 DB 는
   그대로**라, 마이그레이션이 지우거나 이름을 바꾸면 되돌린 옛 코드가 깨진다. 파일을 훑어 막는다.
"""

import re

import pytest

from app import migrate
from app.migrate import MIGRATIONS_DIR, migration_files, split_sql


class TestSplitSql:
    def test_세미콜론으로_나눈다(self):
        assert split_sql("CREATE TABLE a (x INT);\nUPDATE a SET x = 1;") == [
            "CREATE TABLE a (x INT)", "UPDATE a SET x = 1"]

    def test_주석은_걷는다(self):
        src = "-- 설명; 여기 세미콜론은 끊지 않는다\nSELECT 1; /* 블록; 주석 */ SELECT 2"
        assert split_sql(src) == ["SELECT 1", "SELECT 2"]

    def test_따옴표_안의_세미콜론은_끊지_않는다(self):
        assert split_sql("UPDATE t SET c = 'a;b' WHERE n = \"x;y\";") == [
            "UPDATE t SET c = 'a;b' WHERE n = \"x;y\""]

    def test_따옴표_안의_이스케이프(self):
        assert split_sql(r"SELECT 'it\'s; fine'; SELECT 2") == [r"SELECT 'it\'s; fine'", "SELECT 2"]

    def test_빈_문장은_버린다(self):
        assert split_sql(";;\n  ;") == []


class TestFiles:
    def test_번호_순서로_나온다(self, tmp_path):
        for name in ("0002_b.sql", "0001_a.sql", "0010_c.sql"):
            (tmp_path / name).write_text("SELECT 1;")
        assert [p.name for p in migration_files(tmp_path)] == ["0001_a.sql", "0002_b.sql", "0010_c.sql"]

    @pytest.mark.parametrize("bad", ["1_a.sql", "0003-a.sql", "0003_A.sql", "0003_한글.sql"])
    def test_이름이_틀리면_멈춘다(self, tmp_path, bad):
        (tmp_path / bad).write_text("SELECT 1;")
        with pytest.raises(SystemExit):
            migration_files(tmp_path)

    def test_실제_파일_이름이_규칙에_맞다(self):
        assert migration_files(MIGRATIONS_DIR), "마이그레이션 파일이 하나도 없다"

    def test_번호가_겹치지_않는다(self):
        nums = [p.name[:4] for p in migration_files(MIGRATIONS_DIR)]
        assert len(nums) == len(set(nums))


class TestAdditiveOnly:
    """⚠️ 더하기만 — 지우기·이름 바꾸기·좁히기는 되돌린 옛 코드를 깨뜨린다."""

    FORBIDDEN = re.compile(r"\b(DROP|RENAME|TRUNCATE|DELETE|MODIFY|CHANGE\s+COLUMN)\b", re.I)

    @pytest.mark.parametrize("path", migration_files(MIGRATIONS_DIR), ids=lambda p: p.name)
    def test_지우거나_바꾸지_않는다(self, path):
        for stmt in split_sql(path.read_text(encoding="utf-8")):
            assert not self.FORBIDDEN.search(stmt), f"{path.name}: 더하기만 해야 한다 → {stmt[:80]}"

    @pytest.mark.parametrize("path", migration_files(MIGRATIONS_DIR), ids=lambda p: p.name)
    def test_다시_돌려도_안전하다(self, path):
        """중간에 죽으면 처음부터 다시 돈다 — 만들기·더하기는 `IF NOT EXISTS` 여야 한다."""
        for stmt in split_sql(path.read_text(encoding="utf-8")):
            s = " ".join(stmt.split()).upper()
            if s.startswith("CREATE TABLE") or s.startswith("CREATE INDEX"):
                assert "IF NOT EXISTS" in s, f"{path.name}: {stmt[:60]}"
            if s.startswith("ALTER TABLE") and " ADD " in s:
                assert "IF NOT EXISTS" in s, f"{path.name}: {stmt[:60]}"


class TestMain:
    def test_계정이_둘_다_없으면_건너뛴다(self, monkeypatch):
        """CI·로컬 실행에는 DB 가 없다 — 앱이 뜨는 것을 막지 않는다."""
        monkeypatch.delenv("MIGRATE_DATABASE_URL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert migrate.main() == 0

    def test_마이그레이션_계정이_빠졌는데_할_게_있으면_멈춘다(self, monkeypatch):
        """⚠️ 운영 `.env.api` 에 줄을 빠뜨리고 배포하면 옛 스키마에서 500 이 난다 — 대신 뜨지 않는다."""
        monkeypatch.delenv("MIGRATE_DATABASE_URL", raising=False)
        monkeypatch.setenv("DATABASE_URL", "mysql+aiomysql://x:y@nowhere/db")

        async def fake(url, directory=MIGRATIONS_DIR):
            return ["0003_something.sql"]
        monkeypatch.setattr(migrate, "pending_names", fake)
        assert migrate.main() == 1

    def test_마이그레이션_계정이_없어도_할_게_없으면_뜬다(self, monkeypatch):
        monkeypatch.delenv("MIGRATE_DATABASE_URL", raising=False)
        monkeypatch.setenv("DATABASE_URL", "mysql+aiomysql://x:y@nowhere/db")

        async def fake(url, directory=MIGRATIONS_DIR):
            return []
        monkeypatch.setattr(migrate, "pending_names", fake)
        assert migrate.main() == 0
