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
        $market = isset($_GET['market']) ? $this->sanitizeInput($_GET['market']) : '';
        $search = isset($_GET['search']) ? $this->sanitizeInput($_GET['search']) : '';
        $perPage = 50;

        // 주식 목록 조회
        $stocks = $this->stockModel->getStockList($page, $perPage, $market, $search);
        $totalCount = $this->stockModel->getStockCount($market, $search);
        $totalPages = ceil($totalCount / $perPage);
        
        // 시장 통계
        $marketStats = $this->stockModel->getMarketStats();
        
        // 인기 주식
        $topStocks = $this->stockModel->getTopStocks(10);

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

        // 주식 정보 조회
        $stock = $this->stockModel->getStockByCode($stockCode);
        
        if (!$stock) {
            $this->session->setFlash('error', '해당 주식을 찾을 수 없습니다.');
            $this->redirect('/stocks');
            return;
        }

        // 캔들 데이터 조회 (최근 30일)
        $endDate = date('Y-m-d H:i:s');
        $startDate = date('Y-m-d H:i:s', strtotime('-30 days'));
        $candleData = $this->stockModel->getCandleData($stockCode, $startDate, $endDate, 500);
        
        // 최근 체결 데이터
        $recentExecutions = $this->stockModel->getRecentExecutions($stockCode, 50);

        $this->renderLayout('main', 'stocks/show', [
            'stock' => $stock,
            'candleData' => $candleData,
            'recentExecutions' => $recentExecutions,
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
