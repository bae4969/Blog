<?php

namespace Blog\Core;

class GeminiConfig
{
    private const FILE_PATH = __DIR__ . '/../../config/gemini.php';

    private const DEFAULT_MODEL = 'gemini-2.5-flash';
    private const DEFAULT_TIMEOUT = 60;
    private const TIMEOUT_MIN = 5;
    private const TIMEOUT_MAX = 180;

    public static function load(): array
    {
        $defaults = [
            'api_key' => '',
            'model' => self::DEFAULT_MODEL,
            'timeout_sec' => self::DEFAULT_TIMEOUT,
        ];

        if (!file_exists(self::FILE_PATH)) {
            return $defaults;
        }

        $data = require self::FILE_PATH;
        if (!is_array($data)) {
            return $defaults;
        }

        return [
            'api_key' => (string)($data['api_key'] ?? ''),
            'model' => (string)($data['model'] ?? self::DEFAULT_MODEL),
            'timeout_sec' => self::clampTimeout((int)($data['timeout_sec'] ?? self::DEFAULT_TIMEOUT)),
        ];
    }

    public static function save(array $config): void
    {
        $normalized = [
            'api_key' => (string)($config['api_key'] ?? ''),
            'model' => (string)($config['model'] ?? self::DEFAULT_MODEL),
            'timeout_sec' => self::clampTimeout((int)($config['timeout_sec'] ?? self::DEFAULT_TIMEOUT)),
        ];

        $content = "<?php\n\nreturn " . var_export($normalized, true) . ";\n";
        $written = @file_put_contents(self::FILE_PATH, $content, LOCK_EX);

        if ($written === false) {
            throw new \RuntimeException('gemini config write failed');
        }
    }

    public static function isValidApiKey(string $key): bool
    {
        return $key !== '' && (bool)preg_match('~^[A-Za-z0-9_\-]{20,200}$~', $key);
    }

    public static function isValidModel(string $model): bool
    {
        return $model !== '' && (bool)preg_match('~^[A-Za-z0-9._:\-/]{1,100}$~', $model);
    }

    public static function maskApiKey(string $key): string
    {
        if ($key === '') {
            return '(미설정)';
        }
        $len = strlen($key);
        if ($len <= 8) {
            return str_repeat('*', $len);
        }
        return substr($key, 0, 4) . '******' . substr($key, -4);
    }

    private static function clampTimeout(int $sec): int
    {
        return max(self::TIMEOUT_MIN, min(self::TIMEOUT_MAX, $sec));
    }
}
