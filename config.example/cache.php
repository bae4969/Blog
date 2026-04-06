<?php

return [
    // 캐시 설정
    'cache' => [
        'enabled' => true,
        'default_ttl' => 3600, // 기본 TTL (초)
        'cache_dir' => __DIR__ . '/../cache/data',
        'memory_cache_enabled' => true,
        'file_cache_enabled' => true,
    ],
    
    // 모델별 캐시 TTL 설정
    'cache_ttl' => [
        'user' => 1800,           // 사용자 정보: 30분
        'user_can_write' => 600,  // 사용자 권한: 10분
        'user_posting_limit' => 300, // 게시글 제한: 5분
        'visitor_count' => 3600,  // 방문자 수: 1시간
        'categories_read' => 3600, // 카테고리 목록: 1시간
        'categories_write' => 3600, // 카테고리 목록: 1시간
        'posts_meta' => 600,      // 게시글 목록: 10분
        'post_detail' => 1800,    // 게시글 상세: 30분
        'post_count' => 600,      // 게시글 총 개수: 10분

        // 주식 관련 캐시 TTL
        'stock_list_count' => 300,       // 주식 목록: 5분
        'coin_list_count' => 300,        // 코인 목록: 5분
        'stock_detail' => 300,           // 주식 상세: 5분
        'stock_latest_close' => 60,      // 최신 종가: 1분
        'stock_candle' => 60,            // 캔들 데이터: 1분
        'stock_executions' => 10,        // 체결 데이터: 10초
        'market_stats' => 600,           // 시장 통계: 10분
        'top_stocks' => 300,             // 인기 종목: 5분
        'coin_code_set' => 1800,         // 코인 코드 목록: 30분
        'stock_code_exists' => 1800,     // 종목 존재 여부: 30분
        'stock_candle_source' => 3600,   // 캔들 테이블 소스: 1시간
        'stock_tick_source' => 3600,     // 틱 테이블 소스: 1시간
        'stock_admin_list' => 120,       // 관리자 종목 목록: 2분
        'stock_admin_registered' => 60,  // 관리자 등록 종목: 1분
        'stock_admin_market_map' => 300,  // 관리자 시장 맵: 5분
        'stock_split_events' => 3600,     // 분할/병합 이벤트: 1시간

        // 인증/보안 관련 캐시 TTL (실제 TTL은 config/config.php의 rate_limit/ip_block 설정으로 동적 지정)
        'login_attempts_ip' => 60,        // IP별 로그인 시도 횟수: 1분 (window_seconds)
        'login_attempts_user' => 60,      // 사용자별 로그인 시도 횟수: 1분 (window_seconds)
        'login_block_ip' => 600,          // IP 로그인 차단: 10분 (block_seconds)
        'login_block_user' => 600,        // 사용자 로그인 차단: 10분 (block_seconds)
        'ip_login_block_count' => 3600,   // IP 로그인 차단 누적 횟수: 1시간
        'ip_404_count' => 60,             // IP 404 발생 횟수: 1분 (request_window_seconds)
        'blocked_ip' => 3600,             // IP 차단 캐시: 1시간 (차단 남은 시간과 비교)
    ],
    
    // 캐시 무효화 패턴
    'cache_invalidation' => [
        'user_update' => ['user', 'user_can_write', 'user_posting_limit'],
        'post_create' => ['posts_meta', 'post_count'],
        'post_update' => ['posts_meta', 'post_detail', 'post_count'],
        'post_delete' => ['posts_meta', 'post_detail', 'post_count'],
        'category_update' => ['categories_read', 'categories_write'],
    ],
    
    // 주식 일별 캔들 캐시 (gzip 파일 기반, 인메모리 우회)
    'stock_day_cache' => [
        'enabled' => true,
        'cache_dir' => __DIR__ . '/../cache/stock',
        'retention_days' => 90,      // 캐시 파일 보관 기간 (일)
        'today_ttl' => 60,           // 오늘 데이터 갱신 주기 (초)
    ],

    // 성능 모니터링
    'performance' => [
        'log_slow_queries' => true,
        'slow_query_threshold' => 0.1, // 100ms
        'enable_query_cache' => true,
        'enable_result_cache' => true,
    ]
];
