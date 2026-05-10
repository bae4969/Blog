<?php

namespace Blog\Core;

class YouTubeConfig
{
    private const FILE_PATH = __DIR__ . '/../../config/youtube.php';

    public static function load(): array
    {
        $defaults = [
            'api_key' => '',
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
        ];
    }

    public static function save(array $config): void
    {
        $normalized = [
            'api_key' => (string)($config['api_key'] ?? ''),
        ];

        $content = "<?php\n\nreturn " . var_export($normalized, true) . ";\n";
        $written = @file_put_contents(self::FILE_PATH, $content, LOCK_EX);

        if ($written === false) {
            throw new \RuntimeException('youtube config write failed');
        }
    }

    public static function maskApiKey(string $apiKey): string
    {
        $len = strlen($apiKey);
        if ($len === 0) {
            return '(미설정)';
        }
        if ($len <= 8) {
            return str_repeat('*', $len);
        }

        return substr($apiKey, 0, 4) . '******' . substr($apiKey, -4);
    }
}
