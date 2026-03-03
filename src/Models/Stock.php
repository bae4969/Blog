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
     * limit에 미달하면 자동으로 이전 시간대를 포함해서 조회
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

        $candles = $this->fetchCandlesWithExpansion($dbName, $startDate, $endDate, $limit, $timeframe);
        
        $this->cache->set($cacheKey, $candles, 60); // 1분 캐시
        
        return $candles;
    }

    /**
     * 범위를 확장하며 캔들 데이터 조회 (limit에 미달하면 자동으로 이전 시간대 포함)
     */
    private function fetchCandlesWithExpansion(string $dbName, string $startDate, string $endDate, int $limit, string $timeframe): array
    {
        $currentStart = $startDate;
        $candles = [];
        $maxAttempts = 10;  // 최대 10번까지 단계적 확장 시도
        $attemptCount = 0;
        
        try {
            while (count($candles) < $limit && $attemptCount < $maxAttempts) {
                $candles = [];
                $queryStartYear = (int)date('Y', strtotime($currentStart));
                $queryEndYear = (int)date('Y', strtotime($endDate));

                for ($year = $queryStartYear; $year <= $queryEndYear; $year++) {
                    $tableName = "Candle{$year}";

                    try {
                        $sql = "SELECT execution_datetime, execution_open, execution_close, execution_min, execution_max,
                                       execution_non_volume, execution_ask_volume, execution_bid_volume,
                                       execution_non_amount, execution_ask_amount, execution_bid_amount
                                FROM `{$dbName}`.`{$tableName}`
                                WHERE execution_datetime BETWEEN :start_date AND :end_date
                                ORDER BY execution_datetime ASC";

                        $rows = $this->db->fetchAll($sql, [
                            ':start_date' => $currentStart,
                            ':end_date' => $endDate
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

                // 분봉/시간봉(sub-daily)만 정규장 시간대 필터링
                // 일봉 이상은 하루 전체 데이터를 집계해야 정확한 OHLC가 나옴
                if ($this->isSubDailyTimeframe($timeframe)) {
                    $candles = $this->filterRegularTradingHours($candles);
                    $candles = array_values($candles);
                }

                // 필터링된 데이터에 대해 timeframe 집계
                $candles = $this->aggregateCandlesByTimeframe($candles, $timeframe);

                // limit 이상 확보했으면 종료
                if (count($candles) >= $limit) {
                    break;
                }

                // 부족하면 start를 더 이전으로 확장
                $attemptCount++;
                $currentStart = $this->expandStartDateByTimeframe($currentStart, $timeframe);
            }

            // 10번 시도 후에도 부족하면 모든 가능한 데이터를 조회 (1900-01-01부터)
            if (count($candles) < $limit) {
                $candles = [];
                $queryStartYear = 1900;
                $queryEndYear = (int)date('Y', strtotime($endDate));

                for ($year = $queryStartYear; $year <= $queryEndYear; $year++) {
                    $tableName = "Candle{$year}";

                    try {
                        $sql = "SELECT execution_datetime, execution_open, execution_close, execution_min, execution_max,
                                       execution_non_volume, execution_ask_volume, execution_bid_volume,
                                       execution_non_amount, execution_ask_amount, execution_bid_amount
                                FROM `{$dbName}`.`{$tableName}`
                                WHERE execution_datetime <= :end_date
                                ORDER BY execution_datetime ASC";

                        $rows = $this->db->fetchAll($sql, [
                            ':end_date' => $endDate
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

                // 분봉/시간봉(sub-daily)만 정규장 시간대 필터링
                if ($this->isSubDailyTimeframe($timeframe)) {
                    $candles = $this->filterRegularTradingHours($candles);
                    $candles = array_values($candles);
                }

                // 필터링된 데이터에 대해 timeframe 집계
                $candles = $this->aggregateCandlesByTimeframe($candles, $timeframe);
            }

            // 최종적으로 limit개를 초과하면 마지막 limit개만 유지
            if (count($candles) > $limit) {
                $candles = array_slice($candles, -$limit);
            }

            return $candles;
        } catch (\Exception $e) {
            return [];
        }
    }

    /**
     * timeframe에 따라 조회 시작일을 더 이전 영업일로 확장 (한국 정규장: 9:00 ~ 15:30)
     */
    private function expandStartDateByTimeframe(string $startDate, string $timeframe): string
    {
        $date = new \DateTime($startDate);
        $businessDaysToMove = 1;

        if (preg_match('/^(\\d+)m$/', $timeframe, $matches)) {
            // 분봉: 하루에 약 330분(9:00~15:30) 거래 가능이므로, 60 구간 = 약 12일
            $businessDaysToMove = 12;
        } elseif (preg_match('/^(\\d+)h$/', $timeframe, $matches)) {
            // 시간봉: 하루에 약 6.5시간 거래 가능이므로, 60 구간 = 약 10일
            $businessDaysToMove = 10;
        } else {
            // 일/주/월 봉: 직접 설정
            switch ($timeframe) {
                case '1d':
                    // 60개 일봉 = 60 영업일
                    $businessDaysToMove = 60;
                    break;
                case '1w':
                    // 60개 주봉 = 60주 × 5영업일/주 = 300 영업일
                    $businessDaysToMove = 300;
                    break;
                case '1M':
                    // 60개 월봉 = 60개월 × 21영업일/월 ≈ 1260 영업일
                    $businessDaysToMove = 1260;
                    break;
                case '3M':
                    // 60개 분기봉 = 60분기 × 63영업일/분기 ≈ 3780 영업일
                    $businessDaysToMove = 3780;
                    break;
                case '1Y':
                    // 60개 연봉 = 60년 × 252영업일/년 ≈ 15120 영업일
                    $businessDaysToMove = 15120;
                    break;
                default:
                    $businessDaysToMove = 12;
                    break;
            }
        }

        // 이전 영업일로 이동
        $moveDays = 0;
        while ($moveDays < $businessDaysToMove) {
            $date->modify('-1 day');
            $dayOfWeek = (int)$date->format('w');  // 0=일, 1=월, ..., 6=토
            // 월~금만 카운트
            if ($dayOfWeek >= 1 && $dayOfWeek <= 5) {
                $moveDays++;
            }
        }

        // 정규장 시간대 시작 시점(9:00)으로 설정
        $date->setTime(9, 0, 0);
        return $date->format('Y-m-d H:i:s');
    }

    /**
     * sub-daily 타임프레임 여부 확인 (분봉, 시간봉)
     * 일봉 이상(1d, 1w, 1M, 3M, 1Y)은 false 반환
     */
    private function isSubDailyTimeframe(string $timeframe): bool
    {
        // 분봉 (10m, 30m 등)
        if (preg_match('/^\\d+m$/', $timeframe)) {
            return true;
        }
        // 시간봉 (1h, 3h, 6h 등)
        if (preg_match('/^\\d+h$/', $timeframe)) {
            return true;
        }
        // 그 외 (1d, 1w, 1M, 3M, 1Y) = daily 이상
        return false;
    }

    /**
     * 정규장 시간대(9:00 ~ 15:30) 필터링
     */
    private function filterRegularTradingHours(array $candles): array
    {
        return array_filter($candles, function ($candle) {
            $datetime = new \DateTime($candle['execution_datetime']);
            $hour = (int)$datetime->format('G');
            $minute = (int)$datetime->format('i');

            // 9:00 ~ 15:30 범위만 포함
            if ($hour < 9) {
                return false;  // 9시 이전 제외
            }
            if ($hour > 15 || ($hour === 15 && $minute > 30)) {
                return false;  // 15:30 이후 제외
            }
            
            // 월~금만 포함 (0=일, 6=토)
            $dayOfWeek = (int)$datetime->format('w');
            if ($dayOfWeek === 0 || $dayOfWeek === 6) {
                return false;  // 주말 제외
            }

            return true;
        });
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
     * 인기 주식 목록 (거래대금 기준)
     * 각 주식의 최근 캔들 데이터에서 거래대금 합계를 계산하여 순위를 매김
     */
    public function getTopStocks(int $limit = 10, string $market = ''): array
    {
        $cacheKey = Cache::key('top_stocks', $limit, $market);
        $cached = $this->cache->get($cacheKey);
        if ($cached !== null) {
            return $cached;
        }

        $stocks = $this->getTopStocksByTradingAmount($limit, $market);

        $this->cache->set($cacheKey, $stocks, 300); // 5분 캐시

        return $stocks;
    }

    /**
     * 거래대금 기준 상위 주식 조회
     * 모든 Z_Stock 데이터베이스의 최근 캔들 데이터를 UNION ALL로 집계
     */
    private function getTopStocksByTradingAmount(int $limit, string $market): array
    {
        $year = date('Y');

        // 현재 연도의 캔들 테이블을 가진 주식 데이터베이스 목록
        $dbs = $this->db->fetchAll(
            "SELECT TABLE_SCHEMA FROM information_schema.TABLES WHERE TABLE_NAME = :table AND TABLE_SCHEMA LIKE 'Z\\_Stock%'",
            [':table' => "Candle{$year}"]
        );

        if (empty($dbs)) {
            return [];
        }

        // 거래대금 합산 기간
        // - 전체 시장: 최근 3일(실시간성 우선)
        // - 시장 필터: 최근 30일(시장별 종목 수가 너무 적어지는 문제 방지)
        $lookbackDays = ($market !== '') ? 30 : 3;
        $lookback = date('Y-m-d', strtotime("-{$lookbackDays} days"));
        $unions = [];

        foreach ($dbs as $row) {
            $schema = $row['TABLE_SCHEMA'];
            // 스키마 이름 검증 (알파벳, 숫자, 언더스코어만 허용)
            if (!preg_match('/^Z_Stock[A-Za-z0-9_]+$/', $schema)) {
                continue;
            }
            $code = preg_replace('/^Z_Stock_?/', '', $schema);
            $unions[] = sprintf(
                "SELECT '%s' AS stock_code, COALESCE(SUM(execution_non_amount + execution_ask_amount + execution_bid_amount), 0) AS total_amount FROM `%s`.`Candle%s` WHERE execution_datetime >= '%s'",
                addslashes($code),
                $schema,
                $year,
                $lookback
            );
        }

        if (empty($unions)) {
            return [];
        }

        $fetchLimit = max($limit * 3, 30);
        $whereClauses = [
            'si.stock_code IS NOT NULL'
        ];
        $params = [];

        if ($market === '') {
            $whereClauses[] = 'sub.total_amount > 0';
        }

        if ($market !== '') {
            $whereClauses[] = 'UPPER(si.stock_market) = :market';
            $params[':market'] = strtoupper(trim($market));
        }

        $sql = "SELECT sub.stock_code, sub.total_amount,
                       si.stock_name_kr, si.stock_name_en, si.stock_market,
                       si.stock_price, si.stock_capitalization
                FROM (" . implode(' UNION ALL ', $unions) . ") sub
                LEFT JOIN KoreaInvest.stock_info si
                    ON si.stock_code = sub.stock_code
                    OR si.stock_code = REPLACE(sub.stock_code, '_', '.')
                WHERE " . implode(' AND ', $whereClauses) . "
                ORDER BY sub.total_amount DESC
                LIMIT {$fetchLimit}";

        $results = $this->db->fetchAll($sql, $params);

        // 시장 필터 시, 캔들 스키마 기반 결과가 부족하면 stock_info에서 보충
        if ($market !== '' && count($results) < $limit) {
            $need = $limit - count($results);
            $existingCodes = array_values(array_filter(array_map(static function ($row) {
                return $row['stock_code'] ?? null;
            }, $results)));

            $fillParams = [
                ':market_fill' => strtoupper(trim($market)),
                ':limit_fill' => $need,
            ];

            $excludeSql = '';
            if (!empty($existingCodes)) {
                $placeholders = [];
                foreach ($existingCodes as $idx => $code) {
                    $ph = ':exclude_' . $idx;
                    $placeholders[] = $ph;
                    $fillParams[$ph] = $code;
                }
                $excludeSql = ' AND stock_code NOT IN (' . implode(', ', $placeholders) . ')';
            }

            $fillSql = "SELECT stock_code,
                               0 AS total_amount,
                               stock_name_kr,
                               stock_name_en,
                               stock_market,
                               stock_price,
                               stock_capitalization
                        FROM KoreaInvest.stock_info
                        WHERE UPPER(stock_market) = :market_fill" . $excludeSql . "
                        ORDER BY stock_capitalization DESC
                        LIMIT :limit_fill";

            $fillRows = $this->db->fetchAll($fillSql, $fillParams);
            $results = array_merge($results, $fillRows);
        }

        return array_slice($results, 0, $limit);
    }

    /**
     * timeframe에 따라 캔들 데이터 집계
     * @param array $candles 원본 캔들 데이터
     * @param string $timeframe 시간 단위 (1h, 1d, 1w, 1M)
     * @return array 집계된 캔들 데이터
     */
    private function aggregateCandlesByTimeframe(array $candles, string $timeframe): array
    {
        if (empty($candles) || in_array($timeframe, ['10m', 'raw'], true)) {
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
                    $aggregated[] = $this->mergeCandles($groupData);
                }
                // 새 그룹 시작
                $currentGroup = $groupKey;
                $groupData = [];
            }

            $groupData[] = $candle;
        }

        // 마지막 그룹 저장
        if (!empty($groupData)) {
            $aggregated[] = $this->mergeCandles($groupData);
        }

        return $aggregated;
    }

    /**
     * timeframe에 따라 그룹 키 생성
     */
    private function getGroupKey(string $datetime, string $timeframe): string
    {
        $timestamp = strtotime($datetime);

        if (preg_match('/^(\\d+)m$/', $timeframe, $matches)) {
            $intervalMinutes = (int)$matches[1];
            if ($intervalMinutes > 0) {
                $minute = (int)date('i', $timestamp);
                $bucketMinute = (int)(floor($minute / $intervalMinutes) * $intervalMinutes);
                return date('Y-m-d H:', $timestamp) . str_pad((string)$bucketMinute, 2, '0', STR_PAD_LEFT) . ':00';
            }
        }

        if (preg_match('/^(\\d+)h$/', $timeframe, $matches)) {
            $intervalHours = (int)$matches[1];
            if ($intervalHours > 0) {
                $hour = (int)date('G', $timestamp);
                $bucketHour = (int)(floor($hour / $intervalHours) * $intervalHours);
                return date('Y-m-d ', $timestamp) . str_pad((string)$bucketHour, 2, '0', STR_PAD_LEFT) . ':00:00';
            }
        }
        
        switch ($timeframe) {
            case '1d':
                return date('Y-m-d', $timestamp);
            case '1w':
                return date('o-W', $timestamp); // ISO 년도-주차 (연경계 정확)
            case '1M':
                return date('Y-m', $timestamp);
            case '3M':
                $year = (int)date('Y', $timestamp);
                $month = (int)date('n', $timestamp);
                $quarter = (int)floor(($month - 1) / 3) + 1;
                return sprintf('%04d-Q%d', $year, $quarter);
            case '1Y':
                return date('Y', $timestamp);
            default:
                return $datetime;
        }
    }

    /**
     * 여러 캔들을 하나로 병합
     */
    private function mergeCandles(array $candles): array
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
            'execution_datetime' => $candles[0]['execution_datetime'],
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
