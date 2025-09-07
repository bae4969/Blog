<?php

namespace Blog\Controllers;

use Blog\Core\Cache;

class CacheController extends BaseController
{
    private $cache;

    public function __construct()
    {
        parent::__construct();
        $this->cache = Cache::getInstance();
    }

    /**
     * 캐시 통계 조회
     */
    public function stats(): void
    {
        $stats = $this->cache->getStats();
        
        $this->json([
            'success' => true,
            'stats' => $stats,
            'memory_usage' => memory_get_usage(true),
            'memory_peak' => memory_get_peak_usage(true)
        ]);
    }

    /**
     * 캐시 클리어
     */
    public function clear(): void
    {
        $this->cache->clear();
        
        $this->json([
            'success' => true,
            'message' => '모든 캐시가 삭제되었습니다.'
        ]);
    }

    /**
     * 특정 패턴의 캐시 삭제
     */
    public function clearPattern(): void
    {
        $pattern = $this->getParam('pattern', '');
        
        if (empty($pattern)) {
            $this->json([
                'success' => false,
                'message' => '패턴을 입력해주세요.'
            ]);
            return;
        }

        $this->cache->deletePattern($pattern);
        
        $this->json([
            'success' => true,
            'message' => "패턴 '{$pattern}'에 해당하는 캐시가 삭제되었습니다."
        ]);
    }

    /**
     * 캐시 워밍업 (자주 사용되는 데이터 미리 로드)
     */
    public function warmup(): void
    {
        $userLevel = $this->auth->getCurrentUserLevel();
        
        // 카테고리 목록 캐시 워밍업
        $categoryModel = new \Blog\Models\Category();
        $categoryModel->getReadAll($userLevel);
        $categoryModel->getWriteAll($userLevel);
        
        // 게시글 목록 캐시 워밍업 (첫 페이지)
        $postModel = new \Blog\Models\Post();
        $postModel->getMetaAll($userLevel, 1, 10);
        $postModel->getTotalCount();
        
        // 방문자 수 캐시 워밍업
        $userModel = new \Blog\Models\User();
        $userModel->getVisitorCount();
        
        $this->json([
            'success' => true,
            'message' => '캐시 워밍업이 완료되었습니다.'
        ]);
    }

    /**
     * 캐시 상태 확인
     */
    public function status(): void
    {
        $stats = $this->cache->getStats();
        $cacheDir = __DIR__ . '/../../cache/data';
        
        $fileCount = 0;
        $totalSize = 0;
        
        if (is_dir($cacheDir)) {
            $files = glob($cacheDir . '/*');
            $fileCount = count($files);
            
            foreach ($files as $file) {
                $totalSize += filesize($file);
            }
        }
        
        $this->json([
            'success' => true,
            'cache' => [
                'memory_count' => $stats['memory_cache_count'],
                'file_count' => $fileCount,
                'total_size' => $totalSize,
                'total_size_mb' => round($totalSize / 1024 / 1024, 2),
                'cache_dir' => $cacheDir,
                'cache_dir_writable' => is_writable($cacheDir)
            ]
        ]);
    }
}