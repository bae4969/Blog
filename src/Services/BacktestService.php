<?php

namespace Blog\Services;

use Blog\Models\Stock;

/**
 * 포트폴리오 백테스팅 시뮬레이터 (서버 사이드)
 *
 * JS backtest.js의 핵심 연산 로직을 PHP로 이식:
 * - Indicators: SMA, EMA, MACD, RSI, Bollinger Bands
 * - SignalGenerator: 규칙 기반 매매 시그널 생성
 * - PortfolioSimulator: 전략별 시뮬레이션 (buyhold, rebalance, signal)
 * - MetricsCalculator: 수익률·위험지표 계산
 */
class BacktestService
{
    private Stock $stockModel;
    private const WARMUP_DAYS = 60;

    /** CPU yield: N 반복마다 usleep 호출 */
    private const YIELD_INTERVAL = 200;
    /** CPU yield: usleep 시간 (마이크로초) */
    private const YIELD_USLEEP = 2000;
    /** 차트 데이터 최대 포인트 수 */
    private const MAX_CHART_POINTS = 500;
    /** 최대 시뮬레이션 기간 (년) */
    private const MAX_YEARS = 30;

    public function __construct()
    {
        $this->stockModel = new Stock();
    }

    /**
     * 백테스트 실행 메인 엔트리포인트
     *
     * @param array $config {
     *   stocks: [{code, market, weight}],
     *   benchmarks: [{code, market, name}],
     *   startDate, endDate: string,
     *   strategy: 'buyhold'|'rebalance'|'signal',
     *   rebalancePeriod: 'monthly'|'quarterly'|'semiannual'|'annual',
     *   signalRules: [{indicator, targetCode}],
     *   signalCombine: 'and'|'or',
     *   initialCapital: float,
     *   monthlyDCA: float,
     *   dcaDefer: {enabled: bool, indicator: string},
     *   fees: {KR: float, US: float, COIN: float},
     *   riskFreeRate: float
     * }
     * @return array|null
     */
    public function run(array $config): ?array
    {
        // 기간 제한 검증
        $startTs = strtotime($config['startDate']);
        $endTs = strtotime($config['endDate']);
        $years = ($endTs - $startTs) / (365.25 * 86400);
        if ($years > self::MAX_YEARS) {
            return null;
        }

        // 1) 캔들 데이터 조회 (DB 직접 접근)
        $fetchResult = $this->fetchAllCandles(
            $config['stocks'],
            $config['benchmarks'] ?? [],
            $config['startDate'],
            $config['endDate']
        );

        if ($fetchResult === null || empty($fetchResult['commonDates'])) {
            return null;
        }

        // 2) 포트폴리오 시뮬레이션 — array_merge 대신 참조로 전달
        $config['stockData'] = $fetchResult['stockData'];
        $config['commonDates'] = $fetchResult['commonDates'];
        $result = $this->simulate($config);
        if ($result === null || empty($result['dailySeries'])) {
            return null;
        }

        // 3) 메트릭 계산 (전체 dailySeries 기준)
        $riskFreeRate = $config['riskFreeRate'] ?? 3.0;
        $metrics = $this->calculateMetrics($result['dailySeries'], $riskFreeRate);
        $annualReturns = $this->annualReturns($result['dailySeries']);

        // 4) 벤치마크 시뮬레이션 — stockData는 벤치마크에서 불필요, 메모리 해제
        $benchmarkDataMap = $fetchResult['benchmarkDataMap'] ?? [];
        unset($fetchResult, $config['stockData']);

        $benchmarkResults = $this->simulateBenchmarks(
            $config,
            $result,
            $benchmarkDataMap,
            $riskFreeRate
        );
        unset($benchmarkDataMap);

        // 5) 거래 요약
        $buyCount = 0;
        $sellCount = 0;
        foreach ($result['trades'] as $t) {
            if ($t['type'] === 'buy') $buyCount++;
            else $sellCount++;
        }

        // 6) 차트용 dailySeries 다운샘플링 (메트릭은 이미 전체 데이터로 계산 완료)
        $chartSeries = $this->downsampleSeries($result['dailySeries'], self::MAX_CHART_POINTS);

        // 벤치마크 chartData도 다운샘플링
        foreach ($benchmarkResults as &$bmkItem) {
            if (!empty($bmkItem['chartData'])) {
                $bmkItem['chartData'] = $this->downsampleChartData($bmkItem['chartData'], self::MAX_CHART_POINTS);
            }
        }
        unset($bmkItem);

        // 7) TWR 정규화 랭킹 점수 (투자금/DCA 무관한 순수 전략 평가)
        $rankingResult = $this->calculateRankingScore($result['dailySeries'], $riskFreeRate);

        return [
            'dailySeries' => $chartSeries,
            'metrics' => $metrics,
            'annualReturns' => $annualReturns,
            'tradeSummary' => [
                'totalCount' => $buyCount + $sellCount,
                'buyCount' => $buyCount,
                'sellCount' => $sellCount,
                'totalInvested' => $result['totalInvested'],
                'totalFees' => $result['totalFees'],
            ],
            'benchmarks' => $benchmarkResults,
            'rankingScore' => $rankingResult['score'],
            'rankingGrade' => $rankingResult['grade'],
        ];
    }

    /* =========================================
       데이터 계층
       ========================================= */

    /**
     * 전체 종목의 일봉 데이터를 DB에서 직접 조회
     */
    private function fetchAllCandles(array $stocks, array $benchmarks, string $startDate, string $endDate): ?array
    {
        $warmStart = new \DateTime($startDate);
        $warmStart->modify('-' . (self::WARMUP_DAYS * 2) . ' days');
        $warmStartStr = $warmStart->format('Y-m-d') . ' 00:00:00';
        $endStr = $endDate . ' 23:59:00';

        $stockData = [];
        $benchmarkDataMap = [];

        // 주식 종목 캔들 조회 (종목 간 yield)
        foreach ($stocks as $idx => $s) {
            if ($idx > 0) usleep(self::YIELD_USLEEP);
            $data = $this->fetchSingleCandle($s['code'], $s['market'] ?? '', $warmStartStr, $endStr);
            $stockData[$s['code']] = $data;
        }

        // 벤치마크 종목 캔들 조회 (종목 간 yield)
        foreach ($benchmarks as $idx => $b) {
            usleep(self::YIELD_USLEEP);
            $data = $this->fetchSingleCandle($b['code'], $b['market'] ?? '', $warmStartStr, $endStr);
            $benchmarkDataMap[$b['code']] = $data;
        }

        return $this->buildResult($stockData, $benchmarkDataMap);
    }

    /**
     * 단일 종목의 일봉 데이터를 {dates[], ohlcv{date→{o,h,l,c,v}}} 구조로 변환
     */
    private function fetchSingleCandle(string $code, string $market, string $start, string $end): ?array
    {
        $candles = $this->stockModel->getCandleData($code, $start, $end, 15000, '1d', $market);
        if (empty($candles)) {
            return null;
        }

        $map = [];
        $dates = [];
        foreach ($candles as $c) {
            $d = explode(' ', $c['execution_datetime'])[0];
            if (!isset($map[$d])) {
                $map[$d] = [
                    'o' => (float)$c['execution_open'],
                    'h' => (float)$c['execution_max'],
                    'l' => (float)$c['execution_min'],
                    'c' => (float)$c['execution_close'],
                    'v' => (float)($c['execution_bid_volume'] ?? 0) + (float)($c['execution_ask_volume'] ?? 0) + (float)($c['execution_non_volume'] ?? 0),
                ];
                $dates[] = $d;
            }
        }
        sort($dates);
        return ['dates' => $dates, 'ohlcv' => $map];
    }

    /**
     * 공통 날짜 계산
     */
    private function buildResult(array $stockData, array $benchmarkDataMap): ?array
    {
        $dateSets = [];
        foreach ($stockData as $data) {
            if ($data !== null) {
                $dateSets[] = array_flip($data['dates']);
            }
        }
        if (empty($dateSets)) {
            return null;
        }

        $common = array_keys($dateSets[0]);
        for ($i = 1; $i < count($dateSets); $i++) {
            $common = array_filter($common, fn($d) => isset($dateSets[$i][$d]));
        }
        $common = array_values($common);
        sort($common);

        return [
            'stockData' => $stockData,
            'benchmarkDataMap' => $benchmarkDataMap,
            'commonDates' => $common,
        ];
    }

    /* =========================================
       지표 엔진 — Indicators
       ========================================= */

    private function sma(array $values, int $period): array
    {
        $result = [];
        $len = count($values);
        for ($i = 0; $i < $len; $i++) {
            if ($i > 0 && $i % self::YIELD_INTERVAL === 0) usleep(self::YIELD_USLEEP);
            if ($i < $period - 1) {
                $result[] = null;
                continue;
            }
            $sum = 0;
            $valid = true;
            for ($j = $i - $period + 1; $j <= $i; $j++) {
                if (!is_finite($values[$j] ?? NAN)) {
                    $valid = false;
                    break;
                }
                $sum += $values[$j];
            }
            $result[] = $valid ? $sum / $period : null;
        }
        return $result;
    }

    private function ema(array $values, int $period): array
    {
        $result = [];
        $k = 2.0 / ($period + 1);
        $prev = null;
        $len = count($values);
        for ($i = 0; $i < $len; $i++) {
            if ($values[$i] === null || !is_finite($values[$i])) {
                $result[] = null;
                continue;
            }
            if ($prev === null) {
                if ($i >= $period - 1) {
                    $sum = 0;
                    for ($j = $i - $period + 1; $j <= $i; $j++) {
                        $sum += $values[$j];
                    }
                    $prev = $sum / $period;
                    $result[] = $prev;
                } else {
                    $result[] = null;
                }
            } else {
                $prev = $values[$i] * $k + $prev * (1 - $k);
                $result[] = $prev;
            }
        }
        return $result;
    }

    private function macd(array $values, int $fast = 12, int $slow = 26, int $signal = 9): array
    {
        $emaFast = $this->ema($values, $fast);
        $emaSlow = $this->ema($values, $slow);
        $macdLine = [];
        $len = count($values);
        for ($i = 0; $i < $len; $i++) {
            if ($emaFast[$i] !== null && $emaSlow[$i] !== null && is_finite($emaFast[$i]) && is_finite($emaSlow[$i])) {
                $macdLine[] = $emaFast[$i] - $emaSlow[$i];
            } else {
                $macdLine[] = null;
            }
        }
        $signalLine = $this->ema(array_map(fn($v) => $v !== null ? $v : null, $macdLine), $signal);
        $histogram = [];
        for ($i = 0; $i < $len; $i++) {
            if ($macdLine[$i] !== null && $signalLine[$i] !== null && is_finite($macdLine[$i]) && is_finite($signalLine[$i])) {
                $histogram[] = $macdLine[$i] - $signalLine[$i];
            } else {
                $histogram[] = null;
            }
        }
        return ['macd' => $macdLine, 'signal' => $signalLine, 'histogram' => $histogram];
    }

    private function rsi(array $values, int $period = 14): array
    {
        $result = [];
        $gains = [];
        $losses = [];
        $avgGain = 0;
        $avgLoss = 0;
        $len = count($values);
        for ($i = 0; $i < $len; $i++) {
            if ($i === 0 || $values[$i] === null || $values[$i - 1] === null || !is_finite($values[$i]) || !is_finite($values[$i - 1])) {
                $result[] = null;
                $gains[] = 0;
                $losses[] = 0;
                continue;
            }
            $change = $values[$i] - $values[$i - 1];
            $gains[] = $change > 0 ? $change : 0;
            $losses[] = $change < 0 ? -$change : 0;

            if ($i < $period) {
                $result[] = null;
                continue;
            }
            if ($i === $period) {
                $avgGain = 0;
                $avgLoss = 0;
                for ($j = 1; $j <= $period; $j++) {
                    $avgGain += $gains[$j];
                    $avgLoss += $losses[$j];
                }
                $avgGain /= $period;
                $avgLoss /= $period;
            } else {
                $avgGain = ($avgGain * ($period - 1) + $gains[$i]) / $period;
                $avgLoss = ($avgLoss * ($period - 1) + $losses[$i]) / $period;
            }
            if ($avgLoss == 0) {
                $result[] = 100.0;
            } else {
                $result[] = 100 - (100 / (1 + $avgGain / $avgLoss));
            }
        }
        return $result;
    }

    private function bb(array $values, int $period = 20, float $stdMultiplier = 2.0): array
    {
        $upper = [];
        $middle = [];
        $lower = [];
        $len = count($values);
        for ($i = 0; $i < $len; $i++) {
            if ($i > 0 && $i % self::YIELD_INTERVAL === 0) usleep(self::YIELD_USLEEP);
            if ($i < $period - 1) {
                $upper[] = null;
                $middle[] = null;
                $lower[] = null;
                continue;
            }
            $win = [];
            $bad = false;
            for ($j = $i - $period + 1; $j <= $i; $j++) {
                if ($values[$j] === null || !is_finite($values[$j])) {
                    $bad = true;
                    break;
                }
                $win[] = $values[$j];
            }
            if ($bad) {
                $upper[] = null;
                $middle[] = null;
                $lower[] = null;
                continue;
            }
            $avg = array_sum($win) / $period;
            $variance = 0;
            foreach ($win as $w) {
                $variance += ($w - $avg) ** 2;
            }
            $std = sqrt($variance / $period);
            $middle[] = $avg;
            $upper[] = $avg + $std * $stdMultiplier;
            $lower[] = $avg - $std * $stdMultiplier;
        }
        return ['upper' => $upper, 'middle' => $middle, 'lower' => $lower];
    }

    /* =========================================
       시그널 생성기
       ========================================= */

    private function generateSignals(array $closes, array $rules, string $combine): array
    {
        $len = count($closes);
        if (empty($rules)) {
            return array_fill(0, $len, 'hold');
        }

        $ruleSignals = [];
        foreach ($rules as $rule) {
            $ruleSignals[] = $this->evalRule($closes, $rule);
        }

        $signals = [];
        for ($i = 0; $i < $len; $i++) {
            $buys = 0;
            $sells = 0;
            foreach ($ruleSignals as $rs) {
                if ($rs[$i] === 'buy') $buys++;
                elseif ($rs[$i] === 'sell') $sells++;
            }
            if ($combine === 'and') {
                if ($buys === count($ruleSignals)) $signals[] = 'buy';
                elseif ($sells === count($ruleSignals)) $signals[] = 'sell';
                else $signals[] = 'hold';
            } else {
                if ($buys > 0 && $sells === 0) $signals[] = 'buy';
                elseif ($sells > 0 && $buys === 0) $signals[] = 'sell';
                else $signals[] = 'hold';
            }
        }
        return $signals;
    }

    private function evalRule(array $closes, array $rule): array
    {
        $len = count($closes);
        $signals = array_fill(0, $len, 'hold');
        $ind = $rule['indicator'];

        if ($ind === 'bb_lower' || $ind === 'bb_upper') {
            $bb = $this->bb($closes, 20, 2);
            for ($i = 1; $i < $len; $i++) {
                if (!$this->isNum($closes[$i]) || !$this->isNum($bb['lower'][$i])) continue;
                if ($ind === 'bb_lower' && $closes[$i] < $bb['lower'][$i] && $closes[$i - 1] >= $bb['lower'][$i - 1]) {
                    $signals[$i] = 'buy';
                }
                if ($ind === 'bb_upper' && $closes[$i] > $bb['upper'][$i] && $closes[$i - 1] <= $bb['upper'][$i - 1]) {
                    $signals[$i] = 'sell';
                }
            }
        } elseif ($ind === 'macd_golden' || $ind === 'macd_death') {
            $m = $this->macd($closes);
            for ($i = 1; $i < $len; $i++) {
                if (!$this->isNum($m['macd'][$i]) || !$this->isNum($m['signal'][$i])) continue;
                if (!$this->isNum($m['macd'][$i - 1]) || !$this->isNum($m['signal'][$i - 1])) continue;
                $prev = $m['macd'][$i - 1] - $m['signal'][$i - 1];
                $curr = $m['macd'][$i] - $m['signal'][$i];
                if ($ind === 'macd_golden' && $prev <= 0 && $curr > 0) $signals[$i] = 'buy';
                if ($ind === 'macd_death' && $prev >= 0 && $curr < 0) $signals[$i] = 'sell';
            }
        } elseif ($ind === 'rsi_oversold' || $ind === 'rsi_overbought') {
            $rsi = $this->rsi($closes, 14);
            for ($i = 0; $i < $len; $i++) {
                if (!$this->isNum($rsi[$i])) continue;
                if ($ind === 'rsi_oversold' && $rsi[$i] < 30) $signals[$i] = 'buy';
                if ($ind === 'rsi_overbought' && $rsi[$i] > 70) $signals[$i] = 'sell';
            }
        } elseif ($ind === 'sma_golden' || $ind === 'sma_death') {
            $short5 = $this->sma($closes, 5);
            $long20 = $this->sma($closes, 20);
            for ($i = 1; $i < $len; $i++) {
                if (!$this->isNum($short5[$i]) || !$this->isNum($long20[$i])) continue;
                if (!$this->isNum($short5[$i - 1]) || !$this->isNum($long20[$i - 1])) continue;
                $prevDiff = $short5[$i - 1] - $long20[$i - 1];
                $currDiff = $short5[$i] - $long20[$i];
                if ($ind === 'sma_golden' && $prevDiff <= 0 && $currDiff > 0) $signals[$i] = 'buy';
                if ($ind === 'sma_death' && $prevDiff >= 0 && $currDiff < 0) $signals[$i] = 'sell';
            }
        }
        return $signals;
    }

    /**
     * DCA 유예 시그널 생성
     */
    private function generateDCADefer(array $closes, string $deferType): array
    {
        $len = count($closes);
        $deferred = array_fill(0, $len, false);
        if (empty($deferType) || $deferType === 'none') return $deferred;

        if ($deferType === 'macd_death') {
            $m = $this->macd($closes);
            $inDefer = false;
            for ($i = 1; $i < $len; $i++) {
                if (!$this->isNum($m['macd'][$i]) || !$this->isNum($m['signal'][$i]) ||
                    !$this->isNum($m['macd'][$i - 1]) || !$this->isNum($m['signal'][$i - 1])) {
                    $deferred[$i] = $inDefer;
                    continue;
                }
                $prev = $m['macd'][$i - 1] - $m['signal'][$i - 1];
                $curr = $m['macd'][$i] - $m['signal'][$i];
                if ($prev >= 0 && $curr < 0) $inDefer = true;
                if ($prev <= 0 && $curr > 0) $inDefer = false;
                $deferred[$i] = $inDefer;
            }
        } elseif ($deferType === 'rsi_overbought') {
            $rsi = $this->rsi($closes, 14);
            for ($i = 0; $i < $len; $i++) {
                $deferred[$i] = $this->isNum($rsi[$i]) && $rsi[$i] > 70;
            }
        } elseif ($deferType === 'bb_upper') {
            $bb = $this->bb($closes, 20, 2);
            for ($i = 0; $i < $len; $i++) {
                $deferred[$i] = $this->isNum($closes[$i]) && $this->isNum($bb['upper'][$i]) && $closes[$i] > $bb['upper'][$i];
            }
        } elseif ($deferType === 'sma_death') {
            $s5 = $this->sma($closes, 5);
            $s20 = $this->sma($closes, 20);
            $inDefer = false;
            for ($i = 1; $i < $len; $i++) {
                if (!$this->isNum($s5[$i]) || !$this->isNum($s20[$i]) ||
                    !$this->isNum($s5[$i - 1]) || !$this->isNum($s20[$i - 1])) {
                    $deferred[$i] = $inDefer;
                    continue;
                }
                $prevD = $s5[$i - 1] - $s20[$i - 1];
                $currD = $s5[$i] - $s20[$i];
                if ($prevD >= 0 && $currD < 0) $inDefer = true;
                if ($prevD <= 0 && $currD > 0) $inDefer = false;
                $deferred[$i] = $inDefer;
            }
        }
        return $deferred;
    }

    /* =========================================
       포트폴리오 시뮬레이터
       ========================================= */

    private function simulate(array $config): ?array
    {
        $stocks = $config['stocks'];
        $data = $config['stockData'];
        $allDates = array_values(array_filter($config['commonDates'], fn($d) => $d >= $config['startDate'] && $d <= $config['endDate']));
        if (empty($allDates)) return null;

        $fullDates = $config['commonDates'];

        // 종목별 종가 배열 (fullDates 기준)
        $closesMap = [];
        foreach ($stocks as $s) {
            $closesMap[$s['code']] = array_map(
                fn($d) => ($data[$s['code']] && isset($data[$s['code']]['ohlcv'][$d])) ? $data[$s['code']]['ohlcv'][$d]['c'] : null,
                $fullDates
            );
        }

        // 시그널 기반: 종목별 시그널 계산
        $signalMap = [];
        if (($config['strategy'] ?? '') === 'signal' && !empty($config['signalRules'])) {
            $rulesByTarget = [];
            foreach ($config['signalRules'] as $rule) {
                $target = $rule['targetCode'] ?? $stocks[0]['code'];
                $rulesByTarget[$target][] = $rule;
            }
            foreach ($rulesByTarget as $code => $rules) {
                if (isset($closesMap[$code])) {
                    $signalMap[$code] = $this->generateSignals($closesMap[$code], $rules, $config['signalCombine'] ?? 'or');
                }
            }
        }

        // DCA 유예 시그널
        $dcaDeferMap = null;
        if (!empty($config['dcaDefer']['enabled'])) {
            $dcaDeferMap = [];
            foreach ($stocks as $s) {
                if (isset($closesMap[$s['code']])) {
                    $dcaDeferMap[$s['code']] = $this->generateDCADefer($closesMap[$s['code']], $config['dcaDefer']['indicator'] ?? '');
                }
            }
        }

        // closesMap은 시그널/유예 계산 완료 후 불필요 — 메모리 해제
        unset($closesMap);

        // 시뮬레이션 상태
        $cash = $config['initialCapital'] ?? 0;
        $holdings = [];
        $deferredCash = [];
        foreach ($stocks as $s) {
            $holdings[$s['code']] = 0;
            $deferredCash[$s['code']] = 0;
        }
        $totalFees = 0;
        $totalInvested = $config['initialCapital'] ?? 0;
        $trades = [];
        $dailySeries = [];
        $lastDCAMonth = null;
        $lastRebalanceDate = null;

        $fullDatesFlip = array_flip($fullDates);

        // 초기 매수 (Buy & Hold, 리밸런싱)
        if (($config['strategy'] ?? '') !== 'signal' && $cash > 0) {
            $firstDate = $allDates[0];
            $this->buyByWeight($stocks, $data, $firstDate, $holdings, $config['fees'] ?? [], $totalFees, $cash, $trades);
            $cash = 0;
        }

        // 일별 루프
        for ($di = 0; $di < count($allDates); $di++) {
            // CPU yield: 주기적으로 양보
            if ($di > 0 && $di % self::YIELD_INTERVAL === 0) {
                usleep(self::YIELD_USLEEP);
            }
            $date = $allDates[$di];
            $fullIdx = $fullDatesFlip[$date] ?? -1;
            $curMonth = substr($date, 0, 7);

            // 1) DCA: 월 첫 거래일 현금 주입
            $monthlyDCA = $config['monthlyDCA'] ?? 0;
            if ($monthlyDCA > 0 && $curMonth !== $lastDCAMonth) {
                $lastDCAMonth = $curMonth;
                if ($dcaDeferMap !== null) {
                    foreach ($stocks as $s) {
                        $stockDCA = $monthlyDCA * ($s['weight'] / 100);
                        $isDeferred = isset($dcaDeferMap[$s['code']]) && $fullIdx >= 0 && ($dcaDeferMap[$s['code']][$fullIdx] ?? false);
                        if ($isDeferred) {
                            $deferredCash[$s['code']] += $stockDCA;
                        } else {
                            $amount = $stockDCA + $deferredCash[$s['code']];
                            $deferredCash[$s['code']] = 0;
                            $totalInvested += $amount;
                            if (($config['strategy'] ?? '') !== 'signal') {
                                $price = $data[$s['code']]['ohlcv'][$date]['c'] ?? 0;
                                if ($price > 0) {
                                    $feeRate = $this->getFeeRate($s['market'] ?? '', $config['fees'] ?? []);
                                    $fee = $amount * $feeRate;
                                    $qty = ($amount - $fee) / $price;
                                    if ($qty > 0) {
                                        $holdings[$s['code']] += $qty;
                                        $totalFees += $fee;
                                        $trades[] = ['date' => $date, 'code' => $s['code'], 'type' => 'buy', 'qty' => $qty, 'price' => $price, 'fee' => $fee];
                                    }
                                } else {
                                    $cash += $amount;
                                }
                            } else {
                                $cash += $amount;
                            }
                        }
                    }
                } else {
                    $cash += $monthlyDCA;
                    $totalInvested += $monthlyDCA;
                    if (($config['strategy'] ?? '') !== 'signal' && $cash > 0) {
                        $this->buyByWeight($stocks, $data, $date, $holdings, $config['fees'] ?? [], $totalFees, $cash, $trades);
                        $cash = 0;
                    }
                }
            }

            // DCA 유예 해제 체크
            if ($dcaDeferMap !== null && $fullIdx >= 0) {
                foreach ($stocks as $s) {
                    if ($deferredCash[$s['code']] > 0 && isset($dcaDeferMap[$s['code']]) && !($dcaDeferMap[$s['code']][$fullIdx] ?? false)) {
                        $amount = $deferredCash[$s['code']];
                        $deferredCash[$s['code']] = 0;
                        $totalInvested += $amount;
                        if (($config['strategy'] ?? '') !== 'signal') {
                            $price = $data[$s['code']]['ohlcv'][$date]['c'] ?? 0;
                            if ($price > 0) {
                                $feeRate = $this->getFeeRate($s['market'] ?? '', $config['fees'] ?? []);
                                $fee = $amount * $feeRate;
                                $qty = ($amount - $fee) / $price;
                                if ($qty > 0) {
                                    $holdings[$s['code']] += $qty;
                                    $totalFees += $fee;
                                    $trades[] = ['date' => $date, 'code' => $s['code'], 'type' => 'buy', 'qty' => $qty, 'price' => $price, 'fee' => $fee];
                                }
                            } else {
                                $cash += $amount;
                            }
                        } else {
                            $cash += $amount;
                        }
                    }
                }
            }

            // 2) 전략별 매매
            $strategy = $config['strategy'] ?? 'buyhold';
            if ($strategy === 'rebalance') {
                if ($this->shouldRebalance($date, $lastRebalanceDate, $config['rebalancePeriod'] ?? 'quarterly')) {
                    $lastRebalanceDate = $date;
                    $totalValue = $cash + $this->portfolioValue($stocks, $data, $date, $holdings);
                    // 1단계: 초과 비중 종목 매도
                    foreach ($stocks as $s) {
                        $price = $data[$s['code']]['ohlcv'][$date]['c'] ?? 0;
                        if ($price <= 0) continue;
                        $currentVal = $holdings[$s['code']] * $price;
                        $targetVal = $totalValue * ($s['weight'] / 100);
                        if ($currentVal > $targetVal) {
                            $excessVal = $currentVal - $targetVal;
                            $sellQty = $excessVal / $price;
                            $fee = $excessVal * $this->getFeeRate($s['market'] ?? '', $config['fees'] ?? []);
                            $holdings[$s['code']] -= $sellQty;
                            $cash += $excessVal - $fee;
                            $totalFees += $fee;
                            $trades[] = ['date' => $date, 'code' => $s['code'], 'type' => 'sell', 'qty' => $sellQty, 'price' => $price, 'fee' => $fee];
                        }
                    }
                    // 2단계: 부족 비중 종목 매수
                    foreach ($stocks as $s) {
                        $price = $data[$s['code']]['ohlcv'][$date]['c'] ?? 0;
                        if ($price <= 0) continue;
                        $currentVal = $holdings[$s['code']] * $price;
                        $targetVal = $totalValue * ($s['weight'] / 100);
                        if ($currentVal < $targetVal && $cash > 0) {
                            $deficitVal = min($targetVal - $currentVal, $cash);
                            $feeRate = $this->getFeeRate($s['market'] ?? '', $config['fees'] ?? []);
                            $fee = $deficitVal * $feeRate;
                            $buyQty = ($deficitVal - $fee) / $price;
                            if ($buyQty > 0) {
                                $holdings[$s['code']] += $buyQty;
                                $cash -= $deficitVal;
                                $totalFees += $fee;
                                $trades[] = ['date' => $date, 'code' => $s['code'], 'type' => 'buy', 'qty' => $buyQty, 'price' => $price, 'fee' => $fee];
                            }
                        }
                    }
                }
            } elseif ($strategy === 'signal') {
                foreach ($stocks as $s) {
                    $sig = $signalMap[$s['code']] ?? null;
                    if (!$sig) continue;
                    $signal = $sig[$fullIdx] ?? 'hold';
                    $price = $data[$s['code']]['ohlcv'][$date]['c'] ?? 0;
                    if ($price <= 0) continue;
                    $feeRate = $this->getFeeRate($s['market'] ?? '', $config['fees'] ?? []);

                    if ($signal === 'buy' && $cash > 0) {
                        $allocCash = $cash * ($s['weight'] / 100);
                        $fee = $allocCash * $feeRate;
                        $qty = ($allocCash - $fee) / $price;
                        if ($qty > 0) {
                            $holdings[$s['code']] += $qty;
                            $cash -= $allocCash;
                            $totalFees += $fee;
                            $trades[] = ['date' => $date, 'code' => $s['code'], 'type' => 'buy', 'qty' => $qty, 'price' => $price, 'fee' => $fee];
                        }
                    } elseif ($signal === 'sell' && $holdings[$s['code']] > 0) {
                        $sellQty = $holdings[$s['code']];
                        $sellValue = $sellQty * $price;
                        $fee = $sellValue * $feeRate;
                        $cash += $sellValue - $fee;
                        $totalFees += $fee;
                        $holdings[$s['code']] = 0;
                        $trades[] = ['date' => $date, 'code' => $s['code'], 'type' => 'sell', 'qty' => $sellQty, 'price' => $price, 'fee' => $fee];
                    }
                }
                // 시그널 전략 첫날 현금 투입
                if ($cash > 0 && $di === 0) {
                    $this->buyByWeight($stocks, $data, $date, $holdings, $config['fees'] ?? [], $totalFees, $cash, $trades);
                    $cash = 0;
                }
            }

            // 3) 일별 가치 기록
            $pv = $cash + $this->portfolioValue($stocks, $data, $date, $holdings);
            $dailySeries[] = [
                'date' => $date,
                'value' => $pv,
                'cash' => $cash,
                'invested' => $totalInvested,
            ];
        }

        // 시뮬레이션 완료 — 중간 데이터 해제
        unset($signalMap, $dcaDeferMap, $fullDatesFlip);

        return [
            'dailySeries' => $dailySeries,
            'trades' => $trades,
            'totalFees' => $totalFees,
            'totalInvested' => $totalInvested,
        ];
    }

    private function buyByWeight(array $stocks, array $data, string $date, array &$holdings, array $fees, float &$totalFees, float $cashAmount, array &$trades): void
    {
        foreach ($stocks as $s) {
            $price = $data[$s['code']]['ohlcv'][$date]['c'] ?? 0;
            if ($price <= 0) continue;
            $allocCash = $cashAmount * ($s['weight'] / 100);
            $feeRate = $this->getFeeRate($s['market'] ?? '', $fees);
            $fee = $allocCash * $feeRate;
            $qty = ($allocCash - $fee) / $price;
            if ($qty > 0) {
                $holdings[$s['code']] += $qty;
                $totalFees += $fee;
                $trades[] = ['date' => $date, 'code' => $s['code'], 'type' => 'buy', 'qty' => $qty, 'price' => $price, 'fee' => $fee];
            }
        }
    }

    private function portfolioValue(array $stocks, array $data, string $date, array $holdings): float
    {
        $val = 0;
        foreach ($stocks as $s) {
            $price = $data[$s['code']]['ohlcv'][$date]['c'] ?? 0;
            $val += $holdings[$s['code']] * $price;
        }
        return $val;
    }

    private function getFeeRate(string $market, array $fees): float
    {
        if ($market === 'COIN') return ($fees['COIN'] ?? 0.015) / 100;
        if (in_array($market, ['US', 'NYSE', 'NASDAQ', 'AMEX'], true)) return ($fees['US'] ?? 0.2) / 100;
        return ($fees['KR'] ?? 0.015) / 100;
    }

    private function shouldRebalance(string $date, ?string $lastDate, string $period): bool
    {
        if ($lastDate === null) return false;
        $d = new \DateTime($date);
        $ld = new \DateTime($lastDate);
        switch ($period) {
            case 'monthly':
                return (int)$d->format('m') !== (int)$ld->format('m') || (int)$d->format('Y') !== (int)$ld->format('Y');
            case 'quarterly':
                return intdiv((int)$d->format('m') - 1, 3) !== intdiv((int)$ld->format('m') - 1, 3) || (int)$d->format('Y') !== (int)$ld->format('Y');
            case 'semiannual':
                return intdiv((int)$d->format('m') - 1, 6) !== intdiv((int)$ld->format('m') - 1, 6) || (int)$d->format('Y') !== (int)$ld->format('Y');
            case 'annual':
                return (int)$d->format('Y') !== (int)$ld->format('Y');
            default:
                return false;
        }
    }

    /* =========================================
       메트릭 계산
       ========================================= */

    private function calculateMetrics(array $series, float $riskFreeRate): array
    {
        $totalReturn = $this->totalReturn($series);
        $cagr = $this->cagr($series);
        $mdd = $this->maxDrawdown($series);
        $sharpe = $this->sharpeRatio($series, $riskFreeRate);
        $sortino = $this->sortinoRatio($series, $riskFreeRate);
        $annuals = $this->annualReturns($series);
        $avgAnnual = count($annuals) > 0 ? array_sum(array_column($annuals, 'returnPct')) / count($annuals) : 0;

        return [
            'totalReturn' => $totalReturn,
            'avgAnnual' => $avgAnnual,
            'cagr' => $cagr,
            'mdd' => $mdd,
            'sharpe' => $sharpe,
            'sortino' => $sortino,
        ];
    }

    /**
     * TWR 정규화 랭킹 점수 계산
     * 투자금/DCA 영향을 제거한 순수 전략 실력 평가용 점수.
     * TWR 누적 곡선을 가상 포트폴리오(1.0 시작)로 생성하여
     * MDD·totalReturn을 투자금 무관하게 재계산.
     * CAGR·Sharpe·Sortino는 이미 TWR 기반이므로 그대로 활용.
     */
    private function calculateRankingScore(array $series, float $riskFreeRate): array
    {
        if (count($series) < 2) {
            return ['score' => 0, 'grade' => 'F'];
        }

        // TWR 누적 곡선 생성 (1.0 시작)
        $twrCurve = [1.0];
        $seriesLen = count($series);
        for ($i = 1; $i < $seriesLen; $i++) {
            $prevVal = $series[$i - 1]['value'];
            $cashFlow = $series[$i]['invested'] - $series[$i - 1]['invested'];
            $base = $prevVal + $cashFlow;
            if ($base > 0) {
                $twrCurve[] = $twrCurve[$i - 1] * ($series[$i]['value'] / $base);
            } else {
                $twrCurve[] = $twrCurve[$i - 1];
            }
        }

        // TWR 기반 totalReturn
        $twrTotalReturn = (end($twrCurve) - 1.0) * 100;

        // TWR 기반 MDD
        $peak = -INF;
        $twrMdd = 0;
        foreach ($twrCurve as $v) {
            if ($v > $peak) $peak = $v;
            if ($peak > 0) {
                $dd = ($peak - $v) / $peak * 100;
                if ($dd > $twrMdd) $twrMdd = $dd;
            }
        }

        // TWR 기반 연간 평균 수익률
        $yearGroups = [];
        foreach ($series as $idx => $d) {
            $y = substr($d['date'], 0, 4);
            $yearGroups[$y][] = $idx;
        }
        $annualReturns = [];
        foreach ($yearGroups as $indices) {
            if (count($indices) < 2) continue;
            $yearStart = $twrCurve[$indices[0]];
            $yearEnd = $twrCurve[end($indices)];
            if ($yearStart > 0) {
                $annualReturns[] = ($yearEnd / $yearStart - 1) * 100;
            }
        }
        $twrAvgAnnual = count($annualReturns) > 0 ? array_sum($annualReturns) / count($annualReturns) : 0;

        // CAGR·Sharpe·Sortino는 이미 TWR 기반 (dailyReturns가 cashflow 보정)
        $cagr = $this->cagr($series);
        $sharpe = $this->sharpeRatio($series, $riskFreeRate);
        $sortino = $this->sortinoRatio($series, $riskFreeRate);

        return self::computeScore([
            'cagr'        => $cagr,
            'avgAnnual'   => $twrAvgAnnual,
            'totalReturn' => $twrTotalReturn,
            'mdd'         => $twrMdd,
            'sharpe'      => $sharpe,
            'sortino'     => $sortino,
        ]);
    }

    /**
     * 공통 점수 계산 (정규화 0-100 + 가중 합산 + 등급)
     * StockController::calculateDisplayScore()와 로직 통합
     */
    public static function computeScore(array $metrics): array
    {
        $normalize = function ($value, $min, $max) {
            if ($value === null || !is_finite($value)) return 50;
            $score = ($value - $min) / ($max - $min) * 100;
            return max(0, min(100, $score));
        };

        $scores = [
            'cagr'        => $normalize($metrics['cagr'] ?? 0, -10, 15),
            'avgAnnual'   => $normalize($metrics['avgAnnual'] ?? 0, -10, 20),
            'totalReturn' => $normalize($metrics['totalReturn'] ?? 0, -50, 200),
            'mdd'         => 100 - $normalize($metrics['mdd'] ?? 0, 10, 45),
            'sharpe'      => $normalize($metrics['sharpe'] ?? 0, -0.5, 1.8),
            'sortino'     => $normalize($metrics['sortino'] ?? 0, -0.5, 2.0),
        ];

        $weights = ['cagr' => 20, 'avgAnnual' => 10, 'totalReturn' => 10, 'mdd' => 20, 'sharpe' => 20, 'sortino' => 20];
        $weightedSum = 0;
        $totalWeight = 0;
        foreach ($weights as $key => $w) {
            $weightedSum += $scores[$key] * $w;
            $totalWeight += $w;
        }
        $total = (int)round($weightedSum / $totalWeight);

        if ($total >= 90)      $grade = 'A+';
        elseif ($total >= 80)  $grade = 'A';
        elseif ($total >= 70)  $grade = 'B+';
        elseif ($total >= 60)  $grade = 'B';
        elseif ($total >= 50)  $grade = 'C+';
        elseif ($total >= 40)  $grade = 'C';
        elseif ($total >= 30)  $grade = 'D';
        else                   $grade = 'F';

        return ['score' => $total, 'grade' => $grade];
    }

    private function totalReturn(array $series): float
    {
        if (count($series) < 2) return 0;
        $last = end($series);
        return (($last['value'] - $last['invested']) / $last['invested']) * 100;
    }

    private function cagr(array $series): float
    {
        if (count($series) < 2) return 0;
        $first = $series[0];
        $last = end($series);
        $days = (strtotime($last['date']) - strtotime($first['date']));
        $years = $days / (365.25 * 86400);
        if ($years <= 0) return 0;

        // TWR 기반 CAGR
        $twr = 1.0;
        for ($i = 1; $i < count($series); $i++) {
            $prevVal = $series[$i - 1]['value'];
            $cashFlow = $series[$i]['invested'] - $series[$i - 1]['invested'];
            $base = $prevVal + $cashFlow;
            if ($base > 0) {
                $twr *= ($series[$i]['value'] / $base);
            }
        }
        return (pow($twr, 1 / $years) - 1) * 100;
    }

    private function maxDrawdown(array $series): float
    {
        $peak = -INF;
        $maxDD = 0;
        foreach ($series as $d) {
            if ($d['value'] > $peak) $peak = $d['value'];
            $dd = ($peak - $d['value']) / $peak * 100;
            if ($dd > $maxDD) $maxDD = $dd;
        }
        return $maxDD;
    }

    private function sharpeRatio(array $series, float $riskFreeRate): float
    {
        $dailyReturns = $this->dailyReturns($series);
        if (count($dailyReturns) < 2) return 0;
        $rf = $riskFreeRate / 100 / 252;
        $excess = array_map(fn($r) => $r - $rf, $dailyReturns);
        $mean = array_sum($excess) / count($excess);
        $variance = array_sum(array_map(fn($r) => ($r - $mean) ** 2, $excess)) / count($excess);
        $std = sqrt($variance);
        if ($std == 0) return 0;
        return ($mean / $std) * sqrt(252);
    }

    private function sortinoRatio(array $series, float $riskFreeRate): float
    {
        $dailyReturns = $this->dailyReturns($series);
        if (count($dailyReturns) < 2) return 0;
        $rf = $riskFreeRate / 100 / 252;
        $excess = array_map(fn($r) => $r - $rf, $dailyReturns);
        $mean = array_sum($excess) / count($excess);
        $downside = array_filter($excess, fn($r) => $r < 0);
        if (empty($downside)) return $mean > 0 ? INF : 0;
        $downVariance = array_sum(array_map(fn($r) => $r * $r, $downside)) / count($excess);
        $downStd = sqrt($downVariance);
        if ($downStd == 0) return 0;
        return ($mean / $downStd) * sqrt(252);
    }

    private function annualReturns(array $series): array
    {
        if (count($series) < 2) return [];
        $years = [];
        foreach ($series as $d) {
            $y = substr($d['date'], 0, 4);
            if (!isset($years[$y])) {
                $years[$y] = ['first' => $d, 'last' => $d, 'values' => []];
            }
            $years[$y]['last'] = $d;
            $years[$y]['values'][] = $d;
        }
        $result = [];
        ksort($years);
        foreach ($years as $y => $yr) {
            $twr = 1.0;
            for ($i = 1; $i < count($yr['values']); $i++) {
                $prevVal = $yr['values'][$i - 1]['value'];
                $cashFlow = $yr['values'][$i]['invested'] - $yr['values'][$i - 1]['invested'];
                $base = $prevVal + $cashFlow;
                if ($base > 0) {
                    $twr *= ($yr['values'][$i]['value'] / $base);
                }
            }
            $ret = ($twr - 1) * 100;
            $peak = -INF;
            $mdd = 0;
            foreach ($yr['values'] as $d) {
                if ($d['value'] > $peak) $peak = $d['value'];
                $dd = ($peak - $d['value']) / $peak * 100;
                if ($dd > $mdd) $mdd = $dd;
            }
            $result[] = [
                'year' => $y,
                'returnPct' => $ret,
                'startValue' => $yr['first']['value'],
                'endValue' => $yr['last']['value'],
                'invested' => $yr['last']['invested'],
                'mdd' => $mdd,
            ];
        }
        return $result;
    }

    private function dailyReturns(array $series): array
    {
        $returns = [];
        for ($i = 1; $i < count($series); $i++) {
            $prevVal = $series[$i - 1]['value'];
            $cashFlow = $series[$i]['invested'] - $series[$i - 1]['invested'];
            $base = $prevVal + $cashFlow;
            if ($base > 0) {
                $returns[] = $series[$i]['value'] / $base - 1;
            }
        }
        return $returns;
    }

    /* =========================================
       벤치마크 시뮬레이션
       ========================================= */

    private function simulateBenchmarks(array $config, array $portfolioResult, array $benchmarkDataMap, float $riskFreeRate): array
    {
        $bmkResults = [];
        $benchmarks = $config['benchmarks'] ?? [];
        if (empty($benchmarks) || empty($benchmarkDataMap)) return $bmkResults;

        $bmkColors = [
            'rgb(249, 115, 22)',
            'rgb(168, 85, 247)',
            'rgb(34, 197, 94)',
            'rgb(236, 72, 153)',
            'rgb(6, 182, 212)',
        ];

        $portfolioFirstDate = $portfolioResult['dailySeries'][0]['date'];
        $portfolioDates = array_column($portfolioResult['dailySeries'], 'date');

        foreach ($benchmarks as $bmkIdx => $bmk) {
            // 벤치마크 간 CPU yield
            if ($bmkIdx > 0) usleep(self::YIELD_USLEEP * 5);

            $bmkData = $benchmarkDataMap[$bmk['code']] ?? null;
            if (!$bmkData) continue;

            $bmkStockData = [];
            $bmkStockData[$bmk['code']] = [
                'dates' => $bmkData['dates'],
                'ohlcv' => $bmkData['ohlcv'],
            ];
            $bmkDates = $bmkData['dates'];

            // union dates
            $seen = [];
            $unionDates = [];
            foreach (array_merge($portfolioDates, $bmkDates) as $d) {
                if (!isset($seen[$d]) && $d >= $portfolioFirstDate && $d <= $config['endDate']) {
                    $seen[$d] = true;
                    $unionDates[] = $d;
                }
            }
            sort($unionDates);

            // carry-forward
            $bmkOhlcv = &$bmkStockData[$bmk['code']]['ohlcv'];
            $lastCarry = null;
            foreach ($unionDates as $d) {
                if (isset($bmkOhlcv[$d])) {
                    $lastCarry = $bmkOhlcv[$d];
                } elseif ($lastCarry !== null) {
                    $bmkOhlcv[$d] = ['o' => $lastCarry['c'], 'h' => $lastCarry['c'], 'l' => $lastCarry['c'], 'c' => $lastCarry['c'], 'v' => 0];
                }
            }
            $bmkStockData[$bmk['code']]['dates'] = $unionDates;
            unset($bmkOhlcv);

            $bmkConfig = [
                'stocks' => [['code' => $bmk['code'], 'market' => $bmk['market'] ?? '', 'weight' => 100]],
                'stockData' => $bmkStockData,
                'commonDates' => $unionDates,
                'startDate' => $portfolioFirstDate,
                'endDate' => $config['endDate'],
                'strategy' => 'buyhold',
                'rebalancePeriod' => 'quarterly',
                'signalRules' => [],
                'signalCombine' => 'or',
                'initialCapital' => $config['initialCapital'] ?? 0,
                'monthlyDCA' => $config['monthlyDCA'] ?? 0,
                'dcaDefer' => ['enabled' => false],
                'fees' => $config['fees'] ?? [],
                'riskFreeRate' => $riskFreeRate,
            ];

            $bmkResult = $this->simulate($bmkConfig);
            if ($bmkResult && !empty($bmkResult['dailySeries'])) {
                $bmkMetrics = $this->calculateMetrics($bmkResult['dailySeries'], $riskFreeRate);
                $bmkAnnuals = $this->annualReturns($bmkResult['dailySeries']);

                // TWR 기반 차트 데이터 생성
                $twrData = [];
                $bmkTwr = 1.0;
                $bmkDs = $bmkResult['dailySeries'];
                $twrData[] = ['date' => $bmkDs[0]['date'], 'returnPct' => 0];
                for ($bi = 1; $bi < count($bmkDs); $bi++) {
                    $bPrevVal = $bmkDs[$bi - 1]['value'];
                    $bCashFlow = $bmkDs[$bi]['invested'] - $bmkDs[$bi - 1]['invested'];
                    $bBase = $bPrevVal + $bCashFlow;
                    if ($bBase > 0) {
                        $bmkTwr *= ($bmkDs[$bi]['value'] / $bBase);
                    }
                    $twrData[] = ['date' => $bmkDs[$bi]['date'], 'returnPct' => ($bmkTwr - 1) * 100];
                }

                $bmkResults[] = [
                    'name' => $bmk['name'] ?? $bmk['code'],
                    'color' => $bmkColors[$bmkIdx % count($bmkColors)],
                    'metrics' => $bmkMetrics,
                    'chartData' => $twrData,
                ];
            }
            // 중간 데이터 메모리 해제
            unset($bmkStockData, $bmkConfig, $bmkResult, $bmkMetrics, $bmkAnnuals, $twrData, $unionDates);
        }
        return $bmkResults;
    }

    /* =========================================
       유틸리티
       ========================================= */

    private function isNum($v): bool
    {
        return $v !== null && is_numeric($v) && is_finite((float)$v);
    }

    /**
     * dailySeries를 차트용으로 다운샘플링
     * 첫/끝 포인트 유지, 중간은 균등 간격으로 추출
     */
    private function downsampleSeries(array $series, int $maxPoints): array
    {
        $len = count($series);
        if ($len <= $maxPoints) return $series;

        $result = [$series[0]];
        $step = ($len - 1) / ($maxPoints - 1);
        for ($i = 1; $i < $maxPoints - 1; $i++) {
            $idx = (int)round($i * $step);
            $result[] = $series[$idx];
        }
        $result[] = $series[$len - 1];
        return $result;
    }

    /**
     * 벤치마크 chartData [{date, returnPct}] 다운샘플링
     */
    private function downsampleChartData(array $data, int $maxPoints): array
    {
        $len = count($data);
        if ($len <= $maxPoints) return $data;

        $result = [$data[0]];
        $step = ($len - 1) / ($maxPoints - 1);
        for ($i = 1; $i < $maxPoints - 1; $i++) {
            $idx = (int)round($i * $step);
            $result[] = $data[$idx];
        }
        $result[] = $data[$len - 1];
        return $result;
    }
}
