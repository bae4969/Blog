<?php

namespace Blog\Controllers;

use Blog\Core\Auth;
use Blog\Core\Session;
use Blog\Core\View;

abstract class BaseController
{
    protected $auth;
    protected $session;
    protected $view;

    public function __construct()
    {
        $this->auth = new Auth();
        $this->session = new Session();
        $this->view = new View();
    }

    protected function render(string $view, array $data = []): void
    {
        $this->view->render($view, $data);
    }

    protected function renderLayout(string $layout, string $view, array $data = []): void
    {
        $this->view->renderLayout($layout, $view, $data);
    }

    protected function json(array $data): void
    {
        $this->view->json($data);
    }

    protected function jsonResponse(array $data, int $statusCode = 200): void
    {
        http_response_code($statusCode);
        $this->view->json($data);
    }

    protected function redirect(string $url): void
    {
        $this->view->redirect($url);
    }

    protected function getRequestMethod(): string
    {
        return $_SERVER['REQUEST_METHOD'] ?? 'GET';
    }

    protected function isPost(): bool
    {
        return $this->getRequestMethod() === 'POST';
    }

    protected function isGet(): bool
    {
        return $this->getRequestMethod() === 'GET';
    }

    protected function getPostData(): array
    {
        return $_POST;
    }

    protected function getQueryParams(): array
    {
        return $_GET;
    }

    protected function getParam(string $key, $default = null)
    {
        return $_GET[$key] ?? $_POST[$key] ?? $default;
    }

    protected function validateRequired(array $data, array $required): array
    {
        $errors = [];
        
        foreach ($required as $field) {
            if (empty($data[$field])) {
                $errors[$field] = "{$field}는 필수 입력 항목입니다.";
            }
        }
        
        return $errors;
    }

    protected function sanitizeInput(string $input): string
    {
        return trim(strip_tags($input));
    }

    protected function validateCsrfToken(): bool
    {
        if (!$this->isPost()) {
            return true;
        }

        $token = $this->getParam('csrf_token');
        return $this->view->verifyCsrfToken($token);
    }

    /**
     * 내부 AJAX 요청인지 검증 (X-Requested-With 헤더 + Origin/Referer 체크)
     * 외부에서 URL 직접 접근/크롤링 방지용
     */
    protected function requireInternalRequest(): bool
    {
        $header = $_SERVER['HTTP_X_REQUESTED_WITH'] ?? '';
        if ($header !== 'XMLHttpRequest') {
            $this->jsonResponse(['error' => 'Forbidden'], 403);
            return false;
        }

        // Origin 또는 Referer 헤더로 자사 도메인 요청인지 검증
        $config = require __DIR__ . '/../../config/config.php';
        $appUrl = $config['app_url'] ?? '';
        $appHost = parse_url($appUrl, PHP_URL_HOST) ?: '';

        $origin = $_SERVER['HTTP_ORIGIN'] ?? '';
        $referer = $_SERVER['HTTP_REFERER'] ?? '';

        $originHost = $origin ? (parse_url($origin, PHP_URL_HOST) ?: '') : '';
        $refererHost = $referer ? (parse_url($referer, PHP_URL_HOST) ?: '') : '';

        // Origin 또는 Referer 중 하나라도 자사 도메인이면 허용 (서브도메인 포함)
        if ($appHost !== '') {
            $currentHost = $_SERVER['HTTP_HOST'] ?? '';
            $isValidOrigin = (
                $originHost === $appHost || $refererHost === $appHost ||
                $originHost === $currentHost || $refererHost === $currentHost
            );
            if (!$isValidOrigin) {
                $this->jsonResponse(['error' => 'Forbidden'], 403);
                return false;
            }
        }

        return true;
    }
}
