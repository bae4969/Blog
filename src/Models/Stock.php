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

    /**
     * candle.s{Symbol} 소스 resolve
     * @return array{schema: string, table: string}|null
     */
    private function resolveCandleSource(string $stockCode): ?array
    {
        $cacheKey = Cache::key('stock_candle_source', $stockCode);
        $cached = $this->cache->get($cacheKey);
        if ($cached !== null) {
            return $cached ?: null;
        }

        $code = strtoupper($stockCode);
        $normalizedUnderscore = str_replace(['.', '/'], '_', $code);
        $normalizedNoDot = str_replace(['.', '/'], '', $code);

        $candidates = array_values(array_unique([
            's' . $code,
            's' . $normalizedUnderscore,
            's' . $normalizedNoDot,
        ]));

        // 후보가 3개 미만이면 패딩
        while (count($candidates) < 3) {
            $candidates[] = $candidates[count($candidates) - 1];
        }

        $row = $this->db->fetch(
            "SELECT TABLE_SCHEMA, TABLE_NAME
             FROM information_schema.TABLES
             WHERE TABLE_SCHEMA = 'candle'
               AND TABLE_NAME IN (:t1, :t2, :t3)
             LIMIT 1",
            [':t1' => $candidates[0], ':t2' => $candidates[1], ':t3' => $candidates[2]]
        );

        $source = null;
        if ($row) {
            $schema = $row['TABLE_SCHEMA'] ?? '';
            $table = $row['TABLE_NAME'] ?? '';
            if (preg_match('/^[A-Za-z0-9_]+$/', $schema) && preg_match('/^[A-Za-z0-9_]+$/', $table)) {
                $source = ['schema' => $schema, 'table' => $table];
            }
        }

        $this->cache->set($cacheKey, $source ?? '', 3600);
        return $source;
    }

    /**
     * tick.s{Symbol} 소스 resolve (체결 데이터용)
     * @return array{schema: string, table: string}|null
     */
    private function resolveTickSource(string $stockCode): ?array
    {
        $cacheKey = Cache::key('stock_tick_source', $stockCode);
        $cached = $this->cache->get($cacheKey);
        if ($cached !== null) {
            return $cached ?: null;
        }

        $code = strtoupper($stockCode);
        $normalizedUnderscore = str_replace(['.', '/'], '_', $code);
        $normalizedNoDot = str_replace(['.', '/'], '', $code);

        $candidates = array_values(array_unique([
            's' . $code,
            's' . $normalizedUnderscore,
            's' . $normalizedNoDot,
        ]));

        while (count($candidates) < 3) {
            $candidates[] = $candidates[count($candidates) - 1];
        }

        $row = $this->db->fetch(
            "SELECT TABLE_SCHEMA, TABLE_NAME
             FROM information_schema.TABLES
             WHERE TABLE_SCHEMA = 'tick'
               AND TABLE_NAME IN (:t1, :t2, :t3)
             LIMIT 1",
            [':t1' => $candidates[0], ':t2' => $candidates[1], ':t3' => $candidates[2]]
        );

        $source = null;
        if ($row) {
            $schema = $row['TABLE_SCHEMA'] ?? '';
            $table = $row['TABLE_NAME'] ?? '';
            if (preg_match('/^[A-Za-z0-9_]+$/', $schema) && preg_match('/^[A-Za-z0-9_]+$/', $table)) {
                $source = ['schema' => $schema, 'table' => $table];
            }
        }

        $this->cache->set($cacheKey, $source ?? '', 3600);
        return $source;
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

        $candleSource = $this->resolveCandleSource($stockCode);
        if ($candleSource === null) {
            return [];
        }

        $candles = $this->fetchCandlesWithExpansion($candleSource, $startDate, $endDate, $limit, $timeframe);
        
        $this->cache->set($cacheKey, $candles, 60); // 1분 캐시
        
        return $candles;
    }

    /**
     * 범위를 확장하며 캔들 데이터 조회 (limit에 미달하면 자동으로 이전 시간대 포함)
     * 단일 테이블(candle.s{Symbol})에서 날짜 범위만 조정하여 조회
     */
    private function fetchCandlesWithExpansion(array $candleSource, string $startDate, string $endDate, int $limit, string $timeframe): array
    {
        $currentStart = $startDate;
        $allRows = [];
        $maxAttempts = 5;
        $attemptCount = 0;
        $previousStart = $endDate;

        $tableRef = "`{$candleSource['schema']}`.`{$candleSource['table']}`";
        
        try {
            while ($attemptCount <= $maxAttempts) {
                $fetchStart = $currentStart;
                $fetchEnd = ($attemptCount === 0) ? $endDate : $previousStart;
                $newDataAdded = false;

                try {
                    $sql = "SELECT execution_datetime, execution_open, execution_close, execution_min, execution_max,
                                   execution_non_volume, execution_ask_volume, execution_bid_volume,
                                   execution_non_amount, execution_ask_amount, execution_bid_amount
                            FROM {$tableRef}
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
                    return [];
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

                if (count($candles) >= $limit) {
                    return array_slice($candles, -$limit);
                }

                if (!$newDataAdded && $attemptCount > 0) {
                    return $candles;
                }

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
     * 일봉 이상(1d, 1w, 1M)은 false 반환
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
        // 그 외 (1d, 1w, 1M) = daily 이상
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

        $tickSource = $this->resolveTickSource($stockCode);
        if ($tickSource === null) {
            return [];
        }

        try {
            $sql = "SELECT execution_datetime, execution_price,
                           execution_non_volume, execution_ask_volume, execution_bid_volume
                    FROM `{$tickSource['schema']}`.`{$tickSource['table']}`
                    ORDER BY execution_datetime DESC
                    LIMIT :limit";

            $executions = $this->db->fetchAll($sql, [':limit' => $limit]);

            if (!empty($executions)) {
                $this->cache->set($cacheKey, $executions, 10); // 10초 캐시
            }

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
     * candle 스키마의 테이블 목록을 일괄 조회 후 UNION ALL로 집계 (N+1 → 3회 쿼리)
     */
    private function getTopStocksByTradingAmount(int $limit, string $market): array
    {
        // 거래대금 합산 기간
        $lookbackDays = ($market !== '') ? 30 : 3;
        $lookback = date('Y-m-d', strtotime("-{$lookbackDays} days"));

        // 1) candle 스키마의 주식 테이블 목록 일괄 조회
        $candleTables = $this->db->fetchAll(
            "SELECT TABLE_NAME FROM information_schema.TABLES
             WHERE TABLE_SCHEMA = 'candle' AND TABLE_NAME LIKE 's%'"
        );
        if (empty($candleTables)) {
            return [];
        }
        $tableSet = [];
        foreach ($candleTables as $row) {
            $name = $row['TABLE_NAME'];
            if (preg_match('/^[A-Za-z0-9_]+$/', $name)) {
                $tableSet[$name] = true;
            }
        }

        // 2) 수집 중인 종목 코드 조회 (시장별 사전 필터링으로 불필요한 집계 제거)
        $wsSQL = "SELECT DISTINCT wsq.stock_code
                  FROM KoreaInvest.stock_last_ws_query wsq";
        $wsParams = [];
        if ($market !== '') {
            $wsSQL .= " INNER JOIN KoreaInvest.stock_info si ON wsq.stock_code = si.stock_code";
            if ($market === 'KR') {
                $wsSQL .= " WHERE si.stock_market IN ('KOSPI', 'KOSDAQ', 'KONEX')";
            } elseif ($market === 'US') {
                $wsSQL .= " WHERE si.stock_market IN ('NYSE', 'NASDAQ', 'AMEX')";
            } else {
                $wsSQL .= " WHERE UPPER(si.stock_market) = :market";
                $wsParams[':market'] = strtoupper(trim($market));
            }
        }
        $wsRows = $this->db->fetchAll($wsSQL, $wsParams);
        if (empty($wsRows)) {
            return [];
        }

        // 3) 종목코드 → 캔들 테이블 매핑 (PHP side, DB 쿼리 없음)
        $codeToTable = [];
        foreach ($wsRows as $row) {
            $code = $row['stock_code'] ?? '';
            if ($code === '') continue;

            $upper = strtoupper($code);
            $candidates = array_unique([
                's' . $upper,
                's' . str_replace(['.', '/'], '_', $upper),
                's' . str_replace(['.', '/'], '', $upper),
            ]);
            foreach ($candidates as $candidate) {
                if (isset($tableSet[$candidate])) {
                    $codeToTable[$code] = $candidate;
                    break;
                }
            }
        }

        if (empty($codeToTable)) {
            return [];
        }

        // 4) UNION ALL로 거래대금 일괄 집계 (N개 개별 쿼리 → 1회 쿼리)
        $unionParts = [];
        $safeLookback = date('Y-m-d', strtotime($lookback));
        foreach ($codeToTable as $code => $table) {
            $safeCode = str_replace("'", "''", $code);
            $unionParts[] = "SELECT '{$safeCode}' AS stock_code,
                                    COALESCE(SUM(execution_non_amount + execution_ask_amount + execution_bid_amount), 0) AS total_amount
                             FROM `candle`.`{$table}`
                             WHERE execution_datetime >= '{$safeLookback}'";
        }

        try {
            $unionSql = implode("\nUNION ALL\n", $unionParts);
            $aggregatedRows = $this->db->fetchAll($unionSql);
        } catch (\Exception $e) {
            return [];
        }

        $aggregated = [];
        foreach ($aggregatedRows as $row) {
            $amount = (float)($row['total_amount'] ?? 0);
            if ($amount > 0) {
                $aggregated[$row['stock_code']] = $amount;
            }
        }

        if (empty($aggregated)) {
            return [];
        }

        arsort($aggregated);
        $topCodes = array_slice(array_keys($aggregated), 0, max($limit * 3, 30));

        if (empty($topCodes)) {
            return [];
        }

        $codePlaceholders = [];
        $detailParams = [];
        foreach ($topCodes as $i => $code) {
            $ph = ':code' . $i;
            $codePlaceholders[] = $ph;
            $detailParams[$ph] = $code;
        }

        $detailSql = "SELECT si.stock_code,
                             si.stock_name_kr,
                             si.stock_name_en,
                             si.stock_market,
                             si.stock_price,
                             si.stock_capitalization
                      FROM KoreaInvest.stock_info si
                      WHERE si.stock_code IN (" . implode(', ', $codePlaceholders) . ")";

        $detailRows = $this->db->fetchAll($detailSql, $detailParams);
        if (empty($detailRows)) {
            return [];
        }

        $detailByCode = [];
        foreach ($detailRows as $row) {
            $detailByCode[$row['stock_code']] = $row;
        }

        $results = [];
        foreach ($aggregated as $code => $amount) {
            if (!isset($detailByCode[$code])) {
                continue;
            }
            $item = $detailByCode[$code];
            $item['total_amount'] = $amount;
            $results[] = $item;

            if (count($results) >= $limit) {
                break;
            }
        }

        // 부족하면 stock_info에서 시가총액 기준으로 보충
        if ($market !== '' && count($results) < $limit) {
            $need = $limit - count($results);
            $existingCodes = array_column($results, 'stock_code');

            $fillParams = [':limit_fill' => $need];
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

            if ($market === 'KR') {
                $marketFilter = "si.stock_market IN ('KOSPI', 'KOSDAQ', 'KONEX')";
            } elseif ($market === 'US') {
                $marketFilter = "si.stock_market IN ('NYSE', 'NASDAQ', 'AMEX')";
            } else {
                $marketFilter = "UPPER(si.stock_market) = :market_fill";
                $fillParams[':market_fill'] = strtoupper(trim($market));
            }

            $fillSql = "SELECT si.stock_code, 0 AS total_amount,
                               si.stock_name_kr, si.stock_name_en, si.stock_market,
                               si.stock_price, si.stock_capitalization
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
