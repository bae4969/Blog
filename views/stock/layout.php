<?php include __DIR__ . '/../home/partials-head.php'; ?>
<body class="stock-page">
    <div id="blog">
        <?php include __DIR__ . '/../home/header.php'; ?>
        
        <section class="stock-page-section">
            <div id="content" class="stock-page-content">
			    <div class="content-alert-container">
                    <?php include __DIR__ . '/../home/partials-flash-messages.php'; ?>
                </div>
                
                <?= $content ?>
            </div>
        </section>
        
        <?php include __DIR__ . '/../home/footer.php'; ?>
    </div>

    <?php include __DIR__ . '/../home/partials-footer-scripts.php'; ?>
</body>
</html>
