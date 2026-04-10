<?php

namespace Blog\Controllers;

use Blog\Models\Stock;
use Blog\Models\Category;
use Blog\Services\BacktestService;
use Blog\Core\Cache;

class StockController extends BaseController
{
    private $stockModel;

    public function __construct()
    {
        parent::__construct();
        $this->stockModel = new Stock();
    }

    /**
     * 주식 목록 페이지
     */
    public function index(): void
    {
        $page = isset($_GET['page']) ? max(1, intval($_GET['page'])) : 1;
        $market = isset($_GET['market']) ? strtoupper(trim($this->sanitizeInput($_GET['market']))) : '';
        if (!in_array($market, ['KR', 'US', 'COIN'], true)) {
            $market = $this->getDefaultMarketByMarketHours();
        }
        $search = isset($_GET['search']) ? $this->sanitizeInput($_GET['search']) : '';
        $perPage = 50;

        // 주식 목록 + 전체 개수를 한 번에 조회
        $listResult = $this->stockModel->getStockListWithCount($page, $perPage, $market, $search);
        $stocks = $listResult['stocks'];
        $totalCount = $listResult['total'];
        $totalPages = max(1, ceil($totalCount / $perPage));

        // 페이지 범위 제한 (존재하지 않는 페이지 요청 차단)
        if ($page > $totalPages) {
            $page = $totalPages;
        }
        
        // 시장 통계
        $marketStats = $this->stockModel->getMarketStats();
        
        // 인기 주식
        $topStocks = $this->stockModel->getTopStocks(10, $market);

        $this->renderLayout('stock', 'stock/index', [
            'stocks' => $stocks,
            'topStocks' => $topStocks,
            'marketStats' => $marketStats,
            'currentPage' => $page,
            'totalPages' => $totalPages,
            'totalCount' => $totalCount,
            'currentMarket' => $market,
            'searchQuery' => $search,
            'isStockPage' => true,
            'additionalCss' => ['/css/stocks.css']
        ]);
    }

    /**
     * 현재 시간 기준 기본 시장 결정
     * - 한국장 개장 시간(평일 09:00~15:30)이면 KR
     * - 그 외 시간은 US
     */
    private function getDefaultMarketByMarketHours(): string
    {
        $now = new \DateTime('now', new \DateTimeZone('Asia/Seoul'));
        $dayOfWeek = (int)$now->format('N');
        $hour = (int)$now->format('G');

        $isWeekday = $dayOfWeek >= 1 && $dayOfWeek <= 5;
        $isAfterOpen = $hour >= 8;
        $isBeforeClose = $hour < 18;

        if ($isWeekday && $isAfterOpen && $isBeforeClose) {
            return 'KR';
        }

        return 'US';
    }

    /**
     * 주식 상세 페이지 (차트)
     */
    public function show(): void
    {
        $stockCode = isset($_GET['code']) ? $this->sanitizeInput($_GET['code']) : '';
        $market = isset($_GET['market']) ? strtoupper(trim($this->sanitizeInput($_GET['market']))) : '';
        
        if (empty($stockCode)) {
            $this->session->setFlash('error', '주식 코드가 필요합니다.');
            $this->redirect('/stocks');
            return;
        }

        // 주식 정보 조회 (market 파람으로 우선순위 결정)
        $stock = $this->stockModel->getStockByCode($stockCode, $market);
        
        if (!$stock) {
            $this->session->setFlash('error', '해당 주식을 찾을 수 없습니다.');
            $this->redirect('/stocks');
            return;
        }

        $isCoinMarket = (($stock['stock_type'] ?? '') === 'COIN');

        $latestClose = $this->stockModel->getLatestCandleClose($stockCode, $market);
        if ($latestClose !== null) {
            $stock['stock_price'] = $latestClose;
        }

        // 캔들/체결 데이터는 클라이언트에서 API로 비동기 로딩 (페이지 렌더 차단 방지)
        $this->renderLayout('stock', 'stock/show', [
            'stock' => $stock,
            'candleData' => [],
            'recentExecutions' => [],
            'isCoinMarket' => $isCoinMarket,
            'isStockPage' => true,
            'additionalCss' => ['/css/stocks.css'],
            'additionalJs' => ['/js/stocks.js']
        ]);
    }

    /**
     * API: 주식 캔들 데이터 (JSON)
     */
    public function apiCandleData(): void
    {
        if (!$this->requireInternalRequest()) {
            return;
        }

        $stockCode = isset($_GET['code']) ? $this->sanitizeInput($_GET['code']) : '';
        $startDate = isset($_GET['start']) ? $this->sanitizeInput($_GET['start']) : date('Y-m-d H:i:00', strtotime('-30 days'));
        $endDate = isset($_GET['end']) ? $this->sanitizeInput($_GET['end']) : date('Y-m-d H:i:00');

        // 캐시 적중률 향상을 위해 초 단위 제거 (분 단위 정규화)
        $startDate = preg_replace('/:\d{2}$/', ':00', $startDate);
        $endDate = preg_replace('/:\d{2}$/', ':00', $endDate);
        $limit = isset($_GET['limit']) ? min(1000, max(1, intval($_GET['limit']))) : 500;
        $timeframe = isset($_GET['timeframe']) ? $this->sanitizeInput($_GET['timeframe']) : '1h';
        $market = isset($_GET['market']) ? strtoupper(trim($this->sanitizeInput($_GET['market']))) : '';
        
        if (empty($stockCode)) {
            $this->jsonResponse(['error' => 'Stock code is required'], 400);
            return;
        }

        $candleData = $this->stockModel->getCandleData($stockCode, $startDate, $endDate, $limit, $timeframe, $market);
        
        header('Cache-Control: private, max-age=60');
        $this->jsonResponse([
            'success' => true,
            'data' => $candleData,
            'count' => count($candleData)
        ]);
    }

    /**
     * API: 최근 체결 데이터 (JSON)
     */
    public function apiRecentExecutions(): void
    {
        if (!$this->requireInternalRequest()) {
            return;
        }

        $stockCode = isset($_GET['code']) ? $this->sanitizeInput($_GET['code']) : '';
        $limit = isset($_GET['limit']) ? min(200, max(1, intval($_GET['limit']))) : 100;
        $market = isset($_GET['market']) ? strtoupper(trim($this->sanitizeInput($_GET['market']))) : '';
        
        if (empty($stockCode)) {
            $this->jsonResponse(['error' => 'Stock code is required'], 400);
            return;
        }

        $executions = $this->stockModel->getRecentExecutions($stockCode, $limit, $market);
        
        header('Cache-Control: private, max-age=10');
        $this->jsonResponse([
            'success' => true,
            'data' => $executions,
            'count' => count($executions)
        ]);
    }

    /**
     * 포트폴리오 백테스팅 시뮬레이터 페이지
     */
    public function backtest(): void
    {
        $this->renderLayout('stock', 'stock/backtest', [
            'isStockPage' => true,
            'additionalCss' => ['/css/stocks.css'],
            'additionalJs' => ['/vendor/chart.umd.min.js', '/js/backtest.js']
        ]);
    }

    /**
     * API: 종목 코드들의 공통 날짜 범위 조회 (JSON)
     */
    public function apiDateRange(): void
    {
        if (!$this->requireInternalRequest()) {
            return;
        }

        // Rate Limiting (IP당 분당 30회)
        $ip = $_SERVER['REMOTE_ADDR'] ?? 'unknown';
        $cache = Cache::getInstance();
        $rateKey = Cache::key('daterange_rate', $ip);
        $rateCount = (int)($cache->get($rateKey) ?? 0) + 1;
        $cache->set($rateKey, $rateCount, 60);
        if ($rateCount > 30) {
            $this->jsonResponse(['success' => false, 'error' => '요청이 너무 많습니다. 잠시 후 다시 시도해주세요.'], 429);
            return;
        }

        $codesParam = isset($_GET['codes']) ? $this->sanitizeInput($_GET['codes']) : '';
        $marketsParam = isset($_GET['markets']) ? $this->sanitizeInput($_GET['markets']) : '';
        if (empty($codesParam)) {
            $this->jsonResponse(['success' => true, 'data' => null]);
            return;
        }

        $codes = array_slice(array_filter(explode(',', $codesParam)), 0, 15);
        $markets = array_filter(explode(',', $marketsParam));

        $globalMin = null;
        $globalMax = null;

        foreach ($codes as $i => $code) {
            $market = isset($markets[$i]) ? $markets[$i] : '';
            $range = $this->stockModel->getCandleDateRange(trim($code), trim($market));
            if ($range === null) {
                continue;
            }
            if ($globalMin === null || $range['min'] > $globalMin) {
                $globalMin = $range['min'];
            }
            if ($globalMax === null || $range['max'] < $globalMax) {
                $globalMax = $range['max'];
            }
        }

        if ($globalMin === null || $globalMax === null || $globalMin > $globalMax) {
            $this->jsonResponse(['success' => true, 'data' => null]);
            return;
        }

        header('Cache-Control: private, max-age=300');
        $this->jsonResponse([
            'success' => true,
            'data' => ['min' => $globalMin, 'max' => $globalMax]
        ]);
    }

    /**
     * API: 주식 검색 (JSON)
     */
    public function apiSearch(): void
    {
        if (!$this->requireInternalRequest()) {
            return;
        }

        $search = isset($_GET['q']) ? $this->sanitizeInput($_GET['q']) : '';
        $market = isset($_GET['market']) ? $this->sanitizeInput($_GET['market']) : '';
        $limit = isset($_GET['limit']) ? min(100, max(1, intval($_GET['limit']))) : 20;
        
        $stocks = $this->stockModel->getStockList(1, $limit, $market, $search);
        
        $this->jsonResponse([
            'success' => true,
            'data' => $stocks,
            'count' => count($stocks)
        ]);
    }

    /**
     * API: 포트폴리오 백테스트 시뮬레이션 (POST, JSON)
     */
    public function apiBacktest(): void
    {
        if (!$this->requireInternalRequest()) {
            return;
        }

        // Rate Limiting (IP당 분당 5회 — CPU/DB 집약적 API)
        $ip = $_SERVER['REMOTE_ADDR'] ?? 'unknown';
        $cache = Cache::getInstance();
        $rateKey = Cache::key('backtest_rate', $ip);
        $rateCount = (int)($cache->get($rateKey) ?? 0) + 1;
        $cache->set($rateKey, $rateCount, 60);
        if ($rateCount > 5) {
            $this->jsonResponse(['success' => false, 'error' => '백테스트 요청이 너무 많습니다. 잠시 후 다시 시도해주세요.'], 429);
            return;
        }

        $raw = file_get_contents('php://input');
        $input = json_decode($raw, true);
        if (!is_array($input)) {
            $this->jsonResponse(['success' => false, 'error' => 'Invalid JSON'], 400);
            return;
        }

        // 필수 필드 검증
        if (empty($input['stocks']) || !is_array($input['stocks'])) {
            $this->jsonResponse(['success' => false, 'error' => 'stocks is required'], 400);
            return;
        }
        if (empty($input['startDate']) || empty($input['endDate'])) {
            $this->jsonResponse(['success' => false, 'error' => 'startDate and endDate are required'], 400);
            return;
        }

        // 종목 수 제한
        $maxStocks = 10;
        $maxBenchmarks = 5;
        if (count($input['stocks']) > $maxStocks) {
            $this->jsonResponse(['success' => false, 'error' => 'Maximum ' . $maxStocks . ' stocks allowed'], 400);
            return;
        }
        if (isset($input['benchmarks']) && count($input['benchmarks']) > $maxBenchmarks) {
            $this->jsonResponse(['success' => false, 'error' => 'Maximum ' . $maxBenchmarks . ' benchmarks allowed'], 400);
            return;
        }

        // 날짜 형식 검증
        if (!preg_match('/^\d{4}-\d{2}-\d{2}$/', $input['startDate']) ||
            !preg_match('/^\d{4}-\d{2}-\d{2}$/', $input['endDate'])) {
            $this->jsonResponse(['success' => false, 'error' => 'Invalid date format'], 400);
            return;
        }
        if ($input['startDate'] >= $input['endDate']) {
            $this->jsonResponse(['success' => false, 'error' => 'startDate must be before endDate'], 400);
            return;
        }

        // 전략 검증
        $validStrategies = ['buyhold', 'rebalance', 'signal'];
        $strategy = $input['strategy'] ?? 'buyhold';
        if (!in_array($strategy, $validStrategies, true)) {
            $this->jsonResponse(['success' => false, 'error' => 'Invalid strategy'], 400);
            return;
        }

        // 입력 정제
        $config = [
            'stocks' => array_map(function ($s) {
                return [
                    'code' => $this->sanitizeInput($s['code'] ?? ''),
                    'market' => $this->sanitizeInput($s['market'] ?? ''),
                    'weight' => (float)($s['weight'] ?? 0),
                ];
            }, array_slice($input['stocks'], 0, $maxStocks)),
            'benchmarks' => array_map(function ($b) {
                return [
                    'code' => $this->sanitizeInput($b['code'] ?? ''),
                    'market' => $this->sanitizeInput($b['market'] ?? ''),
                    'name' => $this->sanitizeInput($b['name'] ?? $b['code'] ?? ''),
                ];
            }, array_slice($input['benchmarks'] ?? [], 0, $maxBenchmarks)),
            'startDate' => $input['startDate'],
            'endDate' => $input['endDate'],
            'strategy' => $strategy,
            'rebalancePeriod' => in_array($input['rebalancePeriod'] ?? '', ['monthly', 'quarterly', 'semiannual', 'annual'], true)
                ? $input['rebalancePeriod'] : 'quarterly',
            'signalRules' => array_map(function ($r) {
                return [
                    'indicator' => $this->sanitizeInput($r['indicator'] ?? ''),
                    'targetCode' => $this->sanitizeInput($r['targetCode'] ?? ''),
                ];
            }, array_slice($input['signalRules'] ?? [], 0, 20)),
            'signalCombine' => in_array($input['signalCombine'] ?? '', ['and', 'or'], true)
                ? $input['signalCombine'] : 'or',
            'initialCapital' => max(0, min(1e12, (float)($input['initialCapital'] ?? 0))),
            'monthlyDCA' => max(0, min(1e10, (float)($input['monthlyDCA'] ?? 0))),
            'dcaDefer' => [
                'enabled' => (bool)($input['dcaDefer']['enabled'] ?? false),
                'indicator' => $this->sanitizeInput($input['dcaDefer']['indicator'] ?? 'none'),
            ],
            'fees' => [
                'KR' => max(0, min(10, (float)($input['fees']['KR'] ?? 0.015))),
                'US' => max(0, min(10, (float)($input['fees']['US'] ?? 0.2))),
                'COIN' => max(0, min(10, (float)($input['fees']['COIN'] ?? 0.015))),
            ],
            'riskFreeRate' => max(0, min(100, (float)($input['riskFreeRate'] ?? 3))),
        ];

        // 기간 초과 사전 차단 (최대 30년)
        $periodYears = (strtotime($config['endDate']) - strtotime($config['startDate'])) / (365.25 * 86400);
        if ($periodYears > 30) {
            $this->jsonResponse(['success' => false, 'error' => '최대 30년까지 시뮬레이션 가능합니다.'], 400);
            return;
        }

        // 동시 실행 제한 (파일 기반 세마포어)
        $maxConcurrent = 2;
        $lockDir = __DIR__ . '/../../cache/data';
        $lockHandle = null;
        $lockPath = null;
        for ($slot = 0; $slot < $maxConcurrent; $slot++) {
            $path = $lockDir . '/backtest_slot_' . $slot . '.lock';
            $fh = fopen($path, 'c');
            if ($fh && flock($fh, LOCK_EX | LOCK_NB)) {
                $lockHandle = $fh;
                $lockPath = $path;
                break;
            }
            if ($fh) fclose($fh);
        }
        if ($lockHandle === null) {
            $this->jsonResponse(['success' => false, 'error' => '서버가 바쁩니다. 잠시 후 다시 시도해주세요.'], 503);
            return;
        }

        try {
            $service = new BacktestService();
            $result = $service->run($config);
        } finally {
            flock($lockHandle, LOCK_UN);
            fclose($lockHandle);
        }

        if ($result === null) {
            $this->jsonResponse(['success' => false, 'error' => 'No data available for the selected stocks and period'], 404);
            return;
        }

        header('Cache-Control: private, no-cache');
        $this->jsonResponse([
            'success' => true,
            'data' => $result,
        ]);
    }

}
