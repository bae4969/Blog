<div class="stocks-container">
    <!-- 시장별 통계 (가로 배치) -->
    <div class="market-stats-horizontal">
            <?php if (!empty($marketStats)): ?>
                <?php foreach ($marketStats as $stat): ?>
                    <div class="market-stat-item-h <?= $currentMarket === $stat['stock_market'] ? 'active' : '' ?>" 
                         onclick="location.href='/stocks?market=<?= urlencode($stat['stock_market']) ?>'">
                        <div class="market-name"><?= $view->escape($stat['stock_market']) ?></div>
                        <div class="market-info">
                            <span class="market-count"><?= number_format($stat['stock_count']) ?>개</span>
                            <?php 
                            $isUSMarket = in_array($stat['stock_market'], ['NYSE', 'NASDAQ', 'AMEX']);
                            if ($isUSMarket) {
                                $capValue = $stat['total_cap'] / 1000000000; // Billion
                                $capUnit = 'B';
                            } else {
                                $capValue = $stat['total_cap'] / 1000000000000; // 조
                                $capUnit = '조';
                            }
                            ?>
                            <span class="market-cap"><?= $isUSMarket ? '$' : '' ?><?= number_format($capValue, 2) ?><?= $capUnit ?></span>
                        </div>
                    </div>
                <?php endforeach; ?>
            <?php endif; ?>
    </div>

    <!-- 사이드바: 검색 -->
    <div class="sidebar-search-bar">
        <div class="stocks-search-bar">
            <input type="text" id="stockSearchInput" placeholder="종목명 또는 코드 검색..." 
                   value="<?= $view->escape($searchQuery) ?>"
                   onkeyup="if(event.keyCode==13){searchStocks()}">
            <button onclick="searchStocks()" class="search-btn">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="11" cy="11" r="8"></circle>
                    <path d="m21 21-4.35-4.35"></path>
                </svg>
            </button>
        </div>
    </div>

    <!-- 메인 컨텐츠: 주식 목록 -->
    <div class="stocks-main">
        <div class="stocks-table">
            <table>
                <thead>
                    <tr>
                        <th>종목명</th>
                        <th>종목코드</th>
                        <th>시장</th>
                        <th>유형</th>
                        <th>현재가</th>
                        <th>시가총액</th>
                        <th>상장주식수</th>
                    </tr>
                </thead>
                <tbody>
                    <?php if (empty($stocks)): ?>
                        <tr>
                            <td colspan="7" class="no-data">조회된 주식이 없습니다.</td>
                        </tr>
                    <?php else: ?>
                        <?php foreach ($stocks as $stock): ?>
                            <tr class="stock-row" onclick="location.href='/stocks/view?code=<?= urlencode($stock['stock_code']) ?>'">
                                <td class="stock-name-cell">
                                    <div class="stock-name-kr"><?= $view->escape($stock['stock_name_kr']) ?></div>
                                    <?php if ($stock['stock_name_en']): ?>
                                        <div class="stock-name-en"><?= $view->escape($stock['stock_name_en']) ?></div>
                                    <?php endif; ?>
                                </td>
                                <td class="stock-code"><?= $view->escape($stock['stock_code']) ?></td>
                                <td><span class="market-badge"><?= $view->escape($stock['stock_market']) ?></span></td>
                                <td><span class="type-badge type-<?= strtolower($stock['stock_type']) ?>"><?= $view->escape($stock['stock_type']) ?></span></td>
                                <?php $isUSMarket = in_array($stock['stock_market'], ['NYSE', 'NASDAQ', 'AMEX']); ?>
                                <td class="stock-price"><?= $isUSMarket ? '$' : '' ?><?= number_format($stock['stock_price'] ?? 0, $isUSMarket ? 2 : 0) ?><?= $isUSMarket ? '' : '원' ?></td>
                                <td class="stock-cap"><?= $isUSMarket ? '$' : '' ?><?= number_format(($stock['stock_capitalization'] ?? 0) / ($isUSMarket ? 1000000000 : 1000000000000), $isUSMarket ? 2 : 2) ?><?= $isUSMarket ? 'B' : '조' ?></td>
                                <td><?php 
                                    if (!empty($stock['stock_count']) && $stock['stock_count'] > 0) {
                                        $count = $stock['stock_count'];
                                        if ($isUSMarket) {
                                            if ($count >= 1000000000) {
                                                echo number_format($count / 1000000000, 2) . 'B';
                                            } elseif ($count >= 1000000) {
                                                echo number_format($count / 1000000, 2) . 'M';
                                            } elseif ($count >= 1000) {
                                                echo number_format($count / 1000, 2) . 'K';
                                            } else {
                                                echo number_format($count);
                                            }
                                        } else {
                                            if ($count >= 100000000) {
                                                echo number_format($count / 100000000, 1) . '억';
                                            } elseif ($count >= 10000) {
                                                echo number_format($count / 10000, 1) . '만';
                                            } else {
                                                echo number_format($count);
                                            }
                                        }
                                    } else {
                                        echo '-';
                                    }
                                ?></td>
                            </tr>
                        <?php endforeach; ?>
                    <?php endif; ?>
                </tbody>
            </table>
        </div>

        <!-- 페이지네이션 -->
        <?php if ($totalPages > 1): ?>
            <div class="pagination">
                <?php if ($currentPage > 1): ?>
                    <button class="page-btn" onclick="location.href='?page=<?= $currentPage - 1 ?><?= $currentMarket ? '&market=' . urlencode($currentMarket) : '' ?><?= $searchQuery ? '&search=' . urlencode($searchQuery) : '' ?>'">&lt;</button>
                <?php endif; ?>
                
                <?php 
                $startPage = max(1, $currentPage - 2);
                $endPage = min($totalPages, $currentPage + 2);
                for ($i = $startPage; $i <= $endPage; $i++): 
                ?>
                    <button class="page-btn <?= $i === $currentPage ? 'active' : '' ?>" 
                            onclick="location.href='?page=<?= $i ?><?= $currentMarket ? '&market=' . urlencode($currentMarket) : '' ?><?= $searchQuery ? '&search=' . urlencode($searchQuery) : '' ?>'">
                        <?= $i ?>
                    </button>
                <?php endfor; ?>
                
                <?php if ($currentPage < $totalPages): ?>
                    <button class="page-btn" onclick="location.href='?page=<?= $currentPage + 1 ?><?= $currentMarket ? '&market=' . urlencode($currentMarket) : '' ?><?= $searchQuery ? '&search=' . urlencode($searchQuery) : '' ?>'">&gt;</button>
                <?php endif; ?>
            </div>
        <?php endif; ?>
    </div>
    
    <!-- 사이드바: 거래대금 TOP 10 -->
    <div class="stocks-sidebar-right">
        <div class="top-stocks-section">
            <h3>거래대금 TOP 10</h3>
            <div class="top-stocks-list">
                <?php if (!empty($topStocks)): ?>
                    <?php foreach ($topStocks as $idx => $topStock): ?>
                        <div class="top-stock-item" onclick="location.href='/stocks/view?code=<?= urlencode($topStock['stock_code']) ?>'">
                            <div class="top-stock-rank"><?= $idx + 1 ?></div>
                            <div class="stock-info">
                                <div class="stock-name"><?= $view->escape($topStock['stock_name_kr']) ?></div>
                                <div class="stock-code"><?= $view->escape($topStock['stock_code']) ?></div>
                            </div>
                            <div class="stock-price-info">
                                <?php
                                    $isUSMarket = in_array($topStock['stock_market'], ['NYSE', 'NASDAQ', 'AMEX']);
                                    $amount = (float)($topStock['total_amount'] ?? 0);
                                    if ($amount >= 1e12) {
                                        $amountStr = number_format($amount / 1e12, 1) . '조';
                                    } elseif ($amount >= 1e8) {
                                        $amountStr = number_format($amount / 1e8, 0) . '억';
                                    } elseif ($amount >= 1e4) {
                                        $amountStr = number_format($amount / 1e4, 0) . '만';
                                    } else {
                                        $amountStr = number_format($amount, 0);
                                    }
                                ?>
                                <div class="stock-price"><?= $isUSMarket ? '$' : '' ?><?= number_format($topStock['stock_price'], $isUSMarket ? 2 : 0) ?><?= $isUSMarket ? '' : '원' ?></div>
                                <div class="stock-trading-amount"><?= $amountStr ?></div>
                            </div>
                        </div>
                    <?php endforeach; ?>
                <?php else: ?>
                    <div class="no-top-stocks">데이터가 없습니다.</div>
                <?php endif; ?>
            </div>
        </div>
    </div>
</div>

<script>
function searchStocks() {
    const searchValue = document.getElementById('stockSearchInput').value;
    const currentMarket = '<?= $view->escape($currentMarket) ?>';
    let url = '/stocks?search=' + encodeURIComponent(searchValue);
    if (currentMarket) {
        url += '&market=' + encodeURIComponent(currentMarket);
    }
    location.href = url;
}
</script>
