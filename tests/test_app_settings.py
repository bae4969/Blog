"""외부 연동 설정(`app/core/app_settings.py`) — 비밀 값은 빈 칸이면 건드리지 않고, 화면엔 끝 4자리만."""

import asyncio

from app.core import app_settings


class _FakeDB:
    def __init__(self, rows=()):
        self.rows, self.writes, self.committed = list(rows), [], False

    async def execute(self, stmt, params=None):
        if params is not None:
            self.writes.append(params)
        rows = self.rows

        class _R:
            def all(self_inner):
                return rows
        return _R()

    async def commit(self):
        self.committed = True


def test_불러오기는_기본값_위에_저장값():
    db = _FakeDB([("ai_model", "codex-x"), ("모르는키", "v")])
    cfg = asyncio.run(app_settings.load(db))
    assert cfg["ai_model"] == "codex-x"
    assert cfg["smtp_port"] == "465" and "모르는키" not in cfg


def test_비밀값이_비면_그대로_둔다():
    db = _FakeDB()
    asyncio.run(app_settings.save(db, {"smtp_password": "", "smtp_user": "u", "smtp_host": "h", "bogus": "x"}))
    keys = [w["k"] for w in db.writes]
    assert keys == ["smtp_user", "smtp_host"] and db.committed


def test_가리기():
    assert app_settings.masked("bae-agent:baeagt_abcd1234") == "…1234"
    assert app_settings.masked("") == ""


def test_모델은_일부만_쓰면_그중_최신():
    ids = ["auto", "codex-gpt-6.1-sol", "codex-gpt-6-sol", "codex-gpt-6-luna", "codex-gpt-5.6-terra"]
    assert app_settings.pick_model(ids, "sol") == "codex-gpt-6.1-sol"
    assert app_settings.pick_model(ids + ["codex-gpt-6.10-sol"], "sol") == "codex-gpt-6.10-sol"   # 6.10 > 6.1
    assert app_settings.pick_model(ids, "codex-gpt-6-sol") == "codex-gpt-6-sol"                 # 정확히 같으면 그것
    assert app_settings.pick_model(ids, "SOL") == "codex-gpt-6.1-sol"
    assert app_settings.pick_model(ids, "opus") is None


def test_모델_목록과_강도(tmp_path, monkeypatch):
    """codex 의 models_cache.json → 모델·강도. 지원하지 않는 강도는 None(= 모델 기본)."""
    import json
    from app.core.config import settings
    from app.services import codex_runner

    (tmp_path / "models_cache.json").write_text(json.dumps({"fetched_at": "t", "models": [
        {"slug": "gpt-6.1-sol", "display_name": "GPT-6.1-Sol", "default_reasoning_level": "low",
         "supported_reasoning_levels": [{"effort": "low"}, {"effort": "high"}, {"effort": "ultra"}]},
        {"slug": "gpt-5.5", "default_reasoning_level": "medium", "supported_reasoning_levels": [{"effort": "high"}]}]}))
    monkeypatch.setattr(settings, "codex_home", str(tmp_path))
    cat = codex_runner.catalog()
    assert [m["slug"] for m in cat["models"]] == ["gpt-6.1-sol", "gpt-5.5"]
    assert cat["models"][0]["efforts"] == ["low", "high", "ultra"]
    assert codex_runner.resolve_model("sol") == "gpt-6.1-sol"
    assert codex_runner.resolve_effort("gpt-6.1-sol", "ultra") == "ultra"
    assert codex_runner.resolve_effort("gpt-5.5", "ultra") is None      # 지원 안 함 → 모델 기본
    assert codex_runner.resolve_effort("gpt-6.1-sol", "") is None
    assert codex_runner.aliases() == [{"alias": "sol", "slug": "gpt-6.1-sol"}]   # gpt-5.5 는 계열 이름이 없다


def test_목록이_없으면_비어_있다(tmp_path, monkeypatch):
    from app.core.config import settings
    from app.services import codex_runner
    monkeypatch.setattr(settings, "codex_home", str(tmp_path))
    assert codex_runner.catalog() == {"fetched_at": None, "models": []}
    assert codex_runner.resolve_model("sol") is None
