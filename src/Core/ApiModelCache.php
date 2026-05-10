<?php

namespace Blog\Core;

class ApiModelCache
{
    private const CACHE_DIR = __DIR__ . '/../../cache/api_models';
    private const TTL_SECONDS = 86400;
    private const ALLOWED = ['gemini', 'openai'];

    public static function read(string $provider): ?array
    {
        if (!in_array($provider, self::ALLOWED, true)) {
            return null;
        }
        $path = self::path($provider);
        if (!is_file($path)) {
            return null;
        }
        $raw = @file_get_contents($path);
        if ($raw === false) {
            return null;
        }
        $decoded = json_decode($raw, true);
        if (!is_array($decoded) || !isset($decoded['models']) || !is_array($decoded['models'])) {
            return null;
        }

        $fetchedAt = (int)($decoded['fetched_at'] ?? 0);
        $models = [];
        foreach ($decoded['models'] as $m) {
            $s = trim((string)$m);
            if ($s !== '') {
                $models[] = $s;
            }
        }
        return [
            'fetched_at' => $fetchedAt,
            'models' => $models,
            'is_expired' => $fetchedAt > 0 && (time() - $fetchedAt) > self::TTL_SECONDS,
        ];
    }

    public static function write(string $provider, array $models): bool
    {
        if (!in_array($provider, self::ALLOWED, true)) {
            return false;
        }
        $dir = self::CACHE_DIR;
        if (!is_dir($dir) && !@mkdir($dir, 0775, true) && !is_dir($dir)) {
            return false;
        }

        $clean = [];
        foreach ($models as $m) {
            $s = trim((string)$m);
            if ($s !== '') {
                $clean[] = $s;
            }
        }

        $payload = json_encode([
            'fetched_at' => time(),
            'models' => array_values(array_unique($clean)),
        ], JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);
        if ($payload === false) {
            return false;
        }

        $written = @file_put_contents(self::path($provider), $payload, LOCK_EX);
        return $written !== false;
    }

    private static function path(string $provider): string
    {
        return self::CACHE_DIR . '/' . $provider . '.json';
    }
}
