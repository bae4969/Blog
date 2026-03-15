<?php

namespace Blog\Models;

use Blog\Database\Database;
use Blog\Core\Cache;

class Category
{
    private $db;
    private $cache;

    public function __construct()
    {
        $this->db = Database::getInstance();
        $this->cache = Cache::getInstance();
    }

    public function getReadAll(int $userLevel): array
    {
        $cacheKey = Cache::key('categories_read', $userLevel);
        $cached = $this->cache->get($cacheKey);
        
        if ($cached !== null) {
            return $cached;
        }

        $sql = "SELECT * FROM category_list WHERE category_read_level >= ? ORDER BY category_order ASC";
        $categories = $this->db->fetchAll($sql, [$userLevel]);
        
        // 카테고리 목록은 1시간간 캐시
        $this->cache->set($cacheKey, $categories, 3600);
        
        return $categories;
    }

    public function getWriteAll(int $userLevel): array
    {
        $cacheKey = Cache::key('categories_write', $userLevel);
        $cached = $this->cache->get($cacheKey);
        
        if ($cached !== null) {
            return $cached;
        }

        $sql = "SELECT * FROM category_list WHERE category_write_level >= ? ORDER BY category_order ASC";
        $categories = $this->db->fetchAll($sql, [$userLevel]);
        
        // 카테고리 목록은 1시간간 캐시
        $this->cache->set($cacheKey, $categories, 3600);
        
        return $categories;
    }

    public function getById(int $userLevel, int $categoryId): ?array
    {
        $sql = "SELECT * FROM category_list WHERE category_read_level >= ? AND category_index = ?";
        return $this->db->fetch($sql, [$userLevel, $categoryId]);
    }

    public function getReadableList(int $userLevel): ?array
    {
        $sql = "SELECT * FROM category_list WHERE category_read_level >= ?";
        return $this->db->fetch($sql, [$userLevel]);
    } 

    public function getWritableList(int $userLevel): ?array
    {
        $sql = "SELECT * FROM category_list WHERE category_write_level >= ?";
        return $this->db->fetch($sql, [$userLevel]);
    } 

    public function create(string $name, int $order = 0, int $readLevel = 0, int $writeLevel = 0): int
    {
        $sql = "INSERT INTO category_list (category_name, category_order, category_read_level, category_write_level) VALUES (?, ?, ?, ?)";
        $this->db->query($sql, [$name, $order, $readLevel, $writeLevel]);
        
        // 카테고리 관련 캐시 무효화
        $this->cache->deletePattern('categories_');
        
        return (int)$this->db->lastInsertId();
    }

    public function delete(int $categoryId): bool
    {
        $sql = "SELECT COUNT(*) as count FROM posting_list WHERE category_index = ?";
        $result = $this->db->fetch($sql, [$categoryId]);
        
        if ($result && $result['count'] > 0) {
            return false;
        }

        $sql = "DELETE FROM category_list WHERE category_index = ?";
        $stmt = $this->db->query($sql, [$categoryId]);
        
        if ($stmt->rowCount() > 0) {
            // 카테고리 관련 캐시 무효화
            $this->cache->deletePattern('categories_');
            return true;
        }
        
        return false;
    }

    public function getPostCount(int $categoryId): int
    {
        $sql = "SELECT COUNT(*) as count FROM posting_list WHERE category_index = ?";
        $result = $this->db->fetch($sql, [$categoryId]);
        return $result ? (int)$result['count'] : 0;
    }

    public function isWriteAuth(int $userLevel, int $categoryId): bool
    {
        $sql = "SELECT COUNT(*) as count FROM category_list WHERE category_write_level >= ? AND category_index = ?";
        $result = $this->db->fetch($sql, [$userLevel, $categoryId]);
        return ($result && $result['count'] > 0);
    }

    public function isReadAuth(int $userLevel, int $categoryId): bool
    {
        $sql = "SELECT COUNT(*) as count FROM category_list WHERE category_read_level >= ? AND category_index = ?";
        $result = $this->db->fetch($sql, [$userLevel, $categoryId]);
        return ($result && $result['count'] > 0);
    }

    public function getAllForAdmin(): array
    {
        $sql = "SELECT c.*, (SELECT COUNT(*) FROM posting_list p WHERE p.category_index = c.category_index) as post_count
                FROM category_list c ORDER BY c.category_order ASC, c.category_index ASC";
        return $this->db->fetchAll($sql);
    }

    public function getByIdForAdmin(int $categoryId): ?array
    {
        $sql = "SELECT * FROM category_list WHERE category_index = ?";
        return $this->db->fetch($sql, [$categoryId]);
    }

    public function update(int $categoryId, string $name, int $readLevel, int $writeLevel): bool
    {
        $sql = "UPDATE category_list SET category_name = ?, category_read_level = ?, category_write_level = ? WHERE category_index = ?";
        $stmt = $this->db->query($sql, [$name, $readLevel, $writeLevel, $categoryId]);

        if ($stmt->rowCount() > 0) {
            $this->cache->deletePattern('categories_');
            return true;
        }

        return false;
    }

    public function getMaxOrder(): int
    {
        $sql = "SELECT MAX(category_order) as max_order FROM category_list";
        $result = $this->db->fetch($sql);
        return $result && $result['max_order'] !== null ? (int)$result['max_order'] : -1;
    }

    public function swapOrder(int $categoryIdA, int $categoryIdB): bool
    {
        $a = $this->getByIdForAdmin($categoryIdA);
        $b = $this->getByIdForAdmin($categoryIdB);
        if (!$a || !$b) {
            return false;
        }

        $orderA = (int)$a['category_order'];
        $orderB = (int)$b['category_order'];

        // category_order가 tinyint unsigned + UNIQUE이므로 사용되지 않는 임시값으로 3단계 swap
        $sql = "UPDATE category_list SET category_order = ? WHERE category_index = ?";
        $usedOrders = array_column($this->db->fetchAll("SELECT category_order FROM category_list"), 'category_order');
        $tempOrder = 255;
        while (in_array((string)$tempOrder, $usedOrders, true)) {
            $tempOrder--;
        }
        $this->db->query($sql, [$tempOrder, $categoryIdA]);
        $this->db->query($sql, [$orderA, $categoryIdB]);
        $this->db->query($sql, [$orderB, $categoryIdA]);

        $this->cache->deletePattern('categories_');
        return true;
    }
}
