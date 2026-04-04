<?php

namespace Blog\Models;

use Blog\Database\Database;
use Blog\Core\Cache;

class Stock
{
    private $db;
    private $cache;
    private $config;

    public function __construct()
    {
        $this->db = Database::getInstance();
        $this->cache = Cache::getInstance();
        $this->config = require __DIR__ . '/../../config/config.php';
    }

    /**
     * 코인 코드 여부 판별 (Bithumb.coin_info 존재 확인, 캐시)
     */
    public function isCoinCode(string $code): bool
    {
        $cacheKey = Cache::key('coin_code_set');
        $coinSet = $this->cache->get($cacheKey);
        if ($coinSet === null) {
            $rows = $this->db->fetchAll("SELECT coin_code FROM Bithumb.coin_info");
            $coinSet = [];
            foreach ($rows as $row) {
                $coinSet[$row['coin_code']] = true;
            }
            $this->cache->set($cacheKey, $coinSet, $this->cache->getTtl('coin_code_set'));
        }
        return isset($coinSet[$code]);
    }

    /**
     * 주식/코인 여부를 market 힌트와 stock_info 존재 여부로 판별
     * stock_info에 존재하는 코드는 주식 우선 (코인과 코드가 겹치는 경우 대응)
     */
    private function resolveIsCoin(string $stockCode, string $market): bool
    {
        if ($market === 'COIN') {
            return true;
        }
        if ($market !== '') {
            return false;
        }

        $cacheKey = Cache::key('stock_code_exists', $stockCode);
        $exists = $this->cache->get($cacheKey);
        if ($exists === null) {
            $row = $this->db->fetch(
                "SELECT 1 FROM KoreaInvest.stock_info WHERE stock_code = :code LIMIT 1",
                [':code' => $stockCode]
            );
            $exists = ($row !== false && $row !== null);
            $this->cache->set($cacheKey, $exists, $this->cache->getTtl('stock_code_exists'));
        }

        if ($exists) {
            return false;
        }

        return $this->isCoinCode($stockCode);
    }

    /**
     * candle 스키마 소스 resolve (주식: s{Symbol}, 코인: c{Symbol})
     * @return array{schema: string, table: string}|null
     */
    private function resolveCandleSource(string $stockCode, string $prefix = 's'): ?array
    {
        $cacheKey = Cache::key('stock_candle_source', $prefix, $stockCode);
        $cached = $this->cache->get($cacheKey);
        if ($cached !== null) {
            return $cached ?: null;
        }

        $code = strtoupper($stockCode);
        $normalizedUnderscore = str_replace(['.', '/'], '_', $code);
        $normalizedNoDot = str_replace(['.', '/'], '', $code);

        $candidates = array_values(array_unique([
            $prefix . $code,
            $prefix . $normalizedUnderscore,
            $prefix . $normalizedNoDot,
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

        $this->cache->set($cacheKey, $source ?? '', $this->cache->getTtl('stock_candle_source'));
        return $source;
    }

    /**
     * tick 스키마 소스 resolve (주식: s{Symbol}, 코인: c{Symbol})
     * @return array{schema: string, table: string}|null
     */
    private function resolveTickSource(string $stockCode, string $prefix = 's'): ?array
    {
        $cacheKey = Cache::key('stock_tick_source', $prefix, $stockCode);
        $cached = $this->cache->get($cacheKey);
        if ($cached !== null) {
            return $cached ?: null;
        }

        $code = strtoupper($stockCode);
        $normalizedUnderscore = str_replace(['.', '/'], '_', $code);
        $normalizedNoDot = str_replace(['.', '/'], '', $code);

        $candidates = array_values(array_unique([
            $prefix . $code,
            $prefix . $normalizedUnderscore,
            $prefix . $normalizedNoDot,
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

        $this->cache->set($cacheKey, $source ?? '', $this->cache->getTtl('stock_tick_source'));
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

    public function getAdminStockListWithCount(int $page = 1, int $perPage = 100, string $market = 'KR', string $search = ''): array
    {
        $market = strtoupper(trim($market));
        $offset = ($page - 1) * $perPage;

        $cacheKey = Cache::key('stock_admin_list', $page, $perPage, $market, $search);
        $cached = $this->cache->get($cacheKey);
        if ($cached !== null) {
            return $cached;
        }

        $result = ($market === 'COIN')
            ? $this->getAdminCoinListWithCount($offset, $perPage, $search)
            : $this->getAdminMarketStockListWithCount($offset, $perPage, $market, $search);

        $this->cache->set($cacheKey, $result, $this->cache->getTtl('stock_admin_list'));

        return $result;
    }

    public function getRegisteredStockCodeSet(): array
    {
        $cacheKey = Cache::key('stock_admin_registered');
        $cached = $this->cache->get($cacheKey);
        if ($cached !== null) {
            return $cached;
        }

        $rows = $this->db->fetchAll(
            "SELECT CONCAT('STOCK:', stock_code) AS selection_key
             FROM KoreaInvest.stock_last_ws_query
             UNION
             SELECT CONCAT('COIN:', coin_code) AS selection_key
             FROM Bithumb.coin_last_ws_query"
        );

        $set = [];
        foreach ($rows as $row) {
            if (!empty($row['selection_key'])) {
                $set[$row['selection_key']] = true;
            }
        }

        $this->cache->set($cacheKey, $set, $this->cache->getTtl('stock_admin_registered'));

        return $set;
    }

    public function getSelectionMarketMap(): array
    {
        $cacheKey = Cache::key('stock_admin_market_map');
        $cached = $this->cache->get($cacheKey);
        if ($cached !== null) {
            return $cached;
        }

        $map = [];

        $stockRows = $this->db->fetchAll(
            "SELECT stock_code, stock_market
             FROM KoreaInvest.stock_info"
        );
        foreach ($stockRows as $row) {
            $stockCode = strtoupper((string)($row['stock_code'] ?? ''));
            if ($stockCode === '') {
                continue;
            }

            $map['STOCK:' . $stockCode] = $this->normalizeSelectionMarket((string)($row['stock_market'] ?? ''));
        }

        $coinRows = $this->db->fetchAll(
            "SELECT coin_code
             FROM Bithumb.coin_info"
        );
        foreach ($coinRows as $row) {
            $coinCode = strtoupper((string)($row['coin_code'] ?? ''));
            if ($coinCode === '') {
                continue;
            }

            $map['COIN:' . $coinCode] = 'COIN';
        }

        $this->cache->set($cacheKey, $map, $this->cache->getTtl('stock_admin_market_map'));

        return $map;
    }

    public function getRegisteredCountsByMarket(): array
    {
        $registeredSet = $this->getRegisteredStockCodeSet();
        $selectionMarketMap = $this->getSelectionMarketMap();

        return $this->countSelectionKeysByMarket(array_keys($registeredSet), $selectionMarketMap);
    }

    public function replaceRegisteredSubscriptions(array $selectedCodes): array
    {
        [$stockCodes, $coinCodes] = $this->partitionSubscriptionSelections($selectedCodes);

        $validStocks = $this->fetchValidStockMarkets($stockCodes);
        $this->validateMarketSubscriptionLimits($validStocks);
        $validCoins = $this->fetchValidCoinCodes($coinCodes);
        $stockCountsByMarket = $this->countStocksByRegion($validStocks);

        $stockRows = [];
        foreach ($validStocks as $stockCode => $stockMarket) {
            $queryType = 'EX';
            [$apiCode, $apiKey] = $this->buildStockApiMapping($stockCode, $stockMarket);
            $stockRows[] = [
                $this->buildSubscriptionQueryKey($queryType, $stockCode),
                $stockCode,
                $queryType,
                $apiCode,
                $apiKey,
            ];
        }

        $coinRows = [];
        foreach ($validCoins as $coinCode) {
            $queryType = 'EX';
            $coinRows[] = [
                $this->buildSubscriptionQueryKey($queryType, $coinCode),
                $coinCode,
                $queryType,
                'transaction',
                $coinCode . '_KRW',
            ];
        }

        $connection = $this->db->getConnection();
        $connection->beginTransaction();

        try {
            $this->db->query('DELETE FROM KoreaInvest.stock_last_ws_query');
            $this->db->query('DELETE FROM Bithumb.coin_last_ws_query');

            if (!empty($stockRows)) {
                $this->insertStockSubscriptionRows($stockRows);
            }

            if (!empty($coinRows)) {
                $this->insertCoinSubscriptionRows($coinRows);
            }

            $connection->commit();
        } catch (\Throwable $e) {
            if ($connection->inTransaction()) {
                $connection->rollBack();
            }
            throw $e;
        }

        $this->invalidateSubscriptionCaches();

        return [
            'stock_count' => count($stockRows),
            'kr_count' => $stockCountsByMarket['KR'],
            'us_count' => $stockCountsByMarket['US'],
            'coin_count' => count($coinRows),
        ];
    }

    private function countStocksByRegion(array $validStocks): array
    {
        $counts = [
            'KR' => 0,
            'US' => 0,
        ];

        foreach ($validStocks as $stockMarket) {
            if (in_array($stockMarket, ['KOSPI', 'KOSDAQ', 'KONEX'], true)) {
                $counts['KR']++;
                continue;
            }

            if (in_array($stockMarket, ['NYSE', 'NASDAQ', 'AMEX'], true)) {
                $counts['US']++;
            }
        }

        return $counts;
    }

    private function validateMarketSubscriptionLimits(array $validStocks): void
    {
        $limits = $this->getMarketSubscriptionLimits();
        $krCount = 0;
        $usCount = 0;

        foreach ($validStocks as $stockMarket) {
            if (in_array($stockMarket, ['KOSPI', 'KOSDAQ', 'KONEX'], true)) {
                $krCount++;
                continue;
            }

            if (in_array($stockMarket, ['NYSE', 'NASDAQ', 'AMEX'], true)) {
                $usCount++;
            }
        }

        if ($krCount > $limits['kr']) {
            throw new \InvalidArgumentException(
                sprintf('한국 종목은 최대 %d개까지 저장할 수 있습니다. (현재 선택: %d개)', $limits['kr'], $krCount)
            );
        }

        if ($usCount > $limits['us']) {
            throw new \InvalidArgumentException(
                sprintf('미국 종목은 최대 %d개까지 저장할 수 있습니다. (현재 선택: %d개)', $limits['us'], $usCount)
            );
        }
    }

    private function getMarketSubscriptionLimits(): array
    {
        $limitConfig = $this->config['stock_admin_limits'] ?? [];
        $kr = isset($limitConfig['kr_max_subscriptions']) ? (int)$limitConfig['kr_max_subscriptions'] : 400;
        $us = isset($limitConfig['us_max_subscriptions']) ? (int)$limitConfig['us_max_subscriptions'] : 400;

        return [
            'kr' => max(1, $kr),
            'us' => max(1, $us),
        ];
    }

    private function countSelectionKeysByMarket(array $selectionKeys, array $selectionMarketMap): array
    {
        $counts = [
            'KR' => 0,
            'US' => 0,
            'COIN' => 0,
        ];

        foreach ($selectionKeys as $selectionKey) {
            $market = $selectionMarketMap[$selectionKey] ?? null;
            if ($market === null || !isset($counts[$market])) {
                continue;
            }

            $counts[$market]++;
        }

        return $counts;
    }

    private function normalizeSelectionMarket(string $stockMarket): string
    {
        $stockMarket = strtoupper(trim($stockMarket));

        if (in_array($stockMarket, ['KOSPI', 'KOSDAQ', 'KONEX'], true)) {
            return 'KR';
        }

        if (in_array($stockMarket, ['NYSE', 'NASDAQ', 'AMEX'], true)) {
            return 'US';
        }

        return 'KR';
    }

    /**
     * 주식/코인 목록 + 총 개수를 한 번에 조회 (DB 라운드트립 1회로 감소)
     */
    public function getStockListWithCount(int $page = 1, int $perPage = 50, string $market = '', string $search = ''): array
    {
        $offset = ($page - 1) * $perPage;
        
        $cacheKey = Cache::key('stock_list_count', $page, $perPage, $market, $search);
        $cached = $this->cache->get($cacheKey);
        if ($cached !== null) {
            return $cached;
        }

        // 코인 시장은 별도 쿼리
        if ($market === 'COIN') {
            return $this->getCoinListWithCount($page, $perPage, $search);
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
        $stocks = $this->applyLatestCloseToStockRows($stocks, '');
        
        $result = ['stocks' => $stocks, 'total' => $total];
        $this->cache->set($cacheKey, $result, $this->cache->getTtl('stock_list_count'));
        
        return $result;
    }

    /**
     * 코인 목록 + 총 개수 조회 (Bithumb.coin_info)
     */
    private function getCoinListWithCount(int $page, int $perPage, string $search): array
    {
        $offset = ($page - 1) * $perPage;

        $cacheKey = Cache::key('coin_list_count', $page, $perPage, $search);
        $cached = $this->cache->get($cacheKey);
        if ($cached !== null) {
            return $cached;
        }

        $params = [];
        $whereClauses = [];

        if ($search !== '') {
            $whereClauses[] = '(ci.coin_code LIKE :search_code OR ci.coin_name_kr LIKE :search_name_kr OR ci.coin_name_en LIKE :search_name_en)';
            $searchValue = '%' . $search . '%';
            $params[':search_code'] = $searchValue;
            $params[':search_name_kr'] = $searchValue;
            $params[':search_name_en'] = $searchValue;
        }

        $whereSQL = !empty($whereClauses) ? 'WHERE ' . implode(' AND ', $whereClauses) : '';

        $fromSQL = "Bithumb.coin_info ci
                    INNER JOIN (SELECT DISTINCT coin_code FROM Bithumb.coin_last_ws_query) cwq
                        ON ci.coin_code = cwq.coin_code";

        $countResult = $this->db->fetch("SELECT COUNT(*) as count FROM $fromSQL $whereSQL", $params);
        $total = (int)($countResult['count'] ?? 0);

        $sql = "SELECT ci.coin_code AS stock_code,
                       ci.coin_name_kr AS stock_name_kr,
                       ci.coin_name_en AS stock_name_en,
                       'Bithumb' AS stock_market,
                       'COIN' AS stock_type,
                       ci.coin_price AS stock_price,
                       (ci.coin_price * ci.coin_amount) AS stock_capitalization,
                       ci.coin_amount AS stock_count,
                       ci.coin_update AS stock_update
                FROM $fromSQL
                $whereSQL
                ORDER BY (ci.coin_price * ci.coin_amount) DESC
                LIMIT :limit OFFSET :offset";

        $params[':limit'] = $perPage;
        $params[':offset'] = $offset;

        $stocks = $this->db->fetchAll($sql, $params);
        $stocks = $this->applyLatestCloseToStockRows($stocks, 'COIN');

        $result = ['stocks' => $stocks, 'total' => $total];
        $this->cache->set($cacheKey, $result, $this->cache->getTtl('coin_list_count'));

        return $result;
    }

    private function getAdminMarketStockListWithCount(int $offset, int $perPage, string $market, string $search): array
    {
        $params = [];
        $whereClauses = [];

        if ($market === 'KR') {
            $whereClauses[] = "si.stock_market IN ('KOSPI', 'KOSDAQ', 'KONEX')";
        } elseif ($market === 'US') {
            $whereClauses[] = "si.stock_market IN ('NYSE', 'NASDAQ', 'AMEX')";
        }

        $this->appendAdminSearchConditions(
            $whereClauses,
            $params,
            'si.stock_code',
            ['si.stock_name_kr', 'si.stock_name_en'],
            $search,
            'stock_admin'
        );

        $whereSql = !empty($whereClauses) ? 'WHERE ' . implode(' AND ', $whereClauses) : '';
        $fromSql = "KoreaInvest.stock_info si
                    LEFT JOIN (
                        SELECT DISTINCT stock_code
                        FROM KoreaInvest.stock_last_ws_query
                    ) wsq ON si.stock_code = wsq.stock_code";

        $countRow = $this->db->fetch("SELECT COUNT(*) AS count FROM {$fromSql} {$whereSql}", $params);
        $total = (int)($countRow['count'] ?? 0);

        $sql = "SELECT si.stock_code,
                       si.stock_name_kr,
                       si.stock_name_en,
                       si.stock_market,
                       si.stock_type,
                       si.stock_price,
                       si.stock_capitalization,
                       si.stock_count,
                       si.stock_update,
                       'STOCK' AS asset_group,
                       CASE WHEN wsq.stock_code IS NULL THEN 0 ELSE 1 END AS is_registered
                FROM {$fromSql}
                {$whereSql}
                ORDER BY is_registered DESC, si.stock_market ASC, si.stock_capitalization DESC, si.stock_code ASC
                LIMIT :limit OFFSET :offset";

        $params[':limit'] = $perPage;
        $params[':offset'] = $offset;

        $stocks = $this->db->fetchAll($sql, $params);
        $stocks = $this->applyLatestCloseToStockRows($stocks, '');

        return ['stocks' => $stocks, 'total' => $total];
    }

    private function getAdminCoinListWithCount(int $offset, int $perPage, string $search): array
    {
        $params = [];
        $whereClauses = [];

        $this->appendAdminSearchConditions(
            $whereClauses,
            $params,
            'ci.coin_code',
            ['ci.coin_name_kr', 'ci.coin_name_en'],
            $search,
            'coin_admin'
        );

        $whereSql = !empty($whereClauses) ? 'WHERE ' . implode(' AND ', $whereClauses) : '';
        $fromSql = "Bithumb.coin_info ci
                    LEFT JOIN (
                        SELECT DISTINCT coin_code
                        FROM Bithumb.coin_last_ws_query
                    ) cwq ON ci.coin_code = cwq.coin_code";

        $countRow = $this->db->fetch("SELECT COUNT(*) AS count FROM {$fromSql} {$whereSql}", $params);
        $total = (int)($countRow['count'] ?? 0);

        $sql = "SELECT ci.coin_code AS stock_code,
                       ci.coin_name_kr AS stock_name_kr,
                       ci.coin_name_en AS stock_name_en,
                       'Bithumb' AS stock_market,
                       'COIN' AS stock_type,
                       ci.coin_price AS stock_price,
                       (ci.coin_price * ci.coin_amount) AS stock_capitalization,
                       ci.coin_amount AS stock_count,
                       ci.coin_update AS stock_update,
                       'COIN' AS asset_group,
                       CASE WHEN cwq.coin_code IS NULL THEN 0 ELSE 1 END AS is_registered
                FROM {$fromSql}
                {$whereSql}
                ORDER BY is_registered DESC, (ci.coin_price * ci.coin_amount) DESC, ci.coin_code ASC
                LIMIT :limit OFFSET :offset";

        $params[':limit'] = $perPage;
        $params[':offset'] = $offset;

        $coins = $this->db->fetchAll($sql, $params);
        $coins = $this->applyLatestCloseToStockRows($coins, 'COIN');

        return ['stocks' => $coins, 'total' => $total];
    }

    private function appendAdminSearchConditions(
        array &$whereClauses,
        array &$params,
        string $codeColumn,
        array $nameColumns,
        string $search,
        string $prefix
    ): void {
        $search = trim($search);
        if ($search === '') {
            return;
        }

        $terms = $this->splitSearchTerms($search);
        $searchParts = [];
        $params[":{$prefix}_code"] = $search . '%';
        $searchParts[] = "{$codeColumn} LIKE :{$prefix}_code";

        if (!empty($terms)) {
            $nameTermClauses = [];
            foreach ($terms as $index => $term) {
                $termClauses = [];
                foreach ($nameColumns as $columnIndex => $column) {
                    $paramName = sprintf(':%s_term_%d_%d', $prefix, $index, $columnIndex);
                    $params[$paramName] = '%' . $term . '%';
                    $termClauses[] = "{$column} LIKE {$paramName}";
                }
                $nameTermClauses[] = '(' . implode(' OR ', $termClauses) . ')';
            }
            $searchParts[] = '(' . implode(' AND ', $nameTermClauses) . ')';
        }

        $whereClauses[] = '(' . implode(' OR ', $searchParts) . ')';
    }

    private function splitSearchTerms(string $search): array
    {
        $search = str_replace("'", '', trim($search));
        $terms = preg_split('/\s+/', $search) ?: [];
        $terms = array_values(array_filter(array_map('trim', $terms)));
        return array_slice($terms, 0, 5);
    }

    private function partitionSubscriptionSelections(array $selectedCodes): array
    {
        $stockCodes = [];
        $coinCodes = [];

        foreach ($selectedCodes as $value) {
            if (!preg_match('/^(STOCK|COIN):([A-Za-z0-9._\/-]{1,32})$/i', (string)$value, $matches)) {
                continue;
            }

            $type = strtoupper($matches[1]);
            $code = strtoupper($matches[2]);

            if ($type === 'STOCK') {
                $stockCodes[$code] = true;
                continue;
            }

            $coinCodes[$code] = true;
        }

        return [array_keys($stockCodes), array_keys($coinCodes)];
    }

    private function fetchValidStockMarkets(array $stockCodes): array
    {
        if (empty($stockCodes)) {
            return [];
        }

        $placeholders = implode(', ', array_fill(0, count($stockCodes), '?'));
        $rows = $this->db->fetchAll(
            "SELECT stock_code, stock_market
             FROM KoreaInvest.stock_info
                         WHERE stock_code IN ({$placeholders})",
            $stockCodes
        );

        $result = [];
        foreach ($rows as $row) {
            $result[strtoupper($row['stock_code'])] = strtoupper($row['stock_market']);
        }

        return $result;
    }

    private function fetchValidCoinCodes(array $coinCodes): array
    {
        if (empty($coinCodes)) {
            return [];
        }

        $placeholders = implode(', ', array_fill(0, count($coinCodes), '?'));
        $rows = $this->db->fetchAll(
            "SELECT coin_code
             FROM Bithumb.coin_info
                         WHERE coin_code IN ({$placeholders})",
            $coinCodes
        );

        $result = [];
        foreach ($rows as $row) {
            $result[] = strtoupper($row['coin_code']);
        }

        return $result;
    }

    private function buildStockApiMapping(string $stockCode, string $stockMarket): array
    {
        switch (strtoupper($stockMarket)) {
            case 'NYSE':
                return ['HDFSCNT0', 'DNYS' . $stockCode];
            case 'NASDAQ':
                return ['HDFSCNT0', 'DNAS' . $stockCode];
            case 'AMEX':
                return ['HDFSCNT0', 'DAMS' . $stockCode];
            default:
                return ['H0STCNT0', $stockCode];
        }
    }

    private function buildSubscriptionQueryKey(string $queryType, string $queryCode): string
    {
        $normalizedType = strtoupper(trim($queryType));
        $normalizedType = preg_replace('/[^A-Z0-9_]+/', '', $normalizedType);
        $normalizedType = trim((string)$normalizedType, '_');
        if ($normalizedType === '') {
            $normalizedType = 'EX';
        }

        $normalizedCode = strtoupper($queryCode);
        $normalizedCode = str_replace(['/', '.'], '_', $normalizedCode);
        $normalizedCode = preg_replace('/[^A-Z0-9_]+/', '', $normalizedCode);
        $normalizedCode = trim((string)$normalizedCode, '_');

        if ($normalizedCode === '') {
            $normalizedCode = 'UNKNOWN';
        }

        // query 컬럼은 varchar(32): {query_type}_{query_code}
        // 타입 + '_' 길이만큼 제외하고 code를 잘라 길이 제한을 맞춘다.
        $maxCodeLength = max(1, 32 - (strlen($normalizedType) + 1));
        return $normalizedType . '_' . substr($normalizedCode, 0, $maxCodeLength);
    }

    private function insertStockSubscriptionRows(array $rows): void
    {
        $valueGroups = [];
        $params = [];
        foreach ($rows as $row) {
            $valueGroups[] = '(?, ?, ?, ?, ?)';
            foreach ($row as $value) {
                $params[] = $value;
            }
        }

        $sql = 'INSERT INTO KoreaInvest.stock_last_ws_query (stock_query, stock_code, query_type, stock_api_type, stock_api_stock_code) VALUES '
            . implode(', ', $valueGroups);
        $this->db->query($sql, $params);
    }

    private function insertCoinSubscriptionRows(array $rows): void
    {
        $valueGroups = [];
        $params = [];
        foreach ($rows as $row) {
            $valueGroups[] = '(?, ?, ?, ?, ?)';
            foreach ($row as $value) {
                $params[] = $value;
            }
        }

        $sql = 'INSERT INTO Bithumb.coin_last_ws_query (coin_query, coin_code, query_type, coin_api_type, coin_api_coin_code) VALUES '
            . implode(', ', $valueGroups);
        $this->db->query($sql, $params);
    }

    private function invalidateSubscriptionCaches(): void
    {
        $this->cache->deletePattern('stock_list_count');
        $this->cache->deletePattern('coin_list_count');
        $this->cache->deletePattern('market_stats');
        $this->cache->deletePattern('top_stocks');
        $this->cache->deletePattern('stock_admin_list');
        $this->cache->deletePattern('stock_admin_registered');
        $this->cache->deletePattern('stock_admin_market_map');
    }

    /**
     * 특정 주식/코인 상세 정보 조회
     * $market='COIN'이면 Bithumb 우선, 그 외에는 KoreaInvest 우선 후 폴백
     */
    public function getStockByCode(string $stockCode, string $market = ''): ?array
    {
        $cacheKey = Cache::key('stock_detail', $stockCode, $market);
        $cached = $this->cache->get($cacheKey);
        if ($cached !== null) {
            return $cached;
        }

        if ($market === 'COIN') {
            // 코인 우선 조회
            $coin = $this->fetchCoinByCode($stockCode);
            if ($coin) {
                $this->cache->set($cacheKey, $coin, $this->cache->getTtl('stock_detail'));
                return $coin;
            }
        }

        $sql = "SELECT * FROM KoreaInvest.stock_info WHERE stock_code = :stock_code";
        $stock = $this->db->fetch($sql, [':stock_code' => $stockCode]);
        
        if ($stock) {
            $this->cache->set($cacheKey, $stock, $this->cache->getTtl('stock_detail'));
            return $stock;
        }

        // 코인 폴백 (market이 명시되지 않은 경우)
        if ($market !== 'COIN') {
            $coin = $this->fetchCoinByCode($stockCode);
            if ($coin) {
                $this->cache->set($cacheKey, $coin, $this->cache->getTtl('stock_detail'));
                return $coin;
            }
        }

        return null;
    }

    /**
     * 캔들 테이블의 최신 종가 조회
     */
    public function getLatestCandleClose(string $stockCode, string $market = ''): ?float
    {
        $cacheKey = Cache::key('stock_latest_close', $stockCode, $market);
        $cached = $this->cache->get($cacheKey);
        if ($cached !== null) {
            return $cached === '' ? null : (float)$cached;
        }

        $isCoin = $this->resolveIsCoin($stockCode, $market);
        $prefix = $isCoin ? 'c' : 's';
        $candleSource = $this->resolveCandleSource($stockCode, $prefix);

        if ($candleSource === null) {
            $this->cache->set($cacheKey, '', $this->cache->getTtl('stock_latest_close'));
            return null;
        }

        $tableRef = "`{$candleSource['schema']}`.`{$candleSource['table']}`";

        try {
            $row = $this->db->fetch(
                "SELECT execution_close
                 FROM {$tableRef}
                 ORDER BY execution_datetime DESC
                 LIMIT 1"
            );
        } catch (\Exception $e) {
            return null;
        }

        if (!$row || !isset($row['execution_close'])) {
            $this->cache->set($cacheKey, '', $this->cache->getTtl('stock_latest_close'));
            return null;
        }

        $latestClose = (float)$row['execution_close'];
        $this->cache->set($cacheKey, $latestClose, $this->cache->getTtl('stock_latest_close'));

        return $latestClose;
    }

    /**
     * 목록 데이터의 현재가를 최신 캔들 종가로 일괄 보정
     */
    private function applyLatestCloseToStockRows(array $stocks, string $market = ''): array
    {
        if (empty($stocks)) {
            return $stocks;
        }

        foreach ($stocks as $index => $stock) {
            $stockCode = $stock['stock_code'] ?? '';
            if ($stockCode === '') {
                continue;
            }

            $rowMarket = $market;
            if ($rowMarket === '' && (($stock['stock_type'] ?? '') === 'COIN')) {
                $rowMarket = 'COIN';
            }

            $latestClose = $this->getLatestCandleClose($stockCode, $rowMarket);
            if ($latestClose !== null) {
                $stocks[$index]['stock_price'] = $latestClose;
            }
        }

        return $stocks;
    }

    /**
     * Bithumb.coin_info에서 코인 조회
     */
    private function fetchCoinByCode(string $coinCode): ?array
    {
        $coinSql = "SELECT ci.coin_code AS stock_code,
                           ci.coin_name_kr AS stock_name_kr,
                           ci.coin_name_en AS stock_name_en,
                           'Bithumb' AS stock_market,
                           'COIN' AS stock_type,
                           ci.coin_price AS stock_price,
                           (ci.coin_price * ci.coin_amount) AS stock_capitalization,
                           ci.coin_amount AS stock_count,
                           ci.coin_update AS stock_update
                    FROM Bithumb.coin_info ci
                    WHERE ci.coin_code = :coin_code";
        $coin = $this->db->fetch($coinSql, [':coin_code' => $coinCode]);
        return $coin ?: null;
    }

    /**
     * 주식/코인 캔들 데이터 조회 (차트용)
     * limit에 미달하면 자동으로 이전 시간대를 포함해서 조회
     */
    public function getCandleData(string $stockCode, string $startDate, string $endDate, int $limit = 500, string $timeframe = '1h', string $market = ''): array
    {
        $cacheKey = Cache::key('stock_candle', $stockCode, $startDate, $endDate, $limit, $timeframe, $market);
        $cached = $this->cache->get($cacheKey);
        if ($cached !== null) {
            return $cached;
        }

        $isCoin = $this->resolveIsCoin($stockCode, $market);
        $prefix = $isCoin ? 'c' : 's';

        $candleSource = $this->resolveCandleSource($stockCode, $prefix);
        if ($candleSource === null) {
            return [];
        }

        $candles = $this->fetchCandlesWithExpansion($candleSource, $startDate, $endDate, $limit, $timeframe, $isCoin, $market);
        
        $this->cache->set($cacheKey, $candles, $this->cache->getTtl('stock_candle'));
        
        return $candles;
    }

    /**
     * 범위를 확장하며 캔들 데이터 조회 (limit에 미달하면 자동으로 이전 시간대 포함)
     * 단일 테이블(candle.s{Symbol})에서 날짜 범위만 조정하여 조회
     */
    private function fetchCandlesWithExpansion(array $candleSource, string $startDate, string $endDate, int $limit, string $timeframe, bool $isCoin = false, string $market = ''): array
    {
        $currentStart = $startDate;
        $allRows = [];
        $maxAttempts = 5;
        $attemptCount = 0;
        $previousStart = $endDate;
        $isKR = in_array($market, ['KR', ''], true) && !$isCoin;

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

                // 필터링 + 집계 (코인/US는 정규장 필터 제외, KR만 적용)
                $candles = $allRows;
                if ($isKR && $this->isSubDailyTimeframe($timeframe)) {
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
                $currentStart = $this->expandStartDateByTimeframe($currentStart, $timeframe, $isKR);
            }

            // 마지막 결과 반환
            $candles = $allRows;
            if ($isKR && $this->isSubDailyTimeframe($timeframe)) {
                $candles = array_values($this->filterRegularTradingHours($candles));
            }
            $candles = $this->aggregateCandlesByTimeframe($candles, $timeframe);

            return count($candles) > $limit ? array_slice($candles, -$limit) : $candles;
        } catch (\Exception $e) {
            return [];
        }
    }

    /**
     * timeframe에 따라 조회 시작일을 더 이전 영업일로 확장
     * KR 정규장: 9:00 ~ 15:30 (6.5h), US/기타: 4:00 ~ 20:00 (16h)
     */
    private function expandStartDateByTimeframe(string $startDate, string $timeframe, bool $isKR = true): string
    {
        $date = new \DateTime($startDate);
        $businessDaysToMove = 1;

        if (preg_match('/^(\\d+)m$/', $timeframe, $matches)) {
            // 분봉: KR 하루 330분, US 하루 960분
            $businessDaysToMove = $isKR ? 12 : 5;
        } elseif (preg_match('/^(\\d+)h$/', $timeframe, $matches)) {
            // 시간봉: KR 하루 6.5h, US 하루 16h
            $businessDaysToMove = $isKR ? 10 : 4;
        } else {
            switch ($timeframe) {
                case '1d':
                    $businessDaysToMove = 60;
                    break;
                case '1w':
                    $businessDaysToMove = 300;
                    break;
                case '1M':
                    $businessDaysToMove = 1260;
                    break;
                default:
                    $businessDaysToMove = $isKR ? 12 : 5;
                    break;
            }
        }

        // 이전 영업일로 이동
        $moveDays = 0;
        while ($moveDays < $businessDaysToMove) {
            $date->modify('-1 day');
            $dayOfWeek = (int)$date->format('w');
            if ($dayOfWeek >= 1 && $dayOfWeek <= 5) {
                $moveDays++;
            }
        }

        // KR: 정규장 시작 9:00, US/기타: 프리마켓 시작 4:00 (ET)
        $date->setTime($isKR ? 9 : 4, 0, 0);
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
    public function getRecentExecutions(string $stockCode, int $limit = 100, string $market = ''): array
    {
        $cacheKey = Cache::key('stock_executions', $stockCode, $limit, $market);
        $cached = $this->cache->get($cacheKey);
        if ($cached !== null) {
            return $cached;
        }

        $isCoin = $this->resolveIsCoin($stockCode, $market);
        $prefix = $isCoin ? 'c' : 's';

        $tickSource = $this->resolveTickSource($stockCode, $prefix);
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
                $this->cache->set($cacheKey, $executions, $this->cache->getTtl('stock_executions'));
            }

            return $executions;
        } catch (\Exception $e) {
            return [];
        }
    }

    /**
     * 시장별 주식/코인 통계
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

                UNION ALL

                SELECT 'COIN' AS market_group,
                       '코인' AS market_label,
                       COUNT(*) AS stock_count,
                       SUM(ci.coin_price * ci.coin_amount) AS total_cap
                FROM Bithumb.coin_info ci
                INNER JOIN (SELECT DISTINCT coin_code FROM Bithumb.coin_last_ws_query) cwq
                    ON ci.coin_code = cwq.coin_code

                ORDER BY FIELD(market_group, 'KR', 'US', 'COIN', 'ETC')";
        
        $stats = $this->db->fetchAll($sql);
        
        $this->cache->set($cacheKey, $stats, $this->cache->getTtl('market_stats'));
        
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
        $stocks = $this->applyLatestCloseToStockRows($stocks, $market === 'COIN' ? 'COIN' : '');

        $this->cache->set($cacheKey, $stocks, $this->cache->getTtl('top_stocks'));

        return $stocks;
    }

    /**
     * 거래대금 기준 상위 주식/코인 조회
     * candle 스키마의 테이블 목록을 일괄 조회 후 UNION ALL로 집계 (N+1 → 3회 쿼리)
     */
    private function getTopStocksByTradingAmount(int $limit, string $market): array
    {
        if ($market === 'COIN') {
            return $this->getTopCoinsByTradingAmount($limit);
        }

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
     * 코인 거래대금 기준 상위 조회
     */
    private function getTopCoinsByTradingAmount(int $limit): array
    {
        $lookback = date('Y-m-d', strtotime('-30 days'));

        // 1) candle 스키마의 코인 테이블 목록 (c prefix)
        $candleTables = $this->db->fetchAll(
            "SELECT TABLE_NAME FROM information_schema.TABLES
             WHERE TABLE_SCHEMA = 'candle' AND TABLE_NAME LIKE 'c%'"
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

        // 2) 수집 중인 코인 코드 조회
        $wsRows = $this->db->fetchAll(
            "SELECT DISTINCT coin_code FROM Bithumb.coin_last_ws_query"
        );
        if (empty($wsRows)) {
            return [];
        }

        // 3) 코인코드 → 캔들 테이블 매핑
        $codeToTable = [];
        foreach ($wsRows as $row) {
            $code = $row['coin_code'] ?? '';
            if ($code === '') continue;
            $upper = strtoupper($code);
            $candidate = 'c' . $upper;
            if (isset($tableSet[$candidate])) {
                $codeToTable[$code] = $candidate;
            }
        }

        if (empty($codeToTable)) {
            return [];
        }

        // 4) UNION ALL로 거래대금 집계
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

        // 상세 정보 조회
        $codePlaceholders = [];
        $detailParams = [];
        foreach ($topCodes as $i => $code) {
            $ph = ':code' . $i;
            $codePlaceholders[] = $ph;
            $detailParams[$ph] = $code;
        }

        $detailSql = "SELECT ci.coin_code AS stock_code,
                             ci.coin_name_kr AS stock_name_kr,
                             ci.coin_name_en AS stock_name_en,
                             'Bithumb' AS stock_market,
                             ci.coin_price AS stock_price,
                             (ci.coin_price * ci.coin_amount) AS stock_capitalization
                      FROM Bithumb.coin_info ci
                      WHERE ci.coin_code IN (" . implode(', ', $codePlaceholders) . ")";

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
            if (!isset($detailByCode[$code])) continue;
            $item = $detailByCode[$code];
            $item['total_amount'] = $amount;
            $results[] = $item;
            if (count($results) >= $limit) break;
        }

        // 부족하면 시총 기준으로 보충
        if (count($results) < $limit) {
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
                $excludeSql = ' AND ci.coin_code NOT IN (' . implode(', ', $placeholders) . ')';
            }

            $fillSql = "SELECT ci.coin_code AS stock_code, 0 AS total_amount,
                               ci.coin_name_kr AS stock_name_kr,
                               ci.coin_name_en AS stock_name_en,
                               'Bithumb' AS stock_market,
                               ci.coin_price AS stock_price,
                               (ci.coin_price * ci.coin_amount) AS stock_capitalization
                        FROM Bithumb.coin_info ci
                        INNER JOIN (SELECT DISTINCT coin_code FROM Bithumb.coin_last_ws_query) cwq
                            ON ci.coin_code = cwq.coin_code
                        WHERE 1=1" . $excludeSql . "
                        ORDER BY (ci.coin_price * ci.coin_amount) DESC
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
