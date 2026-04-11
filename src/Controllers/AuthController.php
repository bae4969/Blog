<?php

namespace Blog\Controllers;

use Blog\Core\Cache;
use Blog\Core\Logger;
use Blog\Models\BlockedIp;

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

    /**
     * return URL 추출 (GET 'return' 또는 POST 'return_url')
     * 내부 경로만 허용, 기본값 /blog
     */
    private function getReturnUrl(): string
    {
        $url = $_GET['return'] ?? $_POST['return_url'] ?? '';
        // 내부 절대 경로만 허용 (Open Redirect 방어)
        if ($url !== '' && $url[0] === '/' && strpos($url, '//') !== 0) {
            // 프로토콜 상대 URL(\/\evil.com), 줄바꿈/탭 인젝션 방어
            $url = preg_replace('/[\x00-\x1f]/', '', $url);
            $parsed = parse_url($url);
            if ($parsed !== false && !isset($parsed['host']) && !isset($parsed['scheme'])) {
                return $url;
            }
        }
        return '/blog';
    }

    public function loginForm(): void
    {
        if ($this->auth->isLoggedIn()) {
            $this->redirect($this->getReturnUrl());
        }

        // CSRF 토큰을 미리 생성 후, 세션 쓰기를 종료해 동시접속 시 잠금 최소화
        $token = $this->view->csrfToken();
        $this->session->writeClose();

        $returnUrl = $this->getReturnUrl();

        $this->renderLayout('home', 'home/login', [
            'csrfToken' => $token,
            'returnUrl' => $returnUrl,
        ]);
    }

    public function login(): void
    {
        $returnUrl = $this->getReturnUrl();
        $loginRedirect = $returnUrl !== '/blog'
            ? '/login.php?return=' . urlencode($returnUrl)
            : '/login.php';

        if (!$this->isPost()) {
            $this->redirect($loginRedirect);
        }

        if (!$this->validateCsrfToken()) {
            $this->session->setFlash('error', '보안 토큰이 유효하지 않습니다.');
            $this->redirect($loginRedirect);
        }

        // Honeypot 필드 체크 (봇이 자동으로 채우는 숨김 필드)
        $honeypot = $this->getParam('website_url', '');
        if ($honeypot !== '') {
            $ip = $_SERVER['REMOTE_ADDR'] ?? 'unknown';
            Logger::warn('BlogAuth', "honeypot triggered ip={$ip}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            // 봇에게는 성공한 것처럼 보이게 지연 후 리다이렉트
            usleep(random_int(500, 1500) * 1000);
            $this->redirect('/blog');
            return;
        }

        $userId = $this->sanitizeInput($this->getParam('user_id', ''));
        $password = $this->getParam('user_pw', '');

        $errors = $this->validateRequired(['user_id' => $userId, 'user_pw' => $password], ['user_id', 'user_pw']);
        
        if (!empty($errors)) {
            $this->session->setFlash('error', '아이디와 비밀번호를 모두 입력해주세요.');
            $this->redirect($loginRedirect);
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
            $this->redirect($loginRedirect);
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

            // IP 자동 차단: 로그인 실패 누적 카운터
            $this->checkLoginFailAutoBlock($ip, $ipAttempts);
        }
        if ($userAttempts > $userThreshold) {
            $this->cache->set($userBlockKey, 1, $blockSeconds);
        }

        if ($this->auth->login($userId, $password)) {
            // 성공 시 카운터 리셋
            $this->cache->delete($ipAttemptsKey);
            $this->cache->delete($userAttemptsKey);
            Logger::info('BlogAuth', "success ip={$ip} user={$userId}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->redirect($this->getReturnUrl());
        } else {
            // 실패 시 소량 랜덤 지연으로 대량 시도 완화
            usleep(random_int($this->rateLimit['fail_delay_ms_min'], $this->rateLimit['fail_delay_ms_max']) * 1000);
            Logger::error('BlogAuth', "fail ip={$ip} user={$userId}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
            $this->session->setFlash('error', '아이디 또는 비밀번호가 일치하지 않습니다.');
            $this->redirect($loginRedirect);
        }
    }

    public function logoutRedirect(): void
    {
        $this->redirect('/blog');
    }

    public function logout(): void
    {
        if (!$this->isPost() || !$this->validateCsrfToken()) {
            $this->redirect('/blog');
        }

        $returnUrl = $this->getReturnUrl();

        $ip = $_SERVER['REMOTE_ADDR'] ?? 'unknown';
        $user = $this->auth->getCurrentUser();
        $userId = $user['user_id'] ?? 'anonymous';
        Logger::info('BlogAuth', "logout ip={$ip} user={$userId}", ['function'=>__METHOD__, 'file'=>__FILE__, 'line'=>__LINE__]);
        $this->auth->logout();
        $this->session->setFlash('success', '로그아웃되었습니다.');
        $this->redirect($returnUrl);
    }

    public function verify(): void
    {
        if (!$this->requireInternalRequest()) {
            return;
        }

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

    /**
     * 로그인 실패 누적 시 IP 자동 차단 체크
     */
    private function checkLoginFailAutoBlock(string $ip, int $currentAttempts): void
    {
        try {
            $config = require __DIR__ . '/../../config/config.php';
            $settings = $config['ip_block'] ?? [];
            if (empty($settings['enabled'])) {
                return;
            }

            $whitelist = $settings['whitelist'] ?? ['127.0.0.1', '::1'];
            if (in_array($ip, $whitelist, true)) {
                return;
            }

            $threshold = $settings['login_fail_threshold'] ?? 20;

            // 누적 블록 횟수 추적 (레이트리밋 블록이 발동될 때마다 카운트)
            $blockCountKey = Cache::key('ip_login_block_count', $ip);
            $blockCount = (int)($this->cache->get($blockCountKey) ?? 0) + 1;
            $this->cache->set($blockCountKey, $blockCount, 3600); // 1시간 윈도우

            if ($blockCount * ($this->rateLimit['ip_threshold'] ?? 15) >= $threshold) {
                $blockDurations = $settings['block_duration'] ?? ['low' => 300, 'medium' => 86400, 'high' => 604800];
                $duration = $blockDurations['high'] ?? 604800;
                $totalAttempts = $blockCount * ($this->rateLimit['ip_threshold'] ?? 15);
                $model = new BlockedIp();
                $model->blockIp(
                    $ip,
                    "로그인 실패 반복 (누적 약 {$totalAttempts}회)",
                    'auto',
                    $duration > 0 ? $duration : null
                );
                Logger::warn('IpBlock', "auto-blocked ip={$ip} reason=login_fail total_attempts≈{$totalAttempts}");
                $this->cache->delete($blockCountKey);
            }
        } catch (\Throwable $e) {
            error_log('[IpBlock] login fail auto-block check failed: ' . $e->getMessage());
        }
    }
}
