<?php

namespace Blog\Core;

class View
{
    private $config;

    public function __construct()
    {
        $this->config = require __DIR__ . '/../../config/config.php';
    }

    public function render(string $viewName, array $data = []): void
    {
        $viewPath = __DIR__ . "/../../views/{$viewName}.php";
        
        if (!file_exists($viewPath)) {
            throw new \Exception("View file not found: {$viewPath}");
        }

        // 데이터를 변수로 추출
        extract($data);
        
        // 공통 데이터 추가
        $config = $this->config;
        $session = new Session();
        $auth = new Auth();
        $view = $this; // View 객체를 $view 변수로 전달
        
        // 출력 버퍼 시작
        ob_start();
        include $viewPath;
        $content = ob_get_clean();
        
        echo $content;
    }

    public function renderLayout(string $layout, string $viewName, array $data = []): void
    {
        $layoutPath = __DIR__ . "/../../views/layouts/{$layout}.php";
        
        if (!file_exists($layoutPath)) {
            throw new \Exception("Layout file not found: {$layoutPath}");
        }

        // 데이터를 변수로 추출
        extract($data);
        
        // 공통 데이터 추가
        $config = $this->config;
        $session = new Session();
        $auth = new Auth();
        $view = $this; // View 객체를 $view 변수로 전달
        
        // 뷰 콘텐츠를 변수로 설정
        ob_start();
        $this->render($viewName, $data);
        $content = ob_get_clean();
        
        // 레이아웃 렌더링
        include $layoutPath;
    }

    public function json(array $data): void
    {
        header('Content-Type: application/json');
        echo json_encode($data, JSON_UNESCAPED_UNICODE);
    }

    public function redirect(string $url): void
    {
        header("Location: {$url}");
        exit;
    }

    public function escape(string $string): string
    {
        return htmlspecialchars($string, ENT_QUOTES, 'UTF-8');
    }

    public function csrfToken(): string
    {
        $session = new Session();
        $token = $session->get('csrf_token');
        
        if (!$token) {
            $token = bin2hex(random_bytes(32));
            $session->set('csrf_token', $token);
        }
        
        return $token;
    }

    public function verifyCsrfToken(string $token): bool
    {
        $session = new Session();
        $storedToken = $session->get('csrf_token');
        
        if (!$storedToken || !hash_equals($storedToken, $token)) {
            return false;
        }
        
        return true;
    }
}
