<?php include __DIR__ . '/../home/partials-head.php'; ?>
<body class="func-page">
    <div id="blog">
        <?php include __DIR__ . '/../home/header.php'; ?>

        <?php
        $funcCurrentKey = $funcCurrentKey ?? 'youtube-feed';
        $funcMenuItems = $funcMenuItems ?? [];
        ?>

        <section>
            <aside id="side-panel">
                <button class="sidebar-toggle" onclick="toggleSidebar()">메뉴</button>
                <div class="sidebar-content">
                    <ul id="category">
                        <?php foreach ($funcMenuItems as $item): ?>
                            <?php
                            $isActive = $funcCurrentKey === ($item['key'] ?? '');
                            $isSoon = ($item['status'] ?? '') === 'soon';
                            ?>
                            <?php if ($isSoon): ?>
                                <li class="category func-menu-soon"><?= $view->escape((string)($item['label'] ?? '')) ?></li>
                            <?php else: ?>
                                <li class="category <?= $isActive ? 'category-selected' : '' ?>" onclick="location.href='<?= $view->escape((string)($item['href'] ?? '/func')) ?>'"><?= $view->escape((string)($item['label'] ?? '')) ?></li>
                            <?php endif; ?>
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
    <script nonce="<?= $view->getNonce() ?>">
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
            const toggleButton = document.querySelector('.sidebar-toggle');
            if (toggleButton) {
                toggleButton.classList.add('collapsed');
            }
        }
    });
    </script>
</body>
</html>
