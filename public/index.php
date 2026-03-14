<?php

require_once __DIR__ . '/../vendor/autoload.php';

use Blog\Core\Router;
use Blog\Controllers\HomeController;
use Blog\Controllers\AuthController;
use Blog\Controllers\PostController;
use Blog\Controllers\StockController;
use Blog\Controllers\AdminController;

// 에러 리포팅 설정 (개발/운영 분리)
ini_set('display_errors', '0');
ini_set('log_errors', '1');
if (getenv('APP_ENV') === 'development') {
	error_reporting(E_ALL);
	ini_set('display_errors', '1');
}

// 타임존 설정
date_default_timezone_set('Asia/Seoul');

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

// 관리자 컨트롤러 라우트
$router->get('/admin', [AdminController::class, 'index']);
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
$router->get('/admin/stocks', [AdminController::class, 'stockSubscriptions']);
$router->post('/admin/stocks/subscriptions', [AdminController::class, 'updateStockSubscriptions']);
$router->get('/admin/wol', [AdminController::class, 'wol']);
$router->post('/admin/wol/execute', [AdminController::class, 'wolExecute']);
$router->post('/admin/wol/create', [AdminController::class, 'wolCreateDevice']);
$router->post('/admin/wol/update', [AdminController::class, 'wolUpdateDevice']);
$router->post('/admin/wol/delete', [AdminController::class, 'wolDeleteDevice']);

// 주식 컨트롤러 라우트
$router->get('/stocks', [StockController::class, 'index']);
$router->get('/stocks/admin', [StockController::class, 'adminRedirect']);
$router->post('/stocks/admin/subscriptions', [StockController::class, 'adminRedirect']);
$router->get('/stocks/view', [StockController::class, 'show']);
$router->get('/stocks/api/candle', [StockController::class, 'apiCandleData']);
$router->get('/stocks/api/executions', [StockController::class, 'apiRecentExecutions']);
$router->get('/stocks/api/search', [StockController::class, 'apiSearch']);

// 요청 처리
$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$uri = $_SERVER['REQUEST_URI'] ?? '/';

$router->dispatch($method, $uri);
