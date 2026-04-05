<div class="admin-content">
    <div class="admin-card collapsible-card collapsed">
        <h2>액면분할/병합 관리</h2>
        <div class="stat-row">
            <div class="stat-item"><span class="stat-label">등록된 이벤트</span> <span class="stat-value"><?= (int)$totalCount ?></span></div>
        </div>
        <hr>

        <h3 class="collapsible-header">
            이벤트 등록
            <svg class="collapsible-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
        </h3>
        <div class="collapsible-body">
            <form method="post" action="/admin/stock-splits/create" class="admin-form" id="splitEventForm">
                <input type="hidden" name="csrf_token" value="<?= $csrfToken ?>">
                <input type="hidden" name="stock_code" id="splitStockCode">
                <input type="hidden" name="market" id="splitMarket">
                <input type="hidden" name="ratio_from" id="splitRatioFrom">
                <input type="hidden" name="ratio_to" id="splitRatioTo">
                <div class="admin-form-grid">
                    <div class="admin-form-field" style="position:relative">
                        <label>종목 검색 <span style="color:var(--danger-color, #e53935)">*</span></label>
                        <input type="text" id="splitStockSearch" autocomplete="off" placeholder="종목명 또는 코드 검색 (예: 엔비디아, NVDA, 삼성전자)" required>
                        <div id="splitSearchResults" style="display:none;position:absolute;top:100%;left:0;right:0;z-index:100;max-height:240px;overflow-y:auto;border:1px solid var(--border-color, #464646);border-radius:4px;background:var(--card-bg, #1e1e1e)"></div>
                        <div id="splitSelectedStock" style="display:none;margin-top:0.4rem;padding:0.4rem 0.7rem;border-radius:4px;background:var(--bg-tertiary, #2a2a2a);font-size:0.9rem">
                            <span id="splitSelectedInfo"></span>
                            <button type="button" onclick="clearSplitSelection()" style="float:right;background:none;border:none;color:var(--text-muted, #9aa0a6);cursor:pointer;font-size:0.85rem">✕ 초기화</button>
                        </div>
                    </div>
                    <div class="admin-form-field">
                        <label>이벤트 일자 <span style="color:var(--danger-color, #e53935)">*</span></label>
                        <input type="date" name="event_date" id="splitEventDate" required>
                    </div>
                    <div class="admin-form-field">
                        <label>유형 <span style="color:var(--danger-color, #e53935)">*</span></label>
                        <select id="splitType" onchange="updateSplitDescription()" required>
                            <option value="split">액면분할 (1주 → N주)</option>
                            <option value="merge">주식병합 (N주 → 1주)</option>
                        </select>
                    </div>
                    <div class="admin-form-field">
                        <label id="splitRatioLabel">배수 <span style="color:var(--danger-color, #e53935)">*</span></label>
                        <input type="number" id="splitRatio" required min="2" max="10000" placeholder="예: 10 (1주→10주)">
                    </div>
                    <div class="admin-form-field">
                        <label>설명</label>
                        <input type="text" name="description" id="splitDescription" maxlength="200" placeholder="자동 생성됩니다">
                    </div>
                </div>
                <div class="admin-form-actions">
                    <button type="submit" class="btn btn-primary">이벤트 등록</button>
                </div>
            </form>
        </div>

        <!-- 이벤트 목록 -->
        <?php if (empty($events)): ?>
            <p class="admin-placeholder">등록된 분할/병합 이벤트가 없습니다.</p>
        <?php else: ?>
            <div class="admin-table-wrap">
                <table class="admin-table">
                    <thead>
                        <tr>
                            <th>종목 코드</th>
                            <th>시장</th>
                            <th>이벤트 일자</th>
                            <th>비율</th>
                            <th>유형</th>
                            <th>설명</th>
                            <th>등록일</th>
                            <th>작업</th>
                        </tr>
                    </thead>
                    <tbody>
                    <?php foreach ($events as $event):
                        $isSplit = $event['ratio_from'] < $event['ratio_to'];
                    ?>
                        <tr>
                            <td><strong><?= $view->escape($event['stock_code']) ?></strong></td>
                            <td style="text-align:center">
                                <?php if ($event['market'] === 'KR'): ?>
                                    <span class="ip-badge ip-badge-manual">KR</span>
                                <?php elseif ($event['market'] === 'US'): ?>
                                    <span class="ip-badge ip-badge-auto">US</span>
                                <?php else: ?>
                                    <span class="ip-badge">COIN</span>
                                <?php endif; ?>
                            </td>
                            <td><?= $view->escape($event['event_date']) ?></td>
                            <td><strong><?= (int)$event['ratio_from'] ?>:<?= (int)$event['ratio_to'] ?></strong></td>
                            <td>
                                <?php if ($isSplit): ?>
                                    <span style="color:var(--success-color, #4CAF50)">분할</span>
                                <?php else: ?>
                                    <span style="color:var(--warning-color, #FF9800)">병합</span>
                                <?php endif; ?>
                            </td>
                            <td class="text-muted"><?= $view->escape($event['description'] ?? '-') ?></td>
                            <td class="text-muted"><?= $view->escape($event['created_at']) ?></td>
                            <td>
                                <form method="post" action="/admin/stock-splits/delete" style="display:inline" onsubmit="return confirm('이 이벤트를 삭제하시겠습니까?\n삭제 후 해당 종목의 캔들 캐시가 무효화됩니다.')">
                                    <input type="hidden" name="csrf_token" value="<?= $csrfToken ?>">
                                    <input type="hidden" name="event_id" value="<?= (int)$event['id'] ?>">
                                    <button type="submit" class="btn btn-sm btn-danger">삭제</button>
                                </form>
                            </td>
                        </tr>
                    <?php endforeach; ?>
                    </tbody>
                </table>
            </div>

            <?php if ($totalPages > 1): ?>
                <div class="admin-pagination">
                    <?php if ($currentPage > 1): ?>
                        <a href="/admin/stock-splits?page=<?= $currentPage - 1 ?>" class="btn btn-sm">← 이전</a>
                    <?php endif; ?>
                    <span class="text-muted"><?= $currentPage ?> / <?= $totalPages ?></span>
                    <?php if ($currentPage < $totalPages): ?>
                        <a href="/admin/stock-splits?page=<?= $currentPage + 1 ?>" class="btn btn-sm">다음 →</a>
                    <?php endif; ?>
                </div>
            <?php endif; ?>
        <?php endif; ?>
    </div>
</div>

<script>
(function() {
    var searchTimer = null;
    var searchInput = document.getElementById('splitStockSearch');
    var resultsBox = document.getElementById('splitSearchResults');
    var selectedBox = document.getElementById('splitSelectedStock');
    var selectedInfo = document.getElementById('splitSelectedInfo');

    searchInput.addEventListener('input', function() {
        clearTimeout(searchTimer);
        var q = this.value.trim();
        if (q.length < 1) { resultsBox.style.display = 'none'; return; }
        searchTimer = setTimeout(function() { searchStocks(q); }, 300);
    });

    searchInput.addEventListener('blur', function() {
        setTimeout(function() { resultsBox.style.display = 'none'; }, 200);
    });

    function searchStocks(q) {
        fetch('/stocks/api/search?q=' + encodeURIComponent(q) + '&limit=10')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data.success || !data.data.length) {
                    resultsBox.innerHTML = '<div style="padding:0.6rem;color:var(--text-muted,#9aa0a6)">검색 결과 없음</div>';
                    resultsBox.style.display = 'block';
                    return;
                }
                var html = '';
                data.data.forEach(function(s) {
                    var market = resolveMarket(s.stock_market, s.stock_type);
                    html += '<div class="split-search-item" style="padding:0.5rem 0.7rem;cursor:pointer;border-bottom:1px solid var(--border-color,#464646)" '
                        + 'onmousedown="selectSplitStock(\'' + escAttr(s.stock_code) + '\',\'' + escAttr(s.stock_name_kr) + '\',\'' + market + '\')">'
                        + '<strong>' + esc(s.stock_code) + '</strong> '
                        + '<span style="color:var(--text-secondary,#C3C3C3)">' + esc(s.stock_name_kr) + '</span> '
                        + '<span class="ip-badge" style="font-size:0.75rem">' + market + '</span>'
                        + '</div>';
                });
                resultsBox.innerHTML = html;
                resultsBox.style.display = 'block';
            })
            .catch(function() { resultsBox.style.display = 'none'; });
    }

    function resolveMarket(stockMarket, stockType) {
        if (stockType === 'COIN') return 'COIN';
        var m = (stockMarket || '').toUpperCase();
        if (['KOSPI','KOSDAQ','KONEX'].indexOf(m) >= 0) return 'KR';
        if (['NYSE','NASDAQ','AMEX'].indexOf(m) >= 0) return 'US';
        return 'KR';
    }

    window.selectSplitStock = function(code, name, market) {
        document.getElementById('splitStockCode').value = code;
        document.getElementById('splitMarket').value = market;
        selectedInfo.textContent = code + ' — ' + name + ' (' + market + ')';
        selectedBox.style.display = 'block';
        searchInput.style.display = 'none';
        resultsBox.style.display = 'none';
    };

    window.clearSplitSelection = function() {
        document.getElementById('splitStockCode').value = '';
        document.getElementById('splitMarket').value = '';
        selectedBox.style.display = 'none';
        searchInput.style.display = '';
        searchInput.value = '';
        searchInput.focus();
    };

    window.updateSplitDescription = function() {
        var type = document.getElementById('splitType').value;
        var ratio = document.getElementById('splitRatio').value;
        var label = document.getElementById('splitRatioLabel');
        var desc = document.getElementById('splitDescription');

        if (type === 'split') {
            label.innerHTML = '분할 배수 <span style="color:var(--danger-color,#e53935)">*</span>';
            if (ratio) desc.value = '1:' + ratio + ' 액면분할';
        } else {
            label.innerHTML = '병합 배수 <span style="color:var(--danger-color,#e53935)">*</span>';
            if (ratio) desc.value = ratio + ':1 주식병합';
        }
    };

    document.getElementById('splitRatio').addEventListener('input', updateSplitDescription);

    document.getElementById('splitEventForm').addEventListener('submit', function(e) {
        var code = document.getElementById('splitStockCode').value;
        if (!code) { e.preventDefault(); alert('종목을 검색하여 선택해주세요.'); return; }

        var type = document.getElementById('splitType').value;
        var ratio = parseInt(document.getElementById('splitRatio').value, 10);
        if (!ratio || ratio < 2) { e.preventDefault(); alert('배수를 2 이상 입력해주세요.'); return; }

        if (type === 'split') {
            document.getElementById('splitRatioFrom').value = '1';
            document.getElementById('splitRatioTo').value = ratio;
        } else {
            document.getElementById('splitRatioFrom').value = ratio;
            document.getElementById('splitRatioTo').value = '1';
        }
    });

    function esc(s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
    function escAttr(s) { return s.replace(/'/g, "\\'").replace(/"/g, '&quot;'); }
})();
</script>
