<?php

namespace Blog\Models;

use HTMLPurifier;
use HTMLPurifier_Config;
use Blog\Database\Database;
use Blog\Core\Cache;

class Post
{
    private $db;
    private $cache;

    public function __construct()
    {
        $this->db = Database::getInstance();
        $this->cache = Cache::getInstance();
    }

    public function getMetaAll(int $userLevel, int $page = 1, int $perPage = 10, ?int $categoryId = null, ?string $search = null): array
    {
        // 검색어가 있으면 캐시하지 않음 (동적 결과)
        if ($search) {
            return $this->getMetaAllFromDb($userLevel, $page, $perPage, $categoryId, $search);
        }

        $cacheKey = Cache::key('posts_meta', $userLevel, $page, $perPage, $categoryId ?? 0);
        $cached = $this->cache->get($cacheKey);
        
        if ($cached !== null) {
            return $cached;
        }

        $posts = $this->getMetaAllFromDb($userLevel, $page, $perPage, $categoryId, $search);
        
        // 게시글 목록은 10분간 캐시
        $this->cache->set($cacheKey, $posts, 600);
        
        return $posts;
    }

    private function getMetaAllFromDb(int $userLevel, int $page = 1, int $perPage = 10, ?int $categoryId = null, ?string $search = null): array
    {
        $offset = ($page - 1) * $perPage;
        $whereConditions = [];
        $params = [];
        

        $whereConditions[] = "C.category_read_level >= ?";
        $params[] = $userLevel;

        if($userLevel > 1)
        {
            $whereConditions[] = "P.posting_state = ?";
            $params[] = 0;
        }

        if ($categoryId !== null && $categoryId > 0) {
            $whereConditions[] = "P.category_index = ?";
            $params[] = $categoryId;
        }

        if ($search) {
            $whereConditions[] = "P.posting_title LIKE ?";
            $params[] = "%{$search}%";
        }

        $whereClause = !empty($whereConditions) ? "WHERE " . implode(" AND ", $whereConditions) : "";

        $sql = "SELECT 
                    P.posting_index,
                    P.user_index,
                    P.category_index,
                    P.posting_state,
                    P.posting_first_post_datetime,
                    P.posting_last_edit_datetime,
                    P.posting_read_cnt,
                    P.posting_title,
                    P.posting_thumbnail,
                    P.posting_summary,
                    C.category_name,
                    U.user_id AS user_name
                FROM posting_list P
                LEFT JOIN category_list C 
                    ON P.category_index = C.category_index
                LEFT JOIN user_list U 
                    ON P.user_index = U.user_index
                {$whereClause}
                ORDER BY P.posting_index DESC
                LIMIT ? OFFSET ?";

        $params[] = $perPage;
        $params[] = $offset;

        return $this->db->fetchAll($sql, $params);
    }

    public function getDetailById(int $userLevel, int $postId): ?array
    {
        $cacheKey = Cache::key('post_detail', $userLevel, $postId);
        $cached = $this->cache->get($cacheKey);
        
        if ($cached !== null) {
            return $cached;
        }

        $sql = "SELECT P.*, C.category_name, U.user_id as user_name 
                FROM posting_list P 
                LEFT JOIN category_list C ON P.category_index = C.category_index 
                LEFT JOIN user_list U ON P.user_index = U.user_index 
                WHERE C.category_read_level >= ? AND P.posting_index = ?" ;
        
        $post = $this->db->fetch($sql, [$userLevel, $postId]);
        
        if ($post) {
            // 게시글 상세는 30분간 캐시
            $this->cache->set($cacheKey, $post, 1800);
        }
        
        return $post;
    }

    public function create(array $data): int
    {
        $sql = "SELECT COUNT(*) AS count
                FROM category_list
                WHERE category_write_level >= ? AND category_index = ?";
        $result = $this->db->fetch($sql, [$data['user_level'], $data['category_index']]);
        if ($result === null || (int)$result['count'] < 1) {
            throw new \Exception("해당 카테고리에 글을 작성할 권한이 없습니다.");
        }

        // Purifier 준비
        $config = HTMLPurifier_Config::createDefault();
        $config->set('Cache.SerializerPath', __DIR__ . '/../../cache/htmlpurifier'); // 웹서버 쓰기 가능 경로
        $config->set('HTML.Allowed', 'p,br,strong,em,ul,ol,li,a[href|title],img[src|alt|title],code,pre,blockquote');
        $config->set('URI.AllowedSchemes', ['http'=>true,'https'=>true,'data'=>false]); // data: 금지 권장
        $purifier = new HTMLPurifier($config);

        // 원문
        $title_raw = (string)($data['title'] ?? '');
        $content_raw = (string)$data['content'];

        // 첫 이미지 추출은 정제 전 원문 기준으로 시도
        $thumbnail = '';
        if (preg_match('/<img[^>]+src=["\']?([^"\'>\s]+)["\']?/i', $content_raw, $m)) {
            $thumbnail = $m[1];
        } elseif (preg_match('/!\[[^\]]*\]\(([^)]+)\)/', $content_raw, $m)) {
            $thumbnail = $m[1];
        }

        // 제목 정제
        $title = htmlspecialchars(strip_tags($title_raw), ENT_QUOTES | ENT_HTML5, 'UTF-8');

        // 본문 정제
        $content = $purifier->purify($content_raw);

        // 요약 생성(정제본에서 이미지 제거 후 200자)
        $tmp = preg_replace('/<img\b[^>]*>/i', '', $content);
        $tmp = strip_tags($tmp);
        $tmp = html_entity_decode($tmp, ENT_QUOTES | ENT_HTML5, 'UTF-8');
        $tmp = preg_replace('/\s+/u', ' ', trim($tmp));
        $summary = mb_substr($tmp, 0, 200, 'UTF-8');

        // INSERT
        $sql = "INSERT INTO posting_list
                (posting_title, posting_content, posting_summary, posting_thumbnail,
                category_index, user_index, posting_first_post_datetime)
                VALUES (?, ?, ?, ?, ?, ?, NOW())";

        $this->db->query($sql, [
            $title,
            $content,
            $summary,
            $thumbnail,
            $data['category_index'],
            $data['user_index']
        ]);

        $postId = (int)$this->db->lastInsertId();
        
        // 게시글 관련 캐시 무효화
        $this->cache->deletePattern('posts_meta');
        $this->cache->deletePattern('post_count');
        
        return $postId;
    }

    public function update(int $postId, array $data): bool
    {
        $sql = "UPDATE posting_list 
                SET posting_title = ?, posting_content = ?, category_index = ?, posting_last_edit_datetime = NOW() 
                WHERE posting_index = ?";
        
        $stmt = $this->db->query($sql, [
            $data['title'],
            $data['content'],
            $data['category_index'],
            $postId
        ]);

        if ($stmt->rowCount() > 0) {
            // 게시글 관련 캐시 무효화
            $this->cache->deletePattern('posts_meta');
            $this->cache->deletePattern('post_detail');
            $this->cache->deletePattern('post_count');
            return true;
        }
        
        return false;
    }

    public function enable(int $postId): bool
    {
        $sql = "UPDATE posting_list SET posting_state = 0 WHERE posting_index = ?";
        $stmt = $this->db->query($sql, [$postId]);
        
        if ($stmt->rowCount() > 0) {
            // 게시글 관련 캐시 무효화
            $this->cache->deletePattern('posts_meta');
            $this->cache->deletePattern('post_detail');
            $this->cache->deletePattern('post_count');
            return true;
        }
        
        return false;
    }
    
    public function disable(int $postId): bool
    {
        $sql = "UPDATE posting_list SET posting_state = 1 WHERE posting_index = ?";
        $stmt = $this->db->query($sql, [$postId]);
        
        if ($stmt->rowCount() > 0) {
            // 게시글 관련 캐시 무효화
            $this->cache->deletePattern('posts_meta');
            $this->cache->deletePattern('post_detail');
            $this->cache->deletePattern('post_count');
            return true;
        }
        
        return false;
    }

    public function getTotalCount(?int $categoryId = null, ?string $search = null): int
    {
        // 검색어가 있으면 캐시하지 않음
        if ($search) {
            return $this->getTotalCountFromDb($categoryId, $search);
        }

        $cacheKey = Cache::key('post_count', $categoryId ?? 0);
        $cached = $this->cache->get($cacheKey);
        
        if ($cached !== null) {
            return $cached;
        }

        $count = $this->getTotalCountFromDb($categoryId, $search);
        
        // 총 개수는 10분간 캐시
        $this->cache->set($cacheKey, $count, 600);
        
        return $count;
    }

    private function getTotalCountFromDb(?int $categoryId = null, ?string $search = null): int
    {
        $whereConditions = [];
        $params = [];

        if ($categoryId !== null && $categoryId > 0) {
            $whereConditions[] = "category_index = ?";
            $params[] = $categoryId;
        }

        if ($search) {
            $whereConditions[] = "posting_title LIKE ?";
            $params[] = "%{$search}%";
        }

        $whereClause = !empty($whereConditions) ? "WHERE " . implode(" AND ", $whereConditions) : "";

        $sql = "SELECT COUNT(*) as count FROM posting_list {$whereClause}";
        $result = $this->db->fetch($sql, $params);
        
        return $result ? (int)$result['count'] : 0;
    }

    public function getByUserId(int $userId): array
    {
        $sql = "SELECT P.*, C.category_name 
                FROM posting_list P 
                LEFT JOIN category_list C ON P.category_index = C.category_index 
                WHERE P.user_index = ? 
                ORDER BY P.posting_index DESC";
        
        return $this->db->fetchAll($sql, [$userId]);
    }

    public function incrementReadCount(int $postId): bool
    {
        if (session_status() === PHP_SESSION_NONE) {
            session_start();
        }
        
        $today = date("Y-m-d");
        $sessionKey = 'post_read_' . $postId . '_' . $today;
        
        // 오래된 날짜의 세션 키들 정리
        if (isset($_SESSION)) {
            foreach ($_SESSION as $key => $value) {
                if (strpos($key, 'post_read_' . $postId . '_') === 0) {
                    $sessionDate = substr($key, strlen('post_read_' . $postId . '_'));
                    if ($sessionDate !== $today) {
                        unset($_SESSION[$key]);
                    }
                }
            }
        }
        
        // 이미 오늘 조회한 포스트인지 확인
        if (isset($_SESSION[$sessionKey])) {
            return false;
        }
        
        // 조회수 증가
        $sql = "UPDATE posting_list SET posting_read_cnt = posting_read_cnt + 1 WHERE posting_index = ?";
        $this->db->query($sql, [$postId]);
        
        // 해당 게시글 상세 캐시 무효화 (조회수 변경)
        $this->cache->deletePattern('post_detail');
        
        // 세션에 조회 완료 표시
        $_SESSION[$sessionKey] = true;
        
        return true;
    }
}
