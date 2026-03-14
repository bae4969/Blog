<div class="admin-content">
    <h2>캐시 관리</h2>

    <!-- 캐시 현황 - 상단 요약 카드 -->
    <div class="admin-summary-stats">
        <div class="admin-stat-card">
            <span class="admin-stat-label">파일 수</span>
            <strong class="admin-stat-value"><?= (int)$fileDetails['file_count'] ?></strong>
        </div>
        <div class="admin-stat-card">
            <span class="admin-stat-label">전체 크기</span>
            <strong class="admin-stat-value"><?= $view->escape($fileDetails['total_size_formatted']) ?></strong>
        </div>
        <div class="admin-stat-card">
            <span class="admin-stat-label">활성</span>
            <strong class="admin-stat-value stat-active"><?= (int)$fileDetails['active_count'] ?></strong>
        </div>
        <div class="admin-stat-card">
            <span class="admin-stat-label">만료</span>
            <strong class="admin-stat-value stat-inactive"><?= (int)$fileDetails['expired_count'] ?></strong>
        </div>
        <div class="admin-stat-card">
            <span class="admin-stat-label">디렉토리</span>
            <strong class="admin-stat-value"><?= $fileDetails['cache_dir_writable'] ? '쓰기 가능' : '쓰기 불가' ?></strong>
        </div>
    </div>

    <!-- 캐시 작업 -->
    <div class="admin-card">
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
            <form method="post" action="/admin/cache/clear" class="inline-form"
                  onsubmit="return confirm('모든 캐시를 삭제하시겠습니까? 일시적으로 사이트 응답이 느려질 수 있습니다.');">
                <input type="hidden" name="csrf_token" value="<?= $csrfToken ?>">
                <button type="submit" class="btn btn-danger">전체 캐시 삭제</button>
                <span class="action-desc">모든 캐시를 삭제합니다 (주의)</span>
            </form>
        </div>
    </div>

    <!-- 패턴 삭제 -->
    <div class="admin-card">
        <h3>패턴별 캐시 삭제</h3>
        <form method="post" action="/admin/cache/clear-pattern" class="admin-form">
            <input type="hidden" name="csrf_token" value="<?= $csrfToken ?>">
            <div class="admin-form-row">
                <label>패턴</label>
                <select name="pattern" class="pattern-select">
                    <option value="">-- 패턴 선택 --</option>
                    <?php foreach ($cacheTtl as $key => $ttl): ?>
                        <option value="<?= $view->escape($key) ?>"><?= $view->escape($key) ?></option>
                    <?php endforeach; ?>
                </select>
            </div>
            <div class="admin-form-actions">
                <button type="submit" class="btn btn-primary">선택 패턴 삭제</button>
            </div>
        </form>
    </div>

    <!-- TTL 설정 (읽기 전용) -->
    <div class="admin-card">
        <h3>캐시 TTL 설정</h3>
        <div class="admin-table-wrap">
            <table class="admin-table">
                <thead>
                    <tr>
                        <th>캐시 키</th>
                        <th>TTL</th>
                        <th>설명</th>
                    </tr>
                </thead>
                <tbody>
                    <?php
                    $ttlDescriptions = [
                        'user' => '사용자 정보',
                        'user_can_write' => '사용자 쓰기 권한',
                        'user_posting_limit' => '게시글 제한',
                        'visitor_count' => '방문자 수',
                        'categories_read' => '읽기 카테고리 목록',
                        'categories_write' => '쓰기 카테고리 목록',
                        'posts_meta' => '게시글 목록',
                        'post_detail' => '게시글 상세',
                        'post_count' => '게시글 총 개수',
                    ];
                    ?>
                    <?php foreach ($cacheTtl as $key => $ttl): ?>
                        <tr>
                            <td><code><?= $view->escape($key) ?></code></td>
                            <td><?= $ttl >= 3600 ? ($ttl / 3600) . '시간' : ($ttl / 60) . '분' ?></td>
                            <td><?= $view->escape($ttlDescriptions[$key] ?? '-') ?></td>
                        </tr>
                    <?php endforeach; ?>
                </tbody>
            </table>
        </div>
        <div class="admin-help">
            <p>* TTL 설정은 <code>config/cache.php</code> 파일에서 변경할 수 있습니다</p>
        </div>
    </div>

    <!-- 무효화 규칙 -->
    <div class="admin-card">
        <h3>캐시 무효화 규칙</h3>
        <div class="admin-table-wrap">
            <table class="admin-table">
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
