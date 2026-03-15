<?php include __DIR__ . '/../home/partials-head.php'; ?>
<body>
    <div id="blog">
        <?php include __DIR__ . '/../home/header.php'; ?>
        
        <section>
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
    function writePostingClick() {
        <?php if (isset($userPostingInfo) && $userPostingInfo && $userPostingInfo['is_limited']): ?>
            alert('게시글 작성 제한에 도달했습니다. (<?= $userPostingInfo['current_count'] ?>/<?= $userPostingInfo['limit'] ?>)');
            return;
        <?php endif; ?>
        
        location.href = '/writer.php';
    }
    
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
    });
    </script>
</body>
</html>
