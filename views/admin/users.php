<div class="admin-content">
    <h2>사용자 관리</h2>

    <!-- 사용자 생성 폼 -->
    <div class="admin-card">
        <h3>새 사용자 생성</h3>
        <form method="post" action="/admin/users/create" class="admin-form" id="createUserForm">
            <input type="hidden" name="csrf_token" value="<?= $csrfToken ?>">
            <div class="admin-form-row">
                <label>아이디</label>
                <input type="text" name="user_id" required minlength="2" maxlength="50" placeholder="아이디 입력">
            </div>
            <div class="admin-form-row">
                <label>비밀번호</label>
                <input type="password" name="user_pw" id="createPasswordField" required placeholder="비밀번호 입력">
            </div>
            <div class="admin-form-row">
                <label>권한</label>
                <select name="user_level">
                    <?php foreach ($levelLabels as $lv => $label): ?>
                        <option value="<?= $lv ?>" <?= $lv === 4 ? 'selected' : '' ?>><?= $lv ?> - <?= $view->escape($label) ?></option>
                    <?php endforeach; ?>
                </select>
            </div>
            <div class="admin-form-row">
                <label>게시글 제한</label>
                <input type="number" name="user_posting_limit" value="10" min="0" max="10000">
            </div>
            <div class="admin-form-actions">
                <button type="submit" class="btn btn-primary">생성</button>
            </div>
        </form>
    </div>

    <!-- 사용자 목록 -->
    <div class="admin-card">
        <h3>사용자 목록 (<?= count($users) ?>명)</h3>
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
                                    <span class="level-badge"><?= (int)$user['user_level'] ?> - <?= $view->escape($levelLabels[(int)$user['user_level']] ?? '알 수 없음') ?></span>
                                <?php else: ?>
                                    <form method="post" action="/admin/users/update" class="inline-form">
                                        <input type="hidden" name="csrf_token" value="<?= $csrfToken ?>">
                                        <input type="hidden" name="user_index" value="<?= (int)$user['user_index'] ?>">
                                        <input type="hidden" name="action" value="update_level">
                                        <select name="user_level" onchange="this.form.submit()">
                                            <?php foreach ($levelLabels as $lv => $label): ?>
                                                <option value="<?= $lv ?>" <?= (int)$user['user_level'] === $lv ? 'selected' : '' ?>><?= $lv ?> - <?= $view->escape($label) ?></option>
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
                                    <input type="hidden" name="user_index" value="<?= (int)$user['user_index'] ?>">
                                    <input type="hidden" name="action" value="update_posting_limit">
                                    <input type="number" name="user_posting_limit" value="<?= (int)$user['user_posting_limit'] ?>" min="0" max="10000" class="input-small" onchange="this.form.submit()">
                                </form>
                            </td>
                            <td class="text-muted"><?= $user['user_last_action_datetime'] ? date('Y-m-d H:i', strtotime($user['user_last_action_datetime'])) : '-' ?></td>
                            <td>
                                <?php if (!$isSelf): ?>
                                    <button type="button" class="btn btn-sm btn-secondary" onclick="resetPassword(<?= (int)$user['user_index'] ?>, '<?= $view->escape($user['user_id']) ?>')">비밀번호 초기화</button>
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

function resetPassword(userIndex, userId) {
    const newPw = prompt(userId + '의 새 비밀번호를 입력하세요:');
    if (!newPw) return;

    const form = document.createElement('form');
    form.method = 'post';
    form.action = '/admin/users/update';
    form.innerHTML =
        '<input type="hidden" name="csrf_token" value="<?= $csrfToken ?>">' +
        '<input type="hidden" name="user_index" value="' + userIndex + '">' +
        '<input type="hidden" name="action" value="reset_password">' +
        '<input type="hidden" name="new_password" value="' + sha256(newPw) + '">';
    document.body.appendChild(form);
    form.submit();
}
</script>
