<?php

namespace Blog\Core;

use Blog\Database\Database;

class Logger
{
    /**
     * 일반 로그 기록
     * @param string $name   논리적 로그 이름(예: 'auth', 'post')
     * @param string $type   1글자 타입(예: 'I','W','E')
     * @param string $message 메시지
     * @param array $context  추가 컨텍스트 ['function'=>..., 'file'=>..., 'line'=>...]
     */
    public static function log(string $name, string $type, string $message, array $context = []): void
    {
        try {
            $db = Database::getInstance();
            $year = date('Y');
            $table = "Log.Log{$year}"; // 다른 DB 스키마(Log) 내 연도별 테이블

            // 길이 제어 및 기본값
            $name = mb_substr($name, 0, 255, 'UTF-8');
            $type = mb_substr($type, 0, 1, 'UTF-8');
            $message = (string)$message;
            if (mb_strlen($message, 'UTF-8') > 8000) {
                $message = mb_substr($message, 0, 8000, 'UTF-8');
            }

            $func = isset($context['function']) ? mb_substr((string)$context['function'], 0, 255, 'UTF-8') : null;
            $file = isset($context['file']) ? mb_substr((string)$context['file'], 0, 255, 'UTF-8') : null;
            $line = isset($context['line']) ? (int)$context['line'] : null;

            // 기본적으로 현재 호출 스택에서 보완
            if ($func === null || $file === null || $line === null) {
                $bt = debug_backtrace(DEBUG_BACKTRACE_IGNORE_ARGS, 2);
                if (isset($bt[1])) {
                    $func = $func ?? ($bt[1]['function'] ?? null);
                    $file = $file ?? ($bt[1]['file'] ?? null);
                    $line = $line ?? ($bt[1]['line'] ?? null);
                }
            }

            $sql = "INSERT INTO {$table} (log_name, log_type, log_message, log_function, log_file, log_line) VALUES (?, ?, ?, ?, ?, ?)";
            $db->query($sql, [$name, $type, $message, $func, $file, $line]);
        } catch (\Throwable $e) {
            // 로깅 실패 시 애플리케이션 흐름을 방해하지 않음
            error_log('[Logger] write failed: ' . $e->getMessage());
        }
    }

    public static function info(string $name, string $message, array $context = []): void
    {
        self::log($name, 'I', $message, $context);
    }

    public static function warn(string $name, string $message, array $context = []): void
    {
        self::log($name, 'W', $message, $context);
    }

    public static function error(string $name, string $message, array $context = []): void
    {
        self::log($name, 'E', $message, $context);
    }
}
