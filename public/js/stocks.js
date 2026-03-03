/**
 * 주식 차트 및 체결 정보 관리 JavaScript
 */

let stockChart = null;
let currentChartType = 'candle';
let currentPeriod = '1M';
let currentTimeframe = '1M';

// 즉시 실행: stocks.js가 로드되었는지 확인
console.log('[stocks.js] 파일이 로드되었습니다.');
console.log('[stocks.js] 전역 변수 확인: candleData =', typeof candleData !== 'undefined' ? (candleData ? candleData.length : 'null') : 'undefined');
console.log('[stocks.js] 전역 변수 확인: stockCode =', typeof stockCode !== 'undefined' ? stockCode : 'undefined');

// Chart.js가 로드되었을 때 초기화
document.addEventListener('DOMContentLoaded', function() {
    console.log('[DOMContentLoaded] 이벤트 발생');
    
    // candleData가 정의되었는지 확인
    if (typeof candleData !== 'undefined') {
        console.log('[DOMContentLoaded] candleData 정의됨. 길이:', candleData.length);
        if (candleData.length > 0) {
            console.log('[DOMContentLoaded] candleData가 준비되었습니다. Chart 모듈을 로드합니다.');
            loadChartModules().finally(() => {
                // 약간의 지연 후 차트 초기화 (DOM이 완전히 준비되도록)
                setTimeout(() => {
                    console.log('[DOMContentLoaded] 지연 후 initChart 호출');
                    if (typeof candleData !== 'undefined' && candleData.length > 0) {
                        initChart();
                    } else {
                        console.warn('[DOMContentLoaded] candleData가 비어있습니다.');
                    }
                }, 100);
            });
        } else {
            console.warn('[DOMContentLoaded] candleData가 비어있습니다.');
        }
    } else {
        console.error('[DOMContentLoaded] candleData가 정의되지 않았습니다!');
    }

    const activePeriodButton = document.querySelector('.period-btn.active');
    if (activePeriodButton) {
        setTimeout(() => {
            loadChartData(currentPeriod, activePeriodButton);
        }, 200);
    }

    syncExecutionHeaderSpacing();
    window.addEventListener('resize', syncExecutionHeaderSpacing);
});

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
            console.log('Chart.js 로드 중...');
            await loadScript('/vendor/chart.umd.min.js');
            console.log('Chart.js 로드 완료');
        }

        if (!hasCandlestickSupport()) {
            console.log('캔들스틱 플러그인 로드 중...');
            try {
                await loadScript('/vendor/chartjs-chart-financial.min.js');
                console.log('캔들스틱 플러그인 로드 완료');
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
    console.log('[initChart] 시작. candleData 길이:', typeof candleData !== 'undefined' ? candleData.length : 'undefined');
    
    const canvas = document.getElementById('stockChart');
    if (!canvas) {
        console.error('[initChart] Canvas 요소를 찾을 수 없습니다.');
        showChartError('Canvas 요소를 찾을 수 없습니다.');
        return;
    }

    // Canvas wrapper의 크기 확인
    const wrapper = canvas.parentElement;
    if (!wrapper) {
        console.error('[initChart] Canvas wrapper를 찾을 수 없습니다.');
        showChartError('Canvas wrapper를 찾을 수 없습니다.');
        return;
    }

    // Wrapper의 실제 크기 가져오기
    const rect = wrapper.getBoundingClientRect();
    console.log('[initChart] Wrapper 크기:', { width: rect.width, height: rect.height, offsetWidth: wrapper.offsetWidth, offsetHeight: wrapper.offsetHeight });
    
    if (rect.width === 0 || rect.height === 0) {
        console.warn('[initChart] Canvas wrapper의 크기가 0입니다. 크기 조정 후 재시도합니다.');
        setTimeout(() => initChart(), 200);
        return;
    }

    // Canvas의 크기를 wrapper 크기에 맞춰 설정
    const paddingLeft = parseInt(getComputedStyle(wrapper).paddingLeft) || 0;
    const paddingRight = parseInt(getComputedStyle(wrapper).paddingRight) || 0;
    const paddingTop = parseInt(getComputedStyle(wrapper).paddingTop) || 0;
    const paddingBottom = parseInt(getComputedStyle(wrapper).paddingBottom) || 0;
    
    const width = wrapper.offsetWidth - paddingLeft - paddingRight;
    const height = wrapper.offsetHeight - paddingTop - paddingBottom;
    
    console.log('[initChart] 계산된 Canvas 크기:', { width, height, padding: { left: paddingLeft, right: paddingRight, top: paddingTop, bottom: paddingBottom } });
    
    // Canvas 해상도 비율 설정
    canvas.width = width * window.devicePixelRatio;
    canvas.height = height * window.devicePixelRatio;
    
    // Canvas CSS 크기 설정 (max-width/height 무시하도록 important 추가)
    canvas.style.width = width + 'px !important';
    canvas.style.height = height + 'px !important';
    canvas.style.display = 'block';
    
    // Canvas 컨텍스트 스케일 설정
    const ctx = canvas.getContext('2d');
    if (ctx) {
        ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
    }
    
    // Canvas 해상도 비율 설정
    canvas.width = width * window.devicePixelRatio;
    canvas.height = height * window.devicePixelRatio;
    
    // Canvas CSS 크기 설정 (max-width/height 무시하도록 important 추가)
    canvas.style.width = width + 'px !important';
    canvas.style.height = height + 'px !important';
    canvas.style.display = 'block';
    
    console.log('[initChart] Canvas element 크기 설정 완료');

    if (!isChartReady()) {
        console.log('[initChart] Chart.js가 준비되지 않았습니다. 로드 중...');
        loadChartModules().then(() => {
            console.log('[initChart] Chart.js 로드 완료. 재시도합니다.');
            setTimeout(() => initChart(), 100);
        }).catch(error => {
            console.error('[initChart] Chart.js 로드 실패:', error);
            showChartError('차트 라이브러리를 로드할 수 없습니다.');
        });
        return;
    }

    if (!ctx) {
        console.error('[initChart] Canvas 컨텍스트를 가져올 수 없습니다.');
        showChartError('Canvas 컨텍스트를 가져올 수 없습니다.');
        return;
    }

    if (stockChart) {
        console.log('[initChart] 기존 차트 제거');
        stockChart.destroy();
    }

    const resolvedChartType = (currentChartType === 'candle' && hasCandlestickSupport()) ? 'candle' : 'line';
    console.log('[initChart] resolvedChartType:', resolvedChartType, '| currentChartType:', currentChartType, '| hasCandlestickSupport:', hasCandlestickSupport());
    
    const chartData = prepareChartData(candleData, resolvedChartType);
    console.log('[initChart] chartData 준비 완료:', chartData);

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
            console.log('[initChart] 데이터 범위:', dataRange, '데이터 포인트:', candleData.length);
        }
    }

    try {
        console.log('[initChart] Chart 생성 중... type:', resolvedChartType === 'candle' ? 'candlestick' : 'line');
        stockChart = new Chart(ctx, {
            type: resolvedChartType === 'candle' ? 'candlestick' : 'line',
            data: chartData,
            options: getChartOptions(resolvedChartType, dataRange)
        });
        console.log('[initChart] 차트가 성공적으로 렌더링되었습니다.');
    } catch (error) {
        console.warn('[initChart] 캔들/라인 렌더 실패, 라인 차트로 재시도합니다.', error);
        try {
            stockChart = new Chart(ctx, {
                type: 'line',
                data: prepareChartData(candleData, 'line'),
                options: getChartOptions('line')
            });
            console.log('[initChart] 라인 차트가 성공적으로 렌더링되었습니다.');
        } catch (fallbackError) {
            console.error('[initChart] 차트 렌더링 완전 실패:', fallbackError);
            showChartError('차트를 렌더링할 수 없습니다: ' + fallbackError.message);
        }
    }
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
                barPercentage: 0.035,
                categoryPercentage: 0.5
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
                                `시가: ${new Intl.NumberFormat('ko-KR').format(context.raw.o)}원`,
                                `고가: ${new Intl.NumberFormat('ko-KR').format(context.raw.h)}원`,
                                `저가: ${new Intl.NumberFormat('ko-KR').format(context.raw.l)}원`,
                                `종가: ${new Intl.NumberFormat('ko-KR').format(context.raw.c)}원`
                            ];
                        }

                        let label = context.dataset.label || '';
                        if (label) {
                            label += ': ';
                        }

                        if (context.parsed.y !== null) {
                            label += new Intl.NumberFormat('ko-KR').format(context.parsed.y) + '원';
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
                        return new Intl.NumberFormat('ko-KR').format(value) + '원';
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
        console.log('[getChartOptions] Y축 범위 설정:', { min: options.scales.y.min, max: options.scales.y.max, dataRange });
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
    
    fetch(`/stocks/api/candle?code=${encodeURIComponent(stockCode)}&start=${startDateStr}&end=${endDateStr}&timeframe=${timeframe}&limit=${limit}`)
        .then(response => response.json())
        .then(data => {
            if (data.success && data.data.length > 0) {
                candleData = data.data;
                // 차트를 다시 그리기 전에 약간 기다림
                setTimeout(() => initChart(), 50);
            } else {
                candleData = [];
                if (stockChart) {
                    stockChart.destroy();
                    stockChart = null;
                }
                console.warn('차트 데이터가 없습니다.');
            }
        })
        .catch(error => {
            console.error('차트 데이터 로드 실패:', error);
        });
}

/**
 * 차트 타입 변경
 */
function setChartType(chartType, triggerEl = null) {
    currentChartType = chartType;

    if (currentChartType === 'candle' && !hasCandlestickSupport()) {
        loadChartModules().finally(() => initChart());
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
                <div class="exec-price">${formatNumber(exec.execution_price)}</div>
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
