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
        if (!in_array($market, ['KR', 'US'], true)) {
            $market = $this->getDefaultMarketByMarketHours();
        }
        $search = isset($_GET['search']) ? $this->sanitizeInput($_GET['search']) : '';
        $perPage = 50;

        // 주식 목록 + 전체 개수를 한 번에 조회
        $listResult = $this->stockModel->getStockListWithCount($page, $perPage, $market, $search);
        $stocks = $listResult['stocks'];
        $totalCount = $listResult['total'];
        $totalPages = ceil($totalCount / $perPage);
        
        // 시장 통계
        $marketStats = $this->stockModel->getMarketStats();
        
        // 인기 주식
        $topStocks = $this->stockModel->getTopStocks(10, $market);

        $this->renderLayout('main', 'stocks/index', [
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
        $minute = (int)$now->format('i');

        $isWeekday = $dayOfWeek >= 1 && $dayOfWeek <= 5;
        $isAfterOpen = ($hour > 9) || ($hour === 9 && $minute >= 0);
        $isBeforeClose = ($hour < 15) || ($hour === 15 && $minute <= 30);

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
        
        if (empty($stockCode)) {
            $this->session->setFlash('error', '주식 코드가 필요합니다.');
            $this->redirect('/stocks');
            return;
        }

        // 주식 정보 조회 (가벼운 단건 쿼리만 서버에서 실행)
        $stock = $this->stockModel->getStockByCode($stockCode);
        
        if (!$stock) {
            $this->session->setFlash('error', '해당 주식을 찾을 수 없습니다.');
            $this->redirect('/stocks');
            return;
        }

        // 캔들/체결 데이터는 클라이언트에서 API로 비동기 로딩 (페이지 렌더 차단 방지)
        $this->renderLayout('main', 'stocks/show', [
            'stock' => $stock,
            'candleData' => [],
            'recentExecutions' => [],
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
        $stockCode = isset($_GET['code']) ? $this->sanitizeInput($_GET['code']) : '';
        $startDate = isset($_GET['start']) ? $this->sanitizeInput($_GET['start']) : date('Y-m-d H:i:s', strtotime('-30 days'));
        $endDate = isset($_GET['end']) ? $this->sanitizeInput($_GET['end']) : date('Y-m-d H:i:s');
        $limit = isset($_GET['limit']) ? min(1000, max(1, intval($_GET['limit']))) : 500;
        $timeframe = isset($_GET['timeframe']) ? $this->sanitizeInput($_GET['timeframe']) : '1h';
        
        if (empty($stockCode)) {
            $this->jsonResponse(['error' => 'Stock code is required'], 400);
            return;
        }

        $candleData = $this->stockModel->getCandleData($stockCode, $startDate, $endDate, $limit, $timeframe);
        
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
        $stockCode = isset($_GET['code']) ? $this->sanitizeInput($_GET['code']) : '';
        $limit = isset($_GET['limit']) ? min(200, max(1, intval($_GET['limit']))) : 100;
        
        if (empty($stockCode)) {
            $this->jsonResponse(['error' => 'Stock code is required'], 400);
            return;
        }

        $executions = $this->stockModel->getRecentExecutions($stockCode, $limit);
        
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
