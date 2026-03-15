<?php $blogJsVersion = @filemtime(__DIR__ . '/../../public/js/blog.js') ?: time(); ?>
<script src="/js/blog.js?v=<?= $blogJsVersion ?>"></script>
<?php if ($auth->isLoggedIn()): ?>
<form id="logout-form" method="POST" action="/logout.php" style="display:none;">
    <input type="hidden" name="csrf_token" value="<?= $view->csrfToken() ?>">
</form>
<?php endif; ?>
<script>
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
</script>
<?php if (isset($additionalJs)): ?>
    <?php foreach ($additionalJs as $js): ?>
        <?php
            $jsPublicPath = __DIR__ . '/../../public' . $js;
            $jsVersion = @filemtime($jsPublicPath) ?: $blogJsVersion;
        ?>
        <script src="<?= $js ?>?v=<?= $jsVersion ?>"></script>
    <?php endforeach; ?>
<?php endif; ?>
