"""투자 계획 쓰기 잠금 — `plan_v1` 의 모듈 주석이 실제로 풀리고(asyncio 를 모듈에서 가져온다), 잠금이 사용자마다 하나다."""

import asyncio
import typing

from app.api import plan_v1


def test_module_annotations_resolve():
    # 예전엔 `"asyncio.Lock"` 문자열 주석이 모듈에 없는 이름을 가리켜 get_type_hints 가 NameError 였다(ruff F821)
    hints = typing.get_type_hints(plan_v1)
    assert hints["_WRITE_LOCKS"] == dict[int, asyncio.Lock]


def test_write_lock_one_per_user():
    a = plan_v1.write_lock(900001)
    assert isinstance(a, asyncio.Lock)
    assert plan_v1.write_lock(900001) is a
    assert plan_v1.write_lock(900002) is not a
