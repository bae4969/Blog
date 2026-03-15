<?php
$queryBase = ['market' => $currentMarket];
if ($searchQuery !== '') {
    $queryBase['search'] = $searchQuery;
}
$marketLabels = [
    'KR' => '한국',
    'US' => '미국',
    'COIN' => '코인',
];
$draftSelections = array_keys($registeredCodes ?? []);
$registeredCountsByMarket = $registeredCountsByMarket ?? ['KR' => 0, 'US' => 0, 'COIN' => 0];
$currentRegisteredCount = (int)($registeredCountsByMarket[$currentMarket] ?? 0);
?>

<div class="admin-content">
    <div class="admin-card">
        <h2>주식 구독 관리</h2>
    </div>

    <div class="admin-card">
        <div class="stat-row">
            <div class="stat-item"><span class="stat-label">현재 필터 결과</span> <span class="stat-value"><?= number_format($totalCount) ?></span></div>
            <span class="stat-sep">·</span>
            <div class="stat-item"><span class="stat-label">현재 시장 등록 종목</span> <span class="stat-value" id="registeredCountLabel"><?= number_format($currentRegisteredCount) ?></span></div>
            <span class="stat-sep">·</span>
            <div class="stat-item"><span class="stat-label">현재 시장 선택 수</span> <span class="stat-value" id="selectedCountLabel">0</span></div>
        </div>
    </div>

    <div class="admin-card stock-admin-management-card">
        <div class="stock-admin-toolbar">
            <div class="stock-admin-market-tabs">
                <?php foreach ($marketLabels as $marketCode => $marketLabel): ?>
                    <?php $marketQuery = $queryBase; $marketQuery['market'] = $marketCode; $marketQuery['page'] = 1; ?>
                    <a class="stock-admin-market-tab <?= $currentMarket === $marketCode ? 'active' : '' ?>" href="/admin/stocks?<?= http_build_query($marketQuery) ?>">
                        <?= $view->escape($marketLabel) ?>
                    </a>
                <?php endforeach; ?>
            </div>

            <form class="stock-admin-search-form" method="get" action="/admin/stocks">
                <input type="hidden" name="market" value="<?= $view->escape($currentMarket) ?>">
                <input type="text" name="search" placeholder="종목명 또는 코드 검색" value="<?= $view->escape($searchQuery) ?>">
                <button type="submit" class="btn btn-primary">검색</button>
            </form>

            <div class="stock-admin-actions">
                <button type="button" class="btn btn-secondary stock-admin-action" id="resetSelectionButton">원래 상태로 되돌리기</button>
                <button type="submit" form="stockAdminForm" class="btn btn-primary stock-admin-action">구독 목록 저장</button>
            </div>
        </div>

        <form class="stock-admin-table-form" method="post" action="/admin/stocks/subscriptions" id="stockAdminForm">
            <input type="hidden" name="csrf_token" value="<?= $view->csrfToken() ?>">
            <input type="hidden" name="current_market" value="<?= $view->escape($currentMarket) ?>">
            <input type="hidden" name="current_search" value="<?= $view->escape($searchQuery) ?>">
            <input type="hidden" name="current_page" value="<?= (int)$currentPage ?>">
            <div id="dynamicSelectionInputs"></div>

            <div class="stocks-table admin-table">
                <table>
                    <thead>
                        <tr>
                            <th>선택</th>
                            <th>종목명</th>
                            <th>코드</th>
                            <th>시장</th>
                            <th>유형</th>
                            <th>현재가</th>
                            <th>등록 상태</th>
                            <th>이동</th>
                        </tr>
                    </thead>
                    <tbody>
                        <?php if (empty($stocks)): ?>
                            <tr>
                                <td colspan="8" class="no-data">조회된 종목이 없습니다.</td>
                            </tr>
                        <?php else: ?>
                            <?php foreach ($stocks as $stock): ?>
                                <?php
                                $selectionKey = ($stock['asset_group'] ?? 'STOCK') . ':' . ($stock['stock_code'] ?? '');
                                $viewMarket = ($stock['asset_group'] ?? '') === 'COIN' ? 'COIN' : '';
                                $isUSMarket = in_array($stock['stock_market'], ['NYSE', 'NASDAQ', 'AMEX'], true);
                                ?>
                                <tr class="admin-table-row <?= !empty($stock['is_registered']) ? 'is-selected' : '' ?>" data-selection-key="<?= $view->escape($selectionKey) ?>">
                                    <td class="admin-select-cell">
                                        <input
                                            type="checkbox"
                                            class="admin-stock-checkbox"
                                            value="<?= $view->escape($selectionKey) ?>"
                                            <?= !empty($stock['is_registered']) ? 'checked' : '' ?>
                                        >
                                    </td>
                                    <td class="stock-name-cell">
                                        <div class="stock-name-kr"><?= $view->escape($stock['stock_name_kr'] ?? '') ?></div>
                                        <?php if (!empty($stock['stock_name_en'])): ?>
                                            <div class="stock-name-en"><?= $view->escape($stock['stock_name_en']) ?></div>
                                        <?php endif; ?>
                                    </td>
                                    <td class="stock-code"><?= $view->escape($stock['stock_code'] ?? '') ?></td>
                                    <td><span class="market-badge"><?= $view->escape($stock['stock_market'] ?? '') ?></span></td>
                                    <td><span class="type-badge type-<?= strtolower($stock['stock_type'] ?? 'stock') ?>"><?= $view->escape($stock['stock_type'] ?? '') ?></span></td>
                                    <td class="stock-price">
                                        <?= $isUSMarket ? '$' : '' ?><?= number_format((float)($stock['stock_price'] ?? 0), $isUSMarket ? 2 : 0) ?><?= $isUSMarket ? '' : '원' ?>
                                    </td>
                                    <td><?= !empty($stock['is_registered']) ? '등록됨' : '미등록' ?></td>
                                    <td>
                                        <a class="stock-admin-view-link" href="/stocks/view?code=<?= urlencode($stock['stock_code'] ?? '') ?><?= $viewMarket !== '' ? '&market=' . urlencode($viewMarket) : '' ?>">
                                            상세 보기
                                        </a>
                                    </td>
                                </tr>
                            <?php endforeach; ?>
                        <?php endif; ?>
                    </tbody>
                </table>
            </div>

            <?php if ($totalPages > 1): ?>
                <div class="pagination">
                    <?php if ($currentPage > 1): ?>
                        <?php $previousQuery = $queryBase; $previousQuery['page'] = $currentPage - 1; ?>
                        <a class="page-btn" href="/admin/stocks?<?= http_build_query($previousQuery) ?>" aria-label="이전 페이지" title="이전 페이지">&lt;</a>
                    <?php endif; ?>

                    <?php
                    $startPage = max(1, $currentPage - 2);
                    $endPage = min($totalPages, $currentPage + 2);
                    for ($pageNumber = $startPage; $pageNumber <= $endPage; $pageNumber++):
                        $pageQuery = $queryBase;
                        $pageQuery['page'] = $pageNumber;
                    ?>
                        <a class="page-btn <?= $pageNumber === $currentPage ? 'active' : '' ?>" href="/admin/stocks?<?= http_build_query($pageQuery) ?>">
                            <?= $pageNumber ?>
                        </a>
                    <?php endfor; ?>

                    <?php if ($currentPage < $totalPages): ?>
                        <?php $nextQuery = $queryBase; $nextQuery['page'] = $currentPage + 1; ?>
                        <a class="page-btn" href="/admin/stocks?<?= http_build_query($nextQuery) ?>" aria-label="다음 페이지" title="다음 페이지">&gt;</a>
                    <?php endif; ?>
                </div>
            <?php endif; ?>
        </form>
    </div>
</div>

<script>
const stockAdminStorageKey = 'stock-admin-selection-draft';
const stockAdminServerSelections = <?= json_encode(array_values($draftSelections), JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) ?>;
const stockAdminSelectionMarketMap = <?= json_encode($selectionMarketMap ?? [], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) ?>;
const stockAdminCurrentMarket = <?= json_encode($currentMarket, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) ?>;
const stockAdminForceSync = <?= !empty($forceSelectionSync) ? 'true' : 'false' ?>;

function loadStockAdminDraft() {
    if (stockAdminForceSync || !sessionStorage.getItem(stockAdminStorageKey)) {
        sessionStorage.setItem(stockAdminStorageKey, JSON.stringify(stockAdminServerSelections));
    }

    try {
        const parsed = JSON.parse(sessionStorage.getItem(stockAdminStorageKey) || '[]');
        return new Set(Array.isArray(parsed) ? parsed : []);
    } catch (error) {
        sessionStorage.setItem(stockAdminStorageKey, JSON.stringify(stockAdminServerSelections));
        return new Set(stockAdminServerSelections);
    }
}

function saveStockAdminDraft(selectionSet) {
    sessionStorage.setItem(stockAdminStorageKey, JSON.stringify(Array.from(selectionSet)));
}

function countStockAdminSelectionsForMarket(selectionSet, market) {
    let count = 0;

    selectionSet.forEach((selectionKey) => {
        if ((stockAdminSelectionMarketMap[selectionKey] || null) === market) {
            count += 1;
        }
    });

    return count;
}

function updateStockAdminSelectionCount(selectionSet) {
    const label = document.getElementById('selectedCountLabel');
    if (label) {
        label.textContent = countStockAdminSelectionsForMarket(selectionSet, stockAdminCurrentMarket).toLocaleString();
    }
}

function syncStockAdminCheckboxes(selectionSet) {
    document.querySelectorAll('.admin-stock-checkbox').forEach((checkbox) => {
        const isChecked = selectionSet.has(checkbox.value);
        checkbox.checked = isChecked;
        const row = checkbox.closest('.admin-table-row');
        if (row) {
            row.classList.toggle('is-selected', isChecked);
        }
    });
}

document.addEventListener('DOMContentLoaded', function () {
    const form = document.getElementById('stockAdminForm');
    const resetButton = document.getElementById('resetSelectionButton');
    const dynamicSelectionInputs = document.getElementById('dynamicSelectionInputs');
    const selectionSet = loadStockAdminDraft();

    syncStockAdminCheckboxes(selectionSet);
    updateStockAdminSelectionCount(selectionSet);

    document.querySelectorAll('.admin-stock-checkbox').forEach((checkbox) => {
        checkbox.addEventListener('change', function () {
            if (this.checked) {
                selectionSet.add(this.value);
            } else {
                selectionSet.delete(this.value);
            }

            const row = this.closest('.admin-table-row');
            if (row) {
                row.classList.toggle('is-selected', this.checked);
            }

            saveStockAdminDraft(selectionSet);
            updateStockAdminSelectionCount(selectionSet);
        });
    });

    if (resetButton) {
        resetButton.addEventListener('click', function () {
            selectionSet.clear();
            stockAdminServerSelections.forEach((value) => selectionSet.add(value));
            saveStockAdminDraft(selectionSet);
            syncStockAdminCheckboxes(selectionSet);
            updateStockAdminSelectionCount(selectionSet);
        });
    }

    if (form) {
        form.addEventListener('submit', function () {
            dynamicSelectionInputs.innerHTML = '';
            Array.from(selectionSet).sort().forEach((value) => {
                const input = document.createElement('input');
                input.type = 'hidden';
                input.name = 'selected_codes[]';
                input.value = value;
                dynamicSelectionInputs.appendChild(input);
            });
        });
    }
});
</script>
