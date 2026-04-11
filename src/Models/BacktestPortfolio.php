<?php

namespace Blog\Models;

use Blog\Database\Database;
use Blog\Core\Cache;

class BacktestPortfolio
{
    private $db;
    private $cache;

    public function __construct()
    {
        $this->db = Database::getInstance();
        $this->cache = Cache::getInstance();
    }

    /**
     * 포트폴리오 저장 (INSERT or UPDATE — 동일 IP + config_hash)
     *
     * @return int portfolio_id
     */
    public function save(array $data): int
    {
        $existing = $this->db->fetch(
            "SELECT portfolio_id FROM backtest_portfolio WHERE ip_address = ? AND config_hash = ?",
            [$data['ip_address'], $data['config_hash']]
        );

        if ($existing) {
            $this->db->query(
                "UPDATE backtest_portfolio SET
                    portfolio_name = ?,
                    config_json = ?,
                    display_score = ?,
                    display_grade = ?,
                    ranking_score = ?,
                    ranking_grade = ?,
                    metrics_json = ?,
                    stock_summary = ?,
                    strategy = ?,
                    period_start = ?,
                    period_end = ?,
                    initial_capital = ?,
                    monthly_dca = ?
                WHERE portfolio_id = ?",
                [
                    $data['portfolio_name'],
                    $data['config_json'],
                    $data['display_score'],
                    $data['display_grade'],
                    $data['ranking_score'],
                    $data['ranking_grade'],
                    $data['metrics_json'],
                    $data['stock_summary'],
                    $data['strategy'],
                    $data['period_start'],
                    $data['period_end'],
                    $data['initial_capital'],
                    $data['monthly_dca'],
                    $existing['portfolio_id'],
                ]
            );
            $id = (int)$existing['portfolio_id'];
        } else {
            $this->db->query(
                "INSERT INTO backtest_portfolio
                    (portfolio_name, ip_address, config_hash, config_json,
                     display_score, display_grade, ranking_score, ranking_grade,
                     metrics_json, stock_summary, strategy,
                     period_start, period_end, initial_capital, monthly_dca)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    $data['portfolio_name'],
                    $data['ip_address'],
                    $data['config_hash'],
                    $data['config_json'],
                    $data['display_score'],
                    $data['display_grade'],
                    $data['ranking_score'],
                    $data['ranking_grade'],
                    $data['metrics_json'],
                    $data['stock_summary'],
                    $data['strategy'],
                    $data['period_start'],
                    $data['period_end'],
                    $data['initial_capital'],
                    $data['monthly_dca'],
                ]
            );
            $id = (int)$this->db->lastInsertId();
        }

        $this->cache->deletePattern('backtest_top');
        return $id;
    }

    /**
     * Top N 포트폴리오 조회 (ranking_score DESC)
     */
    public function getTopPortfolios(int $limit = 10): array
    {
        $cacheKey = Cache::key('backtest_top', $limit);
        $cached = $this->cache->get($cacheKey);
        if ($cached !== null) {
            return $cached;
        }

        $rows = $this->db->fetchAll(
            "SELECT portfolio_id, portfolio_name, ranking_score, ranking_grade,
                    display_score, display_grade, metrics_json,
                    stock_summary, strategy, period_start, period_end,
                    initial_capital, monthly_dca, updated_at
             FROM backtest_portfolio
             ORDER BY ranking_score DESC, updated_at DESC
             LIMIT ?",
            [$limit]
        );

        foreach ($rows as &$row) {
            $row['metrics'] = json_decode($row['metrics_json'], true);
            unset($row['metrics_json']);
        }
        unset($row);

        $this->cache->set($cacheKey, $rows, 300); // 5분
        return $rows;
    }

    /**
     * 단일 포트폴리오 상세 조회 (config_json 포함)
     */
    public function getById(int $id): ?array
    {
        $row = $this->db->fetch(
            "SELECT portfolio_id, portfolio_name, ip_address, config_json,
                    display_score, display_grade, ranking_score, ranking_grade,
                    metrics_json, stock_summary, strategy,
                    period_start, period_end, initial_capital, monthly_dca,
                    created_at, updated_at
             FROM backtest_portfolio
             WHERE portfolio_id = ?",
            [$id]
        );

        if (!$row) {
            return null;
        }

        $row['config'] = json_decode($row['config_json'], true);
        $row['metrics'] = json_decode($row['metrics_json'], true);
        unset($row['config_json'], $row['metrics_json']);
        return $row;
    }

    /**
     * 포트폴리오 이름 수정 (IP 검증)
     */
    public function updateName(int $id, string $ip, string $name): bool
    {
        $row = $this->db->fetch(
            "SELECT ip_address FROM backtest_portfolio WHERE portfolio_id = ?",
            [$id]
        );

        if (!$row || $row['ip_address'] !== $ip) {
            return false;
        }

        $this->db->query(
            "UPDATE backtest_portfolio SET portfolio_name = ? WHERE portfolio_id = ?",
            [$name, $id]
        );

        $this->cache->deletePattern('backtest_top');
        return true;
    }

    /**
     * 종목 조합 해시 생성 (IP와 함께 UNIQUE 키로 사용)
     * 종목 코드 + 비중 + 전략을 정규화하여 해시
     */
    public static function buildConfigHash(array $stocks, string $strategy): string
    {
        $parts = [];
        foreach ($stocks as $s) {
            $parts[] = $s['code'] . ':' . round($s['weight'], 2);
        }
        sort($parts);
        return md5(implode('|', $parts) . '|' . $strategy);
    }

    /**
     * 자동 포트폴리오 이름 생성
     */
    public static function generateName(array $stocks): string
    {
        $names = array_column($stocks, 'name');
        if (count($names) <= 3) {
            return implode(' · ', $names);
        }
        $shown = array_slice($names, 0, 3);
        return implode(' · ', $shown) . ' 외 ' . (count($names) - 3) . '종목';
    }
}
