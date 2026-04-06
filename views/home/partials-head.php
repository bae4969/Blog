<?php $view->emitCspHeader(); ?>
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="robots" content="noindex, nofollow">
    <title><?= $config['app_name'] ?></title>
    <?php $commonCssVersion = @filemtime(__DIR__ . '/../../public/css/common.css') ?: time(); ?>
    <link rel="stylesheet" href="/css/common.css?v=<?= $commonCssVersion ?>">
    <?php $blogCssVersion = @filemtime(__DIR__ . '/../../public/css/blog.css') ?: time(); ?>
    <link rel="stylesheet" href="/css/blog.css?v=<?= $blogCssVersion ?>">
    <?php if (isset($additionalCss)): ?>
        <?php foreach ($additionalCss as $css): ?>
            <?php
                $cssPublicPath = __DIR__ . '/../../public' . $css;
                $cssVersion = @filemtime($cssPublicPath) ?: $blogCssVersion;
            ?>
            <link rel="stylesheet" href="<?= $css ?>?v=<?= $cssVersion ?>">
        <?php endforeach; ?>
    <?php endif; ?>
</head>
