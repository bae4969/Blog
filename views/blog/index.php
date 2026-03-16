<div id="postings">
    <div>
        <?php if (empty($posts)): ?>
            <div class="alert alert-info">
                게시글이 없습니다.
            </div>
        <?php else: ?>
            <div id="left">
                <?php foreach ($posts as $post): ?>
                    <div class="posting <?= $post['posting_state'] != 0 ? 'posting-disabled' : '' ?>" onclick="location.href='/reader.php?posting_index=<?= $post['posting_index'] ?>'">
                        <div class="posting_title">
                            <?= $view->escape($post['posting_title']) ?>
                        </div>
                        <div class="post-meta">
                            <span class="post-category"><?= $view->escape($post['category_name'] ?? '미분류') ?></span>
                            <span class="post-author"><?= $view->escape($post['user_name'] ?? '익명') ?></span>
                            <span class="post-date"><?= date('Y-m-d H:i', strtotime($post['posting_first_post_datetime'])) ?></span>
                            <?php if (isset($post['posting_last_post_datetime']) && $post['posting_last_post_datetime'] !== $post['posting_first_post_datetime']): ?>
                                <span class="post-updated">(수정: <?= date('Y-m-d H:i', strtotime($post['posting_last_post_datetime'])) ?>)</span>
                            <?php endif; ?>
                            <span class="post-read-count">조회: <?= number_format($post['posting_read_cnt'] ?? 0) ?></span>
                        </div>
                        <hr>
                        <div class="posting_content_wrapper <?php echo empty($post['posting_thumbnail']) ? 'no-thumbnail' : ''; ?>">
                            <?php if (!empty($post['posting_thumbnail'])): ?>
                            <div class="posting_thumbnail_container">
                                <img class="posting_thumbnail" src="data:image/webp;base64,<?= $post['posting_thumbnail'] ?>" alt="썸네일">
                            </div>
                            <?php endif; ?>
                            <div class="posting_summary">
                                <?php 
                                    $summary = trim(strip_tags($post['posting_summary'] ?? ''));
                                    $summary = preg_replace('/\s+/u', ' ', $summary);
                                    $originalLength = mb_strlen($summary, 'UTF-8');
                                    $summary = mb_substr($summary, 0, 200, 'UTF-8');
                                    if (!empty($summary)) {
                                        echo $view->escape($summary);
                                        if ($originalLength > 200) {
                                            echo ' ...';
                                        }
                                    } else {
                                        echo '내용이 없습니다.';
                                    }
                                ?>
                            </div>
                        </div>
                    </div>
                <?php endforeach; ?>
            </div>
            <div id="right"></div>
        <?php endif; ?>
    </div>
    
    <?php if ($totalPages > 1): ?>
        <?php
        $blogQuery = function($p) use ($currentCategory, $search) {
            $params = array_filter([
                'page' => $p > 1 ? $p : null,
                'category_index' => $currentCategory ?: null,
                'search_string' => $search ?: null,
            ]);
            return $params ? '?' . http_build_query($params) : '';
        };
        $start = max(1, $currentPage - 4);
        $end = min($totalPages, $currentPage + 4);
        ?>
        <div class="pagination">
            <?php if ($currentPage > 1): ?>
                <a href="<?= $blogQuery($currentPage - 1) ?>" class="page-link">←</a>
            <?php endif; ?>

            <?php if ($start > 1): ?>
                <a href="<?= $blogQuery(1) ?>" class="page-link">1</a>
                <?php if ($start > 2): ?><span class="page-ellipsis">…</span><?php endif; ?>
            <?php endif; ?>

            <?php for ($i = $start; $i <= $end; $i++): ?>
                <?php if ($i === $currentPage): ?>
                    <span class="page-link page-current"><?= $i ?></span>
                <?php else: ?>
                    <a href="<?= $blogQuery($i) ?>" class="page-link"><?= $i ?></a>
                <?php endif; ?>
            <?php endfor; ?>

            <?php if ($end < $totalPages): ?>
                <?php if ($end < $totalPages - 1): ?><span class="page-ellipsis">…</span><?php endif; ?>
                <a href="<?= $blogQuery($totalPages) ?>" class="page-link"><?= $totalPages ?></a>
            <?php endif; ?>

            <?php if ($currentPage < $totalPages): ?>
                <a href="<?= $blogQuery($currentPage + 1) ?>" class="page-link">→</a>
            <?php endif; ?>
        </div>
    <?php endif; ?>
    
    <div id="temp"></div>
</div>

<script>
function loginoutClick() {
    <?php if ($auth->isLoggedIn()): ?>
        if (confirm('로그아웃하시겠습니까?')) {
            document.getElementById('logout-form').submit();
        }
    <?php else: ?>
        location.href = '/login.php';
    <?php endif; ?>
}

function writePostingClick() {
    location.href = '/writer.php<?= $currentCategory ? '?category_index=' . $currentCategory : '' ?>';
}

function searchPostingClick() {
    const categorySelect = document.getElementById('search_category_list');
    const searchText = document.getElementById('search_posting_text').value;
    const categoryIndex = categorySelect.value;
    
    let url = '/blog?';
    if (categoryIndex !== '-1') {
        url += 'category_index=' + categoryIndex + '&';
    }
    if (searchText.trim()) {
        url += 'search_string=' + encodeURIComponent(searchText.trim());
    }
    
    location.href = url;
}
</script>
