<?php

require_once __DIR__ . '/../vendor/autoload.php';

use Blog\Core\Router;
use Blog\Controllers\HomeController;
use Blog\Controllers\AuthController;
use Blog\Controllers\PostController;

// 에러 리포팅 설정 (개발/운영 분리)
if (getenv('APP_ENV') === 'production') {
	ini_set('display_errors', '0');
	ini_set('log_errors', '1');
} else {
	error_reporting(E_ALL);
	ini_set('display_errors', '1');
}

// 타임존 설정
date_default_timezone_set('Asia/Seoul');

// 라우터 설정
$router = new Router();

// 홈 컨트롤러 라우트
$router->get('/', [HomeController::class, 'index']);
$router->get('/index.php', [HomeController::class, 'index']);
$router->get('/search', [HomeController::class, 'search']);

// 인증 컨트롤러 라우트
$router->get('/login.php', [AuthController::class, 'loginForm']);
$router->post('/login.php', [AuthController::class, 'login']);
$router->get('/logout.php', [AuthController::class, 'logout']);
$router->get('/get/login_verify', [AuthController::class, 'verify']);

// 게시글 컨트롤러 라우트
$router->get('/reader.php', [PostController::class, 'show']);
$router->get('/writer.php', [PostController::class, 'createForm']);
$router->post('/writer.php', [PostController::class, 'create']);
$router->get('/post/edit/:id', [PostController::class, 'editForm', '/post/edit/:id']);
$router->post('/post/update/:id', [PostController::class, 'update', '/post/update/:id']);
$router->post('/post/enable/:id', [PostController::class, 'enable', '/post/enable/:id']);
$router->post('/post/disable/:id', [PostController::class, 'disable', '/post/disable/:id']);

// 요청 처리
$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$uri = $_SERVER['REQUEST_URI'] ?? '/';

$router->dispatch($method, $uri);
