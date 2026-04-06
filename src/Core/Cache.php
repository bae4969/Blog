<?php

namespace Blog\Core;

class Cache
{
    private static $instance = null;
    private $cache = [];
    private $cacheDir;
    private $defaultTtl = 3600; // 1시간
    private $config;

    private function __construct()
    {
        $this->config = require __DIR__ . '/../../config/cache.php';
        $this->cacheDir = $this->config['cache']['cache_dir'];
        $this->defaultTtl = $this->config['cache']['default_ttl'];
        
        // 캐시 디렉토리 생성
        if (!is_dir($this->cacheDir)) {
            mkdir($this->cacheDir, 0755, true);
        }
    }

    public static function getInstance(): self
    {
        if (self::$instance === null) {
            self::$instance = new self();
        }
        return self::$instance;
    }

    /**
     * 캐시에서 데이터 가져오기
     */
    public function get(string $key)
    {
        // 메모리 캐시에서 먼저 확인
        if (isset($this->cache[$key])) {
            $data = $this->cache[$key];
            if ($data['expires'] > time()) {
                return $data['value'];
            } else {
                unset($this->cache[$key]);
            }
        }

        // 파일 캐시에서 확인
        $filePath = $this->getFilePath($key);
        if (file_exists($filePath)) {
            $data = unserialize(file_get_contents($filePath), ['allowed_classes' => false]);
            if ($data['expires'] > time()) {
                // 메모리 캐시에도 저장
                $this->cache[$key] = $data;
                return $data['value'];
            } else {
                // 만료된 파일 삭제
                unlink($filePath);
            }
        }

        return null;
    }

    /**
     * 캐시에 데이터 저장
     */
    public function set(string $key, $value, int $ttl = null): void
    {
        $ttl = $ttl ?? $this->defaultTtl;
        $data = [
            'value' => $value,
            'expires' => time() + $ttl,
            'created' => time()
        ];

        // 메모리 캐시에 저장
        $this->cache[$key] = $data;

        // 파일 캐시에 저장
        $filePath = $this->getFilePath($key);
        file_put_contents($filePath, serialize($data), LOCK_EX);
    }

    /**
     * 캐시에서 데이터 삭제
     */
    public function delete(string $key): void
    {
        // 메모리 캐시에서 삭제
        unset($this->cache[$key]);

        // 파일 캐시에서 삭제
        $filePath = $this->getFilePath($key);
        if (file_exists($filePath)) {
            unlink($filePath);
        }
    }

    /**
     * 패턴으로 캐시 삭제
     */
    public function deletePattern(string $pattern): void
    {
        $files = glob($this->cacheDir . '/' . $pattern . '*');
        foreach ($files as $file) {
            unlink($file);
        }

        // 메모리 캐시에서도 패턴 매칭으로 삭제
        foreach ($this->cache as $key => $value) {
            if (fnmatch($pattern . '*', $key)) {
                unset($this->cache[$key]);
            }
        }
    }

    /**
     * 캐시 무효화 (특정 키들)
     */
    public function invalidate(array $keys): void
    {
        foreach ($keys as $key) {
            $this->delete($key);
        }
    }

    /**
     * 캐시 클리어
     */
    public function clear(): void
    {
        $this->cache = [];
        $files = glob($this->cacheDir . '/*');
        foreach ($files as $file) {
            unlink($file);
        }
    }

    /**
     * 캐시 통계 정보
     */
    public function getStats(): array
    {
        $memoryCount = count($this->cache);
        $fileCount = count(glob($this->cacheDir . '/*'));
        
        return [
            'memory_cache_count' => $memoryCount,
            'file_cache_count' => $fileCount,
            'total_cache_count' => $memoryCount + $fileCount
        ];
    }

    /**
     * 캐시 파일 상세 정보 (패턴별 그룹)
     */
    public function getFileDetails(): array
    {
        $files = glob($this->cacheDir . '/*.cache');
        $groups = [];
        $totalSize = 0;
        $expiredCount = 0;
        $now = time();

        foreach ($files as $file) {
            $size = filesize($file);
            $totalSize += $size;

            $raw = @file_get_contents($file);
            if ($raw === false) {
                continue;
            }
            $data = @unserialize($raw, ['allowed_classes' => false]);
            if (!is_array($data) || !isset($data['expires'], $data['created'])) {
                continue;
            }

            $expired = $data['expires'] <= $now;
            if ($expired) {
                $expiredCount++;
            }

            // 파일명에서 키를 복원할 수 없으므로 created/expires 기준으로 그룹핑 안 함
            // 대신 파일 mtime 기준 최근순 정렬 정보 제공
        }

        return [
            'file_count' => count($files),
            'total_size' => $totalSize,
            'total_size_formatted' => $this->formatBytes($totalSize),
            'expired_count' => $expiredCount,
            'active_count' => count($files) - $expiredCount,
            'cache_dir' => $this->cacheDir,
            'cache_dir_writable' => is_writable($this->cacheDir),
        ];
    }

    /**
     * 만료된 캐시만 삭제
     */
    public function clearExpired(): int
    {
        $files = glob($this->cacheDir . '/*.cache');
        $count = 0;
        $now = time();

        foreach ($files as $file) {
            $raw = @file_get_contents($file);
            if ($raw === false) {
                continue;
            }
            $data = @unserialize($raw, ['allowed_classes' => false]);
            if (is_array($data) && isset($data['expires']) && $data['expires'] <= $now) {
                @unlink($file);
                $count++;
            }
        }

        // 메모리 캐시에서도 만료된 것 정리
        foreach ($this->cache as $key => $value) {
            if ($value['expires'] <= $now) {
                unset($this->cache[$key]);
            }
        }

        return $count;
    }

    private function formatBytes(int $bytes): string
    {
        if ($bytes >= 1048576) {
            return round($bytes / 1048576, 2) . ' MB';
        } elseif ($bytes >= 1024) {
            return round($bytes / 1024, 2) . ' KB';
        }
        return $bytes . ' B';
    }

    /**
     * 캐시 파일 경로 생성
     */
    private function getFilePath(string $key): string
    {
        $safe = preg_replace('/[^a-zA-Z0-9_\-.]/', '_', $key);
        return $this->cacheDir . '/' . $safe . '.cache';
    }

    /**
     * 캐시 키 생성 헬퍼
     */
    public static function key(string $prefix, ...$params): string
    {
        return $prefix . ':' . md5(implode(':', $params));
    }

    /**
     * 설정에서 TTL 가져오기
     */
    public function getTtl(string $key): int
    {
        return $this->config['cache_ttl'][$key] ?? $this->defaultTtl;
    }

    /**
     * 캐시 설정 가져오기
     */
    public function getConfig(): array
    {
        return $this->config;
    }

    /**
     * 캐시가 활성화되어 있는지 확인
     */
    public function isEnabled(): bool
    {
        return $this->config['cache']['enabled'];
    }

    // ──────────────────────────────────────────────
    // 주식 일별 캔들 캐시 (gzip 파일, 인메모리 배열 우회)
    // ──────────────────────────────────────────────

    /**
     * 스톡 일별 캐시 디렉토리 경로
     */
    public function getStockDayCacheDir(): string
    {
        return $this->config['stock_day_cache']['cache_dir']
            ?? (dirname($this->cacheDir) . '/stock');
    }

    /**
     * 스톡 일별 캐시 활성화 여부
     */
    public function isStockDayCacheEnabled(): bool
    {
        return (bool)($this->config['stock_day_cache']['enabled'] ?? false);
    }

    /**
     * 스톡 오늘 데이터 TTL (초)
     */
    public function getStockDayTodayTtl(): int
    {
        return (int)($this->config['stock_day_cache']['today_ttl'] ?? 60);
    }

    /**
     * 스톡 일별 캐시에서 데이터 읽기
     * 메모리 배열($this->cache)을 사용하지 않아 memory_limit 문제 회피
     *
     * @param string $filePath gzip 캐시 파일 절대 경로
     * @return array|null 캔들 행 배열 또는 null(미스)
     */
    public function stockCacheGet(string $filePath): ?array
    {
        if (!file_exists($filePath)) {
            return null;
        }

        $compressed = @file_get_contents($filePath);
        if ($compressed === false) {
            return null;
        }

        $raw = @gzdecode($compressed);
        if ($raw === false) {
            return null;
        }

        $data = @unserialize($raw, ['allowed_classes' => false]);
        return is_array($data) ? $data : null;
    }

    /**
     * 스톡 일별 캐시에 데이터 저장 (gzip 압축)
     * 메모리 배열($this->cache)에 저장하지 않음
     *
     * @param string $filePath gzip 캐시 파일 절대 경로
     * @param array $data 캔들 행 배열
     */
    public function stockCacheSet(string $filePath, array $data): void
    {
        $dir = dirname($filePath);
        if (!is_dir($dir)) {
            mkdir($dir, 0755, true);
        }

        $compressed = gzencode(serialize($data), 6);
        file_put_contents($filePath, $compressed, LOCK_EX);
    }

    /**
     * 스톡 일별 캐시 파일이 유효한지 확인
     *
     * @param string $filePath 캐시 파일 경로
     * @param bool $isToday 오늘 날짜인지 여부
     * @return bool
     */
    public function stockCacheIsFresh(string $filePath, bool $isToday): bool
    {
        if (!file_exists($filePath)) {
            return false;
        }

        // 과거 날짜: 파일이 존재하면 영구 유효
        if (!$isToday) {
            return true;
        }

        // 오늘 날짜: mtime 기반 TTL 체크
        $mtime = filemtime($filePath);
        return ($mtime !== false) && (time() - $mtime < $this->getStockDayTodayTtl());
    }

    /**
     * 스톡 일별 캐시 통계 정보
     */
    public function getStockDayCacheDetails(): array
    {
        $baseDir = $this->getStockDayCacheDir();
        if (!is_dir($baseDir)) {
            return [
                'enabled' => $this->isStockDayCacheEnabled(),
                'file_count' => 0,
                'total_size' => 0,
                'total_size_formatted' => '0 B',
                'symbol_count' => 0,
                'cache_dir' => $baseDir,
            ];
        }

        $totalSize = 0;
        $fileCount = 0;
        $symbolDirs = glob($baseDir . '/*', GLOB_ONLYDIR);
        $symbolCount = count($symbolDirs);

        foreach ($symbolDirs as $symbolDir) {
            $files = glob($symbolDir . '/*.gz');
            $fileCount += count($files);
            foreach ($files as $file) {
                $totalSize += filesize($file);
            }
        }

        return [
            'enabled' => $this->isStockDayCacheEnabled(),
            'file_count' => $fileCount,
            'total_size' => $totalSize,
            'total_size_formatted' => $this->formatBytes($totalSize),
            'symbol_count' => $symbolCount,
            'cache_dir' => $baseDir,
        ];
    }

    /**
     * 스톡 일별 캐시 정리 (retention 기간 초과 파일 삭제)
     */
    public function cleanupStockDayCache(): int
    {
        $baseDir = $this->getStockDayCacheDir();
        $retentionDays = (int)($this->config['stock_day_cache']['retention_days'] ?? 90);

        if (!is_dir($baseDir)) {
            return 0;
        }

        $cutoffDate = date('Y-m-d', strtotime("-{$retentionDays} days"));
        $deletedCount = 0;

        $symbolDirs = glob($baseDir . '/*', GLOB_ONLYDIR);
        foreach ($symbolDirs as $symbolDir) {
            $files = glob($symbolDir . '/*.gz');
            foreach ($files as $file) {
                $filename = basename($file, '.gz'); // YYYY-MM-DD
                if (preg_match('/^\d{4}-\d{2}-\d{2}$/', $filename) && $filename < $cutoffDate) {
                    @unlink($file);
                    $deletedCount++;
                }
            }

            // 빈 디렉토리 삭제
            $remaining = glob($symbolDir . '/*');
            if (empty($remaining)) {
                @rmdir($symbolDir);
            }
        }

        return $deletedCount;
    }

    /**
     * 스톡 일별 캐시 전체 삭제
     */
    public function clearStockDayCache(): int
    {
        $baseDir = $this->getStockDayCacheDir();
        if (!is_dir($baseDir)) {
            return 0;
        }

        $deletedCount = 0;
        $symbolDirs = glob($baseDir . '/*', GLOB_ONLYDIR);
        foreach ($symbolDirs as $symbolDir) {
            $files = glob($symbolDir . '/*.gz');
            foreach ($files as $file) {
                @unlink($file);
                $deletedCount++;
            }
            @rmdir($symbolDir);
        }

        return $deletedCount;
    }
}