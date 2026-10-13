"""codex CLI 실행 — 투자 계획 상담이 블로그 컨테이너 안에서 `codex exec` 를 부른다(2026-10-10). **DB 를 모른다.**

전에는 32.ai_stream 의 API 를 거쳤다. 그런데 거기서는 AI 가 블로그 데이터를 조회할 길이 없어(stream 은 공용이라
MCP 를 붙일 수 없다) 사용자 결정으로 블로그가 직접 codex 에 로그인하고 MCP(`/mcp`)를 붙여 부르게 했다.

    codex exec --json --ephemeral --skip-git-repo-check -s read-only --disable shell_tool -m <모델>
               -c mcp_servers.blog.url="…/mcp" -c mcp_servers.blog.bearer_token_env_var="BLOG_MCP_TOKEN" [-i 이미지…]

- 셸은 끄고 읽기 전용 샌드박스 — AI 가 할 수 있는 일은 대화·웹 검색·블로그 MCP 조회뿐이다.
- 프롬프트는 stdin 으로(인자 길이 제한), 출력은 JSON 줄을 **한 줄씩** 읽는다(32.ai_stream 의 교훈 — 한 줄이 아주 길 수 있다).
- 로그인 정보는 `CODEX_HOME`(설정 `codex_home`)의 `auth.json`. 로그인은 관리자 › 외부 연동의 기기 코드 흐름으로 한다.

⚠️ 32.ai_stream 에서 `codex app-server` 를 SIGKILL 로 죽였다가 NAS 커널 패닉이 두 번 났다(ZFS 버그). 여기서는
   `exec` 만 쓰고, 시간이 넘으면 SIGTERM 으로 끝내고 기다린다.
"""

import asyncio
import base64
import json
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path

from app.core import app_settings
from app.core.config import settings

logger = logging.getLogger(__name__)

TIMEOUT = 600


class CodexError(RuntimeError):
    """codex 가 답을 못 냈다. 메시지는 화면에 그대로 보여도 되는 말로 쓴다."""


def home() -> Path:
    return Path(settings.codex_home or Path.home() / ".codex")


def logged_in() -> bool:
    auth = home() / "auth.json"
    return auth.is_file() and auth.stat().st_size > 0


def catalog() -> dict:
    """codex 가 남긴 모델 목록(`models_cache.json`) — {fetched_at, models: [{slug, name, default, efforts}]}.

    codex 가 실행할 때 스스로 갱신한다(로그인 뒤 첫 실행 전에는 비어 있다). 관리자 화면이 이걸 보여 준다.
    """
    try:
        data = json.loads((home() / "models_cache.json").read_text())
    except (OSError, ValueError):
        return {"fetched_at": None, "models": []}
    return {"fetched_at": data.get("fetched_at"), "models": [
        {"slug": m["slug"], "name": m.get("display_name") or m["slug"], "default": m.get("default_reasoning_level"),
         "efforts": [e["effort"] for e in m.get("supported_reasoning_levels", []) if e.get("effort")]}
        for m in data.get("models", []) if m.get("slug")]}


def models() -> list[str]:
    return [m["slug"] for m in catalog()["models"]]


def resolve_model(want: str) -> str | None:
    """설정의 모델 이름(일부여도 된다 — "sol") → codex 모델. 목록이 없거나 맞는 게 없으면 None(= codex 기본 모델)."""
    return app_settings.pick_model(models(), want) if want else None


def aliases() -> list[dict]:
    """계열 이름 → 지금 그 계열의 최신 모델. `gpt-6.1-sol` 이면 계열은 `sol`. 버전 숫자가 없는 모델은 계열이 없다."""
    slugs, out = models(), {}
    for slug in slugs:
        m = re.fullmatch(r".*\d(?:\.\d+)*-([a-z]+)", slug)
        if m and m.group(1) not in out:
            out[m.group(1)] = app_settings.pick_model(slugs, m.group(1))
    return [{"alias": a, "slug": s} for a, s in out.items()]


def resolve_effort(model: str | None, want: str) -> str | None:
    """설정의 추론 강도 → 그 모델이 지원하면 그대로, 아니면 None(= 모델 기본 강도)."""
    if not (model and want):
        return None
    hit = next((m for m in catalog()["models"] if m["slug"] == model), None)
    return want if hit and want in hit["efforts"] else None


def _env(extra: dict | None = None) -> dict:
    env = {**os.environ, "CODEX_HOME": str(home())}
    env.update(extra or {})
    return env


def _save_images(folder: str, images: list[str]) -> list[str]:
    paths = []
    for i, url in enumerate(images):
        m = re.match(r"data:image/(\w+);base64,(.*)", url, re.S)
        if not m:
            continue
        path = os.path.join(folder, f"image{i}.{m.group(1).replace('jpeg', 'jpg')}")
        with open(path, "wb") as f:
            f.write(base64.b64decode(m.group(2)))
        paths.append(path)
    return paths


async def run(prompt: str, model: str | None, images: list[str] | None = None,
              mcp_url: str | None = None, mcp_token: str | None = None, write_tools: tuple = (),
              effort: str | None = None) -> str:
    """답 본문(에이전트 메시지들을 이은 것). 실패하면 CodexError."""
    if not logged_in():
        raise CodexError("Codex 로그인이 필요합니다 — 관리자 › 외부 연동에서 로그인해 주세요")
    folder = tempfile.mkdtemp(prefix="plan-codex-")   # 빈 작업 폴더 — 읽을 파일이 없다
    try:
        cmd = [settings.codex_bin, "exec", "--json", "--ephemeral", "--skip-git-repo-check",
               "-s", "read-only", "--disable", "shell_tool"] + (["-m", model] if model else [])
        if effort:
            cmd += ["-c", f'model_reasoning_effort="{effort}"']
        extra = {}
        if mcp_url and mcp_token:
            # 승인할 사람이 없다 — 읽기 전용 표시(readOnlyHint)가 붙은 도구만 바로 부르게 한다(plan_mcp 의 도구는 전부 그렇다).
            cmd += ["-c", f'mcp_servers.blog.url="{mcp_url}"',
                    "-c", 'mcp_servers.blog.bearer_token_env_var="BLOG_MCP_TOKEN"',
                    "-c", 'mcp_servers.blog.default_tools_approval_mode="writes"']
            # 쓰기 도구는 도구별로 자동 승인 — 서버가 검증·버전 저장·되돌리기를 맡는다(plan_mcp.WRITE_TOOLS).
            for tool in write_tools:
                cmd += ["-c", f'mcp_servers.blog.tools.{tool}.approval_mode="approve"']
            extra["BLOG_MCP_TOKEN"] = mcp_token
        for path in _save_images(folder, images or []):
            cmd += ["-i", path]

        with open(os.path.join(folder, "stderr.log"), "w+b") as err:
            # ⚠️ stderr 를 파이프로 받으면 stdout 을 읽는 동안 가득 차 서로 막힐 수 있다 — 파일로 돌린다.
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=err,
                cwd=folder, env=_env(extra), limit=64 * 1024 * 1024)
            proc.stdin.write(prompt.encode())
            await proc.stdin.drain()
            proc.stdin.close()

            texts, failure, tools = [], None, []

            async def read():
                nonlocal failure
                while line := await proc.stdout.readline():
                    try:
                        o = json.loads(line)
                    except ValueError:
                        continue
                    kind, item = o.get("type"), o.get("item") or {}
                    if kind == "item.completed" and item.get("type") == "agent_message" and item.get("text"):
                        texts.append(item["text"])
                    elif kind == "item.completed" and item.get("type") == "mcp_tool_call":
                        tools.append(f"{item.get('tool')}:{item.get('status')}")
                    elif kind == "error":
                        failure = o.get("message") or failure
                    elif kind == "turn.failed":
                        failure = (o.get("error") or {}).get("message") or failure

            try:
                await asyncio.wait_for(read(), TIMEOUT)
            except TimeoutError:
                proc.terminate()
                await proc.wait()
                raise CodexError(f"AI 가 {TIMEOUT}초 안에 답하지 않았습니다")
            await proc.wait()
            if tools:
                logger.info("codex MCP 호출: %s", ", ".join(tools))
            if not texts:
                err.seek(0)
                tail = err.read()[-500:].decode(errors="replace").strip()
                logger.warning("codex 실패(exit %s): %s | %s", proc.returncode, failure, tail)
                raise CodexError(f"AI 가 답하지 못했습니다: {(failure or tail or '원인 불명')[:200]}")
        return "\n\n".join(texts)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


# ---------------------------------------------------------------------------
# 로그인 — 관리자 › 외부 연동. `codex login --device-auth` 를 뒤에서 돌리고 화면엔 링크·코드만 보인다.
# ---------------------------------------------------------------------------
#
# ⚠️ 32.ai_stream 처럼 app-server(JSON-RPC)로 하지 않는다 — app-server 를 강제 종료했다가 커널 패닉이 났던 길이다.
#    CLI 로그인은 코드를 찍고 사용자가 브라우저에서 넣을 때까지(최대 15분) 기다리다 스스로 끝난다.

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_login: dict = {"proc": None, "url": None, "code": None, "error": None}


async def _cli(*args: str, timeout: int = 20) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        settings.codex_bin, *args, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=_env())
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.terminate()
        await proc.wait()
        return -1, "시간 초과"
    return proc.returncode, _ANSI.sub("", out.decode(errors="replace")).strip()


async def account() -> str:
    """`codex login status` 의 한 줄(예: "Logged in using ChatGPT"). 실행 파일이 없으면 그렇게 말한다."""
    try:
        code, out = await _cli("login", "status")
    except FileNotFoundError:
        return "codex 가 설치되어 있지 않습니다"
    return out.splitlines()[-1] if out else f"알 수 없음(exit {code})"


def login_state() -> dict:
    proc = _login["proc"]
    return {"pending": proc is not None and proc.returncode is None,
            "url": _login["url"], "code": _login["code"], "error": _login["error"]}


async def start_login() -> dict:
    """이미 진행 중이면 그대로 둔다. 링크·코드가 찍힐 때까지(최대 20초) 기다렸다 돌려준다."""
    if login_state()["pending"]:
        return login_state()
    _login.update(url=None, code=None, error=None)
    proc = await asyncio.create_subprocess_exec(
        settings.codex_bin, "login", "--device-auth", stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=_env())
    _login["proc"] = proc
    got = asyncio.Event()

    async def follow():
        lines = []
        while line := await proc.stdout.readline():
            text = _ANSI.sub("", line.decode(errors="replace")).strip()
            lines.append(text)
            if m := re.search(r"https://\S+/device\S*", text):
                _login["url"] = m.group()
            if m := re.fullmatch(r"[A-Z0-9]{4}-[A-Z0-9]{4,6}", text):
                _login["code"] = m.group()
            if _login["url"] and _login["code"]:
                got.set()
        await proc.wait()
        if proc.returncode != 0 and not logged_in():
            _login["error"] = (lines[-1] if lines else f"exit {proc.returncode}")[:200]
        got.set()

    asyncio.create_task(follow())
    try:
        await asyncio.wait_for(got.wait(), 20)
    except TimeoutError:
        pass
    return login_state()


async def cancel_login() -> None:
    proc = _login["proc"]
    if proc is not None and proc.returncode is None:
        proc.terminate()
        await proc.wait()
    _login.update(proc=None, url=None, code=None, error=None)


async def logout() -> str:
    _, out = await _cli("logout")
    return out
