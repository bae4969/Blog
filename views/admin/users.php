<?php
$totalUsers = count($users);
$activeUsers = 0;
$inactiveUsers = 0;
$searchQuery = $searchQuery ?? '';
foreach ($users as $u) {
    if ((int)$u['user_state'] === 0) $activeUsers++;
    else $inactiveUsers++;
}
?>
<div class="admin-content">
    <div class="admin-card">
        <h2>사용자 관리</h2>
    </div>

    <div class="admin-card">
        <div class="stat-row">
            <div class="stat-item"><span class="stat-label">전체 사용자</span> <span class="stat-value"><?= $totalUsers ?></span></div>
            <span class="stat-sep">·</span>
            <div class="stat-item"><span class="stat-label">활성</span> <span class="stat-value stat-active"><?= $activeUsers ?></span></div>
            <span class="stat-sep">·</span>
            <div class="stat-item"><span class="stat-label">비활성</span> <span class="stat-value" style="color:#f44336"><?= $inactiveUsers ?></span></div>
        </div>
    </div>

    <!-- 사용자 생성 폼 -->
    <div class="admin-card">
        <h3>새 사용자 생성</h3>
        <form method="post" action="/admin/users/create" class="admin-form" id="createUserForm">
            <input type="hidden" name="csrf_token" value="<?= $csrfToken ?>">
            <input type="hidden" name="q" value="<?= $view->escape($searchQuery) ?>">
            <div class="admin-form-grid">
                <div class="admin-form-field">
                    <label>아이디</label>
                    <input type="text" name="user_id" required minlength="2" maxlength="50" placeholder="아이디 입력">
                </div>
                <div class="admin-form-field">
                    <label>비밀번호</label>
                    <input type="password" name="user_pw" id="createPasswordField" required placeholder="비밀번호 입력">
                </div>
                <div class="admin-form-field">
                    <label>권한</label>
                    <select name="user_level">
                        <?php foreach ($levelLabels as $lv => $label): ?>
                            <option value="<?= $lv ?>" <?= $lv === 4 ? 'selected' : '' ?>><?= $view->escape($label) ?></option>
                        <?php endforeach; ?>
                    </select>
                </div>
                <div class="admin-form-field">
                    <label>게시글 제한</label>
                    <input type="number" name="user_posting_limit" value="10" min="0" max="10000">
                </div>
            </div>
            <div class="admin-form-actions">
                <button type="submit" class="btn btn-primary">생성</button>
            </div>
        </form>
    </div>

    <!-- 사용자 목록 -->
    <div class="admin-card">
        <div class="admin-card-header">
            <h3>사용자 목록</h3>
            <form method="get" action="/admin/users" class="admin-search-form">
                <input type="text" name="q" value="<?= $view->escape($searchQuery) ?>" placeholder="아이디 또는 ID로 검색" maxlength="50">
                <button type="submit" class="btn btn-primary">검색</button>
                <?php if ($searchQuery !== ''): ?>
                    <a href="/admin/users" class="btn btn-secondary">초기화</a>
                    <span class="admin-search-result">검색 결과 <?= $totalUsers ?>명</span>
                <?php endif; ?>
            </form>
        </div>
        <div class="admin-table-wrap">
            <table class="admin-table">
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>아이디</th>
                        <th>권한</th>
                        <th>상태</th>
                        <th>게시글</th>
                        <th>제한</th>
                        <th>최근 활동</th>
                        <th>작업</th>
                    </tr>
                </thead>
                <tbody>
                    <?php foreach ($users as $user): ?>
                        <?php $isSelf = ($user['user_index'] == $auth->getCurrentUserIndex()); ?>
                        <tr class="<?= (int)$user['user_state'] !== 0 ? 'row-disabled' : '' ?>">
                            <td><?= (int)$user['user_index'] ?></td>
                            <td>
                                <strong><?= $view->escape($user['user_id']) ?></strong>
                                <?php if ($isSelf): ?><span class="badge-self">나</span><?php endif; ?>
                            </td>
                            <td>
                                <?php if ($isSelf): ?>
                                    <span class="level-badge"><?= $view->escape($levelLabels[(int)$user['user_level']] ?? '알 수 없음') ?></span>
                                <?php else: ?>
                                    <form method="post" action="/admin/users/update" class="inline-form">
                                        <input type="hidden" name="csrf_token" value="<?= $csrfToken ?>">
                                        <input type="hidden" name="q" value="<?= $view->escape($searchQuery) ?>">
                                        <input type="hidden" name="user_index" value="<?= (int)$user['user_index'] ?>">
                                        <input type="hidden" name="action" value="update_level">
                                        <select name="user_level" onchange="this.form.submit()">
                                            <?php foreach ($levelLabels as $lv => $label): ?>
                                                <option value="<?= $lv ?>" <?= (int)$user['user_level'] === $lv ? 'selected' : '' ?>><?= $view->escape($label) ?></option>
                                            <?php endforeach; ?>
                                        </select>
                                    </form>
                                <?php endif; ?>
                            </td>
                            <td>
                                <?php if ($isSelf): ?>
                                    <span class="state-badge state-active">활성</span>
                                <?php else: ?>
                                    <form method="post" action="/admin/users/update" class="inline-form">
                                        <input type="hidden" name="csrf_token" value="<?= $csrfToken ?>">
                                        <input type="hidden" name="q" value="<?= $view->escape($searchQuery) ?>">
                                        <input type="hidden" name="user_index" value="<?= (int)$user['user_index'] ?>">
                                        <input type="hidden" name="action" value="toggle_state">
                                        <button type="submit" class="btn-state <?= (int)$user['user_state'] === 0 ? 'state-active' : 'state-inactive' ?>">
                                            <?= (int)$user['user_state'] === 0 ? '활성' : '비활성' ?>
                                        </button>
                                    </form>
                                <?php endif; ?>
                            </td>
                            <td><?= number_format((int)$user['user_posting_count']) ?></td>
                            <td>
                                <form method="post" action="/admin/users/update" class="inline-form">
                                    <input type="hidden" name="csrf_token" value="<?= $csrfToken ?>">
                                    <input type="hidden" name="q" value="<?= $view->escape($searchQuery) ?>">
                                    <input type="hidden" name="user_index" value="<?= (int)$user['user_index'] ?>">
                                    <input type="hidden" name="action" value="update_posting_limit">
                                    <input type="number" name="user_posting_limit" value="<?= (int)$user['user_posting_limit'] ?>" min="0" max="10000" class="input-small" onchange="this.form.submit()">
                                </form>
                            </td>
                            <td class="text-muted"><?= $user['user_last_action_datetime'] ? date('Y-m-d H:i', strtotime($user['user_last_action_datetime'])) : '-' ?></td>
                            <td>
                                <?php if (!$isSelf): ?>
                                    <button type="button" class="btn btn-sm btn-secondary" onclick="resetPassword(<?= (int)$user['user_index'] ?>, '<?= $view->escape($user['user_id']) ?>')">비밀번호</button>
                                <?php else: ?>
                                    <span class="text-muted">-</span>
                                <?php endif; ?>
                            </td>
                        </tr>
                    <?php endforeach; ?>
                </tbody>
            </table>
        </div>
    </div>
</div>

<!-- 비밀번호 변경 모달 -->
<div id="resetPwModal" style="display:none;position:fixed;inset:0;z-index:9999;align-items:center;justify-content:center;background:rgba(0,0,0,.45);">
    <div style="background:#fff;border-radius:8px;padding:28px 24px;width:320px;max-width:95vw;box-shadow:0 4px 24px rgba(0,0,0,.2);">
        <h3 id="resetPwModalTitle" style="margin:0 0 16px;font-size:1rem;"></h3>
        <div style="position:relative;margin-bottom:16px;">
            <input type="password" id="resetPwInput" placeholder="새 비밀번호 입력"
                style="width:100%;box-sizing:border-box;padding:8px 36px 8px 10px;border:1px solid #ccc;border-radius:4px;font-size:.95rem;">
            <button type="button" id="resetPwToggle" title="비밀번호 표시/숨기기"
                onclick="toggleResetPwVisibility()"
                style="position:absolute;right:6px;top:50%;transform:translateY(-50%);background:none;border:none;cursor:pointer;padding:2px 4px;color:#666;font-size:.85rem;">
                표시
            </button>
        </div>
        <div style="display:flex;gap:8px;justify-content:flex-end;">
            <button type="button" class="btn btn-secondary" onclick="closeResetPwModal()">취소</button>
            <button type="button" class="btn btn-primary" onclick="submitResetPassword()">변경</button>
        </div>
    </div>
</div>

<script src="/js/sha256.js"></script>
<script>
document.getElementById('createUserForm').addEventListener('submit', function(e) {
    e.preventDefault();
    const pwField = document.getElementById('createPasswordField');
    if (pwField.value && !pwField.dataset.hashed) {
        pwField.value = sha256(pwField.value);
        pwField.dataset.hashed = '1';
    }
    this.submit();
});

let _resetPwUserIndex = null;

function resetPassword(userIndex, userId) {
    _resetPwUserIndex = userIndex;
    document.getElementById('resetPwModalTitle').textContent = userId + '의 새 비밀번호를 입력하세요';
    const input = document.getElementById('resetPwInput');
    input.type = 'password';
    input.value = '';
    document.getElementById('resetPwToggle').textContent = '표시';
    const modal = document.getElementById('resetPwModal');
    modal.style.display = 'flex';
    input.focus();
}

function closeResetPwModal() {
    document.getElementById('resetPwModal').style.display = 'none';
    _resetPwUserIndex = null;
}

function toggleResetPwVisibility() {
    const input = document.getElementById('resetPwInput');
    const btn = document.getElementById('resetPwToggle');
    if (input.type === 'password') {
        input.type = 'text';
        btn.textContent = '숨기기';
    } else {
        input.type = 'password';
        btn.textContent = '표시';
    }
}

function submitResetPassword() {
    const newPw = document.getElementById('resetPwInput').value;
    if (!newPw) { alert('비밀번호를 입력하세요.'); return; }

    const form = document.createElement('form');
    form.method = 'post';
    form.action = '/admin/users/update';
    form.innerHTML =
        '<input type="hidden" name="csrf_token" value="<?= $csrfToken ?>">' +
        '<input type="hidden" name="q" value="<?= $view->escape($searchQuery) ?>">' +
        '<input type="hidden" name="user_index" value="' + _resetPwUserIndex + '">' +
        '<input type="hidden" name="action" value="reset_password">' +
        '<input type="hidden" name="new_password" value="' + sha256(newPw) + '">';
    document.body.appendChild(form);
    closeResetPwModal();
    form.submit();
}

document.getElementById('resetPwModal').addEventListener('click', function(e) {
    if (e.target === this) closeResetPwModal();
});

document.getElementById('resetPwInput').addEventListener('keydown', function(e) {
    if (e.key === 'Enter') submitResetPassword();
    if (e.key === 'Escape') closeResetPwModal();
});
</script>
