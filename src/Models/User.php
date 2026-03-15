<?php

namespace Blog\Models;

use Blog\Database\Database;
use Blog\Core\Cache;

class User
{
    private $db;
    private $cache;

    public function __construct()
    {
        $this->db = Database::getInstance();
        $this->cache = Cache::getInstance();
    }

    public function authenticate(string $userId, string $password): ?array
    {
        $sql = "SELECT * FROM user_list WHERE user_id = ? AND user_pw = ? AND user_state = 0";
        $user = $this->db->fetch($sql, [$userId, $password]);
        
        if ($user) {
            $this->updateLastAction($user['user_index']);
            return $user;
        }
        
        return null;
    }

    public function getUserById(string $userId): ?array
    {
        $cacheKey = Cache::key('user', $userId);
        $cached = $this->cache->get($cacheKey);
        
        if ($cached !== null) {
            return $cached;
        }

        $sql = "SELECT * FROM user_list WHERE user_id = ?";
        $user = $this->db->fetch($sql, [$userId]);
        
        if ($user) {
            // 사용자 정보는 설정에서 TTL 가져오기
            $this->cache->set($cacheKey, $user, $this->cache->getTtl('user'));
        }
        
        return $user;
    }

    public function updateLastAction(int $userIndex): void
    {
        $sql = "UPDATE user_list SET user_last_action_datetime = NOW() WHERE user_index = ?";
        $this->db->query($sql, [$userIndex]);
    }

    public function canWrite(int $userIndex): bool
    {
        $cacheKey = Cache::key('user_can_write', $userIndex);
        $cached = $this->cache->get($cacheKey);
        
        if ($cached !== null) {
            return $cached;
        }

        $sql = "SELECT user_level FROM user_list WHERE user_index = ?";
        $user = $this->db->fetch($sql, [$userIndex]);
        
        if (!$user) {
            return false;
        }
        
        $canWrite = $user['user_level'] <= 3;
        
        // 권한 정보는 설정에서 TTL 가져오기
        $this->cache->set($cacheKey, $canWrite, $this->cache->getTtl('user_can_write'));
        
        return $canWrite;
    }

    public function getPostingLimitInfo(int $userIndex): ?array
    {
        $cacheKey = Cache::key('user_posting_limit', $userIndex);
        $cached = $this->cache->get($cacheKey);
        
        if ($cached !== null) {
            return $cached;
        }

        $sql = "SELECT user_posting_count, user_posting_limit FROM user_list WHERE user_index = ?";
        $user = $this->db->fetch($sql, [$userIndex]);
        
        if (!$user) {
            return null;
        }
        
        $result = [
            'current_count' => (int)$user['user_posting_count'],
            'limit' => (int)$user['user_posting_limit'],
            'is_limited' => $user['user_posting_count'] >= $user['user_posting_limit']
        ];
        
        // 게시글 제한 정보는 5분간 캐시
        $this->cache->set($cacheKey, $result, 300);
        
        return $result;
    }

    public function incrementPostCount(int $userIndex): void
    {
        $sql = "UPDATE user_list SET user_posting_count = user_posting_count + 1 WHERE user_index = ?";
        $this->db->query($sql, [$userIndex]);
        
        // 관련 캐시 무효화
        $this->cache->delete(Cache::key('user_posting_limit', $userIndex));
        $this->cache->delete(Cache::key('user_can_write', $userIndex));
    }

    public function getVisitorCount(): int
    {
        $visitYear = date("Y");
        $visitWeek = date("W");
        $yearWeek = $visitYear . str_pad($visitWeek, 2, '0', STR_PAD_LEFT);
        
        $cacheKey = Cache::key('visitor_count', $yearWeek);
        $cached = $this->cache->get($cacheKey);
        
        if ($cached !== null) {
            return $cached;
        }
        
        $sql = "SELECT visit_count FROM weekly_visitors WHERE year_week = ?";
        $result = $this->db->fetch($sql, [$yearWeek]);
        $count = $result ? (int)$result['visit_count'] : 0;
        
        // 방문자 수는 1시간간 캐시
        $this->cache->set($cacheKey, $count, 3600);
        
        return $count;
    }

    public function updateVisitorCount(): bool
    {
        if (session_status() === PHP_SESSION_NONE) {
            session_start();
        }
        
        $visitYear = date("Y");
        $visitWeek = date("W");
        $yearWeek = $visitYear . str_pad($visitWeek, 2, '0', STR_PAD_LEFT);
        $sessionKey = 'visitor_counted_' . $yearWeek;
        
        // 오래된 주의 세션 키들 정리 (현재 주가 아닌 것들)
        if (isset($_SESSION)) {
            foreach ($_SESSION as $key => $value) {
                if (strpos($key, 'visitor_counted_') === 0) {
                    $sessionYearWeek = substr($key, 16);
                    if ($sessionYearWeek !== $yearWeek) {
                        unset($_SESSION[$key]);
                    }
                }
            }
        }
        
        if (isset($_SESSION[$sessionKey])) {
            return false;
        }
        
        $sql = "INSERT INTO weekly_visitors VALUES (?, 1) ON DUPLICATE KEY UPDATE visit_count = visit_count + 1";
        $this->db->query($sql, [$yearWeek]);
        
        // 방문자 수 캐시 무효화
        $this->cache->delete(Cache::key('visitor_count', $yearWeek));
        
        $_SESSION[$sessionKey] = true;
        
        return true;
    }

    // ================================
    // 관리자용 메서드
    // ================================

    public function getAllUsers(): array
    {
        return $this->getAllUsersBySearch('');
    }

    public function getAllUsersBySearch(string $searchQuery = ''): array
    {
        $sql = "SELECT user_index, user_id, user_level, user_state, user_posting_count, user_posting_limit, user_last_action_datetime FROM user_list";
        $params = [];

        if ($searchQuery !== '') {
            $sql .= " WHERE user_id LIKE ?";
            $params[] = '%' . $searchQuery . '%';

            if (ctype_digit($searchQuery)) {
                $sql .= " OR user_index = ?";
                $params[] = (int)$searchQuery;
            }
        }

        $sql .= " ORDER BY user_level ASC, user_id ASC";

        return $this->db->fetchAll($sql, $params);
    }

    public function getUserByIndex(int $userIndex): ?array
    {
        $sql = "SELECT user_index, user_id, user_level, user_state, user_posting_count, user_posting_limit, user_last_action_datetime FROM user_list WHERE user_index = ?";
        return $this->db->fetch($sql, [$userIndex]);
    }

    public function createUser(string $userId, string $hashedPassword, int $level = 4, int $postingLimit = 10): int
    {
        $sql = "INSERT INTO user_list (user_id, user_pw, user_level, user_state, user_posting_count, user_posting_limit) VALUES (?, ?, ?, 0, 0, ?)";
        $this->db->query($sql, [$userId, $hashedPassword, $level, $postingLimit]);
        return (int)$this->db->lastInsertId();
    }

    public function isUserIdExists(string $userId): bool
    {
        $sql = "SELECT COUNT(*) as cnt FROM user_list WHERE user_id = ?";
        $result = $this->db->fetch($sql, [$userId]);
        return $result && (int)$result['cnt'] > 0;
    }

    public function updateUserLevel(int $userIndex, int $level): void
    {
        $sql = "UPDATE user_list SET user_level = ? WHERE user_index = ?";
        $this->db->query($sql, [$level, $userIndex]);
        $this->invalidateUserCache($userIndex);
    }

    public function updateUserState(int $userIndex, int $state): void
    {
        $sql = "UPDATE user_list SET user_state = ? WHERE user_index = ?";
        $this->db->query($sql, [$state, $userIndex]);
        $this->invalidateUserCache($userIndex);
    }

    public function updateUserPostingLimit(int $userIndex, int $limit): void
    {
        $sql = "UPDATE user_list SET user_posting_limit = ? WHERE user_index = ?";
        $this->db->query($sql, [$limit, $userIndex]);
        $this->cache->delete(Cache::key('user_posting_limit', $userIndex));
    }

    public function resetUserPassword(int $userIndex, string $hashedPassword): void
    {
        $sql = "UPDATE user_list SET user_pw = ? WHERE user_index = ?";
        $this->db->query($sql, [$hashedPassword, $userIndex]);
    }

    private function invalidateUserCache(int $userIndex): void
    {
        $this->cache->delete(Cache::key('user_can_write', $userIndex));
        $this->cache->delete(Cache::key('user_posting_limit', $userIndex));
        $this->cache->deletePattern('user_');
    }
}
