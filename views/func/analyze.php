<?php if (!empty($error)): ?>

<div class="post-wrapper post-wrapper-disabled">
    <article class="post">
        <header class="post-header">
            <h1 class="post-title">분석을 완료하지 못했습니다</h1>
            <div class="post-meta">
                <span class="post-category">오류</span>
            </div>
        </header>
        <div class="post-content">
            <p><?= $view->escape($error) ?></p>
            <p><a href="/func">처음으로 돌아가기</a></p>
        </div>
    </article>
</div>

<?php elseif (!empty($analysis)): ?>

<div class="post-wrapper">
    <article class="post">
        <header class="post-header">
            <h1 class="post-title">분석 결과</h1>
            <div class="post-meta">
                <span class="post-category"><?= !empty($llmAnalysis) ? 'LLM 심층 분석' : '주요 성향' ?></span>
                <span class="post-author">추천 피드 기반</span>
                <span class="post-read-count"><?= (int)$videoCount ?>개 영상 분석</span>
            </div>
        </header>

        <div class="post-content">
            <?php if (!empty($llmError)): ?>
                <p class="func-llm-error"><?= $view->escape($llmError) ?></p>
            <?php endif; ?>

            <h2 class="func-result-headline"><?= $view->escape(!empty($llmAnalysis) ? $llmAnalysis['result_type'] : $analysis['resultType']) ?></h2>

            <?php if (!empty($llmAnalysis)): ?>
                <p><?= $view->escape($llmAnalysis['summary']) ?></p>

                <?php if (!empty($llmAnalysis['traits'])): ?>
                    <h2>두드러진 특성</h2>
                    <ul class="func-llm-traits">
                        <?php foreach ($llmAnalysis['traits'] as $trait): ?>
                            <li><?= $view->escape($trait) ?></li>
                        <?php endforeach; ?>
                    </ul>
                <?php endif; ?>

                <?php if (!empty($llmAnalysis['hidden_axes'])): ?>
                    <h2>겉으로는 다르지만 공통된 축</h2>
                    <ul class="func-llm-axes">
                        <?php foreach ($llmAnalysis['hidden_axes'] as $axis): ?>
                            <li><?= $view->escape($axis) ?></li>
                        <?php endforeach; ?>
                    </ul>
                <?php endif; ?>

                <?php if (!empty($llmAnalysis['honest_critique'])): ?>
                    <h2>솔직한 비평</h2>
                    <p class="func-llm-critique"><?= $view->escape($llmAnalysis['honest_critique']) ?></p>
                <?php endif; ?>
            <?php else: ?>
                <p><?= $view->escape($analysis['summary']) ?></p>
            <?php endif; ?>

            <hr class="func-section-divider">
            <h2 class="func-section-title">성향 점수 분포</h2>
            <ul class="func-scores">
                <?php foreach ($analysis['scores'] as $type => $score): ?>
                    <?php $pct = (int)($analysis['percentages'][$type] ?? 0); ?>
                    <li>
                        <span class="func-score-label"><?= $view->escape($type) ?></span>
                        <span class="func-score-bar" aria-hidden="true">
                            <span class="func-score-fill" style="width: <?= $pct ?>%"></span>
                        </span>
                        <span class="func-score-pct"><?= $pct ?>%</span>
                    </li>
                <?php endforeach; ?>
            </ul>

            <?php if (!empty($analysis['mbti'])): ?>
                <div class="func-mbti">
                    <p class="func-mbti-code">MBTI: <strong><?= $view->escape($analysis['mbti']) ?></strong></p>
                    <?php if (!empty($analysis['mbtiAxes'])): ?>
                        <ul class="func-mbti-axes">
                            <?php foreach ($analysis['mbtiAxes'] as $ax): ?>
                                <li>
                                    <span class="func-mbti-axis-side"><strong><?= $view->escape($ax['left']) ?></strong> <?= (int)$ax['leftPct'] ?>%</span>
                                    <span class="func-mbti-axis-bar" aria-hidden="true">
                                        <span class="func-mbti-axis-fill func-mbti-axis-fill--left" style="width: <?= (int)$ax['leftPct'] ?>%"></span>
                                        <span class="func-mbti-axis-fill func-mbti-axis-fill--right" style="width: <?= (int)$ax['rightPct'] ?>%"></span>
                                    </span>
                                    <span class="func-mbti-axis-side"><?= (int)$ax['rightPct'] ?>% <strong><?= $view->escape($ax['right']) ?></strong></span>
                                </li>
                            <?php endforeach; ?>
                        </ul>
                    <?php endif; ?>
                </div>
            <?php endif; ?>

            <?php if (!empty($llmAnalysis)): ?>
                <?php $confidencePct = (int)round((float)$llmAnalysis['confidence'] * 100); ?>
                <hr class="func-section-divider">
                <h2 class="func-section-title">분석 신뢰도: <strong><?= $confidencePct ?>%</strong></h2>
                <div class="func-llm-confidence-bar" aria-hidden="true">
                    <div class="func-llm-confidence-fill" style="width: <?= $confidencePct ?>%"></div>
                </div>
            <?php endif; ?>

        </div>
    </article>

    <?php if (!empty($analysisId)): ?>
        <div class="func-reactions"
             data-analysis-id="<?= (int)$analysisId ?>"
             data-user-vote="<?= $view->escape((string)($userVote ?? '')) ?>">
            <input type="hidden" name="csrf_token" value="<?= $view->escape((string)($csrfToken ?? '')) ?>">
            <button type="button"
                    class="func-reaction-btn func-reaction-btn--like<?= ($userVote === 'like') ? ' is-active' : '' ?>"
                    data-vote="like"
                    aria-pressed="<?= ($userVote === 'like') ? 'true' : 'false' ?>"
                    aria-label="좋아요">
                <svg class="func-reaction-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <path d="M7 10v11"/>
                    <path d="M15 5.88 14 10h5.5a2 2 0 0 1 2 2.26l-1.34 9A2 2 0 0 1 18.18 23H7V10l4.59-7.59a1 1 0 0 1 1.7.7Z"/>
                </svg>
                <span class="func-reaction-label">좋아요</span>
            </button>
            <button type="button"
                    class="func-reaction-btn func-reaction-btn--dislike<?= ($userVote === 'dislike') ? ' is-active' : '' ?>"
                    data-vote="dislike"
                    aria-pressed="<?= ($userVote === 'dislike') ? 'true' : 'false' ?>"
                    aria-label="싫어요">
                <svg class="func-reaction-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <path d="M17 14V3"/>
                    <path d="M9 18.12 10 14H4.5a2 2 0 0 1-2-2.26l1.34-9A2 2 0 0 1 5.82 1H17v13l-4.59 7.59a1 1 0 0 1-1.7-.7Z"/>
                </svg>
                <span class="func-reaction-label">싫어요</span>
            </button>
        </div>
    <?php endif; ?>

    <?php if (!empty($analysisId) && !empty($shareToken)): ?>
        <?php $shortPath = '/a/' . $shareToken; ?>
        <div class="func-share">
            <label class="func-share-label" for="func-share-input">공유 링크</label>
            <div class="func-share-row">
                <input id="func-share-input" class="func-share-input" type="text" readonly
                       value="<?= $view->escape($shortPath) ?>"
                       data-path="<?= $view->escape($shortPath) ?>">
                <button type="button" class="func-share-copy" data-target="#func-share-input" aria-label="링크 복사">복사</button>
            </div>
        </div>
    <?php endif; ?>

    <div class="post-actions">
        <a href="/func" class="btn btn-primary">다시 분석</a>
    </div>
</div>

<?php if (!empty($analysisId)): ?>
<script nonce="<?= $view->getNonce() ?>">
(function () {
    var box = document.querySelector('.func-reactions');
    if (!box) return;
    var analysisId = box.getAttribute('data-analysis-id');
    var buttons = box.querySelectorAll('.func-reaction-btn');
    var pending = false;

    function setState(userVote) {
        box.setAttribute('data-user-vote', userVote || '');
        buttons.forEach(function (btn) {
            var on = (userVote === btn.getAttribute('data-vote'));
            btn.classList.toggle('is-active', on);
            btn.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
    }

    function predictNext(current, vote) {
        return current === vote ? '' : vote;
    }

    // 절대 URL은 클라이언트가 보는 origin 기준으로만 정확 — SSR 값(path) 위로 덮어쓴다
    var shareInput = document.getElementById('func-share-input');
    if (shareInput && shareInput.dataset.path) {
        shareInput.value = window.location.origin + shareInput.dataset.path;
    }

    function copyText(text) {
        if (navigator.clipboard && navigator.clipboard.writeText && window.isSecureContext) {
            return navigator.clipboard.writeText(text);
        }
        return new Promise(function (resolve, reject) {
            var ta = document.createElement('textarea');
            ta.value = text;
            ta.setAttribute('readonly', '');
            ta.style.position = 'fixed';
            ta.style.left = '-9999px';
            ta.style.top = '0';
            document.body.appendChild(ta);
            ta.focus();
            ta.select();
            try { ta.setSelectionRange(0, text.length); } catch (e) {}
            var ok = false;
            try { ok = document.execCommand('copy'); } catch (e) {}
            document.body.removeChild(ta);
            ok ? resolve() : reject(new Error('copy_failed'));
        });
    }

    var copyBtn = document.querySelector('.func-share-copy');
    if (copyBtn) {
        var defaultLabel = copyBtn.textContent;
        copyBtn.addEventListener('click', function () {
            var input = document.querySelector(copyBtn.getAttribute('data-target'));
            if (!input || !input.value) return;
            // 사용자가 시각적으로도 선택 상태를 보게
            input.focus();
            input.select();
            try { input.setSelectionRange(0, input.value.length); } catch (e) {}

            copyText(input.value).then(function () {
                copyBtn.textContent = '복사됨';
                copyBtn.classList.add('is-copied');
            }).catch(function () {
                copyBtn.textContent = '직접 복사';
                copyBtn.classList.add('is-failed');
            }).then(function () {
                setTimeout(function () {
                    copyBtn.textContent = defaultLabel;
                    copyBtn.classList.remove('is-copied');
                    copyBtn.classList.remove('is-failed');
                }, 1400);
            });
        });
    }

    var csrfInput = box.querySelector('input[name="csrf_token"]');
    var csrfToken = csrfInput ? csrfInput.value : '';

    buttons.forEach(function (btn) {
        btn.addEventListener('click', function () {
            if (pending) return;
            pending = true;
            var vote = btn.getAttribute('data-vote');
            var prev = box.getAttribute('data-user-vote') || '';
            // optimistic — 즉시 시각 반영
            setState(predictNext(prev, vote));
            btn.classList.add('is-pulsing');
            setTimeout(function () { btn.classList.remove('is-pulsing'); }, 220);

            var body = new URLSearchParams();
            body.append('analysis_id', analysisId);
            body.append('vote', vote);
            body.append('csrf_token', csrfToken);
            fetch('/func/analyze/react', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: body.toString()
            }).then(function (r) {
                return r.json().then(function (j) { return { ok: r.ok, body: j }; });
            }).then(function (res) {
                if (res.ok && res.body && res.body.ok) {
                    // 서버 정답으로 동기화 (대개 동일 — 변화 없음)
                    setState(res.body.user_vote);
                } else {
                    // 실패 — 직전 상태 롤백
                    setState(prev);
                }
            }).catch(function () {
                setState(prev);
            }).finally(function () {
                pending = false;
            });
        });
    });
})();
</script>
<?php endif; ?>

<?php else: ?>

<div class="post-wrapper post-wrapper-disabled">
    <article class="post">
        <header class="post-header">
            <h1 class="post-title">분석할 영상 데이터가 없습니다</h1>
            <div class="post-meta">
                <span class="post-category">빈 상태</span>
            </div>
        </header>
        <div class="post-content">
            <p>추천 목록을 다시 불러온 뒤 분석을 다시 시도해주세요.</p>
            <p><a href="/func">처음으로 돌아가기</a></p>
        </div>
    </article>
</div>

<?php endif; ?>
