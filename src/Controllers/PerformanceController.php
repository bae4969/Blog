<?php

namespace Blog\Controllers;

use Blog\Database\Database;

class PerformanceController extends BaseController
{
    private $db;

    public function __construct()
    {
        parent::__construct();
        $this->db = Database::getInstance();
    }

    /**
     * 쿼리 성능 통계
     */
    public function queryStats(): void
    {
        $stats = $this->db->getQueryStats();
        $queryLog = $this->db->getQueryLog();
        
        // 최근 10개 쿼리만 표시
        $recentQueries = array_slice($queryLog, -10);
        
        $this->json([
            'success' => true,
            'stats' => $stats,
            'recent_queries' => $recentQueries
        ]);
    }

    /**
     * 느린 쿼리 목록
     */
    public function slowQueries(): void
    {
        $queryLog = $this->db->getQueryLog();
        $slowQueries = array_filter($queryLog, function($query) {
            return $query['execution_time'] > 0.1; // 100ms 이상
        });
        
        // 실행 시간 순으로 정렬
        usort($slowQueries, function($a, $b) {
            return $b['execution_time'] <=> $a['execution_time'];
        });
        
        $this->json([
            'success' => true,
            'slow_queries' => $slowQueries,
            'count' => count($slowQueries)
        ]);
    }

    /**
     * 중복 쿼리 분석
     */
    public function duplicateQueries(): void
    {
        $queryLog = $this->db->getQueryLog();
        $queryCounts = [];
        
        foreach ($queryLog as $query) {
            $sql = $query['sql'];
            if (!isset($queryCounts[$sql])) {
                $queryCounts[$sql] = [
                    'count' => 0,
                    'total_time' => 0,
                    'avg_time' => 0,
                    'first_execution' => $query['timestamp'],
                    'last_execution' => $query['timestamp']
                ];
            }
            
            $queryCounts[$sql]['count']++;
            $queryCounts[$sql]['total_time'] += $query['execution_time'];
            $queryCounts[$sql]['last_execution'] = $query['timestamp'];
        }
        
        // 평균 시간 계산
        foreach ($queryCounts as $sql => &$data) {
            $data['avg_time'] = $data['total_time'] / $data['count'];
        }
        
        // 실행 횟수 순으로 정렬
        uasort($queryCounts, function($a, $b) {
            return $b['count'] <=> $a['count'];
        });
        
        // 2회 이상 실행된 쿼리만 필터링
        $duplicates = array_filter($queryCounts, function($data) {
            return $data['count'] > 1;
        });
        
        $this->json([
            'success' => true,
            'duplicate_queries' => $duplicates,
            'total_unique_queries' => count($queryCounts),
            'duplicate_count' => count($duplicates)
        ]);
    }

    /**
     * 시스템 성능 정보
     */
    public function systemInfo(): void
    {
        $this->json([
            'success' => true,
            'system' => [
                'memory_usage' => memory_get_usage(true),
                'memory_peak' => memory_get_peak_usage(true),
                'memory_limit' => ini_get('memory_limit'),
                'execution_time' => microtime(true) - $_SERVER['REQUEST_TIME_FLOAT'],
                'php_version' => PHP_VERSION,
                'server_time' => date('Y-m-d H:i:s'),
                'timezone' => date_default_timezone_get()
            ],
            'cache' => [
                'cache_dir_exists' => is_dir(__DIR__ . '/../../cache/data'),
                'cache_dir_writable' => is_writable(__DIR__ . '/../../cache/data'),
                'cache_files_count' => count(glob(__DIR__ . '/../../cache/data/*'))
            ]
        ]);
    }

    /**
     * 성능 최적화 권장사항
     */
    public function recommendations(): void
    {
        $stats = $this->db->getQueryStats();
        $queryLog = $this->db->getQueryLog();
        
        $recommendations = [];
        
        // 느린 쿼리 권장사항
        if ($stats['slow_queries'] > 0) {
            $recommendations[] = [
                'type' => 'slow_queries',
                'message' => "{$stats['slow_queries']}개의 느린 쿼리가 발견되었습니다.",
                'suggestion' => '인덱스 추가나 쿼리 최적화를 고려해보세요.'
            ];
        }
        
        // 중복 쿼리 권장사항
        $queryCounts = [];
        foreach ($queryLog as $query) {
            $sql = $query['sql'];
            $queryCounts[$sql] = ($queryCounts[$sql] ?? 0) + 1;
        }
        
        $duplicates = array_filter($queryCounts, function($count) {
            return $count > 3;
        });
        
        if (!empty($duplicates)) {
            $recommendations[] = [
                'type' => 'duplicate_queries',
                'message' => count($duplicates) . '개의 중복 쿼리가 발견되었습니다.',
                'suggestion' => '캐시를 활용하여 중복 쿼리를 줄이세요.'
            ];
        }
        
        // 메모리 사용량 권장사항
        $memoryUsage = memory_get_usage(true);
        $memoryLimit = ini_get('memory_limit');
        $memoryLimitBytes = $this->parseMemoryLimit($memoryLimit);
        
        if ($memoryUsage > $memoryLimitBytes * 0.8) {
            $recommendations[] = [
                'type' => 'memory_usage',
                'message' => '메모리 사용량이 높습니다.',
                'suggestion' => '메모리 사용량을 모니터링하고 필요시 메모리 제한을 늘리세요.'
            ];
        }
        
        $this->json([
            'success' => true,
            'recommendations' => $recommendations,
            'stats' => $stats
        ]);
    }

    /**
     * 메모리 제한 파싱
     */
    private function parseMemoryLimit(string $limit): int
    {
        $limit = trim($limit);
        $last = strtolower($limit[strlen($limit)-1]);
        $limit = (int) $limit;
        
        switch($last) {
            case 'g':
                $limit *= 1024;
            case 'm':
                $limit *= 1024;
            case 'k':
                $limit *= 1024;
        }
        
        return $limit;
    }
}
