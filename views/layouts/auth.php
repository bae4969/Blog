<!DOCTYPE html>
<html lang="ko">
<head>
	<meta charset="utf-8">
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<title><?= $config['app_name'] ?> - Login</title>
	<link rel="stylesheet" href="/css/main.css">
	<?php if (isset($additionalCss)): ?>
		<?php foreach ($additionalCss as $css): ?>
			<link rel="stylesheet" href="<?= $css ?>">
		<?php endforeach; ?>
	<?php endif; ?>
</head>
<body>
	<div class="auth-wrapper">
		<div class="auth-card">
			<div class="auth-alert-container">
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
	</div>

	<script src="/js/main.js"></script>
	<?php if (isset($additionalJs)): ?>
		<?php foreach ($additionalJs as $js): ?>
			<script src="<?= $js ?>"></script>
		<?php endforeach; ?>
	<?php endif; ?>
</body>
</html>
