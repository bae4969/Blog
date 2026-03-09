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
