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
            $data = unserialize(file_get_contents($filePath));
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