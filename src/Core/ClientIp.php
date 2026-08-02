<?php

namespace Blog\Core;

use Blog\Models\BlockedIp;

class ClientIp
{
    /**
     * 클라이언트 IP 추출 (신뢰 프록시 뒤에서만 프록시 헤더 사용)
     *
     * 리버스 프록시 뒤에 있으면 REMOTE_ADDR이 항상 프록시(도커 게이트웨이) IP라 방문자를 구분할 수 없다.
     * trusted_proxies에 해당하는 요청에 한해 프록시가 붙인 헤더로 실제 방문자 IP를 복원한다.
     *
     * X-Forwarded-For는 클라이언트가 앞쪽에 임의 값을 끼워넣을 수 있으므로(위조 → 남의 IP 차단 유발)
     * 프록시가 덧붙이는 맨 뒤 항목만 신뢰한다. 프록시가 항상 덮어쓰는 X-Real-IP가 있으면 그쪽을 우선한다.
     */
    public static function get(): string
    {
        $remoteAddr = $_SERVER['REMOTE_ADDR'] ?? '-';

        $config = require __DIR__ . '/../../config/config.php';
        $trustedProxies = $config['trusted_proxies'] ?? ['127.0.0.1', '::1'];
        if (!BlockedIp::isIpWhitelisted($remoteAddr, $trustedProxies)) {
            return $remoteAddr;
        }

        $forwarded = $_SERVER['HTTP_X_REAL_IP'] ?? null;
        if ($forwarded === null && !empty($_SERVER['HTTP_X_FORWARDED_FOR'])) {
            $parts = explode(',', $_SERVER['HTTP_X_FORWARDED_FOR']);
            $forwarded = end($parts);
        }

        $forwarded = trim((string)$forwarded);
        return filter_var($forwarded, FILTER_VALIDATE_IP) !== false ? $forwarded : $remoteAddr;
    }
}
