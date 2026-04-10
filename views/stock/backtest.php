<button class="btn btn-ghost stock-back-btn" onclick="location.href='/stocks'">
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M19 12H5M12 19l-7-7 7-7"/>
    </svg>
    목록으로
</button>
<h2 class="stock-detail-title">포트폴리오 백테스팅</h2>
<div class="backtest-container">
    <!-- 결과 패널 -->
    <div class="backtest-results" id="backtestResults">
        <!-- 진행률 -->
        <div id="backtestProgress" class="backtest-progress" style="display:none">
            <div class="progress-bar">
                <div class="progress-fill" id="progressFill"></div>

            </div>
            <span class="progress-text" id="progressText">데이터 로딩 중...</span>
        </div>

        <!-- 핵심 지표 카드 -->
        <div class="metrics-cards" id="metricsCards">
            <div class="metric-card">
                <span class="metric-info" tabindex="0">ⓘ<span class="metric-tooltip">(최종 가치 − 투자금) ÷ 투자금<br><br>참고 (10년 평균):<br>S&amp;P500 ~170%<br>나스닥100 ~350%<br>60/40 ~100%<br>올웨더 ~80%</span></span>
                <span class="metric-label">총 수익률</span>
                <span class="metric-value" id="metricTotalReturn">-</span>
                <span class="metric-bmk" id="bmkTotalReturn"></span>
            </div>
            <div class="metric-card">
                <span class="metric-info" tabindex="0">ⓘ<span class="metric-tooltip">연도별 수익률의 산술 평균<br><br>참고 (장기 평균):<br>S&amp;P500 ~12%<br>나스닥100 ~18%<br>60/40 ~9%<br>올웨더 ~8%</span></span>
                <span class="metric-label">연간수익률 평균</span>
                <span class="metric-value" id="metricAvgAnnual">-</span>
                <span class="metric-bmk" id="bmkAvgAnnual"></span>
            </div>
            <div class="metric-card">
                <span class="metric-info" tabindex="0">ⓘ<span class="metric-tooltip">연평균 복합 성장률<br>매년 일정하게 성장한 가정치<br><br>참고 (장기 평균):<br>S&amp;P500 ~10%<br>나스닥100 ~16%<br>60/40 ~8%<br>올웨더 ~7%</span></span>
                <span class="metric-label">CAGR</span>
                <span class="metric-value" id="metricCAGR">-</span>
                <span class="metric-bmk" id="bmkCAGR"></span>
            </div>
            <div class="metric-card">
                <span class="metric-info" tabindex="0">ⓘ<span class="metric-tooltip">고점 대비 최대 하락 폭<br><br>참고:<br>S&amp;P500 ~-33%<br>나스닥100 ~-49%<br>60/40 ~-22%<br>올웨더 ~-12%</span></span>
                <span class="metric-label">MDD</span>
                <span class="metric-value" id="metricMDD">-</span>
                <span class="metric-bmk" id="bmkMDD"></span>
            </div>
            <div class="metric-card">
                <span class="metric-info" tabindex="0">ⓘ<span class="metric-tooltip">위험 대비 초과 수익<br>1↑ 양호 / 2↑ 우수<br><br>참고:<br>S&amp;P500 ~0.8<br>나스닥100 ~0.7<br>60/40 ~0.8<br>올웨더 ~1.0</span></span>
                <span class="metric-label">샤프 비율</span>
                <span class="metric-value" id="metricSharpe">-</span>
                <span class="metric-bmk" id="bmkSharpe"></span>
            </div>
            <div class="metric-card">
                <span class="metric-info" tabindex="0">ⓘ<span class="metric-tooltip">하락 변동성만 고려한 초과 수익<br>높을수록 수익이 비대칭적 우세<br><br>참고:<br>S&amp;P500 ~1.0<br>나스닥100 ~0.9<br>60/40 ~1.0<br>올웨더 ~1.2</span></span>
                <span class="metric-label">소르티노 비율</span>
                <span class="metric-value" id="metricSortino">-</span>
                <span class="metric-bmk" id="bmkSortino"></span>
            </div>
        </div>

        <!-- 누적 수익률 차트 -->
        <div class="backtest-chart-section">
            <h3 class="result-section-title">누적 수익률</h3>
            <div class="backtest-chart-wrapper">
                <canvas id="backtestChart"></canvas>
            </div>
        </div>

        <!-- 연도별 수익률 -->
        <div class="annual-returns-section">
            <h3 class="result-section-title">연도별 수익률</h3>
            <div class="table-responsive">
                <table class="annual-returns-table" id="annualReturnsTable">
                    <thead>
                        <tr>
                            <th>연도</th>
                            <th>수익률</th>
                            <th>연초 가치</th>
                            <th>연말 가치</th>
                            <th>MDD</th>
                        </tr>
                    </thead>
                    <tbody></tbody>
                </table>
            </div>
        </div>

        <!-- 거래 요약 -->
        <div class="trade-summary-section">
            <h3 class="result-section-title">거래 요약</h3>
            <div class="trade-summary-grid" id="tradeSummary">
                <div class="trade-stat">
                    <span class="trade-stat-label">총 거래 횟수</span>
                    <span class="trade-stat-value" id="tradeTotalCount">-</span>
                </div>
                <div class="trade-stat">
                    <span class="trade-stat-label">매수 횟수</span>
                    <span class="trade-stat-value" id="tradeBuyCount">-</span>
                </div>
                <div class="trade-stat">
                    <span class="trade-stat-label">매도 횟수</span>
                    <span class="trade-stat-value" id="tradeSellCount">-</span>
                </div>
                <div class="trade-stat">
                    <span class="trade-stat-label">총 투자금</span>
                    <span class="trade-stat-value" id="tradeTotalInvested">-</span>
                </div>
                <div class="trade-stat">
                    <span class="trade-stat-label">총 수수료</span>
                    <span class="trade-stat-value" id="metricTotalFees">-</span>
                </div>
            </div>
        </div>
    </div>

    <!-- 설정 패널 -->
    <div class="backtest-config">

        <!-- 종목 선택 (포트폴리오 + 벤치마크 통합) -->
        <div class="config-section">
            <h3 class="config-section-title">종목 구성</h3>
            <div class="stock-picker">
                <div class="stock-search-row">
                    <input type="text" id="stockSearchInput" class="backtest-input" placeholder="종목명 또는 코드 검색..." autocomplete="off">
                    <div id="stockSearchResults" class="stock-search-dropdown"></div>
                </div>
                <h4 class="picker-sub-title">포트폴리오 <span class="picker-sub-hint">(최대 10개)</span></h4>
                <div id="selectedStocks" class="selected-stocks-list">
                    <p class="empty-hint">검색 결과에서 [+ 포트폴리오] 버튼을 눌러 추가하세요</p>
                </div>
                <hr class="picker-divider">
                <h4 class="picker-sub-title">벤치마크 <span class="picker-sub-hint">(선택, 최대 5개)</span></h4>
                <div id="selectedBenchmark" class="selected-benchmark"></div>
            </div>
        </div>

        <!-- 적립식(DCA) 설정 -->
        <div class="config-section">
            <h3 class="config-section-title">투자 설정</h3>
            <div class="config-grid">
                <div class="config-field">
                    <label class="config-label" for="initialCapital">초기 투자금</label>
                    <div class="input-with-unit">
                        <input type="number" id="initialCapital" class="backtest-input" value="1000" min="0" step="100">
                        <span class="input-unit">만원</span>
                    </div>
                </div>
                <div class="config-field">
                    <label class="config-label" for="monthlyDCA">월 적립금</label>
                    <div class="input-with-unit">
                        <input type="number" id="monthlyDCA" class="backtest-input" value="100" min="0" step="10">
                        <span class="input-unit">만원</span>
                    </div>
                </div>
            </div>
            <div class="config-grid" style="margin-top:8px">
                <div class="config-field">
                    <label class="config-label" for="startDate">시작일</label>
                    <input type="date" id="startDate" class="backtest-input" value="2024-06-01">
                </div>
                <div class="config-field">
                    <label class="config-label" for="endDate">종료일</label>
                    <input type="date" id="endDate" class="backtest-input">
                </div>
            </div>
        </div>

        <!-- 전략 선택 -->
        <div class="config-section">
            <h3 class="config-section-title">전략</h3>
            <div class="strategy-tabs">
                <button class="strategy-tab active" data-strategy="buyhold">Buy &amp; Hold</button>
                <button class="strategy-tab" data-strategy="rebalance">정기 리밸런싱</button>
                <button class="strategy-tab" data-strategy="signal">시그널 기반</button>
            </div>

            <!-- 리밸런싱 설정 -->
            <div id="rebalanceConfig" class="strategy-detail" style="display:none">
                <label class="config-label">리밸런싱 주기</label>
                <select id="rebalancePeriod" class="backtest-select">
                    <option value="monthly">월간</option>
                    <option value="quarterly" selected>분기</option>
                    <option value="semiannual">반기</option>
                    <option value="annual">연간</option>
                </select>
            </div>

            <!-- 시그널 기반 설정 -->
            <div id="signalConfig" class="strategy-detail" style="display:none">
                <div class="signal-rules" id="signalRules">
                    <!-- 동적으로 추가 -->
                </div>
                <button type="button" class="btn btn-sm btn-outline" id="addSignalRule">+ 규칙 추가</button>
                <div class="signal-combine">
                    <label class="config-label">조건 결합</label>
                    <select id="signalCombine" class="backtest-select">
                        <option value="or">OR (하나라도 만족)</option>
                        <option value="and">AND (모두 만족)</option>
                    </select>
                </div>
            </div>

            <!-- DCA 유예 조건 -->
            <div class="config-field" style="margin-top:10px">
                <label class="config-label" for="dcaDeferIndicator">적립 유예 조건</label>
                <select id="dcaDeferIndicator" class="backtest-select">
                    <option value="none">사용 안 함</option>
                    <option value="macd_death">MACD 데스크로스 시 유예</option>
                    <option value="rsi_overbought">RSI 과매수 시 유예</option>
                    <option value="bb_upper">BB 상단 돌파 시 유예</option>
                    <option value="sma_death">SMA 데스크로스 시 유예</option>
                </select>
                <p class="config-hint" id="dcaDeferHint">매월 적립금을 즉시 투입합니다.</p>
            </div>
        </div>

        <!-- 고급 설정 -->
        <div class="config-section">
            <details class="advanced-settings">
                <summary class="config-section-title clickable">고급 설정</summary>
                <div style="margin-top:8px">
                    <h4 class="config-subsection-title">수수료</h4>
                    <div class="config-grid config-grid-3">
                        <div class="config-field">
                            <label class="config-label" for="feeKR">KR</label>
                            <div class="input-with-unit">
                                <input type="number" id="feeKR" class="backtest-input" value="0.015" min="0" max="10" step="0.001">
                                <span class="input-unit">%</span>
                            </div>
                        </div>
                        <div class="config-field">
                            <label class="config-label" for="feeUS">US</label>
                            <div class="input-with-unit">
                                <input type="number" id="feeUS" class="backtest-input" value="0.2" min="0" max="10" step="0.001">
                                <span class="input-unit">%</span>
                            </div>
                        </div>
                        <div class="config-field">
                            <label class="config-label" for="feeCOIN">COIN</label>
                            <div class="input-with-unit">
                                <input type="number" id="feeCOIN" class="backtest-input" value="0.015" min="0" max="10" step="0.001">
                                <span class="input-unit">%</span>
                            </div>
                        </div>
                    </div>
                    <div class="config-grid" style="margin-top:8px">
                        <div class="config-field">
                            <label class="config-label" for="riskFreeRate">무위험 수익률 (연)</label>
                            <div class="input-with-unit">
                                <input type="number" id="riskFreeRate" class="backtest-input" value="3.0" min="0" max="20" step="0.1">
                                <span class="input-unit">%</span>
                            </div>
                        </div>
                    </div>
                </div>
            </details>
        </div>

        <!-- 설정 저장/불러오기 -->
        <div class="config-section config-save-section">
            <div class="config-save-row">
                <button type="button" class="btn btn-sm btn-outline" id="saveConfig" title="현재 설정 저장">💾 설정 저장</button>
                <button type="button" class="btn btn-sm btn-outline" id="loadConfig" title="저장된 설정 불러오기">📂 불러오기</button>
                <button type="button" class="btn btn-sm btn-outline" id="clearConfig" title="저장된 설정 삭제">🗑 초기화</button>
                <span class="config-save-status" id="saveStatus"></span>
            </div>
        </div>

        <!-- 실행 버튼 -->
        <button type="button" id="runBacktest" class="btn btn-primary btn-lg btn-block">
            백테스트 실행
        </button>
    </div>
</div>

<!-- 시그널 규칙 템플릿 -->
<template id="signalRuleTemplate">
    <div class="signal-rule">
        <select class="backtest-select signal-indicator" name="indicator">
            <option value="bb_lower">BB 하단 돌파 → 매수</option>
            <option value="bb_upper">BB 상단 돌파 → 매도</option>
            <option value="macd_golden">MACD 골든크로스 → 매수</option>
            <option value="macd_death">MACD 데스크로스 → 매도</option>
            <option value="rsi_oversold">RSI 과매도 (< 30) → 매수</option>
            <option value="rsi_overbought">RSI 과매수 (> 70) → 매도</option>
            <option value="sma_golden">SMA 골든크로스 → 매수</option>
            <option value="sma_death">SMA 데스크로스 → 매도</option>
        </select>
        <select class="backtest-select signal-target" name="target">
            <!-- 동적 옵션: 포트폴리오 종목 목록 -->
        </select>
        <button type="button" class="btn btn-sm btn-danger signal-remove" title="삭제">&times;</button>
    </div>
</template>

<script nonce="<?= $view->getNonce() ?>">
    // 페이지 초기화 시 오늘 날짜를 종료일 기본값으로 설정
    document.getElementById('endDate').value = new Date().toISOString().split('T')[0];
</script>