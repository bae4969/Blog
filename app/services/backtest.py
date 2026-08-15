"""포트폴리오 백테스트 엔진 — PHP `BacktestService`(1,270줄)를 옮긴 것이다.

**DB 도 HTTP 도 모른다.** 시세는 호출부가 `stock_data` 로 넘겨준다(`app/ui/backtest.py`).
그래야 저장된 옛 결과를 다시 태워 대조하는 검증이 가능하다.

## 숫자가 어긋나기 쉬운 곳 — PHP 와 맞춘 지점들

- **반올림**: PHP `round()` 는 0.5 를 **0 에서 먼 쪽으로** 올린다(72.5 → 73). 파이썬 기본
  `round()` 는 짝수로 붙어(72.5 → 72) 점수가 1 씩 어긋난다. `_php_round` 를 쓴다.
- **null 은 0 이다**: PHP 산술에서 `null + 1 == 1`. EMA 시드 구간에 null 이 섞이면 PHP 는
  그걸 0 으로 더한다 — 흉내 내지 않으면 MACD 시그널선이 통째로 달라진다.
- **모집단 표준편차**: 볼린저·샤프 모두 `n` 으로 나눈다(표본 `n-1` 이 아니다).
- **소르티노 하방분산의 분모**는 하방 개수가 아니라 **전체 개수**다(PHP 그대로).

## 수익률은 전부 TWR 이다

투자원금이 중간에 늘어나므로(DCA) 단순 가치 변화는 실력이 아니다. 매 구간
`값 / (직전값 + 유입액)` 으로 유입 효과를 걷어낸 시간가중수익률을 쓴다.
"""

import math
from datetime import datetime, timedelta

WARMUP_DAYS = 60
MAX_CHART_POINTS = 500
MAX_YEARS = 30

_BMK_COLORS = (
    "rgb(249, 115, 22)", "rgb(168, 85, 247)", "rgb(34, 197, 94)",
    "rgb(236, 72, 153)", "rgb(6, 182, 212)",
)
_US_MARKETS = ("US", "NYSE", "NASDAQ", "AMEX")


def _php_round(v: float, precision: int = 0):
    """PHP `round()` — 0.5 를 0 에서 먼 쪽으로 올린다."""
    if v is None or not math.isfinite(v):
        return v
    m = 10 ** precision
    x = v * m
    r = math.floor(x + 0.5) if x >= 0 else math.ceil(x - 0.5)
    return r / m


def _num(v) -> bool:
    """PHP `isNum` — null 이 아니고 유한한 수인가."""
    return v is not None and isinstance(v, (int, float)) and math.isfinite(v)


def _z(v):
    """PHP 산술의 null → 0."""
    return 0.0 if v is None else v


# ---------------------------------------------------------------------------
# 지표
# ---------------------------------------------------------------------------

def sma(values: list, period: int) -> list:
    out = []
    for i in range(len(values)):
        if i < period - 1:
            out.append(None)
            continue
        window = values[i - period + 1:i + 1]
        out.append(sum(window) / period if all(_num(v) for v in window) else None)
    return out


def ema(values: list, period: int) -> list:
    """지수이동평균. 첫 값은 직전 `period` 개의 단순평균으로 시드한다.

    ⚠️ 시드 구간의 null 을 PHP 는 0 으로 더한다(`_z`). MACD 시그널선은 앞쪽이 null 인
       배열에 EMA 를 다시 걸기 때문에 이 동작이 결과를 좌우한다.
    """
    out = []
    k = 2.0 / (period + 1)
    prev = None
    for i, v in enumerate(values):
        if not _num(v):
            out.append(None)
            continue
        if prev is None:
            if i >= period - 1:
                prev = sum(_z(x) for x in values[i - period + 1:i + 1]) / period
                out.append(prev)
            else:
                out.append(None)
        else:
            prev = v * k + prev * (1 - k)
            out.append(prev)
    return out


def macd(values: list, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    ef, es = ema(values, fast), ema(values, slow)
    line = [ef[i] - es[i] if _num(ef[i]) and _num(es[i]) else None for i in range(len(values))]
    sig = ema(line, signal)
    hist = [line[i] - sig[i] if _num(line[i]) and _num(sig[i]) else None for i in range(len(values))]
    return {"macd": line, "signal": sig, "histogram": hist}


def rsi(values: list, period: int = 14) -> list:
    out, gains, losses = [], [], []
    avg_gain = avg_loss = 0.0
    for i in range(len(values)):
        if i == 0 or not _num(values[i]) or not _num(values[i - 1]):
            out.append(None)
            gains.append(0.0)
            losses.append(0.0)
            continue
        change = values[i] - values[i - 1]
        gains.append(change if change > 0 else 0.0)
        losses.append(-change if change < 0 else 0.0)

        if i < period:
            out.append(None)
            continue
        if i == period:
            avg_gain = sum(gains[1:period + 1]) / period
            avg_loss = sum(losses[1:period + 1]) / period
        else:
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        out.append(100.0 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss)))
    return out


def bb(values: list, period: int = 20, mult: float = 2.0) -> dict:
    upper, middle, lower = [], [], []
    for i in range(len(values)):
        if i < period - 1:
            upper.append(None); middle.append(None); lower.append(None)
            continue
        win = values[i - period + 1:i + 1]
        if not all(_num(v) for v in win):
            upper.append(None); middle.append(None); lower.append(None)
            continue
        avg = sum(win) / period
        std = math.sqrt(sum((w - avg) ** 2 for w in win) / period)   # 모집단 표준편차
        middle.append(avg)
        upper.append(avg + std * mult)
        lower.append(avg - std * mult)
    return {"upper": upper, "middle": middle, "lower": lower}


# ---------------------------------------------------------------------------
# 매매 시그널
# ---------------------------------------------------------------------------

def _eval_rule(closes: list, rule: dict) -> list:
    """규칙 하나를 날짜별 buy/sell/hold 로 편다."""
    n = len(closes)
    sig = ["hold"] * n
    ind = rule.get("indicator")

    if ind in ("bb_lower", "bb_upper"):
        b = bb(closes, 20, 2)
        for i in range(1, n):
            # ⚠️ PHP 는 **`i` 시점만, 그것도 lower 만** 유효성을 본다. 그래서 밴드가 처음
            #    생기는 i=19 에서 `[i-1]` 은 null 인 채로 비교에 들어가고, PHP 는 그걸
            #    **0 으로 강제**한다. `_z` 로 그 동작을 그대로 흉내 낸다 — 빼면 파이썬은
            #    None 비교로 터지고(단축평가 덕에 가끔만 드러난다), 0 대신 건너뛰면
            #    bb_lower 가 그 하루에 내야 할 매수 신호를 놓친다.
            if not _num(closes[i]) or not _num(b["lower"][i]):
                continue
            if ind == "bb_lower" and closes[i] < b["lower"][i] and closes[i - 1] >= _z(b["lower"][i - 1]):
                sig[i] = "buy"
            if ind == "bb_upper" and closes[i] > _z(b["upper"][i]) and closes[i - 1] <= _z(b["upper"][i - 1]):
                sig[i] = "sell"
    elif ind in ("macd_golden", "macd_death"):
        m = macd(closes)
        for i in range(1, n):
            if not all(_num(x) for x in (m["macd"][i], m["signal"][i], m["macd"][i - 1], m["signal"][i - 1])):
                continue
            prev = m["macd"][i - 1] - m["signal"][i - 1]
            curr = m["macd"][i] - m["signal"][i]
            if ind == "macd_golden" and prev <= 0 < curr:
                sig[i] = "buy"
            if ind == "macd_death" and prev >= 0 > curr:
                sig[i] = "sell"
    elif ind in ("rsi_oversold", "rsi_overbought"):
        r = rsi(closes, 14)
        for i in range(n):
            if not _num(r[i]):
                continue
            if ind == "rsi_oversold" and r[i] < 30:
                sig[i] = "buy"
            if ind == "rsi_overbought" and r[i] > 70:
                sig[i] = "sell"
    elif ind in ("sma_golden", "sma_death"):
        s5, s20 = sma(closes, 5), sma(closes, 20)
        for i in range(1, n):
            if not all(_num(x) for x in (s5[i], s20[i], s5[i - 1], s20[i - 1])):
                continue
            prev = s5[i - 1] - s20[i - 1]
            curr = s5[i] - s20[i]
            if ind == "sma_golden" and prev <= 0 < curr:
                sig[i] = "buy"
            if ind == "sma_death" and prev >= 0 > curr:
                sig[i] = "sell"
    return sig


def generate_signals(closes: list, rules: list, combine: str) -> list:
    """여러 규칙을 합친다. `and` 는 전원 찬성, `or` 는 반대표가 없을 때만 움직인다."""
    n = len(closes)
    if not rules:
        return ["hold"] * n
    per_rule = [_eval_rule(closes, r) for r in rules]

    out = []
    for i in range(n):
        buys = sum(1 for rs in per_rule if rs[i] == "buy")
        sells = sum(1 for rs in per_rule if rs[i] == "sell")
        if combine == "and":
            out.append("buy" if buys == len(per_rule) else
                       "sell" if sells == len(per_rule) else "hold")
        else:
            out.append("buy" if buys > 0 and sells == 0 else
                       "sell" if sells > 0 and buys == 0 else "hold")
    return out


def generate_dca_defer(closes: list, defer_type: str) -> list:
    """적립 유예 구간. 참인 날은 그 달 적립금을 넣지 않고 미뤄 둔다."""
    n = len(closes)
    out = [False] * n
    if not defer_type or defer_type == "none":
        return out

    if defer_type == "macd_death":
        m = macd(closes)
        in_defer = False
        for i in range(1, n):
            if not all(_num(x) for x in (m["macd"][i], m["signal"][i], m["macd"][i - 1], m["signal"][i - 1])):
                out[i] = in_defer
                continue
            prev = m["macd"][i - 1] - m["signal"][i - 1]
            curr = m["macd"][i] - m["signal"][i]
            if prev >= 0 > curr:
                in_defer = True
            if prev <= 0 < curr:
                in_defer = False
            out[i] = in_defer
    elif defer_type == "rsi_overbought":
        r = rsi(closes, 14)
        out = [_num(r[i]) and r[i] > 70 for i in range(n)]
    elif defer_type == "bb_upper":
        b = bb(closes, 20, 2)
        out = [_num(closes[i]) and _num(b["upper"][i]) and closes[i] > b["upper"][i] for i in range(n)]
    elif defer_type == "sma_death":
        s5, s20 = sma(closes, 5), sma(closes, 20)
        in_defer = False
        for i in range(1, n):
            if not all(_num(x) for x in (s5[i], s20[i], s5[i - 1], s20[i - 1])):
                out[i] = in_defer
                continue
            prev = s5[i - 1] - s20[i - 1]
            curr = s5[i] - s20[i]
            if prev >= 0 > curr:
                in_defer = True
            if prev <= 0 < curr:
                in_defer = False
            out[i] = in_defer
    return out


# ---------------------------------------------------------------------------
# 시뮬레이터
# ---------------------------------------------------------------------------

def _price(data: dict, code: str, date: str) -> float:
    d = data.get(code)
    if not d:
        return 0.0
    return d["ohlcv"].get(date, {}).get("c", 0.0) or 0.0


def _fee_rate(market: str, fees: dict) -> float:
    if market == "COIN":
        return fees.get("COIN", 0.015) / 100
    if market in _US_MARKETS:
        return fees.get("US", 0.2) / 100
    return fees.get("KR", 0.015) / 100


def _buy_by_weight(stocks, data, date, holdings, fees, cash_amount, trades) -> float:
    """가진 현금을 비중대로 나눠 산다. 낸 수수료 합계를 돌려준다."""
    paid = 0.0
    for s in stocks:
        price = _price(data, s["code"], date)
        if price <= 0:
            continue
        alloc = cash_amount * (s["weight"] / 100)
        fee = alloc * _fee_rate(s.get("market") or "", fees)
        qty = (alloc - fee) / price
        if qty > 0:
            holdings[s["code"]] += qty
            paid += fee
            trades.append({"date": date, "code": s["code"], "type": "buy",
                           "qty": qty, "price": price, "fee": fee})
    return paid


def _portfolio_value(stocks, data, date, holdings) -> float:
    return sum(holdings[s["code"]] * _price(data, s["code"], date) for s in stocks)


def _should_rebalance(date: str, last: str | None, period: str) -> bool:
    """직전 리밸런싱 이후 기간 경계를 넘었나. 첫날은 하지 않는다(초기 매수가 이미 했다)."""
    if last is None:
        return False
    y, m = int(date[:4]), int(date[5:7])
    ly, lm = int(last[:4]), int(last[5:7])
    if period == "monthly":
        return m != lm or y != ly
    if period == "quarterly":
        return (m - 1) // 3 != (lm - 1) // 3 or y != ly
    if period == "semiannual":
        return (m - 1) // 6 != (lm - 1) // 6 or y != ly
    if period == "annual":
        return y != ly
    return False


def simulate(config: dict) -> dict | None:
    """하루씩 걸으며 매매하고 자산가치를 기록한다."""
    stocks = config["stocks"]
    data = config["stockData"]
    full_dates = config["commonDates"]
    all_dates = [d for d in full_dates if config["startDate"] <= d <= config["endDate"]]
    if not all_dates:
        return None

    strategy = config.get("strategy") or "buyhold"
    fees = config.get("fees") or {}

    closes_map = {s["code"]: [_price(data, s["code"], d) or None for d in full_dates] for s in stocks}

    signal_map = {}
    if strategy == "signal" and config.get("signalRules"):
        by_target: dict[str, list] = {}
        for rule in config["signalRules"]:
            by_target.setdefault(rule.get("targetCode") or stocks[0]["code"], []).append(rule)
        for code, rules in by_target.items():
            if code in closes_map:
                signal_map[code] = generate_signals(closes_map[code], rules,
                                                    config.get("signalCombine") or "or")

    defer_map = None
    if (config.get("dcaDefer") or {}).get("enabled"):
        ind = (config.get("dcaDefer") or {}).get("indicator") or ""
        defer_map = {s["code"]: generate_dca_defer(closes_map[s["code"]], ind)
                     for s in stocks if s["code"] in closes_map}

    cash = float(config.get("initialCapital") or 0)
    holdings = {s["code"]: 0.0 for s in stocks}
    deferred = {s["code"]: 0.0 for s in stocks}
    total_fees = 0.0
    total_invested = float(config.get("initialCapital") or 0)
    trades: list = []
    series: list = []
    last_dca_month = None
    last_rebalance = None
    idx_of = {d: i for i, d in enumerate(full_dates)}

    # 초기 매수 — 시그널 전략은 시그널이 날 때까지 현금으로 들고 있는다.
    if strategy != "signal" and cash > 0:
        total_fees += _buy_by_weight(stocks, data, all_dates[0], holdings, fees, cash, trades)
        cash = 0.0

    monthly_dca = float(config.get("monthlyDCA") or 0)

    def _invest(s, amount, date):
        """유예가 풀린 적립금을 실제로 넣는다. (현금 증가분, 수수료) 를 돌려준다."""
        if strategy == "signal":
            return amount, 0.0
        price = _price(data, s["code"], date)
        if price <= 0:
            return amount, 0.0
        fee = amount * _fee_rate(s.get("market") or "", fees)
        qty = (amount - fee) / price
        if qty <= 0:
            return 0.0, 0.0
        holdings[s["code"]] += qty
        trades.append({"date": date, "code": s["code"], "type": "buy",
                       "qty": qty, "price": price, "fee": fee})
        return 0.0, fee

    for di, date in enumerate(all_dates):
        full_idx = idx_of.get(date, -1)
        month = date[:7]

        # 1) 적립: 그 달의 첫 거래일에 넣는다
        if monthly_dca > 0 and month != last_dca_month:
            last_dca_month = month
            if defer_map is not None:
                for s in stocks:
                    part = monthly_dca * (s["weight"] / 100)
                    is_deferred = (s["code"] in defer_map and full_idx >= 0
                                   and defer_map[s["code"]][full_idx])
                    if is_deferred:
                        deferred[s["code"]] += part
                    else:
                        amount = part + deferred[s["code"]]
                        deferred[s["code"]] = 0.0
                        total_invested += amount
                        back, fee = _invest(s, amount, date)
                        cash += back
                        total_fees += fee
            else:
                cash += monthly_dca
                total_invested += monthly_dca
                if strategy != "signal" and cash > 0:
                    total_fees += _buy_by_weight(stocks, data, date, holdings, fees, cash, trades)
                    cash = 0.0

        # 유예가 풀렸으면 밀어둔 적립금을 넣는다
        if defer_map is not None and full_idx >= 0:
            for s in stocks:
                if deferred[s["code"]] > 0 and s["code"] in defer_map \
                        and not defer_map[s["code"]][full_idx]:
                    amount = deferred[s["code"]]
                    deferred[s["code"]] = 0.0
                    total_invested += amount
                    back, fee = _invest(s, amount, date)
                    cash += back
                    total_fees += fee

        # 2) 전략별 매매
        if strategy == "rebalance":
            if _should_rebalance(date, last_rebalance, config.get("rebalancePeriod") or "quarterly"):
                last_rebalance = date
                total_value = cash + _portfolio_value(stocks, data, date, holdings)
                # 먼저 초과분을 판다 — 현금을 만들어야 부족분을 살 수 있다.
                for s in stocks:
                    price = _price(data, s["code"], date)
                    if price <= 0:
                        continue
                    cur = holdings[s["code"]] * price
                    target = total_value * (s["weight"] / 100)
                    if cur > target:
                        excess = cur - target
                        fee = excess * _fee_rate(s.get("market") or "", fees)
                        holdings[s["code"]] -= excess / price
                        cash += excess - fee
                        total_fees += fee
                        trades.append({"date": date, "code": s["code"], "type": "sell",
                                       "qty": excess / price, "price": price, "fee": fee})
                for s in stocks:
                    price = _price(data, s["code"], date)
                    if price <= 0:
                        continue
                    cur = holdings[s["code"]] * price
                    target = total_value * (s["weight"] / 100)
                    if cur < target and cash > 0:
                        deficit = min(target - cur, cash)
                        fee = deficit * _fee_rate(s.get("market") or "", fees)
                        qty = (deficit - fee) / price
                        if qty > 0:
                            holdings[s["code"]] += qty
                            cash -= deficit
                            total_fees += fee
                            trades.append({"date": date, "code": s["code"], "type": "buy",
                                           "qty": qty, "price": price, "fee": fee})
        elif strategy == "signal":
            for s in stocks:
                sig = signal_map.get(s["code"])
                if not sig:
                    continue
                signal = sig[full_idx] if 0 <= full_idx < len(sig) else "hold"
                price = _price(data, s["code"], date)
                if price <= 0:
                    continue
                rate = _fee_rate(s.get("market") or "", fees)
                if signal == "buy" and cash > 0:
                    alloc = cash * (s["weight"] / 100)
                    fee = alloc * rate
                    qty = (alloc - fee) / price
                    if qty > 0:
                        holdings[s["code"]] += qty
                        cash -= alloc
                        total_fees += fee
                        trades.append({"date": date, "code": s["code"], "type": "buy",
                                       "qty": qty, "price": price, "fee": fee})
                elif signal == "sell" and holdings[s["code"]] > 0:
                    qty = holdings[s["code"]]
                    value = qty * price
                    fee = value * rate
                    cash += value - fee
                    total_fees += fee
                    holdings[s["code"]] = 0.0
                    trades.append({"date": date, "code": s["code"], "type": "sell",
                                   "qty": qty, "price": price, "fee": fee})
            if cash > 0 and di == 0:
                total_fees += _buy_by_weight(stocks, data, date, holdings, fees, cash, trades)
                cash = 0.0

        series.append({"date": date,
                       "value": cash + _portfolio_value(stocks, data, date, holdings),
                       "cash": cash, "invested": total_invested})

    return {"dailySeries": series, "trades": trades,
            "totalFees": total_fees, "totalInvested": total_invested}


# ---------------------------------------------------------------------------
# 성과 지표 — 전부 TWR 기준이다
# ---------------------------------------------------------------------------

def _daily_returns(series: list) -> list:
    """하루 수익률. 분모에 그날 유입액을 더해 적립 효과를 걷어낸다."""
    out = []
    for i in range(1, len(series)):
        base = series[i - 1]["value"] + (series[i]["invested"] - series[i - 1]["invested"])
        if base > 0:
            out.append(series[i]["value"] / base - 1)
    return out


def _twr(values: list) -> float:
    """구간 전체의 시간가중 누적배수."""
    t = 1.0
    for i in range(1, len(values)):
        base = values[i - 1]["value"] + (values[i]["invested"] - values[i - 1]["invested"])
        if base > 0:
            t *= values[i]["value"] / base
    return t


def total_return(series: list) -> float:
    if len(series) < 2:
        return 0.0
    last = series[-1]
    if not last["invested"]:
        return 0.0
    return (last["value"] - last["invested"]) / last["invested"] * 100


def cagr(series: list) -> float:
    if len(series) < 2:
        return 0.0
    d0 = datetime.strptime(series[0]["date"], "%Y-%m-%d")
    d1 = datetime.strptime(series[-1]["date"], "%Y-%m-%d")
    years = (d1 - d0).total_seconds() / (365.25 * 86400)
    if years <= 0:
        return 0.0
    t = _twr(series)
    if t <= 0:
        return -100.0
    return (t ** (1 / years) - 1) * 100


def max_drawdown(series: list) -> float:
    peak, mdd = -math.inf, 0.0
    for d in series:
        if d["value"] > peak:
            peak = d["value"]
        if peak > 0:
            dd = (peak - d["value"]) / peak * 100
            mdd = max(mdd, dd)
    return mdd


def sharpe_ratio(series: list, risk_free: float) -> float:
    rets = _daily_returns(series)
    if len(rets) < 2:
        return 0.0
    rf = risk_free / 100 / 252
    excess = [r - rf for r in rets]
    mean = sum(excess) / len(excess)
    std = math.sqrt(sum((r - mean) ** 2 for r in excess) / len(excess))
    return 0.0 if std == 0 else mean / std * math.sqrt(252)


def sortino_ratio(series: list, risk_free: float) -> float:
    rets = _daily_returns(series)
    if len(rets) < 2:
        return 0.0
    rf = risk_free / 100 / 252
    excess = [r - rf for r in rets]
    mean = sum(excess) / len(excess)
    downside = [r for r in excess if r < 0]
    if not downside:
        return math.inf if mean > 0 else 0.0
    # ⚠️ 분모는 하방 개수가 아니라 전체 개수다(PHP 그대로).
    down_std = math.sqrt(sum(r * r for r in downside) / len(excess))
    return 0.0 if down_std == 0 else mean / down_std * math.sqrt(252)


def annual_returns(series: list) -> list:
    if len(series) < 2:
        return []
    years: dict[str, list] = {}
    for d in series:
        years.setdefault(d["date"][:4], []).append(d)

    out = []
    for y in sorted(years):
        vals = years[y]
        peak, mdd = -math.inf, 0.0
        for d in vals:
            if d["value"] > peak:
                peak = d["value"]
            if peak > 0:
                mdd = max(mdd, (peak - d["value"]) / peak * 100)
        out.append({
            "year": y,
            "returnPct": (_twr(vals) - 1) * 100,
            "startValue": vals[0]["value"],
            "endValue": vals[-1]["value"],
            "invested": vals[-1]["invested"],
            "mdd": mdd,
        })
    return out


def calculate_metrics(series: list, risk_free: float) -> dict:
    annuals = annual_returns(series)
    return {
        "totalReturn": total_return(series),
        "avgAnnual": (sum(a["returnPct"] for a in annuals) / len(annuals)) if annuals else 0.0,
        "cagr": cagr(series),
        "mdd": max_drawdown(series),
        "sharpe": sharpe_ratio(series, risk_free),
        "sortino": sortino_ratio(series, risk_free),
    }


def compute_score(metrics: dict) -> dict:
    """0~100 점과 등급. 지표마다 실무적인 상·하한을 잡아 정규화한 뒤 가중 평균한다."""
    def norm(v, lo, hi):
        if v is None or not isinstance(v, (int, float)) or not math.isfinite(v):
            return 50.0
        return max(0.0, min(100.0, (v - lo) / (hi - lo) * 100))

    scores = {
        "cagr": norm(metrics.get("cagr", 0), -10, 15),
        "avgAnnual": norm(metrics.get("avgAnnual", 0), -10, 20),
        "totalReturn": norm(metrics.get("totalReturn", 0), -50, 200),
        "mdd": 100 - norm(metrics.get("mdd", 0), 10, 45),      # 낙폭은 작을수록 좋다
        "sharpe": norm(metrics.get("sharpe", 0), -0.5, 1.8),
        "sortino": norm(metrics.get("sortino", 0), -0.5, 2.0),
    }
    weights = {"cagr": 20, "avgAnnual": 10, "totalReturn": 10, "mdd": 20, "sharpe": 20, "sortino": 20}
    total = int(_php_round(sum(scores[k] * w for k, w in weights.items()) / sum(weights.values())))

    for cut, grade in ((90, "A+"), (80, "A"), (70, "B+"), (60, "B"),
                       (50, "C+"), (40, "C"), (30, "D")):
        if total >= cut:
            return {"score": total, "grade": grade}
    return {"score": total, "grade": "F"}


def calculate_ranking_score(series: list, risk_free: float) -> dict:
    """투자금·적립액과 무관한 '전략 실력' 점수.

    총수익률과 낙폭을 실제 금액이 아니라 **1.0 에서 시작하는 TWR 곡선** 위에서 다시 잰다.
    그래야 많이 넣은 사람이 자동으로 높은 점수를 받는 일이 없다.
    """
    if len(series) < 2:
        return {"score": 0, "grade": "F"}

    curve = [1.0]
    for i in range(1, len(series)):
        base = series[i - 1]["value"] + (series[i]["invested"] - series[i - 1]["invested"])
        curve.append(curve[i - 1] * (series[i]["value"] / base) if base > 0 else curve[i - 1])

    peak, twr_mdd = -math.inf, 0.0
    for v in curve:
        if v > peak:
            peak = v
        if peak > 0:
            twr_mdd = max(twr_mdd, (peak - v) / peak * 100)

    year_idx: dict[str, list] = {}
    for i, d in enumerate(series):
        year_idx.setdefault(d["date"][:4], []).append(i)
    yearly = [(curve[ix[-1]] / curve[ix[0]] - 1) * 100
              for ix in year_idx.values() if len(ix) >= 2 and curve[ix[0]] > 0]

    return compute_score({
        "cagr": cagr(series),
        "avgAnnual": sum(yearly) / len(yearly) if yearly else 0.0,
        "totalReturn": (curve[-1] - 1.0) * 100,
        "mdd": twr_mdd,
        "sharpe": sharpe_ratio(series, risk_free),
        "sortino": sortino_ratio(series, risk_free),
    })


def _downsample(rows: list, max_points: int) -> list:
    """차트용으로 솎는다. 첫 점과 끝 점은 반드시 남긴다."""
    n = len(rows)
    if n <= max_points:
        return rows
    step = (n - 1) / (max_points - 1)
    out = [rows[0]]
    out += [rows[int(_php_round(i * step))] for i in range(1, max_points - 1)]
    out.append(rows[n - 1])
    return out


# ---------------------------------------------------------------------------
# 벤치마크
# ---------------------------------------------------------------------------

def simulate_benchmarks(config: dict, portfolio: dict, bmk_data: dict, risk_free: float) -> list:
    """같은 조건으로 벤치마크를 단순 매수·보유했다면 어땠을지.

    ⚠️ 벤치마크는 포트폴리오와 **거래일이 다를 수 있다**(한국 종목 vs 미국 지수). 그래서
       두 날짜집합의 합집합을 만들고, 벤치마크가 쉬는 날은 **직전 종가를 끌어다 채운다**.
       안 그러면 상대 비교 그래프가 날짜마다 어긋난다.
    """
    out = []
    benchmarks = config.get("benchmarks") or []
    if not benchmarks or not bmk_data:
        return out

    first_date = portfolio["dailySeries"][0]["date"]
    pf_dates = [d["date"] for d in portfolio["dailySeries"]]

    for i, bmk in enumerate(benchmarks):
        src = bmk_data.get(bmk["code"])
        if not src:
            continue

        ohlcv = dict(src["ohlcv"])
        union = sorted({d for d in (*pf_dates, *src["dates"])
                        if first_date <= d <= config["endDate"]})
        carry = None
        for d in union:
            if d in ohlcv:
                carry = ohlcv[d]
            elif carry is not None:
                ohlcv[d] = {"o": carry["c"], "h": carry["c"], "l": carry["c"],
                            "c": carry["c"], "v": 0}

        # ⚠️ 첫날 값이 없는 벤치마크는 **건너뛴다**. 끌어올 직전 종가가 없어 살 수가 없고,
        #    그러면 자산가치가 0 인 채로 흘러 "-100%" 라는 거짓 선이 차트에 그려진다.
        #    PHP 는 이 경우 maxDrawdown 에서 0 으로 나눠 죽었다(요청 전체가 500). 어느
        #    쪽도 못 쓰므로, 비교 대상에서 빼고 넘어간다.
        if not union or union[0] not in ohlcv:
            continue

        res = simulate({
            "stocks": [{"code": bmk["code"], "market": bmk.get("market") or "", "weight": 100}],
            "stockData": {bmk["code"]: {"dates": union, "ohlcv": ohlcv}},
            "commonDates": union,
            "startDate": first_date, "endDate": config["endDate"],
            "strategy": "buyhold", "rebalancePeriod": "quarterly",
            "signalRules": [], "signalCombine": "or",
            "initialCapital": config.get("initialCapital") or 0,
            "monthlyDCA": config.get("monthlyDCA") or 0,
            "dcaDefer": {"enabled": False},
            "fees": config.get("fees") or {}, "riskFreeRate": risk_free,
        })
        if not res or not res["dailySeries"]:
            continue

        ds = res["dailySeries"]
        chart = [{"date": ds[0]["date"], "returnPct": 0}]
        t = 1.0
        for bi in range(1, len(ds)):
            base = ds[bi - 1]["value"] + (ds[bi]["invested"] - ds[bi - 1]["invested"])
            if base > 0:
                t *= ds[bi]["value"] / base
            chart.append({"date": ds[bi]["date"], "returnPct": (t - 1) * 100})

        out.append({
            "name": bmk.get("name") or bmk["code"],
            "color": _BMK_COLORS[i % len(_BMK_COLORS)],
            "metrics": calculate_metrics(ds, risk_free),
            "chartData": _downsample(chart, MAX_CHART_POINTS),
        })
    return out


# ---------------------------------------------------------------------------
# 엔트리포인트
# ---------------------------------------------------------------------------

def warmup_start(start_date: str) -> str:
    """지표가 워밍업할 여유를 둔 조회 시작일 — 요청 시작일보다 120일 앞."""
    return (datetime.strptime(start_date, "%Y-%m-%d")
            - timedelta(days=WARMUP_DAYS * 2)).strftime("%Y-%m-%d")


def build_series(candles: list) -> dict | None:
    """캔들 행을 `{dates, ohlcv}` 로. 같은 날이 여럿이면 **첫 행만** 쓴다(PHP 와 같다)."""
    if not candles:
        return None
    ohlcv, dates = {}, []
    for c in candles:
        d = str(c["execution_datetime"])[:10]
        if d in ohlcv:
            continue
        ohlcv[d] = {
            "o": float(c["execution_open"]), "h": float(c["execution_max"]),
            "l": float(c["execution_min"]), "c": float(c["execution_close"]),
            "v": (float(c.get("execution_bid_volume") or 0)
                  + float(c.get("execution_ask_volume") or 0)
                  + float(c.get("execution_non_volume") or 0)),
        }
        dates.append(d)
    dates.sort()
    return {"dates": dates, "ohlcv": ohlcv}


def run(config: dict, stock_data: dict, benchmark_data: dict) -> dict | None:
    """백테스트 한 번. 시세는 호출부가 이미 읽어서 넘겨준다.

    `stock_data`·`benchmark_data` 는 `{종목코드: build_series(...) 결과 또는 None}`.
    """
    d0 = datetime.strptime(config["startDate"], "%Y-%m-%d")
    d1 = datetime.strptime(config["endDate"], "%Y-%m-%d")
    if (d1 - d0).total_seconds() / (365.25 * 86400) > MAX_YEARS:
        return None

    # 공통 거래일 = 모든 **포트폴리오** 종목이 값을 가진 날(벤치마크는 빠진다).
    date_sets = [set(d["dates"]) for d in stock_data.values() if d]
    if not date_sets:
        return None
    common = sorted(set.intersection(*date_sets))
    if not common:
        return None

    result = simulate({**config, "stockData": stock_data, "commonDates": common})
    if not result or not result["dailySeries"]:
        return None

    risk_free = config.get("riskFreeRate", 3.0)
    series = result["dailySeries"]
    buys = sum(1 for t in result["trades"] if t["type"] == "buy")
    sells = len(result["trades"]) - buys
    ranking = calculate_ranking_score(series, risk_free)

    return {
        "dailySeries": _downsample(series, MAX_CHART_POINTS),
        "metrics": calculate_metrics(series, risk_free),
        "annualReturns": annual_returns(series),
        "tradeSummary": {
            "totalCount": buys + sells, "buyCount": buys, "sellCount": sells,
            "totalInvested": result["totalInvested"], "totalFees": result["totalFees"],
        },
        "benchmarks": simulate_benchmarks(config, result, benchmark_data, risk_free),
        "rankingScore": ranking["score"],
        "rankingGrade": ranking["grade"],
    }
