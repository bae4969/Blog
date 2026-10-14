"""캔들 조회(`app/ui/stocks.py` 의 `_fetch_candles`) — 쿼리 고르기와 다시 읽기 멈춤. DB 대신 가짜를 끼운다.

값이 옛 방식(10분봉을 앱에서 묶기)과 같은지는 실제 DB 로 비교했다(temp/scripts/chart-perf, 2026-10-14: 123 경우 모두 같음).
"""

import asyncio
from datetime import datetime

from app.ui import stocks


class _DB:
    def __init__(self, first, rows):
        self.first, self.rows, self.sqls = first, rows, []

    async def execute(self, stmt, params=None):
        sql, outer = str(stmt), self
        self.sqls.append(sql)

        class _R:
            def scalar(self):
                return outer.first

            def all(self):
                return [type("Row", (), {"_mapping": dict(r)})() for r in outer.rows]
        return _R()


def _row(at, price=100.0):
    return {"execution_datetime": at, "execution_open": price, "execution_close": price, "execution_min": price,
            "execution_max": price, **{k: 1.0 for k in ("execution_non_volume", "execution_ask_volume",
                                                         "execution_bid_volume", "execution_non_amount",
                                                         "execution_ask_amount", "execution_bid_amount")}}


def _run(db, tf, start=datetime(2020, 1, 1), limit=420):
    return asyncio.run(stocks._fetch_candles(db, "sX", start, datetime(2026, 10, 14), limit, tf, False, []))


def test_일봉_이상은_DB_가_하루씩_묶는다():
    for tf, grouped in (("1d", True), ("1w", True), ("1M", True), ("1h", False), ("10m", False), ("raw", False)):
        db = _DB(datetime(2019, 1, 1), [_row(datetime(2026, 10, 13, 9))])
        _run(db, tf, limit=1)
        assert ("GROUP BY DATE(execution_datetime)" in db.sqls[-1]) is grouped, tf


def test_첫_봉보다_앞까지_읽었으면_다시_읽지_않는다():
    db = _DB(datetime(2024, 3, 1), [_row(datetime(2024, 3, 1, 9)), _row(datetime(2024, 4, 1, 9))])
    assert len(_run(db, "1M")) == 2
    assert len(db.sqls) == 2   # 첫 봉 시각 + 데이터 한 번


def test_첫_봉이_더_앞이면_넓혀_본다():
    db = _DB(datetime(2010, 1, 1), [_row(datetime(2024, 3, 1, 9))])
    _run(db, "1d", start=datetime(2024, 1, 1))
    assert len(db.sqls) == 3   # 첫 봉 + 처음 + 넓힌 한 번(늘지 않아 멈춤)


def test_빈_표는_한_번만():
    db = _DB(None, [])
    assert _run(db, "1d") == [] and len(db.sqls) == 2
