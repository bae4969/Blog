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
    ],
    
    // 캐시 무효화 패턴
    'cache_invalidation' => [
        'user_update' => ['user', 'user_can_write', 'user_posting_limit'],
        'post_create' => ['posts_meta', 'post_count'],
        'post_update' => ['posts_meta', 'post_detail', 'post_count'],
        'post_delete' => ['posts_meta', 'post_detail', 'post_count'],
        'category_update' => ['categories_read', 'categories_write'],
    ],
    
    // 성능 모니터링
    'performance' => [
        'log_slow_queries' => true,
        'slow_query_threshold' => 0.1, // 100ms
        'enable_query_cache' => true,
        'enable_result_cache' => true,
    ]
];
