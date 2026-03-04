/**
 * 주식 차트 및 체결 정보 관리 JavaScript
 */

let stockChart = null;
let currentChartType = 'candle';
let currentPeriod = '1D';
let currentTimeframe = '1d';

/**
 * 통화 단위 반환 (미국 주식이면 $, 한국 주식이면 원)
 */
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
    return prefix + new Intl.NumberFormat('ko-KR').format(value) + suffix;
}

// Chart.js가 로드되었을 때 초기화
document.addEventListener('DOMContentLoaded', function() {
    // 차트 라이브러리는 defer로 이미 로딩 중 — 준비되면 데이터 fetch 시작
    waitForChartReady().then(() => {
        // 캔들 데이터와 체결 데이터를 동시에 비동기 로딩
        loadChartData(currentPeriod, document.querySelector('.period-btn.active'));
        loadInitialExecutions();
    });

    syncExecutionHeaderSpacing();
    window.addEventListener('resize', syncExecutionHeaderSpacing);
});

/**
 * Chart.js defer 스크립트 로딩 완료 대기 (최대 5초)
 */
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

/**
 * 초기 체결 데이터 로딩
 */
function loadInitialExecutions() {
    fetch(`/stocks/api/executions?code=${encodeURIComponent(stockCode)}&limit=50`)
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

/**
 * 차트 모듈 준비 상태 확인
 */
function isChartReady() {
    return typeof Chart !== 'undefined';
}

function hasCandlestickSupport() {
    if (typeof window.CandlestickController !== 'undefined') {
        return true;
    }

    if (typeof Chart !== 'undefined' && Chart.registry && typeof Chart.registry.getController === 'function') {
        try {
            return !!Chart.registry.getController('candlestick');
        } catch (e) {
            return false;
        }
    }

    return false;
}

/**
 * 외부 스크립트 로드
 */
function loadScript(src) {
    return new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = src;
        script.async = true;
        script.onload = () => resolve();
        script.onerror = () => reject(new Error(`스크립트 로드 실패: ${src}`));
        document.head.appendChild(script);
    });
}

/**
 * Chart.js + Financial Plugin 동적 로드
 */
async function loadChartModules() {
    try {
        if (typeof Chart === 'undefined') {
            await loadScript('/vendor/chart.umd.min.js');
        }

        if (!hasCandlestickSupport()) {
            try {
                await loadScript('/vendor/chartjs-chart-financial.min.js');
            } catch (pluginError) {
                console.warn('캔들 플러그인 로드 실패, 라인 차트로 대체합니다.', pluginError);
            }
        }
    } catch (error) {
        console.error('차트 모듈 로드 실패:', error);
        throw error;
    }
}

/**
 * 차트 초기화
 */
function initChart() {
    const canvas = document.getElementById('stockChart');
    if (!canvas) {
        showChartError('Canvas 요소를 찾을 수 없습니다.');
        return;
    }

    const wrapper = canvas.parentElement;
    if (!wrapper) {
        showChartError('Canvas wrapper를 찾을 수 없습니다.');
        return;
    }

    const rect = wrapper.getBoundingClientRect();
    
    if (rect.width === 0 || rect.height === 0) {
        setTimeout(() => initChart(), 200);
        return;
    }

    // Canvas의 크기를 wrapper 크기에 맞춰 설정
    const cs = getComputedStyle(wrapper);
    const width = wrapper.offsetWidth - (parseInt(cs.paddingLeft) || 0) - (parseInt(cs.paddingRight) || 0);
    const height = wrapper.offsetHeight - (parseInt(cs.paddingTop) || 0) - (parseInt(cs.paddingBottom) || 0);
    
    // Canvas 해상도 + CSS 크기 설정 (한 번만)
    const dpr = window.devicePixelRatio;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    canvas.style.width = width + 'px';
    canvas.style.height = height + 'px';
    canvas.style.display = 'block';

    if (!isChartReady()) {
        // defer 스크립트 로딩 대기 후 재시도
        waitForChartReady().then(() => initChart());
        return;
    }

    const ctx = canvas.getContext('2d');
    if (!ctx) {
        showChartError('Canvas 컨텍스트를 가져올 수 없습니다.');
        return;
    }
    
    ctx.scale(dpr, dpr);

    if (stockChart) {
        stockChart.destroy();
    }

    const resolvedChartType = (currentChartType === 'candle' && hasCandlestickSupport()) ? 'candle' : 'line';
    
    const chartData = prepareChartData(candleData, resolvedChartType);

    // 데이터 범위 계산
    let dataRange = null;
    if (candleData && candleData.length > 0) {
        const allValues = candleData.flatMap(d => [
            parseFloat(d.execution_open),
            parseFloat(d.execution_close),
            parseFloat(d.execution_min),
            parseFloat(d.execution_max)
        ].filter(v => !isNaN(v)));
        
        if (allValues.length > 0) {
            dataRange = {
                min: Math.min(...allValues),
                max: Math.max(...allValues)
            };
        }
    }

    try {
        stockChart = new Chart(ctx, {
            type: resolvedChartType === 'candle' ? 'candlestick' : 'line',
            data: chartData,
            options: getChartOptions(resolvedChartType, dataRange)
        });
    } catch (error) {
        try {
            stockChart = new Chart(ctx, {
                type: 'line',
                data: prepareChartData(candleData, 'line'),
                options: getChartOptions('line')
            });
        } catch (fallbackError) {
            showChartError('차트를 렌더링할 수 없습니다: ' + fallbackError.message);
        }
    }
}

/**
 * 차트 로딩 인디케이터 표시/숨김
 */
function showChartLoading(show) {
    const el = document.getElementById('chartLoading');
    if (el) el.style.display = show ? 'flex' : 'none';
}

/**
 * 차트 데이터 없음 표시/숨김
 */
function showChartNoData(show) {
    const el = document.getElementById('chartNoData');
    if (el) el.style.display = show ? 'flex' : 'none';
}

/**
 * 차트 오류 메시지 표시
 */
function showChartError(message) {
    const canvas = document.getElementById('stockChart');
    if (!canvas) return;
    
    const wrapper = canvas.parentElement;
    if (!wrapper) return;
    
    wrapper.innerHTML = `
        <div class="chart-no-data" style="position: static; transform: none; padding: 20px;">
            <p>${message}</p>
            <p class="chart-no-data-sub">명령어로 npm install을 실행하거나 CDN 접속을 확인해주세요.</p>
        </div>
    `;
}

/**
 * 차트 데이터 준비
 */
function prepareChartData(data, chartType) {
    if (chartType === 'line') {
        return {
            labels: data.map(d => formatDateTime(d.execution_datetime)),
            datasets: [{
                label: '종가',
                data: data.map(d => parseFloat(d.execution_close)),
                borderColor: '#4CAF50',
                backgroundColor: 'rgba(76, 175, 80, 0.1)',
                fill: true,
                tension: 0.4
            }]
        };
    } else {
        return {
            labels: data.map(d => formatDateTime(d.execution_datetime)),
            datasets: [{
                label: '캔들',
                data: data.map(d => {
                    const open = parseFloat(d.execution_open);
                    const close = parseFloat(d.execution_close);
                    const high = parseFloat(d.execution_max);
                    const low = parseFloat(d.execution_min);
                    
                    return {
                        x: formatDateTime(d.execution_datetime),
                        o: open,
                        h: high,
                        l: low,
                        c: close
                    };
                }),
                color: {
                    up: '#ef5350',      // 상승(양봉) - 빨강
                    down: '#26a69a',    // 하락(음봉) - 파랑/청록
                    unchanged: '#999'
                },
                borderColor: {
                    up: '#ef5350',
                    down: '#26a69a',
                    unchanged: '#999'
                },
                barPercentage: 0.05,
                categoryPercentage: 1.0
            }]
        };
    }
}

/**
 * 차트 옵션
 */
function getChartOptions(chartType = 'line', dataRange = null) {
    const options = {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
            mode: 'index',
            intersect: false,
        },
        plugins: {
            legend: {
                display: true,
                position: 'top',
                labels: {
                    color: '#C3C3C3',
                    font: {
                        size: 12
                    }
                }
            },
            tooltip: {
                backgroundColor: 'rgba(0, 0, 0, 0.8)',
                titleColor: '#fff',
                bodyColor: '#fff',
                borderColor: '#464646',
                borderWidth: 1,
                padding: 12,
                displayColors: true,
                callbacks: {
                    label: function(context) {
                        if (chartType === 'candle' && context.raw) {
                            return [
                                `시가: ${formatPrice(context.raw.o)}`,
                                `고가: ${formatPrice(context.raw.h)}`,
                                `저가: ${formatPrice(context.raw.l)}`,
                                `종가: ${formatPrice(context.raw.c)}`
                            ];
                        }

                        let label = context.dataset.label || '';
                        if (label) {
                            label += ': ';
                        }

                        if (context.parsed.y !== null) {
                            label += formatPrice(context.parsed.y);
                        }
                        return label;
                    }
                }
            }
        },
        scales: {
            x: {
                type: 'category',
                grid: {
                    color: '#464646',
                    borderColor: '#464646'
                },
                ticks: {
                    color: '#9aa0a6',
                    maxTicksLimit: 10
                }
            },
            y: {
                beginAtZero: false,
                grid: {
                    color: '#464646',
                    borderColor: '#464646'
                },
                ticks: {
                    color: '#9aa0a6',
                    callback: function(value) {
                        return formatPrice(value);
                    }
                }
            }
        }
    };

    // 데이터 범위가 제공되면 y축 범위 설정
    if (dataRange && dataRange.min !== undefined && dataRange.max !== undefined) {
        const padding = (dataRange.max - dataRange.min) * 0.05; // 5% 여유 공간
        options.scales.y.min = Math.max(0, dataRange.min - padding);
        options.scales.y.max = dataRange.max + padding;
    }

    return options;
}

/**
 * 차트 기간 변경
 */
function loadChartData(period, triggerEl = null) {
    currentPeriod = period;
    
    // 버튼 활성화 상태 변경
    document.querySelectorAll('.period-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    const targetEl = triggerEl || (typeof event !== 'undefined' ? event.target : null);
    if (targetEl && targetEl.classList) {
        targetEl.classList.add('active');
    }
    
    // API 호출하여 데이터 로드
    const endDate = new Date();
    let startDate = new Date();
    let timeframe = '1d'; // 기본값
    let limit = 60;
    let candleCount = 60; // 한 번에 보여줄 캔들 수
    
    switch(period) {
        case '10M':
            startDate = new Date(endDate.getTime() - (candleCount * 10 * 60 * 1000));
            timeframe = '10m'; // 10분봉
            limit = candleCount;
            break;
        case '30M':
            startDate = new Date(endDate.getTime() - (candleCount * 30 * 60 * 1000));
            timeframe = '30m'; // 30분봉
            limit = candleCount;
            break;
        case '1H':
            startDate = new Date(endDate.getTime() - (candleCount * 60 * 60 * 1000));
            timeframe = '1h'; // 1시간봉
            limit = candleCount;
            break;
        case '3H':
            startDate = new Date(endDate.getTime() - (candleCount * 3 * 60 * 60 * 1000));
            timeframe = '3h'; // 3시간봉
            limit = candleCount;
            break;
        case '6H':
            startDate = new Date(endDate.getTime() - (candleCount * 6 * 60 * 60 * 1000));
            timeframe = '6h'; // 6시간봉
            limit = candleCount;
            break;
        case '1D':
            startDate.setDate(endDate.getDate() - 180);
            timeframe = '1d'; // 1일: 일봉
            limit = candleCount;
            break;
        case '1W':
            startDate.setDate(endDate.getDate() - (candleCount * 8));
            timeframe = '1w'; // 1주: 주봉
            limit = candleCount;
            break;
        case '1M':
            startDate.setMonth(endDate.getMonth() - (candleCount + 12));
            timeframe = '1M'; // 1개월: 월봉
            limit = candleCount;
            break;
        case '3M':
            startDate.setMonth(endDate.getMonth() - (candleCount * 3 + 12));
            timeframe = '3M'; // 3개월: 분기봉
            limit = candleCount;
            break;
        case '1Y':
            startDate.setFullYear(endDate.getFullYear() - (candleCount + 5));
            timeframe = '1Y'; // 1년: 연봉
            limit = candleCount;
            break;
    }

    currentTimeframe = timeframe;
    
    const startDateStr = formatDateForAPI(startDate);
    const endDateStr = formatDateForAPI(endDate);

    // 로딩 UI 표시
    showChartLoading(true);
    
    fetch(`/stocks/api/candle?code=${encodeURIComponent(stockCode)}&start=${startDateStr}&end=${endDateStr}&timeframe=${timeframe}&limit=${limit}`)
        .then(response => response.json())
        .then(data => {
            showChartLoading(false);
            if (data.success && data.data.length > 0) {
                candleData = data.data;
                showChartNoData(false);
                initChart();
            } else {
                candleData = [];
                if (stockChart) {
                    stockChart.destroy();
                    stockChart = null;
                }
                showChartNoData(true);
            }
        })
        .catch(error => {
            showChartLoading(false);
            showChartNoData(true);
            console.error('차트 데이터 로드 실패:', error);
        });
}

/**
 * 차트 타입 변경
 */
function setChartType(chartType, triggerEl = null) {
    currentChartType = chartType;

    if (currentChartType === 'candle' && !hasCandlestickSupport()) {
        // defer 스크립트로 이미 로딩 시도됨 — 폴백으로 동적 로딩 재시도
        loadChartModules().finally(() => initChart());
        return;
    }
    
    // 버튼 활성화 상태 변경
    document.querySelectorAll('.chart-type-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    const targetEl = triggerEl || (typeof event !== 'undefined' ? event.target : null);
    if (targetEl && targetEl.classList) {
        targetEl.classList.add('active');
    }
    
    // 차트 다시 그리기
    initChart();
}

/**
 * 체결 정보 새로고침
 */
function refreshExecutions() {
    fetch(`/stocks/api/executions?code=${encodeURIComponent(stockCode)}&limit=50`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                updateExecutionList(data.data);
                syncExecutionHeaderSpacing();
            }
        })
        .catch(error => {
            console.error('체결 정보 로드 실패:', error);
        });
}

function syncExecutionHeaderSpacing() {
    const executionBodyEl = document.getElementById('executionList');
    if (!executionBodyEl) return;

    const headerEl = executionBodyEl.parentElement?.querySelector('.execution-header');
    if (!headerEl) return;

    const scrollbarWidth = executionBodyEl.offsetWidth - executionBodyEl.clientWidth;
    headerEl.style.paddingRight = `${15 + Math.max(0, scrollbarWidth)}px`;
}

/**
 * 체결 목록 업데이트
 */
function updateExecutionList(executions) {
    const executionListEl = document.getElementById('executionList');
    if (!executionListEl) return;
    
    if (executions.length === 0) {
        executionListEl.innerHTML = '<div class="execution-no-data">체결 데이터가 없습니다.</div>';
        return;
    }
    
    let html = '';
    executions.forEach(exec => {
        const isBuy = parseFloat(exec.execution_bid_volume) > parseFloat(exec.execution_ask_volume);
        const volume = Math.max(
            parseFloat(exec.execution_non_volume || 0),
            parseFloat(exec.execution_bid_volume || 0),
            parseFloat(exec.execution_ask_volume || 0)
        );
        
        html += `
            <div class="execution-item ${isBuy ? 'buy' : 'sell'}">
                <div class="exec-time">${formatTime(exec.execution_datetime)}</div>
                <div class="exec-price">${formatPrice(exec.execution_price)}</div>
                <div class="exec-volume">${formatNumber(volume)}</div>
                <div class="exec-type">${isBuy ? '매수' : '매도'}</div>
            </div>
        `;
    });
    
    executionListEl.innerHTML = html;
}

/**
 * 날짜/시간 형식화
 */
function formatDateTime(datetime) {
    const date = new Date(datetime.replace(' ', 'T'));
    if (isNaN(date.getTime())) {
        // Date 파싱 실패시 원본 문자열 사용
        return datetime;
    }
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');

    // timeframe에 따라 포맷 결정
    switch (currentTimeframe) {
        case '1Y':
            return `${year}`;
        case '3M':
            const quarter = Math.ceil((date.getMonth() + 1) / 3);
            return `${year} Q${quarter}`;
        case '1M':
            return `${year}-${month}`;
        case '1w':
            return `${month}/${day}`;
        case '1d':
            return `${month}/${day}`;
        default:
            // 분봉/시간봉
            return `${month}/${day} ${hours}:${minutes}`;
    }
}

function formatTime(datetime) {
    const date = new Date(datetime);
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    const seconds = String(date.getSeconds()).padStart(2, '0');
    return `${hours}:${minutes}:${seconds}`;
}

function formatDateForAPI(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    const seconds = String(date.getSeconds()).padStart(2, '0');
    return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
}

function formatNumber(num) {
    return new Intl.NumberFormat('ko-KR').format(num);
}

// 자동 새로고침 (30초마다)
setInterval(function() {
    if (typeof stockCode !== 'undefined' && document.getElementById('executionList')) {
        refreshExecutions();
    }
}, 30000);
