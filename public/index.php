<?php

require_once __DIR__ . '/../vendor/autoload.php';

use Blog\Core\Router;
use Blog\Controllers\HomeController;
use Blog\Controllers\AuthController;
use Blog\Controllers\PostController;
use Blog\Controllers\StockController;
use Blog\Controllers\AdminController;
use Blog\Core\Logger;
use Blog\Core\Cache;
use Blog\Models\BlockedIp;

// 에러 리포팅 설정 (개발/운영 분리)
ini_set('display_errors', '0');
ini_set('log_errors', '1');
if (getenv('APP_ENV') === 'development') {
	error_reporting(E_ALL);
	ini_set('display_errors', '1');
}

// 타임존 설정
date_default_timezone_set('Asia/Seoul');

// HTTPS 강제 리다이렉트 (개발 환경 제외)
if (getenv('APP_ENV') !== 'development') {
    $isHttps = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off')
        || (isset($_SERVER['HTTP_X_FORWARDED_PROTO']) && $_SERVER['HTTP_X_FORWARDED_PROTO'] === 'https');
    if (!$isHttps) {
        $host = $_SERVER['HTTP_HOST'] ?? 'localhost';
        $uri = $_SERVER['REQUEST_URI'] ?? '/';
        header('Location: https://' . $host . $uri, true, 301);
        exit;
    }
}

// 403 차단 응답 헬퍼
function renderBlockedPage(string $message = '접근이 차단되었습니다.'): never
{
    http_response_code(403);
    echo '<!DOCTYPE html><html><head><meta charset="utf-8"><title>403 Forbidden</title>';
    echo '<link rel="stylesheet" href="/css/common.css"></head>';
    echo '<body style="font-family:sans-serif;text-align:center;padding:50px;background:var(--bg-primary);color:var(--text-secondary)">';
    echo '<h1 style="color:var(--text-primary)">403 Forbidden</h1><p>' . htmlspecialchars($message) . '</p></body></html>';
    exit;
}

// 라우터 설정
$router = new Router();

// 홈 컨트롤러 라우트 (블로그는 /blog 아래)
$router->get('/', [HomeController::class, 'redirectToBlog']);
$router->get('/index.php', [HomeController::class, 'redirectToBlog']);
$router->get('/blog', [HomeController::class, 'index']);
$router->get('/blog/search', [HomeController::class, 'search']);
$router->get('/search', [HomeController::class, 'search']);

// 인증 컨트롤러 라우트
$router->get('/login.php', [AuthController::class, 'loginForm']);
$router->post('/login.php', [AuthController::class, 'login']);
$router->get('/logout.php', [AuthController::class, 'logoutRedirect']);
$router->post('/logout.php', [AuthController::class, 'logout']);
$router->get('/get/login_verify', [AuthController::class, 'verify']);

// 게시글 컨트롤러 라우트
$router->get('/reader.php', [PostController::class, 'show']);
$router->get('/writer.php', [PostController::class, 'createForm']);
$router->post('/writer.php', [PostController::class, 'create']);
$router->get('/post/edit/:id', [PostController::class, 'editForm', '/post/edit/:id']);
$router->post('/post/update/:id', [PostController::class, 'update', '/post/update/:id']);
$router->post('/post/enable/:id', [PostController::class, 'enable', '/post/enable/:id']);
$router->post('/post/disable/:id', [PostController::class, 'disable', '/post/disable/:id']);
$router->post('/post/hard-delete/:id', [PostController::class, 'hardDelete', '/post/hard-delete/:id']);

// 관리자 컨트롤러 라우트
$router->get('/admin', [AdminController::class, 'index']);
$router->get('/admin/logs', [AdminController::class, 'logs']);
$router->get('/admin/users', [AdminController::class, 'users']);
$router->post('/admin/users/create', [AdminController::class, 'createUser']);
$router->post('/admin/users/update', [AdminController::class, 'updateUser']);
$router->get('/admin/categories', [AdminController::class, 'categories']);
$router->post('/admin/categories/create', [AdminController::class, 'createCategory']);
$router->post('/admin/categories/update', [AdminController::class, 'updateCategory']);
$router->post('/admin/categories/delete', [AdminController::class, 'deleteCategory']);
$router->post('/admin/categories/reorder', [AdminController::class, 'reorderCategory']);
$router->get('/admin/cache', [AdminController::class, 'cache']);
$router->post('/admin/cache/clear', [AdminController::class, 'clearAllCache']);
$router->post('/admin/cache/clear-expired', [AdminController::class, 'clearExpiredCache']);
$router->post('/admin/cache/clear-pattern', [AdminController::class, 'clearPatternCache']);
$router->post('/admin/cache/warmup', [AdminController::class, 'warmupCache']);
$router->post('/admin/cache/stock-day-cleanup', [AdminController::class, 'cleanupStockDayCache']);
$router->post('/admin/cache/stock-day-clear', [AdminController::class, 'clearStockDayCache']);
$router->get('/admin/stocks', [AdminController::class, 'stockSubscriptions']);
$router->post('/admin/stocks/subscriptions', [AdminController::class, 'updateStockSubscriptions']);
$router->get('/admin/stock-splits', [AdminController::class, 'splitEvents']);
$router->post('/admin/stock-splits/create', [AdminController::class, 'createSplitEvent', '/admin/stock-splits/create']);
$router->post('/admin/stock-splits/delete', [AdminController::class, 'deleteSplitEvent', '/admin/stock-splits/delete']);
$router->get('/admin/wol', [AdminController::class, 'wol']);
$router->post('/admin/wol/execute', [AdminController::class, 'wolExecute']);
$router->post('/admin/wol/create', [AdminController::class, 'wolCreateDevice']);
$router->post('/admin/wol/update', [AdminController::class, 'wolUpdateDevice']);
$router->post('/admin/wol/delete', [AdminController::class, 'wolDeleteDevice']);

// IP 차단 관리 라우트
$router->get('/admin/ip-blocks', [AdminController::class, 'ipBlocks']);
$router->post('/admin/ip-blocks/add', [AdminController::class, 'addIpBlock']);
$router->post('/admin/ip-blocks/remove', [AdminController::class, 'removeIpBlock']);
$router->post('/admin/ip-blocks/clean', [AdminController::class, 'cleanExpiredBlocks']);

// 주식 컨트롤러 라우트
$router->get('/stocks', [StockController::class, 'index']);
$router->get('/stocks/view', [StockController::class, 'show']);
$router->get('/stocks/backtest', [StockController::class, 'backtest']);
$router->get('/stocks/api/candle', [StockController::class, 'apiCandleData']);
$router->get('/stocks/api/executions', [StockController::class, 'apiRecentExecutions']);
$router->get('/stocks/api/search', [StockController::class, 'apiSearch']);

// 요청 처리
$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$uri = $_SERVER['REQUEST_URI'] ?? '/';

// 클라이언트 IP 추출 (신뢰 프록시에서만 X-Forwarded-For 사용)
$remoteAddr = $_SERVER['REMOTE_ADDR'] ?? '-';
$trustedProxies = (require __DIR__ . '/../config/config.php')['trusted_proxies'] ?? ['127.0.0.1', '::1'];
if (in_array($remoteAddr, $trustedProxies, true)) {
    $clientIp = $_SERVER['HTTP_X_FORWARDED_FOR'] ?? $_SERVER['HTTP_X_REAL_IP'] ?? $remoteAddr;
    if (strpos($clientIp, ',') !== false) {
        $clientIp = trim(explode(',', $clientIp)[0]);
    }
    // IP 형식 검증
    if (filter_var($clientIp, FILTER_VALIDATE_IP) === false) {
        $clientIp = $remoteAddr;
    }
} else {
    $clientIp = $remoteAddr;
}

// IP 차단 체크 (라우팅 전 즉시 차단)
$ipBlockConfig = require __DIR__ . '/../config/config.php';
$ipBlockSettings = $ipBlockConfig['ip_block'] ?? [];
if (!empty($ipBlockSettings['enabled']) && !in_array($clientIp, ['127.0.0.1', '::1', '-'], true)) {
    $whitelist = $ipBlockSettings['whitelist'] ?? ['127.0.0.1', '::1'];
    if (!BlockedIp::isIpWhitelisted($clientIp, $whitelist)) {
        try {
            $blockedIpModel = new BlockedIp();
            if ($blockedIpModel->isBlocked($clientIp)) {
                renderBlockedPage('접근이 차단되었습니다.');
            }

            $blockDurations = $ipBlockSettings['block_duration'] ?? ['low' => 300, 'medium' => 86400, 'high' => 604800];

            // 의심 URL 패턴 체크 (위험도: 높음)
            $suspiciousPatterns = $ipBlockSettings['suspicious_url_patterns'] ?? [];
            $requestPath = parse_url($uri, PHP_URL_PATH) ?? '';
            foreach ($suspiciousPatterns as $pattern) {
                if (preg_match($pattern, $requestPath)) {
                    $duration = $blockDurations['high'] ?? 604800;
                    $blockedIpModel->blockIp(
                        $clientIp,
                        "의심 URL 접근: {$requestPath}",
                        'auto',
                        $duration > 0 ? $duration : null
                    );
                    Logger::warn('IpBlock', "auto-blocked ip={$clientIp} reason=suspicious_url path={$requestPath}");
                    renderBlockedPage('비정상적인 접근이 감지되어 차단되었습니다.');
                }
            }

            // 봇 User-Agent 패턴 체크 (위험도: 높음)
            $botPatterns = $ipBlockSettings['bot_user_agents'] ?? [];
            $userAgent = $_SERVER['HTTP_USER_AGENT'] ?? '';
            foreach ($botPatterns as $pattern) {
                if ($userAgent !== '' && preg_match($pattern, $userAgent)) {
                    $duration = $blockDurations['high'] ?? 604800;
                    $blockedIpModel->blockIp(
                        $clientIp,
                        "봇 User-Agent 감지: " . substr($userAgent, 0, 100),
                        'auto',
                        $duration > 0 ? $duration : null
                    );
                    Logger::warn('IpBlock', "auto-blocked ip={$clientIp} reason=bot_ua ua=" . substr($userAgent, 0, 100));
                    renderBlockedPage('비정상적인 접근이 감지되어 차단되었습니다.');
                }
            }

            // 분당 요청 수 카운터 (위험도: 낮음)
            $cache = Cache::getInstance();
            $window = $ipBlockSettings['request_window_seconds'] ?? 60;
            $reqThreshold = $ipBlockSettings['request_threshold'] ?? 120;
            $reqCountKey = Cache::key('ip_req_count', $clientIp);
            $reqCount = (int)($cache->get($reqCountKey) ?? 0) + 1;
            $cache->set($reqCountKey, $reqCount, $window);

            if ($reqCount > $reqThreshold) {
                $duration = $blockDurations['low'] ?? 300;
                $blockedIpModel->blockIp(
                    $clientIp,
                    "분당 요청 수 초과 ({$reqCount}/{$reqThreshold})",
                    'auto',
                    $duration > 0 ? $duration : null
                );
                Logger::warn('IpBlock', "auto-blocked ip={$clientIp} reason=request_flood count={$reqCount}/{$reqThreshold}");
                renderBlockedPage('비정상적인 접근이 감지되어 차단되었습니다.');
            }
        } catch (\Throwable $e) {
            // 차단 체크 실패 시에도 서비스는 계속 제공
            error_log('[IpBlock] check failed: ' . $e->getMessage());
        }
    }
}

// 방문자 접속 로깅 (세션당 1회, 로컬 요청 제외)
if (session_status() === PHP_SESSION_NONE) {
    session_start();
}
if (empty($_SESSION['access_logged'])) {
    if (!in_array($clientIp, ['127.0.0.1', '::1', '-'], true)) {
        $ua = substr(preg_replace('/[\x00-\x1f\x7f]/', '', $_SERVER['HTTP_USER_AGENT'] ?? '-'), 0, 500);
        Logger::log('access', 'N', "{$clientIp} | {$ua}");
    }
    $_SESSION['access_logged'] = true;
}

$router->dispatch($method, $uri);
