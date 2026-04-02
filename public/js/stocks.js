/**
 * 주식 차트 및 체결 정보 관리 JavaScript
 * - 크로스헤어 인터랙션, 거래량 바, 줌/팬, 반응형 캔들 너비
 */

let stockChart = null;
let currentChartType = 'candle';
let currentPeriod = '1D';
let currentTimeframe = '1d';
let isLoadingMoreData = false;
let allDataLoaded = false;
const MAX_CANDLES = 360;

/* ========================================
   CSS 변수 기반 색상 시스템
   ======================================== */
function getCSSVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

const chartColors = {
    get up()          { return getCSSVar('--chart-up-color')       || '#ef5350'; },
    get down()        { return getCSSVar('--chart-down-color')     || '#26a69a'; },
    get unchanged()   { return getCSSVar('--chart-unchanged-color')|| '#999';    },
    get grid()        { return getCSSVar('--chart-grid-color')     || '#333';    },
    get crosshair()   { return getCSSVar('--chart-crosshair-color')|| 'rgba(255,255,255,0.4)'; },
    get volumeUp()    { return getCSSVar('--chart-volume-up')      || 'rgba(239,83,80,0.35)';  },
    get volumeDown()  { return getCSSVar('--chart-volume-down')    || 'rgba(38,166,154,0.35)';  },
    get tooltipBg()   { return getCSSVar('--chart-tooltip-bg')     || 'rgba(20,20,20,0.92)'; },
    get textPrimary() { return getCSSVar('--text-primary')         || '#fff';    },
    get textMuted()   { return getCSSVar('--text-muted')           || '#9aa0a6'; },
    get textSecondary() { return getCSSVar('--text-secondary')     || '#C3C3C3'; },
    get border()      { return getCSSVar('--border-color')         || '#464646'; },
    get primary()     { return getCSSVar('--primary-color')        || '#4CAF50'; },
};

/* ========================================
   통화 포맷팅
   ======================================== */
function getCurrencyPrefix() {
    return (typeof isUSMarket !== 'undefined' && isUSMarket) ? '$' : '';
}
function getCurrencySuffix() {
    return (typeof isUSMarket !== 'undefined' && isUSMarket) ? '' : '원';
}
function formatPrice(value) {
    const prefix = getCurrencyPrefix();
    const suffix = getCurrencySuffix();
    if (typeof isUSMarket !== 'undefined' && isUSMarket) {
        return prefix + new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value) + suffix;
    }
    if (typeof isCoinMarket !== 'undefined' && isCoinMarket) {
        return prefix + new Intl.NumberFormat('ko-KR').format(value) + suffix;
    }
    return prefix + new Intl.NumberFormat('ko-KR').format(value) + suffix;
}

function formatPriceValueOnly(value) {
    const prefix = getCurrencyPrefix();
    if (typeof isUSMarket !== 'undefined' && isUSMarket) {
        return prefix + new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
    }
    return prefix + new Intl.NumberFormat('ko-KR').format(value);
}

function updateCurrentPriceFromCandles(data) {
    if (!Array.isArray(data) || data.length === 0) return;

    const latestCandle = data[data.length - 1];
    const latestClose = parseFloat(latestCandle.execution_close);
    if (isNaN(latestClose)) return;

    const mainPriceEl = document.getElementById('currentPriceMainValue');
    if (mainPriceEl) mainPriceEl.textContent = formatPriceValueOnly(latestClose);

    const infoPriceEl = document.getElementById('currentPriceInfoValue');
    if (infoPriceEl) infoPriceEl.textContent = formatPriceValueOnly(latestClose);
}

/* ========================================
   크로스헤어 플러그인 (Chart.js 4.x 인라인)
   ======================================== */
const crosshairPlugin = {
    id: 'crosshairPlugin',
    afterInit(chart) {
        chart._crosshair = { x: null, y: null, show: false };
    },
    afterEvent(chart, args) {
        const { event } = args;
        const area = chart.chartArea;
        if (!area) return;

        if (event.type === 'mousemove') {
            const x = event.x;
            const y = event.y;
            if (x >= area.left && x <= area.right && y >= area.top && y <= area.bottom) {
                chart._crosshair = { x, y, show: true };
            } else {
                chart._crosshair.show = false;
            }
            chart.draw();
        } else if (event.type === 'mouseout') {
            chart._crosshair.show = false;
            chart.draw();
        }
    },
    afterDraw(chart) {
        const ch = chart._crosshair;
        if (!ch || !ch.show) return;

        const { ctx, chartArea: area, scales } = chart;
        if (!area) return;

        ctx.save();
        ctx.setLineDash([4, 4]);
        ctx.strokeStyle = chartColors.crosshair;
        ctx.lineWidth = 1;

        // 수직선
        ctx.beginPath();
        ctx.moveTo(ch.x, area.top);
        ctx.lineTo(ch.x, area.bottom);
        ctx.stroke();

        // 수평선
        ctx.beginPath();
        ctx.moveTo(area.left, ch.y);
        ctx.lineTo(area.right, ch.y);
        ctx.stroke();

        ctx.setLineDash([]);

        // Y축 가격 라벨
        const yScale = scales.y;
        if (yScale) {
            const priceValue = yScale.getValueForPixel(ch.y);
            const label = formatPrice(priceValue);
            ctx.font = '11px -apple-system, BlinkMacSystemFont, sans-serif';
            const textWidth = ctx.measureText(label).width;
            const labelW = textWidth + 10;
            const labelH = 20;
            const labelX = area.right + 2;
            const labelY = ch.y - labelH / 2;

            ctx.fillStyle = chartColors.border;
            ctx.fillRect(labelX, labelY, labelW, labelH);
            ctx.fillStyle = chartColors.textPrimary;
            ctx.textAlign = 'left';
            ctx.textBaseline = 'middle';
            ctx.fillText(label, labelX + 5, ch.y);
        }

        // X축 시간 라벨
        const xScale = scales.x;
        if (xScale) {
            const xIndex = xScale.getValueForPixel(ch.x);
            const xLabel = (typeof xIndex === 'number' && chart.data.labels[xIndex])
                ? chart.data.labels[xIndex]
                : (typeof xIndex === 'string' ? xIndex : '');
            if (xLabel) {
                ctx.font = '11px -apple-system, BlinkMacSystemFont, sans-serif';
                const tw = ctx.measureText(xLabel).width;
                const lw = tw + 10;
                const lh = 20;
                const lx = ch.x - lw / 2;
                const ly = area.bottom + 2;

                ctx.fillStyle = chartColors.border;
                ctx.fillRect(lx, ly, lw, lh);
                ctx.fillStyle = chartColors.textPrimary;
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillText(xLabel, ch.x, ly + lh / 2);
            }
        }

        ctx.restore();
    }
};

/* ========================================
   커스텀 캔들스틱 렌더링 플러그인
   - Canvas API 직접 사용, barPercentage 불필요
   - 슬롯 픽셀 폭에서 바디 60% 계산
   ======================================== */
const candleDrawPlugin = {
    id: 'candleDrawPlugin',
    afterDatasetsDraw(chart) {
        var ohlc = chart._ohlcData;
        if (!ohlc || ohlc.length === 0) return;

        var ctx = chart.ctx;
        var area = chart.chartArea;
        var xScale = chart.scales.x;
        var yScale = chart.scales.y;
        if (!area || !xScale || !yScale) return;

        // 인접 인덱스 간 픽셀 거리로 슬롯 폭 계산
        var slotWidth;
        if (ohlc.length > 1) {
            slotWidth = Math.abs(xScale.getPixelForValue(1) - xScale.getPixelForValue(0));
        } else {
            slotWidth = area.right - area.left;
        }

        // 바디 폭: 슬롯의 60%, 최소 1px
        var bodyWidth = Math.max(1, Math.round(slotWidth * 0.6));
        var halfBody = Math.floor(bodyWidth / 2);

        ctx.save();
        ctx.beginPath();
        ctx.rect(area.left, area.top, area.right - area.left, area.bottom - area.top);
        ctx.clip();

        for (var i = 0; i < ohlc.length; i++) {
            var d = ohlc[i];
            var x = Math.round(xScale.getPixelForValue(i));

            // 보이는 영역 밖이면 스킵
            if (x + halfBody < area.left || x - halfBody > area.right) continue;

            var openPx = yScale.getPixelForValue(d.o);
            var closePx = yScale.getPixelForValue(d.c);
            var highPx = yScale.getPixelForValue(d.h);
            var lowPx = yScale.getPixelForValue(d.l);

            var color = d.c > d.o ? chartColors.up
                      : d.c < d.o ? chartColors.down
                      : chartColors.unchanged;

            // 꼬리 (shadow/wick)
            ctx.strokeStyle = color;
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(x + 0.5, Math.round(highPx));
            ctx.lineTo(x + 0.5, Math.round(lowPx));
            ctx.stroke();

            // 몸통 (body)
            var bodyTop = Math.round(Math.min(openPx, closePx));
            var bodyH = Math.max(1, Math.round(Math.abs(closePx - openPx)));

            ctx.fillStyle = color;
            ctx.fillRect(x - halfBody, bodyTop, bodyWidth, bodyH);
        }

        ctx.restore();
    }
};

/* ========================================
   초기화
   ======================================== */
document.addEventListener('DOMContentLoaded', function() {
    waitForChartReady().then(() => {
        if (typeof Chart !== 'undefined') {
            Chart.register(crosshairPlugin, candleDrawPlugin);
        }
        loadChartData(currentPeriod);
        loadInitialExecutions();
    });

    syncExecutionHeaderSpacing();
    window.addEventListener('resize', syncExecutionHeaderSpacing);

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') closeExecutionOverlay();
    });
    
    setupPeriodWheelControl();
});

function waitForChartReady() {
    return new Promise((resolve) => {
        if (typeof Chart !== 'undefined') {
            resolve();
            return;
        }
        let elapsed = 0;
        const interval = setInterval(() => {
            elapsed += 50;
            if (typeof Chart !== 'undefined' || elapsed >= 5000) {
                clearInterval(interval);
                resolve();
            }
        }, 50);
    });
}

/* ========================================
   체결 데이터
   ======================================== */
function getMarketParam() {
    if (typeof isCoinMarket !== 'undefined' && isCoinMarket) return '&market=COIN';
    if (typeof isUSMarket !== 'undefined' && isUSMarket) return '&market=US';
    return '';
}

function loadInitialExecutions() {
    fetch('/stocks/api/executions?code=' + encodeURIComponent(stockCode) + '&limit=50' + getMarketParam())
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                updateExecutionList(data.data);
                syncExecutionHeaderSpacing();
            }
        })
        .catch(error => {
            console.error('체결 정보 로드 실패:', error);
            const el = document.getElementById('executionList');
            if (el) el.innerHTML = '<div class="execution-no-data">체결 데이터를 불러올 수 없습니다.</div>';
        });
}

/* ========================================
   차트 모듈 상태
   ======================================== */
function isChartReady() {
    return typeof Chart !== 'undefined';
}

function hasCandlestickSupport() {
    if (typeof window.CandlestickController !== 'undefined') return true;
    if (typeof Chart !== 'undefined' && Chart.registry && typeof Chart.registry.getController === 'function') {
        try { return !!Chart.registry.getController('candlestick'); } catch (e) { return false; }
    }
    return false;
}

function loadScript(src) {
    return new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = src;
        script.async = true;
        script.onload = () => resolve();
        script.onerror = () => reject(new Error('스크립트 로드 실패: ' + src));
        document.head.appendChild(script);
    });
}

async function loadChartModules() {
    try {
        if (typeof Chart === 'undefined') await loadScript('/vendor/chart.umd.min.js');
        if (!hasCandlestickSupport()) {
            try { await loadScript('/vendor/chartjs-chart-financial.min.js'); }
            catch (e) { console.warn('캔들 플러그인 로드 실패, 라인 차트로 대체합니다.', e); }
        }
    } catch (error) { console.error('차트 모듈 로드 실패:', error); throw error; }
}

/* ========================================
   줌 리셋 버튼
   ======================================== */
function updateZoomResetButton() {
    const btn = document.getElementById('chartZoomReset');
    if (!btn) return;
    if (stockChart && typeof stockChart.isZoomedOrPanned === 'function' && stockChart.isZoomedOrPanned()) {
        btn.classList.add('visible');
    } else {
        btn.classList.remove('visible');
    }
}

function resetChartZoom() {
    if (stockChart && typeof stockChart.resetZoom === 'function') {
        stockChart.resetZoom();
        updateZoomResetButton();
        updateYAxisRange();
    }
}

/* ========================================
   Y축 범위 동적 조절 (보이는 캔들 기준)
   ======================================== */
function updateYAxisRange() {
    if (!stockChart) return;
    var xScale = stockChart.scales ? stockChart.scales.x : null;
    if (!xScale) return;

    var ohlc = stockChart._ohlcData;
    var priceData = (!ohlc && stockChart.data && stockChart.data.datasets)
        ? stockChart.data.datasets[0].data : null;
    var total = ohlc ? ohlc.length : (priceData ? priceData.length : 0);
    if (total === 0) return;

    var visibleMin = 0;
    var visibleMax = total - 1;
    if (typeof xScale.min === 'number' && typeof xScale.max === 'number'
        && !isNaN(xScale.min) && !isNaN(xScale.max)) {
        visibleMin = Math.max(0, Math.floor(xScale.min));
        visibleMax = Math.min(total - 1, Math.ceil(xScale.max));
    }

    var lo = Infinity, hi = -Infinity;
    for (var i = visibleMin; i <= visibleMax; i++) {
        if (ohlc) {
            if (ohlc[i].l < lo) lo = ohlc[i].l;
            if (ohlc[i].h > hi) hi = ohlc[i].h;
        } else if (priceData) {
            var v = priceData[i];
            if (typeof v === 'number' && !isNaN(v)) {
                if (v < lo) lo = v;
                if (v > hi) hi = v;
            }
        }
    }

    if (lo === Infinity || hi === -Infinity) return;

    var padding = (hi - lo) * 0.08;
    if (padding === 0) padding = hi * 0.02 || 1;
    var newMin = Math.max(0, lo - padding);
    var newMax = hi + padding;

    var yScale = stockChart.options.scales.y;
    if (Math.abs((yScale.min || 0) - newMin) > padding * 0.1
        || Math.abs((yScale.max || 0) - newMax) > padding * 0.1) {
        yScale.min = newMin;
        yScale.max = newMax;
        requestAnimationFrame(function() {
            if (stockChart) stockChart.update('none');
        });
    }
}

/* ========================================
   차트 초기화
   ======================================== */
function initChart() {
    const canvas = document.getElementById('stockChart');
    if (!canvas) { showChartError('Canvas 요소를 찾을 수 없습니다.'); return; }

    const wrapper = canvas.parentElement;
    if (!wrapper) { showChartError('Canvas wrapper를 찾을 수 없습니다.'); return; }

    const rect = wrapper.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) {
        setTimeout(() => initChart(), 200);
        return;
    }

    const cs = getComputedStyle(wrapper);
    const width = wrapper.offsetWidth - (parseInt(cs.paddingLeft) || 0) - (parseInt(cs.paddingRight) || 0);
    const height = wrapper.offsetHeight - (parseInt(cs.paddingTop) || 0) - (parseInt(cs.paddingBottom) || 0);
    
    const dpr = window.devicePixelRatio;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    canvas.style.width = width + 'px';
    canvas.style.height = height + 'px';
    canvas.style.display = 'block';

    if (!isChartReady()) {
        waitForChartReady().then(() => initChart());
        return;
    }

    const ctx = canvas.getContext('2d');
    if (!ctx) { showChartError('Canvas 컨텍스트를 가져올 수 없습니다.'); return; }
    ctx.scale(dpr, dpr);

    if (stockChart) stockChart.destroy();

    const chartData = prepareChartData(candleData, currentChartType);

    // 데이터 범위 계산
    let dataRange = null;
    if (candleData && candleData.length > 0) {
        const allValues = candleData.flatMap(d => [
            parseFloat(d.execution_open), parseFloat(d.execution_close),
            parseFloat(d.execution_min), parseFloat(d.execution_max)
        ].filter(v => !isNaN(v)));
        if (allValues.length > 0) {
            dataRange = { min: Math.min(...allValues), max: Math.max(...allValues) };
        }
    }

    stockChart = new Chart(ctx, {
        type: 'line',
        data: chartData,
        options: getChartOptions(currentChartType, dataRange)
    });
    stockChart._ohlcData = chartData._ohlcData || null;

    updateZoomResetButton();
}

/* ========================================
   로딩/에러 UI
   ======================================== */
function showChartLoading(show) {
    const el = document.getElementById('chartLoading');
    if (el) el.style.display = show ? 'flex' : 'none';
}

function showChartNoData(show) {
    const el = document.getElementById('chartNoData');
    if (el) el.style.display = show ? 'flex' : 'none';
}

function showChartError(message) {
    const canvas = document.getElementById('stockChart');
    if (!canvas) return;
    const wrapper = canvas.parentElement;
    if (!wrapper) return;
    wrapper.innerHTML =
        '<div class="chart-no-data" style="position: static; transform: none; padding: 20px;">' +
            '<p>' + message + '</p>' +
            '<p class="chart-no-data-sub">명령어로 npm install을 실행하거나 CDN 접속을 확인해주세요.</p>' +
        '</div>';
}

/* ========================================
   차트 데이터 준비 (+ 거래량 바)
   ======================================== */
function prepareChartData(data, chartType) {
    var labels = data.map(function(d) { return formatDateTime(d.execution_datetime); });

    // 거래량 데이터 (양봉/음봉 색상 분기)
    var volumes = data.map(function(d) {
        return Math.max(
            parseFloat(d.execution_non_volume || 0),
            parseFloat(d.execution_ask_volume || 0) + parseFloat(d.execution_bid_volume || 0)
        );
    });
    var volumeColors = data.map(function(d) {
        var open = parseFloat(d.execution_open);
        var close = parseFloat(d.execution_close);
        return close >= open ? chartColors.volumeUp : chartColors.volumeDown;
    });

    var volumeDataset = {
        label: '거래량',
        type: 'bar',
        data: volumes,
        backgroundColor: volumeColors,
        yAxisID: 'y2',
        order: 2,
        barPercentage: 0.6,
        categoryPercentage: 0.9
    };

    if (chartType === 'line') {
        return {
            labels: labels,
            datasets: [
                {
                    label: '종가',
                    data: data.map(function(d) { return parseFloat(d.execution_close); }),
                    borderColor: chartColors.primary,
                    backgroundColor: 'rgba(76, 175, 80, 0.08)',
                    fill: true,
                    tension: 0.3,
                    pointRadius: 0,
                    pointHitRadius: 8,
                    borderWidth: 2,
                    order: 1
                },
                volumeDataset
            ]
        };
    } else {
        // 커스텀 캔들 렌더링 (candleDrawPlugin)
        // 투명 라인 (y축 스케일링 + 툴팁 인터랙션) + 거래량 바 + OHLC 데이터
        var ohlcData = data.map(function(d) {
            return {
                o: parseFloat(d.execution_open),
                h: parseFloat(d.execution_max),
                l: parseFloat(d.execution_min),
                c: parseFloat(d.execution_close)
            };
        });

        return {
            labels: labels,
            datasets: [
                {
                    label: '캔들',
                    data: data.map(function(d) { return parseFloat(d.execution_close); }),
                    borderWidth: 0,
                    borderColor: 'transparent',
                    pointRadius: 0,
                    pointHitRadius: 10,
                    fill: false,
                    order: 1
                },
                volumeDataset
            ],
            _ohlcData: ohlcData
        };
    }
}

/* ========================================
   차트 옵션 (크로스헤어, 줌/팬, 거래량 y2 축)
   ======================================== */
function getChartOptions(chartType, dataRange) {
    chartType = chartType || 'line';
    dataRange = dataRange || null;

    var hasZoomPlugin = false;
    if (typeof Chart !== 'undefined' && Chart.registry && typeof Chart.registry.getPlugin === 'function') {
        try { hasZoomPlugin = !!Chart.registry.getPlugin('zoom'); } catch(e) {}
    }

    var options = {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 300 },
        interaction: {
            mode: 'index',
            intersect: false
        },
        plugins: {
            legend: {
                display: false
            },
            tooltip: {
                backgroundColor: chartColors.tooltipBg,
                titleColor: chartColors.textPrimary,
                bodyColor: chartColors.textSecondary,
                borderColor: chartColors.border,
                borderWidth: 1,
                padding: 12,
                cornerRadius: 8,
                displayColors: false,
                titleFont: { size: 13, weight: '600' },
                bodyFont: { size: 12 },
                bodySpacing: 6,
                callbacks: {
                    title: function(items) {
                        if (items.length > 0) return items[0].label;
                        return '';
                    },
                    label: function(context) {
                        if (context.dataset.label === '거래량') {
                            return '거래량: ' + formatNumber(context.parsed.y);
                        }
                        if (chartType === 'candle' && context.dataset.label === '캔들') {
                            var ohlc = context.chart._ohlcData;
                            if (ohlc && ohlc[context.dataIndex]) {
                                var d = ohlc[context.dataIndex];
                                var change = d.o !== 0 ? ((d.c - d.o) / d.o * 100).toFixed(2) : '0.00';
                                var changeSign = d.c >= d.o ? '+' : '';
                                return [
                                    '시가: ' + formatPrice(d.o),
                                    '고가: ' + formatPrice(d.h),
                                    '저가: ' + formatPrice(d.l),
                                    '종가: ' + formatPrice(d.c),
                                    '등락: ' + changeSign + change + '%'
                                ];
                            }
                        }
                        if (context.parsed.y !== null) {
                            return '종가: ' + formatPrice(context.parsed.y);
                        }
                        return '';
                    }
                }
            },
            crosshairPlugin: {}
        },
        scales: {
            x: {
                type: 'category',
                grid: {
                    color: chartColors.grid,
                    drawTicks: false
                },
                border: { color: chartColors.grid },
                ticks: {
                    color: chartColors.textMuted,
                    maxTicksLimit: window.innerWidth <= 480 ? 5 : 10,
                    maxRotation: 0,
                    padding: 8,
                    font: { size: 11 }
                }
            },
            y: {
                position: 'right',
                beginAtZero: false,
                grid: {
                    color: chartColors.grid,
                    drawTicks: false
                },
                border: { color: chartColors.grid },
                ticks: {
                    color: chartColors.textMuted,
                    padding: 8,
                    font: { size: 11 },
                    callback: function(value) {
                        return formatPrice(value);
                    }
                }
            },
            y2: {
                position: 'left',
                beginAtZero: true,
                grid: { display: false },
                border: { display: false },
                ticks: { display: false },
                max: undefined
            }
        },
        onResize: function() {
            updateZoomResetButton();
        }
    };

    // 거래량 y2 축 max: 가격 데이터와 겹치지 않도록 거래량 최대값의 5배
    if (candleData && candleData.length > 0) {
        var maxVol = 0;
        for (var i = 0; i < candleData.length; i++) {
            var v = Math.max(
                parseFloat(candleData[i].execution_non_volume || 0),
                parseFloat(candleData[i].execution_ask_volume || 0) + parseFloat(candleData[i].execution_bid_volume || 0)
            );
            if (v > maxVol) maxVol = v;
        }
        if (maxVol > 0) {
            options.scales.y2.max = maxVol * 5;
        }
    }

    // 데이터 범위가 제공되면 y축 범위 설정
    if (dataRange && dataRange.min !== undefined && dataRange.max !== undefined) {
        var padding = (dataRange.max - dataRange.min) * 0.08;
        options.scales.y.min = Math.max(0, dataRange.min - padding);
        options.scales.y.max = dataRange.max + padding;
    }

    // 줌/팬 설정 (플러그인이 로드된 경우에만)
    if (hasZoomPlugin) {
        options.plugins.zoom = {
            pan: {
                enabled: true,
                mode: 'x',
                onPanComplete: function() {
                    updateZoomResetButton();
                    updateYAxisRange();
                    checkAndLoadMoreData();
                }
            },
            zoom: {
                wheel: { enabled: true, speed: 0.1 },
                pinch: { enabled: true },
                mode: 'x',
                onZoomComplete: function() {
                    updateZoomResetButton();
                    updateYAxisRange();
                    checkAndLoadMoreData();
                }
            },
            limits: {
                x: { minRange: 5, min: 0 }
            }
        };
    }

    return options;
}

/* ========================================
   차트 데이터 로드 (기간별)
   ======================================== */
function loadChartData(period) {
    currentPeriod = period;
    isLoadingMoreData = false;
    allDataLoaded = false;
    
    var periodSelect = document.getElementById('periodSelect');
    if (periodSelect && periodSelect.value !== period) {
        periodSelect.value = period;
    }
    
    var endDate = new Date();
    var startDate = new Date();
    var timeframe = '1d';
    var candleCount = 60;
    
    switch(period) {
        case '10M':
            startDate = new Date(endDate.getTime() - (candleCount * 10 * 60 * 1000));
            timeframe = '10m';
            break;
        case '30M':
            startDate = new Date(endDate.getTime() - (candleCount * 30 * 60 * 1000));
            timeframe = '30m';
            break;
        case '1H':
            startDate = new Date(endDate.getTime() - (candleCount * 60 * 60 * 1000));
            timeframe = '1h';
            break;
        case '3H':
            startDate = new Date(endDate.getTime() - (candleCount * 3 * 60 * 60 * 1000));
            timeframe = '3h';
            break;
        case '6H':
            startDate = new Date(endDate.getTime() - (candleCount * 6 * 60 * 60 * 1000));
            timeframe = '6h';
            break;
        case '1D':
            startDate.setDate(endDate.getDate() - 180);
            timeframe = '1d';
            break;
        case '1W':
            startDate.setDate(endDate.getDate() - (candleCount * 8));
            timeframe = '1w';
            break;
        case '1M':
            startDate.setMonth(endDate.getMonth() - (candleCount + 12));
            timeframe = '1M';
            break;
    }

    currentTimeframe = timeframe;
    
    var startDateStr = formatDateForAPI(startDate);
    var endDateStr = formatDateForAPI(endDate);

    showChartLoading(true);
    
    fetch('/stocks/api/candle?code=' + encodeURIComponent(stockCode) + '&start=' + startDateStr + '&end=' + endDateStr + '&timeframe=' + timeframe + '&limit=' + candleCount + getMarketParam())
        .then(function(response) { return response.json(); })
        .then(function(data) {
            showChartLoading(false);
            if (data.success && data.data.length > 0) {
                candleData = data.data;
                updateCurrentPriceFromCandles(candleData);
                showChartNoData(false);
                initChart();
            } else {
                candleData = [];
                if (stockChart) { stockChart.destroy(); stockChart = null; }
                showChartNoData(true);
            }
        })
        .catch(function(error) {
            showChartLoading(false);
            showChartNoData(true);
            console.error('차트 데이터 로드 실패:', error);
        });
}

/* ========================================
   과거 데이터 무한 스크롤
   ======================================== */
function checkAndLoadMoreData() {
    if (!stockChart || !stockChart.scales || !stockChart.scales.x) return;
    if (isLoadingMoreData || allDataLoaded || !candleData || candleData.length === 0) return;
    if (candleData.length >= MAX_CANDLES) {
        allDataLoaded = true;
        return;
    }

    var visibleMin = Math.floor(stockChart.scales.x.min);
    if (visibleMin <= 10) {
        loadMoreHistoricalData();
    }
}

function loadMoreHistoricalData() {
    if (isLoadingMoreData || allDataLoaded || !candleData || candleData.length === 0) return;

    isLoadingMoreData = true;

    var earliestDatetime = candleData[0].execution_datetime;
    var earliestDate = new Date(earliestDatetime.replace(' ', 'T'));
    var fetchCount = 60;

    var newStartDate = new Date(earliestDate);
    switch (currentTimeframe) {
        case '10m': newStartDate = new Date(earliestDate.getTime() - fetchCount * 10 * 60 * 1000); break;
        case '30m': newStartDate = new Date(earliestDate.getTime() - fetchCount * 30 * 60 * 1000); break;
        case '1h':  newStartDate = new Date(earliestDate.getTime() - fetchCount * 60 * 60 * 1000); break;
        case '3h':  newStartDate = new Date(earliestDate.getTime() - fetchCount * 3 * 60 * 60 * 1000); break;
        case '6h':  newStartDate = new Date(earliestDate.getTime() - fetchCount * 6 * 60 * 60 * 1000); break;
        case '1d':  newStartDate.setDate(earliestDate.getDate() - 180); break;
        case '1w':  newStartDate.setDate(earliestDate.getDate() - fetchCount * 8); break;
        case '1M':  newStartDate.setMonth(earliestDate.getMonth() - (fetchCount + 12)); break;
    }

    var startDateStr = formatDateForAPI(newStartDate);
    var endDateStr = formatDateForAPI(new Date(earliestDate.getTime() - 1000));

    fetch('/stocks/api/candle?code=' + encodeURIComponent(stockCode) +
          '&start=' + startDateStr + '&end=' + endDateStr +
          '&timeframe=' + currentTimeframe + '&limit=' + fetchCount + getMarketParam())
        .then(function(response) { return response.json(); })
        .then(function(data) {
            isLoadingMoreData = false;
            if (data.success && data.data.length > 0) {
                var existingTimes = {};
                for (var i = 0; i < candleData.length; i++) {
                    existingTimes[candleData[i].execution_datetime] = true;
                }
                var newData = data.data.filter(function(d) {
                    return !existingTimes[d.execution_datetime];
                });

                if (newData.length === 0) {
                    allDataLoaded = true;
                    return;
                }

                if (newData.length < 5) {
                    allDataLoaded = true;
                }

                var prependedCount = newData.length;

                // 최대 캔들 수 제한
                var room = MAX_CANDLES - candleData.length;
                if (room <= 0) {
                    allDataLoaded = true;
                    return;
                }
                if (newData.length > room) {
                    newData = newData.slice(newData.length - room);
                    prependedCount = newData.length;
                    allDataLoaded = true;
                }

                candleData = newData.concat(candleData);
                prependChartData(prependedCount);
            } else {
                allDataLoaded = true;
            }
        })
        .catch(function(error) {
            isLoadingMoreData = false;
            console.error('추가 과거 데이터 로드 실패:', error);
        });
}

function prependChartData(prependedCount) {
    if (!stockChart) return;

    var newChartData = prepareChartData(candleData, currentChartType);

    // 현재 보이는 범위 인덱스 저장
    var xScale = stockChart.scales.x;
    var oldMinIdx = Math.max(0, Math.round(xScale.min));
    var oldMaxIdx = Math.min(stockChart.data.labels.length - 1, Math.round(xScale.max));

    // 데이터 업데이트
    stockChart.data.labels = newChartData.labels;
    for (var i = 0; i < newChartData.datasets.length; i++) {
        if (stockChart.data.datasets[i]) {
            stockChart.data.datasets[i].data = newChartData.datasets[i].data;
            if (newChartData.datasets[i].backgroundColor) {
                stockChart.data.datasets[i].backgroundColor = newChartData.datasets[i].backgroundColor;
            }
        }
    }
    stockChart._ohlcData = newChartData._ohlcData || null;

    // 거래량 y2 축 max 재계산
    var maxVol = 0;
    for (var i = 0; i < candleData.length; i++) {
        var v = Math.max(
            parseFloat(candleData[i].execution_non_volume || 0),
            parseFloat(candleData[i].execution_ask_volume || 0) + parseFloat(candleData[i].execution_bid_volume || 0)
        );
        if (v > maxVol) maxVol = v;
    }
    if (maxVol > 0) {
        stockChart.options.scales.y2.max = maxVol * 5;
    }

    // 줌 위치 보정: 추가된 캔들 수만큼 인덱스 시프트 (결정적 산술)
    var newMinIdx = oldMinIdx + prependedCount;
    var newMaxIdx = oldMaxIdx + prependedCount;

    // 스케일 범위 지정 후 업데이트
    stockChart.options.scales.x.min = newMinIdx;
    stockChart.options.scales.x.max = newMaxIdx;
    stockChart.update('none');

    updateYAxisRange();
    updateZoomResetButton();
}

/* ========================================
   차트 타입 변경
   ======================================== */
function setChartType(chartType, triggerEl) {
    currentChartType = chartType;
    
    document.querySelectorAll('.chart-type-btn').forEach(function(btn) { btn.classList.remove('active'); });
    var targetEl = triggerEl || (typeof event !== 'undefined' ? event.target : null);
    if (targetEl && targetEl.classList) targetEl.classList.add('active');
    
    initChart();
}

/* ========================================
   체결 정보
   ======================================== */
function refreshExecutions() {
    fetch('/stocks/api/executions?code=' + encodeURIComponent(stockCode) + '&limit=50' + getMarketParam())
        .then(function(response) { return response.json(); })
        .then(function(data) {
            if (data.success) {
                updateExecutionList(data.data);
                syncExecutionHeaderSpacing();
            }
        })
        .catch(function(error) { console.error('체결 정보 로드 실패:', error); });
}

function syncExecutionHeaderSpacing() {
    var executionBodyEl = document.getElementById('executionList');
    if (executionBodyEl) {
        var headerEl = executionBodyEl.parentElement ? executionBodyEl.parentElement.querySelector('.execution-header') : null;
        if (headerEl) {
            var scrollbarWidth = executionBodyEl.offsetWidth - executionBodyEl.clientWidth;
            headerEl.style.paddingRight = (15 + Math.max(0, scrollbarWidth)) + 'px';
        }
    }
    var overlayBodyEl = document.getElementById('executionOverlayList');
    if (overlayBodyEl) {
        var overlayHeaderEl = overlayBodyEl.parentElement ? overlayBodyEl.parentElement.querySelector('.execution-header') : null;
        if (overlayHeaderEl) {
            var sw = overlayBodyEl.offsetWidth - overlayBodyEl.clientWidth;
            overlayHeaderEl.style.paddingRight = (15 + Math.max(0, sw)) + 'px';
        }
    }
}

function updateExecutionList(executions) {
    var executionListEl = document.getElementById('executionList');
    var overlayListEl = document.getElementById('executionOverlayList');
    if (!executionListEl) return;
    
    if (executions.length === 0) {
        var emptyHtml = '<div class="execution-no-data">체결 데이터가 없습니다.</div>';
        executionListEl.innerHTML = emptyHtml;
        if (overlayListEl) overlayListEl.innerHTML = emptyHtml;
        return;
    }
    
    var html = '';
    for (var i = 0; i < executions.length; i++) {
        var exec = executions[i];
        var isBuy = parseFloat(exec.execution_bid_volume) > parseFloat(exec.execution_ask_volume);
        var volume = Math.max(
            parseFloat(exec.execution_non_volume || 0),
            parseFloat(exec.execution_bid_volume || 0),
            parseFloat(exec.execution_ask_volume || 0)
        );
        
        html += '<div class="execution-item ' + (isBuy ? 'buy' : 'sell') + '">' +
                    '<div class="exec-time">' + formatTime(exec.execution_datetime) + '</div>' +
                    '<div class="exec-price">' + formatPrice(exec.execution_price) + '</div>' +
                    '<div class="exec-volume">' + formatNumber(volume) + '</div>' +
                    '<div class="exec-type">' + (isBuy ? '매수' : '매도') + '</div>' +
                '</div>';
    }
    
    executionListEl.innerHTML = html;
    if (overlayListEl) overlayListEl.innerHTML = html;
}

/* ========================================
   날짜/시간 유틸리티
   ======================================== */
function formatDateTime(datetime) {
    var date = new Date(datetime.replace(' ', 'T'));
    if (isNaN(date.getTime())) return datetime;
    
    var year = date.getFullYear();
    var month = String(date.getMonth() + 1).padStart(2, '0');
    var day = String(date.getDate()).padStart(2, '0');
    var hours = String(date.getHours()).padStart(2, '0');
    var minutes = String(date.getMinutes()).padStart(2, '0');

    switch (currentTimeframe) {
        case '1M': return year + '-' + month;
        case '1w': return month + '/' + day;
        case '1d': return month + '/' + day;
        default:   return month + '/' + day + ' ' + hours + ':' + minutes;
    }
}

function openExecutionOverlay() {
    var backdrop = document.getElementById('executionOverlayBackdrop');
    var overlay = document.getElementById('executionOverlay');
    if (!backdrop || !overlay) return;

    var inlineList = document.getElementById('executionList');
    var overlayList = document.getElementById('executionOverlayList');
    if (inlineList && overlayList) overlayList.innerHTML = inlineList.innerHTML;

    backdrop.classList.add('active');
    overlay.classList.add('active');
    document.body.style.overflow = 'hidden';
    syncExecutionHeaderSpacing();
}

function closeExecutionOverlay() {
    var backdrop = document.getElementById('executionOverlayBackdrop');
    var overlay = document.getElementById('executionOverlay');
    if (!backdrop || !overlay) return;
    overlay.classList.remove('active');
    backdrop.classList.remove('active');
    document.body.style.overflow = '';
}

function formatTime(datetime) {
    var date = new Date(datetime);
    var hours = String(date.getHours()).padStart(2, '0');
    var minutes = String(date.getMinutes()).padStart(2, '0');
    var seconds = String(date.getSeconds()).padStart(2, '0');
    return hours + ':' + minutes + ':' + seconds;
}

function formatDateForAPI(date) {
    var year = date.getFullYear();
    var month = String(date.getMonth() + 1).padStart(2, '0');
    var day = String(date.getDate()).padStart(2, '0');
    var hours = String(date.getHours()).padStart(2, '0');
    var minutes = String(date.getMinutes()).padStart(2, '0');
    return year + '-' + month + '-' + day + ' ' + hours + ':' + minutes + ':00';
}

function formatNumber(num) {
    return new Intl.NumberFormat('ko-KR').format(num);
}

// 자동 새로고침 (30초마다, 페이지가 보일 때만)
setInterval(function() {
    if (document.visibilityState === 'visible' && typeof stockCode !== 'undefined' && document.getElementById('executionList')) {
        refreshExecutions();
    }
}, 30000);

/* ========================================
   기간 선택 휠 컨트롤
   ======================================== */
function setupPeriodWheelControl() {
    var periodSelect = document.getElementById('periodSelect');
    if (!periodSelect) return;
    
    var periodOptions = ['10M', '30M', '1H', '3H', '6H', '1D', '1W', '1M'];
    
    periodSelect.addEventListener('wheel', function(e) {
        e.preventDefault();
        
        var currentValue = periodSelect.value;
        var currentIndex = periodOptions.indexOf(currentValue);
        if (currentIndex === -1) return;
        
        var newIndex;
        if (e.deltaY < 0) {
            newIndex = Math.min(currentIndex + 1, periodOptions.length - 1);
        } else {
            newIndex = Math.max(currentIndex - 1, 0);
        }
        
        var newValue = periodOptions[newIndex];
        if (newValue !== currentValue) {
            periodSelect.value = newValue;
            loadChartData(newValue);
        }
    });
}
