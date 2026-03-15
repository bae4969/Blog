<?php
$queryString = $_SERVER['QUERY_STRING'] ?? '';
$target = '/blog' . ($queryString ? '?' . $queryString : '');

header('Location: ' . $target, true, 302);
exit;
