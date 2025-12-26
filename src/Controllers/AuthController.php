<?php

namespace Blog\Controllers;

use Blog\Core\Cache;
use Blog\Core\Logger;

class AuthController extends BaseController
{
    private $cache;
    private $rateLimit;

    public function __construct()
    {
        parent::__construct();
        $this->cache = Cache::getInstance();

        // 레이트 리미트 설정 로드 (없으면 기본값 사용)
        $config = require __DIR__ . '/../../config/config.php';
        $defaults = [
            'window_seconds' => 60,
            'ip_threshold' => 30,
            'user_threshold' => 10,
            'block_seconds' => 300,
            'block_delay_ms_min' => 150,
            'block_delay_ms_max' => 300,
            'fail_delay_ms_min' => 200,
            'fail_delay_ms_max' => 500,
        ];
        $this->rateLimit = array_merge($defaults, $config['login_rate_limit'] ?? []);
    }

    public function loginForm(): void
    {
        if ($this->auth->isLoggedIn()) {
            $this->redirect('/index.php');
        }

        // CSRF 토큰을 미리 생성 후, 세션 쓰기를 종료해 동시접속 시 잠금 최소화
        $token = $this->view->csrfToken();
        $this->session->writeClose();

        $this->renderLayout('auth', 'auth/login', [
            'csrfToken' => $token
        ]);
    }

    public function login(): void
    {
        if (!$this->isPost()) {
            $this->redirect('/login.php');
        }

        if (!$this->validateCsrfToken()) {
            $this->session->setFlash('error', '보안 토큰이 유효하지 않습니다.');
            $this->redirect('/login.php');
        }

        $userId = $this->sanitizeInput($this->getParam('user_id', ''));
        $password = $this->getParam('user_pw', '');

        $errors = $this->validateRequired(['user_id' => $userId, 'user_pw' => $password], ['user_id', 'user_pw']);
        
        if (!empty($errors)) {
            $this->session->setFlash('error', '아이디와 비밀번호를 모두 입력해주세요.');
            $this->redirect('/login.php');
        }

        // 과도한 로그인 시도 방지 (IP/아이디 기준 단순 레이트 리미팅)
        $ip = $_SERVER['REMOTE_ADDR'] ?? 'unknown';
        $ipAttemptsKey = Cache::key('login_attempts_ip', $ip);
        $ipBlockKey = Cache::key('login_block_ip', $ip);
        $userAttemptsKey = Cache::key('login_attempts_user', strtolower($userId));
        $userBlockKey = Cache::key('login_block_user', strtolower($userId));

        // 차단 상태면 즉시 차단 응답
        if ($this->cache->get($ipBlockKey) || $this->cache->get($userBlockKey)) {
            // 타이밍 공격 완화용 소량 지연
            usleep(random_int($this->rateLimit['block_delay_ms_min'], $this->rateLimit['block_delay_ms_max']) * 1000);
            Logger::warn('BlogAuth', "blocked: too many attempts ip={$ip} user={$userId}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->session->setFlash('error', '로그인 시도가 너무 많습니다. 잠시 후 다시 시도해주세요.');
            $this->redirect('/login.php');
        }

        // 설정된 윈도우에서 카운트 증가
        $window = $this->rateLimit['window_seconds'];
        $ipAttempts = (int)($this->cache->get($ipAttemptsKey) ?? 0) + 1;
        $userAttempts = (int)($this->cache->get($userAttemptsKey) ?? 0) + 1;
        $this->cache->set($ipAttemptsKey, $ipAttempts, $window);
        $this->cache->set($userAttemptsKey, $userAttempts, $window);

        // 임계치 초과 시 차단
        $ipThreshold = $this->rateLimit['ip_threshold'];
        $userThreshold = $this->rateLimit['user_threshold'];
        $blockSeconds = $this->rateLimit['block_seconds'];
        if ($ipAttempts > $ipThreshold) {
            $this->cache->set($ipBlockKey, 1, $blockSeconds);
        }
        if ($userAttempts > $userThreshold) {
            $this->cache->set($userBlockKey, 1, $blockSeconds);
        }

        if ($this->auth->login($userId, $password)) {
            // 성공 시 카운터 리셋
            $this->cache->delete($ipAttemptsKey);
            $this->cache->delete($userAttemptsKey);
            Logger::info('BlogAuth', "success ip={$ip} user={$userId}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->redirect('/index.php');
        } else {
            // 실패 시 소량 랜덤 지연으로 대량 시도 완화
            usleep(random_int($this->rateLimit['fail_delay_ms_min'], $this->rateLimit['fail_delay_ms_max']) * 1000);
            Logger::error('BlogAuth', "fail ip={$ip} user={$userId}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->session->setFlash('error', '아이디 또는 비밀번호가 일치하지 않습니다.');
            $this->redirect('/login.php');
        }
    }

    public function logout(): void
    {
        $ip = $_SERVER['REMOTE_ADDR'] ?? 'unknown';
        $user = $this->auth->getCurrentUser();
        $userId = $user['user_id'] ?? 'anonymous';
        Logger::info('BlogAuth', "logout ip={$ip} user={$userId}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
        $this->auth->logout();
        $this->session->setFlash('success', '로그아웃되었습니다.');
        $this->redirect('/index.php');
    }

    public function verify(): void
    {
        if ($this->auth->isLoggedIn()) {
            $user = $this->auth->getCurrentUser();
            $canWrite = $this->auth->canWrite();
            
            $this->json([
                'state' => 0,
                'can_write' => $canWrite ? 1 : 0,
                'user_name' => $user['user_id'] ?? '',
                'session_expired' => false
            ]);
        } else {
            $this->json([
                'state' => 1,
                'etc' => '로그인이 필요합니다.',
                'session_expired' => $this->session->isExpired()
            ]);
        }
    }
}
