<?php
$currentPath = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';
$topNavLabel = '이동';

if (isset($isAdminPage) && $isAdminPage) {
    $topNavLabel = '관리자';
} elseif (isset($isStockPage) && $isStockPage) {
    $topNavLabel = '주식';
} elseif ($currentPath === '/' || strpos($currentPath, '/blog') === 0 || strpos($currentPath, '/reader.php') === 0 || strpos($currentPath, '/writer.php') === 0 || strpos($currentPath, '/post/') === 0 || strpos($currentPath, '/search') === 0) {
    $topNavLabel = '블로그';
}

if (isset($isAdminPage) && $isAdminPage) {
    $titleLink = '/admin';
} elseif (isset($isStockPage) && $isStockPage) {
    $titleLink = '/stocks';
} else {
    $titleLink = '/blog';
}
?>
<header>
    <div id="topNav">
        <div id="topNavSelected"><?= $view->escape($topNavLabel) ?> ▾</div>
        <div id="topNavDropdown">
            <a href="/blog">블로그</a>
            <a href="/stocks">주식</a>
            <?php if ($auth->isLoggedIn() && $auth->canManageStocks()): ?>
                <a href="/admin">관리자</a>
            <?php endif; ?>
        </div>
    </div>
    <div id="topRight" onclick="loginoutClick()">
        <?= $auth->isLoggedIn() ? '로그아웃' : '로그인' ?>
    </div>
    <?php if ((!isset($isStockPage) || !$isStockPage) && (!isset($isAdminPage) || !$isAdminPage) && $auth->isLoggedIn() && $auth->canWrite()): ?>
        <div id="topWrite" data-button-role="blog-write" onclick="writePostingClick()">글쓰기</div>
    <?php endif; ?>
    <div id="title">
        <img id="blogTitle" onclick="location.href='<?= $titleLink ?>'" src="/res/title.png" alt="Blog Page" />
    </div>
</header>
