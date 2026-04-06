<?php

namespace Blog\Controllers;

use Blog\Models\Stock;
use Blog\Models\Category;

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

}
