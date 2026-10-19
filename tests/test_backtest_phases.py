"""백테스트 구성 변경(구간, 2026-10-19) — 가짜 시세로 엔진만 본다. DB 없이.

⚠️ 구성 변경이 없을 때 예전과 같은지는 실제 시세로 따로 대조했다(temp/scripts/backtest-phases/golden.py — 24건 바이트 일치).
"""

from datetime import date, timedelta

import pytest

from app.services import backtest as engine


def _days(n, start=date(2025, 1, 6), skip=()):
    """평일 n 개(skip 날짜는 뺀다) — 'YYYY-MM-DD'."""
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5 and d.isoformat() not in skip:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _series(dates, price=100.0):
    px = price if callable(price) else (lambda i: price)
    return {"dates": list(dates), "ohlcv": {d: {"o": px(i), "h": px(i), "l": px(i), "c": px(i), "v": 0} for i, d in enumerate(dates)}}


def _cfg(dates, changes=None, **kw):
    return {"stocks": [{"code": "A", "market": "KR", "weight": 100}], "changes": changes or [],
            "startDate": dates[0], "endDate": dates[-1], "strategy": "buyhold", "initialCapital": 1_000_000,
            "monthlyDCA": 0, "fees": {"KR": 0}, "riskFreeRate": 3, "benchmarks": [], **kw}


def _sim(cfg, data):
    """run() 과 같은 길 — 구간이 있으면 실제 시작일로 고치고 그 구간들의 거래일로."""
    phases = engine.phases_of(cfg)
    if len(phases) > 1:
        phases = engine.effective_phases(phases, data)
        return engine.simulate({**cfg, "stockData": data, "commonDates": engine.phase_dates(phases, data), "phases": phases})
    common = sorted(set.intersection(*[set(d["dates"]) for d in data.values()]))
    return engine.simulate({**cfg, "stockData": data, "commonDates": common})


def _held(res, code):
    q = 0.0
    for t in res["trades"]:
        if t["code"] == code:
            q += t["qty"] if t["type"] == "buy" else -t["qty"]
    return q


def test_한번에_바꾸면_그날_다_옮긴다():
    dates = _days(10)
    data = {"A": _series(dates), "B": _series(dates, 50.0)}
    res = _sim(_cfg(dates, [{"date": dates[4], "stocks": [{"code": "B", "market": "KR", "weight": 100}]}]), data)
    assert res["changedAt"] == [{"date": dates[4], "phase": 1}]
    assert _held(res, "A") == pytest.approx(0) and _held(res, "B") == pytest.approx(20_000)   # 100만 / 50
    assert {round(r["value"]) for r in res["dailySeries"]} == {1_000_000}                   # 값이 그대로면 평가도 그대로


def test_나눠_바꾸면_매일_같은_몫씩_다가간다():
    dates = _days(10)
    data = {"A": _series(dates), "B": _series(dates)}
    res = _sim(_cfg(dates, [{"date": dates[2], "stocks": [{"code": "B", "market": "KR", "weight": 100}], "spreadDays": 4}]), data)
    b_by_day = {}
    q = 0.0
    for t in sorted((t for t in res["trades"] if t["code"] == "B"), key=lambda t: t["date"]):
        q += t["qty"]
        b_by_day[t["date"]] = q
    assert [round(b_by_day[d]) for d in dates[2:6]] == [2_500, 5_000, 7_500, 10_000]       # 25·50·75·100%
    assert not any(t["date"] > dates[5] for t in res["trades"])                           # 다 옮긴 뒤엔 매매 없음


def test_늦게_상장한_종목이_시작일을_밀지_않는다():
    dates = _days(20)
    data = {"A": _series(dates), "B": _series(dates[10:])}                                 # B 는 11번째 날부터
    res = _sim(_cfg(dates, [{"date": dates[12], "stocks": [{"code": "A", "market": "KR", "weight": 50},
                                                           {"code": "B", "market": "KR", "weight": 50}]}]), data)
    assert res["dailySeries"][0]["date"] == dates[0] and len(res["dailySeries"]) == 20


def test_새_종목_시세가_늦으면_그날_시작하고_그전엔_앞_구간이_이어진다():
    dates = _days(30)
    data = {"A": _series(dates), "B": _series(dates[20:], 50.0)}                          # B 는 21번째 날부터
    res = _sim(_cfg(dates, [{"date": dates[5], "stocks": [{"code": "B", "market": "KR", "weight": 100}]}]), data)
    assert res["changedAt"] == [{"date": dates[20], "phase": 1}]
    assert [r["date"] for r in res["dailySeries"]] == dates                               # 빠지는 날이 없다
    assert _held(res, "B") == pytest.approx(20_000)


def test_휴장인_변경일은_다음_거래일에():
    dates = _days(10, skip={"2025-01-09"})
    data = {"A": _series(dates), "B": _series(dates)}
    res = _sim(_cfg(dates, [{"date": "2025-01-09", "stocks": [{"code": "B", "market": "KR", "weight": 100}]}]), data)
    assert res["changedAt"][0]["date"] == "2025-01-10"


def test_빠진_종목은_새_구간에서_팔린다_시그널도():
    dates = _days(30)
    data = {"A": _series(dates, lambda i: 100 + i), "B": _series(dates, 80.0)}
    cfg = _cfg(dates, [{"date": dates[15], "stocks": [{"code": "B", "market": "KR", "weight": 100}]}], strategy="signal",
               signalRules=[{"indicator": "rsi_overbought", "targetCode": "A"}], signalCombine="or")
    res = _sim(cfg, data)
    assert _held(res, "A") == pytest.approx(0, abs=1e-9) and _held(res, "B") > 0
    assert not any(t["code"] == "A" for t in res["trades"] if t["date"] > dates[15])        # A 규칙은 그 뒤로 쉰다


def test_정기_리밸런싱은_새_비중으로():
    dates = _days(70)
    data = {"A": _series(dates, lambda i: 100 + i), "B": _series(dates)}
    cfg = _cfg(dates, [{"date": dates[5], "stocks": [{"code": "A", "market": "KR", "weight": 30},
                                                      {"code": "B", "market": "KR", "weight": 70}]}],
               stocks=[{"code": "A", "market": "KR", "weight": 50}, {"code": "B", "market": "KR", "weight": 50}],
               strategy="rebalance", rebalancePeriod="monthly")
    res = _sim(cfg, data)
    last = res["dailySeries"][-1]
    d = max(t["date"] for t in res["trades"])          # 마지막 리밸런싱 날의 비중이 30:70
    pa = data["A"]["ohlcv"][d]["c"]
    a_val, b_val = _held(res, "A") * pa, _held(res, "B") * 100
    assert a_val / (a_val + b_val) == pytest.approx(0.30, abs=0.02) and last["value"] > 0


def test_구성_변경이_없으면_changedAt_도_없다():
    dates = _days(10)
    res = _sim(_cfg(dates), {"A": _series(dates)})
    assert "changedAt" not in res


class TestNormChanges:
    """서버 입력 검사(`_norm_config`) — 구성 변경은 날짜순·기간 안·비중 합 100·종목 1개 이상."""

    BASE = {"stocks": [{"code": "A", "market": "KR", "weight": 100}], "startDate": "2025-01-01", "endDate": "2025-12-31"}

    def _norm(self, changes):
        from app.ui.backtest import _norm_config
        return _norm_config({**self.BASE, "changes": changes})

    def test_정상(self):
        cfg, err = self._norm([{"date": "2025-03-03", "stocks": [{"code": "B", "weight": 60}, {"code": "A", "weight": 40}],
                                "spreadDays": 5}])
        assert err is None and cfg["changes"][0]["spreadDays"] == 5 and cfg["changes"][0]["stocks"][0]["code"] == "B"

    @pytest.mark.parametrize("changes, msg", [
        ([{"date": "2025-01-01", "stocks": [{"code": "B", "weight": 100}]}], "뒤"),          # 시작일과 같은 날
        ([{"date": "2026-01-02", "stocks": [{"code": "B", "weight": 100}]}], "종료일"),
        ([{"date": "2025-05-01", "stocks": [{"code": "B", "weight": 100}]},
          {"date": "2025-04-01", "stocks": [{"code": "A", "weight": 100}]}], "앞 구간"),     # 날짜순이 아님
        ([{"date": "2025-03-03", "stocks": [{"code": "B", "weight": 90}]}], "100%"),
        ([{"date": "2025-03-03", "stocks": []}], "1개 이상"),
        ([{"date": "2025-03", "stocks": [{"code": "B", "weight": 100}]}], "형식"),
    ])
    def test_어긋나면_이유와_함께_거절(self, changes, msg):
        cfg, err = self._norm(changes)
        assert cfg is None and msg in err

    def test_합쳐서_15종목까지(self):
        many = [{"code": f"C{i}", "weight": 10} for i in range(10)]
        more = [{"code": f"D{i}", "weight": 10} for i in range(10)]
        cfg, err = self._norm([{"date": "2025-03-03", "stocks": many}, {"date": "2025-06-02", "stocks": more}])
        assert cfg is None and "15" in err

    def test_요청_모델이_changes_를_버리지_않는다(self):
        # ⚠️ 2026-08-23 회귀(선언 안 된 키를 Pydantic 이 조용히 버림)와 같은 자리 — 기본값(빈 목록)과 다른 값으로 잰다
        from app.api.backtest_v1 import BacktestRequest
        ch = [{"date": "2025-03-03", "stocks": [{"code": "B", "weight": 100}]}]
        assert BacktestRequest.model_validate({**self.BASE, "changes": ch}).model_dump()["changes"] == ch


def test_키는_일정이_있을_때만_달라진다():
    from app.ui.backtest import _config_hash
    st = [{"code": "A", "weight": 100}]
    assert _config_hash(st, "buyhold") == _config_hash(st, "buyhold", [])          # 옛 키 그대로(마이그레이션 0007 과도 맞는다)
    a = _config_hash(st, "buyhold", [{"date": "2025-03-03", "spreadDays": 1, "stocks": [{"code": "B", "weight": 100}]}])
    b = _config_hash(st, "buyhold", [{"date": "2025-03-03", "spreadDays": 5, "stocks": [{"code": "B", "weight": 100}]}])
    assert len({_config_hash(st, "buyhold"), a, b}) == 3
