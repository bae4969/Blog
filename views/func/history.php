<?php
/** @var array $historyItems */
$historyItems = $historyItems ?? [];
?>

<div class="post-wrapper">
    <article class="post">
        <header class="post-header">
            <h1 class="post-title">분석 이력</h1>
            <div class="post-meta">
                <span class="post-category">이 브라우저 기준</span>
            </div>
        </header>

        <div class="post-content">
            <?php if (empty($historyItems)): ?>
                <p>아직 분석 기록이 없습니다.</p>
                <p><a href="/func/youtube-feed">YouTube 알고리즘 분석 시작하기</a></p>
            <?php else: ?>
                <ul class="func-history-list">
                    <?php foreach ($historyItems as $item): ?>
                        <?php
                        $href = !empty($item['share_token']) ? '/a/' . $view->escape($item['share_token']) : '/func';
                        $dateStr = '';
                        if (!empty($item['created_at'])) {
                            try {
                                $dt = new DateTimeImmutable($item['created_at']);
                                $dateStr = $dt->format('Y.m.d H:i');
                            } catch (\Throwable $e) {
                                $dateStr = $view->escape($item['created_at']);
                            }
                        }
                        ?>
                        <li class="func-history-item">
                            <a href="<?= $href ?>" class="func-history-link">
                                <span class="func-history-type"><?= $view->escape((string)$item['result_type']) ?></span>
                                <?php if (!empty($item['mbti'])): ?>
                                    <span class="func-history-mbti"><?= $view->escape((string)$item['mbti']) ?></span>
                                <?php endif; ?>
                                <span class="func-history-meta"><?= (int)$item['video_count'] ?>개 영상</span>
                                <?php if ($dateStr): ?>
                                    <span class="func-history-date"><?= $dateStr ?></span>
                                <?php endif; ?>
                            </a>
                        </li>
                    <?php endforeach; ?>
                </ul>
            <?php endif; ?>
        </div>
    </article>

    <div class="post-actions">
        <a href="/func/youtube-feed" class="btn btn-primary">새 분석</a>
    </div>
</div>
