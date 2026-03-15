<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title><?= $config['app_name'] ?></title>
    <?php $mainCssVersion = @filemtime(__DIR__ . '/../../public/css/main.css') ?: time(); ?>
    <link rel="stylesheet" href="/css/main.css?v=<?= $mainCssVersion ?>">
    <?php if (isset($additionalCss)): ?>
        <?php foreach ($additionalCss as $css): ?>
            <?php
                $cssPublicPath = __DIR__ . '/../../public' . $css;
                $cssVersion = @filemtime($cssPublicPath) ?: $mainCssVersion;
            ?>
            <link rel="stylesheet" href="<?= $css ?>?v=<?= $cssVersion ?>">
        <?php endforeach; ?>
    <?php endif; ?>
</head>
<body class="<?= isset($isStockPage) && $isStockPage ? 'stock-page' : '' ?><?= isset($isAdminPage) && $isAdminPage ? ' admin-page' : '' ?>">
    <div id="main">
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
                <?php
                    if (isset($isAdminPage) && $isAdminPage) {
                        $titleLink = '/admin';
                    } elseif (isset($isStockPage) && $isStockPage) {
                        $titleLink = '/stocks';
                    } else {
                        $titleLink = '/blog';
                    }
                ?>
                <img id="mainTitle" onclick="location.href='<?= $titleLink ?>'" src="/res/title.png" alt="Blog Page" />
            </div>
        </header>
        
        <?php
            $sectionClass = '';
            if (isset($isStockPage) && $isStockPage) $sectionClass = 'stock-page-section';
            elseif (isset($isAdminPage) && $isAdminPage) $sectionClass = '';
        ?>
        <section class="<?= $sectionClass ?>">
            <?php if (isset($isAdminPage) && $isAdminPage): ?>
            <!-- 관리자 사이드바 -->
            <aside id="side-panel">
                <button class="sidebar-toggle" onclick="toggleSidebar()">메뉴</button>
                <div class="sidebar-content">
                    <div id="profile">
                        관리자: <?= $view->escape($auth->getCurrentUserName()) ?>
                    </div>
                    <ul id="category">
                        <?php
                        $adminMenus = [
                            'users' => ['label' => '사용자 관리', 'url' => '/admin/users'],
                            'categories' => ['label' => '블로그 카테고리', 'url' => '/admin/categories'],
                            'cache' => ['label' => '캐시 관리', 'url' => '/admin/cache'],
                            'stocks' => ['label' => '주식 구독 관리', 'url' => '/admin/stocks'],
                            'wol' => ['label' => 'WOL', 'url' => '/admin/wol'],
                        ];
                        $currentAdminMenu = $adminCurrentMenu ?? '';
                        ?>
                        <?php foreach ($adminMenus as $menuKey => $menu): ?>
                            <li class="category <?= $currentAdminMenu === $menuKey ? 'category-selected' : '' ?>" onclick="location.href='<?= $menu['url'] ?>'">
                                <?= $view->escape($menu['label']) ?>
                            </li>
                        <?php endforeach; ?>
                    </ul>
                </div>
            </aside>
            <?php elseif (!isset($isStockPage) || !$isStockPage): ?>
            <!-- 블로그 사이드바 -->
            <aside id="side-panel">
                <button class="sidebar-toggle" onclick="toggleSidebar()">메뉴</button>
                <div class="sidebar-content">
                    <div id="profile">
                        <?php if ($auth->isLoggedIn()): ?>
                            안녕하세요<br>
                            <span class="profile-user-id"><?= $view->escape($auth->getCurrentUserName()) ?> 님</span>
                        <?php else: ?>
                            로그인해주세요
                        <?php endif; ?>
                    </div>
                    <div id="user_count">방문자: <?= number_format($visitorCount ?? 0) ?></div>
                    <ul id="category">
                        <li class="category <?= (!isset($currentCategory) || $currentCategory === null) ? 'category-selected' : '' ?>" onclick="selectCategory(-1)">전체</li>
                        <?php if (isset($categories)): ?>
                            <?php foreach ($categories as $category): ?>
                                <li class="category <?= (isset($currentCategory) && $currentCategory == $category['category_index']) ? 'category-selected' : '' ?>" onclick="selectCategory(<?= $category['category_index'] ?>)">
                                    <?= $view->escape($category['category_name']) ?>
                                </li>
                            <?php endforeach; ?>
                        <?php endif; ?>
                    </ul>
                    <div id="search_posting_div">
                    <div class="search-container">
                        <div class="search-input-group">
                            <input id="search_posting_text" type="text" placeholder="검색..." 
                                   onkeyup="if(window.event.keyCode==13){searchPostingClick()}" />
                            <button id="search_posting_btn" onclick="searchPostingClick()" class="search-btn">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <circle cx="11" cy="11" r="8"></circle>
                                    <path d="m21 21-4.35-4.35"></path>
                                </svg>
                            </button>
                        </div>
                        <div class="search-filter-group">
                            <select id="search_category_list">
                                <option value="-1">전체</option>
                                <?php if (isset($categories)): ?>
                                    <?php foreach ($categories as $category): ?>
                                        <option value="<?= $category['category_index'] ?>">
                                            <?= $view->escape($category['category_name']) ?>
                                        </option>
                                    <?php endforeach; ?>
                                <?php endif; ?>
                            </select>
                        </div>
                    </div>
                </div>
                </div>
            </aside>
            <?php endif; ?>
            
            <?php
                $contentClass = '';
                if (isset($isStockPage) && $isStockPage) $contentClass = 'stock-page-content';
            ?>
            <div id="content" class="<?= $contentClass ?>">
			    <div class="content-alert-container">
                    <?php if ($session->hasFlash('success')): ?>
                        <div class="alert alert-success">
                            <?= $view->escape($session->getFlash('success')) ?>
                        </div>
                    <?php endif; ?>
                    
                    <?php if ($session->hasFlash('error')): ?>
                        <div class="alert alert-error">
                            <?= $view->escape($session->getFlash('error')) ?>
                        </div>
                    <?php endif; ?>
                </div>
                
                <?= $content ?>
            </div>
        </section>
        
        <footer>
            <p>
                Contact: <?= $view->escape($config['contact_email']) ?><br>
                Github: <a class="footer" href="<?= $view->escape($config['github_url']) ?>"><?= $view->escape($config['github_url']) ?></a>
            </p>
        </footer>
    </div>

    <?php $mainJsVersion = @filemtime(__DIR__ . '/../../public/js/main.js') ?: time(); ?>
    <script src="/js/main.js?v=<?= $mainJsVersion ?>"></script>
    <?php if ($auth->isLoggedIn()): ?>
    <form id="logout-form" method="POST" action="/logout.php" style="display:none;">
        <input type="hidden" name="csrf_token" value="<?= $view->csrfToken() ?>">
    </form>
    <?php endif; ?>
    <script>
    // 네비게이션 드롭다운 토글
    (function() {
        const topNav = document.getElementById('topNav');
        const topNavSelected = document.getElementById('topNavSelected');
        if (topNav && topNavSelected) {
            topNavSelected.addEventListener('click', function(e) {
                e.stopPropagation();
                topNav.classList.toggle('open');
            });
            document.addEventListener('click', function(e) {
                if (!topNav.contains(e.target)) {
                    topNav.classList.remove('open');
                }
            });
        }
    })();

    function writePostingClick() {
        <?php if (isset($userPostingInfo) && $userPostingInfo && $userPostingInfo['is_limited']): ?>
            alert('게시글 작성 제한에 도달했습니다. (<?= $userPostingInfo['current_count'] ?>/<?= $userPostingInfo['limit'] ?>)');
            return;
        <?php endif; ?>
        
        location.href = '/writer.php';
    }
    
    // 사이드 패널 토글 함수
    function toggleSidebar() {
        const sidebarContent = document.querySelector('.sidebar-content');
        const toggleButton = document.querySelector('.sidebar-toggle');
        
        if (sidebarContent.classList.contains('expanded')) {
            sidebarContent.classList.remove('expanded');
            toggleButton.classList.add('collapsed');
        } else {
            sidebarContent.classList.add('expanded');
            toggleButton.classList.remove('collapsed');
        }
    }
    
    // 모바일에서 페이지 로드 시 사이드 패널 접기
    document.addEventListener('DOMContentLoaded', function() {
        if (window.innerWidth <= 1024) {
            const sidebarContent = document.querySelector('.sidebar-content');
            const toggleButton = document.querySelector('.sidebar-toggle');
            
            if (sidebarContent && toggleButton) {
                // CSS에서 이미 접힌 상태로 설정되어 있으므로 추가 작업 불필요
                toggleButton.classList.add('collapsed');
            }
        }
    });
    </script>
    <?php if (isset($additionalJs)): ?>
        <?php foreach ($additionalJs as $js): ?>
            <?php
                $jsPublicPath = __DIR__ . '/../../public' . $js;
                $jsVersion = @filemtime($jsPublicPath) ?: $mainJsVersion;
            ?>
            <script src="<?= $js ?>?v=<?= $jsVersion ?>"></script>
        <?php endforeach; ?>
    <?php endif; ?>
</body>
</html>
