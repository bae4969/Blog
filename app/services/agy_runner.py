"""AGY CLI 실행 및 로그인 — 투자 계획 상담·매일 점검이 블로그 컨테이너 안에서 `agy` 를 부른다. **DB 를 모른다.**

로그인 흐름은 `32.ai_stream` 의 검증된 PTY 방식을 따른다:
- `agy` 는 별도 로그인 명령이 없어 미인증 상태에서 `agy -p=/usage` 를 가상 터미널(PTY)로 띄우면
  Google OAuth 주소를 출력하고 60초 동안 일회용 코드를 기다린다.
- 사용자가 코드를 제출하면 PTY 로 전달해 토큰(`$AGY_HOME/.gemini/antigravity-cli/antigravity-oauth-token`)을 저장한다.

실행 흐름:
- `codex_runner._RUN_LOCK` 을 공유해 동시에 하나의 AI 프로세스만 띄운다(테스트 컨테이너 512M 한도).
- 블로그 MCP(`/mcp`)는 실행 직전 `$AGY_HOME/.gemini/config/mcp_config.json` 에 일회용 Bearer 토큰으로 기록하고
  실행이 끝나면(`finally`) 지운다.
- 종료 시 SIGKILL 대신 SIGTERM + `STOP_WAIT` 대기 원칙을 지킨다.
"""

import asyncio
import base64
import fcntl
import json
import logging
import os
import re
import select
import shutil
import struct
import subprocess
import tempfile
import termios
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core import app_settings
from app.core.config import settings
from app.services import codex_runner
from app.services.codex_runner import CodexError

logger = logging.getLogger(__name__)

TIMEOUT = codex_runner.TIMEOUT
STOP_WAIT = codex_runner.STOP_WAIT
_KST = timezone(timedelta(hours=9))
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)|\x1b[@-_]")
_EFFORT_ORDER = ("low", "medium", "high", "xhigh", "max")
_EFFORT_SUFFIX = re.compile(r"^(.+)-(low|medium|high|xhigh|max)$")
_AGY_GUARD = (
    "[실행 규칙] 셸 명령·파일 수정·워크스페이스 탐색 도구는 쓰지 마라. "
    "블로그 MCP 도구(`blog`)와 첨부 이미지 읽기만 사용하라."
)


class AgyError(CodexError):
    """AGY 가 답을 못 냈다. CodexError 를 상속해 기존 호출부와 오류 계약을 공유한다."""


def bin_path() -> str:
    """실행할 agy 바이너리 경로. AGY_BIN 미지정 시 codex_bin 옆의 agy 를 먼저 찾는다."""
    if settings.agy_bin:
        return settings.agy_bin
    if "/" in settings.codex_bin:
        sibling = Path(settings.codex_bin).parent / "agy"
        if sibling.is_file():
            return str(sibling)
    return "agy"


def home() -> Path:
    """AGY 전용 HOME 디렉터리(로그인 토큰·모델 캐시·임시 MCP 설정 보관).

    compose 볼륨 변경 없이 운영/테스트에서 로그인을 유지하려고 기본은 `codex_home/agy-home` 을 쓴다.
    """
    if settings.agy_home:
        return Path(settings.agy_home)
    if settings.codex_home:
        return Path(settings.codex_home) / "agy-home"
    return Path.home() / ".agy-blog"


def token_file() -> Path:
    return home() / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"


def _models_cache_file() -> Path:
    return home() / "agy_models_cache.json"


def _mcp_config_file() -> Path:
    return home() / ".gemini" / "config" / "mcp_config.json"


def logged_in() -> bool:
    p = token_file()
    return p.is_file() and p.stat().st_size > 0


def _env(extra: dict | None = None) -> dict:
    h = home()
    h.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "HOME": str(h)}
    env.update(extra or {})
    return env


def _parse_models(raw: str) -> list[dict]:
    """`agy models` 출력(탭 구분 `id\\tlabel`) → 강도 변형을 하나로 묶은 모델 목록."""
    groups: dict[str, dict] = {}
    for line in raw.splitlines():
        if "\t" not in line:
            continue
        mid, label = (x.strip() for x in line.split("\t", 1))
        if not mid:
            continue
        m = _EFFORT_SUFFIX.match(mid)
        base, effort = (m.group(1), m.group(2)) if m else (mid, None)
        group = groups.setdefault(base, {
            "slug": base,
            "name": re.sub(r"\s*\((?:low|medium|high|xhigh|max)\)\s*$", "", label, flags=re.I) or base,
            "default": None,
            "efforts": [],
            "variants": {},
        })
        if effort:
            group["variants"][effort] = mid
    for group in groups.values():
        if group["variants"]:
            group["efforts"] = [e for e in _EFFORT_ORDER if e in group["variants"]]
            group["default"] = next(
                (e for e in ("medium", "high", "low", "xhigh", "max") if e in group["variants"]),
                group["efforts"][0],
            )
    return list(groups.values())


def catalog() -> dict:
    """저장된 AGY 모델 목록(`agy_models_cache.json`) — {fetched_at, models: [{slug, name, default, efforts, variants}]}."""
    if not logged_in():
        return {"fetched_at": None, "models": []}
    try:
        data = json.loads(_models_cache_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"fetched_at": None, "models": []}
    models_out = []
    for m in data.get("models", []):
        if isinstance(m, dict) and m.get("slug"):
            models_out.append({
                "slug": m["slug"],
                "name": m.get("name") or m["slug"],
                "default": m.get("default"),
                "efforts": list(m.get("efforts") or []),
                "variants": dict(m.get("variants") or {}),
            })
    return {"fetched_at": data.get("fetched_at"), "models": models_out}


def models() -> list[str]:
    return [m["slug"] for m in catalog()["models"]]


def aliases() -> list[dict]:
    """AGY 는 모델 슬러그 자체가 계열을 포함하므로 별도 계열 별칭을 두지 않는다."""
    return []


def resolve_model(want: str) -> str | None:
    """설정의 모델 이름(일부 가능) → AGY 기본 모델 slug. 변형 이름(`...-high`)도 기본 slug 로 풀어준다."""
    want = (want or "").strip()
    if not want:
        return None
    cat = catalog()["models"]
    slugs = [m["slug"] for m in cat]
    hit = app_settings.pick_model(slugs, want)
    if hit:
        return hit
    # 사용자가 변형 ID(`gemini-4-neon-high`)를 그대로 넣은 경우 매칭
    for m in cat:
        if want in m["variants"].values():
            return m["slug"]
    return None


def resolve_effort(model: str | None, want: str) -> str | None:
    if not (model and want):
        return None
    hit = next((m for m in catalog()["models"] if m["slug"] == model), None)
    return want if hit and want in hit["efforts"] else None


def cli_model_for(model: str | None, effort: str | None) -> tuple[str | None, str | None]:
    """(agy --model 인자, agy --effort 인자). 강도 변형 모델이 있으면 변형 ID 를 쓰고 --effort 는 생략한다."""
    if not model:
        return None, effort
    hit = next((m for m in catalog()["models"] if m["slug"] == model), None)
    if not hit:
        return model, effort
    variants = hit.get("variants") or {}
    if variants:
        chosen = effort if effort in variants else hit.get("default")
        if chosen and chosen in variants:
            return variants[chosen], None
    return model, effort


async def _cli(*args: str, timeout: int = 20) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        bin_path(), *args, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=_env())
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        await codex_runner._stop(proc)
        return -1, "시간 초과"
    return proc.returncode or 0, _ANSI.sub("", out.decode(errors="replace")).strip()


async def version() -> str:
    try:
        code, out = await _cli("--version", timeout=5)
    except OSError:
        return "설치되지 않음"
    return out.splitlines()[-1] if code == 0 and out else "확인 실패"


async def refresh_catalog() -> dict:
    """`agy models` 를 실행해 모델 목록 캐시를 갱신한다."""
    if not logged_in():
        return {"fetched_at": None, "models": []}
    try:
        code, out = await _cli("models", timeout=30)
    except OSError as e:
        logger.warning("agy models 실행 실패: %s", e)
        return catalog()
    if code != 0:
        logger.warning("agy models 실패(exit %s): %s", code, out[-200:])
        return catalog()
    parsed = _parse_models(out)
    if not parsed:
        return catalog()
    payload = {"fetched_at": datetime.now(_KST).isoformat(timespec="seconds"), "models": parsed}
    target = _models_cache_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)
    return payload


_email_cache: dict[str, str | None] = {"token": None, "email": None}


def _fetch_email_sync() -> str | None:
    try:
        data = json.loads(token_file().read_text(encoding="utf-8"))
        token = (data.get("token") or {}).get("access_token")
    except (OSError, ValueError, AttributeError):
        return None
    if not token:
        return None
    if token == _email_cache["token"]:
        return _email_cache["email"]
    try:
        req = urllib.request.Request(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            email = json.loads(resp.read().decode()).get("email")
    except Exception:  # noqa: BLE001 — 네트워크 실패 시 화면을 막지 않는다
        return _email_cache["email"]
    _email_cache.update(token=token, email=email)
    return email


async def account() -> str:
    if not shutil.which(bin_path()) and not Path(bin_path()).is_file():
        return "agy 가 설치되어 있지 않습니다"
    if not logged_in():
        return "로그인 필요"
    email = await asyncio.to_thread(_fetch_email_sync)
    return f"Google ({email})" if email else "Google 로그인됨"


# ---------------------------------------------------------------------------
# 실행 — codex_runner._RUN_LOCK 공유, MCP 임시 설정, stream-json 파싱
# ---------------------------------------------------------------------------

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


def _write_mcp_config(mcp_url: str, mcp_token: str) -> Path:
    path = _mcp_config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "mcpServers": {
            "blog": {
                "disabled": False,
                "headers": {"Authorization": f"Bearer {mcp_token}"},
                "serverUrl": mcp_url,
            }
        }
    }
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path


def _clear_mcp_config() -> None:
    try:
        _mcp_config_file().unlink()
    except FileNotFoundError:
        pass


async def run(prompt: str, model: str | None, images: list[str] | None = None,
              mcp_url: str | None = None, mcp_token: str | None = None, write_tools: tuple = (),
              effort: str | None = None) -> str:
    """답 본문. 실패하면 AgyError(CodexError). codex_runner._RUN_LOCK 을 공유해 한 번에 하나만 돈다."""
    try:
        await asyncio.wait_for(codex_runner._RUN_LOCK.acquire(), codex_runner.LOCK_WAIT)
    except TimeoutError:
        raise AgyError("앞의 AI 작업이 끝나지 않았습니다 — 잠시 뒤 다시 해 주세요") from None
    try:
        return await _run(prompt, model, images, mcp_url, mcp_token, write_tools, effort)
    finally:
        codex_runner._RUN_LOCK.release()


async def _run(prompt: str, model: str | None, images: list[str] | None,
               mcp_url: str | None, mcp_token: str | None, write_tools: tuple,
               effort: str | None) -> str:
    del write_tools  # 블로그 MCP 서버(`/mcp`)가 허용된 쓰기 도구만 `tools/list`·`tools/call` 로 노출·집행한다.
    if not logged_in():
        raise AgyError("AGY 로그인이 필요합니다 — 관리자 › 외부 연동에서 로그인해 주세요")

    folder = tempfile.mkdtemp(prefix="plan-agy-")
    mcp_written = False
    try:
        if mcp_url and mcp_token:
            _write_mcp_config(mcp_url, mcp_token)
            mcp_written = True
        else:
            _clear_mcp_config()

        cli_model, cli_effort = cli_model_for(model, effort)
        cmd = [
            bin_path(), "-p=",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--sandbox",
            "--dangerously-skip-permissions",
            "--disable-slash-commands",
            "--print-timeout", f"{TIMEOUT}s",
        ]
        if cli_model:
            cmd += ["--model", cli_model]
        if cli_effort:
            cmd += ["--effort", cli_effort]

        img_paths = _save_images(folder, images or [])
        body = f"{_AGY_GUARD}\n\n{prompt}"
        if img_paths:
            cmd += ["--add-dir", folder]
            files = "\n".join(f"- {p}" for p in img_paths)
            body = (
                f"{_AGY_GUARD}\n\n"
                "[첨부 이미지] 아래 파일을 열어서 보고 대화에 답하라. 이 파일을 여는 것만 허용한다. "
                f"답에는 파일 이름·경로·링크를 쓰지 마라.\n{files}\n\n{prompt}"
            )
        turn = json.dumps({"event": "user", "message": {"content": body}}, ensure_ascii=False) + "\n"

        with open(os.path.join(folder, "stderr.log"), "w+b") as err:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=err,
                    cwd=folder, env=_env(), limit=64 * 1024 * 1024)
            except FileNotFoundError:
                raise AgyError("agy 가 설치되어 있지 않습니다") from None

            proc.stdin.write(turn.encode())
            await proc.stdin.drain()
            proc.stdin.close()

            deltas: list[str] = []
            final_text: str | None = None
            failure: str | None = None

            async def read():
                nonlocal final_text, failure
                while line := await proc.stdout.readline():
                    try:
                        o = json.loads(line)
                    except ValueError:
                        continue
                    ev = o.get("event")
                    if ev == "step_update":
                        step = o.get("step_update") or {}
                        if step.get("step_type") == "agent_response" and step.get("text_delta"):
                            deltas.append(step["text_delta"])
                    elif ev == "result":
                        r = o.get("result") or {}
                        if r.get("status") == "SUCCESS":
                            final_text = r.get("response") or final_text
                        else:
                            failure = str(r.get("error") or r.get("status") or "오류")

            try:
                await asyncio.wait_for(read(), TIMEOUT)
                await proc.wait()
            except TimeoutError:
                raise AgyError(f"AI 가 {TIMEOUT}초 안에 답하지 않았습니다") from None
            finally:
                await codex_runner._stop(proc)

            out = "".join(deltas).strip() or (final_text or "").strip()
            if failure or not out:
                err.seek(0)
                tail = err.read()[-500:].decode(errors="replace").strip()
                logger.warning("agy 실패(exit %s): %s | %s", proc.returncode, failure, tail)
                raise AgyError(f"AI 가 답하지 못했습니다: {(failure or tail or '원인 불명')[:200]}")
            return out
    finally:
        if mcp_written:
            _clear_mcp_config()
        shutil.rmtree(folder, ignore_errors=True)


# ---------------------------------------------------------------------------
# 로그인 — 관리자 › 외부 연동. PTY 로 `agy -p=/usage` 를 띄워 Google OAuth 주소를 받고 코드를 넣는다.
# ---------------------------------------------------------------------------

_login_lock = threading.Lock()
_login: dict = {
    "proc": None,
    "master": None,
    "url": None,
    "expires": None,
    "error": None,
    "message": None,
    "output": "",
    "done_event": None,
}


def _close_login_handles() -> None:
    master = _login.get("master")
    if master is not None:
        try:
            os.close(master)
        except OSError:
            pass
        _login["master"] = None


def login_state() -> dict:
    with _login_lock:
        proc = _login["proc"]
        pending = proc is not None and proc.poll() is None
        expires = _login["expires"]
        remaining = max(0, int(expires - time.time())) if pending and expires else None
        return {
            "pending": pending,
            "url": _login["url"] if pending else None,
            "remaining": remaining,
            "message": _login["message"] if pending else None,
            "error": _login["error"],
            "needs_code": pending and bool(_login["url"]),
        }


def _pty_reader(proc: subprocess.Popen, master: int, url_ready: threading.Event, done_event: threading.Event) -> None:
    raw = b""
    try:
        while True:
            try:
                ready, _, _ = select.select([master], [], [], 0.5)
                chunk = os.read(master, 65536) if ready else None
            except (OSError, ValueError):
                chunk = b""
            if chunk:
                raw += chunk
                text = _ANSI.sub("", raw.decode(errors="replace")).replace("\r", "")
                with _login_lock:
                    _login["output"] = text
                    if not _login["url"]:
                        m = re.search(r"https://accounts\.google\.com/\S+", text)
                        if m:
                            _login["url"] = m.group(0)
                            _login["expires"] = time.time() + 60
                            _login["message"] = "60초 안에 주소를 열어 Google 로그인 후 나온 코드를 붙여넣어 주세요."
                            url_ready.set()
            elif chunk == b"" or proc.poll() is not None:
                break
            with _login_lock:
                exp = _login["expires"]
            if exp and time.time() > exp + 3:
                try:
                    proc.terminate()
                except OSError:
                    pass
                with _login_lock:
                    _login["error"] = "60초가 지나 로그인이 만료되었습니다 — 다시 시작해 주세요"
                break
        try:
            code = proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.terminate()
            code = proc.poll()
        with _login_lock:
            if _login["proc"] is proc:
                if code == 0 and logged_in():
                    _login["error"] = None
                    _login["message"] = None
                elif not _login["error"]:
                    lines = [x.strip() for x in _login["output"].splitlines() if x.strip()]
                    tail = " / ".join(lines[-2:])[-200:] if lines else f"exit {code}"
                    _login["error"] = tail
    finally:
        with _login_lock:
            if _login["proc"] is proc:
                _close_login_handles()
                _login["proc"] = None
        url_ready.set()
        done_event.set()


async def start_login() -> dict:
    """미인증 agy PTY 로그인 시작. Google OAuth 주소가 나올 때까지(최대 20초) 기다린다."""
    st = login_state()
    if st["pending"] and st["url"] and (st["remaining"] or 0) > 5:
        return st
    await cancel_login()

    url_ready = threading.Event()
    done_event = threading.Event()
    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 4000, 0, 0))
    attrs = termios.tcgetattr(slave)
    attrs[3] &= ~(termios.ECHO | termios.ECHONL)
    termios.tcsetattr(slave, termios.TCSANOW, attrs)
    env = _env({"TERM": "xterm-256color"})
    folder = tempfile.mkdtemp(prefix="agy-login-")
    try:
        proc = subprocess.Popen(
            [bin_path(), "-p=/usage"], cwd=folder, env=env,
            stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
        )
    except OSError as e:
        os.close(master)
        os.close(slave)
        shutil.rmtree(folder, ignore_errors=True)
        with _login_lock:
            _login.update(proc=None, master=None, url=None, expires=None, message=None,
                          error=f"agy 실행 실패: {e}")
        return login_state()
    finally:
        try:
            os.close(slave)
        except OSError:
            pass

    with _login_lock:
        _login.update(proc=proc, master=master, url=None, expires=None, error=None,
                      message="로그인 주소를 준비하는 중…", output="", done_event=done_event)

    def _run_reader():
        try:
            _pty_reader(proc, master, url_ready, done_event)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    threading.Thread(target=_run_reader, daemon=True).start()
    await asyncio.to_thread(url_ready.wait, 20.0)
    return login_state()


async def submit_code(code: str) -> tuple[bool, str]:
    """사용자가 붙여넣은 Google OAuth 코드를 PTY 에 전달하고 로그인 완료를 기다린다."""
    code = (code or "").strip()
    if not code:
        return False, "인증 코드를 입력해 주세요"
    with _login_lock:
        proc = _login["proc"]
        master = _login["master"]
        done_event = _login["done_event"]
        if proc is None or proc.poll() is not None or master is None:
            return False, "진행 중인 AGY 로그인이 없습니다 — 다시 로그인을 시작해 주세요"
        try:
            os.write(master, code.encode() + b"\r")
        except OSError as e:
            return False, f"코드 전달에 실패했습니다: {e}"
        _login["message"] = "코드를 확인하는 중…"

    if done_event is not None:
        await asyncio.to_thread(done_event.wait, 20.0)
    if logged_in():
        await refresh_catalog()
        return True, "AGY 로그인을 완료했습니다"
    st = login_state()
    if st["pending"]:
        return False, "코드 확인이 아직 끝나지 않았습니다 — 잠시 뒤 새로고침해 주세요"
    return False, f"AGY 로그인 실패: {st['error'] or '코드를 확인해 주세요'}"


async def cancel_login() -> None:
    with _login_lock:
        proc = _login["proc"]
        _close_login_handles()
        _login.update(proc=None, url=None, expires=None, error=None, message=None, output="", done_event=None)
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
            await asyncio.to_thread(proc.wait, 5.0)
        except (OSError, subprocess.TimeoutExpired):
            pass


async def logout() -> None:
    await cancel_login()
    for p in (token_file(), _models_cache_file(), _mcp_config_file()):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
    _email_cache.update(token=None, email=None)
