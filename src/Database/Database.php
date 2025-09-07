<?php

namespace Blog\Database;

use PDO;
use PDOException;

class Database
{
    private static $instance = null;
    private $connection;
    private $queryLog = [];
    private $slowQueryThreshold = 0.1; // 100ms

    private function __construct()
    {
        $config = require __DIR__ . '/../../config/database.php';
        
        try {
            $dsn = "mysql:host={$config['host']};dbname={$config['dbname']};charset={$config['charset']}";
            $this->connection = new PDO($dsn, $config['username'], $config['password'], $config['options']);
        } catch (PDOException $e) {
            throw new \Exception("데이터베이스 연결 실패: " . $e->getMessage());
        }
    }

    public static function getInstance(): self
    {
        if (self::$instance === null) {
            self::$instance = new self();
        }
        return self::$instance;
    }

    public function getConnection(): PDO
    {
        return $this->connection;
    }

    public function query(string $sql, array $params = []): \PDOStatement
    {
        $startTime = microtime(true);
        
        $stmt = $this->connection->prepare($sql);
        $stmt->execute($params);
        
        $executionTime = microtime(true) - $startTime;
        
        // 쿼리 로깅
        $this->logQuery($sql, $params, $executionTime);
        
        return $stmt;
    }

    /**
     * 쿼리 로깅
     */
    private function logQuery(string $sql, array $params, float $executionTime): void
    {
        $logEntry = [
            'sql' => $sql,
            'params' => $params,
            'execution_time' => $executionTime,
            'timestamp' => date('Y-m-d H:i:s')
        ];
        
        $this->queryLog[] = $logEntry;
        
        // 느린 쿼리 로깅
        if ($executionTime > $this->slowQueryThreshold) {
            error_log("Slow Query ({$executionTime}s): {$sql}");
        }
    }

    /**
     * 쿼리 로그 가져오기
     */
    public function getQueryLog(): array
    {
        return $this->queryLog;
    }

    /**
     * 쿼리 통계
     */
    public function getQueryStats(): array
    {
        $totalQueries = count($this->queryLog);
        $totalTime = array_sum(array_column($this->queryLog, 'execution_time'));
        $slowQueries = array_filter($this->queryLog, function($query) {
            return $query['execution_time'] > $this->slowQueryThreshold;
        });
        
        return [
            'total_queries' => $totalQueries,
            'total_time' => $totalTime,
            'average_time' => $totalQueries > 0 ? $totalTime / $totalQueries : 0,
            'slow_queries' => count($slowQueries),
            'slow_query_threshold' => $this->slowQueryThreshold
        ];
    }

    public function fetchAll(string $sql, array $params = []): array
    {
        return $this->query($sql, $params)->fetchAll();
    }

    public function fetch(string $sql, array $params = []): ?array
    {
        $result = $this->query($sql, $params)->fetch();
        return $result ?: null;
    }

    public function lastInsertId(): string
    {
        return $this->connection->lastInsertId();
    }
}
