"""AGY 실행기 및 공용 AI 파사드(`app/services/agy_runner.py`, `app/services/ai_runner.py`) 단위 테스트."""

import asyncio
import json

import pytest

from app.core.config import settings
from app.services import agy_runner, ai_runner, codex_runner


def test_agy_모델_목록_파싱과_강도_변형():
    raw = "\n".join([
        "Fetching available models...",
        "gemini-4-neon-high\tGemini 4 Neon (High)",
        "gemini-4-neon-xhigh\tGemini 4 Neon (XHigh)",
        "gemini-4-neon-medium\tGemini 4 Neon (Medium)",
        "gemini-4-neon-low\tGemini 4 Neon (Low)",
        "gemini-pro-orchestrator\tOrchestrator (Carbon)",
    ])
    parsed = agy_runner._parse_models(raw)
    assert [m["slug"] for m in parsed] == ["gemini-4-neon", "gemini-pro-orchestrator"]
    neon = parsed[0]
    assert neon["name"] == "Gemini 4 Neon"
    assert neon["efforts"] == ["low", "medium", "high", "xhigh"]
    assert neon["default"] == "medium"
    assert neon["variants"]["xhigh"] == "gemini-4-neon-xhigh"
    assert parsed[1]["efforts"] == []
    assert parsed[1]["default"] is None


def test_agy_모델_해석과_변형_선택(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "agy_home", str(tmp_path))
    tok = agy_runner.token_file()
    tok.parent.mkdir(parents=True, exist_ok=True)
    tok.write_text('{"token":{"access_token":"abc"}}', encoding="utf-8")
    agy_runner._models_cache_file().write_text(json.dumps({
        "fetched_at": "2026-11-21T23:00:00+09:00",
        "models": [
            {
                "slug": "gemini-4-neon",
                "name": "Gemini 4 Neon",
                "default": "medium",
                "efforts": ["low", "medium", "high", "xhigh"],
                "variants": {
                    "low": "gemini-4-neon-low",
                    "medium": "gemini-4-neon-medium",
                    "high": "gemini-4-neon-high",
                    "xhigh": "gemini-4-neon-xhigh",
                },
            },
            {
                "slug": "gemini-pro-orchestrator",
                "name": "Orchestrator",
                "default": None,
                "efforts": [],
                "variants": {},
            },
        ],
    }), encoding="utf-8")

    assert agy_runner.logged_in() is True
    assert agy_runner.resolve_model("neon") == "gemini-4-neon"
    assert agy_runner.resolve_model("gemini-4-neon-high") == "gemini-4-neon"
    assert agy_runner.resolve_effort("gemini-4-neon", "high") == "high"
    assert agy_runner.resolve_effort("gemini-4-neon", "ultra") is None
    assert agy_runner.cli_model_for("gemini-4-neon", "high") == ("gemini-4-neon-high", None)
    assert agy_runner.cli_model_for("gemini-4-neon", None) == ("gemini-4-neon-medium", None)
    assert agy_runner.cli_model_for("gemini-pro-orchestrator", None) == ("gemini-pro-orchestrator", None)


def test_agy_mcp_설정_생성후_정리(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "agy_home", str(tmp_path))
    path = agy_runner._write_mcp_config("http://127.0.0.1:8080/mcp", "secret-tok")
    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["mcpServers"]["blog"]["serverUrl"] == "http://127.0.0.1:8080/mcp"
    assert data["mcpServers"]["blog"]["headers"]["Authorization"] == "Bearer secret-tok"
    agy_runner._clear_mcp_config()
    assert not path.exists()


def test_agy와_codex가_실행_잠금을_공유한다(monkeypatch):
    running, peak = 0, 0

    async def fake_codex(*args):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.02)
        running -= 1
        return "codex"

    async def fake_agy(*args):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.02)
        running -= 1
        return "agy"

    monkeypatch.setattr(codex_runner, "_run", fake_codex)
    monkeypatch.setattr(agy_runner, "_run", fake_agy)
    monkeypatch.setattr(codex_runner, "_RUN_LOCK", asyncio.Lock())

    async def main():
        return await asyncio.gather(
            codex_runner.run("p1", None),
            agy_runner.run("p2", None),
        )

    assert asyncio.run(main()) == ["codex", "agy"]
    assert peak == 1


def test_ai_runner_프로바이더별_분기와_모델키(monkeypatch):
    calls = []

    async def fake_codex_run(prompt, model, images=None, mcp_url=None, mcp_token=None, write_tools=(), effort=None):
        calls.append(("codex", prompt, model, effort))
        return "from-codex"

    async def fake_agy_run(prompt, model, images=None, mcp_url=None, mcp_token=None, write_tools=(), effort=None):
        calls.append(("agy", prompt, model, effort))
        return "from-agy"

    monkeypatch.setattr(codex_runner, "resolve_model", lambda want: f"c:{want}" if want else None)
    monkeypatch.setattr(codex_runner, "resolve_effort", lambda m, e: e or None)
    monkeypatch.setattr(codex_runner, "run", fake_codex_run)
    monkeypatch.setattr(agy_runner, "resolve_model", lambda want: f"a:{want}" if want else None)
    monkeypatch.setattr(agy_runner, "resolve_effort", lambda m, e: e or None)
    monkeypatch.setattr(agy_runner, "run", fake_agy_run)

    cfg_codex = {"ai_provider": "codex", "ai_model": "sol", "ai_effort": "high", "agy_model": "neon", "agy_effort": "low"}
    cfg_agy = {**cfg_codex, "ai_provider": "agy"}

    assert asyncio.run(ai_runner.run(cfg_codex, "hello")) == "from-codex"
    assert asyncio.run(ai_runner.run(cfg_agy, "world")) == "from-agy"
    assert calls == [
        ("codex", "hello", "c:sol", "high"),
        ("agy", "world", "a:neon", "low"),
    ]


def test_agy_미로그인시_AgyError(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "agy_home", str(tmp_path))
    monkeypatch.setattr(codex_runner, "_RUN_LOCK", asyncio.Lock())
    with pytest.raises(ai_runner.AIError) as exc:
        asyncio.run(agy_runner.run("hi", None))
    assert "AGY 로그인" in str(exc.value)
