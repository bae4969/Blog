<div class="stocks-container">
    <!-- 시장별 통계 (가로 배치) -->
    <div class="market-stats-horizontal">
            <?php if (!empty($marketStats)): ?>
                <?php foreach ($marketStats as $stat): ?>
                    <?php if (!in_array($stat['market_group'], ['KR', 'US', 'COIN'], true)) { continue; } ?>
                    <?php $isUS = ($stat['market_group'] === 'US'); ?>
                    <?php $isCoin = ($stat['market_group'] === 'COIN'); ?>
                    <div class="market-stat-item-h market-<?= strtolower($stat['market_group']) ?> <?= $currentMarket === $stat['market_group'] ? 'active' : '' ?>" 
                         onclick="location.href='/stocks?market=<?= urlencode($stat['market_group']) ?>'">
                        <div class="market-name">
                            <?php if ($stat['market_group'] === 'KR'): ?>
                                <svg class="market-symbol" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                                    <rect x="2.2" y="2.2" width="15.6" height="15.6" rx="4" stroke="currentColor" stroke-width="1.4" opacity="0.5" />
                                    <path d="M10 6.2C11.9 6.2 13.4 7.7 13.4 9.6C13.4 11.5 11.9 13 10 13C8.1 13 6.6 11.5 6.6 9.6C6.6 7.7 8.1 6.2 10 6.2Z" fill="#ef4444" />
                                    <path d="M10 13C8.1 13 6.6 11.5 6.6 9.6C6.6 7.7 8.1 6.2 10 6.2C11.9 6.2 13.4 7.7 13.4 9.6C13.4 11.5 11.9 13 10 13Z" fill="#2563eb" transform="translate(0 0.9)" />
                                    <circle cx="10" cy="9.15" r="1.7" fill="#2563eb" />
                                    <circle cx="10" cy="10.95" r="1.7" fill="#ef4444" />
                                </svg>
                            <?php elseif ($stat['market_group'] === 'US'): ?>
                                <svg class="market-symbol" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                                    <rect x="2.2" y="2.2" width="15.6" height="15.6" rx="4" stroke="currentColor" stroke-width="1.4" opacity="0.5" />
                                    <path d="M4.6 6.1H15.4M4.6 8.2H15.4M4.6 10.3H15.4M4.6 12.4H15.4" stroke="#ef4444" stroke-width="1.2" stroke-linecap="round" />
                                    <rect x="4.6" y="5.2" width="5.4" height="4.6" rx="1" fill="#2563eb" />
                                    <path d="M6 6.3L6.3 7L7 7.1L6.5 7.6L6.6 8.3L6 7.9L5.4 8.3L5.5 7.6L5 7.1L5.7 7L6 6.3Z" fill="white" />
                                    <path d="M8.1 6.9L8.28 7.28L8.7 7.34L8.4 7.63L8.47 8.04L8.1 7.83L7.73 8.04L7.8 7.63L7.5 7.34L7.92 7.28L8.1 6.9Z" fill="white" />
                                </svg>
                            <?php else: ?>
                                <svg class="market-symbol" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                                    <circle cx="10" cy="10" r="7" stroke="currentColor" stroke-width="1.5" opacity="0.55" />
                                    <circle cx="10" cy="10" r="5.2" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.35" />
                                    <path d="M11.5 6.2H8.9C8.15 6.2 7.6 6.72 7.6 7.38C7.6 8.04 8.15 8.56 8.9 8.56H10.9C11.65 8.56 12.2 9.08 12.2 9.74C12.2 10.4 11.65 10.92 10.9 10.92H8" stroke="currentColor" stroke-width="1.45" stroke-linecap="round" stroke-linejoin="round" />
                                    <path d="M9.9 5.5V13.8" stroke="currentColor" stroke-width="1.45" stroke-linecap="round" />
                                    <path d="M6.2 14.4L13.8 14.4" stroke="currentColor" stroke-width="1" stroke-linecap="round" opacity="0.4" />
                                </svg>
                            <?php endif; ?>
                            <span><?= $view->escape($stat['market_label']) ?></span>
                        </div>
                        <div class="market-info">
                            <span class="market-count"><?= number_format($stat['stock_count']) ?><?= $isCoin ? '종목' : '종목' ?></span>
                            <span class="market-sep">·</span>
                            <?php 
                            if ($isUS) {
                                $capValue = $stat['total_cap'] / 1000000000;
                                $capUnit = 'B';
                            } else {
                                $cap = $stat['total_cap'];
                                if ($cap >= 1e20) { $capValue = $cap / 1e20; $capUnit = '해'; }
                                elseif ($cap >= 1e16) { $capValue = $cap / 1e16; $capUnit = '경'; }
                                elseif ($cap >= 1e12) { $capValue = $cap / 1e12; $capUnit = '조'; }
                                elseif ($cap >= 1e8) { $capValue = $cap / 1e8; $capUnit = '억'; }
                                elseif ($cap >= 1e4) { $capValue = $cap / 1e4; $capUnit = '만'; }
                                else { $capValue = $cap; $capUnit = ''; }
                            }
                            ?>
                            <span class="market-cap"><?= $isUS ? '$' : '' ?><?= number_format($capValue, 2) ?><?= $capUnit ?></span>
                        </div>
                    </div>
                <?php endforeach; ?>
            <?php endif; ?>
    </div>

    <!-- 백테스팅 버튼 -->
    <div class="sidebar-search-bar">
        <a href="/stocks/backtest" class="backtest-link-btn">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>
            </svg>
            포트폴리오 백테스팅
        </a>
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
                        <th><?= $currentMarket === 'COIN' ? '총 발행량' : '상장주식수' ?></th>
                    </tr>
                </thead>
                <tbody>
                    <?php if (empty($stocks)): ?>
                        <tr>
                            <td colspan="7" class="no-data">조회된 종목이 없습니다.</td>
                        </tr>
                    <?php else: ?>
                        <?php foreach ($stocks as $stock): ?>
                            <tr class="stock-row" onclick="location.href='/stocks/view?code=<?= urlencode($stock['stock_code']) ?><?= $currentMarket === 'COIN' ? '&market=COIN' : '' ?>'">
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
                                <?php $isCoinMarket = (($stock['stock_type'] ?? '') === 'COIN'); ?>
                                <td class="stock-price"><?= $isUSMarket ? '$' : '' ?><?= number_format($stock['stock_price'] ?? 0, $isUSMarket ? 2 : 0) ?><?= $isUSMarket ? '' : '원' ?></td>
                                <td class="stock-cap"><?php
                                    $cap = (float)($stock['stock_capitalization'] ?? 0);
                                    if ($isUSMarket) {
                                        echo '$' . number_format($cap / 1e9, 2) . 'B';
                                    } elseif ($cap >= 1e20) {
                                        echo number_format($cap / 1e20, 2) . '해';
                                    } elseif ($cap >= 1e16) {
                                        echo number_format($cap / 1e16, 2) . '경';
                                    } elseif ($cap >= 1e12) {
                                        echo number_format($cap / 1e12, 2) . '조';
                                    } elseif ($cap >= 1e8) {
                                        echo number_format($cap / 1e8, 0) . '억';
                                    } elseif ($cap >= 1e4) {
                                        echo number_format($cap / 1e4, 0) . '만';
                                    } else {
                                        echo number_format($cap, 0);
                                    }
                                ?></td>
                                <td><?php 
                                    if (!empty($stock['stock_count']) && $stock['stock_count'] > 0) {
                                        $count = (float)$stock['stock_count'];
                                        if ($count >= 1e16) {
                                            echo number_format($count / 1e16, 2) . '경';
                                        } elseif ($count >= 1e12) {
                                            echo number_format($count / 1e12, 2) . '조';
                                        } elseif ($count >= 1e8) {
                                            echo number_format($count / 1e8, 1) . '억';
                                        } elseif ($count >= 1e4) {
                                            echo number_format($count / 1e4, 1) . '만';
                                        } else {
                                            echo number_format($count);
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
            <?php
            $stockQuery = function($p) use ($currentMarket, $searchQuery) {
                $params = array_filter([
                    'page' => $p > 1 ? $p : null,
                    'market' => $currentMarket ?: null,
                    'search' => $searchQuery ?: null,
                ]);
                return $params ? '?' . http_build_query($params) : '';
            };
            $start = max(1, $currentPage - 4);
            $end = min($totalPages, $currentPage + 4);
            ?>
            <div class="pagination">
                <?php if ($currentPage > 1): ?>
                    <a href="<?= $stockQuery($currentPage - 1) ?>" class="page-link">←</a>
                <?php endif; ?>

                <?php if ($start > 1): ?>
                    <a href="<?= $stockQuery(1) ?>" class="page-link">1</a>
                    <?php if ($start > 2): ?><span class="page-ellipsis">…</span><?php endif; ?>
                <?php endif; ?>

                <?php for ($i = $start; $i <= $end; $i++): ?>
                    <?php if ($i === $currentPage): ?>
                        <span class="page-link page-current"><?= $i ?></span>
                    <?php else: ?>
                        <a href="<?= $stockQuery($i) ?>" class="page-link"><?= $i ?></a>
                    <?php endif; ?>
                <?php endfor; ?>

                <?php if ($end < $totalPages): ?>
                    <?php if ($end < $totalPages - 1): ?><span class="page-ellipsis">…</span><?php endif; ?>
                    <a href="<?= $stockQuery($totalPages) ?>" class="page-link"><?= $totalPages ?></a>
                <?php endif; ?>

                <?php if ($currentPage < $totalPages): ?>
                    <a href="<?= $stockQuery($currentPage + 1) ?>" class="page-link">→</a>
                <?php endif; ?>
            </div>
        <?php endif; ?>
    </div>
    
    <!-- 사이드바 -->
    <div class="stocks-sidebar-right">
        <div class="stocks-search-bar sidebar-search">
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

        <!-- 거래대금 TOP 10 -->
        <div class="top10-section">
            <h3>거래대금 TOP 10</h3>
            <div class="top10-list">
                <?php if (!empty($topStocks)): ?>
                    <?php foreach ($topStocks as $idx => $topStock): ?>
                        <div class="top10-item" onclick="location.href='/stocks/view?code=<?= urlencode($topStock['stock_code']) ?><?= ($topStock['stock_market'] === 'Bithumb') ? '&market=COIN' : '' ?>'">
                            <div class="top10-rank"><?= $idx + 1 ?></div>
                            <div class="top10-info">
                                <div class="top10-name"><?= $view->escape($topStock['stock_name_kr']) ?></div>
                                <div class="top10-code"><?= $view->escape($topStock['stock_code']) ?></div>
                            </div>
                            <div class="top10-value">
                                <?php
                                    $isUSMarket = in_array($topStock['stock_market'], ['NYSE', 'NASDAQ', 'AMEX']);
                                    $amount = (float)($topStock['total_amount'] ?? 0);
                                    if ($amount >= 1e20) {
                                        $amountStr = number_format($amount / 1e20, 1) . '해';
                                    } elseif ($amount >= 1e16) {
                                        $amountStr = number_format($amount / 1e16, 1) . '경';
                                    } elseif ($amount >= 1e12) {
                                        $amountStr = number_format($amount / 1e12, 1) . '조';
                                    } elseif ($amount >= 1e8) {
                                        $amountStr = number_format($amount / 1e8, 0) . '억';
                                    } elseif ($amount >= 1e4) {
                                        $amountStr = number_format($amount / 1e4, 0) . '만';
                                    } else {
                                        $amountStr = number_format($amount, 0);
                                    }
                                ?>
                                <div class="top10-primary"><?= $isUSMarket ? '$' : '' ?><?= number_format($topStock['stock_price'], $isUSMarket ? 2 : 0) ?><?= $isUSMarket ? '' : '원' ?></div>
                                <div class="top10-secondary"><?= $amountStr ?></div>
                            </div>
                        </div>
                    <?php endforeach; ?>
                <?php else: ?>
                    <div class="top10-empty">데이터가 없습니다.</div>
                <?php endif; ?>
            </div>
        </div>

        <!-- 포트폴리오 TOP 10 -->
        <div class="top10-section top10-section-sub">
            <h3>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>
                </svg>
                포트폴리오 TOP 10
            </h3>
            <div class="top10-list">
                <?php if (!empty($topPortfolios)): ?>
                    <?php foreach ($topPortfolios as $idx => $pf): ?>
                        <?php
                            $scoreClass = ($pf['ranking_score'] >= 70) ? 'score-high' : (($pf['ranking_score'] >= 40) ? 'score-mid' : 'score-low');
                            $strategyLabels = ['buyhold' => 'B&H', 'rebalance' => '리밸런싱', 'signal' => '시그널'];
                            $strategyLabel = $strategyLabels[$pf['strategy']] ?? $pf['strategy'];
                        ?>
                        <a href="/stocks/backtest?portfolio=<?= (int)$pf['portfolio_id'] ?>" class="top10-item">
                            <div class="top10-rank"><?= $idx + 1 ?></div>
                            <div class="top10-info">
                                <div class="top10-name"><?= $view->escape($pf['portfolio_name']) ?></div>
                            </div>
                            <div class="top10-value <?= $scoreClass ?>">
                                <div class="top10-primary"><?= (int)$pf['ranking_score'] ?></div>
                                <div class="top10-secondary"><?= $view->escape($pf['ranking_grade']) ?></div>
                            </div>
                        </a>
                    <?php endforeach; ?>
                <?php else: ?>
                    <div class="top10-empty">
                        <p>아직 등록된 포트폴리오가 없습니다.</p>
                        <a href="/stocks/backtest" class="top10-cta-link">백테스트 시작하기 →</a>
                    </div>
                <?php endif; ?>
            </div>
        </div>
    </div>
</div>

<script nonce="<?= $view->getNonce() ?>">
(function() {
    const params = new URLSearchParams(window.location.search);
    if (params.has('market')) {
        const m = params.get('market').toUpperCase();
        if (m === 'KR' || m === 'US' || m === 'COIN') {
            sessionStorage.setItem('stock_market_preference', m);
        }
    } else {
        sessionStorage.removeItem('stock_market_preference');
    }
})();

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
