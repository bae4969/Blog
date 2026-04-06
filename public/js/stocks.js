/**
 * 주식 차트 및 체결 정보 관리 JavaScript
 * - 크로스헤어 인터랙션, 거래량 바, 줌/팬, 반응형 캔들 너비
 */

let stockChart = null;
let initialXMin = null;
let initialXMax = null;
let currentChartType = 'candle';
let currentPeriod = '1D';
let currentTimeframe = '1d';
let currentVisibleCandleCount = 60;
let visibleRangeMinLimit = 0;
let visibleRangeMaxLimit = null;
let displayedCandleData = [];
let isLoadingMoreData = false;
let allDataLoaded = false;
let useLogScale = false;
let yAxisRangeRafId = null;
const CHART_LOG_SCALE_STORAGE_KEY = 'stockChart.useLogScale';
const MAX_CANDLES = 360;

function loadLogScalePreference() {
    try {
        return window.localStorage.getItem(CHART_LOG_SCALE_STORAGE_KEY) === 'true';
    } catch (error) {
        return false;
    }
}

function saveLogScalePreference(enabled) {
    try {
        window.localStorage.setItem(CHART_LOG_SCALE_STORAGE_KEY, enabled ? 'true' : 'false');
    } catch (error) {}
}

function syncLogScaleToggle() {
    var toggleEl = document.getElementById('logScaleToggle');
    if (toggleEl) {
        toggleEl.checked = useLogScale;
    }
}

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
    get zoomDragBg()  { return getCSSVar('--chart-zoom-drag-bg')   || 'rgba(33,150,243,0.15)'; },
    get zoomDragBorder() { return getCSSVar('--chart-zoom-drag-border') || 'rgba(33,150,243,0.6)'; },
    get textPrimary() { return getCSSVar('--text-primary')         || '#fff';    },
    get textMuted()   { return getCSSVar('--text-muted')           || '#9aa0a6'; },
    get textSecondary() { return getCSSVar('--text-secondary')     || '#C3C3C3'; },
    get border()      { return getCSSVar('--border-color')         || '#464646'; },
    get primary()     { return getCSSVar('--primary-color')        || '#4CAF50'; },
    get sma5()        { return getCSSVar('--chart-sma5-color'); },
    get sma20()       { return getCSSVar('--chart-sma20-color'); },
    get sma60()       { return getCSSVar('--chart-sma60-color'); },
    get bbUpper()     { return getCSSVar('--chart-bb-upper-color'); },
    get bbMiddle()    { return getCSSVar('--chart-bb-middle-color'); },
    get bbLower()     { return getCSSVar('--chart-bb-lower-color'); },
    get bbFill()      { return getCSSVar('--chart-bb-fill'); },
    get volumeMa20()  { return getCSSVar('--chart-volume-ma20-color'); },
};

const INDICATOR_PERIODS = {
    smaFast: 5,
    smaMid: 20,
    smaSlow: 60,
    bbPeriod: 20,
    bbStdDev: 2,
    volumeMa: 20
};

const INDICATOR_WARMUP_COUNT = Math.max(
    INDICATOR_PERIODS.smaSlow,
    INDICATOR_PERIODS.bbPeriod,
    INDICATOR_PERIODS.volumeMa
);

function setShiftZoomArmedState(isArmed) {
    // Shift 키 상태 표시 — 현재 사용하지 않음
}

/* ========================================
   통화 포맷팅
   ======================================== */
function getCurrencyPrefix() {
    return (typeof isUSMarket !== 'undefined' && isUSMarket) ? '$' : '';
}
function getCurrencySuffix() {
    return (typeof isUSMarket !== 'undefined' && isUSMarket) ? '' : '원';
}

function buildFixedLogarithmicTicks(scale, tickCount) {
    if (!scale || !isFiniteNumber(scale.min) || !isFiniteNumber(scale.max) || scale.min <= 0 || scale.max <= 0) {
        return scale && Array.isArray(scale.ticks) ? scale.ticks : [];
    }

    var safeTickCount = Math.max(2, tickCount || 2);
    var logMin = Math.log(scale.min);
    var logMax = Math.log(scale.max);
    var ticks = [];
    var used = Object.create(null);

    if (Math.abs(logMax - logMin) < 0.0000001) {
        return [{ value: scale.min }, { value: scale.max }];
    }

    for (var i = 0; i < safeTickCount; i++) {
        var ratio = safeTickCount === 1 ? 0 : i / (safeTickCount - 1);
        var rawValue = Math.exp(logMin + ((logMax - logMin) * ratio));
        var key = rawValue.toPrecision(12);
        if (used[key]) continue;
        used[key] = true;
        ticks.push({ value: rawValue });
    }

    if (ticks.length === 0) {
        return [{ value: scale.min }, { value: scale.max }];
    }

    ticks[0].value = scale.min;
    ticks[ticks.length - 1].value = scale.max;
    return ticks;
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
        var ohlc = chart._ohlcData || chart.data._ohlcData;
        if (!ohlc || ohlc.length === 0) return;

        var ctx = chart.ctx;
        var area = chart.chartArea;
        var xScale = chart.scales.x;
        var yScale = chart.scales.y;
        if (!area || !xScale || !yScale) return;

        // 캔들 데이터셋의 실제 렌더 포인트 x 좌표를 사용해
        // 지표 라인과 x축 정렬을 완전히 동일하게 맞춘다.
        var candleDatasetIndex = -1;
        for (var di = 0; di < chart.data.datasets.length; di++) {
            if (chart.data.datasets[di] && chart.data.datasets[di].label === '캔들') {
                candleDatasetIndex = di;
                break;
            }
        }

        var candleMeta = candleDatasetIndex >= 0 ? chart.getDatasetMeta(candleDatasetIndex) : null;
        var points = (candleMeta && candleMeta.data) ? candleMeta.data : null;
        if (!points || points.length === 0) return;

        // 인접 포인트 간 픽셀 거리로 슬롯 폭 계산
        var slotWidth;
        if (points.length > 1 && typeof points[0].x === 'number' && typeof points[1].x === 'number') {
            slotWidth = Math.abs(points[1].x - points[0].x);
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
            var point = points[i];
            if (!point || typeof point.x !== 'number') continue;
            var x = Math.round(point.x);

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
    useLogScale = loadLogScalePreference();
    syncLogScaleToggle();

    loadChartModules().then(() => {
        if (typeof Chart !== 'undefined') {
            Chart.register(crosshairPlugin, candleDrawPlugin);
        }
        loadChartData(currentPeriod);
        loadInitialExecutions();
    });

    var chartCanvas = document.getElementById('stockChart');
    if (chartCanvas) {
        chartCanvas.addEventListener('dblclick', function() {
            resetChartZoom();
        });
    }

    syncExecutionHeaderSpacing();
    window.addEventListener('resize', syncExecutionHeaderSpacing);

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Shift') setShiftZoomArmedState(true);
        if (e.key === 'Escape') closeExecutionOverlay();
    });

    document.addEventListener('keyup', function(e) {
        if (e.key === 'Shift') setShiftZoomArmedState(false);
    });

    window.addEventListener('blur', function() {
        setShiftZoomArmedState(false);
    });

    document.addEventListener('visibilitychange', function() {
        if (document.visibilityState !== 'visible') {
            setShiftZoomArmedState(false);
        }
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
    fetch('/stocks/api/executions?code=' + encodeURIComponent(stockCode) + '&limit=50' + getMarketParam(), {
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        })
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

function hasZoomSupport() {
    if (typeof Chart === 'undefined' || !Chart.registry || typeof Chart.registry.getPlugin !== 'function') return false;
    try { return !!Chart.registry.getPlugin('zoom'); } catch(e) { return false; }
}

async function loadChartModules() {
    try {
        if (typeof Chart === 'undefined') await loadScript('/vendor/chart.umd.min.js');
        if (!hasCandlestickSupport()) {
            try { await loadScript('/vendor/chartjs-chart-financial.min.js'); }
            catch (e) { console.warn('캔들 플러그인 로드 실패, 라인 차트로 대체합니다.', e); }
        }
        if (!hasZoomSupport()) {
            try {
                if (typeof Hammer === 'undefined') await loadScript('/vendor/hammer.min.js');
                await loadScript('/vendor/chartjs-plugin-zoom.min.js');
            } catch (e) { console.warn('줌 플러그인 로드 실패:', e); }
        }
    } catch (error) { console.error('차트 모듈 로드 실패:', error); throw error; }
}

/* ========================================
   줌 리셋 버튼
   ======================================== */
function updateZoomResetButton() {
    // 리셋 버튼은 항상 보이므로 별도 토글 불필요
}

function resetChartZoom() {
    if (!stockChart) return;
    if (typeof stockChart.resetZoom === 'function') {
        stockChart.resetZoom();
    }
    // 초기 x 범위(최근 구간)로 복원
    if (stockChart.options.scales.x) {
        if (initialXMin !== null) {
            stockChart.options.scales.x.min = initialXMin;
        } else {
            delete stockChart.options.scales.x.min;
        }
        if (initialXMax !== null) {
            stockChart.options.scales.x.max = initialXMax;
        } else {
            delete stockChart.options.scales.x.max;
        }
    }
    stockChart.update('none');
    updateZoomResetButton();
    updateYAxisRange();
}

function enforceVisibleRangeBounds() {
    if (!stockChart || !stockChart.options || !stockChart.options.scales || !stockChart.options.scales.x) return;
    if (stockChart.options.plugins && stockChart.options.plugins.zoom && stockChart.options.plugins.zoom.limits) {
        stockChart.options.plugins.zoom.limits.x.min = visibleRangeMinLimit;
        stockChart.options.plugins.zoom.limits.x.max = visibleRangeMaxLimit;
    }
}

function calculatePriceAxisBounds(range) {
    if (!range || !isFiniteNumber(range.min) || !isFiniteNumber(range.max)) return null;

    if (useLogScale) {
        // 로그 스케일: ln 공간에서 패딩 계산
        var safeMin = Math.max(range.min, 0.01);
        var safeMax = Math.max(range.max, 0.02);
        var logMin = Math.log(safeMin);
        var logMax = Math.log(safeMax);
        var logSpan = logMax - logMin;
        var logBasePadding = logSpan * 0.08;
        if (logBasePadding === 0) logBasePadding = 0.02;

        var logMinPadding = logBasePadding * 1.8;
        var logMaxPadding = logBasePadding * 0.75;

        return {
            min: Math.exp(logMin - logMinPadding),
            max: Math.exp(logMax + logMaxPadding),
            threshold: Math.exp(logBasePadding * 0.1)
        };
    }

    var span = range.max - range.min;
    var basePadding = span * 0.08;
    if (basePadding === 0) basePadding = range.max * 0.02 || 1;

    // 거래량 패널과 시각적으로 분리되도록 하단 패딩을 더 크게 부여
    var minPadding = basePadding * 1.8;
    var maxPadding = basePadding * 0.75;

    return {
        min: Math.max(0, range.min - minPadding),
        max: range.max + maxPadding,
        threshold: basePadding * 0.1
    };
}

function resetYAxisRange() {
    if (!stockChart) return;
    var labels = (stockChart.data && stockChart.data.labels) ? stockChart.data.labels : [];
    var total = labels.length;
    if (total === 0) return;

    var range = getVisiblePriceRange(0, total - 1);
    if (!range) return;

    var bounds = calculatePriceAxisBounds(range);
    if (!bounds) return;
    stockChart.options.scales.y.min = bounds.min;
    stockChart.options.scales.y.max = bounds.max;
    requestAnimationFrame(function() {
        if (stockChart) stockChart.update('none');
    });
}

function getVisibleIndexRangeFromPixels() {
    if (!stockChart || !stockChart.chartArea) return null;

    var area = stockChart.chartArea;
    var datasets = (stockChart.data && stockChart.data.datasets) ? stockChart.data.datasets : [];
    for (var di = 0; di < datasets.length; di++) {
        var ds = datasets[di];
        if (!ds || ds.yAxisID === 'y2') continue;
        var meta = stockChart.getDatasetMeta(di);
        if (!meta || !meta.data || meta.data.length === 0) continue;

        var minIdx = Infinity;
        var maxIdx = -Infinity;
        for (var i = 0; i < meta.data.length; i++) {
            var point = meta.data[i];
            if (!point || typeof point.x !== 'number') continue;
            if (point.x < area.left || point.x > area.right) continue;
            if (i < minIdx) minIdx = i;
            if (i > maxIdx) maxIdx = i;
        }

        if (isFinite(minIdx) && isFinite(maxIdx)) {
            return { min: minIdx, max: maxIdx };
        }
    }

    return null;
}

function scheduleYAxisRangeUpdate(forceUpdate) {
    if (yAxisRangeRafId !== null) {
        cancelAnimationFrame(yAxisRangeRafId);
    }
    yAxisRangeRafId = requestAnimationFrame(function() {
        yAxisRangeRafId = null;
        updateYAxisRange(forceUpdate);
    });
}

/* ========================================
   Y축 범위 동적 조절 (보이는 캔들 기준)
   ======================================== */
function updateYAxisRange(forceUpdate) {
    if (!stockChart) return;
    forceUpdate = !!forceUpdate;
    var xScale = stockChart.scales ? stockChart.scales.x : null;
    if (!xScale) return;

    var labels = (stockChart.data && stockChart.data.labels) ? stockChart.data.labels : [];
    var total = labels.length;
    if (total === 0) return;

    var visibleMin = 0;
    var visibleMax = total - 1;
    var pixelRange = getVisibleIndexRangeFromPixels();
    if (pixelRange) {
        visibleMin = Math.max(0, pixelRange.min);
        visibleMax = Math.min(total - 1, pixelRange.max);
    } else if (typeof xScale.min === 'number' && typeof xScale.max === 'number'
        && !isNaN(xScale.min) && !isNaN(xScale.max)) {
        visibleMin = Math.max(0, Math.floor(xScale.min));
        visibleMax = Math.min(total - 1, Math.ceil(xScale.max));
    }

    var range = getVisiblePriceRange(visibleMin, visibleMax);
    if (!range) return;

    var bounds = calculatePriceAxisBounds(range);
    if (!bounds) return;
    var newMin = bounds.min;
    var newMax = bounds.max;

    var yScale = stockChart.options.scales.y;
    if (forceUpdate
        || Math.abs((yScale.min || 0) - newMin) > bounds.threshold
        || Math.abs((yScale.max || 0) - newMax) > bounds.threshold) {
        yScale.min = newMin;
        yScale.max = newMax;
        requestAnimationFrame(function() {
            if (stockChart) stockChart.update('none');
        });
    }
}

function isFiniteNumber(value) {
    return typeof value === 'number' && isFinite(value);
}

function calculateSMA(values, period) {
    var result = [];
    for (var i = 0; i < values.length; i++) {
        if (i < period - 1) {
            result.push(null);
            continue;
        }

        var sum = 0;
        var valid = true;
        for (var j = i - period + 1; j <= i; j++) {
            var value = parseFloat(values[j]);
            if (!isFiniteNumber(value)) {
                valid = false;
                break;
            }
            sum += value;
        }

        result.push(valid ? (sum / period) : null);
    }

    return result;
}

function calculateBollingerBands(values, period, stdMultiplier) {
    var upper = [];
    var middle = [];
    var lower = [];

    for (var i = 0; i < values.length; i++) {
        if (i < period - 1) {
            upper.push(null);
            middle.push(null);
            lower.push(null);
            continue;
        }

        var windowValues = [];
        var hasInvalid = false;
        for (var j = i - period + 1; j <= i; j++) {
            var value = parseFloat(values[j]);
            if (!isFiniteNumber(value)) {
                hasInvalid = true;
                break;
            }
            windowValues.push(value);
        }

        if (hasInvalid) {
            middle.push(null);
            upper.push(null);
            lower.push(null);
            continue;
        }

        var avg = 0;
        for (var k = 0; k < windowValues.length; k++) {
            avg += windowValues[k];
        }
        avg = avg / period;

        var varianceSum = 0;
        for (var m = 0; m < windowValues.length; m++) {
            varianceSum += Math.pow(windowValues[m] - avg, 2);
        }
        var stdDev = Math.sqrt(varianceSum / period);

        middle.push(avg);
        upper.push(avg + (stdDev * stdMultiplier));
        lower.push(avg - (stdDev * stdMultiplier));
    }

    return {
        upper: upper,
        middle: middle,
        lower: lower
    };
}

function getVisiblePriceRange(startIndex, endIndex) {
    if (!stockChart) return null;

    var lo = Infinity;
    var hi = -Infinity;
    var i;
    var value;

    var ohlc = stockChart._ohlcData;
    if (ohlc && ohlc.length > 0) {
        for (i = startIndex; i <= endIndex; i++) {
            if (!ohlc[i]) continue;
            if (isFiniteNumber(ohlc[i].l) && ohlc[i].l < lo) lo = ohlc[i].l;
            if (isFiniteNumber(ohlc[i].h) && ohlc[i].h > hi) hi = ohlc[i].h;
        }
    }

    var datasets = (stockChart.data && stockChart.data.datasets) ? stockChart.data.datasets : [];
    for (var dsIdx = 0; dsIdx < datasets.length; dsIdx++) {
        var dataset = datasets[dsIdx];
        if (dataset.yAxisID === 'y2') continue;
        var dsLabel = dataset.label || '';
        if (dsLabel.indexOf('SMA') === 0 || dsLabel.indexOf('BB ') === 0) continue;
        if (!dataset.data || !Array.isArray(dataset.data)) continue;

        for (i = startIndex; i <= endIndex; i++) {
            value = dataset.data[i];
            if (!isFiniteNumber(value)) continue;
            if (value < lo) lo = value;
            if (value > hi) hi = value;
        }
    }

    if (!isFinite(lo) || !isFinite(hi)) {
        return null;
    }

    return { min: lo, max: hi };
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

    // 초기 X축 범위 먼저 계산
    var totalLabels = chartData.labels ? chartData.labels.length : 0;
    initialXMax = totalLabels > 0 ? totalLabels - 1 : null;
    initialXMin = null;

    if (totalLabels > currentVisibleCandleCount) {
        initialXMin = totalLabels - currentVisibleCandleCount;
    }

    visibleRangeMinLimit = Math.max(0, totalLabels - MAX_CANDLES);
    visibleRangeMaxLimit = initialXMax;

    // 데이터 범위 계산 (보이는 캔들 범위 기준)
    let dataRange = null;
    var visStart = (typeof initialXMin === 'number') ? initialXMin : 0;
    var visEnd = (typeof initialXMax === 'number') ? initialXMax : totalLabels - 1;
    var lo = Infinity;
    var hi = -Infinity;

    if (chartData._ohlcData && chartData._ohlcData.length > 0) {
        for (var ri = visStart; ri <= visEnd; ri++) {
            var od = chartData._ohlcData[ri];
            if (!od) continue;
            if (isFiniteNumber(od.l) && od.l < lo) lo = od.l;
            if (isFiniteNumber(od.h) && od.h > hi) hi = od.h;
        }
    }

    if (chartData.datasets) {
        for (var di = 0; di < chartData.datasets.length; di++) {
            var ds = chartData.datasets[di];
            if (ds.yAxisID === 'y2') continue;
            var dsLbl = ds.label || '';
            if (dsLbl.indexOf('SMA') === 0 || dsLbl.indexOf('BB ') === 0) continue;
            if (!ds.data || !Array.isArray(ds.data)) continue;
            for (var ri = visStart; ri <= visEnd; ri++) {
                var val = ds.data[ri];
                if (!isFiniteNumber(val)) continue;
                if (val < lo) lo = val;
                if (val > hi) hi = val;
            }
        }
    }

    if (isFinite(lo) && isFinite(hi)) {
        dataRange = { min: lo, max: hi };
    }

    stockChart = new Chart(ctx, {
        type: 'line',
        data: chartData,
        options: getChartOptions(currentChartType, dataRange, {
            min: initialXMin,
            max: initialXMax
        })
    });
    stockChart._ohlcData = chartData._ohlcData || null;
    stockChart._indicatorSeries = chartData._indicatorSeries || null;
    enforceVisibleRangeBounds();
    updateZoomResetButton();
    requestAnimationFrame(function() {
        requestAnimationFrame(function() {
            updateYAxisRange(true);
        });
    });
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
    var fullData = Array.isArray(data) ? data : [];
    var displayCount = Math.min(MAX_CANDLES, fullData.length);
    var displayStartIndex = Math.max(0, fullData.length - displayCount);
    displayedCandleData = fullData.slice(displayStartIndex);

    var labels = displayedCandleData.map(function(d) { return formatDateTime(d.execution_datetime); });
    var closePrices = displayedCandleData.map(function(d) { return parseFloat(d.execution_close); });

    // 거래량 데이터 (양봉/음봉 색상 분기)
    var volumes = displayedCandleData.map(function(d) {
        return Math.max(
            parseFloat(d.execution_non_volume || 0),
            parseFloat(d.execution_ask_volume || 0) + parseFloat(d.execution_bid_volume || 0)
        );
    });
    var volumeColors = displayedCandleData.map(function(d) {
        var open = parseFloat(d.execution_open);
        var close = parseFloat(d.execution_close);
        return close >= open ? chartColors.volumeUp : chartColors.volumeDown;
    });

    var fullClosePrices = fullData.map(function(d) { return parseFloat(d.execution_close); });
    var fullVolumes = fullData.map(function(d) {
        return Math.max(
            parseFloat(d.execution_non_volume || 0),
            parseFloat(d.execution_ask_volume || 0) + parseFloat(d.execution_bid_volume || 0)
        );
    });

    var volumeDataset = {
        label: '거래량',
        type: 'bar',
        data: volumes,
        backgroundColor: volumeColors,
        yAxisID: 'y2',
        order: 5,
        barPercentage: 0.6,
        categoryPercentage: 0.9
    };

    if (chartType === 'line') {
        var lineDatasets = [
            {
                label: '종가',
                data: closePrices,
                borderColor: chartColors.primary,
                backgroundColor: getCSSVar('--primary-bg-light'),
                fill: true,
                tension: 0.3,
                pointRadius: 0,
                pointHitRadius: 8,
                borderWidth: 2,
                order: 1
            }
        ];

        return {
            labels: labels,
            datasets: lineDatasets,
            _indicatorSeries: {
                priceSeries: [],
                volumeSeries: []
            }
        };
    }

    var sma5 = calculateSMA(fullClosePrices, INDICATOR_PERIODS.smaFast).slice(displayStartIndex);
    var sma20 = calculateSMA(fullClosePrices, INDICATOR_PERIODS.smaMid).slice(displayStartIndex);
    var sma60 = calculateSMA(fullClosePrices, INDICATOR_PERIODS.smaSlow).slice(displayStartIndex);
    var bollingerFull = calculateBollingerBands(fullClosePrices, INDICATOR_PERIODS.bbPeriod, INDICATOR_PERIODS.bbStdDev);
    var bollinger = {
        upper: bollingerFull.upper.slice(displayStartIndex),
        middle: bollingerFull.middle.slice(displayStartIndex),
        lower: bollingerFull.lower.slice(displayStartIndex)
    };
    var volumeMa20 = calculateSMA(fullVolumes, INDICATOR_PERIODS.volumeMa).slice(displayStartIndex);

    var priceIndicatorDatasets = [
        {
            label: 'SMA5',
            data: sma5,
            borderColor: chartColors.sma5,
            borderWidth: 1.1,
            fill: false,
            tension: 0,
            pointRadius: 0,
            pointHitRadius: 8,
            order: 2
        },
        {
            label: 'SMA20',
            data: sma20,
            borderColor: chartColors.sma20,
            borderWidth: 1.15,
            fill: false,
            tension: 0,
            pointRadius: 0,
            pointHitRadius: 8,
            order: 2
        },
        {
            label: 'SMA60',
            data: sma60,
            borderColor: chartColors.sma60,
            borderWidth: 1.15,
            fill: false,
            tension: 0,
            pointRadius: 0,
            pointHitRadius: 8,
            order: 2
        },
        {
            label: 'BB 상단',
            data: bollinger.upper,
            borderColor: chartColors.bbUpper,
            borderWidth: 0.9,
            fill: false,
            tension: 0,
            pointRadius: 0,
            pointHitRadius: 8,
            order: 2
        },
        {
            label: 'BB 하단',
            data: bollinger.lower,
            borderColor: chartColors.bbLower,
            borderWidth: 0.9,
            fill: '-1',
            backgroundColor: chartColors.bbFill,
            tension: 0,
            pointRadius: 0,
            pointHitRadius: 8,
            order: 2
        },
        {
            label: 'BB 중앙',
            data: bollinger.middle,
            borderColor: chartColors.bbMiddle,
            borderWidth: 0.9,
            borderDash: [4, 3],
            fill: false,
            tension: 0,
            pointRadius: 0,
            pointHitRadius: 8,
            order: 2
        }
    ];

    var volumeMaDataset = {
        label: '거래량 MA20',
        type: 'line',
        data: volumeMa20,
        yAxisID: 'y2',
        borderColor: chartColors.volumeMa20,
        borderWidth: 1,
        pointRadius: 0,
        pointHitRadius: 8,
        fill: false,
        tension: 0,
        order: 4
    };

    // 커스텀 캔들 렌더링 (candleDrawPlugin)
    // 투명 라인 (y축 스케일링 + 툴팁 인터랙션) + 거래량 바 + OHLC 데이터
    var ohlcData = displayedCandleData.map(function(d) {
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
                data: closePrices,
                borderWidth: 0,
                borderColor: 'transparent',
                pointRadius: 0,
                pointHitRadius: 10,
                fill: false,
                order: 1
            },
        ].concat(priceIndicatorDatasets, [volumeMaDataset, volumeDataset]),
        _ohlcData: ohlcData,
        _indicatorSeries: {
            priceSeries: [sma5, sma20, sma60, bollinger.upper, bollinger.middle, bollinger.lower],
            volumeSeries: [volumeMa20]
        }
    };
}

/* ========================================
   차트 옵션 (크로스헤어, 줌/팬, 거래량 y2 축)
   ======================================== */
function getChartOptions(chartType, dataRange, initialRange) {
    chartType = chartType || 'line';
    dataRange = dataRange || null;
    initialRange = initialRange || null;

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
                padding: { left: 32, right: 32, top: 12, bottom: 12 },
                cornerRadius: 8,
                displayColors: false,
                titleFont: { size: 13, weight: '600' },
                bodyFont: { size: 12 },
                bodySpacing: 6,
                filter: function(tooltipItem) {
                    var lbl = tooltipItem.dataset.label;
                    if (lbl === '거래량 MA20') return false;
                    if (lbl && (lbl.indexOf('SMA') === 0 || lbl.indexOf('BB ') === 0)) return false;
                    return true;
                },
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
                            return context.dataset.label + ': ' + formatPrice(context.parsed.y);
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
                type: useLogScale ? 'logarithmic' : 'linear',
                position: 'right',
                beginAtZero: false,
                afterBuildTicks: function(axis) {
                    if (!useLogScale) return;
                    axis.ticks = buildFixedLogarithmicTicks(
                        axis,
                        window.innerWidth <= 480 ? 9 : 14
                    );
                },
                grid: {
                    color: chartColors.grid,
                    drawTicks: false
                },
                border: { color: chartColors.grid },
                ticks: {
                    color: chartColors.textMuted,
                    maxTicksLimit: useLogScale ? 14 : 10,
                    padding: 8,
                    font: { size: 11 },
                    callback: function(value) {
                        return formatPrice(value);
                    }
                }
            },
            y2: {
                display: chartType !== 'line',
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
    var volumeScaleSource = displayedCandleData && displayedCandleData.length > 0 ? displayedCandleData : candleData;
    if (volumeScaleSource && volumeScaleSource.length > 0) {
        var maxVol = 0;
        for (var i = 0; i < volumeScaleSource.length; i++) {
            var v = Math.max(
                parseFloat(volumeScaleSource[i].execution_non_volume || 0),
                parseFloat(volumeScaleSource[i].execution_ask_volume || 0) + parseFloat(volumeScaleSource[i].execution_bid_volume || 0)
            );
            if (v > maxVol) maxVol = v;
        }
        if (maxVol > 0) {
            options.scales.y2.max = maxVol * 5;
        }
    }

    // 데이터 범위가 제공되면 y축 범위 설정
    if (dataRange && dataRange.min !== undefined && dataRange.max !== undefined) {
        var initBounds = calculatePriceAxisBounds(dataRange);
        if (initBounds) {
            options.scales.y.min = initBounds.min;
            options.scales.y.max = initBounds.max;
        }
    }

    if (initialRange) {
        if (typeof initialRange.min === 'number' && !isNaN(initialRange.min)) {
            options.scales.x.min = initialRange.min;
        }
        if (typeof initialRange.max === 'number' && !isNaN(initialRange.max)) {
            options.scales.x.max = initialRange.max;
        }
    }

    // 줌/팬 설정 (플러그인이 로드된 경우에만)
    if (hasZoomPlugin) {
        var hasTouchSupport = 'ontouchstart' in window || navigator.maxTouchPoints > 0;
        var isCoarsePointer = window.matchMedia && window.matchMedia('(pointer: coarse)').matches;
        var useTouchInteractions = hasTouchSupport && isCoarsePointer;
        options.plugins.zoom = {
            pan: {
                enabled: true,
                mode: 'x',
                onPanComplete: function() {
                    updateZoomResetButton();
                    scheduleYAxisRangeUpdate();
                    checkAndLoadMoreData();
                }
            },
            zoom: {
                wheel: { enabled: true, speed: 0.1, modifierKey: 'ctrl' },
                pinch: { enabled: true },
                drag: useTouchInteractions ? { enabled: false } : {
                    enabled: true,
                    modifierKey: 'shift',
                    backgroundColor: chartColors.zoomDragBg,
                    borderColor: chartColors.zoomDragBorder,
                    borderWidth: 1
                },
                mode: 'x',
                onZoomComplete: function() {
                    updateZoomResetButton();
                    scheduleYAxisRangeUpdate();
                    checkAndLoadMoreData();
                }
            },
            limits: {
                x: {
                    minRange: 5,
                    min: visibleRangeMinLimit,
                    max: visibleRangeMaxLimit
                }
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
    var historyCount = MAX_CANDLES + INDICATOR_WARMUP_COUNT;
    
    switch(period) {
        case '10M':
            startDate = new Date(endDate.getTime() - (historyCount * 10 * 60 * 1000));
            timeframe = '10m';
            break;
        case '30M':
            startDate = new Date(endDate.getTime() - (historyCount * 30 * 60 * 1000));
            timeframe = '30m';
            break;
        case '1H':
            startDate = new Date(endDate.getTime() - (historyCount * 60 * 60 * 1000));
            timeframe = '1h';
            break;
        case '3H':
            startDate = new Date(endDate.getTime() - (historyCount * 3 * 60 * 60 * 1000));
            timeframe = '3h';
            break;
        case '6H':
            startDate = new Date(endDate.getTime() - (historyCount * 6 * 60 * 60 * 1000));
            timeframe = '6h';
            break;
        case '1D':
            startDate.setDate(endDate.getDate() - (historyCount * 3));
            timeframe = '1d';
            break;
        case '1W':
            startDate.setDate(endDate.getDate() - (historyCount * 8));
            timeframe = '1w';
            break;
        case '1M':
            startDate.setMonth(endDate.getMonth() - (historyCount + 12));
            timeframe = '1M';
            break;
    }

    historyCount = MAX_CANDLES + INDICATOR_WARMUP_COUNT;

    currentTimeframe = timeframe;
    currentVisibleCandleCount = candleCount;
    
    var startDateStr = formatDateForAPI(startDate);
    var endDateStr = formatDateForAPI(endDate);

    showChartLoading(true);
    
    fetch('/stocks/api/candle?code=' + encodeURIComponent(stockCode) + '&start=' + startDateStr + '&end=' + endDateStr + '&timeframe=' + timeframe + '&limit=' + historyCount + getMarketParam(), {
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        })
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
    return;

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
          '&timeframe=' + currentTimeframe + '&limit=' + fetchCount + getMarketParam(), {
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        })
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
    stockChart._indicatorSeries = newChartData._indicatorSeries || null;

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
   차트 설정 패널
   ======================================== */
function toggleChartSettings(e) {
    e.stopPropagation();
    var panel = document.getElementById('chartSettingsPanel');
    if (!panel) return;
    panel.classList.toggle('open');

    if (panel.classList.contains('open')) {
        setTimeout(function() {
            document.addEventListener('click', closeChartSettingsOnClickOutside);
        }, 0);
    } else {
        document.removeEventListener('click', closeChartSettingsOnClickOutside);
    }
}

function closeChartSettingsOnClickOutside(e) {
    var panel = document.getElementById('chartSettingsPanel');
    var btn = document.querySelector('.chart-settings-btn');
    if (!panel || !btn) return;
    if (!panel.contains(e.target) && !btn.contains(e.target)) {
        panel.classList.remove('open');
        document.removeEventListener('click', closeChartSettingsOnClickOutside);
    }
}

function toggleLogScale(enabled) {
    useLogScale = enabled;
    saveLogScalePreference(enabled);
    syncLogScaleToggle();

    if (!stockChart) return;

    stockChart.options.scales.y.type = enabled ? 'logarithmic' : 'linear';

    if (enabled) {
        delete stockChart.options.scales.y.min;
        delete stockChart.options.scales.y.max;
        stockChart.options.scales.y.beginAtZero = false;
    }

    stockChart.update('none');

    if (!enabled) {
        updateYAxisRange(true);
    }
}

/* ========================================
   체결 정보
   ======================================== */
function refreshExecutions() {
    fetch('/stocks/api/executions?code=' + encodeURIComponent(stockCode) + '&limit=50' + getMarketParam(), {
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        })
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
