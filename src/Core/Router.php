<?php

namespace Blog\Core;

use Blog\Core\Cache;
use Blog\Core\Logger;
use Blog\Models\BlockedIp;

class Router
{
    private $routes = [];

    public function addRoute(string $method, string $path, array $handler): void
    {
        $this->routes[] = [
            'method' => $method,
            'path' => $path,
            'handler' => $handler
        ];
    }

    public function get(string $path, array $handler): void
    {
        $this->addRoute('GET', $path, $handler);
    }

    public function post(string $path, array $handler): void
    {
        $this->addRoute('POST', $path, $handler);
    }

    public function dispatch(string $method, string $uri): void
    {
        $path = parse_url($uri, PHP_URL_PATH);
        
        foreach ($this->routes as $route) {
            if ($route['method'] === $method && $this->matchPath($route['path'], $path)) {
                $this->executeHandler($route['handler'], $path);
                return;
            }
        }
        
        // 404 처리 — IP별 404 카운터 증가 및 자동 차단 체크
        $this->track404();

        http_response_code(404);
        echo "페이지를 찾을 수 없습니다.";
    }

    private function matchPath(string $routePath, string $requestPath): bool
    {
        // 간단한 경로 매칭 (파라미터 추출 포함)
        $routeParts = explode('/', trim($routePath, '/'));
        $requestParts = explode('/', trim($requestPath, '/'));
        
        if (count($routeParts) !== count($requestParts)) {
            return false;
        }
        
        for ($i = 0; $i < count($routeParts); $i++) {
            if (strpos($routeParts[$i], ':') === 0) {
                // 파라미터 부분은 무시
                continue;
            }
            
            if ($routeParts[$i] !== $requestParts[$i]) {
                return false;
            }
        }
        
        return true;
    }

    private function executeHandler(array $handler, string $path): void
    {
        $controllerClass = $handler[0];
        $method = $handler[1];
        
        $controller = new $controllerClass();
        
        // URL 파라미터 추출
        $params = $this->extractParams($path, $handler[2] ?? '');
        
        if (!empty($params)) {
            call_user_func_array([$controller, $method], $params);
        } else {
            $controller->$method();
        }
    }

    private function extractParams(string $path, string $routePath): array
    {
        $params = [];
        $routeParts = explode('/', trim($routePath, '/'));
        $pathParts = explode('/', trim($path, '/'));
        
        for ($i = 0; $i < count($routeParts) && $i < count($pathParts); $i++) {
            if (strpos($routeParts[$i], ':') === 0) {
                $paramName = substr($routeParts[$i], 1);
                $params[] = $pathParts[$i];
            }
        }
        
        return $params;
    }

    /**
     * 404 발생 시 IP별 카운터 증가, 임계치 초과 시 자동 차단
     */
    private function track404(): void
    {
        try {
            $config = require __DIR__ . '/../../config/config.php';
            $settings = $config['ip_block'] ?? [];
            if (empty($settings['enabled'])) {
                return;
            }

            $clientIp = $_SERVER['HTTP_X_FORWARDED_FOR'] ?? $_SERVER['HTTP_X_REAL_IP'] ?? $_SERVER['REMOTE_ADDR'] ?? '';
            if (strpos($clientIp, ',') !== false) {
                $clientIp = trim(explode(',', $clientIp)[0]);
            }
            if ($clientIp === '' || BlockedIp::isIpWhitelisted($clientIp, $settings['whitelist'] ?? ['127.0.0.1', '::1'])) {
                return;
            }

            $cache = Cache::getInstance();
            $window = $settings['request_window_seconds'] ?? 60;
            $threshold = $settings['not_found_threshold'] ?? 30;
            $countKey = Cache::key('ip_404_count', $clientIp);
            $count = (int)($cache->get($countKey) ?? 0) + 1;
            $cache->set($countKey, $count, $window);

            if ($count > $threshold) {
                $blockDurations = $settings['block_duration'] ?? ['low' => 300, 'medium' => 86400, 'high' => 604800];
                $duration = $blockDurations['medium'] ?? 86400;
                $blockedIpModel = new BlockedIp();
                $blockedIpModel->blockIp(
                    $clientIp,
                    "404 반복 접근 ({$count}/{$threshold})",
                    'auto',
                    $duration > 0 ? $duration : null
                );
                Logger::warn('IpBlock', "auto-blocked ip={$clientIp} reason=404_flood count={$count}/{$threshold}");
            }
        } catch (\Throwable $e) {
            error_log('[IpBlock] 404 tracking failed: ' . $e->getMessage());
        }
    }
}
