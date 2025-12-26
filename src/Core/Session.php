<?php

namespace Blog\Core;

class Session
{
    private $config;

    public function __construct()
    {
        $this->config = require __DIR__ . '/../../config/config.php';
        
        if (session_status() === PHP_SESSION_NONE) {
            // 세션 쿠키 설정
            $lifetime = $this->config['session_lifetime'] ?? 3600;
            $isSecure = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off');
            session_set_cookie_params([
                'lifetime' => $lifetime,
                'path' => '/',
                'domain' => '',
                'secure' => $isSecure,
                'httponly' => true,
                'samesite' => 'Lax'
            ]);
            
            session_start();
            
            // 세션 만료 시간 설정
            if (!isset($_SESSION['last_activity'])) {
                $_SESSION['last_activity'] = time();
            }
            
            // 세션이 만료되었는지 확인
            $this->checkSessionExpiry();
        }
    }

    public function set(string $key, $value): void
    {
        $_SESSION[$key] = $value;
        $_SESSION['last_activity'] = time(); // 활동 시간 업데이트
    }

    public function get(string $key, $default = null)
    {
        return $_SESSION[$key] ?? $default;
    }

    public function has(string $key): bool
    {
        return isset($_SESSION[$key]);
    }

    public function remove(string $key): void
    {
        unset($_SESSION[$key]);
    }

    public function destroy(): void
    {
        session_destroy();
    }

    public function regenerate(): void
    {
        session_regenerate_id(true);
    }

    public function setFlash(string $key, $value): void
    {
        $_SESSION['flash'][$key] = $value;
    }

    public function getFlash(string $key, $default = null)
    {
        $value = $_SESSION['flash'][$key] ?? $default;
        unset($_SESSION['flash'][$key]);
        return $value;
    }

    public function hasFlash(string $key): bool
    {
        return isset($_SESSION['flash'][$key]);
    }

    /**
     * 세션 만료 확인
     */
    private function checkSessionExpiry(): void
    {
        if (isset($_SESSION['last_activity'])) {
            $lifetime = $this->config['session_lifetime'] ?? 3600;
            $inactiveTime = time() - $_SESSION['last_activity'];
            
            if ($inactiveTime > $lifetime) {
                // 세션이 만료된 경우 세션 파괴
                $this->destroy();
            }
        }
    }

    /**
     * 세션이 만료되었는지 확인
     */
    public function isExpired(): bool
    {
        if (!isset($_SESSION['last_activity'])) {
            return true;
        }
        
        $lifetime = $this->config['session_lifetime'] ?? 3600;
        $inactiveTime = time() - $_SESSION['last_activity'];
        
        return $inactiveTime > $lifetime;
    }

    /**
     * 세션 활동 시간 업데이트
     */
    public function updateActivity(): void
    {
        $_SESSION['last_activity'] = time();
    }

    /**
     * 세션 쓰기를 종료하여 잠금을 해제
     */
    public function writeClose(): void
    {
        if (session_status() === PHP_SESSION_ACTIVE) {
            session_write_close();
        }
    }
}
