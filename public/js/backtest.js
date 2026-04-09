/**
 * 포트폴리오 백테스팅 시뮬레이터
 * - 모든 연산은 클라이언트에서 수행
 * - 기존 /stocks/api/candle API를 활용하여 일봉 데이터 fetch
 */
(function () {
    'use strict';

    /* =========================================
       상수 & 상태
       ========================================= */
    var MAX_STOCKS = 10;
    var WARMUP_DAYS = 60; // 지표 계산을 위한 워밍업 기간
    var portfolio = [];    // [{ code, name, market, weight }]
    var benchmark = null;  // { code, name, market }
    var backtestChart = null;

    /* =========================================
       유틸리티
       ========================================= */
    function formatNumber(n, decimals) {
        if (decimals === undefined) decimals = 0;
        if (n === null || n === undefined || isNaN(n)) return '-';
        return Number(n).toLocaleString('ko-KR', {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals
        });
    }

    function formatPercent(n, decimals) {
        if (decimals === undefined) decimals = 2;
        if (n === null || n === undefined || isNaN(n)) return '-';
        var sign = n >= 0 ? '+' : '';
        return sign + n.toFixed(decimals) + '%';
    }

    function formatCurrency(n) {
        if (n === null || n === undefined || isNaN(n)) return '-';
        if (Math.abs(n) >= 1e8) return formatNumber(n / 1e8, 1) + '억원';
        if (Math.abs(n) >= 1e4) return formatNumber(n / 1e4, 0) + '만원';
        return formatNumber(n, 0) + '원';
    }

    function dateStr(d) {
        var yyyy = d.getFullYear();
        var mm = String(d.getMonth() + 1).padStart(2, '0');
        var dd = String(d.getDate()).padStart(2, '0');
        return yyyy + '-' + mm + '-' + dd;
    }

    function parseDate(s) {
        var parts = s.split(/[-T ]/);
        return new Date(+parts[0], +parts[1] - 1, +parts[2] || 1);
    }

    function isFiniteNum(v) {
        return typeof v === 'number' && isFinite(v);
    }

    function getMarketParam(market) {
        if (!market) return '';
        return '&market=' + encodeURIComponent(market);
    }

    /* =========================================
       데이터 계층 — BacktestData
       ========================================= */
    var BacktestData = {
        /**
         * 단일 종목의 일봉 데이터 fetch
         * @returns Promise<{dates:string[], ohlcv:{date→{o,h,l,c,v}}}>
         */
        fetchCandle: function (code, market, startDate, endDate) {
            var warmStart = new Date(parseDate(startDate));
            warmStart.setDate(warmStart.getDate() - WARMUP_DAYS * 2);
            var start = dateStr(warmStart) + ' 00:00:00';
            var end = endDate + ' 23:59:00';
            var url = '/stocks/api/candle?code=' + encodeURIComponent(code) +
                '&start=' + encodeURIComponent(start) +
                '&end=' + encodeURIComponent(end) +
                '&timeframe=1d&limit=1000' + getMarketParam(market);

            return fetch(url, {
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            })
                .then(function (r) { return r.json(); })
                .then(function (json) {
                    if (!json.success || !json.data) return null;
                    var map = {};
                    var dates = [];
                    json.data.forEach(function (c) {
                        var d = c.execution_datetime.split(' ')[0];
                        if (!map[d]) {
                            map[d] = {
                                o: parseFloat(c.execution_open),
                                h: parseFloat(c.execution_max),
                                l: parseFloat(c.execution_min),
                                c: parseFloat(c.execution_close),
                                v: parseFloat(c.execution_bid_volume || 0) + parseFloat(c.execution_ask_volume || 0) + parseFloat(c.execution_non_volume || 0)
                            };
                            dates.push(d);
                        }
                    });
                    dates.sort();
                    return { dates: dates, ohlcv: map };
                });
        },

        /**
         * 포트폴리오 + 벤치마크 전체 데이터 병렬 fetch
         * @param onProgress 콜백(loaded, total)
         * @returns Promise<{ stockData:{code→{dates,ohlcv}}, benchmarkData, commonDates }>
         */
        fetchAll: function (stocks, bmk, startDate, endDate, onProgress) {
            var total = stocks.length + (bmk ? 1 : 0);
            var loaded = 0;
            var allItems = stocks.map(function (s) { return { code: s.code, market: s.market, isBmk: false }; });
            if (bmk) allItems.push({ code: bmk.code, market: bmk.market, isBmk: true });

            var stockData = {};
            var benchmarkData = null;

            var promises = allItems.map(function (item) {
                return BacktestData.fetchCandle(item.code, item.market, startDate, endDate)
                    .then(function (data) {
                        loaded++;
                        if (onProgress) onProgress(loaded, total);
                        if (item.isBmk) {
                            benchmarkData = data;
                        } else {
                            stockData[item.code] = data;
                        }
                    });
            });

            return Promise.all(promises).then(function () {
                // 공통 날짜 계산 (모든 종목에 데이터 있는 날만)
                var dateSets = [];
                Object.keys(stockData).forEach(function (code) {
                    if (stockData[code]) dateSets.push(new Set(stockData[code].dates));
                });
                if (dateSets.length === 0) return null;

                var common = Array.from(dateSets[0]);
                for (var i = 1; i < dateSets.length; i++) {
                    common = common.filter(function (d) { return dateSets[i].has(d); });
                }
                // 시작일 이후만 필터 (워밍업 기간 포함)
                common.sort();

                return {
                    stockData: stockData,
                    benchmarkData: benchmarkData,
                    commonDates: common
                };
            });
        }
    };

    /* =========================================
       지표 엔진 — Indicators
       ========================================= */
    var Indicators = {
        sma: function (values, period) {
            var result = [];
            for (var i = 0; i < values.length; i++) {
                if (i < period - 1) { result.push(null); continue; }
                var sum = 0, valid = true;
                for (var j = i - period + 1; j <= i; j++) {
                    if (!isFiniteNum(values[j])) { valid = false; break; }
                    sum += values[j];
                }
                result.push(valid ? sum / period : null);
            }
            return result;
        },

        ema: function (values, period) {
            var result = [];
            var k = 2 / (period + 1);
            var prev = null;
            for (var i = 0; i < values.length; i++) {
                if (!isFiniteNum(values[i])) { result.push(null); continue; }
                if (prev === null) {
                    // 첫 유효값: SMA로 초기화
                    if (i >= period - 1) {
                        var sum = 0;
                        for (var j = i - period + 1; j <= i; j++) sum += values[j];
                        prev = sum / period;
                        result.push(prev);
                    } else {
                        result.push(null);
                    }
                } else {
                    prev = values[i] * k + prev * (1 - k);
                    result.push(prev);
                }
            }
            return result;
        },

        macd: function (values, fast, slow, signal) {
            if (!fast) fast = 12;
            if (!slow) slow = 26;
            if (!signal) signal = 9;
            var emaFast = this.ema(values, fast);
            var emaSlow = this.ema(values, slow);
            var macdLine = [];
            for (var i = 0; i < values.length; i++) {
                if (isFiniteNum(emaFast[i]) && isFiniteNum(emaSlow[i])) {
                    macdLine.push(emaFast[i] - emaSlow[i]);
                } else {
                    macdLine.push(null);
                }
            }
            // signal line = EMA of MACD line
            var validMacd = macdLine.map(function (v) { return v !== null ? v : NaN; });
            var signalLine = this.ema(validMacd.map(function (v) { return isFinite(v) ? v : null; }), signal);
            var histogram = [];
            for (var i = 0; i < values.length; i++) {
                if (isFiniteNum(macdLine[i]) && isFiniteNum(signalLine[i])) {
                    histogram.push(macdLine[i] - signalLine[i]);
                } else {
                    histogram.push(null);
                }
            }
            return { macd: macdLine, signal: signalLine, histogram: histogram };
        },

        rsi: function (values, period) {
            if (!period) period = 14;
            var result = [];
            var gains = [], losses = [];
            for (var i = 0; i < values.length; i++) {
                if (i === 0 || !isFiniteNum(values[i]) || !isFiniteNum(values[i - 1])) {
                    result.push(null);
                    gains.push(0);
                    losses.push(0);
                    continue;
                }
                var change = values[i] - values[i - 1];
                gains.push(change > 0 ? change : 0);
                losses.push(change < 0 ? -change : 0);

                if (i < period) {
                    result.push(null);
                    continue;
                }
                if (i === period) {
                    var avgGain = 0, avgLoss = 0;
                    for (var j = 1; j <= period; j++) { avgGain += gains[j]; avgLoss += losses[j]; }
                    avgGain /= period;
                    avgLoss /= period;
                } else {
                    avgGain = (avgGain * (period - 1) + gains[i]) / period;
                    avgLoss = (avgLoss * (period - 1) + losses[i]) / period;
                }
                if (avgLoss === 0) { result.push(100); }
                else { result.push(100 - (100 / (1 + avgGain / avgLoss))); }
            }
            return result;
        },

        bb: function (values, period, stdMultiplier) {
            if (!period) period = 20;
            if (!stdMultiplier) stdMultiplier = 2;
            var upper = [], middle = [], lower = [];
            for (var i = 0; i < values.length; i++) {
                if (i < period - 1) { upper.push(null); middle.push(null); lower.push(null); continue; }
                var win = [], bad = false;
                for (var j = i - period + 1; j <= i; j++) {
                    if (!isFiniteNum(values[j])) { bad = true; break; }
                    win.push(values[j]);
                }
                if (bad) { upper.push(null); middle.push(null); lower.push(null); continue; }
                var avg = 0;
                for (var k = 0; k < win.length; k++) avg += win[k];
                avg /= period;
                var variance = 0;
                for (var k = 0; k < win.length; k++) variance += Math.pow(win[k] - avg, 2);
                var std = Math.sqrt(variance / period);
                middle.push(avg);
                upper.push(avg + std * stdMultiplier);
                lower.push(avg - std * stdMultiplier);
            }
            return { upper: upper, middle: middle, lower: lower };
        }
    };

    /* =========================================
       시그널 생성기 — SignalGenerator
       ========================================= */
    var SignalGenerator = {
        /**
         * 규칙 목록과 일봉 종가 배열로 시그널 생성
         * @param closes 종가 배열
         * @param rules [{ indicator, action }]  (action: buy/sell)
         * @param combine 'and'|'or'
         * @returns string[] — 'buy'|'sell'|'hold' (closes와 동일 길이)
         */
        generate: function (closes, rules, combine) {
            if (!rules || rules.length === 0) {
                return closes.map(function () { return 'hold'; });
            }

            var ruleSignals = rules.map(function (rule) {
                return SignalGenerator._evalRule(closes, rule);
            });

            var signals = [];
            for (var i = 0; i < closes.length; i++) {
                var buys = 0, sells = 0;
                for (var r = 0; r < ruleSignals.length; r++) {
                    var s = ruleSignals[r][i];
                    if (s === 'buy') buys++;
                    else if (s === 'sell') sells++;
                }
                if (combine === 'and') {
                    if (buys === ruleSignals.length) signals.push('buy');
                    else if (sells === ruleSignals.length) signals.push('sell');
                    else signals.push('hold');
                } else {
                    if (buys > 0 && sells === 0) signals.push('buy');
                    else if (sells > 0 && buys === 0) signals.push('sell');
                    else signals.push('hold');
                }
            }
            return signals;
        },

        _evalRule: function (closes, rule) {
            var signals = closes.map(function () { return 'hold'; });
            var ind = rule.indicator;

            if (ind === 'bb_lower' || ind === 'bb_upper') {
                var bb = Indicators.bb(closes, 20, 2);
                for (var i = 1; i < closes.length; i++) {
                    if (!isFiniteNum(closes[i]) || !isFiniteNum(bb.lower[i])) continue;
                    if (ind === 'bb_lower' && closes[i] < bb.lower[i] && closes[i - 1] >= bb.lower[i - 1]) {
                        signals[i] = 'buy';
                    }
                    if (ind === 'bb_upper' && closes[i] > bb.upper[i] && closes[i - 1] <= bb.upper[i - 1]) {
                        signals[i] = 'sell';
                    }
                }
            } else if (ind === 'macd_golden' || ind === 'macd_death') {
                var m = Indicators.macd(closes);
                for (var i = 1; i < closes.length; i++) {
                    if (!isFiniteNum(m.macd[i]) || !isFiniteNum(m.signal[i])) continue;
                    if (!isFiniteNum(m.macd[i - 1]) || !isFiniteNum(m.signal[i - 1])) continue;
                    var prev = m.macd[i - 1] - m.signal[i - 1];
                    var curr = m.macd[i] - m.signal[i];
                    if (ind === 'macd_golden' && prev <= 0 && curr > 0) signals[i] = 'buy';
                    if (ind === 'macd_death' && prev >= 0 && curr < 0) signals[i] = 'sell';
                }
            } else if (ind === 'rsi_oversold' || ind === 'rsi_overbought') {
                var rsi = Indicators.rsi(closes, 14);
                for (var i = 0; i < closes.length; i++) {
                    if (!isFiniteNum(rsi[i])) continue;
                    if (ind === 'rsi_oversold' && rsi[i] < 30) signals[i] = 'buy';
                    if (ind === 'rsi_overbought' && rsi[i] > 70) signals[i] = 'sell';
                }
            } else if (ind === 'sma_golden' || ind === 'sma_death') {
                var short5 = Indicators.sma(closes, 5);
                var long20 = Indicators.sma(closes, 20);
                for (var i = 1; i < closes.length; i++) {
                    if (!isFiniteNum(short5[i]) || !isFiniteNum(long20[i])) continue;
                    if (!isFiniteNum(short5[i - 1]) || !isFiniteNum(long20[i - 1])) continue;
                    var prevDiff = short5[i - 1] - long20[i - 1];
                    var currDiff = short5[i] - long20[i];
                    if (ind === 'sma_golden' && prevDiff <= 0 && currDiff > 0) signals[i] = 'buy';
                    if (ind === 'sma_death' && prevDiff >= 0 && currDiff < 0) signals[i] = 'sell';
                }
            }
            return signals;
        },

        /**
         * DCA 유예 시그널 생성
         * @returns boolean[] — true=유예, false=투입 가능
         */
        generateDCADefer: function (closes, deferType) {
            var deferred = closes.map(function () { return false; });
            if (!deferType) return deferred;

            if (deferType === 'macd_death') {
                var m = Indicators.macd(closes);
                var inDefer = false;
                for (var i = 1; i < closes.length; i++) {
                    if (!isFiniteNum(m.macd[i]) || !isFiniteNum(m.signal[i])) { deferred[i] = inDefer; continue; }
                    if (!isFiniteNum(m.macd[i - 1]) || !isFiniteNum(m.signal[i - 1])) { deferred[i] = inDefer; continue; }
                    var prev = m.macd[i - 1] - m.signal[i - 1];
                    var curr = m.macd[i] - m.signal[i];
                    if (prev >= 0 && curr < 0) inDefer = true; // 데스크로스 → 유예
                    if (prev <= 0 && curr > 0) inDefer = false; // 골든크로스 → 해제
                    deferred[i] = inDefer;
                }
            } else if (deferType === 'rsi_overbought') {
                var rsi = Indicators.rsi(closes, 14);
                for (var i = 0; i < closes.length; i++) {
                    deferred[i] = isFiniteNum(rsi[i]) && rsi[i] > 70;
                }
            } else if (deferType === 'bb_upper') {
                var bb = Indicators.bb(closes, 20, 2);
                for (var i = 0; i < closes.length; i++) {
                    deferred[i] = isFiniteNum(closes[i]) && isFiniteNum(bb.upper[i]) && closes[i] > bb.upper[i];
                }
            } else if (deferType === 'sma_death') {
                var s5 = Indicators.sma(closes, 5);
                var s20 = Indicators.sma(closes, 20);
                var inDefer = false;
                for (var i = 1; i < closes.length; i++) {
                    if (!isFiniteNum(s5[i]) || !isFiniteNum(s20[i])) { deferred[i] = inDefer; continue; }
                    if (!isFiniteNum(s5[i - 1]) || !isFiniteNum(s20[i - 1])) { deferred[i] = inDefer; continue; }
                    var prevD = s5[i - 1] - s20[i - 1];
                    var currD = s5[i] - s20[i];
                    if (prevD >= 0 && currD < 0) inDefer = true;
                    if (prevD <= 0 && currD > 0) inDefer = false;
                    deferred[i] = inDefer;
                }
            }
            return deferred;
        }
    };

    /* =========================================
       포트폴리오 시뮬레이터 — PortfolioSimulator
       ========================================= */
    var PortfolioSimulator = {
        /**
         * @param config {
         *   stocks: [{code, market, weight}],
         *   stockData: {code→{dates,ohlcv}},
         *   commonDates: string[],
         *   startDate, endDate: string,
         *   strategy: 'buyhold'|'rebalance'|'signal',
         *   rebalancePeriod: 'monthly'|'quarterly'|'semiannual'|'annual',
         *   signalRules: [{indicator, targetCode}],
         *   signalCombine: 'and'|'or',
         *   initialCapital: number,
         *   monthlyDCA: number,
         *   dcaDefer: { enabled, indicator, targetCode },
         *   fees: { KR, US, COIN },
         *   riskFreeRate: number
         * }
         * @returns { dailySeries, trades, totalFees, totalInvested }
         */
        run: function (config) {
            var stocks = config.stocks;
            var data = config.stockData;
            var allDates = config.commonDates.filter(function (d) { return d >= config.startDate && d <= config.endDate; });
            if (allDates.length === 0) return null;

            // 워밍업 포함 전체 날짜 (지표 계산용)
            var fullDates = config.commonDates;

            // 종목별 종가 배열 (fullDates 기준)
            var closesMap = {};
            stocks.forEach(function (s) {
                closesMap[s.code] = fullDates.map(function (d) {
                    return data[s.code] && data[s.code].ohlcv[d] ? data[s.code].ohlcv[d].c : null;
                });
            });

            // 시그널 기반: 종목별 시그널 계산
            var signalMap = {};
            if (config.strategy === 'signal' && config.signalRules && config.signalRules.length > 0) {
                // 종목별로 규칙 그룹핑
                var rulesByTarget = {};
                config.signalRules.forEach(function (rule) {
                    var target = rule.targetCode || stocks[0].code;
                    if (!rulesByTarget[target]) rulesByTarget[target] = [];
                    rulesByTarget[target].push(rule);
                });

                Object.keys(rulesByTarget).forEach(function (code) {
                    if (closesMap[code]) {
                        signalMap[code] = SignalGenerator.generate(
                            closesMap[code], rulesByTarget[code], config.signalCombine || 'or'
                        );
                    }
                });
            }

            // DCA 유예 시그널 계산
            var dcaDeferSignals = null;
            if (config.dcaDefer && config.dcaDefer.enabled) {
                var deferCode = config.dcaDefer.targetCode || stocks[0].code;
                var deferCloses = closesMap[deferCode] || closesMap[stocks[0].code];
                dcaDeferSignals = SignalGenerator.generateDCADefer(deferCloses, config.dcaDefer.indicator);
            }

            // 시뮬레이션 상태
            var cash = config.initialCapital || 0;
            var holdings = {}; // code → 보유수량 (소수점 허용)
            stocks.forEach(function (s) { holdings[s.code] = 0; });
            var totalFees = 0;
            var totalInvested = config.initialCapital || 0;
            var deferredCash = 0; // 유예된 DCA 금액
            var trades = [];
            var dailySeries = [];
            var lastDCAMonth = null;
            var lastRebalanceDate = null;

            // fullDates에서 startDate의 인덱스 찾기
            var startIdx = fullDates.indexOf(allDates[0]);
            if (startIdx < 0) startIdx = 0;

            // 초기 매수 (Buy & Hold, 리밸런싱)
            if (config.strategy !== 'signal' && cash > 0) {
                var firstDate = allDates[0];
                PortfolioSimulator._buyByWeight(stocks, data, firstDate, holdings, config.fees, function (fee) { totalFees += fee; }, cash, trades);
                cash = 0;
            }

            // 일별 루프
            for (var di = 0; di < allDates.length; di++) {
                var date = allDates[di];
                var fullIdx = fullDates.indexOf(date);
                var curMonth = date.substring(0, 7);

                // 1) DCA: 월 첫 거래일 현금 주입
                if (config.monthlyDCA > 0 && curMonth !== lastDCAMonth) {
                    lastDCAMonth = curMonth;
                    var shouldDefer = dcaDeferSignals && fullIdx >= 0 && dcaDeferSignals[fullIdx];
                    if (shouldDefer) {
                        deferredCash += config.monthlyDCA;
                    } else {
                        var dcaAmount = config.monthlyDCA + deferredCash;
                        deferredCash = 0;
                        cash += dcaAmount;
                        totalInvested += dcaAmount;

                        // DCA 금액으로 즉시 매수 (buy & hold / rebalance 전략)
                        if (config.strategy !== 'signal' && cash > 0) {
                            PortfolioSimulator._buyByWeight(stocks, data, date, holdings, config.fees, function (fee) { totalFees += fee; }, cash, trades);
                            cash = 0;
                        }
                    }
                }

                // DCA 유예 해제 체크 (월 첫 거래일 아닌데 유예 풀릴 때)
                if (deferredCash > 0 && dcaDeferSignals && fullIdx >= 0 && !dcaDeferSignals[fullIdx]) {
                    cash += deferredCash + config.monthlyDCA * 0; // 누적분만
                    totalInvested += deferredCash;
                    var releasedCash = deferredCash;
                    deferredCash = 0;
                    if (config.strategy !== 'signal' && releasedCash > 0) {
                        PortfolioSimulator._buyByWeight(stocks, data, date, holdings, config.fees, function (fee) { totalFees += fee; }, releasedCash, trades);
                        cash -= releasedCash;
                        if (cash < 0) cash = 0;
                    }
                }

                // 2) 전략별 매매
                if (config.strategy === 'rebalance') {
                    if (PortfolioSimulator._shouldRebalance(date, lastRebalanceDate, config.rebalancePeriod)) {
                        lastRebalanceDate = date;
                        var totalValue = cash + PortfolioSimulator._portfolioValue(stocks, data, date, holdings);
                        // 전량 매도 후 비중대로 재매수
                        stocks.forEach(function (s) {
                            if (holdings[s.code] > 0) {
                                var price = data[s.code] && data[s.code].ohlcv[date] ? data[s.code].ohlcv[date].c : 0;
                                var sellValue = holdings[s.code] * price;
                                var fee = sellValue * PortfolioSimulator._getFeeRate(s.market, config.fees);
                                cash += sellValue - fee;
                                totalFees += fee;
                                trades.push({ date: date, code: s.code, type: 'sell', qty: holdings[s.code], price: price, fee: fee });
                                holdings[s.code] = 0;
                            }
                        });
                        PortfolioSimulator._buyByWeight(stocks, data, date, holdings, config.fees, function (fee) { totalFees += fee; }, cash, trades);
                        cash = 0;
                    }
                } else if (config.strategy === 'signal') {
                    stocks.forEach(function (s) {
                        var sig = signalMap[s.code];
                        if (!sig) return;
                        var signal = sig[fullIdx];
                        var price = data[s.code] && data[s.code].ohlcv[date] ? data[s.code].ohlcv[date].c : 0;
                        if (price <= 0) return;
                        var feeRate = PortfolioSimulator._getFeeRate(s.market, config.fees);

                        if (signal === 'buy' && cash > 0) {
                            var allocCash = cash * (s.weight / 100);
                            var fee = allocCash * feeRate;
                            var qty = (allocCash - fee) / price;
                            if (qty > 0) {
                                holdings[s.code] += qty;
                                cash -= allocCash;
                                totalFees += fee;
                                trades.push({ date: date, code: s.code, type: 'buy', qty: qty, price: price, fee: fee });
                            }
                        } else if (signal === 'sell' && holdings[s.code] > 0) {
                            var sellQty = holdings[s.code];
                            var sellValue = sellQty * price;
                            var fee = sellValue * feeRate;
                            cash += sellValue - fee;
                            totalFees += fee;
                            holdings[s.code] = 0;
                            trades.push({ date: date, code: s.code, type: 'sell', qty: sellQty, price: price, fee: fee });
                        }
                    });

                    // 시그널 전략에서 DCA 금액 투입
                    if (cash > 0 && di === 0) {
                        PortfolioSimulator._buyByWeight(stocks, data, date, holdings, config.fees, function (fee) { totalFees += fee; }, cash, trades);
                        cash = 0;
                    }
                }

                // 3) 일별 가치 기록
                var pv = cash + PortfolioSimulator._portfolioValue(stocks, data, date, holdings);
                dailySeries.push({
                    date: date,
                    value: pv,
                    cash: cash,
                    invested: totalInvested
                });
            }

            return {
                dailySeries: dailySeries,
                trades: trades,
                totalFees: totalFees,
                totalInvested: totalInvested
            };
        },

        _buyByWeight: function (stocks, data, date, holdings, fees, onFee, cashAmount, trades) {
            stocks.forEach(function (s) {
                var price = data[s.code] && data[s.code].ohlcv[date] ? data[s.code].ohlcv[date].c : 0;
                if (price <= 0) return;
                var allocCash = cashAmount * (s.weight / 100);
                var feeRate = PortfolioSimulator._getFeeRate(s.market, fees);
                var fee = allocCash * feeRate;
                var qty = (allocCash - fee) / price;
                if (qty > 0) {
                    holdings[s.code] += qty;
                    onFee(fee);
                    trades.push({ date: date, code: s.code, type: 'buy', qty: qty, price: price, fee: fee });
                }
            });
        },

        _portfolioValue: function (stocks, data, date, holdings) {
            var val = 0;
            stocks.forEach(function (s) {
                var price = data[s.code] && data[s.code].ohlcv[date] ? data[s.code].ohlcv[date].c : 0;
                val += holdings[s.code] * price;
            });
            return val;
        },

        _getFeeRate: function (market, fees) {
            if (market === 'COIN') return (fees.COIN || 0.015) / 100;
            if (market === 'US' || market === 'NYSE' || market === 'NASDAQ' || market === 'AMEX') return (fees.US || 0.2) / 100;
            return (fees.KR || 0.015) / 100;
        },

        _shouldRebalance: function (date, lastDate, period) {
            if (!lastDate) return false; // 첫날은 이미 초기 매수 완료
            var d = parseDate(date);
            var ld = parseDate(lastDate);
            var diffMs = d - ld;
            var diffDays = diffMs / 86400000;
            switch (period) {
                case 'monthly': return d.getMonth() !== ld.getMonth() || d.getFullYear() !== ld.getFullYear();
                case 'quarterly': return Math.floor(d.getMonth() / 3) !== Math.floor(ld.getMonth() / 3) || d.getFullYear() !== ld.getFullYear();
                case 'semiannual': return Math.floor(d.getMonth() / 6) !== Math.floor(ld.getMonth() / 6) || d.getFullYear() !== ld.getFullYear();
                case 'annual': return d.getFullYear() !== ld.getFullYear();
                default: return false;
            }
        }
    };

    /* =========================================
       메트릭 계산기 — MetricsCalculator
       ========================================= */
    var MetricsCalculator = {
        totalReturn: function (series) {
            if (series.length < 2) return 0;
            var last = series[series.length - 1];
            return ((last.value - last.invested) / last.invested) * 100;
        },

        cagr: function (series) {
            if (series.length < 2) return 0;
            var first = series[0];
            var last = series[series.length - 1];
            var years = (parseDate(last.date) - parseDate(first.date)) / (365.25 * 86400000);
            if (years <= 0 || last.invested <= 0) return 0;
            // 적립식의 경우 CAGR 근사: 최종가치 / 총투자로 계산
            return (Math.pow(last.value / last.invested, 1 / years) - 1) * 100;
        },

        maxDrawdown: function (series) {
            var peak = -Infinity;
            var maxDD = 0;
            for (var i = 0; i < series.length; i++) {
                if (series[i].value > peak) peak = series[i].value;
                var dd = (peak - series[i].value) / peak * 100;
                if (dd > maxDD) maxDD = dd;
            }
            return maxDD;
        },

        sharpeRatio: function (series, riskFreeRate) {
            var dailyReturns = MetricsCalculator._dailyReturns(series);
            if (dailyReturns.length < 2) return 0;
            var rf = (riskFreeRate || 3) / 100 / 252;
            var excessReturns = dailyReturns.map(function (r) { return r - rf; });
            var mean = excessReturns.reduce(function (a, b) { return a + b; }, 0) / excessReturns.length;
            var variance = excessReturns.reduce(function (a, b) { return a + Math.pow(b - mean, 2); }, 0) / excessReturns.length;
            var std = Math.sqrt(variance);
            if (std === 0) return 0;
            return (mean / std) * Math.sqrt(252);
        },

        sortinoRatio: function (series, riskFreeRate) {
            var dailyReturns = MetricsCalculator._dailyReturns(series);
            if (dailyReturns.length < 2) return 0;
            var rf = (riskFreeRate || 3) / 100 / 252;
            var excessReturns = dailyReturns.map(function (r) { return r - rf; });
            var mean = excessReturns.reduce(function (a, b) { return a + b; }, 0) / excessReturns.length;
            var downside = excessReturns.filter(function (r) { return r < 0; });
            if (downside.length === 0) return mean > 0 ? Infinity : 0;
            var downVariance = downside.reduce(function (a, b) { return a + b * b; }, 0) / excessReturns.length;
            var downStd = Math.sqrt(downVariance);
            if (downStd === 0) return 0;
            return (mean / downStd) * Math.sqrt(252);
        },

        annualReturns: function (series) {
            if (series.length < 2) return [];
            var years = {};
            series.forEach(function (d) {
                var y = d.date.substring(0, 4);
                if (!years[y]) years[y] = { first: d, last: d, values: [] };
                years[y].last = d;
                years[y].values.push(d);
            });
            var result = [];
            Object.keys(years).sort().forEach(function (y) {
                var yr = years[y];
                var ret = yr.last.invested > 0 ? ((yr.last.value - yr.last.invested) / yr.last.invested * 100) : 0;
                // 연중 MDD
                var peak = -Infinity, mdd = 0;
                yr.values.forEach(function (d) {
                    if (d.value > peak) peak = d.value;
                    var dd = (peak - d.value) / peak * 100;
                    if (dd > mdd) mdd = dd;
                });
                result.push({
                    year: y,
                    returnPct: ret,
                    invested: yr.last.invested,
                    value: yr.last.value,
                    mdd: mdd
                });
            });
            return result;
        },

        _dailyReturns: function (series) {
            var returns = [];
            for (var i = 1; i < series.length; i++) {
                if (series[i - 1].value > 0) {
                    returns.push((series[i].value - series[i - 1].value) / series[i - 1].value);
                }
            }
            return returns;
        }
    };

    /* =========================================
       차트 렌더러 — BacktestChart
       ========================================= */
    var BacktestChart = {
        render: function (series, benchmarkSeries) {
            var ctx = document.getElementById('backtestChart');
            if (!ctx) return;

            if (backtestChart) {
                backtestChart.destroy();
                backtestChart = null;
            }

            var labels = series.map(function (d) { return d.date; });
            var portfolioReturns = series.map(function (d) {
                return d.invested > 0 ? ((d.value - d.invested) / d.invested * 100) : 0;
            });
            var investedLine = series.map(function (d) {
                return d.invested > 0 ? 0 : 0; // 투자 원금선 (0% 기준선)
            });

            var datasets = [
                {
                    label: '포트폴리오 수익률',
                    data: portfolioReturns,
                    borderColor: 'rgb(59, 130, 246)',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    borderWidth: 2,
                    pointRadius: 0,
                    fill: true,
                    tension: 0.1
                },
                {
                    label: '',
                    data: investedLine,
                    borderColor: 'rgba(150, 150, 150, 0.5)',
                    borderWidth: 1,
                    borderDash: [5, 5],
                    pointRadius: 0,
                    fill: false,
                    hidden: false
                }
            ];

            if (benchmarkSeries && benchmarkSeries.length > 0) {
                var bmkMap = {};
                benchmarkSeries.forEach(function (d) { bmkMap[d.date] = d.returnPct; });
                // carry-forward: 날짜 불일치 시 직전 값 사용 (KR/US 거래일 차이 보정)
                var lastBmkVal = 0;
                var bmkReturns = labels.map(function (d) {
                    if (bmkMap[d] !== undefined) lastBmkVal = bmkMap[d];
                    return lastBmkVal;
                });
                datasets.push({
                    label: '벤치마크 수익률',
                    data: bmkReturns,
                    borderColor: 'rgb(249, 115, 22)',
                    backgroundColor: 'rgba(249, 115, 22, 0.05)',
                    borderWidth: 2,
                    borderDash: [4, 4],
                    pointRadius: 0,
                    fill: false,
                    tension: 0.1
                });
            }

            var rootStyle = getComputedStyle(document.documentElement);
            var textColor = rootStyle.getPropertyValue('--text-secondary').trim() || '#888';
            var gridColor = rootStyle.getPropertyValue('--border-color').trim() || '#333';

            backtestChart = new Chart(ctx, {
                type: 'line',
                data: { labels: labels, datasets: datasets },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: {
                        mode: 'index',
                        intersect: false
                    },
                    plugins: {
                        legend: {
                            display: true,
                            labels: {
                                color: textColor,
                                filter: function (item) { return item.text !== ''; }
                            }
                        },
                        tooltip: {
                            callbacks: {
                                label: function (ctx) {
                                    if (!ctx.dataset.label) return null;
                                    return ctx.dataset.label + ': ' + formatPercent(ctx.parsed.y);
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            ticks: {
                                color: textColor,
                                maxTicksLimit: 12,
                                maxRotation: 0
                            },
                            grid: { color: gridColor }
                        },
                        y: {
                            ticks: {
                                color: textColor,
                                callback: function (v) { return v.toFixed(1) + '%'; }
                            },
                            grid: { color: gridColor }
                        }
                    }
                }
            });
        }
    };

    /* =========================================
       UI 컨트롤러
       ========================================= */

    // 종목 검색 — 자동완성
    function initStockSearch(inputId, resultsId, onSelect) {
        var input = document.getElementById(inputId);
        var resultsDiv = document.getElementById(resultsId);
        if (!input || !resultsDiv) return;
        var debounce = null;

        input.addEventListener('input', function () {
            clearTimeout(debounce);
            var q = input.value.trim();
            if (q.length < 1) { resultsDiv.style.display = 'none'; return; }
            debounce = setTimeout(function () {
                fetch('/stocks/api/search?q=' + encodeURIComponent(q) + '&limit=10', {
                    headers: { 'X-Requested-With': 'XMLHttpRequest' }
                })
                    .then(function (r) { return r.json(); })
                    .then(function (json) {
                        if (!json.success || !json.data || json.data.length === 0) {
                            resultsDiv.innerHTML = '<div class="search-empty">검색 결과 없음</div>';
                            resultsDiv.style.display = 'block';
                            return;
                        }
                        var html = '';
                        json.data.forEach(function (s) {
                            var market = s.stock_type === 'COIN' ? 'COIN' : (
                                ['NYSE', 'NASDAQ', 'AMEX'].indexOf(s.stock_market) >= 0 ? 'US' : 'KR'
                            );
                            html += '<div class="search-result-item" data-code="' + s.stock_code +
                                '" data-name="' + (s.stock_name_kr || s.stock_code) +
                                '" data-market="' + market + '">' +
                                '<span class="sr-name">' + (s.stock_name_kr || s.stock_code) + '</span>' +
                                '<span class="sr-code">' + s.stock_code + '</span>' +
                                '<span class="sr-market badge-' + market.toLowerCase() + '">' + market + '</span>' +
                                '</div>';
                        });
                        resultsDiv.innerHTML = html;
                        resultsDiv.style.display = 'block';

                        resultsDiv.querySelectorAll('.search-result-item').forEach(function (item) {
                            item.addEventListener('click', function () {
                                onSelect({
                                    code: item.dataset.code,
                                    name: item.dataset.name,
                                    market: item.dataset.market
                                });
                                input.value = '';
                                resultsDiv.style.display = 'none';
                            });
                        });
                    });
            }, 300);
        });

        // 외부 클릭 시 드롭다운 닫기
        document.addEventListener('click', function (e) {
            if (!input.contains(e.target) && !resultsDiv.contains(e.target)) {
                resultsDiv.style.display = 'none';
            }
        });
    }

    // 포트폴리오 종목 렌더링
    function renderPortfolio() {
        var container = document.getElementById('selectedStocks');
        if (!container) return;
        if (portfolio.length === 0) {
            container.innerHTML = '<p class="empty-hint">종목을 검색하여 추가하세요 (최대 10개)</p>';
            return;
        }
        var html = '';
        portfolio.forEach(function (s, idx) {
            html += '<div class="portfolio-stock-item">' +
                '<span class="ps-name">' + s.name + '</span>' +
                '<span class="ps-code">' + s.code + '</span>' +
                '<span class="ps-market badge-' + s.market.toLowerCase() + '">' + s.market + '</span>' +
                '<div class="ps-weight-wrap">' +
                '<input type="number" class="backtest-input ps-weight" data-idx="' + idx + '" value="' + s.weight + '" min="0" max="100" step="1">' +
                '<span class="input-unit">%</span>' +
                '</div>' +
                '<button type="button" class="btn btn-sm btn-danger ps-remove" data-idx="' + idx + '">&times;</button>' +
                '</div>';
        });
        var totalWeight = portfolio.reduce(function (a, b) { return a + b.weight; }, 0);
        html += '<div class="portfolio-weight-total' + (Math.abs(totalWeight - 100) > 0.01 ? ' weight-warning' : '') + '">' +
            '합계: ' + totalWeight.toFixed(1) + '% ' +
            (Math.abs(totalWeight - 100) > 0.01 ? '<span class="weight-warn-text">(100%가 되어야 합니다)</span>' : '<span class="weight-ok">✓</span>') +
            ' <button type="button" class="btn btn-sm btn-outline" id="equalizeWeights">균등 배분</button>' +
            '</div>';
        container.innerHTML = html;

        // 비중 변경 이벤트
        container.querySelectorAll('.ps-weight').forEach(function (inp) {
            inp.addEventListener('change', function () {
                var idx = parseInt(this.dataset.idx);
                portfolio[idx].weight = parseFloat(this.value) || 0;
                renderPortfolio();
                updateSignalTargets();
            });
        });
        // 삭제 이벤트
        container.querySelectorAll('.ps-remove').forEach(function (btn) {
            btn.addEventListener('click', function () {
                portfolio.splice(parseInt(this.dataset.idx), 1);
                renderPortfolio();
                updateSignalTargets();
            });
        });
        // 균등 배분
        var eqBtn = document.getElementById('equalizeWeights');
        if (eqBtn) {
            eqBtn.addEventListener('click', function () {
                var n = portfolio.length;
                var base = Math.floor(10000 / n); // 정수 기반 (10000 = 100.00%)
                var remainder = 10000 - base * n;
                portfolio.forEach(function (s, i) {
                    s.weight = (base + (i < remainder ? 1 : 0)) / 100;
                });
                renderPortfolio();
            });
        }
    }

    // 시그널 타겟 옵션 업데이트
    function updateSignalTargets() {
        document.querySelectorAll('.signal-target').forEach(function (sel) {
            var currentVal = sel.value;
            sel.innerHTML = '';
            portfolio.forEach(function (s) {
                var opt = document.createElement('option');
                opt.value = s.code;
                opt.textContent = s.name + ' (' + s.code + ')';
                sel.appendChild(opt);
            });
            if (currentVal) sel.value = currentVal;
        });
    }

    // 시그널 규칙 추가
    function addSignalRule() {
        var container = document.getElementById('signalRules');
        var template = document.getElementById('signalRuleTemplate');
        if (!container || !template) return;
        var clone = template.content.cloneNode(true);
        container.appendChild(clone);
        updateSignalTargets();
        // 삭제 버튼
        container.querySelectorAll('.signal-remove').forEach(function (btn) {
            btn.onclick = function () { btn.closest('.signal-rule').remove(); };
        });
    }

    // 전략 탭 전환
    function initStrategyTabs() {
        document.querySelectorAll('.strategy-tab').forEach(function (tab) {
            tab.addEventListener('click', function () {
                document.querySelectorAll('.strategy-tab').forEach(function (t) { t.classList.remove('active'); });
                tab.classList.add('active');
                var strategy = tab.dataset.strategy;
                document.getElementById('rebalanceConfig').style.display = strategy === 'rebalance' ? '' : 'none';
                document.getElementById('signalConfig').style.display = strategy === 'signal' ? '' : 'none';
            });
        });
    }

    // DCA 유예 토글
    function initDCADefer() {
        var cb = document.getElementById('dcaDeferEnabled');
        var cfg = document.getElementById('dcaDeferConfig');
        if (cb && cfg) {
            cb.addEventListener('change', function () {
                cfg.style.display = cb.checked ? '' : 'none';
            });
        }
    }

    // 벤치마크 렌더링
    function renderBenchmark() {
        var container = document.getElementById('selectedBenchmark');
        if (!container) return;
        if (!benchmark) { container.innerHTML = ''; return; }
        container.innerHTML = '<div class="benchmark-item">' +
            '<span class="ps-name">' + benchmark.name + '</span>' +
            '<span class="ps-code">' + benchmark.code + '</span>' +
            '<span class="ps-market badge-' + benchmark.market.toLowerCase() + '">' + benchmark.market + '</span>' +
            '<button type="button" class="btn btn-sm btn-danger bmk-remove">&times;</button>' +
            '</div>';
        container.querySelector('.bmk-remove').addEventListener('click', function () {
            benchmark = null;
            renderBenchmark();
        });
    }

    // 결과 표시
    function displayResults(result, benchmarkResult) {
        var panel = document.getElementById('backtestResults');
        panel.style.display = '';

        var series = result.dailySeries;
        var riskFreeRate = parseFloat(document.getElementById('riskFreeRate').value) || 3;

        // 지표 카드
        var totalRet = MetricsCalculator.totalReturn(series);
        var cagr = MetricsCalculator.cagr(series);
        var mdd = MetricsCalculator.maxDrawdown(series);
        var sharpe = MetricsCalculator.sharpeRatio(series, riskFreeRate);
        var sortino = MetricsCalculator.sortinoRatio(series, riskFreeRate);

        var annualsForAvg = MetricsCalculator.annualReturns(series);
        var avgAnnual = annualsForAvg.length > 0 ? annualsForAvg.reduce(function(s, a) { return s + a.returnPct; }, 0) / annualsForAvg.length : 0;

        document.getElementById('metricTotalReturn').textContent = formatPercent(totalRet);
        document.getElementById('metricTotalReturn').className = 'metric-value ' + (totalRet >= 0 ? 'positive' : 'negative');
        document.getElementById('metricAvgAnnual').textContent = formatPercent(avgAnnual);
        document.getElementById('metricAvgAnnual').className = 'metric-value ' + (avgAnnual >= 0 ? 'positive' : 'negative');
        document.getElementById('metricCAGR').textContent = formatPercent(cagr);
        document.getElementById('metricCAGR').className = 'metric-value ' + (cagr >= 0 ? 'positive' : 'negative');
        document.getElementById('metricMDD').textContent = formatPercent(-mdd);
        document.getElementById('metricMDD').className = 'metric-value negative';
        document.getElementById('metricSharpe').textContent = sharpe === Infinity ? '∞' : sharpe.toFixed(2);
        document.getElementById('metricSortino').textContent = sortino === Infinity ? '∞' : sortino.toFixed(2);
        document.getElementById('metricTotalFees').textContent = formatCurrency(result.totalFees);

        // 차트 — 벤치마크도 동일 DCA 시뮬레이션 결과 사용
        var bmkSeries = null;
        if (benchmarkResult && benchmarkResult.dailySeries && benchmarkResult.dailySeries.length > 0) {
            bmkSeries = benchmarkResult.dailySeries.map(function (d) {
                return {
                    date: d.date,
                    returnPct: d.invested > 0 ? ((d.value - d.invested) / d.invested * 100) : 0
                };
            });
        }
        BacktestChart.render(series, bmkSeries);

        // 연도별 수익률 테이블
        var annuals = MetricsCalculator.annualReturns(series);
        var tbody = document.querySelector('#annualReturnsTable tbody');
        tbody.innerHTML = '';
        annuals.forEach(function (a) {
            var tr = document.createElement('tr');
            tr.innerHTML = '<td>' + a.year + '</td>' +
                '<td class="' + (a.returnPct >= 0 ? 'positive' : 'negative') + '">' + formatPercent(a.returnPct) + '</td>' +
                '<td>' + formatCurrency(a.invested) + '</td>' +
                '<td>' + formatCurrency(a.value) + '</td>' +
                '<td class="negative">' + formatPercent(-a.mdd) + '</td>';
            tbody.appendChild(tr);
        });

        // 거래 요약
        var buys = result.trades.filter(function (t) { return t.type === 'buy'; });
        var sells = result.trades.filter(function (t) { return t.type === 'sell'; });
        document.getElementById('tradeTotalCount').textContent = formatNumber(result.trades.length);
        document.getElementById('tradeBuyCount').textContent = formatNumber(buys.length);
        document.getElementById('tradeSellCount').textContent = formatNumber(sells.length);
        document.getElementById('tradeTotalInvested').textContent = formatCurrency(result.totalInvested);
    }

    // 설정 수집
    function collectConfig() {
        if (portfolio.length === 0) {
            alert('종목을 1개 이상 추가하세요.');
            return null;
        }
        var totalWeight = portfolio.reduce(function (a, b) { return a + b.weight; }, 0);
        if (Math.abs(totalWeight - 100) > 0.5) {
            alert('종목 비중 합계가 100%여야 합니다. (현재: ' + totalWeight.toFixed(1) + '%)');
            return null;
        }
        var startDate = document.getElementById('startDate').value;
        var endDate = document.getElementById('endDate').value;
        if (!startDate || !endDate || startDate >= endDate) {
            alert('유효한 기간을 설정하세요.');
            return null;
        }

        var activeTab = document.querySelector('.strategy-tab.active');
        var strategy = activeTab ? activeTab.dataset.strategy : 'buyhold';

        // 시그널 규칙 수집
        var signalRules = [];
        if (strategy === 'signal') {
            document.querySelectorAll('.signal-rule').forEach(function (rule) {
                var indicator = rule.querySelector('.signal-indicator').value;
                var target = rule.querySelector('.signal-target').value;
                signalRules.push({ indicator: indicator, targetCode: target });
            });
            if (signalRules.length === 0) {
                alert('시그널 기반 전략에는 최소 1개의 규칙이 필요합니다.');
                return null;
            }
        }

        return {
            stocks: portfolio.map(function (s) { return { code: s.code, market: s.market, weight: s.weight }; }),
            startDate: startDate,
            endDate: endDate,
            strategy: strategy,
            rebalancePeriod: document.getElementById('rebalancePeriod').value,
            signalRules: signalRules,
            signalCombine: document.getElementById('signalCombine').value,
            initialCapital: (parseFloat(document.getElementById('initialCapital').value) || 0) * 10000,
            monthlyDCA: (parseFloat(document.getElementById('monthlyDCA').value) || 0) * 10000,
            dcaDefer: {
                enabled: document.getElementById('dcaDeferEnabled').checked,
                indicator: document.getElementById('dcaDeferIndicator').value,
                targetCode: document.getElementById('dcaDeferTarget').value === 'benchmark' && benchmark ? benchmark.code : (portfolio[0] ? portfolio[0].code : '')
            },
            fees: {
                KR: parseFloat(document.getElementById('feeKR').value) || 0,
                US: parseFloat(document.getElementById('feeUS').value) || 0,
                COIN: parseFloat(document.getElementById('feeCOIN').value) || 0
            },
            riskFreeRate: parseFloat(document.getElementById('riskFreeRate').value) || 3
        };
    }

    // 백테스트 실행
    function runBacktest() {
        var config = collectConfig();
        if (!config) return;

        var btn = document.getElementById('runBacktest');
        btn.disabled = true;
        btn.textContent = '실행 중...';

        var progressDiv = document.getElementById('backtestProgress');
        var progressFill = document.getElementById('progressFill');
        var progressText = document.getElementById('progressText');
        var resultsPanel = document.getElementById('backtestResults');
        progressDiv.style.display = '';

        BacktestData.fetchAll(
            config.stocks,
            benchmark,
            config.startDate,
            config.endDate,
            function (loaded, total) {
                var pct = Math.round(loaded / total * 100);
                progressFill.style.width = pct + '%';
                progressText.textContent = '데이터 로딩 중... (' + loaded + '/' + total + ')';
            }
        ).then(function (allData) {
            if (!allData || allData.commonDates.length === 0) {
                alert('선택한 기간에 공통 데이터가 없습니다. 기간을 조정하거나 다른 종목을 선택하세요.');
                btn.disabled = false;
                btn.textContent = '백테스트 실행';
                progressDiv.style.display = 'none';
                return;
            }

            progressText.textContent = '시뮬레이션 계산 중...';
            progressFill.style.width = '100%';

            // 약간의 지연으로 UI 업데이트 반영
            setTimeout(function () {
                config.stockData = allData.stockData;
                config.commonDates = allData.commonDates;

                var result = PortfolioSimulator.run(config);
                if (!result || result.dailySeries.length === 0) {
                    alert('시뮬레이션 결과가 없습니다. 기간에 데이터가 충분한지 확인하세요.');
                    btn.disabled = false;
                    btn.textContent = '백테스트 실행';
                    progressDiv.style.display = 'none';
                    return;
                }

                // 벤치마크: 동일 DCA/수수료로 Buy & Hold 시뮬레이션
                // 포트폴리오의 실제 첫 거래일로 시작일을 정렬하여 둘 다 0%에서 시작
                var bmkResult = null;
                if (allData.benchmarkData && benchmark) {
                    var portfolioFirstDate = result.dailySeries[0].date;
                    var bmkStockData = {};
                    bmkStockData[benchmark.code] = allData.benchmarkData;
                    var bmkConfig = {
                        stocks: [{ code: benchmark.code, market: benchmark.market, weight: 100 }],
                        stockData: bmkStockData,
                        commonDates: allData.benchmarkData.dates,
                        startDate: portfolioFirstDate,
                        endDate: config.endDate,
                        strategy: 'buyhold',
                        rebalancePeriod: 'quarterly',
                        signalRules: [],
                        signalCombine: 'or',
                        initialCapital: config.initialCapital,
                        monthlyDCA: config.monthlyDCA,
                        dcaDefer: { enabled: false },
                        fees: config.fees,
                        riskFreeRate: config.riskFreeRate
                    };
                    bmkResult = PortfolioSimulator.run(bmkConfig);
                }

                progressDiv.style.display = 'none';
                displayResults(result, bmkResult);

                btn.disabled = false;
                btn.textContent = '백테스트 실행';

                // 결과 패널로 스크롤
                document.getElementById('metricsCards').scrollIntoView({ behavior: 'smooth', block: 'start' });
            }, 50);
        }).catch(function (err) {
            console.error('백테스트 에러:', err);
            alert('데이터 로딩 중 오류가 발생했습니다.');
            btn.disabled = false;
            btn.textContent = '백테스트 실행';
            progressDiv.style.display = 'none';
        });
    }

    /* =========================================
       설정 저장/불러오기 (localStorage)
       ========================================= */
    var STORAGE_KEY = 'backtest_config_v1';

    function saveConfigToStorage() {
        var activeTab = document.querySelector('.strategy-tab.active');
        var signalRules = [];
        document.querySelectorAll('.signal-rule').forEach(function (rule) {
            signalRules.push({
                indicator: rule.querySelector('.signal-indicator').value,
                targetCode: rule.querySelector('.signal-target').value
            });
        });

        var data = {
            portfolio: portfolio.map(function (s) { return { code: s.code, name: s.name, market: s.market, weight: s.weight }; }),
            benchmark: benchmark ? { code: benchmark.code, name: benchmark.name, market: benchmark.market } : null,
            strategy: activeTab ? activeTab.dataset.strategy : 'buyhold',
            rebalancePeriod: document.getElementById('rebalancePeriod').value,
            signalRules: signalRules,
            signalCombine: document.getElementById('signalCombine').value,
            initialCapital: document.getElementById('initialCapital').value,
            monthlyDCA: document.getElementById('monthlyDCA').value,
            dcaDeferEnabled: document.getElementById('dcaDeferEnabled').checked,
            dcaDeferIndicator: document.getElementById('dcaDeferIndicator').value,
            dcaDeferTarget: document.getElementById('dcaDeferTarget').value,
            feeKR: document.getElementById('feeKR').value,
            feeUS: document.getElementById('feeUS').value,
            feeCOIN: document.getElementById('feeCOIN').value,
            startDate: document.getElementById('startDate').value,
            endDate: document.getElementById('endDate').value,
            riskFreeRate: document.getElementById('riskFreeRate').value,
            savedAt: new Date().toISOString()
        };

        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
            showSaveStatus('저장 완료');
        } catch (e) {
            alert('설정 저장에 실패했습니다.');
        }
    }

    function loadConfigFromStorage() {
        try {
            var raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) { alert('저장된 설정이 없습니다.'); return; }
            var data = JSON.parse(raw);

            // 포트폴리오 복원
            portfolio = (data.portfolio || []).map(function (s) {
                return { code: s.code, name: s.name, market: s.market, weight: s.weight };
            });
            renderPortfolio();

            // 벤치마크 복원
            benchmark = data.benchmark ? { code: data.benchmark.code, name: data.benchmark.name, market: data.benchmark.market } : null;
            renderBenchmark();

            // 전략 탭
            document.querySelectorAll('.strategy-tab').forEach(function (t) { t.classList.remove('active'); });
            var targetTab = document.querySelector('.strategy-tab[data-strategy="' + (data.strategy || 'buyhold') + '"]');
            if (targetTab) targetTab.classList.add('active');
            document.getElementById('rebalanceConfig').style.display = data.strategy === 'rebalance' ? '' : 'none';
            document.getElementById('signalConfig').style.display = data.strategy === 'signal' ? '' : 'none';

            // 필드 값 복원
            document.getElementById('rebalancePeriod').value = data.rebalancePeriod || 'quarterly';
            document.getElementById('signalCombine').value = data.signalCombine || 'or';
            document.getElementById('initialCapital').value = data.initialCapital || '1000';
            document.getElementById('monthlyDCA').value = data.monthlyDCA || '100';
            document.getElementById('dcaDeferEnabled').checked = !!data.dcaDeferEnabled;
            document.getElementById('dcaDeferConfig').style.display = data.dcaDeferEnabled ? '' : 'none';
            document.getElementById('dcaDeferIndicator').value = data.dcaDeferIndicator || 'macd_death';
            document.getElementById('dcaDeferTarget').value = data.dcaDeferTarget || 'first';
            document.getElementById('feeKR').value = data.feeKR || '0.015';
            document.getElementById('feeUS').value = data.feeUS || '0.2';
            document.getElementById('feeCOIN').value = data.feeCOIN || '0.015';
            if (data.startDate) document.getElementById('startDate').value = data.startDate;
            if (data.endDate) document.getElementById('endDate').value = data.endDate;
            document.getElementById('riskFreeRate').value = data.riskFreeRate || '3.0';

            // 시그널 규칙 복원
            document.getElementById('signalRules').innerHTML = '';
            (data.signalRules || []).forEach(function (rule) {
                addSignalRule();
                var rules = document.querySelectorAll('.signal-rule');
                var last = rules[rules.length - 1];
                last.querySelector('.signal-indicator').value = rule.indicator;
                updateSignalTargets();
                if (rule.targetCode) last.querySelector('.signal-target').value = rule.targetCode;
            });

            var savedDate = data.savedAt ? new Date(data.savedAt) : null;
            var timeStr = savedDate ? savedDate.toLocaleDateString('ko-KR') + ' ' + savedDate.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }) : '';
            showSaveStatus('불러옴 (' + timeStr + ')');
        } catch (e) {
            alert('설정 불러오기에 실패했습니다.');
        }
    }

    function clearStoredConfig() {
        localStorage.removeItem(STORAGE_KEY);
        showSaveStatus('삭제됨');
    }

    function showSaveStatus(msg) {
        var el = document.getElementById('saveStatus');
        if (!el) return;
        el.textContent = msg;
        el.style.opacity = '1';
        setTimeout(function () { el.style.opacity = '0'; }, 3000);
    }

    /* =========================================
       초기화
       ========================================= */
    function init() {
        // 종목 검색 초기화
        initStockSearch('stockSearchInput', 'stockSearchResults', function (stock) {
            if (portfolio.length >= MAX_STOCKS) { alert('최대 ' + MAX_STOCKS + '개까지 추가 가능합니다.'); return; }
            if (portfolio.some(function (s) { return s.code === stock.code; })) { alert('이미 추가된 종목입니다.'); return; }
            stock.weight = Math.round(100 / (portfolio.length + 1) * 100) / 100;
            // 기존 종목 비중 재조정
            var totalOld = portfolio.reduce(function (a, b) { return a + b.weight; }, 0);
            if (totalOld > 0) {
                var factor = (100 - stock.weight) / totalOld;
                portfolio.forEach(function (s) { s.weight = Math.round(s.weight * factor * 100) / 100; });
            }
            portfolio.push(stock);
            renderPortfolio();
            updateSignalTargets();
        });

        // 벤치마크 검색 초기화
        initStockSearch('benchmarkSearch', 'benchmarkSearchResults', function (stock) {
            benchmark = stock;
            renderBenchmark();
        });

        // 전략 탭
        initStrategyTabs();

        // DCA 유예
        initDCADefer();

        // 시그널 규칙 추가 버튼
        var addBtn = document.getElementById('addSignalRule');
        if (addBtn) addBtn.addEventListener('click', addSignalRule);

        // 실행 버튼
        var runBtn = document.getElementById('runBacktest');
        if (runBtn) runBtn.addEventListener('click', runBacktest);

        // 설정 저장/불러오기 버튼
        var saveBtn = document.getElementById('saveConfig');
        if (saveBtn) saveBtn.addEventListener('click', saveConfigToStorage);
        var loadBtn = document.getElementById('loadConfig');
        if (loadBtn) loadBtn.addEventListener('click', loadConfigFromStorage);
        var clearBtn = document.getElementById('clearConfig');
        if (clearBtn) clearBtn.addEventListener('click', function () {
            if (confirm('저장된 설정을 삭제하시겠습니까?')) clearStoredConfig();
        });

        // 저장된 설정이 있으면 자동 복원
        if (localStorage.getItem(STORAGE_KEY)) {
            loadConfigFromStorage();
        }
    }

    // DOM 준비 후 초기화
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
