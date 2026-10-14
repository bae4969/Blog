"""codex 실행기(`app/services/codex_runner.py`) — 한 번에 하나만 돈다(상담과 매일 점검이 겹쳐도)."""

import asyncio

from app.services import codex_runner


def test_동시에_불러도_하나씩_돈다(monkeypatch):
    running, peak = 0, 0

    async def fake(*args):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return "ok"

    monkeypatch.setattr(codex_runner, "_run", fake)
    monkeypatch.setattr(codex_runner, "_RUN_LOCK", asyncio.Lock())   # 잠금은 처음 기다린 이벤트 루프에 묶인다 — 테스트마다 새로

    async def main():
        return await asyncio.gather(*(codex_runner.run("p", None) for _ in range(3)))

    assert asyncio.run(main()) == ["ok"] * 3 and peak == 1


def test_앞_실행을_기다리는_데도_상한이_있다(monkeypatch):
    monkeypatch.setattr(codex_runner, "LOCK_WAIT", 0.05)

    async def slow(*args):
        await asyncio.sleep(0.3)
        return "ok"

    monkeypatch.setattr(codex_runner, "_run", slow)
    monkeypatch.setattr(codex_runner, "_RUN_LOCK", asyncio.Lock())

    async def main():
        first = asyncio.create_task(codex_runner.run("p", None))
        await asyncio.sleep(0.01)
        try:
            await codex_runner.run("q", None)
        except codex_runner.CodexError as e:
            return await first, str(e)

    done, err = asyncio.run(main())
    assert done == "ok" and "앞의 AI 작업" in err
