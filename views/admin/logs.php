<?php
$currentSort = $sort ?? 'log_datetime';
$currentOrder = $order ?? 'DESC';

// 쿼리스트링 유지 헬퍼
$filterTypeArr = is_array($filterType) ? $filterType : ($filterType !== '' ? [$filterType] : []);
$filterTableArr = is_array($filterTable) ? $filterTable : ($filterTable !== '' ? [$filterTable] : []);
$buildQuery = function (array $overrides = []) use ($filterName, $filterTableArr, $filterTypeArr, $filterQ, $filterDateFrom, $filterDateTo, $currentSort, $currentOrder, $page) {
    $params = array_filter([
        'name' => $overrides['name'] ?? $filterName,
        'q' => $overrides['q'] ?? $filterQ,
        'date_from' => $overrides['date_from'] ?? $filterDateFrom,
        'date_to' => $overrides['date_to'] ?? $filterDateTo,
        'sort' => $overrides['sort'] ?? $currentSort,
        'order' => $overrides['order'] ?? $currentOrder,
        'page' => $overrides['page'] ?? $page,
    ]);
    // 기본값 제거
    if (($params['sort'] ?? '') === 'log_datetime') unset($params['sort']);
    if (($params['order'] ?? '') === 'DESC') unset($params['order']);
    if (($params['page'] ?? 1) == 1) unset($params['page']);
    $qs = $params ? http_build_query($params) : '';
    $types = $overrides['type'] ?? $filterTypeArr;
    if (!empty($types)) {
        $typeParts = array_map(fn($t) => 'type[]=' . urlencode($t), $types);
        $qs .= ($qs ? '&' : '') . implode('&', $typeParts);
    }
    $tables = $overrides['table'] ?? $filterTableArr;
    if (!empty($tables)) {
        $tableParts = array_map(fn($t) => 'table[]=' . urlencode($t), $tables);
        $qs .= ($qs ? '&' : '') . implode('&', $tableParts);
    }
    return $qs ? '?' . $qs : '';
};

// 정렬 헤더 링크 헬퍼
$sortLink = function (string $column, string $label) use ($currentSort, $currentOrder, $buildQuery) {
    $isActive = ($currentSort === $column);
    $nextOrder = ($isActive && $currentOrder === 'ASC') ? 'DESC' : 'ASC';
    $arrow = '';
    if ($isActive) {
        $arrow = $currentOrder === 'ASC' ? ' ▲' : ' ▼';
    }
    $url = '/admin/logs' . $buildQuery(['sort' => $column, 'order' => $nextOrder, 'page' => 1]);
    $cls = $isActive ? 'log-sort-active' : '';
    return '<a href="' . htmlspecialchars($url, ENT_QUOTES, 'UTF-8') . '" class="log-sort-link ' . $cls . '">' . htmlspecialchars($label, ENT_QUOTES, 'UTF-8') . $arrow . '</a>';
};

$typeLabels = ['I' => '정보', 'W' => '경고', 'E' => '에러', 'N' => '일반'];
$typeCss = ['I' => 'log-type-normal', 'W' => 'log-type-warn', 'E' => 'log-type-error', 'N' => 'log-type-notice'];
?>
<div class="admin-content">
    <div class="admin-card collapsible-card collapsed">
        <h2>로그</h2>

        <div class="stat-row">
            <div class="stat-item"><span class="stat-label">검색 결과</span> <span class="stat-value"><?= number_format($total) ?></span></div>
            <span class="stat-sep">·</span>
            <div class="stat-item"><span class="stat-label">페이지</span> <span class="stat-value"><?= (int)$page ?> / <?= (int)$totalPages ?></span></div>
        </div>
        <hr>

        <h3 class="collapsible-header">
            필터
            <svg class="collapsible-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
        </h3>
        <div class="collapsible-body">
        <form method="get" action="/admin/logs" class="log-filter-form">
            <div class="log-filter-grid">
                <div class="admin-form-field">
                    <label>테이블</label>
                    <div class="checkbox-dropdown">
                        <button type="button" class="checkbox-dropdown-toggle">
                            <?= empty($filterTableArr) ? '전체' : $view->escape(count($filterTableArr) . '개 선택') ?>
                        </button>
                        <div class="checkbox-dropdown-menu">
                            <?php foreach ($logTableNames as $tn): ?>
                                <label class="checkbox-dropdown-item">
                                    <span class="checkbox-dropdown-label"><?= $view->escape($tn) ?></span>
                                    <input type="checkbox" name="table[]" value="<?= $view->escape($tn) ?>" <?= in_array($tn, $filterTableArr) ? 'checked' : '' ?>>
                                </label>
                            <?php endforeach; ?>
                        </div>
                    </div>
                </div>
                <div class="admin-form-field">
                    <label>로그 이름</label>
                    <select name="name">
                        <option value="">전체</option>
                        <?php foreach ($logNames as $ln): ?>
                            <option value="<?= $view->escape($ln) ?>" <?= $filterName === $ln ? 'selected' : '' ?>><?= $view->escape($ln) ?></option>
                        <?php endforeach; ?>
                    </select>
                </div>
                <div class="admin-form-field">
                    <label>타입</label>
                    <div class="checkbox-dropdown">
                        <button type="button" class="checkbox-dropdown-toggle">
                            <?= empty($filterTypeArr) ? '전체' : $view->escape(implode(', ', array_map(fn($t) => $typeLabels[$t] ?? $t, $filterTypeArr))) ?>
                        </button>
                        <div class="checkbox-dropdown-menu">
                            <label class="checkbox-dropdown-item"><span class="checkbox-dropdown-label">일반 (N)</span><input type="checkbox" name="type[]" value="N" <?= in_array('N', $filterTypeArr) ? 'checked' : '' ?>></label>
                            <label class="checkbox-dropdown-item"><span class="checkbox-dropdown-label">정보 (I)</span><input type="checkbox" name="type[]" value="I" <?= in_array('I', $filterTypeArr) ? 'checked' : '' ?>></label>
                            <label class="checkbox-dropdown-item"><span class="checkbox-dropdown-label">경고 (W)</span><input type="checkbox" name="type[]" value="W" <?= in_array('W', $filterTypeArr) ? 'checked' : '' ?>></label>
                            <label class="checkbox-dropdown-item"><span class="checkbox-dropdown-label">에러 (E)</span><input type="checkbox" name="type[]" value="E" <?= in_array('E', $filterTypeArr) ? 'checked' : '' ?>></label>
                        </div>
                    </div>
                </div>
                <div class="admin-form-field">
                    <label>시작일</label>
                    <input type="date" name="date_from" value="<?= $view->escape($filterDateFrom) ?>">
                </div>
                <div class="admin-form-field">
                    <label>종료일</label>
                    <input type="date" name="date_to" value="<?= $view->escape($filterDateTo) ?>">
                </div>
                <div class="admin-form-field">
                    <label>메시지 검색</label>
                    <input type="text" name="q" value="<?= $view->escape($filterQ) ?>" placeholder="메시지 내용 검색" maxlength="200">
                </div>
            </div>
            <?php if ($currentSort !== 'log_datetime'): ?>
                <input type="hidden" name="sort" value="<?= $view->escape($currentSort) ?>">
            <?php endif; ?>
            <?php if ($currentOrder !== 'DESC'): ?>
                <input type="hidden" name="order" value="<?= $view->escape($currentOrder) ?>">
            <?php endif; ?>
            <div class="log-filter-actions">
                <a href="/admin/logs" class="btn btn-secondary">초기화</a>
                <button type="submit" class="btn btn-primary">검색</button>
            </div>
        </form>
        </div>

        <!-- 로그 테이블 -->
        <div class="admin-table-wrap">
            <table class="admin-table log-table">
                <thead>
                    <tr>
                        <th class="log-col-datetime"><?= $sortLink('log_datetime', '시간') ?></th>
                        <th class="log-col-name"><?= $sortLink('log_name', '이름') ?></th>
                        <th class="log-col-type"><?= $sortLink('log_type', '타입') ?></th>
                        <th class="log-col-message">메시지</th>
                        <th class="log-col-location"><?= $sortLink('log_file', '위치') ?></th>
                    </tr>
                </thead>
                <tbody>
                    <?php if (empty($logs)): ?>
                        <tr><td colspan="5" class="log-empty">로그가 없습니다</td></tr>
                    <?php else: ?>
                        <?php foreach ($logs as $log): ?>
                            <?php
                            $logType = $log['log_type'] ?? '';
                            $badgeCls = $typeCss[$logType] ?? 'log-type-info';
                            $badgeLabel = $typeLabels[$logType] ?? $logType;
                            $message = $log['log_message'] ?? '';
                            $isJson = false;
                            $decoded = json_decode($message, true);
                            if (json_last_error() === JSON_ERROR_NONE && is_array($decoded)) {
                                $isJson = true;
                            }
                            $fileLine = $log['log_file'] ?? '';
                            if ($fileLine && $log['log_line']) {
                                $fileLine .= ':' . (int)$log['log_line'];
                            }
                            ?>
                            <tr class="<?= $logType === 'E' ? 'log-row-error' : ($logType === 'W' ? 'log-row-warn' : '') ?>">
                                <td class="log-col-datetime"><?= $view->escape($log['log_datetime'] ?? '') ?></td>
                                <td class="log-col-name"><code><?= $view->escape($log['log_name'] ?? '') ?></code></td>
                                <td class="log-col-type"><span class="log-type-badge <?= $badgeCls ?>"><?= $view->escape($badgeLabel) ?></span></td>
                                <td class="log-col-message">
                                    <?php if ($isJson): ?>
                                        <?php
                                        // 대표 요약 생성
                                        $summary = '';
                                        if (isset($decoded['action'])) {
                                            $summary .= $view->escape($decoded['action']);
                                        }
                                        if (isset($decoded['result'])) {
                                            $resultCls = $decoded['result'] === 'success' ? 'log-result-ok' : 'log-result-fail';
                                            $summary .= ' <span class="' . $resultCls . '">[' . $view->escape($decoded['result']) . ']</span>';
                                        }
                                        if (isset($decoded['actor_user_id'])) {
                                            $summary .= ' <span class="log-actor">' . $view->escape($decoded['actor_user_id']) . '</span>';
                                        }
                                        if (!$summary) {
                                            $keys = array_keys($decoded);
                                            $summary = $view->escape(implode(', ', array_slice($keys, 0, 3)));
                                        }
                                        $detailId = 'log-detail-' . md5($message . ($log['log_datetime'] ?? ''));
                                        ?>
                                        <div class="log-json-summary">
                                            <span class="log-summary-text"><?= $summary ?></span>
                                            <button type="button" class="log-detail-btn" onclick="toggleLogDetail('<?= $detailId ?>')">상세</button>
                                        </div>
                                        <pre class="log-json log-json-hidden" id="<?= $detailId ?>"><?= $view->escape(json_encode($decoded, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES)) ?></pre>
                                    <?php else: ?>
                                        <span class="log-message-text"><?= $view->escape($message) ?></span>
                                    <?php endif; ?>
                                </td>
                                <td class="log-col-location"><code><?php
                                    $location = $log['log_function'] ?? '';
                                    if ($fileLine) {
                                        $location = $location ? $location . ' @ ' . $fileLine : $fileLine;
                                    }
                                    echo $view->escape($location);
                                ?></code></td>
                            </tr>
                        <?php endforeach; ?>
                    <?php endif; ?>
                </tbody>
            </table>
        </div>

        <!-- 페이지네이션 -->
        <?php if ($totalPages > 1): ?>
            <div class="pagination">
                <?php if ($page > 1): ?>
                    <a href="/admin/logs<?= $buildQuery(['page' => $page - 1]) ?>" class="page-link">←</a>
                <?php endif; ?>

                <?php
                $start = max(1, $page - 4);
                $end = min($totalPages, $page + 4);
                ?>
                <?php if ($start > 1): ?>
                    <a href="/admin/logs<?= $buildQuery(['page' => 1]) ?>" class="page-link">1</a>
                    <?php if ($start > 2): ?><span class="page-ellipsis">…</span><?php endif; ?>
                <?php endif; ?>

                <?php for ($i = $start; $i <= $end; $i++): ?>
                    <?php if ($i === $page): ?>
                        <span class="page-link page-current"><?= $i ?></span>
                    <?php else: ?>
                        <a href="/admin/logs<?= $buildQuery(['page' => $i]) ?>" class="page-link"><?= $i ?></a>
                    <?php endif; ?>
                <?php endfor; ?>

                <?php if ($end < $totalPages): ?>
                    <?php if ($end < $totalPages - 1): ?><span class="page-ellipsis">…</span><?php endif; ?>
                    <a href="/admin/logs<?= $buildQuery(['page' => $totalPages]) ?>" class="page-link"><?= $totalPages ?></a>
                <?php endif; ?>

                <?php if ($page < $totalPages): ?>
                    <a href="/admin/logs<?= $buildQuery(['page' => $page + 1]) ?>" class="page-link">→</a>
                <?php endif; ?>
            </div>
        <?php endif; ?>
    </div>
</div>
<script>
function toggleLogDetail(id) {
    var el = document.getElementById(id);
    if (!el) return;
    var btn = el.previousElementSibling.querySelector('.log-detail-btn');
    if (el.classList.contains('log-json-hidden')) {
        el.classList.remove('log-json-hidden');
        if (btn) btn.textContent = '접기';
    } else {
        el.classList.add('log-json-hidden');
        if (btn) btn.textContent = '상세';
    }
}

// Checkbox dropdown
document.querySelectorAll('.checkbox-dropdown-toggle').forEach(function(btn) {
    btn.addEventListener('click', function(e) {
        e.preventDefault();
        var dd = this.closest('.checkbox-dropdown');
        // 다른 열린 드롭다운 닫기
        document.querySelectorAll('.checkbox-dropdown.open').forEach(function(other) {
            if (other !== dd) other.classList.remove('open');
        });
        dd.classList.toggle('open');
    });
});

// 체크박스 변경 시 토글 텍스트 업데이트
document.querySelectorAll('.checkbox-dropdown-menu').forEach(function(menu) {
    menu.addEventListener('change', function() {
        var dd = this.closest('.checkbox-dropdown');
        var toggle = dd.querySelector('.checkbox-dropdown-toggle');
        var checked = Array.from(dd.querySelectorAll('input[type=checkbox]:checked'));
        if (checked.length === 0) {
            toggle.firstChild.textContent = '전체';
        } else {
            var labels = checked.map(function(cb) {
                return cb.parentElement.textContent.trim();
            });
            toggle.firstChild.textContent = labels.join(', ');
        }
    });
});

// 외부 클릭 시 닫기
document.addEventListener('click', function(e) {
    if (!e.target.closest('.checkbox-dropdown')) {
        document.querySelectorAll('.checkbox-dropdown.open').forEach(function(dd) {
            dd.classList.remove('open');
        });
    }
});
</script>
