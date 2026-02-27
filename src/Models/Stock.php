<?php

namespace Blog\Models;

use Blog\Database\Database;
use Blog\Core\Cache;

class Stock
{
    private $db;
    private $cache;

    public function __construct()
    {
        $this->db = Database::getInstance();
        $this->cache = Cache::getInstance();
    }

    private function resolveStockDbName(string $stockCode): ?string
    {
        $normalizedCode = str_replace('.', '_', $stockCode);
        $candidates = [
            'Z_Stock' . $normalizedCode,
            'Z_Stock_' . $normalizedCode,
        ];

        foreach ($candidates as $candidate) {
            $exists = $this->db->fetch(
                'SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = :schema LIMIT 1',
                [':schema' => $candidate]
            );

            if ($exists) {
                return $candidate;
            }
        }

        return null;
    }

    /**
     * 주식 목록 조회 (페이징 지원)
     */
    public function getStockList(int $page = 1, int $perPage = 50, string $market = '', string $search = ''): array
    {
        $offset = ($page - 1) * $perPage;
        
        $cacheKey = Cache::key('stock_list', $page, $perPage, $market, $search);
        $cached = $this->cache->get($cacheKey);
        if ($cached !== null) {
            return $cached;
        }

        $params = [];
        $whereClauses = [];
        
        if ($market !== '') {
            $whereClauses[] = 'stock_market = :market';
            $params[':market'] = $market;
        }
        
        if ($search !== '') {
            $whereClauses[] = '(stock_code LIKE :search_code OR stock_name_kr LIKE :search_name_kr OR stock_name_en LIKE :search_name_en)';
            $searchValue = '%' . $search . '%';
            $params[':search_code'] = $searchValue;
            $params[':search_name_kr'] = $searchValue;
            $params[':search_name_en'] = $searchValue;
        }

        $whereSQL = !empty($whereClauses) ? 'WHERE ' . implode(' AND ', $whereClauses) : '';
        
        $sql = "SELECT stock_code, stock_name_kr, stock_name_en, stock_market, stock_type, 
                       stock_price, stock_capitalization, stock_count, stock_update
                FROM KoreaInvest.stock_info 
                $whereSQL
                ORDER BY stock_capitalization DESC 
                LIMIT :limit OFFSET :offset";
        
        $params[':limit'] = $perPage;
        $params[':offset'] = $offset;
        
        $stocks = $this->db->fetchAll($sql, $params);
        
        $this->cache->set($cacheKey, $stocks, 300); // 5분 캐시
        
        return $stocks;
    }

    /**
     * 주식 총 개수 조회
     */
    public function getStockCount(string $market = '', string $search = ''): int
    {
        $cacheKey = Cache::key('stock_count', $market, $search);
        $cached = $this->cache->get($cacheKey);
        if ($cached !== null) {
            return (int)$cached;
        }

        $params = [];
        $whereClauses = [];
        
        if ($market !== '') {
            $whereClauses[] = 'stock_market = :market';
            $params[':market'] = $market;
        }
        
        if ($search !== '') {
            $whereClauses[] = '(stock_code LIKE :search_code OR stock_name_kr LIKE :search_name_kr OR stock_name_en LIKE :search_name_en)';
            $searchValue = '%' . $search . '%';
            $params[':search_code'] = $searchValue;
            $params[':search_name_kr'] = $searchValue;
            $params[':search_name_en'] = $searchValue;
        }

        $whereSQL = !empty($whereClauses) ? 'WHERE ' . implode(' AND ', $whereClauses) : '';
        
        $sql = "SELECT COUNT(*) as count FROM KoreaInvest.stock_info $whereSQL";
        
        $result = $this->db->fetch($sql, $params);
        $count = $result['count'] ?? 0;
        
        $this->cache->set($cacheKey, $count, 300); // 5분 캐시
        
        return (int)$count;
    }

    /**
     * 특정 주식 상세 정보 조회
     */
    public function getStockByCode(string $stockCode): ?array
    {
        $cacheKey = Cache::key('stock_detail', $stockCode);
        $cached = $this->cache->get($cacheKey);
        if ($cached !== null) {
            return $cached;
        }

        $sql = "SELECT * FROM KoreaInvest.stock_info WHERE stock_code = :stock_code";
        $stock = $this->db->fetch($sql, [':stock_code' => $stockCode]);
        
        if ($stock) {
            $this->cache->set($cacheKey, $stock, 300); // 5분 캐시
        }
        
        return $stock ?: null;
    }

    /**
     * 주식 캔들 데이터 조회 (차트용)
     */
    public function getCandleData(string $stockCode, string $startDate, string $endDate, int $limit = 500, string $timeframe = '1h'): array
    {
        $cacheKey = Cache::key('stock_candle', $stockCode, $startDate, $endDate, $limit, $timeframe);
        $cached = $this->cache->get($cacheKey);
        if ($cached !== null) {
            return $cached;
        }

        $dbName = $this->resolveStockDbName($stockCode);
        if ($dbName === null) {
            return [];
        }
        
        try {
            $startYear = (int)date('Y', strtotime($startDate));
            $endYear = (int)date('Y', strtotime($endDate));
            $candles = [];

            for ($year = $startYear; $year <= $endYear; $year++) {
                $tableName = "Candle{$year}";

                try {
                    $sql = "SELECT execution_datetime, execution_open, execution_close, execution_min, execution_max,
                                   execution_non_volume, execution_ask_volume, execution_bid_volume,
                                   execution_non_amount, execution_ask_amount, execution_bid_amount
                            FROM `{$dbName}`.`{$tableName}`
                            WHERE execution_datetime BETWEEN :start_date AND :end_date
                            ORDER BY execution_datetime ASC
                            LIMIT :limit";

                    $rows = $this->db->fetchAll($sql, [
                        ':start_date' => $startDate,
                        ':end_date' => $endDate,
                        ':limit' => $limit
                    ]);

                    if (!empty($rows)) {
                        $candles = array_merge($candles, $rows);
                    }
                } catch (\Exception $e) {
                    continue;
                }
            }

            usort($candles, function ($left, $right) {
                return strcmp($left['execution_datetime'], $right['execution_datetime']);
            });

            if (count($candles) > $limit) {
                $candles = array_slice($candles, -$limit);
            }
            
            // timeframe에 따라 데이터 집계
            $candles = $this->aggregateCandlesByTimeframe($candles, $timeframe);
            
            $this->cache->set($cacheKey, $candles, 60); // 1분 캐시
            
            return $candles;
        } catch (\Exception $e) {
            // 테이블이 없거나 에러 발생 시 빈 배열 반환
            return [];
        }
    }

    /**
     * 실시간 체결 데이터 조회 (최근 N건)
     */
    public function getRecentExecutions(string $stockCode, int $limit = 100): array
    {
        $cacheKey = Cache::key('stock_executions', $stockCode, $limit);
        $cached = $this->cache->get($cacheKey);
        if ($cached !== null) {
            return $cached;
        }

        $dbName = $this->resolveStockDbName($stockCode);
        if ($dbName === null) {
            return [];
        }

        $year = date('Y');
        $tableName = "Raw{$year}";
        
        try {
            $sql = "SELECT execution_datetime, execution_price, 
                           execution_non_volume, execution_ask_volume, execution_bid_volume
                    FROM `{$dbName}`.`{$tableName}`
                    ORDER BY execution_datetime DESC
                    LIMIT :limit";
            
            $executions = $this->db->fetchAll($sql, [':limit' => $limit]);
            
            $this->cache->set($cacheKey, $executions, 10); // 10초 캐시
            
            return $executions;
        } catch (\Exception $e) {
            return [];
        }
    }

    /**
     * 시장별 주식 통계
     */
    public function getMarketStats(): array
    {
        $cacheKey = Cache::key('market_stats');
        $cached = $this->cache->get($cacheKey);
        if ($cached !== null) {
            return $cached;
        }

        $sql = "SELECT stock_market, COUNT(*) as stock_count, 
                       SUM(stock_capitalization) as total_cap
                FROM KoreaInvest.stock_info
                GROUP BY stock_market
                ORDER BY CASE stock_market
                    WHEN 'KOSPI' THEN 1
                    WHEN 'KOSDAQ' THEN 2
                    WHEN 'KONEX' THEN 3
                    WHEN 'NYSE' THEN 4
                    WHEN 'NASDAQ' THEN 5
                    WHEN 'AMEX' THEN 6
                    ELSE 99
                END";
        
        $stats = $this->db->fetchAll($sql);
        
        $this->cache->set($cacheKey, $stats, 600); // 10분 캐시
        
        return $stats;
    }

    /**
     * 인기 주식 목록 (시가총액 기준)
     */
    public function getTopStocks(int $limit = 10, string $market = ''): array
    {
        $cacheKey = Cache::key('top_stocks', $limit, $market);
        $cached = $this->cache->get($cacheKey);
        if ($cached !== null) {
            return $cached;
        }

        $whereSQL = $market !== '' ? 'WHERE stock_market = :market' : '';
        $params = $market !== '' ? [':market' => $market, ':limit' => $limit] : [':limit' => $limit];
        
        $sql = "SELECT stock_code, stock_name_kr, stock_name_en, stock_market, 
                       stock_price, stock_capitalization
                FROM KoreaInvest.stock_info
                $whereSQL
                ORDER BY stock_capitalization DESC
                LIMIT :limit";
        
        $stocks = $this->db->fetchAll($sql, $params);
        
        $this->cache->set($cacheKey, $stocks, 300); // 5분 캐시
        
        return $stocks;
    }

    /**
     * timeframe에 따라 캔들 데이터 집계
     * @param array $candles 원본 캔들 데이터
     * @param string $timeframe 시간 단위 (1h, 1d, 1w, 1M)
     * @return array 집계된 캔들 데이터
     */
    private function aggregateCandlesByTimeframe(array $candles, string $timeframe): array
    {
        if (empty($candles) || $timeframe === '1h') {
            return $candles; // 기본 데이터 그대로 반환
        }

        $aggregated = [];
        $currentGroup = null;
        $groupData = [];

        foreach ($candles as $candle) {
            $datetime = $candle['execution_datetime'];
            $groupKey = $this->getGroupKey($datetime, $timeframe);

            if ($currentGroup !== $groupKey) {
                // 이전 그룹 데이터 저장
                if (!empty($groupData)) {
                    $aggregated[] = $this->mergeCandles($groupData, $currentGroup);
                }
                // 새 그룹 시작
                $currentGroup = $groupKey;
                $groupData = [];
            }

            $groupData[] = $candle;
        }

        // 마지막 그룹 저장
        if (!empty($groupData)) {
            $aggregated[] = $this->mergeCandles($groupData, $currentGroup);
        }

        return $aggregated;
    }

    /**
     * timeframe에 따라 그룹 키 생성
     */
    private function getGroupKey(string $datetime, string $timeframe): string
    {
        $timestamp = strtotime($datetime);
        
        switch ($timeframe) {
            case '1d':
                return date('Y-m-d', $timestamp);
            case '1w':
                return date('Y-W', $timestamp); // 년도-주차
            case '1M':
                return date('Y-m', $timestamp);
            default:
                return $datetime;
        }
    }

    /**
     * 여러 캔들을 하나로 병합
     */
    private function mergeCandles(array $candles, string $datetime): array
    {
        if (empty($candles)) {
            return [];
        }

        $open = $candles[0]['execution_open'];
        $close = $candles[count($candles) - 1]['execution_close'];
        $high = max(array_column($candles, 'execution_max'));
        $low = min(array_column($candles, 'execution_min'));

        $totalNonVolume = array_sum(array_column($candles, 'execution_non_volume'));
        $totalAskVolume = array_sum(array_column($candles, 'execution_ask_volume'));
        $totalBidVolume = array_sum(array_column($candles, 'execution_bid_volume'));
        
        $totalNonAmount = array_sum(array_column($candles, 'execution_non_amount'));
        $totalAskAmount = array_sum(array_column($candles, 'execution_ask_amount'));
        $totalBidAmount = array_sum(array_column($candles, 'execution_bid_amount'));

        return [
            'execution_datetime' => $datetime,
            'execution_open' => $open,
            'execution_close' => $close,
            'execution_min' => $low,
            'execution_max' => $high,
            'execution_non_volume' => $totalNonVolume,
            'execution_ask_volume' => $totalAskVolume,
            'execution_bid_volume' => $totalBidVolume,
            'execution_non_amount' => $totalNonAmount,
            'execution_ask_amount' => $totalAskAmount,
            'execution_bid_amount' => $totalBidAmount,
        ];
    }
}
