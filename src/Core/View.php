<?php

namespace Blog\Core;

class View
{
    private $config;
    private static ?string $cspNonce = null;

    public function __construct()
    {
        $this->config = require __DIR__ . '/../../config/config.php';
    }

    /**
     * CSP nonce 반환 (요청당 1회 생성, 동일 요청 내 모든 View 인스턴스에서 공유)
     */
    public function getNonce(): string
    {
        if (self::$cspNonce === null) {
            self::$cspNonce = base64_encode(random_bytes(16));
        }
        return self::$cspNonce;
    }

    /**
     * CSP 헤더 전송 (출력 전 1회만 호출)
     */
    public function emitCspHeader(): void
    {
        if (headers_sent()) {
            return;
        }
        $nonce = $this->getNonce();
        $csp = "default-src 'self'; "
             . "script-src 'self' 'nonce-{$nonce}'; "
             . "script-src-attr 'unsafe-inline'; "
             . "style-src 'self' 'unsafe-inline'; "
             . "img-src 'self' data: https:; "
             . "font-src 'self' data:;";
        header("Content-Security-Policy: {$csp}");
    }

    public function render(string $viewName, array $data = []): void
    {
        $viewPath = __DIR__ . "/../../views/{$viewName}.php";
        
        if (!file_exists($viewPath)) {
            throw new \Exception("View file not found: {$viewPath}");
        }

        // 데이터를 변수로 추출 (기존 변수 덮어쓰기 방지)
        extract($data, EXTR_SKIP);
        
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
        $layoutPath = __DIR__ . "/../../views/{$layout}/layout.php";
        
        if (!file_exists($layoutPath)) {
            throw new \Exception("Layout file not found: {$layoutPath}");
        }

        // 데이터를 변수로 추출 (기존 변수 덮어쓰기 방지)
        extract($data, EXTR_SKIP);
        
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
        // 내부 경로만 허용 (Open Redirect 방어)
        if ($url === '' || $url[0] !== '/' || strpos($url, '//') === 0) {
            $url = '/';
        }
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
        
        // 토큰 소비 후 재생성 (replay attack 방어)
        $newToken = bin2hex(random_bytes(32));
        $session->set('csrf_token', $newToken);
        
        return true;
    }
}
