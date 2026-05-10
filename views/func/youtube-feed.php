<div class="post-wrapper">
    <article class="post">
        <header class="post-header">
            <h1 class="post-title">Youtube 알고리즘 분석</h1>
            <div class="post-meta">
                <span class="post-category">PC 브라우저 전용</span>
            </div>
        </header>

        <div class="post-content">
            <?php if (empty($youtubeConfigured)): ?>
                <p>관리자에서 YouTube API 설정을 완료해야 분석을 사용할 수 있습니다.</p>
            <?php else: ?>
                <h2>북마클릿 등록 (최초 1회)</h2>
                <div class="func-setup-methods">
                    <div class="func-setup-method">
                        <strong>방법 1: 드래그</strong>
                        <p>아래 버튼을 즐겨찾기 바에 끌어다 놓으세요.</p>
                        <a class="btn btn-primary" href="<?= htmlspecialchars($bookmarkletJs, ENT_QUOTES, 'UTF-8') ?>">피드 분석하기</a>
                    </div>

                    <div class="func-setup-method">
                        <strong>방법 2: 복사 후 수동 등록</strong>
                        <p>코드를 복사한 뒤 새 북마크의 URL 란에 붙여넣으세요.</p>
                        <button type="button" class="btn btn-primary" onclick="copyBookmarklet()">코드 복사</button>
                        <span id="copy-result" style="margin-left:10px;color:var(--primary-color);display:none;">복사됨</span>
                    </div>
                </div>

                <h2>분석 시작</h2>
                <p>YouTube 홈을 연 뒤 즐겨찾기 바의 <strong>피드 분석하기</strong>를 한 번 클릭하면 결과 페이지로 이동합니다.</p>
                <div class="func-action-group">
                    <button type="button" class="btn btn-primary" onclick="window.open('https://www.youtube.com', '_blank')">YouTube 홈 열기</button>
                </div>
            <?php endif; ?>
        </div>
    </article>
</div>

<?php if (!empty($youtubeConfigured)): ?>
<script nonce="<?= $view->getNonce() ?>">
function copyBookmarklet() {
    var code = <?= json_encode($bookmarkletJs) ?>;
    navigator.clipboard.writeText(code).then(function() {
        var el = document.getElementById('copy-result');
        el.style.display = 'inline';
        setTimeout(function() { el.style.display = 'none'; }, 2000);
    });
}
</script>
<?php endif; ?>
