<div id="postings">
    <div id="left">
        <?php foreach ($funcFeatures as $feature): ?>
            <div class="posting <?= empty($feature["href"]) ? "posting-disabled" : "" ?>"
                 <?php if (!empty($feature["href"])): ?>
                 onclick="location.href='<?= $view->escape((string)$feature['href']) ?>'"
                 <?php endif; ?>>
                <div class="posting_title"><?= htmlspecialchars($feature["title"], ENT_QUOTES, "UTF-8") ?></div>
                <div class="post-meta">
                    <span class="post-category"><?= htmlspecialchars($feature["category"], ENT_QUOTES, "UTF-8") ?></span>
                    <?php $featureTag = (string)($feature["tag"] ?? ""); ?>
                    <?php if ($featureTag !== ""): ?>
                        <span class="post-author"><?= htmlspecialchars($featureTag, ENT_QUOTES, "UTF-8") ?></span>
                    <?php endif; ?>
                    <span class="post-read-count"><?= empty($feature["href"]) ? "준비 중" : "사용 가능" ?></span>
                </div>
                <hr>
                <div class="posting_content_wrapper no-thumbnail">
                    <div class="posting_summary"><?= htmlspecialchars($feature["summary"], ENT_QUOTES, "UTF-8") ?></div>
                </div>
            </div>
        <?php endforeach; ?>
    </div>
    <div id="right"></div>
</div>
