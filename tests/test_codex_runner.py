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

    async def main():
        return await asyncio.gather(*(codex_runner.run("p", None) for _ in range(3)))

    assert asyncio.run(main()) == ["ok"] * 3 and peak == 1

