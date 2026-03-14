<?php
$totalCategories = count($categories);
$totalPosts = 0;
foreach ($categories as $c) {
    $totalPosts += (int)$c['post_count'];
}
?>
<div class="admin-content">
    <h2>블로그 카테고리 관리</h2>

    <div class="admin-summary-stats">
        <div class="admin-stat-card">
            <span class="admin-stat-label">전체 카테고리</span>
            <strong class="admin-stat-value"><?= $totalCategories ?></strong>
        </div>
        <div class="admin-stat-card">
            <span class="admin-stat-label">전체 게시글</span>
            <strong class="admin-stat-value"><?= number_format($totalPosts) ?></strong>
        </div>
    </div>

    <!-- 카테고리 생성 폼 -->
    <div class="admin-card">
        <h3>새 카테고리 생성</h3>
        <form method="post" action="/admin/categories/create" class="admin-form">
            <input type="hidden" name="csrf_token" value="<?= $csrfToken ?>">
            <div class="admin-form-grid">
                <div class="admin-form-field">
                    <label>이름</label>
                    <input type="text" name="category_name" required maxlength="50" placeholder="카테고리 이름">
                </div>
                <div class="admin-form-field">
                    <label>읽기 권한</label>
                    <select name="category_read_level">
                        <?php foreach ($levelOptions as $lv => $label): ?>
                            <option value="<?= $lv ?>" <?= $lv === 4 ? 'selected' : '' ?>><?= $view->escape($label) ?></option>
                        <?php endforeach; ?>
                    </select>
                </div>
                <div class="admin-form-field">
                    <label>쓰기 권한</label>
                    <select name="category_write_level">
                        <?php foreach ($levelOptions as $lv => $label): ?>
                            <option value="<?= $lv ?>" <?= $lv === 1 ? 'selected' : '' ?>><?= $view->escape($label) ?></option>
                        <?php endforeach; ?>
                    </select>
                </div>
            </div>
            <div class="admin-form-actions">
                <button type="submit" class="btn btn-primary">생성</button>
            </div>
        </form>
    </div>

    <!-- 카테고리 목록 -->
    <div class="admin-card">
        <h3>카테고리 목록</h3>
        <?php if (empty($categories)): ?>
            <p class="admin-placeholder">등록된 카테고리가 없습니다.</p>
        <?php else: ?>
            <div class="admin-table-wrap">
                <table class="admin-table">
                    <thead>
                        <tr>
                            <th>순서</th>
                            <th>이름</th>
                            <th>읽기 권한</th>
                            <th>쓰기 권한</th>
                            <th>게시글</th>
                            <th>작업</th>
                        </tr>
                    </thead>
                    <tbody>
                        <?php foreach ($categories as $i => $cat): ?>
                            <tr>
                                <td class="order-cell">
                                    <div class="order-buttons">
                                        <?php if ($i > 0): ?>
                                            <form method="post" action="/admin/categories/reorder" class="inline-form">
                                                <input type="hidden" name="csrf_token" value="<?= $csrfToken ?>">
                                                <input type="hidden" name="category_index" value="<?= (int)$cat['category_index'] ?>">
                                                <input type="hidden" name="direction" value="up">
                                                <button type="submit" class="btn-arrow" title="위로">▲</button>
                                            </form>
                                        <?php else: ?>
                                            <span class="btn-arrow disabled">▲</span>
                                        <?php endif; ?>
                                        <?php if ($i < count($categories) - 1): ?>
                                            <form method="post" action="/admin/categories/reorder" class="inline-form">
                                                <input type="hidden" name="csrf_token" value="<?= $csrfToken ?>">
                                                <input type="hidden" name="category_index" value="<?= (int)$cat['category_index'] ?>">
                                                <input type="hidden" name="direction" value="down">
                                                <button type="submit" class="btn-arrow" title="아래로">▼</button>
                                            </form>
                                        <?php else: ?>
                                            <span class="btn-arrow disabled">▼</span>
                                        <?php endif; ?>
                                    </div>
                                </td>
                                <td>
                                    <form method="post" action="/admin/categories/update" class="inline-form">
                                        <input type="hidden" name="csrf_token" value="<?= $csrfToken ?>">
                                        <input type="hidden" name="category_index" value="<?= (int)$cat['category_index'] ?>">
                                        <input type="text" name="category_name" value="<?= $view->escape($cat['category_name']) ?>" required maxlength="50" class="inline-input">
                                </td>
                                <td>
                                        <select name="category_read_level" class="inline-select">
                                            <?php foreach ($levelOptions as $lv => $label): ?>
                                                <option value="<?= $lv ?>" <?= (int)$cat['category_read_level'] === $lv ? 'selected' : '' ?>><?= $view->escape($label) ?></option>
                                            <?php endforeach; ?>
                                        </select>
                                </td>
                                <td>
                                        <select name="category_write_level" class="inline-select">
                                            <?php foreach ($levelOptions as $lv => $label): ?>
                                                <option value="<?= $lv ?>" <?= (int)$cat['category_write_level'] === $lv ? 'selected' : '' ?>><?= $view->escape($label) ?></option>
                                            <?php endforeach; ?>
                                        </select>
                                </td>
                                <td><?= (int)$cat['post_count'] ?></td>
                                <td class="action-cell">
                                        <button type="submit" class="btn btn-sm btn-primary">저장</button>
                                    </form>
                                    <form method="post" action="/admin/categories/delete" class="inline-form"
                                          onsubmit="return confirm('카테고리 \'<?= $view->escape($cat['category_name']) ?>\'을(를) 삭제하시겠습니까?<?= (int)$cat['post_count'] > 0 ? ' (게시글 ' . (int)$cat['post_count'] . '개 존재)' : '' ?>');">
                                        <input type="hidden" name="csrf_token" value="<?= $csrfToken ?>">
                                        <input type="hidden" name="category_index" value="<?= (int)$cat['category_index'] ?>">
                                        <button type="submit" class="btn btn-sm btn-danger">삭제</button>
                                    </form>
                                </td>
                            </tr>
                        <?php endforeach; ?>
                    </tbody>
                </table>
            </div>
            <div class="admin-help">
                <p>* 게시글이 존재하는 카테고리는 삭제할 수 없습니다</p>
            </div>
        <?php endif; ?>
    </div>
</div>
