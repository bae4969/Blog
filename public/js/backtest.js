/**
 * 포트폴리오 백테스팅 시뮬레이터
 * - 연산은 서버(PHP BacktestService)에서 수행
 * - 클라이언트는 UI 제어, API 호출, 결과 렌더링만 담당
 */
(function () {
    'use strict';

    /* =========================================
       상수 & 상태
       ========================================= */
    var MAX_STOCKS = 10;
    var MAX_BENCHMARKS = 5;
    var portfolio = [];    // [{ code, name, market, weight }]
    var benchmarks = [];   // [{ code, name, market }]
    var backtestChart = null;
    var hasRunOnce = false;
    var autoRecalcTimer = null;
    var dateRangeTimer = null;

    // 벤치마크 차트 색상 팔레트
    var BMK_COLORS = [
        'rgb(249, 115, 22)',
        'rgb(168, 85, 247)',
        'rgb(34, 197, 94)',
        'rgb(236, 72, 153)',
        'rgb(6, 182, 212)'
    ];

    // 마지막으로 성공한 요청의 config 키 (debounce용)
    var lastRunKey = null;

    /**
     * 포트폴리오+벤치마크 종목의 공통 날짜 범위를 조회하여 date picker 제한 적용
     */
    function updateDateRange() {
        clearTimeout(dateRangeTimer);
        dateRangeTimer = setTimeout(function () {
            var allStocks = portfolio.concat(benchmarks);
            var startEl = document.getElementById('startDate');
            var endEl = document.getElementById('endDate');
            if (!startEl || !endEl) return;

            if (allStocks.length === 0) {
                startEl.removeAttribute('min');
                startEl.removeAttribute('max');
                endEl.removeAttribute('min');
                endEl.removeAttribute('max');
                return;
            }

            var codes = allStocks.map(function (s) { return s.code; }).join(',');
            var markets = allStocks.map(function (s) { return s.market || ''; }).join(',');

            fetch('/stocks/api/date-range?codes=' + encodeURIComponent(codes) + '&markets=' + encodeURIComponent(markets), {
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            })
                .then(function (r) { return r.json(); })
                .then(function (json) {
                    if (json.success && json.data) {
                        startEl.setAttribute('min', json.data.min);
                        startEl.setAttribute('max', json.data.max);
                        endEl.setAttribute('min', json.data.min);
                        endEl.setAttribute('max', json.data.max);
                        if (startEl.value && startEl.value < json.data.min) startEl.value = json.data.min;
                        if (startEl.value && startEl.value > json.data.max) startEl.value = json.data.max;
                        if (endEl.value && endEl.value < json.data.min) endEl.value = json.data.min;
                        if (endEl.value && endEl.value > json.data.max) endEl.value = json.data.max;
                    } else {
                        startEl.removeAttribute('min');
                        startEl.removeAttribute('max');
                        endEl.removeAttribute('min');
                        endEl.removeAttribute('max');
                    }
                })
                .catch(function () { /* 무시 */ });
        }, 300);
    }

    /**
     * 실행 버튼 상태 업데이트
     */
    function updateRunButtonState() {
        var btn = document.getElementById('runBacktest');
        if (!btn || btn.disabled) return;

        if (!hasRunOnce) {
            btn.textContent = '백테스트 실행';
            btn.className = 'btn btn-primary btn-lg btn-block';
            return;
        }
        var currentKey = JSON.stringify(collectConfig());
        if (currentKey === lastRunKey) {
            btn.textContent = '재계산';
            btn.className = 'btn btn-primary btn-lg btn-block btn-recalc';
        } else {
            btn.textContent = '백테스트 실행';
            btn.className = 'btn btn-primary btn-lg btn-block btn-refetch';
        }
    }

    /* =========================================
       유틸리티
       ========================================= */
    function escapeHtml(str) {
        if (str === null || str === undefined) return '';
        return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');
    }

    function formatNumber(n, decimals) {
        if (decimals === undefined) decimals = 0;
        if (n === null || n === undefined || isNaN(n)) return '-';
        return Number(n).toLocaleString('ko-KR', {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals
        });
    }

    function formatPercent(n, decimals) {
        if (decimals === undefined) decimals = 2;
        if (n === null || n === undefined || isNaN(n)) return '-';
        var sign = n >= 0 ? '+' : '';
        return sign + n.toFixed(decimals) + '%';
    }

    function formatCurrency(n) {
        if (n === null || n === undefined || isNaN(n)) return '-';
        if (Math.abs(n) >= 1e8) return formatNumber(n / 1e8, 1) + '억원';
        if (Math.abs(n) >= 1e4) return formatNumber(n / 1e4, 0) + '만원';
        return formatNumber(n, 0) + '원';
    }

    /**
     * 메트릭들을 종합하여 0 – 100 총 점수를 산출한다.
     * 각 지표를 합리적 범위에서 0-100 으로 정규화한 뒤 가중 합산.
     *
     * 정규화 범위 (min→0점, max→100점):
     *   CAGR        : -5 % ~ 20 %
     *   연간수익률    : -5 % ~ 25 %
     *   총 수익률     : -30 % ~ 300 %
     *   MDD (역전)   : 60 % ~ 5 %  (낮을수록 좋음)
     *   샤프 비율     : -0.5 ~ 2.5
     *   소르티노 비율  : -0.5 ~ 3.0
     *
     * 가중치: CAGR 20, avgAnnual 10, totalReturn 10, MDD 20, Sharpe 20, Sortino 20
     */
    function calculateTotalScore(metrics) {
        function normalize(value, minVal, maxVal) {
            if (value === null || value === undefined || !isFinite(value)) return 50;
            var score = (value - minVal) / (maxVal - minVal) * 100;
            return Math.max(0, Math.min(100, score));
        }

        var scores = {
            cagr:        normalize(metrics.cagr, -5, 20),
            avgAnnual:   normalize(metrics.avgAnnual, -5, 25),
            totalReturn: normalize(metrics.totalReturn, -30, 300),
            mdd:         normalize(metrics.mdd, 60, 5),   // 역전: 60→0점, 5→100점
            sharpe:      normalize(metrics.sharpe, -0.5, 2.5),
            sortino:     normalize(metrics.sortino, -0.5, 3.0)
        };

        var weights = {
            cagr: 20, avgAnnual: 10, totalReturn: 10,
            mdd: 20, sharpe: 20, sortino: 20
        };
        var totalWeight = 0;
        var weightedSum = 0;
        for (var key in weights) {
            weightedSum += scores[key] * weights[key];
            totalWeight += weights[key];
        }

        var total = Math.round(weightedSum / totalWeight);
        var grade;
        if (total >= 90)      grade = 'A+';
        else if (total >= 80) grade = 'A';
        else if (total >= 70) grade = 'B+';
        else if (total >= 60) grade = 'B';
        else if (total >= 50) grade = 'C+';
        else if (total >= 40) grade = 'C';
        else if (total >= 30) grade = 'D';
        else                  grade = 'F';

        return { total: total, grade: grade, scores: scores };
    }

    /* =========================================
       차트 렌더러
       ========================================= */
    function renderChart(series, benchmarkSeries) {
        var ctx = document.getElementById('backtestChart');
        if (!ctx) return;

        if (backtestChart) {
            backtestChart.destroy();
            backtestChart = null;
        }

        var labels = series.map(function (d) { return d.date; });
        // TWR 기반 누적 수익률
        var portfolioReturns = [];
        var twrCum = 1;
        portfolioReturns.push(0);
        for (var i = 1; i < series.length; i++) {
            var prevVal = series[i - 1].value;
            var cashFlow = series[i].invested - series[i - 1].invested;
            var base = prevVal + cashFlow;
            if (base > 0) {
                twrCum *= (series[i].value / base);
            }
            portfolioReturns.push((twrCum - 1) * 100);
        }
        var investedLine = series.map(function () { return 0; });

        var datasets = [
            {
                label: '포트폴리오',
                data: portfolioReturns,
                borderColor: 'rgb(59, 130, 246)',
                backgroundColor: 'rgba(59, 130, 246, 0.1)',
                borderWidth: 2,
                pointRadius: 0,
                fill: true,
                tension: 0.1
            },
            {
                label: '',
                data: investedLine,
                borderColor: 'rgba(150, 150, 150, 0.5)',
                borderWidth: 1,
                borderDash: [5, 5],
                pointRadius: 0,
                fill: false,
                hidden: false
            }
        ];

        if (benchmarkSeries && benchmarkSeries.length > 0) {
            benchmarkSeries.forEach(function (bmkItem) {
                if (!bmkItem.chartData) return;
                var bmkMap = {};
                bmkItem.chartData.forEach(function (d) { bmkMap[d.date] = d.returnPct; });
                var lastBmkVal = 0;
                var bmkReturns = labels.map(function (d) {
                    if (bmkMap[d] !== undefined) lastBmkVal = bmkMap[d];
                    return lastBmkVal;
                });
                var color = bmkItem.color;
                datasets.push({
                    label: bmkItem.name,
                    data: bmkReturns,
                    borderColor: color,
                    backgroundColor: color.replace('rgb', 'rgba').replace(')', ', 0.05)'),
                    borderWidth: 2,
                    borderDash: [4, 4],
                    pointRadius: 0,
                    fill: false,
                    tension: 0.1
                });
            });
        }

        var rootStyle = getComputedStyle(document.documentElement);
        var textColor = rootStyle.getPropertyValue('--text-secondary').trim() || '#888';
        var gridColor = rootStyle.getPropertyValue('--border-color').trim() || '#333';

        backtestChart = new Chart(ctx, {
            type: 'line',
            data: { labels: labels, datasets: datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: 'index',
                    intersect: false
                },
                plugins: {
                    legend: {
                        display: true,
                        labels: {
                            color: textColor,
                            filter: function (item) { return item.text !== ''; }
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: function (ctx) {
                                if (!ctx.dataset.label) return null;
                                return ctx.dataset.label + ': ' + formatPercent(ctx.parsed.y);
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        ticks: {
                            color: textColor,
                            maxTicksLimit: 12,
                            maxRotation: 0
                        },
                        grid: { color: gridColor }
                    },
                    y: {
                        ticks: {
                            color: textColor,
                            callback: function (v) { return v.toFixed(1) + '%'; }
                        },
                        grid: { color: gridColor }
                    }
                }
            }
        });
    }

    /* =========================================
       UI 컨트롤러
       ========================================= */

    // 종목 검색 — 자동완성
    function initStockSearch(inputId, resultsId, onAddPortfolio, onAddBenchmark) {
        var input = document.getElementById(inputId);
        var resultsDiv = document.getElementById(resultsId);
        if (!input || !resultsDiv) return;
        var debounce = null;

        input.addEventListener('input', function () {
            clearTimeout(debounce);
            var q = input.value.trim();
            if (q.length < 1) { resultsDiv.style.display = 'none'; return; }
            debounce = setTimeout(function () {
                fetch('/stocks/api/search?q=' + encodeURIComponent(q) + '&limit=10', {
                    headers: { 'X-Requested-With': 'XMLHttpRequest' }
                })
                    .then(function (r) { return r.json(); })
                    .then(function (json) {
                        if (!json.success || !json.data || json.data.length === 0) {
                            resultsDiv.innerHTML = '<div class="search-empty">검색 결과 없음</div>';
                            resultsDiv.style.display = 'block';
                            return;
                        }
                        var html = '';
                        json.data.forEach(function (s) {
                            var market = s.stock_type === 'COIN' ? 'COIN' : (
                                ['NYSE', 'NASDAQ', 'AMEX'].indexOf(s.stock_market) >= 0 ? 'US' : 'KR'
                            );
                            html += '<div class="search-result-item" data-code="' + escapeHtml(s.stock_code) +
                                '" data-name="' + escapeHtml(s.stock_name_kr || s.stock_code) +
                                '" data-market="' + escapeHtml(market) + '">' +
                                '<span class="sr-name">' + escapeHtml(s.stock_name_kr || s.stock_code) + '</span>' +
                                '<span class="sr-code">' + escapeHtml(s.stock_code) + '</span>' +
                                '<span class="sr-market badge-' + escapeHtml(market.toLowerCase()) + '">' + escapeHtml(market) + '</span>' +
                                '<span class="sr-actions">' +
                                '<button type="button" class="sr-add-btn sr-add-portfolio" title="포트폴리오에 추가">+ 포폴</button>' +
                                '<button type="button" class="sr-add-btn sr-add-benchmark" title="벤치마크에 추가">+ 벤치</button>' +
                                '</span>' +
                                '</div>';
                        });
                        resultsDiv.innerHTML = html;
                        resultsDiv.style.display = 'block';

                        resultsDiv.querySelectorAll('.search-result-item').forEach(function (item) {
                            var stock = {
                                code: item.dataset.code,
                                name: item.dataset.name,
                                market: item.dataset.market
                            };
                            item.querySelector('.sr-add-portfolio').addEventListener('click', function (e) {
                                e.stopPropagation();
                                onAddPortfolio(stock);
                                resultsDiv.style.display = 'none';
                            });
                            item.querySelector('.sr-add-benchmark').addEventListener('click', function (e) {
                                e.stopPropagation();
                                onAddBenchmark(stock);
                                resultsDiv.style.display = 'none';
                            });
                        });
                    });
            }, 300);
        });

        document.addEventListener('click', function (e) {
            if (!input.contains(e.target) && !resultsDiv.contains(e.target)) {
                resultsDiv.style.display = 'none';
            }
        });
    }

    // 포트폴리오 종목 렌더링
    function renderPortfolio() {
        var container = document.getElementById('selectedStocks');
        if (!container) return;
        if (portfolio.length === 0) {
            container.innerHTML = '<p class="empty-hint">검색 결과에서 [+ 포트폴리오] 버튼을 눌러 추가하세요</p>';
            return;
        }
        var totalWeight = portfolio.reduce(function (a, b) { return a + b.weight; }, 0);
        var weightOk = Math.abs(totalWeight - 100) <= 0.01;
        var eqBtnHeader = document.getElementById('equalizeWeights');
        if (eqBtnHeader) eqBtnHeader.style.display = portfolio.length > 0 ? '' : 'none';
        var html = '';
        portfolio.forEach(function (s, idx) {
            html += '<div class="portfolio-stock-item">' +
                '<span class="ps-name">' + escapeHtml(s.name) + '</span>' +
                '<span class="ps-code">' + escapeHtml(s.code) + '</span>' +
                '<span class="ps-market badge-' + escapeHtml(s.market.toLowerCase()) + '">' + escapeHtml(s.market) + '</span>' +
                '<div class="ps-weight-wrap">' +
                '<input type="number" class="backtest-input ps-weight" data-idx="' + idx + '" value="' + s.weight + '" min="0" max="100" step="1">' +
                '<span class="input-unit">%</span>' +
                '</div>' +
                '<button type="button" class="btn btn-sm btn-danger picker-remove" data-idx="' + idx + '">&times;</button>' +
                '</div>';
        });
        html += '<div class="portfolio-weight-total">' +
            '<span class="weight-total-text' + (weightOk ? '' : ' weight-warning') + '">합계: ' + totalWeight.toFixed(1) + '% ' + (weightOk ? '✓' : '✗') + '</span>' +
            '</div>';
        container.innerHTML = html;

        container.querySelectorAll('.ps-weight').forEach(function (inp) {
            inp.addEventListener('change', function () {
                var idx = parseInt(this.dataset.idx);
                portfolio[idx].weight = parseFloat(this.value) || 0;
                renderPortfolio();
                updateSignalTargets();
                scheduleAutoRecalc();
            });
        });
        container.querySelectorAll('.picker-remove').forEach(function (btn) {
            btn.addEventListener('click', function () {
                portfolio.splice(parseInt(this.dataset.idx), 1);
                renderPortfolio();
                updateSignalTargets();
                updateRunButtonState();
                updateDateRange();
            });
        });
        if (eqBtnHeader && !eqBtnHeader._bound) {
            eqBtnHeader._bound = true;
            eqBtnHeader.addEventListener('click', function () {
                var n = portfolio.length;
                var base = Math.floor(10000 / n);
                var remainder = 10000 - base * n;
                portfolio.forEach(function (s, i) {
                    s.weight = (base + (i < remainder ? 1 : 0)) / 100;
                });
                renderPortfolio();
            });
        }
    }

    // 시그널 타겟 옵션 업데이트
    function updateSignalTargets() {
        document.querySelectorAll('.signal-target').forEach(function (sel) {
            var currentVal = sel.value;
            sel.innerHTML = '';
            portfolio.forEach(function (s) {
                var opt = document.createElement('option');
                opt.value = s.code;
                opt.textContent = s.name + ' (' + s.code + ')';
                sel.appendChild(opt);
            });
            if (currentVal) sel.value = currentVal;
        });
    }

    // 시그널 규칙 추가
    function addSignalRule() {
        var container = document.getElementById('signalRules');
        var template = document.getElementById('signalRuleTemplate');
        if (!container || !template) return;
        var clone = template.content.cloneNode(true);
        container.appendChild(clone);
        updateSignalTargets();
        var rules = container.querySelectorAll('.signal-rule');
        var lastRule = rules[rules.length - 1];
        lastRule.querySelector('.signal-indicator').addEventListener('change', scheduleAutoRecalc);
        lastRule.querySelector('.signal-target').addEventListener('change', scheduleAutoRecalc);
        container.querySelectorAll('.signal-remove').forEach(function (btn) {
            btn.onclick = function () { btn.closest('.signal-rule').remove(); scheduleAutoRecalc(); };
        });
    }

    // 전략 탭 전환
    function initStrategyTabs() {
        document.querySelectorAll('.strategy-tab').forEach(function (tab) {
            tab.addEventListener('click', function () {
                document.querySelectorAll('.strategy-tab').forEach(function (t) { t.classList.remove('active'); });
                tab.classList.add('active');
                var strategy = tab.dataset.strategy;
                document.getElementById('rebalanceConfig').style.display = strategy === 'rebalance' ? '' : 'none';
                document.getElementById('signalConfig').style.display = strategy === 'signal' ? '' : 'none';
                scheduleAutoRecalc();
            });
        });
    }

    // DCA 유예 힌트 업데이트
    var DCA_DEFER_HINTS = {
        none: '매월 적립금을 즉시 투입합니다.',
        macd_death: 'MACD 단기선이 장기선 아래로 교차(데드크로스)하면 해당 종목의 적립을 유예합니다.',
        rsi_overbought: 'RSI가 70 이상(과매수 구간)이면 해당 종목의 적립을 유예합니다.',
        bb_upper: '가격이 볼린저 밴드 상단을 돌파하면 해당 종목의 적립을 유예합니다.',
        sma_death: '단기 SMA가 장기 SMA 아래로 교차(데드크로스)하면 해당 종목의 적립을 유예합니다.'
    };

    function updateDcaDeferHint() {
        var sel = document.getElementById('dcaDeferIndicator');
        var hint = document.getElementById('dcaDeferHint');
        if (!sel || !hint) return;
        hint.textContent = DCA_DEFER_HINTS[sel.value] || '';
    }

    // 벤치마크 렌더링
    function renderBenchmark() {
        var container = document.getElementById('selectedBenchmark');
        if (!container) return;
        if (benchmarks.length === 0) { container.innerHTML = ''; return; }
        var html = '';
        benchmarks.forEach(function (b, idx) {
            var color = BMK_COLORS[idx % BMK_COLORS.length];
            html += '<div class="benchmark-item">' +
                '<span class="bmk-color-dot" style="background:' + color + '"></span>' +
                '<span class="ps-name">' + escapeHtml(b.name) + '</span>' +
                '<span class="ps-code">' + escapeHtml(b.code) + '</span>' +
                '<span class="ps-market badge-' + escapeHtml(b.market.toLowerCase()) + '">' + escapeHtml(b.market) + '</span>' +
                '<button type="button" class="btn btn-sm btn-danger picker-remove" data-idx="' + idx + '">&times;</button>' +
                '</div>';
        });
        container.innerHTML = html;
        container.querySelectorAll('.picker-remove').forEach(function (btn) {
            btn.addEventListener('click', function () {
                benchmarks.splice(parseInt(this.dataset.idx), 1);
                renderBenchmark();
                updateRunButtonState();
                updateDateRange();
            });
        });
    }

    // 결과 표시
    function displayResults(data) {
        var panel = document.getElementById('backtestResults');
        panel.style.display = '';

        var metrics = data.metrics;
        var bmkResults = data.benchmarks || [];

        // 지표 카드
        document.getElementById('metricTotalReturn').textContent = formatPercent(metrics.totalReturn);
        document.getElementById('metricTotalReturn').className = 'metric-value ' + (metrics.totalReturn >= 0 ? 'positive' : 'negative');
        document.getElementById('metricAvgAnnual').textContent = formatPercent(metrics.avgAnnual);
        document.getElementById('metricAvgAnnual').className = 'metric-value ' + (metrics.avgAnnual >= 0 ? 'positive' : 'negative');
        document.getElementById('metricCAGR').textContent = formatPercent(metrics.cagr);
        document.getElementById('metricCAGR').className = 'metric-value ' + (metrics.cagr >= 0 ? 'positive' : 'negative');
        document.getElementById('metricMDD').textContent = formatPercent(-metrics.mdd);
        document.getElementById('metricMDD').className = 'metric-value negative';
        document.getElementById('metricSharpe').textContent = metrics.sharpe === null || !isFinite(metrics.sharpe) ? '∞' : metrics.sharpe.toFixed(2);
        document.getElementById('metricSortino').textContent = metrics.sortino === null || !isFinite(metrics.sortino) ? '∞' : metrics.sortino.toFixed(2);
        document.getElementById('metricTotalFees').textContent = formatCurrency(data.tradeSummary.totalFees);

        // 총 점수 계산 & 표시
        var scoreResult = calculateTotalScore(metrics);
        var scoreEl = document.getElementById('totalScoreValue');
        var gradeEl = document.getElementById('totalScoreGrade');
        var bmkScoreEl = document.getElementById('bmkTotalScore');
        if (scoreEl) {
            scoreEl.textContent = scoreResult.total;
            scoreEl.className = 'score-number';
            if (scoreResult.total >= 70) scoreEl.classList.add('score-high');
            else if (scoreResult.total >= 40) scoreEl.classList.add('score-mid');
            else scoreEl.classList.add('score-low');
        }
        if (gradeEl) {
            gradeEl.textContent = scoreResult.grade;
            gradeEl.className = 'score-grade';
            if (scoreResult.total >= 70) gradeEl.classList.add('score-high');
            else if (scoreResult.total >= 40) gradeEl.classList.add('score-mid');
            else gradeEl.classList.add('score-low');
        }
        // 세부 점수 바
        var breakdownLabels = {
            cagr: 'CAGR', avgAnnual: '연간수익률', totalReturn: '총수익률',
            mdd: 'MDD', sharpe: '샤프', sortino: '소르티노'
        };
        var breakdownEl = document.getElementById('scoreBreakdown');
        if (breakdownEl) {
            breakdownEl.innerHTML = '';
            for (var key in breakdownLabels) {
                var s = Math.round(scoreResult.scores[key]);
                var barClass = s >= 70 ? 'bar-high' : (s >= 40 ? 'bar-mid' : 'bar-low');
                breakdownEl.innerHTML +=
                    '<div class="score-bar-row">' +
                    '<span class="score-bar-label">' + breakdownLabels[key] + '</span>' +
                    '<div class="score-bar-track"><div class="score-bar-fill ' + barClass + '" style="width:' + s + '%"></div></div>' +
                    '<span class="score-bar-value">' + s + '</span>' +
                    '</div>';
            }
        }

        // 벤치마크 지표
        var bmkMetricIds = ['bmkTotalReturn', 'bmkAvgAnnual', 'bmkCAGR', 'bmkMDD', 'bmkSharpe', 'bmkSortino'];
        bmkMetricIds.forEach(function (id) {
            var el = document.getElementById(id);
            if (el) { el.innerHTML = ''; el.classList.remove('visible'); }
        });
        if (bmkScoreEl) { bmkScoreEl.innerHTML = ''; bmkScoreEl.classList.remove('visible'); }
        if (bmkResults.length > 0) {
            var bmkLines = { bmkTotalReturn: [], bmkAvgAnnual: [], bmkCAGR: [], bmkMDD: [], bmkSharpe: [], bmkSortino: [] };
            var bmkScoreLines = [];
            bmkResults.forEach(function (bmkItem) {
                if (!bmkItem.metrics) return;
                var bm = bmkItem.metrics;
                var colorStyle = ' style="color:' + bmkItem.color + '"';
                var safeName = escapeHtml(bmkItem.name);
                bmkLines.bmkTotalReturn.push('<span class="bmk-val"' + colorStyle + '>' + safeName + ' ' + formatPercent(bm.totalReturn) + '</span>');
                bmkLines.bmkAvgAnnual.push('<span class="bmk-val"' + colorStyle + '>' + safeName + ' ' + formatPercent(bm.avgAnnual) + '</span>');
                bmkLines.bmkCAGR.push('<span class="bmk-val"' + colorStyle + '>' + safeName + ' ' + formatPercent(bm.cagr) + '</span>');
                bmkLines.bmkMDD.push('<span class="bmk-val"' + colorStyle + '>' + safeName + ' ' + formatPercent(-bm.mdd) + '</span>');
                bmkLines.bmkSharpe.push('<span class="bmk-val"' + colorStyle + '>' + safeName + ' ' + (bm.sharpe === null || !isFinite(bm.sharpe) ? '∞' : bm.sharpe.toFixed(2)) + '</span>');
                bmkLines.bmkSortino.push('<span class="bmk-val"' + colorStyle + '>' + safeName + ' ' + (bm.sortino === null || !isFinite(bm.sortino) ? '∞' : bm.sortino.toFixed(2)) + '</span>');
                var bmkScore = calculateTotalScore(bm);
                bmkScoreLines.push('<span class="bmk-val"' + colorStyle + '>' + safeName + ' ' + bmkScore.total + '점 (' + bmkScore.grade + ')</span>');
            });
            bmkMetricIds.forEach(function (id) {
                var el = document.getElementById(id);
                if (el && bmkLines[id].length > 0) {
                    el.innerHTML = bmkLines[id].join('<br>');
                    el.classList.add('visible');
                }
            });
            if (bmkScoreEl && bmkScoreLines.length > 0) {
                bmkScoreEl.innerHTML = bmkScoreLines.join('<br>');
                bmkScoreEl.classList.add('visible');
            }
        }

        // 차트
        renderChart(data.dailySeries, bmkResults);

        // 연도별 수익률 테이블
        var tbody = document.querySelector('#annualReturnsTable tbody');
        tbody.innerHTML = '';
        (data.annualReturns || []).forEach(function (a) {
            var tr = document.createElement('tr');
            tr.innerHTML = '<td>' + a.year + '</td>' +
                '<td class="' + (a.returnPct >= 0 ? 'positive' : 'negative') + '">' + formatPercent(a.returnPct) + '</td>' +
                '<td>' + formatCurrency(a.startValue) + '</td>' +
                '<td>' + formatCurrency(a.endValue) + '</td>' +
                '<td class="negative">' + formatPercent(-a.mdd) + '</td>';
            tbody.appendChild(tr);
        });

        // 거래 요약
        var ts = data.tradeSummary;
        document.getElementById('tradeTotalCount').textContent = formatNumber(ts.totalCount);
        document.getElementById('tradeBuyCount').textContent = formatNumber(ts.buyCount);
        document.getElementById('tradeSellCount').textContent = formatNumber(ts.sellCount);
        document.getElementById('tradeTotalInvested').textContent = formatCurrency(ts.totalInvested);
    }

    // 설정 수집
    function collectConfig() {
        if (portfolio.length === 0) return null;
        var totalWeight = portfolio.reduce(function (a, b) { return a + b.weight; }, 0);
        if (Math.abs(totalWeight - 100) > 0.5) return null;
        var startDate = document.getElementById('startDate').value;
        var endDate = document.getElementById('endDate').value;
        if (!startDate || !endDate || startDate >= endDate) return null;

        var activeTab = document.querySelector('.strategy-tab.active');
        var strategy = activeTab ? activeTab.dataset.strategy : 'buyhold';

        var signalRules = [];
        if (strategy === 'signal') {
            document.querySelectorAll('.signal-rule').forEach(function (rule) {
                signalRules.push({
                    indicator: rule.querySelector('.signal-indicator').value,
                    targetCode: rule.querySelector('.signal-target').value
                });
            });
            if (signalRules.length === 0) return null;
        }

        return {
            stocks: portfolio.map(function (s) { return { code: s.code, market: s.market, weight: s.weight }; }),
            benchmarks: benchmarks.map(function (b) { return { code: b.code, market: b.market, name: b.name }; }),
            startDate: startDate,
            endDate: endDate,
            strategy: strategy,
            rebalancePeriod: document.getElementById('rebalancePeriod').value,
            signalRules: signalRules,
            signalCombine: document.getElementById('signalCombine').value,
            initialCapital: (parseFloat(document.getElementById('initialCapital').value) || 0) * 10000,
            monthlyDCA: (parseFloat(document.getElementById('monthlyDCA').value) || 0) * 10000,
            dcaDefer: {
                enabled: document.getElementById('dcaDeferIndicator').value !== 'none',
                indicator: document.getElementById('dcaDeferIndicator').value
            },
            fees: {
                KR: parseFloat(document.getElementById('feeKR').value) || 0,
                US: parseFloat(document.getElementById('feeUS').value) || 0,
                COIN: parseFloat(document.getElementById('feeCOIN').value) || 0
            },
            riskFreeRate: parseFloat(document.getElementById('riskFreeRate').value) || 3
        };
    }

    // 설정 수집 + 유효성 검사 (사용자 알림 포함)
    function collectConfigWithAlert() {
        if (portfolio.length === 0) {
            alert('종목을 1개 이상 추가하세요.');
            return null;
        }
        var totalWeight = portfolio.reduce(function (a, b) { return a + b.weight; }, 0);
        if (Math.abs(totalWeight - 100) > 0.5) {
            alert('종목 비중 합계가 100%여야 합니다. (현재: ' + totalWeight.toFixed(1) + '%)');
            return null;
        }
        var startDate = document.getElementById('startDate').value;
        var endDate = document.getElementById('endDate').value;
        if (!startDate || !endDate || startDate >= endDate) {
            alert('유효한 기간을 설정하세요.');
            return null;
        }
        var activeTab = document.querySelector('.strategy-tab.active');
        var strategy = activeTab ? activeTab.dataset.strategy : 'buyhold';
        if (strategy === 'signal') {
            var rules = document.querySelectorAll('.signal-rule');
            if (rules.length === 0) {
                alert('시그널 기반 전략에는 최소 1개의 규칙이 필요합니다.');
                return null;
            }
        }
        return collectConfig();
    }

    // 자동 재계산 트리거 (debounce)
    function scheduleAutoRecalc() {
        if (!hasRunOnce) return;
        clearTimeout(autoRecalcTimer);
        autoRecalcTimer = setTimeout(function () {
            runBacktest(true);
        }, 500);
    }

    // 백테스트 실행 (서버 API 호출)
    function runBacktest(silent) {
        var config = silent ? collectConfig() : collectConfigWithAlert();
        if (!config) return;

        var btn = document.getElementById('runBacktest');
        btn.disabled = true;
        btn.textContent = '실행 중...';

        var progressDiv = document.getElementById('backtestProgress');
        var progressFill = document.getElementById('progressFill');
        var progressText = document.getElementById('progressText');

        progressDiv.style.display = '';
        progressFill.style.width = '30%';
        progressText.textContent = '서버에서 시뮬레이션 중...';

        fetch('/stocks/api/backtest', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify(config)
        })
            .then(function (r) { return r.json(); })
            .then(function (json) {
                progressFill.style.width = '100%';
                if (!json.success) {
                    if (!silent) alert(json.error || '시뮬레이션 실패');
                    btn.disabled = false;
                    updateRunButtonState();
                    progressDiv.style.display = 'none';
                    return;
                }

                progressDiv.style.display = 'none';
                displayResults(json.data);

                hasRunOnce = true;
                lastRunKey = JSON.stringify(config);
                btn.disabled = false;
                updateRunButtonState();

                document.getElementById('metricsCards').scrollIntoView({ behavior: 'smooth', block: 'start' });
            })
            .catch(function (err) {
                console.error('백테스트 에러:', err);
                if (!silent) alert('시뮬레이션 중 오류가 발생했습니다.');
                btn.disabled = false;
                updateRunButtonState();
                progressDiv.style.display = 'none';
            });
    }

    /* =========================================
       설정 저장/불러오기 (localStorage)
       ========================================= */
    var STORAGE_KEY = 'backtest_config_v2';

    function saveConfigToStorage() {
        var activeTab = document.querySelector('.strategy-tab.active');
        var signalRules = [];
        document.querySelectorAll('.signal-rule').forEach(function (rule) {
            signalRules.push({
                indicator: rule.querySelector('.signal-indicator').value,
                targetCode: rule.querySelector('.signal-target').value
            });
        });

        var data = {
            portfolio: portfolio.map(function (s) { return { code: s.code, name: s.name, market: s.market, weight: s.weight }; }),
            benchmark: benchmarks.length > 0 ? { code: benchmarks[0].code, name: benchmarks[0].name, market: benchmarks[0].market } : null,
            benchmarks: benchmarks.map(function (b) { return { code: b.code, name: b.name, market: b.market }; }),
            strategy: activeTab ? activeTab.dataset.strategy : 'buyhold',
            rebalancePeriod: document.getElementById('rebalancePeriod').value,
            signalRules: signalRules,
            signalCombine: document.getElementById('signalCombine').value,
            initialCapital: document.getElementById('initialCapital').value,
            monthlyDCA: document.getElementById('monthlyDCA').value,
            dcaDeferIndicator: document.getElementById('dcaDeferIndicator').value,
            feeKR: document.getElementById('feeKR').value,
            feeUS: document.getElementById('feeUS').value,
            feeCOIN: document.getElementById('feeCOIN').value,
            startDate: document.getElementById('startDate').value,
            endDate: document.getElementById('endDate').value,
            riskFreeRate: document.getElementById('riskFreeRate').value,
            savedAt: new Date().toISOString()
        };

        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
            showSaveStatus('저장 완료');
        } catch (e) {
            alert('설정 저장에 실패했습니다.');
        }
    }

    function loadConfigFromStorage() {
        try {
            var raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) { alert('저장된 설정이 없습니다.'); return; }
            var data = JSON.parse(raw);

            portfolio = (data.portfolio || []).map(function (s) {
                return { code: s.code, name: s.name, market: s.market, weight: s.weight };
            });
            renderPortfolio();

            if (data.benchmarks && data.benchmarks.length > 0) {
                benchmarks = data.benchmarks.map(function (b) {
                    return { code: b.code, name: b.name, market: b.market };
                });
            } else if (data.benchmark) {
                benchmarks = [{ code: data.benchmark.code, name: data.benchmark.name, market: data.benchmark.market }];
            } else {
                benchmarks = [];
            }
            renderBenchmark();

            document.querySelectorAll('.strategy-tab').forEach(function (t) { t.classList.remove('active'); });
            var targetTab = document.querySelector('.strategy-tab[data-strategy="' + (data.strategy || 'buyhold') + '"]');
            if (targetTab) targetTab.classList.add('active');
            document.getElementById('rebalanceConfig').style.display = data.strategy === 'rebalance' ? '' : 'none';
            document.getElementById('signalConfig').style.display = data.strategy === 'signal' ? '' : 'none';

            document.getElementById('rebalancePeriod').value = data.rebalancePeriod || 'quarterly';
            document.getElementById('signalCombine').value = data.signalCombine || 'or';
            document.getElementById('initialCapital').value = data.initialCapital || '1000';
            document.getElementById('monthlyDCA').value = data.monthlyDCA || '100';
            document.getElementById('dcaDeferIndicator').value = data.dcaDeferIndicator || (data.dcaDeferEnabled ? 'macd_death' : 'none');
            updateDcaDeferHint();
            document.getElementById('feeKR').value = data.feeKR || '0.015';
            document.getElementById('feeUS').value = data.feeUS || '0.2';
            document.getElementById('feeCOIN').value = data.feeCOIN || '0.015';
            if (data.startDate) document.getElementById('startDate').value = data.startDate;
            if (data.endDate) document.getElementById('endDate').value = data.endDate;
            document.getElementById('riskFreeRate').value = data.riskFreeRate || '3.0';

            document.getElementById('signalRules').innerHTML = '';
            (data.signalRules || []).forEach(function (rule) {
                addSignalRule();
                var rules = document.querySelectorAll('.signal-rule');
                var last = rules[rules.length - 1];
                last.querySelector('.signal-indicator').value = rule.indicator;
                updateSignalTargets();
                if (rule.targetCode) last.querySelector('.signal-target').value = rule.targetCode;
            });

            showSaveStatus('설정 복원됨');
            updateDateRange();
        } catch (e) {
            alert('설정 불러오기에 실패했습니다.');
        }
    }

    function clearStoredConfig() {
        localStorage.removeItem(STORAGE_KEY);
        showSaveStatus('삭제됨');
    }

    function showSaveStatus(msg) {
        var el = document.getElementById('saveStatus');
        if (!el) return;
        el.textContent = msg;
        el.style.opacity = '1';
        setTimeout(function () { el.style.opacity = '0'; }, 3000);
    }

    /* =========================================
       초기화
       ========================================= */
    function init() {
        initStockSearch('stockSearchInput', 'stockSearchResults',
            function (stock) {
                if (portfolio.length >= MAX_STOCKS) { alert('최대 ' + MAX_STOCKS + '개까지 추가 가능합니다.'); return; }
                if (portfolio.some(function (s) { return s.code === stock.code; })) { alert('이미 추가된 종목입니다.'); return; }
                var n = portfolio.length + 1;
                var base = Math.floor(10000 / n);
                var remainder = 10000 - base * n;
                portfolio.forEach(function (s, i) {
                    s.weight = (base + (i < remainder ? 1 : 0)) / 100;
                });
                stock.weight = (base + (portfolio.length < remainder ? 1 : 0)) / 100;
                portfolio.push(stock);
                renderPortfolio();
                updateSignalTargets();
                updateRunButtonState();
                updateDateRange();
            },
            function (stock) {
                if (benchmarks.length >= MAX_BENCHMARKS) { alert('벤치마크는 최대 ' + MAX_BENCHMARKS + '개까지 추가 가능합니다.'); return; }
                if (benchmarks.some(function (b) { return b.code === stock.code; })) { alert('이미 추가된 벤치마크입니다.'); return; }
                benchmarks.push(stock);
                renderBenchmark();
                updateRunButtonState();
                updateDateRange();
            }
        );

        initStrategyTabs();

        var dcaDeferSel = document.getElementById('dcaDeferIndicator');
        if (dcaDeferSel) dcaDeferSel.addEventListener('change', updateDcaDeferHint);

        var addBtn = document.getElementById('addSignalRule');
        if (addBtn) addBtn.addEventListener('click', addSignalRule);

        var runBtn = document.getElementById('runBacktest');
        if (runBtn) runBtn.addEventListener('click', function () { runBacktest(false); });

        var saveBtn = document.getElementById('saveConfig');
        if (saveBtn) saveBtn.addEventListener('click', saveConfigToStorage);
        var loadBtn = document.getElementById('loadConfig');
        if (loadBtn) loadBtn.addEventListener('click', loadConfigFromStorage);
        var clearBtn = document.getElementById('clearConfig');
        if (clearBtn) clearBtn.addEventListener('click', function () {
            if (confirm('저장된 설정을 삭제하시겠습니까?')) clearStoredConfig();
        });

        var simParamIds = [
            'rebalancePeriod', 'signalCombine',
            'initialCapital', 'monthlyDCA',
            'dcaDeferIndicator',
            'feeKR', 'feeUS', 'feeCOIN',
            'riskFreeRate',
            'startDate', 'endDate'
        ];
        simParamIds.forEach(function (id) {
            var el = document.getElementById(id);
            if (!el) return;
            var eventType = (el.type === 'checkbox') ? 'change' : 'input';
            el.addEventListener(eventType, scheduleAutoRecalc);
        });

        // 저장된 설정이 있으면 자동 복원
        if (localStorage.getItem(STORAGE_KEY) || localStorage.getItem('backtest_config_v1')) {
            if (!localStorage.getItem(STORAGE_KEY) && localStorage.getItem('backtest_config_v1')) {
                localStorage.setItem(STORAGE_KEY, localStorage.getItem('backtest_config_v1'));
                localStorage.removeItem('backtest_config_v1');
            }
            loadConfigFromStorage();
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
