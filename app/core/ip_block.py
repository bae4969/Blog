"""차단 IP 적용.

`/admin/ip-blocks` 는 `blocked_ip_list` 를 관리하는데, **그 목록을 읽어 실제로 막는 곳이
없었다**(2026-08-15 발견). 관리자가 IP 를 차단해도 그냥 들어왔다 — 화면만 있고 효력이
없는 상태였다. 이 모듈이 그 구멍을 메운다.

## 자동 판정은 하지 않는다

PHP 는 미들웨어가 분당 과다요청·404 반복·로그인 실패·의심 URL 을 보고 **스스로** 차단했다.
그건 옮기지 않기로 했다(2026-08-15 결정 A):

- **로그인 실패**는 블로그가 알 수 없다 — 인증이 중앙 auth 로 갔다.
- **요청 수 제한**은 앞단(Traefik)이 할 일이다. 앱까지 와서 DB 를 거친 뒤 막는 건 늦고,
  카운터를 DB 에 쓰면 방어하려다 부하를 만든다.

여기서는 **사람이 넣은 차단만 집행**한다.

## 매 요청 DB 를 치지 않는다

차단 목록은 작고 자주 바뀌지 않는다. 메모리에 들고 있다가 `_TTL` 초마다 다시 읽고,
관리자가 목록을 고치면 `invalidate()` 로 즉시 버린다.
"""

import logging
import time

from sqlalchemy import text

logger = logging.getLogger(__name__)

_TTL = 60.0
# 스스로를 잠그면 곤란한 주소들. PHP 도 같은 둘을 화이트리스트로 뒀다.
_NEVER_BLOCK = frozenset({"127.0.0.1", "::1"})

_cache: frozenset[str] = frozenset()
_loaded_at: float = 0.0


def invalidate() -> None:
    """다음 요청에서 목록을 다시 읽게 한다. 관리자가 차단을 더하거나 뺄 때 부른다."""
    global _loaded_at
    _loaded_at = 0.0


async def _blocked_set(db) -> frozenset[str]:
    """지금 유효한 차단 IP 들. 만료된 것은 목록에 남아 있어도 막지 않는다."""
    global _cache, _loaded_at
    now = time.monotonic()
    if now - _loaded_at < _TTL:
        return _cache
    rows = (await db.execute(text(
        "SELECT ip_address FROM blocked_ip_list "
        "WHERE expires_at IS NULL OR expires_at > NOW()"))).all()
    _cache = frozenset(r[0] for r in rows if r[0])
    _loaded_at = now
    return _cache


async def is_blocked(db, ip: str | None) -> bool:
    if not ip or ip in _NEVER_BLOCK:
        return False
    return ip in await _blocked_set(db)
