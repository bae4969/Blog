<?php

namespace Blog\Models;

use Blog\Database\Database;
use Blog\Core\Cache;

class Stock
{
    private $db;
    private $cache;

    /** @var array<string, ?string> 인메모리 DB 이름 캐시 */
    private static $dbNameCache = [];

    public function __construct()
    {
        $this->db = Database::getInstance();
        $this->cache = Cache::getInstance();
    }

    private function resolveStockDbName(string $stockCode): ?string
    {
        // 1) 인메모리 캐시 확인
        if (array_key_exists($stockCode, self::$dbNameCache)) {
            return self::$dbNameCache[$stockCode];
        }

        // 2) 파일 캐시 확인 (1시간 TTL)
        $cacheKey = Cache::key('stock_dbname', $stockCode);
        $cached = $this->cache->get($cacheKey);
        if ($cached !== null) {
            self::$dbNameCache[$stockCode] = $cached ?: null;
            return self::$dbNameCache[$stockCode];
        }

        // 3) information_schema 조회 - 한 번의 IN 쿼리로 처리
        $normalizedCode = str_replace('.', '_', $stockCode);
        $candidates = [
            'Z_Stock' . $normalizedCode,
            'Z_Stock_' . $normalizedCode,
        ];

        $result = $this->db->fetch(
            'SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME IN (:schema1, :schema2) LIMIT 1',
            [':schema1' => $candidates[0], ':schema2' => $candidates[1]]
        );

        $dbName = $result ? $result['SCHEMA_NAME'] : null;

        // 캐시 저장 (없는 경우도 빈 문자열로 저장하여 반복 조회 방지)
        $this->cache->set($cacheKey, $dbName ?? '', 3600);
        self::$dbNameCache[$stockCode] = $dbName;

        return $dbName;
    }

    /**
     * 주식 목록 조회 (페이징 지원)
     */
    public function getStockList(int $page = 1, int $perPage = 50, string $market = '', string $search = ''): array
    {
        $result = $this->getStockListWithCount($page, $perPage, $market, $search);
        return $result['stocks'];
    }

    /**
     * 주식 총 개수 조회
     */
    public function getStockCount(string $market = '', string $search = ''): int
    {
        $result = $this->getStockListWithCount(1, 50, $market, $search);
        return $result['total'];
    }

    /**
     * 주식 목록 + 총 개수를 한 번에 조회 (DB 라운드트립 1회로 감소)
     */
    public function getStockListWithCount(int $page = 1, int $perPage = 50, string $market = '', string $search = ''): array
    {
        $offset = ($page - 1) * $perPage;
        
        $cacheKey = Cache::key('stock_list_count', $page, $perPage, $market, $search);
        $cached = $this->cache->get($cacheKey);
        if ($cached !== null) {
            return $cached;
        }

        $params = [];
        $whereClauses = [];
        
        if ($market !== '') {
            if ($market === 'KR') {
                $whereClauses[] = "si.stock_market IN ('KOSPI', 'KOSDAQ', 'KONEX')";
            } elseif ($market === 'US') {
                $whereClauses[] = "si.stock_market IN ('NYSE', 'NASDAQ', 'AMEX')";
            } else {
                $whereClauses[] = 'si.stock_market = :market';
                $params[':market'] = $market;
            }
        }
        
        if ($search !== '') {
            $whereClauses[] = '(si.stock_code LIKE :search_code OR si.stock_name_kr LIKE :search_name_kr OR si.stock_name_en LIKE :search_name_en)';
            $searchValue = '%' . $search . '%';
            $params[':search_code'] = $searchValue;
            $params[':search_name_kr'] = $searchValue;
            $params[':search_name_en'] = $searchValue;
        }

        $whereSQL = !empty($whereClauses) ? 'WHERE ' . implode(' AND ', $whereClauses) : '';

        // stock_last_ws_query에 등록된 종목만 조회 (수집 중인 종목)
        $fromSQL = "KoreaInvest.stock_info si
                    INNER JOIN (SELECT DISTINCT stock_code FROM KoreaInvest.stock_last_ws_query) wsq
                        ON si.stock_code = wsq.stock_code";

        // COUNT 조회
        $countParams = $params; // LIMIT/OFFSET 없는 복사본
        $countSql = "SELECT COUNT(*) as count FROM $fromSQL $whereSQL";
        $countResult = $this->db->fetch($countSql, $countParams);
        $total = (int)($countResult['count'] ?? 0);

        // 목록 조회
        $sql = "SELECT si.stock_code, si.stock_name_kr, si.stock_name_en, si.stock_market, si.stock_type, 
                       si.stock_price, si.stock_capitalization, si.stock_count, si.stock_update
                FROM $fromSQL
                $whereSQL
                ORDER BY si.stock_capitalization DESC 
                LIMIT :limit OFFSET :offset";
        
        $params[':limit'] = $perPage;
        $params[':offset'] = $offset;
        
        $stocks = $this->db->fetchAll($sql, $params);
        
        $result = ['stocks' => $stocks, 'total' => $total];
        $this->cache->set($cacheKey, $result, 300); // 5분 캐시
        
        return $result;
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
     * 
     * 최적화: 매 확장마다 "새 구간"만 추가로 fetch하여 누적.
     * - 이미 조회한 날짜 범위는 재조회하지 않음 (연도 단위가 아닌 날짜 범위 기준)
     * - 존재하지 않는 Candle 테이블 접근 방지 (연도 목록 캐싱)
     * - 1900년 전체 스캔 fallback 제거
     */
    private function fetchCandlesWithExpansion(string $dbName, string $startDate, string $endDate, int $limit, string $timeframe): array
    {
        $currentStart = $startDate;
        $allRows = [];
        $maxAttempts = 5;
        $attemptCount = 0;
        // 이전에 조회한 시작점 (첫 시도에서는 endDate, 이후 확장 시 이전 시작점까지만 조회)
        $previousStart = $endDate;
        
        try {
            // 실존하는 Candle 테이블 연도 목록을 한 번에 조회
            $existingYears = $this->getExistingCandleYears($dbName);
            if (empty($existingYears)) {
                return [];
            }

            while ($attemptCount <= $maxAttempts) {
                // 조회할 범위 결정: 첫 시도는 전체 범위, 이후는 확장된 갭만
                $fetchStart = $currentStart;
                $fetchEnd = ($attemptCount === 0) ? $endDate : $previousStart;

                $queryStartYear = (int)date('Y', strtotime($fetchStart));
                $queryEndYear = (int)date('Y', strtotime($fetchEnd));
                $newDataAdded = false;

                for ($year = $queryStartYear; $year <= $queryEndYear; $year++) {
                    // 테이블이 없는 연도는 건너뜀
                    if (!in_array($year, $existingYears, true)) {
                        continue;
                    }

                    try {
                        $sql = "SELECT execution_datetime, execution_open, execution_close, execution_min, execution_max,
                                       execution_non_volume, execution_ask_volume, execution_bid_volume,
                                       execution_non_amount, execution_ask_amount, execution_bid_amount
                                FROM `{$dbName}`.`Candle{$year}`
                                WHERE execution_datetime BETWEEN :start_date AND :end_date
                                ORDER BY execution_datetime ASC";

                        $rows = $this->db->fetchAll($sql, [
                            ':start_date' => $fetchStart,
                            ':end_date' => $fetchEnd
                        ]);

                        if (!empty($rows)) {
                            $allRows = array_merge($allRows, $rows);
                            $newDataAdded = true;
                        }
                    } catch (\Exception $e) {
                        continue;
                    }
                }

                $previousStart = $fetchStart;

                // 정렬 (새 데이터 추가 시에만)
                if ($newDataAdded && count($allRows) > 1) {
                    usort($allRows, function ($left, $right) {
                        return strcmp($left['execution_datetime'], $right['execution_datetime']);
                    });
                }

                // 필터링 + 집계
                $candles = $allRows;
                if ($this->isSubDailyTimeframe($timeframe)) {
                    $candles = array_values($this->filterRegularTradingHours($candles));
                }
                $candles = $this->aggregateCandlesByTimeframe($candles, $timeframe);

                // limit 이상 확보했으면 종료
                if (count($candles) >= $limit) {
                    return array_slice($candles, -$limit);
                }

                // 새 데이터 없으면 더 이상 확장 해도 소용없음 → 종료
                if (!$newDataAdded && $attemptCount > 0) {
                    return $candles;
                }

                // 부족하면 start를 더 이전으로 확장
                $attemptCount++;
                $currentStart = $this->expandStartDateByTimeframe($currentStart, $timeframe);
            }

            // 마지막 결과 반환
            $candles = $allRows;
            if ($this->isSubDailyTimeframe($timeframe)) {
                $candles = array_values($this->filterRegularTradingHours($candles));
            }
            $candles = $this->aggregateCandlesByTimeframe($candles, $timeframe);

            return count($candles) > $limit ? array_slice($candles, -$limit) : $candles;
        } catch (\Exception $e) {
            return [];
        }
    }

    /**
     * 특정 주식 DB에 존재하는 Candle 테이블의 연도 목록 조회 (캐싱)
     */
    private function getExistingCandleYears(string $dbName): array
    {
        $cacheKey = Cache::key('stock_candle_years', $dbName);
        $cached = $this->cache->get($cacheKey);
        if ($cached !== null) {
            return $cached;
        }

        $rows = $this->db->fetchAll(
            "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = :schema AND TABLE_NAME LIKE 'Candle%'",
            [':schema' => $dbName]
        );

        $years = [];
        foreach ($rows as $row) {
            if (preg_match('/^Candle(\d{4})$/', $row['TABLE_NAME'], $m)) {
                $years[] = (int)$m[1];
            }
        }
        sort($years);

        $this->cache->set($cacheKey, $years, 3600); // 1시간 캐시
        return $years;
    }

    /**
     * 특정 주식 DB에 존재하는 Raw 테이블의 연도 목록 조회 (캐싱)
     */
    private function getExistingRawYears(string $dbName): array
    {
        $cacheKey = Cache::key('stock_raw_years', $dbName);
        $cached = $this->cache->get($cacheKey);
        if ($cached !== null) {
            return $cached;
        }

        $rows = $this->db->fetchAll(
            "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = :schema AND TABLE_NAME LIKE 'Raw%'",
            [':schema' => $dbName]
        );

        $years = [];
        foreach ($rows as $row) {
            if (preg_match('/^Raw(\d{4})$/', $row['TABLE_NAME'], $m)) {
                $years[] = (int)$m[1];
            }
        }
        sort($years);

        $this->cache->set($cacheKey, $years, 3600); // 1시간 캐시
        return $years;
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

        $year = (int)date('Y');
        
        // 현재 연도 → 이전 연도 순으로 Raw 테이블 조회 (아카이브 대응)
        $existingRawYears = $this->getExistingRawYears($dbName);
        $yearsToTry = [$year, $year - 1];
        
        try {
            foreach ($yearsToTry as $y) {
                if (!in_array($y, $existingRawYears, true)) {
                    continue;
                }

                $tableName = "Raw{$y}";
                $sql = "SELECT execution_datetime, execution_price, 
                               execution_non_volume, execution_ask_volume, execution_bid_volume
                        FROM `{$dbName}`.`{$tableName}`
                        ORDER BY execution_datetime DESC
                        LIMIT :limit";
                
                $executions = $this->db->fetchAll($sql, [':limit' => $limit]);
                
                if (!empty($executions)) {
                    $this->cache->set($cacheKey, $executions, 10); // 10초 캐시
                    return $executions;
                }
            }
            
            return [];
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

        $sql = "SELECT 
                    CASE 
                        WHEN si.stock_market IN ('KOSPI', 'KOSDAQ', 'KONEX') THEN 'KR'
                        WHEN si.stock_market IN ('NYSE', 'NASDAQ', 'AMEX') THEN 'US'
                        ELSE 'ETC'
                    END AS market_group,
                    CASE 
                        WHEN si.stock_market IN ('KOSPI', 'KOSDAQ', 'KONEX') THEN '한국'
                        WHEN si.stock_market IN ('NYSE', 'NASDAQ', 'AMEX') THEN '미국'
                        ELSE '기타'
                    END AS market_label,
                    COUNT(*) as stock_count, 
                    SUM(si.stock_capitalization) as total_cap
                FROM KoreaInvest.stock_info si
                INNER JOIN (SELECT DISTINCT stock_code FROM KoreaInvest.stock_last_ws_query) wsq
                    ON si.stock_code = wsq.stock_code
                GROUP BY market_group, market_label
                ORDER BY CASE 
                    WHEN si.stock_market IN ('KOSPI', 'KOSDAQ', 'KONEX') THEN 1
                    WHEN si.stock_market IN ('NYSE', 'NASDAQ', 'AMEX') THEN 2
                    ELSE 99
                END";
        
        $stats = $this->db->fetchAll($sql);
        
        $this->cache->set($cacheKey, $stats, 1800); // 30분 캐시 (시장 통계는 변경이 드묾)
        
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

        $this->cache->set($cacheKey, $stocks, 600); // 10분 캐시

        return $stocks;
    }

    /**
     * 거래대금 기준 상위 주식 조회
     * 모든 Z_Stock 데이터베이스의 최근 캔들 데이터를 UNION ALL로 집계
     */
    private function getTopStocksByTradingAmount(int $limit, string $market): array
    {
        $year = date('Y');

        // 수집 중인 종목 코드 목록 조회 (stock_last_ws_query 기준)
        $wsCacheKey = Cache::key('stock_ws_query_codes');
        $wsCodes = $this->cache->get($wsCacheKey);
        if ($wsCodes === null) {
            $wsRows = $this->db->fetchAll("SELECT DISTINCT stock_code FROM KoreaInvest.stock_last_ws_query");
            $wsCodes = array_map(function ($r) { return $r['stock_code']; }, $wsRows);
            $this->cache->set($wsCacheKey, $wsCodes, 600); // 10분 캐시
        }

        // 현재 연도의 캔들 테이블을 가진 주식 데이터베이스 목록 (캐싱)
        $dbsCacheKey = Cache::key('stock_dbs_with_candle', $year);
        $dbs = $this->cache->get($dbsCacheKey);
        if ($dbs === null) {
            $dbs = $this->db->fetchAll(
                "SELECT TABLE_SCHEMA FROM information_schema.TABLES WHERE TABLE_NAME = :table AND TABLE_SCHEMA LIKE 'Z\\_Stock%'",
                [':table' => "Candle{$year}"]
            );
            $this->cache->set($dbsCacheKey, $dbs, 3600); // 1시간 캐시
        }

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

            // 수집 중인 종목만 포함 (stock_last_ws_query에 등록된 것)
            $codeWithDot = str_replace('_', '.', $code);
            if (!in_array($code, $wsCodes, true) && !in_array($codeWithDot, $wsCodes, true)) {
                continue;
            }
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
            if ($market === 'KR') {
                $whereClauses[] = "si.stock_market IN ('KOSPI', 'KOSDAQ', 'KONEX')";
            } elseif ($market === 'US') {
                $whereClauses[] = "si.stock_market IN ('NYSE', 'NASDAQ', 'AMEX')";
            } else {
                $whereClauses[] = 'UPPER(si.stock_market) = :market';
                $params[':market'] = strtoupper(trim($market));
            }
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
                $excludeSql = ' AND si.stock_code NOT IN (' . implode(', ', $placeholders) . ')';
            }

            // 한국/미국 그룹 필터
            if ($market === 'KR') {
                $marketFilter = "si.stock_market IN ('KOSPI', 'KOSDAQ', 'KONEX')";
            } elseif ($market === 'US') {
                $marketFilter = "si.stock_market IN ('NYSE', 'NASDAQ', 'AMEX')";
            } else {
                $marketFilter = "UPPER(si.stock_market) = :market_fill";
                $fillParams[':market_fill'] = strtoupper(trim($market));
            }

            $fillSql = "SELECT si.stock_code,
                               0 AS total_amount,
                               si.stock_name_kr,
                               si.stock_name_en,
                               si.stock_market,
                               si.stock_price,
                               si.stock_capitalization
                        FROM KoreaInvest.stock_info si
                        INNER JOIN (SELECT DISTINCT stock_code FROM KoreaInvest.stock_last_ws_query) wsq
                            ON si.stock_code = wsq.stock_code
                        WHERE " . $marketFilter . $excludeSql . "
                        ORDER BY si.stock_capitalization DESC
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
