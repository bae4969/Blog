<div class="admin-content">
    <div class="admin-card">
        <h2>캐시 관리</h2>

        <div class="stat-row cache-stat-row">
            <div class="stat-item"><span class="stat-label">파일 수</span> <span class="stat-value"><?= (int)$fileDetails['file_count'] ?></span></div>
            <span class="stat-sep">·</span>
            <div class="stat-item"><span class="stat-label">전체 크기</span> <span class="stat-value"><?= $view->escape($fileDetails['total_size_formatted']) ?></span></div>
            <span class="stat-sep">·</span>
            <div class="stat-item"><span class="stat-label">활성</span> <span class="stat-value stat-active"><?= (int)$fileDetails['active_count'] ?></span></div>
            <span class="stat-sep">·</span>
            <div class="stat-item"><span class="stat-label">만료</span> <span class="stat-value" style="color:#f44336"><?= (int)$fileDetails['expired_count'] ?></span></div>
            <span class="stat-sep">·</span>
            <div class="stat-item"><span class="stat-label">디렉토리</span> <span class="stat-value"><?= $fileDetails['cache_dir_writable'] ? '쓰기 가능' : '쓰기 불가' ?></span></div>
        </div>

        <hr>

        <h3>캐시 작업</h3>
        <div class="cache-actions">
            <form method="post" action="/admin/cache/clear-expired" class="inline-form">
                <input type="hidden" name="csrf_token" value="<?= $csrfToken ?>">
                <button type="submit" class="btn btn-primary">만료 캐시 정리</button>
                <span class="action-desc">만료된 캐시 파일만 삭제합니다</span>
            </form>
            <form method="post" action="/admin/cache/warmup" class="inline-form">
                <input type="hidden" name="csrf_token" value="<?= $csrfToken ?>">
                <button type="submit" class="btn btn-secondary">캐시 워밍업</button>
                <span class="action-desc">자주 사용하는 데이터를 미리 캐시합니다</span>
            </form>
            <form method="post" action="/admin/cache/clear-pattern" class="inline-form">
                <input type="hidden" name="csrf_token" value="<?= $csrfToken ?>">
                <button type="submit" class="btn btn-danger">캐시 삭제</button>
                <select name="pattern" class="pattern-select" required>
                    <option value="__all__" selected>전체</option>
                    <?php foreach ($cacheTtl as $key => $ttl): ?>
                        <option value="<?= $view->escape($key) ?>"><?= $view->escape($key) ?></option>
                    <?php endforeach; ?>
                </select>
                <span class="action-desc">선택한 패턴의 캐시를 삭제합니다</span>
            </form>
        </div>

        <hr>

        <h3>주식 캔들 일별 캐시</h3>
        <?php if ($stockDayCacheDetails['enabled']): ?>
            <div class="stat-row cache-stat-row">
                <div class="stat-item"><span class="stat-label">종목 수</span> <span class="stat-value"><?= (int)$stockDayCacheDetails['symbol_count'] ?></span></div>
                <span class="stat-sep">·</span>
                <div class="stat-item"><span class="stat-label">파일 수</span> <span class="stat-value"><?= (int)$stockDayCacheDetails['file_count'] ?></span></div>
                <span class="stat-sep">·</span>
                <div class="stat-item"><span class="stat-label">전체 크기</span> <span class="stat-value"><?= $view->escape($stockDayCacheDetails['total_size_formatted']) ?></span></div>
            </div>

            <div class="cache-actions" style="margin-top: 12px;">
                <form method="post" action="/admin/cache/stock-day-cleanup" class="inline-form">
                    <input type="hidden" name="csrf_token" value="<?= $csrfToken ?>">
                    <button type="submit" class="btn btn-primary">오래된 캐시 정리</button>
                    <span class="action-desc">보관 기간 초과 파일을 삭제합니다</span>
                </form>
                <form method="post" action="/admin/cache/stock-day-clear" class="inline-form">
                    <input type="hidden" name="csrf_token" value="<?= $csrfToken ?>">
                    <button type="submit" class="btn btn-danger">전체 삭제</button>
                    <span class="action-desc">주식 캔들 캐시를 모두 삭제합니다</span>
                </form>
            </div>
        <?php else: ?>
            <p class="admin-help">주식 일별 캔들 캐시가 비활성화 상태입니다. <code>config/cache.php</code>에서 활성화할 수 있습니다.</p>
        <?php endif; ?>
    </div>

    <!-- TTL 설정 (읽기 전용) -->
    <div class="admin-card">
        <h3>캐시 TTL 설정</h3>
        <?php
        $ttlGroups = [
            '블로그' => [
                'user' => '사용자 정보',
                'user_can_write' => '쓰기 권한',
                'user_posting_limit' => '게시글 제한',
                'visitor_count' => '방문자 수',
                'categories_read' => '읽기 카테고리',
                'categories_write' => '쓰기 카테고리',
                'posts_meta' => '게시글 목록',
                'post_detail' => '게시글 상세',
                'post_count' => '게시글 수',
            ],
            '주식' => [
                'stock_list_count' => '종목 목록',
                'coin_list_count' => '코인 목록',
                'stock_detail' => '종목 상세',
                'stock_latest_close' => '최신 종가',
                'stock_candle' => '캔들 결과',
                'stock_executions' => '체결 데이터',
                'market_stats' => '시장 통계',
                'top_stocks' => '인기 종목',
                'coin_code_set' => '코인 코드셋',
                'stock_code_exists' => '종목 존재 여부',
                'stock_candle_source' => '캔들 소스',
                'stock_tick_source' => '틱 소스',
                'stock_admin_list' => '관리 종목 목록',
                'stock_admin_registered' => '등록 종목',
                'stock_admin_market_map' => '시장 맵',
                'stock_split_events' => '분할/병합',
            ],
            '보안' => [
                'login_attempts_ip' => 'IP 로그인 시도',
                'login_attempts_user' => '유저 로그인 시도',
                'login_block_ip' => 'IP 로그인 차단',
                'login_block_user' => '유저 로그인 차단',
                'ip_login_block_count' => '차단 누적',
                'ip_404_count' => '404 횟수',
                'blocked_ip' => 'IP 차단',
            ],
        ];
        ?>
        <?php foreach ($ttlGroups as $groupName => $groupKeys): ?>
            <details class="cache-ttl-group">
                <summary><?= $view->escape($groupName) ?> (<?= count($groupKeys) ?>개)</summary>
                <div class="admin-table-wrap">
                    <table class="admin-table cache-table">
                        <thead>
                            <tr><th>캐시 키</th><th>TTL</th><th>설명</th></tr>
                        </thead>
                        <tbody>
                            <?php foreach ($groupKeys as $key => $desc): ?>
                                <?php if (isset($cacheTtl[$key])): ?>
                                    <?php $ttl = $cacheTtl[$key]; ?>
                                    <tr>
                                        <td><code><?= $view->escape($key) ?></code></td>
                                        <td><?= $ttl >= 3600 ? ($ttl / 3600) . '시간' : ($ttl >= 60 ? ($ttl / 60) . '분' : $ttl . '초') ?></td>
                                        <td><?= $view->escape($desc) ?></td>
                                    </tr>
                                <?php endif; ?>
                            <?php endforeach; ?>
                        </tbody>
                    </table>
                </div>
            </details>
        <?php endforeach; ?>
        <div class="admin-help">
            <p>* TTL 설정은 <code>config/cache.php</code> 파일에서 변경할 수 있습니다</p>
        </div>
    </div>

    <!-- 무효화 규칙 -->
    <div class="admin-card">
        <h3>캐시 무효화 규칙</h3>
        <div class="admin-table-wrap">
            <table class="admin-table cache-table">
                <thead>
                    <tr>
                        <th>이벤트</th>
                        <th>삭제되는 캐시</th>
                    </tr>
                </thead>
                <tbody>
                    <?php
                    $eventDescriptions = [
                        'user_update' => '사용자 정보 변경',
                        'post_create' => '게시글 생성',
                        'post_update' => '게시글 수정',
                        'post_delete' => '게시글 삭제',
                        'category_update' => '카테고리 변경',
                    ];
                    ?>
                    <?php foreach ($invalidation as $event => $patterns): ?>
                        <tr>
                            <td><?= $view->escape($eventDescriptions[$event] ?? $event) ?></td>
                            <td>
                                <?php foreach ($patterns as $p): ?>
                                    <span class="cache-tag"><?= $view->escape($p) ?></span>
                                <?php endforeach; ?>
                            </td>
                        </tr>
                    <?php endforeach; ?>
                </tbody>
            </table>
        </div>
    </div>
</div>
