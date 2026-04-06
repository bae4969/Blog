<?php

return [
    'app_name' => 'Developer Blog',
    'app_url' => 'https://dns.com',
    'timezone' => 'Asia/Seoul',
    'session_lifetime' => 3600,
    'csrf_token_name' => 'csrf_token',
    'upload_path' => __DIR__ . '/../public/uploads',
    'max_file_size' => 5 * 1024 * 1024, // 5MB
    'allowed_file_types' => ['jpg', 'jpeg', 'png', 'gif', 'webp'],
    'posts_per_page' => 10,
    'contact_email' => 'bae4969@naver.com',
    'github_url' => 'https://github.com/bae4969',

    // 주식 관리자 저장 제한
    'stock_admin_limits' => [
        'kr_max_subscriptions' => 400,
        'us_max_subscriptions' => 400,
    ],

    // 신뢰할 수 있는 프록시 IP 목록 (이 IP에서만 X-Forwarded-For 헤더를 신뢰)
    'trusted_proxies' => ['127.0.0.1', '::1', '192.168.135.0/24'],

    // IP 자동 차단 설정
    'ip_block' => [
        'enabled' => true,                    // IP 차단 기능 활성화
        'request_window_seconds' => 60,       // 요청 수 집계 윈도우 (초)
        'request_threshold' => 60,            // 윈도우당 최대 요청 수 (위험도: 낮음)
        'login_fail_threshold' => 20,         // 로그인 실패 누적 시 자동 차단 (위험도: 높음)
        'not_found_threshold' => 30,          // 윈도우당 404 횟수 시 자동 차단 (위험도: 중간)
        'block_duration' => [                 // 위험도별 차단 기간 (초, 0=영구)
            'low'    => 300,                  // 낮음: 5분 (과다 요청)
            'medium' => 86400,                // 중간: 24시간 (404 반복)
            'high'   => 604800,               // 높음: 7일 (로그인 실패, 의심 URL)
        ],
        'suspicious_url_patterns' => [        // 즉시 차단할 의심 URL 패턴 (정규식)
            '/wp-(?:admin|login|includes|content)/i',
            '/\.env/i',
            '/\.git\//i',
            '/phpmyadmin/i',
            '/\/etc\/passwd/i',
            '/\.aws\//i',
            '/\.ssh\//i',
            '/\.htaccess/i',
            '/cgi-bin\//i',
            '/\.well-known\/security/i',
            '/actuator\//i',
            '/telescope\//i',
            '/debug\//i',
            '/vendor\/phpunit/i',
            '/eval-stdin\.php/i',
            '/xmlrpc\.php/i',
            '/wp-cron\.php/i',
            '/administrator\//i',
        ],
        'whitelist' => ['127.0.0.1', '::1', '192.168.135.0/24'],  // 차단 제외 IP/CIDR 목록 (예: 192.168.0.0/24)
        'cache_ttl' => 300,                   // 차단 목록 캐시 TTL (초)
        'bot_user_agents' => [                // 즉시 차단할 봇 User-Agent 패턴 (정규식)
            '/curl\b/i',
            '/wget\b/i',
            '/python-requests/i',
            '/python-urllib/i',
            '/scrapy/i',
            '/httpclient/i',
            '/java\//i',
            '/libwww-perl/i',
            '/go-http-client/i',
            '/node-fetch/i',
            '/axios\//i',
            '/headlesschrome/i',
            '/phantomjs/i',
            '/selenium/i',
            '/puppeteer/i',
            '/playwright/i',
        ],
    ],

    // 로그인 레이트 리미팅 설정
    'login_rate_limit' => [
        'window_seconds' => 60,   // 시도 집계 윈도우
        'ip_threshold' => 15,      // 윈도우당 IP 기준 허용 횟수
        'user_threshold' => 5,    // 윈도우당 ID 기준 허용 횟수
        'block_seconds' => 600,    // 임계치 초과 시 차단 시간
        'block_delay_ms_min' => 150, // 차단 응답 시 최소 지연(ms)
        'block_delay_ms_max' => 300, // 차단 응답 시 최대 지연(ms)
        'fail_delay_ms_min' => 200,  // 로그인 실패 시 최소 지연(ms)
        'fail_delay_ms_max' => 500,  // 로그인 실패 시 최대 지연(ms)
    ],
];
