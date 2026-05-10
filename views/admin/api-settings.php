<?php
$youtube = $youtubeSettings ?? [];
$youtubeMasked = $youtubeApiKeyMasked ?? '(미설정)';

$gemini = $geminiSettings ?? [];
$geminiMasked = $geminiApiKeyMasked ?? '(미설정)';
$geminiModel = (string)($gemini['model'] ?? '');
$geminiTimeout = (int)($gemini['timeout_sec'] ?? 60);

$openai = $openaiSettings ?? [];
$openaiMasked = $openaiApiKeyMasked ?? '(미설정)';
$openaiModel = (string)($openai['model'] ?? '');
$openaiTimeout = (int)($openai['timeout_sec'] ?? 60);

$aiProvider = $aiProviderSettings ?? [];
$activeProvider = (string)($aiProvider['active_provider'] ?? 'none');

$geminiModelOptions = [
    'gemini-2.5-flash' => 'gemini-2.5-flash (빠름·저비용)',
    'gemini-2.5-pro'   => 'gemini-2.5-pro (고품질)',
];

$openaiModelOptions = [
    'gpt-5-mini' => 'gpt-5-mini (빠름·저비용)',
    'gpt-5'      => 'gpt-5 (고품질)',
    'gpt-4o-mini' => 'gpt-4o-mini (레거시·저비용)',
    'gpt-4o'      => 'gpt-4o (레거시·고품질)',
];

$nestedClass = static function (string $provider) use ($activeProvider): string {
    return 'admin-card admin-card--nested provider-card ' . ($activeProvider === $provider ? 'is-active' : 'is-inactive');
};

$geminiCache = is_array($geminiModelCache ?? null) ? $geminiModelCache : null;
$openaiCache = is_array($openaiModelCache ?? null) ? $openaiModelCache : null;

$mergeOptions = static function (array $hardcoded, ?array $cache): array {
    $merged = $hardcoded;
    if ($cache !== null && !empty($cache['models'])) {
        foreach ($cache['models'] as $m) {
            $m = (string)$m;
            if ($m !== '' && !isset($merged[$m])) {
                $merged[$m] = $m;
            }
        }
    }
    return $merged;
};

$geminiModelOptions = $mergeOptions($geminiModelOptions, $geminiCache);
$openaiModelOptions = $mergeOptions($openaiModelOptions, $openaiCache);
?>

<div class="admin-content">
    <div class="admin-card">
        <h2>AI 공급자</h2>

        <form method="post" action="/admin/api-settings/ai-providers" class="admin-form">
            <input type="hidden" name="csrf_token" value="<?= $csrfToken ?>">

            <div class="<?= $nestedClass('none') ?>" data-provider="none">
                <label class="provider-card-header">
                    <input type="radio" name="active_provider" value="none" class="visually-hidden" <?= $activeProvider === 'none' ? 'checked' : '' ?>>
                    <h3>비활성</h3>
                    <span class="provider-check" aria-hidden="true"></span>
                </label>
                <p class="provider-card-desc">LLM 분석을 사용하지 않습니다.</p>
            </div>

            <div class="<?= $nestedClass('gemini') ?>" data-provider="gemini">
                <label class="provider-card-header">
                    <input type="radio" name="active_provider" value="gemini" class="visually-hidden" <?= $activeProvider === 'gemini' ? 'checked' : '' ?>>
                    <h3>Gemini</h3>
                    <span class="provider-check" aria-hidden="true"></span>
                </label>

                <div class="admin-form-grid">
                    <div class="admin-form-field">
                        <label>API 키 <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener" class="admin-form-link">발급 ↗</a></label>
                        <input type="text" name="gemini_api_key" value="" placeholder="<?= $view->escape($geminiMasked) ?>">
                    </div>
                    <div class="admin-form-field">
                        <label>모델</label>
                        <div class="combobox" data-combobox>
                            <input type="hidden" name="gemini_model" value="<?= $view->escape($geminiModel) ?>" data-combobox-value>
                            <input type="text" class="combobox-search" value="<?= $view->escape($geminiModel) ?>" placeholder="클릭해서 선택" maxlength="100" autocomplete="off" data-combobox-search>
                            <div class="combobox-dropdown">
                                <ul class="combobox-list" data-combobox-list>
                                    <?php foreach ($geminiModelOptions as $value => $label): ?>
                                        <li class="combobox-item" data-combobox-item data-value="<?= $view->escape($value) ?>"><?= $view->escape($label) ?></li>
                                    <?php endforeach; ?>
                                </ul>
                                <div class="combobox-empty" data-combobox-empty hidden>일치하는 모델이 없습니다.</div>
                            </div>
                        </div>
                    </div>
                    <div class="admin-form-field">
                        <label>타임아웃 (초)</label>
                        <input type="number" name="gemini_timeout_sec" min="5" max="180" value="<?= $geminiTimeout ?>" required>
                    </div>
                </div>
            </div>

            <div class="<?= $nestedClass('openai') ?>" data-provider="openai">
                <label class="provider-card-header">
                    <input type="radio" name="active_provider" value="openai" class="visually-hidden" <?= $activeProvider === 'openai' ? 'checked' : '' ?>>
                    <h3>OpenAI</h3>
                    <span class="provider-check" aria-hidden="true"></span>
                </label>

                <div class="admin-form-grid">
                    <div class="admin-form-field">
                        <label>API 키 <a href="https://platform.openai.com/api-keys" target="_blank" rel="noopener" class="admin-form-link">발급 ↗</a></label>
                        <input type="text" name="openai_api_key" value="" placeholder="<?= $view->escape($openaiMasked) ?>">
                    </div>
                    <div class="admin-form-field">
                        <label>모델</label>
                        <div class="combobox" data-combobox>
                            <input type="hidden" name="openai_model" value="<?= $view->escape($openaiModel) ?>" data-combobox-value>
                            <input type="text" class="combobox-search" value="<?= $view->escape($openaiModel) ?>" placeholder="클릭해서 선택" maxlength="100" autocomplete="off" data-combobox-search>
                            <div class="combobox-dropdown">
                                <ul class="combobox-list" data-combobox-list>
                                    <?php foreach ($openaiModelOptions as $value => $label): ?>
                                        <li class="combobox-item" data-combobox-item data-value="<?= $view->escape($value) ?>"><?= $view->escape($label) ?></li>
                                    <?php endforeach; ?>
                                </ul>
                                <div class="combobox-empty" data-combobox-empty hidden>일치하는 모델이 없습니다.</div>
                            </div>
                        </div>
                    </div>
                    <div class="admin-form-field">
                        <label>타임아웃 (초)</label>
                        <input type="number" name="openai_timeout_sec" min="5" max="180" value="<?= $openaiTimeout ?>" required>
                    </div>
                </div>
            </div>

            <div class="admin-form-actions admin-form-actions--right">
                <button type="submit" class="btn btn-primary">저장</button>
            </div>
        </form>
    </div>

    <script nonce="<?= $view->getNonce() ?>">
    (function () {
        var radios = document.querySelectorAll('input[name="active_provider"]');
        if (!radios.length) return;
        var cards = document.querySelectorAll('[data-provider]');
        if (!cards.length) return;

        function update() {
            var checked = document.querySelector('input[name="active_provider"]:checked');
            var value = checked ? checked.value : '';
            cards.forEach(function (card) {
                var match = card.getAttribute('data-provider') === value;
                card.classList.toggle('is-active', match);
                card.classList.toggle('is-inactive', !match);
            });
        }
        radios.forEach(function (r) { r.addEventListener('change', update); });
        update();
    })();
    </script>

    <div class="admin-card">
        <h2>YouTube Data API v3</h2>

        <form method="post" action="/admin/api-settings/youtube" class="admin-form admin-form--inline-actions">
            <input type="hidden" name="csrf_token" value="<?= $csrfToken ?>">

            <div class="admin-form-grid">
                <div class="admin-form-field">
                    <label>API 키</label>
                    <input type="text" name="api_key" value="" placeholder="<?= $view->escape($youtubeMasked) ?>">
                </div>
            </div>

            <div class="admin-form-actions">
                <button type="submit" class="btn btn-primary">저장</button>
            </div>
        </form>
    </div>
</div>
