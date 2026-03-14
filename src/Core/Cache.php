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
        return $this->cacheDir . '/' . md5($key) . '.cache';
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
}