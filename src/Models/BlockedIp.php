<?php

namespace Blog\Models;

use Blog\Database\Database;
use Blog\Core\Cache;

class BlockedIp
{
    private $db;
    private $cache;

    public function __construct()
    {
        $this->db = Database::getInstance();
        $this->cache = Cache::getInstance();
    }

    /**
     * 화이트리스트에 포함된 IP인지 확인 (단일 IP와 CIDR 대역 모두 지원)
     */
    public static function isIpWhitelisted(string $ip, array $whitelist): bool
    {
        foreach ($whitelist as $entry) {
            if ($ip === $entry) {
                return true;
            }

            if (strpos($entry, '/') === false) {
                continue;
            }

            [$subnet, $prefix] = explode('/', $entry, 2);
            $prefix = (int)$prefix;

            $ipBin = @inet_pton($ip);
            $subnetBin = @inet_pton($subnet);
            if ($ipBin === false || $subnetBin === false || strlen($ipBin) !== strlen($subnetBin)) {
                continue;
            }

            $maxBits = strlen($ipBin) * 8;
            if ($prefix < 0 || $prefix > $maxBits) {
                continue;
            }

            $fullBytes = intdiv($prefix, 8);
            $remainingBits = $prefix % 8;

            if ($fullBytes > 0 && substr($ipBin, 0, $fullBytes) !== substr($subnetBin, 0, $fullBytes)) {
                continue;
            }

            if ($remainingBits > 0) {
                $mask = (0xFF << (8 - $remainingBits)) & 0xFF;
                if ((ord($ipBin[$fullBytes]) & $mask) !== (ord($subnetBin[$fullBytes]) & $mask)) {
                    continue;
                }
            }

            return true;
        }

        return false;
    }

    /**
     * 해당 IP가 현재 차단 중인지 확인 (캐시 적용)
     */
    public function isBlocked(string $ip): bool
    {
        $cacheKey = Cache::key('blocked_ip', $ip);
        $cached = $this->cache->get($cacheKey);
        if ($cached !== null) {
            return (bool)$cached;
        }

        $sql = "SELECT expires_at FROM blocked_ip_list 
                WHERE ip_address = ? 
                AND (expires_at IS NULL OR expires_at > NOW())
                LIMIT 1";
        $result = $this->db->fetch($sql, [$ip]);
        $blocked = !empty($result);

        $config = require __DIR__ . '/../../config/config.php';
        $ttl = $config['ip_block']['cache_ttl'] ?? 300;

        // 차단 만료까지 남은 시간이 캐시 TTL보다 짧으면 그 시간으로 제한
        if ($blocked && !empty($result['expires_at'])) {
            $remaining = strtotime($result['expires_at']) - time();
            if ($remaining > 0 && $remaining < $ttl) {
                $ttl = $remaining;
            }
        }

        $this->cache->set($cacheKey, $blocked ? 1 : 0, $ttl);

        return $blocked;
    }

    /**
     * 활성 차단 목록 조회
     */
    public function getActiveBlocks(): array
    {
        $sql = "SELECT * FROM blocked_ip_list 
                WHERE expires_at IS NULL OR expires_at > NOW() 
                ORDER BY blocked_at DESC";
        return $this->db->fetchAll($sql);
    }

    /**
     * 전체 차단 목록 조회 (만료 포함)
     */
    public function getAll(): array
    {
        $sql = "SELECT * FROM blocked_ip_list ORDER BY blocked_at DESC";
        return $this->db->fetchAll($sql);
    }

    /**
     * IP 차단 등록 (UPSERT: 이미 존재하면 갱신)
     */
    public function blockIp(string $ip, string $reason, string $type = 'manual', ?int $duration = null, ?int $createdBy = null): bool
    {
        $expiresAt = null;
        if ($duration !== null && $duration > 0) {
            // DB 서버 시간 기준으로 만료 시각 계산
            $expiresAt = $duration;
        }

        if ($expiresAt !== null) {
            $sql = "INSERT INTO blocked_ip_list (ip_address, reason, block_type, blocked_at, expires_at, created_by) 
                    VALUES (?, ?, ?, NOW(), DATE_ADD(NOW(), INTERVAL ? SECOND), ?)
                    ON DUPLICATE KEY UPDATE 
                        reason = VALUES(reason), 
                        block_type = VALUES(block_type), 
                        blocked_at = NOW(), 
                        expires_at = DATE_ADD(NOW(), INTERVAL ? SECOND), 
                        created_by = VALUES(created_by)";
            $this->db->query($sql, [$ip, $reason, $type, $expiresAt, $createdBy, $expiresAt]);
        } else {
            $sql = "INSERT INTO blocked_ip_list (ip_address, reason, block_type, blocked_at, expires_at, created_by) 
                    VALUES (?, ?, ?, NOW(), NULL, ?)
                    ON DUPLICATE KEY UPDATE 
                        reason = VALUES(reason), 
                        block_type = VALUES(block_type), 
                        blocked_at = NOW(), 
                        expires_at = NULL, 
                        created_by = VALUES(created_by)";
            $this->db->query($sql, [$ip, $reason, $type, $createdBy]);
        }
        $this->invalidateCache($ip);
        return true;
    }

    /**
     * ID로 차단 해제
     */
    public function unblockById(int $id): bool
    {
        $record = $this->getById($id);
        if (!$record) {
            return false;
        }

        $sql = "DELETE FROM blocked_ip_list WHERE blocked_ip_id = ?";
        $stmt = $this->db->query($sql, [$id]);
        $this->invalidateCache($record['ip_address']);
        return $stmt->rowCount() > 0;
    }

    /**
     * IP 주소로 차단 해제
     */
    public function unblockByIp(string $ip): bool
    {
        $sql = "DELETE FROM blocked_ip_list WHERE ip_address = ?";
        $stmt = $this->db->query($sql, [$ip]);
        $this->invalidateCache($ip);
        return $stmt->rowCount() > 0;
    }

    /**
     * ID로 단일 레코드 조회
     */
    public function getById(int $id): ?array
    {
        $sql = "SELECT * FROM blocked_ip_list WHERE blocked_ip_id = ?";
        return $this->db->fetch($sql, [$id]);
    }

    /**
     * 만료된 차단 정리
     */
    public function cleanExpired(): int
    {
        $sql = "DELETE FROM blocked_ip_list WHERE expires_at IS NOT NULL AND expires_at <= NOW()";
        $stmt = $this->db->query($sql);
        $count = $stmt->rowCount();
        if ($count > 0) {
            $this->cache->deletePattern('blocked_ip');
        }
        return $count;
    }

    /**
     * 통계 조회
     */
    public function getStats(): array
    {
        $sql = "SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN (expires_at IS NULL OR expires_at > NOW()) AND block_type = 'auto' THEN 1 ELSE 0 END) as active_auto,
                    SUM(CASE WHEN (expires_at IS NULL OR expires_at > NOW()) AND block_type = 'manual' THEN 1 ELSE 0 END) as active_manual,
                    SUM(CASE WHEN expires_at IS NOT NULL AND expires_at <= NOW() THEN 1 ELSE 0 END) as expired
                FROM blocked_ip_list";
        $result = $this->db->fetch($sql);
        return [
            'total' => (int)($result['total'] ?? 0),
            'active_auto' => (int)($result['active_auto'] ?? 0),
            'active_manual' => (int)($result['active_manual'] ?? 0),
            'expired' => (int)($result['expired'] ?? 0),
        ];
    }

    /**
     * 캐시 무효화
     */
    private function invalidateCache(string $ip = ''): void
    {
        $this->cache->deletePattern('blocked_ip');
    }
}
