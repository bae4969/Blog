<div class="stock-detail-container">
    <!-- 헤더: 주식 정보 -->
    <div class="stock-detail-header">
        <button class="back-btn" onclick="location.href='/stocks'">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M19 12H5M12 19l-7-7 7-7"/>
            </svg>
            목록으로
        </button>
        <div class="stock-title-section">
            <h2><?= $view->escape($stock['stock_name_kr']) ?></h2>
            <div class="stock-subtitle">
                <span class="stock-code"><?= $view->escape($stock['stock_code']) ?></span>
                <span class="market-badge"><?= $view->escape($stock['stock_market']) ?></span>
                <span class="type-badge type-<?= strtolower($stock['stock_type']) ?>"><?= $view->escape($stock['stock_type']) ?></span>
            </div>
        </div>
        <?php $isUSMarket = in_array($stock['stock_market'], ['NYSE', 'NASDAQ', 'AMEX']); ?>
        <div class="stock-price-section">
            <div class="current-price"><?= $isUSMarket ? '$' : '' ?><?= number_format($stock['stock_price'], $isUSMarket ? 2 : 0) ?><?= $isUSMarket ? '' : '<span class="currency">원</span>' ?></div>
            <div class="stock-meta">
                <span>시가총액: <?= $isUSMarket ? '$' : '' ?><?= number_format($stock['stock_capitalization'] / ($isUSMarket ? 1000000000 : 1000000000000), $isUSMarket ? 2 : 2) ?><?= $isUSMarket ? 'B' : '조원' ?></span>
                <span>상장주식수: <?php 
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
                                echo number_format($count / 100000000, 1) . '억주';
                            } elseif ($count >= 10000) {
                                echo number_format($count / 10000, 1) . '만주';
                            } else {
                                echo number_format($count) . '주';
                            }
                        }
                    } else {
                        echo '-';
                    }
                ?></span>
            </div>
        </div>
    </div>

    <!-- 메인 컨텐츠: 차트 + 체결 정보 -->
    <div class="stock-detail-main">
        <!-- 차트 영역 -->
        <div class="chart-section">
            <div class="chart-controls">
                <div class="chart-period-buttons">
                    <button class="period-btn" onclick="loadChartData('10M', this)">10분</button>
                    <button class="period-btn" onclick="loadChartData('30M', this)">30분</button>
                    <button class="period-btn" onclick="loadChartData('1H', this)">1시간</button>
                    <button class="period-btn" onclick="loadChartData('3H', this)">3시간</button>
                    <button class="period-btn" onclick="loadChartData('6H', this)">6시간</button>
                    <button class="period-btn" onclick="loadChartData('1D', this)">1일</button>
                    <button class="period-btn" onclick="loadChartData('1W', this)">1주</button>
                    <button class="period-btn active" onclick="loadChartData('1M', this)">1개월</button>
                    <button class="period-btn" onclick="loadChartData('3M', this)">3개월</button>
                    <button class="period-btn" onclick="loadChartData('1Y', this)">1년</button>
                </div>
                <div class="chart-type-buttons">
                    <button class="chart-type-btn active" onclick="setChartType('candle', this)">캔들</button>
                    <button class="chart-type-btn" onclick="setChartType('line', this)">라인</button>
                </div>
            </div>
            
            <div class="chart-wrapper">
                <canvas id="stockChart"></canvas>
                <?php if (empty($candleData)): ?>
                    <div class="chart-no-data">
                        <p>차트 데이터가 없습니다.</p>
                        <p class="chart-no-data-sub">해당 종목의 거래 데이터가 수집되지 않았습니다.</p>
                    </div>
                <?php endif; ?>
            </div>
        </div>

        <!-- 체결 정보 영역 -->
        <div class="execution-section">
            <h3>최근 체결</h3>
            <div class="execution-list">
                <div class="execution-header">
                    <div>시간</div>
                    <div>가격</div>
                    <div>수량</div>
                    <div>구분</div>
                </div>
                <div class="execution-body" id="executionList">
                    <?php if (empty($recentExecutions)): ?>
                        <div class="execution-no-data">체결 데이터가 없습니다.</div>
                    <?php else: ?>
                        <?php foreach ($recentExecutions as $exec): ?>
                            <?php
                            $isBuy = $exec['execution_bid_volume'] > $exec['execution_ask_volume'];
                            $volume = max($exec['execution_non_volume'], $exec['execution_bid_volume'], $exec['execution_ask_volume']);
                            ?>
                            <div class="execution-item <?= $isBuy ? 'buy' : 'sell' ?>">
                                <div class="exec-time"><?= date('H:i:s', strtotime($exec['execution_datetime'])) ?></div>
                                <div class="exec-price"><?= $isUSMarket ? '$' : '' ?><?= number_format($exec['execution_price'], $isUSMarket ? 2 : 0) ?></div>
                                <div class="exec-volume"><?= number_format($volume) ?></div>
                                <div class="exec-type"><?= $isBuy ? '매수' : '매도' ?></div>
                            </div>
                        <?php endforeach; ?>
                    <?php endif; ?>
                </div>
            </div>
            
            <button class="refresh-btn" onclick="refreshExecutions()">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"/>
                </svg>
                새로고침
            </button>
        </div>
    </div>

    <!-- 추가 정보 섹션 -->
    <div class="stock-info-section">
        <h3>종목 정보</h3>
        <div class="info-grid">
            <div class="info-item">
                <div class="info-label">종목명 (한글)</div>
                <div class="info-value"><?= $view->escape($stock['stock_name_kr']) ?></div>
            </div>
            <div class="info-item">
                <div class="info-label">종목명 (영문)</div>
                <div class="info-value"><?= $view->escape($stock['stock_name_en']) ?></div>
            </div>
            <div class="info-item">
                <div class="info-label">종목 코드</div>
                <div class="info-value"><?= $view->escape($stock['stock_code']) ?></div>
            </div>
            <div class="info-item">
                <div class="info-label">시장</div>
                <div class="info-value"><?= $view->escape($stock['stock_market']) ?></div>
            </div>
            <div class="info-item">
                <div class="info-label">종목 유형</div>
                <div class="info-value"><?= $view->escape($stock['stock_type']) ?></div>
            </div>
            <div class="info-item">
                <div class="info-label">현재가</div>
                <div class="info-value"><?= $isUSMarket ? '$' : '' ?><?= number_format($stock['stock_price'], $isUSMarket ? 2 : 0) ?><?= $isUSMarket ? '' : '원' ?></div>
            </div>
            <div class="info-item">
                <div class="info-label">시가총액</div>
                <div class="info-value"><?= $isUSMarket ? '$' : '' ?><?= number_format($stock['stock_capitalization'] / ($isUSMarket ? 1000000000 : 100000000), $isUSMarket ? 2 : 0) ?><?= $isUSMarket ? 'B' : '억원' ?></div>
            </div>
            <div class="info-item">
                <div class="info-label">상장주식수</div>
                <div class="info-value"><?php 
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
                                echo number_format($count / 100000000, 1) . '억주';
                            } elseif ($count >= 10000) {
                                echo number_format($count / 10000, 1) . '만주';
                            } else {
                                echo number_format($count) . '주';
                            }
                        }
                    } else {
                        echo '-';
                    }
                ?></div>
            </div>
            <div class="info-item">
                <div class="info-label">최종 업데이트</div>
                <div class="info-value"><?= date('Y-m-d H:i:s', strtotime($stock['stock_update'])) ?></div>
            </div>
        </div>
    </div>
</div>

<script>
// 차트 데이터를 JavaScript 변수로 전달
const stockCode = '<?= $view->escape($stock['stock_code']) ?>';
let candleData = <?= json_encode($candleData) ?>;
const recentExecutions = <?= json_encode($recentExecutions) ?>;
</script>
