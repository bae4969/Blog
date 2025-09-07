<?php

namespace Blog\Core;

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
            header('Location: /login.php');
            exit;
        }
    }

    public function requireWritePermission(): void
    {
        $this->requireLogin();

        if (!$this->canWrite()) {
            $this->session->setFlash('error', '글쓰기 횟수가 초과되었습니다.');
            header('Location: /index.php');
            exit;
        }
    }
}
