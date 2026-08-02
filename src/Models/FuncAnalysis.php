<?php

namespace Blog\Models;

use Blog\Database\Database;

class FuncAnalysis
{
    private $db;
    private static $schemaEnsured = false;

    public function __construct()
    {
        $this->db = Database::getInstance();
        $this->ensureSchema();
    }

    public static function hashIds(array $videoIds, string $provider): string
    {
        $sorted = $videoIds;
        sort($sorted);
        return sha1($provider . '|' . implode(',', $sorted));
    }

    public static function generateShareToken(): string
    {
        // 8 bytes → 16자 hex (소문자 영숫자), 약 1.8e19 조합 — 무작위 대입 방지
        return bin2hex(random_bytes(8));
    }

    public function findByIdsHash(string $idsHash): ?array
    {
        return $this->db->fetch(
            'SELECT analysis_id, share_token, ids_csv, video_count, provider, payload FROM func_analysis_list WHERE ids_hash = ?',
            [$idsHash]
        );
    }

    public function findByShareToken(string $token): ?array
    {
        if (preg_match('/^[a-f0-9]{16}$/', $token) !== 1) {
            return null;
        }
        return $this->db->fetch(
            'SELECT analysis_id, share_token, ids_csv FROM func_analysis_list WHERE share_token = ?',
            [$token]
        );
    }

    /**
     * 신규 저장 또는 기존 ids_hash 회수.
     * 반환: ['id' => int, 'token' => string]
     */
    public function save(string $idsHash, array $videoIds, string $provider, array $payload, ?string $ip, ?string $voterToken = null): array
    {
        $sorted = $videoIds;
        sort($sorted);
        $payloadJson = json_encode($payload, JSON_UNESCAPED_UNICODE);
        $videoCount = (int)($payload['videoCount'] ?? count($videoIds));
        $idsCsv = implode(',', $sorted);

        // INSERT 시도 — UNIQUE(ids_hash) 충돌 시 기존 행 회수
        // 토큰 충돌(1.8e19 중)은 사실상 0이지만 race 대비 3회 재시도
        for ($attempt = 0; $attempt < 3; $attempt++) {
            try {
                $token = self::generateShareToken();
                $this->db->query(
                    'INSERT INTO func_analysis_list (ids_hash, share_token, ids_csv, video_count, provider, payload, created_ip, creator_voter_token)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                     ON DUPLICATE KEY UPDATE updated_at = CURRENT_TIMESTAMP',
                    [$idsHash, $token, $idsCsv, $videoCount, $provider, $payloadJson, $ip, $voterToken]
                );
                $id = (int)$this->db->lastInsertId();
                if ($id > 0) {
                    return ['id' => $id, 'token' => $token];
                }
                // ON DUPLICATE 분기 — 기존 행 회수
                $row = $this->db->fetch(
                    'SELECT analysis_id, share_token FROM func_analysis_list WHERE ids_hash = ?',
                    [$idsHash]
                );
                return [
                    'id' => (int)($row['analysis_id'] ?? 0),
                    'token' => (string)($row['share_token'] ?? ''),
                ];
            } catch (\PDOException $e) {
                // share_token UNIQUE 충돌 시 SQLSTATE 23000 → 다음 시도
                if ($e->getCode() === '23000' && strpos((string)$e->getMessage(), 'share_token') !== false) {
                    continue;
                }
                throw $e;
            }
        }

        // 3회 충돌 — 통계적으로 도달 불가능. 안전망으로 기존 행 회수 시도
        $row = $this->db->fetch(
            'SELECT analysis_id, share_token FROM func_analysis_list WHERE ids_hash = ?',
            [$idsHash]
        );
        return [
            'id' => (int)($row['analysis_id'] ?? 0),
            'token' => (string)($row['share_token'] ?? ''),
        ];
    }

    /**
     * voter_token으로 생성한 분석 이력 조회 (최근 20건).
     */
    public function findByCreatorToken(string $voterToken, int $limit = 20): array
    {
        return $this->db->fetchAll(
            'SELECT analysis_id, share_token, video_count, provider, payload, created_at
             FROM func_analysis_list
             WHERE creator_voter_token = ?
             ORDER BY created_at DESC
             LIMIT ?',
            [$voterToken, $limit]
        );
    }

    public function getUserVote(int $analysisId, string $voterToken): ?string
    {
        $row = $this->db->fetch(
            'SELECT vote FROM func_analysis_reaction_list WHERE analysis_id = ? AND voter_token = ?',
            [$analysisId, $voterToken]
        );
        return $row['vote'] ?? null;
    }

    /**
     * 같은 vote 다시 → 취소(삭제), 다른 vote → 변경, 없으면 → 신규.
     * 결과: 'added' | 'changed' | 'removed'
     */
    public function toggleReaction(int $analysisId, string $voterToken, string $vote, ?string $ip): string
    {
        if ($vote !== 'like' && $vote !== 'dislike') {
            throw new \InvalidArgumentException('vote must be like or dislike');
        }
        $current = $this->getUserVote($analysisId, $voterToken);
        if ($current === $vote) {
            $this->db->query(
                'DELETE FROM func_analysis_reaction_list WHERE analysis_id = ? AND voter_token = ?',
                [$analysisId, $voterToken]
            );
            return 'removed';
        }
        if ($current === null) {
            $this->db->query(
                'INSERT INTO func_analysis_reaction_list (analysis_id, voter_token, vote, voter_ip) VALUES (?, ?, ?, ?)',
                [$analysisId, $voterToken, $vote, $ip]
            );
            return 'added';
        }
        $this->db->query(
            'UPDATE func_analysis_reaction_list SET vote = ?, voter_ip = ? WHERE analysis_id = ? AND voter_token = ?',
            [$vote, $ip, $analysisId, $voterToken]
        );
        return 'changed';
    }

    /**
     * share_token 컬럼 자동 마이그레이션 (Logger의 ensureBlogLogTableInnoDb 패턴).
     * 첫 인스턴스화 시 1회 실행, 이후 static 플래그로 skip.
     */
    private function ensureSchema(): void
    {
        if (self::$schemaEnsured) {
            return;
        }
        self::$schemaEnsured = true;

        try {
            $col = $this->db->fetch("SHOW COLUMNS FROM func_analysis_list LIKE 'share_token'");
            if ($col === null) {
                $this->db->query(
                    "ALTER TABLE func_analysis_list
                     ADD COLUMN share_token CHAR(16) NULL AFTER analysis_id,
                     ADD UNIQUE KEY uk_share_token (share_token)"
                );
            }

            $col2 = $this->db->fetch("SHOW COLUMNS FROM func_analysis_list LIKE 'creator_voter_token'");
            if ($col2 === null) {
                $this->db->query(
                    "ALTER TABLE func_analysis_list
                     ADD COLUMN creator_voter_token CHAR(40) NULL,
                     ADD KEY idx_creator_voter_token (creator_voter_token)"
                );
            }

            // NULL 백필 — 기존 행 행마다 unique 토큰 (UNIQUE 제약상 충돌 시 재시도)
            $rows = $this->db->fetchAll(
                'SELECT analysis_id FROM func_analysis_list WHERE share_token IS NULL'
            );
            foreach ($rows as $row) {
                $analysisId = (int)$row['analysis_id'];
                for ($attempt = 0; $attempt < 5; $attempt++) {
                    try {
                        $this->db->query(
                            'UPDATE func_analysis_list SET share_token = ? WHERE analysis_id = ? AND share_token IS NULL',
                            [self::generateShareToken(), $analysisId]
                        );
                        break;
                    } catch (\PDOException $e) {
                        if ($e->getCode() !== '23000') {
                            throw $e;
                        }
                    }
                }
            }
        } catch (\Throwable $e) {
            // 마이그레이션 실패가 정상 흐름을 막지 않게 — 다음 인스턴스에서 재시도
            self::$schemaEnsured = false;
            error_log('[FuncAnalysis::ensureSchema] ' . $e->getMessage());
        }
    }
}
