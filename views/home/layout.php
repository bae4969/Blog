<?php $view->emitCspHeader(); ?>
<!DOCTYPE html>
<html lang="ko">
<head>
	<meta charset="utf-8">
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<title><?= $config['app_name'] ?> - Login</title>
	<link rel="stylesheet" href="/css/common.css">
	<link rel="stylesheet" href="/css/blog.css">
	<link rel="stylesheet" href="/css/home.css">
	<?php if (isset($additionalCss)): ?>
		<?php foreach ($additionalCss as $css): ?>
			<link rel="stylesheet" href="<?= $css ?>">
		<?php endforeach; ?>
	<?php endif; ?>
</head>
<body>
	<div id="blog">
		<div class="auth-wrapper">
			<div class="auth-card">
				<div class="auth-alert-container">
					<?php include __DIR__ . '/partials-flash-messages.php'; ?>
				</div>

				<?= $content ?>
			</div>
		</div>
	</div>

	<script nonce="<?= $view->getNonce() ?>" src="/js/blog.js"></script>
	<?php if (isset($additionalJs)): ?>
		<?php foreach ($additionalJs as $js): ?>
			<script nonce="<?= $view->getNonce() ?>" src="<?= $js ?>"></script>
		<?php endforeach; ?>
	<?php endif; ?>
</body>
</html>
