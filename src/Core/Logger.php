<?php

namespace Blog\Core;

use Blog\Database\Database;

class Logger
{
    /** @var array<string, bool> */
    private static $ensuredTables = [];

    /**
     * 일반 로그 기록
     * @param string $name   논리적 로그 이름(예: 'auth', 'post')
     * @param string $type   1글자 타입(예: 'I','W','E')
     * @param string $message 메시지
     * @param array $context  추가 컨텍스트 ['function'=>..., 'file'=>..., 'line'=>...]
     */
    public static function log(string $name, string $type, string $message, array $context = []): void
    {
        try {
            $db = Database::getInstance();
            $year = (int)date('Y');
            if ($year < 2000 || $year > 9999) {
                return;
            }
            self::ensureBlogLogTableInnoDb($db, $year);
            $table = "Log.blog_log";

            // 길이 제어 및 기본값
            $name = mb_substr($name, 0, 255, 'UTF-8');
            $type = mb_substr($type, 0, 1, 'UTF-8');
            $message = (string)$message;
            if (mb_strlen($message, 'UTF-8') > 8000) {
                $message = mb_substr($message, 0, 8000, 'UTF-8');
            }

            $func = isset($context['function']) ? self::normalizeFunctionName((string)$context['function']) : null;
            $fileContext = $context['file'] ?? null;
            $file = $fileContext ? basename((string)$fileContext) : null;
            $file = $file ? mb_substr($file, 0, 255, 'UTF-8') : null;
            $line = isset($context['line']) ? (int)$context['line'] : null;

            // 기본적으로 현재 호출 스택에서 보완
            if ($func === null || $file === null || $line === null) {
                $bt = debug_backtrace(DEBUG_BACKTRACE_IGNORE_ARGS, 2);
                if (isset($bt[1])) {
                    $traceFunc = $bt[1]['function'] ?? null;
                    $func = $func ?? self::normalizeFunctionName($traceFunc);
                    $traceFile = $bt[1]['file'] ?? null;
                    $file = $file ?? ($traceFile ? basename($traceFile) : null);
                    $line = $line ?? ($bt[1]['line'] ?? null);
                }
            }

            $sql = "INSERT INTO {$table} (log_name, log_type, log_message, log_function, log_file, log_line) VALUES (?, ?, ?, ?, ?, ?)";
            $db->query($sql, [$name, $type, $message, $func, $file, $line]);
        } catch (\Throwable $e) {
            // 로깅 실패 시 애플리케이션 흐름을 방해하지 않음
            error_log('[Logger] write failed: ' . $e->getMessage());
        }
    }

    public static function info(string $name, string $message, array $context = []): void
    {
        self::log($name, 'I', $message, $context);
    }

    public static function warn(string $name, string $message, array $context = []): void
    {
        self::log($name, 'W', $message, $context);
    }

    public static function error(string $name, string $message, array $context = []): void
    {
        self::log($name, 'E', $message, $context);
    }

    private static function normalizeFunctionName(?string $func): ?string
    {
        if ($func === null || $func === '') {
            return null;
        }

        $funcStr = (string)$func;
        $pos = strrpos($funcStr, '::');
        if ($pos !== false) {
            $funcStr = substr($funcStr, $pos + 2);
        }

        return mb_substr($funcStr, 0, 255, 'UTF-8');
    }

    private static function ensureBlogLogTableInnoDb(Database $db, int $year): void
    {
        $tableName = 'blog_log';
        $ensureKey = $tableName . ':' . $year;

        if (isset(self::$ensuredTables[$ensureKey])) {
            return;
        }

        $quotedTable = "Log.`{$tableName}`";

        $createSql = "
            CREATE TABLE IF NOT EXISTS {$quotedTable} (
                log_datetime DATETIME DEFAULT CURRENT_TIMESTAMP,
                log_name VARCHAR(255),
                log_type CHAR(1),
                log_message TEXT,
                log_function VARCHAR(255),
                log_file VARCHAR(255),
                log_line INT
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            PARTITION BY RANGE (YEAR(log_datetime)) (
                PARTITION p{$year}_prev VALUES LESS THAN ({$year}),
                PARTITION p{$year} VALUES LESS THAN (" . ($year + 1) . "),
                PARTITION pmax VALUES LESS THAN MAXVALUE
            )
        ";
        $db->query($createSql);

        $engineInfo = $db->fetch(
            "SELECT ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? LIMIT 1",
            ['Log', $tableName]
        );

        if (!empty($engineInfo['ENGINE']) && strcasecmp((string)$engineInfo['ENGINE'], 'InnoDB') !== 0) {
            $db->query("ALTER TABLE {$quotedTable} ENGINE=InnoDB");
        }

        $partitionInfo = $db->fetch(
            "SELECT PARTITION_NAME FROM information_schema.PARTITIONS WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? AND PARTITION_NAME IS NOT NULL LIMIT 1",
            ['Log', $tableName]
        );

        if (empty($partitionInfo)) {
            $db->query(
                "ALTER TABLE {$quotedTable} PARTITION BY RANGE (YEAR(log_datetime)) (" .
                "PARTITION p{$year}_prev VALUES LESS THAN ({$year}), " .
                "PARTITION p{$year} VALUES LESS THAN (" . ($year + 1) . "), " .
                "PARTITION pmax VALUES LESS THAN MAXVALUE)"
            );
        } else {
            $yearPartition = $db->fetch(
                "SELECT PARTITION_NAME FROM information_schema.PARTITIONS WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? AND PARTITION_NAME = ? LIMIT 1",
                ['Log', $tableName, 'p' . $year]
            );

            if (empty($yearPartition)) {
                $db->query(
                    "ALTER TABLE {$quotedTable} REORGANIZE PARTITION pmax INTO (" .
                    "PARTITION p{$year} VALUES LESS THAN (" . ($year + 1) . "), " .
                    "PARTITION pmax VALUES LESS THAN MAXVALUE)"
                );
            }
        }

        self::$ensuredTables[$ensureKey] = true;
    }

    private static $allowedSortColumns = [
        'log_datetime', 'log_name', 'log_type', 'log_function', 'log_file',
    ];

    /**
     * Log DB의 모든 로그 테이블명 반환 (동일 스키마만)
     */
    public static function getLogTableNames(): array
    {
        $db = Database::getInstance();
        $rows = $db->fetchAll(
            "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = 'Log' ORDER BY TABLE_NAME"
        );

        $tables = [];
        foreach ($rows as $row) {
            $name = $row['TABLE_NAME'];
            if (preg_match('/^[A-Za-z0-9_]+$/', $name)) {
                $tables[] = $name;
            }
        }
        return $tables;
    }

    /**
     * 모든 로그 테이블을 UNION ALL하는 서브쿼리 생성
     */
    private static function buildUnionSubquery(array $tableNames): string
    {
        $parts = [];
        foreach ($tableNames as $name) {
            $quoted = 'Log.`' . $name . '`';
            $parts[] = "SELECT log_datetime, log_name COLLATE utf8mb4_unicode_ci AS log_name, log_type COLLATE utf8mb4_unicode_ci AS log_type, log_message COLLATE utf8mb4_unicode_ci AS log_message, log_function COLLATE utf8mb4_unicode_ci AS log_function, log_file COLLATE utf8mb4_unicode_ci AS log_file, log_line FROM {$quoted}";
        }
        return '(' . implode(' UNION ALL ', $parts) . ') AS combined_logs';
    }

    /**
     * 로그 조회 (페이지네이션 + 필터 + 정렬) — Log DB 전체 테이블 합산
     */
    public static function getLogs(array $filters = [], string $sort = 'log_datetime', string $order = 'DESC', int $page = 1, int $perPage = 50): array
    {
        $db = Database::getInstance();
        $year = (int)date('Y');
        self::ensureBlogLogTableInnoDb($db, $year);

        $tables = self::getLogTableNames();
        if (empty($tables)) {
            return ['total' => 0, 'logs' => []];
        }

        if (!empty($filters['table'])) {
            $filterTables = (array)$filters['table'];
            $queryTables = array_values(array_intersect($filterTables, $tables));
            if (empty($queryTables)) {
                $queryTables = $tables;
            }
        } else {
            $queryTables = $tables;
        }

        $source = self::buildUnionSubquery($queryTables);

        if (!in_array($sort, self::$allowedSortColumns, true)) {
            $sort = 'log_datetime';
        }
        $order = strtoupper($order) === 'ASC' ? 'ASC' : 'DESC';

        $where = [];
        $params = [];

        if (!empty($filters['name'])) {
            $where[] = 'log_name = ?';
            $params[] = $filters['name'];
        }
        if (!empty($filters['type'])) {
            $types = (array)$filters['type'];
            $placeholders = implode(',', array_fill(0, count($types), '?'));
            $where[] = "log_type IN ({$placeholders})";
            array_push($params, ...$types);
        }
        if (!empty($filters['date_from'])) {
            $where[] = 'log_datetime >= ?';
            $params[] = $filters['date_from'] . ' 00:00:00';
        }
        if (!empty($filters['date_to'])) {
            $where[] = 'log_datetime <= ?';
            $params[] = $filters['date_to'] . ' 23:59:59';
        }
        if (!empty($filters['q'])) {
            $where[] = 'log_message LIKE ?';
            $params[] = '%' . $filters['q'] . '%';
        }

        $whereSql = $where ? 'WHERE ' . implode(' AND ', $where) : '';

        $countSql = "SELECT COUNT(*) AS cnt FROM {$source} {$whereSql}";
        $row = $db->fetch($countSql, $params);
        $total = $row ? (int)$row['cnt'] : 0;

        $offset = ($page - 1) * $perPage;
        $dataSql = "SELECT log_datetime, log_name, log_type, log_message, log_function, log_file, log_line FROM {$source} {$whereSql} ORDER BY {$sort} {$order} LIMIT {$perPage} OFFSET {$offset}";
        $logs = $db->fetchAll($dataSql, $params);

        return ['total' => $total, 'logs' => $logs];
    }

    /**
     * 고유 log_name 목록 반환 (최근 90일) — Log DB 전체 테이블 합산
     */
    public static function getDistinctLogNames(): array
    {
        $db = Database::getInstance();
        $year = (int)date('Y');
        self::ensureBlogLogTableInnoDb($db, $year);

        $tables = self::getLogTableNames();
        if (empty($tables)) {
            return [];
        }

        $source = self::buildUnionSubquery($tables);
        $sql = "SELECT DISTINCT log_name FROM {$source} WHERE log_datetime >= DATE_SUB(NOW(), INTERVAL 90 DAY) ORDER BY log_name";
        $rows = $db->fetchAll($sql);

        return array_column($rows, 'log_name');
    }
}
