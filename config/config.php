<?php

return [
    'app_name' => 'Developer Blog',
    'app_url' => 'https://baenoipddnsaddress.ddns.net:40000',
    'timezone' => 'Asia/Seoul',
    'session_lifetime' => 3600,
    'csrf_token_name' => 'csrf_token',
    'upload_path' => __DIR__ . '/../public/uploads',
    'max_file_size' => 5 * 1024 * 1024, // 5MB
    'allowed_file_types' => ['jpg', 'jpeg', 'png', 'gif'],
    'posts_per_page' => 10,
    'contact_email' => 'bae4969@naver.com',
    'github_url' => 'https://github.com/bae4969',

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
