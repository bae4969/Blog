<?php

namespace Blog\Models;

use Blog\Database\Database;

class BacktestPreset
{
    private $db;
    private const MAX_PRESETS_PER_USER = 20;

    public function __construct()
    {
        $this->db = Database::getInstance();
    }

    /**
     * 사용자의 프리셋 목록 조회 (최신 수정순)
     */
    public function getByUser(int $userIndex): array
    {
        return $this->db->fetchAll(
            "SELECT preset_id, preset_name, stock_summary, strategy, updated_at
             FROM backtest_preset
             WHERE user_index = ?
             ORDER BY updated_at DESC",
            [$userIndex]
        );
    }

    /**
     * 프리셋 저장 (동일 이름이면 덮어쓰기)
     *
     * @return int preset_id
     */
    public function save(int $userIndex, string $name, string $configJson, string $stockSummary, string $strategy): int
    {
        $existing = $this->db->fetch(
            "SELECT preset_id FROM backtest_preset WHERE user_index = ? AND preset_name = ?",
            [$userIndex, $name]
        );

        if ($existing) {
            $this->db->query(
                "UPDATE backtest_preset SET config_json = ?, stock_summary = ?, strategy = ? WHERE preset_id = ?",
                [$configJson, $stockSummary, $strategy, $existing['preset_id']]
            );
            return (int)$existing['preset_id'];
        }

        // 개수 제한 검사
        $count = $this->countByUser($userIndex);
        if ($count >= self::MAX_PRESETS_PER_USER) {
            throw new \RuntimeException('프리셋은 최대 ' . self::MAX_PRESETS_PER_USER . '개까지 저장 가능합니다.');
        }

        $this->db->query(
            "INSERT INTO backtest_preset (user_index, preset_name, config_json, stock_summary, strategy)
             VALUES (?, ?, ?, ?, ?)",
            [$userIndex, $name, $configJson, $stockSummary, $strategy]
        );
        return (int)$this->db->lastInsertId();
    }

    /**
     * 단일 프리셋 조회 (소유권 확인 포함)
     */
    public function getById(int $id, int $userIndex): ?array
    {
        $row = $this->db->fetch(
            "SELECT preset_id, preset_name, config_json, stock_summary, strategy, updated_at
             FROM backtest_preset
             WHERE preset_id = ? AND user_index = ?",
            [$id, $userIndex]
        );

        if (!$row) {
            return null;
        }

        $row['config'] = json_decode($row['config_json'], true);
        unset($row['config_json']);
        return $row;
    }

    /**
     * 프리셋 삭제 (소유권 확인 포함)
     */
    public function delete(int $id, int $userIndex): bool
    {
        $stmt = $this->db->query(
            "DELETE FROM backtest_preset WHERE preset_id = ? AND user_index = ?",
            [$id, $userIndex]
        );
        return $stmt->rowCount() > 0;
    }

    /**
     * 사용자의 프리셋 개수
     */
    public function countByUser(int $userIndex): int
    {
        $row = $this->db->fetch(
            "SELECT COUNT(*) AS cnt FROM backtest_preset WHERE user_index = ?",
            [$userIndex]
        );
        return (int)($row['cnt'] ?? 0);
    }
}
