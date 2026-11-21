"""AI 실행기 통합 파사드 — 설정(`ai_provider`)에 따라 Codex 또는 AGY CLI 를 부른다.

상담 시트([assistant_v1](../api/assistant_v1.py)), 투자 계획 매일 점검([plan_v1](../api/plan_v1.py)),
관리자 응답 시험([admin](../ui/admin.py))이 이 모듈 하나를 통해 현재 선택된 프로바이더를 사용한다.
"""

from app.core import app_settings
from app.services import agy_runner, codex_runner
from app.services.codex_runner import CodexError as AIError

PROVIDER_LABELS = {"codex": "Codex", "agy": "AGY"}


def provider_of(cfg: dict) -> str:
    p = (cfg.get("ai_provider") or "codex").strip().lower()
    return p if p in app_settings.PROVIDERS else "codex"


def runner_of(provider: str):
    return agy_runner if provider == "agy" else codex_runner


def model_keys(provider: str) -> tuple[str, str]:
    """프로바이더가 쓰는 app_setting 키 쌍 `(모델 키, 강도 키)`."""
    return ("agy_model", "agy_effort") if provider == "agy" else ("ai_model", "ai_effort")


def resolve_for(cfg: dict, provider: str | None = None) -> tuple[str, str | None, str | None]:
    """`(provider, resolved_model, resolved_effort)`."""
    prov = provider or provider_of(cfg)
    runner = runner_of(prov)
    m_key, e_key = model_keys(prov)
    model = runner.resolve_model(cfg.get(m_key, ""))
    effort = runner.resolve_effort(model, cfg.get(e_key, ""))
    return prov, model, effort


async def run(cfg: dict, prompt: str, images: list[str] | None = None,
              mcp_url: str | None = None, mcp_token: str | None = None, write_tools: tuple = (),
              provider: str | None = None) -> str:
    """설정된(또는 지정한) 프로바이더로 AI 를 실행하고 답 본문을 돌려준다. 실패 시 AIError."""
    prov, model, effort = resolve_for(cfg, provider)
    runner = runner_of(prov)
    return await runner.run(prompt, model, images, mcp_url, mcp_token, write_tools, effort=effort)


__all__ = ["AIError", "PROVIDER_LABELS", "provider_of", "runner_of", "model_keys", "resolve_for", "run"]
