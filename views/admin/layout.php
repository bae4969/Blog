<?php include __DIR__ . '/../home/partials-head.php'; ?>
<body class="admin-page">
    <div id="blog">
        <?php include __DIR__ . '/../home/header.php'; ?>
        
        <section>
            <aside id="side-panel">
                <button class="sidebar-toggle" onclick="toggleSidebar()">메뉴</button>
                <div class="sidebar-content">
                    <div id="profile">
                        관리자: <?= $view->escape($auth->getCurrentUserName()) ?>
                    </div>
                    <ul id="category">
                        <?php
                        $adminMenus = [
                            'logs' => ['label' => '로그', 'url' => '/admin/logs'],
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
            
            <div id="content">
			    <div class="content-alert-container">
                    <?php include __DIR__ . '/../home/partials-flash-messages.php'; ?>
                </div>
                
                <?= $content ?>
            </div>
        </section>
        
        <?php include __DIR__ . '/../home/footer.php'; ?>
    </div>

    <?php include __DIR__ . '/../home/partials-footer-scripts.php'; ?>
    <script>
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
    
    document.addEventListener('DOMContentLoaded', function() {
        if (window.innerWidth <= 1024) {
            const sidebarContent = document.querySelector('.sidebar-content');
            const toggleButton = document.querySelector('.sidebar-toggle');
            
            if (sidebarContent && toggleButton) {
                toggleButton.classList.add('collapsed');
            }
        }

        // 접기/펼치기 카드 토글
        document.querySelectorAll('.collapsible-header').forEach(function(header) {
            header.addEventListener('click', function() {
                this.closest('.collapsible-card').classList.toggle('collapsed');
            });
        });
    });
    </script>
</body>
</html>
