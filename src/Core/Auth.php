<?php

namespace Blog\Core;

use Blog\Core\Logger;
use Blog\Models\User;

class Auth
{
    private $session;
    private $userModel;

    public function __construct()
    {
        $this->session = new Session();
        $this->userModel = new User();
    }

    public function login(string $userId, string $password): bool
    {
        $user = $this->userModel->authenticate($userId, $password);

        if ($user) {
            if ($user['user_state'] > 0)
                return false;
            $this->session->regenerate();
            $this->session->set('user_index', $user['user_index']);
            $this->session->set('user_id', $user['user_id']);
            $this->session->set('user_level', $user['user_level']);
            $this->session->set('user_state', $user['user_state']);
            return true;
        }

        return false;
    }

    public function logout(): void
    {
        $this->session->destroy();
    }

    public function isLoggedIn(): bool
    {
        // 세션이 만료되었는지 먼저 확인
        if ($this->session->isExpired()) {
            $this->logout();
            return false;
        }
        
        // 세션 활동 시간 업데이트
        $this->session->updateActivity();
        
        return $this->session->has('user_index');
    }

    public function getCurrentUser(): ?array
    {
        if (!$this->isLoggedIn()) {
            return null;
        }

        $userId = $this->session->get('user_id');
        
        // 세션에서 기본 정보를 먼저 확인
        $user = [
            'user_index' => $this->session->get('user_index'),
            'user_id' => $userId,
            'user_level' => $this->session->get('user_level'),
            'user_state' => $this->session->get('user_state')
        ];
        
        // 추가 정보가 필요한 경우에만 DB 조회
        if (empty($user['user_index'])) {
            return $this->userModel->getUserById($userId);
        }
        
        return $user;
    }

    public function getCurrentUserId(): ?string
    {
        return $this->session->get('user_id');
    }

    public function getCurrentUserIndex(): ?int
    {
        return $this->session->get('user_index');
    }

    public function getCurrentUserName(): ?string
    {
        return $this->session->get('user_id');
    }

    public function getCurrentUserLevel(): ?int
    {
        return $this->session->get('user_level') ?? 4;
    }

    public function getCurrentUserState(): ?int
    {
        return $this->session->get('user_state');
    }

    public function canWrite(): bool
    {
        if (!$this->isLoggedIn()) {
            return false;
        }

        $userIndex = $this->getCurrentUserIndex();
        return $this->userModel->canWrite($userIndex);
    }

    public function requireLogin(): void
    {
        if (!$this->isLoggedIn()) {
            $uri = $_SERVER['REQUEST_URI'] ?? '/';
            $ip = $this->getClientIp();
            $this->logAccessOnce('unauth_access', "비인증 접근: {$uri} ({$ip})", $uri);
            header('Location: /login.php');
            exit;
        }
    }

    public function requireWritePermission(): void
    {
        $this->requireLogin();

        if (!$this->canWrite()) {
            $ip = $this->getClientIp();
            $this->logAccessOnce('write_denied', "권한 없는 글쓰기 시도: {$this->getCurrentUserId()} ({$ip})", '/blog/write');
            $this->session->setFlash('error', '글쓰기 횟수가 초과되었습니다.');
            header('Location: /blog');
            exit;
        }
    }

    public function canManageStocks(): bool
    {
        if (!$this->isLoggedIn()) {
            return false;
        }

        return (int)$this->getCurrentUserLevel() <= 1;
    }

    public function requireStockAdminAccess(): void
    {
        $this->requireLogin();

        if (!$this->canManageStocks()) {
            $uri = $_SERVER['REQUEST_URI'] ?? '/';
            $ip = $this->getClientIp();
            $this->logAccessOnce('stock_admin_denied', "관리자 페이지 무단 접근: {$uri} {$this->getCurrentUserId()} ({$ip})", $uri);
            $this->session->setFlash('error', '주식 관리자 페이지는 관리자만 접근할 수 있습니다.');
            header('Location: /stocks');
            exit;
        }
    }

    private function logAccessOnce(string $event, string $message, string $uri = ''): void
    {
        $userId = (string)($this->getCurrentUserId() ?? 'guest');
        $normalizedUri = strtok($uri ?: ($_SERVER['REQUEST_URI'] ?? '/'), '?') ?: '/';
        $sessionKey = 'access_log_once_' . sha1($event . '|' . $normalizedUri . '|' . $userId);

        if ($this->session->has($sessionKey)) {
            return;
        }

        Logger::warn('access', $message);
        $this->session->set($sessionKey, true);
    }

    private function getClientIp(): string
    {
        $remoteAddr = $_SERVER['REMOTE_ADDR'] ?? '-';
        $config = require __DIR__ . '/../../config/config.php';
        $trustedProxies = $config['trusted_proxies'] ?? ['127.0.0.1', '::1'];

        if (in_array($remoteAddr, $trustedProxies, true)) {
            $ip = $_SERVER['HTTP_X_FORWARDED_FOR'] ?? $_SERVER['HTTP_X_REAL_IP'] ?? $remoteAddr;
            if (strpos($ip, ',') !== false) {
                $ip = trim(explode(',', $ip)[0]);
            }
            if (filter_var($ip, FILTER_VALIDATE_IP) !== false) {
                return $ip;
            }
        }

        return $remoteAddr;
    }
}
