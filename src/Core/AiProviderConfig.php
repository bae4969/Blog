<?php

namespace Blog\Core;

class AiProviderConfig
{
    private const FILE_PATH = __DIR__ . '/../../config/ai.php';

    public const ALLOWED = ['none', 'gemini', 'openai'];
    public const DEFAULT_ACTIVE = 'none';

    public static function load(): array
    {
        $defaults = ['active_provider' => self::DEFAULT_ACTIVE];

        if (!file_exists(self::FILE_PATH)) {
            return $defaults;
        }

        $data = require self::FILE_PATH;
        if (!is_array($data)) {
            return $defaults;
        }

        $active = (string)($data['active_provider'] ?? self::DEFAULT_ACTIVE);
        if (!in_array($active, self::ALLOWED, true)) {
            $active = self::DEFAULT_ACTIVE;
        }

        return ['active_provider' => $active];
    }

    public static function save(array $config): void
    {
        $active = (string)($config['active_provider'] ?? self::DEFAULT_ACTIVE);
        if (!in_array($active, self::ALLOWED, true)) {
            $active = self::DEFAULT_ACTIVE;
        }

        $normalized = ['active_provider' => $active];
        $content = "<?php\n\nreturn " . var_export($normalized, true) . ";\n";
        $written = @file_put_contents(self::FILE_PATH, $content, LOCK_EX);

        if ($written === false) {
            throw new \RuntimeException('ai provider config write failed');
        }
    }

    public static function isValidProvider(string $provider): bool
    {
        return in_array($provider, self::ALLOWED, true);
    }
}
