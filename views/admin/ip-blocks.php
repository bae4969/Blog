<div class="admin-content">
    <div class="admin-card collapsible-card collapsed">
        <h2>IP 차단 관리</h2>
        <div class="stat-row">
            <div class="stat-item"><span class="stat-label">전체 차단</span> <span class="stat-value"><?= (int)$stats['total'] ?></span></div>
            <span class="stat-sep">·</span>
            <div class="stat-item"><span class="stat-label">자동</span> <span class="stat-value"><?= (int)$stats['active_auto'] ?></span></div>
            <span class="stat-sep">·</span>
            <div class="stat-item"><span class="stat-label">수동</span> <span class="stat-value"><?= (int)$stats['active_manual'] ?></span></div>
            <span class="stat-sep">·</span>
            <div class="stat-item"><span class="stat-label">만료됨</span> <span class="stat-value" style="color:#999"><?= (int)$stats['expired'] ?></span></div>
        </div>
        <hr>

        <h3 class="collapsible-header">
            수동 IP 차단 추가
            <svg class="collapsible-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
        </h3>
        <div class="collapsible-body">
            <form method="post" action="/admin/ip-blocks/add" class="admin-form">
                <input type="hidden" name="csrf_token" value="<?= $csrfToken ?>">
                <div class="admin-form-grid">
                    <div class="admin-form-field">
                        <label>IP 주소 <span style="color:#e53935">*</span></label>
                        <input type="text" name="ip_address" required maxlength="45" placeholder="예: 192.168.1.100 또는 2001:db8::1">
                    </div>
                    <div class="admin-form-field">
                        <label>사유</label>
                        <input type="text" name="reason" maxlength="500" placeholder="차단 사유 (선택)">
                    </div>
                    <div class="admin-form-field">
                        <label>차단 기간</label>
                        <select name="duration_type" id="ipblock-duration-type" onchange="toggleDurationInput()">
                            <option value="permanent">영구 차단</option>
                            <option value="temporary">시간 제한</option>
                        </select>
                    </div>
                    <div class="admin-form-field" id="ipblock-duration-hours-field" style="visibility:hidden;height:0;overflow:hidden;margin:0;padding:0">
                        <label>차단 시간 (시간)</label>
                        <input type="number" name="duration_hours" min="1" max="8760" value="24" placeholder="시간 단위">
                    </div>
                </div>
                <div class="admin-form-actions">
                    <button type="submit" class="btn btn-primary">차단 추가</button>
                </div>
            </form>
        </div>

        <!-- 차단 목록 -->
        <?php if (empty($blocks)): ?>
            <p class="admin-placeholder">차단된 IP가 없습니다.</p>
        <?php else: ?>
            <div class="admin-table-wrap">
                <table class="admin-table">
                    <thead>
                        <tr>
                            <th>IP 주소</th>
                            <th>사유</th>
                            <th>유형</th>
                            <th>차단 일시</th>
                            <th>만료 일시</th>
                            <th>작업</th>
                        </tr>
                    </thead>
                    <tbody>
                    <?php foreach ($blocks as $block):
                        $isExpired = $block['expires_at'] !== null && strtotime($block['expires_at']) <= time();
                    ?>
                        <tr class="<?= $isExpired ? 'row-disabled' : '' ?>">
                            <td><strong><?= $view->escape($block['ip_address']) ?></strong></td>
                            <td class="text-muted"><?= $view->escape($block['reason'] ?? '-') ?></td>
                            <td>
                                <?php if ($block['block_type'] === 'auto'): ?>
                                    <span class="ip-badge ip-badge-auto">자동</span>
                                <?php else: ?>
                                    <span class="ip-badge ip-badge-manual">수동</span>
                                <?php endif; ?>
                            </td>
                            <td class="text-muted"><?= $view->escape($block['blocked_at']) ?></td>
                            <td class="text-muted">
                                <?php if ($block['expires_at'] === null): ?>
                                    <span style="color:#e53935">영구</span>
                                <?php elseif ($isExpired): ?>
                                    <span style="color:#999">만료됨</span>
                                <?php else: ?>
                                    <?= $view->escape($block['expires_at']) ?>
                                <?php endif; ?>
                            </td>
                            <td class="action-cell">
                                <form method="post" action="/admin/ip-blocks/remove" style="display:inline" onsubmit="return confirm('<?= $view->escape($block['ip_address']) ?> 차단을 해제하시겠습니까?');">
                                    <input type="hidden" name="csrf_token" value="<?= $csrfToken ?>">
                                    <input type="hidden" name="block_id" value="<?= (int)$block['blocked_ip_id'] ?>">
                                    <button type="submit" class="btn btn-sm btn-danger">해제</button>
                                </form>
                            </td>
                        </tr>
                    <?php endforeach; ?>
                    </tbody>
                </table>
            </div>
            <?php if ((int)$stats['expired'] > 0): ?>
            <div style="display:flex;justify-content:space-between;align-items:center;margin-top:12px">
                <span class="text-muted">만료된 차단 <?= (int)$stats['expired'] ?>건이 있습니다.</span>
                <form method="post" action="/admin/ip-blocks/clean" style="margin:0" onsubmit="return confirm('만료된 차단을 모두 정리하시겠습니까?');">
                    <input type="hidden" name="csrf_token" value="<?= $csrfToken ?>">
                    <button type="submit" class="btn btn-sm btn-secondary">만료된 차단 정리</button>
                </form>
            </div>
            <?php endif; ?>
        <?php endif; ?>
    </div>

    <div class="admin-card">
        <h3>자동 차단 설정 현황</h3>
        <div class="admin-help">
            <?php
                $blockDurations = $ipBlockSettings['block_duration'] ?? ['low' => 300, 'medium' => 86400, 'high' => 604800];
                $formatDur = function($s) {
                    $s = (int)$s;
                    if ($s === 0) return '영구';
                    if ($s >= 86400) return ($s / 86400) . '일';
                    if ($s >= 3600) return ($s / 3600) . '시간';
                    if ($s >= 60) return ($s / 60) . '분';
                    return $s . '초';
                };
                $suspiciousCount = count($ipBlockSettings['suspicious_url_patterns'] ?? []);
            ?>
            <table style="width:100%;border-collapse:collapse;font-size:0.92em">
                <thead>
                    <tr style="border-bottom:1px solid var(--border-color)">
                        <th style="text-align:left;padding:6px 8px">규칙</th>
                        <th style="text-align:center;padding:6px 8px">기준</th>
                        <th style="text-align:center;padding:6px 8px">위험도</th>
                        <th style="text-align:center;padding:6px 8px">차단 기간</th>
                    </tr>
                </thead>
                <tbody>
                    <tr style="border-bottom:1px solid var(--border-color)">
                        <td style="padding:6px 8px">분당 과다 요청</td>
                        <td style="text-align:center;padding:6px 8px"><strong><?= (int)($ipBlockSettings['request_threshold'] ?? 120) ?></strong>회/분</td>
                        <td style="text-align:center;padding:6px 8px"><span class="ip-badge" style="background:var(--primary-color)">낮음</span></td>
                        <td style="text-align:center;padding:6px 8px"><?= $formatDur($blockDurations['low'] ?? 300) ?></td>
                    </tr>
                    <tr style="border-bottom:1px solid var(--border-color)">
                        <td style="padding:6px 8px">404 반복 접근</td>
                        <td style="text-align:center;padding:6px 8px"><strong><?= (int)($ipBlockSettings['not_found_threshold'] ?? 30) ?></strong>회/분</td>
                        <td style="text-align:center;padding:6px 8px"><span class="ip-badge ip-badge-auto">중간</span></td>
                        <td style="text-align:center;padding:6px 8px"><?= $formatDur($blockDurations['medium'] ?? 86400) ?></td>
                    </tr>
                    <tr style="border-bottom:1px solid var(--border-color)">
                        <td style="padding:6px 8px">로그인 실패 반복</td>
                        <td style="text-align:center;padding:6px 8px"><strong><?= (int)($ipBlockSettings['login_fail_threshold'] ?? 20) ?></strong>회 누적</td>
                        <td style="text-align:center;padding:6px 8px"><span class="ip-badge" style="background:var(--danger-color)">높음</span></td>
                        <td style="text-align:center;padding:6px 8px"><?= $formatDur($blockDurations['high'] ?? 604800) ?></td>
                    </tr>
                    <tr>
                        <td style="padding:6px 8px">의심 URL 패턴</td>
                        <td style="text-align:center;padding:6px 8px"><strong><?= $suspiciousCount ?></strong>개 패턴</td>
                        <td style="text-align:center;padding:6px 8px"><span class="ip-badge" style="background:var(--danger-color)">높음</span></td>
                        <td style="text-align:center;padding:6px 8px"><?= $formatDur($blockDurations['high'] ?? 604800) ?></td>
                    </tr>
                </tbody>
            </table>
            <p style="margin-top:8px">* 화이트리스트: <code><?= $view->escape(implode(', ', $ipBlockSettings['whitelist'] ?? ['127.0.0.1', '::1'])) ?></code></p>
            <p class="text-muted" style="margin-top:4px">설정 변경은 <code>config/config.php</code>의 <code>ip_block</code> 섹션에서 수정하세요.</p>
        </div>
    </div>
</div>

<script>
function toggleDurationInput() {
    var type = document.getElementById('ipblock-duration-type').value;
    var field = document.getElementById('ipblock-duration-hours-field');
    if (type === 'temporary') {
        field.style.visibility = '';
        field.style.height = '';
        field.style.overflow = '';
        field.style.margin = '';
        field.style.padding = '';
    } else {
        field.style.visibility = 'hidden';
        field.style.height = '0';
        field.style.overflow = 'hidden';
        field.style.margin = '0';
        field.style.padding = '0';
    }
}
</script>
