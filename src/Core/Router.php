<?php

namespace Blog\Core;

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
        
        // 404 처리
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
}
