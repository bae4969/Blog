<div class="stock-detail-container">
    <!-- 헤더: 주식 정보 -->
    <div class="stock-detail-header">
        <button class="btn btn-ghost" onclick="location.href='/stocks<?= !empty($isCoinMarket) ? '?market=COIN' : '' ?>'">
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
        <?php $isCoinType = (($stock['stock_type'] ?? '') === 'COIN'); ?>
        <div class="stock-price-section">
            <div class="current-price">
                <span id="currentPriceMainValue"><?= $isUSMarket ? '$' : '' ?><?= number_format($stock['stock_price'], $isUSMarket ? 2 : 0) ?></span><?= $isUSMarket ? '' : '<span class="currency">원</span>' ?>
            </div>
            <div class="stock-meta">
                <span>시가총액: <?php
                    $cap = (float)$stock['stock_capitalization'];
                    if ($isUSMarket) {
                        echo '$' . number_format($cap / 1e9, 2) . 'B';
                    } elseif ($cap >= 1e20) {
                        echo number_format($cap / 1e20, 2) . '해원';
                    } elseif ($cap >= 1e16) {
                        echo number_format($cap / 1e16, 2) . '경원';
                    } elseif ($cap >= 1e12) {
                        echo number_format($cap / 1e12, 2) . '조원';
                    } elseif ($cap >= 1e8) {
                        echo number_format($cap / 1e8, 0) . '억원';
                    } else {
                        echo number_format($cap, 0) . '원';
                    }
                ?></span>
                <span><?= $isCoinType ? '총 발행량' : '상장주식수' ?>: <?php 
                    if (!empty($stock['stock_count']) && $stock['stock_count'] > 0) {
                        $count = (float)$stock['stock_count'];
                        $suffix = $isCoinType ? '' : '주';
                        if ($count >= 1e16) {
                            echo number_format($count / 1e16, 2) . '경' . $suffix;
                        } elseif ($count >= 1e12) {
                            echo number_format($count / 1e12, 2) . '조' . $suffix;
                        } elseif ($count >= 1e8) {
                            echo number_format($count / 1e8, 1) . '억' . $suffix;
                        } elseif ($count >= 1e4) {
                            echo number_format($count / 1e4, 1) . '만' . $suffix;
                        } else {
                            echo number_format($count) . $suffix;
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
                <div class="chart-type-buttons">
                    <button class="chart-type-btn active" onclick="setChartType('candle', this)">캔들</button>
                    <button class="chart-type-btn" onclick="setChartType('line', this)">라인</button>
                </div>
                <div class="chart-period-select-wrapper">
                    <label for="periodSelect" class="period-label">기간</label>
                    <select id="periodSelect" class="period-select" onchange="loadChartData(this.value)">
                        <option value="10M">10M</option>
                        <option value="30M">30M</option>
                        <option value="1H">1H</option>
                        <option value="3H">3H</option>
                        <option value="6H">6H</option>
                        <option value="1D" selected>1D</option>
                        <option value="1W">1W</option>
                        <option value="1M">1M</option>
                    </select>
                </div>
            </div>
            
            <div class="chart-wrapper">
                <canvas id="stockChart"></canvas>
                <div id="chartLoading" class="chart-loading">
                    <div class="chart-loading-spinner"></div>
                    <p>차트 데이터를 불러오는 중...</p>
                </div>
                <div id="chartNoData" class="chart-no-data" style="display:none;">
                    <p>차트 데이터가 없습니다.</p>
                    <p class="chart-no-data-sub">해당 종목의 거래 데이터가 수집되지 않았습니다.</p>
                </div>
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
                    <div class="execution-loading">체결 데이터를 불러오는 중...</div>
                </div>
                <!-- 모바일: 축약 미리보기 하단 그라데이션 -->
                <div class="execution-fade-overlay"></div>
            </div>
            
            <button class="btn btn-primary" onclick="refreshExecutions()">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"/>
                </svg>
                새로고침
            </button>

            <!-- 모바일 전용: 자세히 보기 버튼 -->
            <button class="btn btn-ghost execution-mobile-trigger" onclick="openExecutionOverlay()">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/>
                </svg>
                자세히 보기
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
                <div class="info-value"><span id="currentPriceInfoValue"><?= $isUSMarket ? '$' : '' ?><?= number_format($stock['stock_price'], $isUSMarket ? 2 : 0) ?></span><?= $isUSMarket ? '' : '원' ?></div>
            </div>
            <div class="info-item">
                <div class="info-label">시가총액</div>
                <div class="info-value"><?php
                    $cap = (float)$stock['stock_capitalization'];
                    if ($isUSMarket) {
                        echo '$' . number_format($cap / 1e9, 2) . 'B';
                    } elseif ($cap >= 1e20) {
                        echo number_format($cap / 1e20, 2) . '해원';
                    } elseif ($cap >= 1e16) {
                        echo number_format($cap / 1e16, 2) . '경원';
                    } elseif ($cap >= 1e12) {
                        echo number_format($cap / 1e12, 2) . '조원';
                    } elseif ($cap >= 1e8) {
                        echo number_format($cap / 1e8, 0) . '억원';
                    } else {
                        echo number_format($cap, 0) . '원';
                    }
                ?></div>
            </div>
            <div class="info-item">
                <div class="info-label"><?= $isCoinType ? '총 발행량' : '상장주식수' ?></div>
                <div class="info-value"><?php 
                    if (!empty($stock['stock_count']) && $stock['stock_count'] > 0) {
                        $count = (float)$stock['stock_count'];
                        $suffix = $isCoinType ? '' : '주';
                        if ($count >= 1e16) {
                            echo number_format($count / 1e16, 2) . '경' . $suffix;
                        } elseif ($count >= 1e12) {
                            echo number_format($count / 1e12, 2) . '조' . $suffix;
                        } elseif ($count >= 1e8) {
                            echo number_format($count / 1e8, 1) . '억' . $suffix;
                        } elseif ($count >= 1e4) {
                            echo number_format($count / 1e4, 1) . '만' . $suffix;
                        } else {
                            echo number_format($count) . $suffix;
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

<!-- 모바일 체결내역 오버레이 -->
<div class="execution-overlay-backdrop" id="executionOverlayBackdrop" onclick="closeExecutionOverlay()"></div>
<div class="execution-overlay" id="executionOverlay">
    <div class="execution-overlay-handle"></div>
    <div class="execution-overlay-header">
        <h3>최근 체결</h3>
        <div class="execution-overlay-actions">
            <button class="btn btn-ghost btn-sm" onclick="refreshExecutions()">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"/>
                </svg>
            </button>
            <button class="btn btn-ghost btn-sm" onclick="closeExecutionOverlay()">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M18 6L6 18M6 6l12 12"/>
                </svg>
            </button>
        </div>
    </div>
    <div class="execution-overlay-content">
        <div class="execution-header">
            <div>시간</div>
            <div>가격</div>
            <div>수량</div>
            <div>구분</div>
        </div>
        <div class="execution-body" id="executionOverlayList">
            <div class="execution-loading">체결 데이터를 불러오는 중...</div>
        </div>
    </div>
</div>

<!-- 차트 라이브러리 프리로드 (페이지 렌더와 병렬 다운로드) -->
<script defer src="/vendor/chart.umd.min.js"></script>
<script defer src="/vendor/chartjs-chart-financial.min.js"></script>

<script>
// 차트 데이터를 JavaScript 변수로 전달
const stockCode = '<?= $view->escape($stock['stock_code']) ?>';
const isUSMarket = <?= $isUSMarket ? 'true' : 'false' ?>;
const isCoinMarket = <?= $isCoinType ? 'true' : 'false' ?>;
let candleData = [];
const recentExecutions = [];
</script>
