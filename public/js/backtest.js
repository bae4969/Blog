/**
 * 포트폴리오 백테스팅 시뮬레이터
 * - 연산은 서버(PHP BacktestService)에서 수행
 * - 클라이언트는 UI 제어, API 호출, 결과 렌더링만 담당
 */
(function () {
    'use strict';
    /** 안내 메시지 — 프로젝트 디자인 규칙대로 **화면 아래 가운데 토스트**로 띄운다.
     *  ⚠️ 예전에는 네이티브 `alert()` 였다(이 파일에만 17곳). 차단형 대화상자라 화면을
     *     가리고, 백테스트처럼 값을 보며 고치는 작업에서는 매번 끊겼다.
     *     `toast` 는 안 막으므로 **호출부의 `return` 은 그대로 둬야 한다**(전부 가드절이다).
     */
    function notify(message, type, opts) {
        if (window.toast) window.toast(message, type || 'error', opts);
        else if (window.console) console.warn(message);
    }


    /* =========================================
       상수 & 상태
       ========================================= */
    var MAX_STOCKS = 10;
    var MAX_BENCHMARKS = 5;
    var portfolio = [];    // [{ code, name, market, weight }] — ⚠️ 지금 **고른 구간**의 종목 목록(아래 phases)
    // 구성 변경(2026-10-19) — 구간들. 구간 1(date null)은 시작일부터, 그다음은 그 날짜부터. 종목 추가·비중·균등 배분·지우기 같은
    // 기존 편집은 `portfolio` 를 고치므로 고른 구간에 그대로 걸린다. 서버로는 stocks(구간 1) + changes(나머지)로 간다.
    var phases = [{ date: null, spread: 1, stocks: portfolio }];
    var selPhase = 0;
    var MAX_CHANGES = 12;
    var MAX_UNIVERSE = 15;
    var lastRunPhases = null;   // 결과를 그릴 때 쓴 구간(실행 시점의 것)
    var benchmarks = [];   // [{ code, name, market }]
    var backtestChart = null;
    var scoreRadarChart = null;
    var hasRunOnce = false;
    var autoRecalcTimer = null;
    var dateRangeTimer = null;

    // 오늘(YYYY-MM-DD). ⚠️ `toISOString()` 은 UTC 라 KST 오전 9시 전에는 어제가 나온다.
    function todayStr() {
        var d = new Date();
        return d.getFullYear() + '-' +
            ('0' + (d.getMonth() + 1)).slice(-2) + '-' +
            ('0' + d.getDate()).slice(-2);
    }

    /* =========================================
       `/api/v1` 호출 — 개인 데이터는 Bearer 가 필요하다

       ⚠️ 인증 쿠키는 `httponly` 라 JS 가 못 읽는다. 그래서 `/api/v1/auth/token` 에서
          지금 세션의 토큰을 받아 `Authorization` 에 싣는다. 쿠키를 그대로 쓰지 않는
          이유는 CSRF 다 — 쿠키는 남의 사이트가 붙일 수 있지만 헤더는 못 붙인다.

       토큰 수명은 10분이라 캐시해 두고 만료 30초 전에 다시 받는다.
       ========================================= */
    var _token = null;
    var _tokenExpiresAt = 0;

    function authToken() {
        if (_token && Date.now() < _tokenExpiresAt) return Promise.resolve(_token);
        // ⚠️ 로그인 안 했으면 아예 부르지 않는다. 그냥 두면 백테스트를 돌릴 때마다 401 이
        //    콘솔에 찍혀, 진짜 오류를 볼 때 눈이 가려진다.
        if (!window.__BACKTEST_USER_LOGGED_IN) {
            return Promise.reject(new Error('로그인이 필요합니다'));
        }
        return fetch('/api/v1/auth/token', { method: 'POST' })
            .then(function (r) {
                if (!r.ok) throw new Error('로그인이 필요합니다');
                return r.json();
            })
            .then(function (j) {
                _token = j.access_token;
                _tokenExpiresAt = Date.now() + Math.max(0, (j.expires_in - 30)) * 1000;
                return _token;
            });
    }

    /** 토큰을 실어 부른다. 실패는 HTTP 상태코드로 온다(옛 API 의 `success:false` 가 아니다). */
    function apiFetch(url, options) {
        return authToken().then(function (t) {
            var opts = options || {};
            var headers = Object.assign({}, opts.headers, { 'Authorization': 'Bearer ' + t });
            return fetch(url, Object.assign({}, opts, { headers: headers }));
        });
    }

    /**
     * 토큰이 **있으면** 싣고 없으면 그냥 보낸다.
     * 백테스트 실행과 포트폴리오 열람은 비로그인도 돼야 한다 — 토큰이 있으면 소유권이
     * 붙고(비공개로 저장), 없으면 주인 없는 공개 항목이 된다.
     */
    function apiFetchOptional(url, options) {
        return authToken()
            .then(function (t) { return t; }, function () { return null; })
            .then(function (t) {
                var opts = options || {};
                var headers = Object.assign({}, opts.headers);
                if (t) headers['Authorization'] = 'Bearer ' + t;
                return fetch(url, Object.assign({}, opts, { headers: headers }));
            });
    }

    /** 응답 본문의 `detail` 을 오류 메시지로 꺼낸다 — FastAPI 가 그 키에 담는다. */
    function apiError(response) {
        return response.json()
            .then(function (j) { return new Error(j && j.detail ? j.detail : ('HTTP ' + response.status)); })
            .catch(function () { return new Error('HTTP ' + response.status); });
    }

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
            var allStocks = phases[0].stocks.concat(benchmarks);
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

            // 기간 조회는 공개 읽기라 토큰이 없어도 된다.
            fetch('/api/v1/backtest/date-range?codes=' + encodeURIComponent(codes) +
                  '&markets=' + encodeURIComponent(markets))
                .then(function (r) {
                    if (!r.ok) throw new Error('HTTP ' + r.status);
                    return r.json();
                })
                .then(function (json) {
                    // 겹치는 구간이 없으면 `min`·`max` 가 null 이다(오류가 아니다).
                    if (json && json.min && json.max) {
                        // ⚠️ 종료일은 **오늘까지** 고를 수 있다(2026-08-23 사용자 요청).
                        //    데이터 마지막 날로 막아 두면 휴장·수집 지연일 때 오늘이 회색이
                        //    되어 "왜 안 되지" 가 된다. 엔진은 CAGR 등을 실제 시세가 있는
                        //    첫날·마지막날로 계산하므로(services/backtest.py `cagr`),
                        //    데이터 없는 날을 끝으로 잡아도 지표가 틀어지지 않는다.
                        var today = todayStr();
                        var endMax = today > json.max ? today : json.max;
                        startEl.setAttribute('min', json.min);
                        startEl.setAttribute('max', json.max);
                        endEl.setAttribute('min', json.min);
                        endEl.setAttribute('max', endMax);
                        if (startEl.value && startEl.value < json.min) startEl.value = json.min;
                        if (startEl.value && startEl.value > json.max) startEl.value = json.max;
                        if (endEl.value && endEl.value < json.min) endEl.value = json.min;
                        if (endEl.value && endEl.value > endMax) endEl.value = endMax;
                        showDateHint(json.min, json.max);
                    } else {
                        showDateHint(null, null);
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
            setRunLabel(btn, '백테스트 실행');
            btn.className = 'btn btn-primary btn-lg btn-block';
            return;
        }
        var currentKey = JSON.stringify(collectConfig());
        if (currentKey === lastRunKey) {
            setRunLabel(btn, '재계산');
            btn.className = 'btn btn-primary btn-lg btn-block btn-recalc';
        } else {
            setRunLabel(btn, '백테스트 실행');
            btn.className = 'btn btn-primary btn-lg btn-block btn-refetch';
        }
    }

    /**
     * 실행 버튼의 이름만 바꾼다. 버튼은 아이콘만 보이고 이름은 눈에 숨긴 span 에 있다
     * (프로젝트 디자인 규칙) — 버튼에 `textContent` 를 쓰면 아이콘이 지워지고 글자가 드러난다.
     */
    function setRunLabel(btn, text) {
        var label = btn.querySelector('span');
        (label || btn).textContent = text;
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
     *   CAGR        : -10 % ~ 15 %
     *   연간수익률    : -10 % ~ 20 %
     *   총 수익률     : -50 % ~ 200 %
     *   MDD (역전)   : 45 % ~ 10 %  (낮을수록 좋음)
     *   샤프 비율     : -0.5 ~ 1.8
     *   소르티노 비율  : -0.5 ~ 2.0
     *
     * 가중치: CAGR 20, avgAnnual 10, totalReturn 10, MDD 20, Sharpe 20, Sortino 20
     */
    function calculateTotalScore(metrics) {
        // 비정상 값(Infinity, null 등)은 중립 점수 50으로 처리하여 총 점수 왜곡 방지
        function normalize(value, minVal, maxVal) {
            if (value === null || value === undefined || !isFinite(value)) return 50;
            var score = (value - minVal) / (maxVal - minVal) * 100;
            return Math.max(0, Math.min(100, score));
        }

        // MDD는 낮을수록 좋으므로 역전 정규화: 100 - 정방향 점수
        var mddNormalized = 100 - normalize(metrics.mdd, 10, 45);

        var scores = {
            cagr:        normalize(metrics.cagr, -10, 15),
            avgAnnual:   normalize(metrics.avgAnnual, -10, 20),
            totalReturn: normalize(metrics.totalReturn, -50, 200),
            mdd:         mddNormalized,
            sharpe:      normalize(metrics.sharpe, -0.5, 1.8),
            sortino:     normalize(metrics.sortino, -0.5, 2.0)
        };

        var weights = {
            cagr: 20, avgAnnual: 10, totalReturn: 10,
            mdd: 20, sharpe: 20, sortino: 20
        };
        var totalWeight = 0;
        var weightedSum = 0;
        var keys = Object.keys(weights);
        for (var i = 0; i < keys.length; i++) {
            var key = keys[i];
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
       레이더 차트 렌더러 (총 점수 세부 지표)
       ========================================= */
    function renderScoreRadar(labels, datasets) {
        var canvas = document.getElementById('scoreRadarChart');
        if (!canvas) return;
        if (scoreRadarChart) { scoreRadarChart.destroy(); scoreRadarChart = null; }

        var style = getComputedStyle(document.documentElement);
        var textColor = style.getPropertyValue('--bae-text-muted').trim() || '#6b7280';
        var gridColor = style.getPropertyValue('--bae-border').trim() || '#e5e7eb';

        scoreRadarChart = new Chart(canvas, {
            type: 'radar',
            data: { labels: labels, datasets: datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: false
                    },
                    tooltip: {
                        callbacks: {
                            label: function (ctx) {
                                return ctx.dataset.label + ': ' + ctx.raw + '점';
                            }
                        }
                    }
                },
                scales: {
                    r: {
                        min: 0,
                        max: 100,
                        ticks: {
                            stepSize: 20,
                            color: textColor,
                            font: { size: 9 },
                            backdropColor: 'transparent'
                        },
                        grid: {
                            color: gridColor
                        },
                        angleLines: {
                            color: gridColor
                        },
                        pointLabels: {
                            color: textColor,
                            font: { size: 11, weight: '600' }
                        }
                    }
                }
            }
        });
    }

    /* =========================================
       차트 렌더러
       ========================================= */
    function renderChart(series, benchmarkSeries, changedAt) {
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
        var textColor = rootStyle.getPropertyValue('--bae-text-muted').trim() || '#888';
        var gridColor = rootStyle.getPropertyValue('--bae-border').trim() || '#333';

        // 구성 변경일 — 세로 점선과 번호(①②…). 차트 점은 솎아져 있어 그 날짜 이후 첫 점에 긋는다.
        var accent = getComputedStyle(document.documentElement).getPropertyValue('--bae-accent-fg').trim() || '#a78bfa';
        var markers = (changedAt || []).map(function (c, n) {
            for (var k = 0; k < labels.length; k++) if (labels[k] >= c.date) return { idx: k, text: c.date.slice(2, 7).replace('-', '.'), color: accent };
            return null;
        }).filter(Boolean);
        var phaseLines = {
            id: 'phaseLines',
            afterDatasetsDraw: function (chart) {
                if (!markers.length) return;
                var c = chart.ctx, area = chart.chartArea, xs = chart.scales.x;
                c.save();
                markers.forEach(function (m) {
                    var x = xs.getPixelForValue(m.idx);
                    c.strokeStyle = m.color;
                    c.lineWidth = 1.5;
                    c.setLineDash([4, 4]);
                    c.beginPath(); c.moveTo(x, area.top); c.lineTo(x, area.bottom); c.stroke();
                    c.setLineDash([]);
                    c.font = '600 10px sans-serif';
                    var tw = c.measureText(m.text).width + 10;
                    c.fillStyle = m.color;
                    c.beginPath(); c.roundRect(x - tw / 2, area.top + 1, tw, 16, 8); c.fill();
                    c.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--bae-accent-text').trim() || '#000';
                    c.textAlign = 'center'; c.textBaseline = 'middle';
                    c.fillText(m.text, x, area.top + 9.5);
                });
                c.restore();
            }
        };

        backtestChart = new Chart(ctx, {
            type: 'line',
            plugins: [phaseLines],
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


    /*
      고를 수 있는 기간 안내. 종목마다 데이터 시작일이 달라 교집합으로 좁혀지는 것이
      달력만 봐서는 안 드러나기 때문이다.
      ⚠️ 늘 한 줄로 깔지 않고 **종료일 라벨 옆 ⓘ 안에** 넣는다(2026-08-23 사용자 지시).
         종료일은 오늘까지 고를 수 있으므로, 데이터가 오늘보다 앞에서 끝나면 계산이
         거기까지만 간다는 것도 이 툴팁이 함께 말해 준다.
    */
    function showDateHint(min, max) {
        // 줄 배열을 그 칸의 ⓘ 툴팁에 채운다. 빈 문자열은 빈 줄이다.
        function fill(id, lines) {
            var el = document.getElementById(id);
            if (!el) return;
            var tip = el.querySelector('.metric-tooltip');
            if (!tip) return;
            if (!lines) { el.hidden = true; tip.textContent = ''; return; }
            tip.textContent = '';
            lines.forEach(function (line, i) {
                if (i > 0) tip.appendChild(document.createElement('br'));
                if (line) tip.appendChild(document.createTextNode(line));
            });
            el.hidden = false;
        }

        if (!min || !max) { fill('startDateHint', null); fill('endDateHint', null); return; }

        fill('startDateHint', [
            '선택한 종목의 데이터 시작',
            min,
            '',
            '이보다 앞은 고를 수 없습니다'
        ]);
        fill('endDateHint', [
            '선택한 종목의 데이터 끝',
            max
        ].concat(max < todayStr()
            ? ['', '오늘까지 고를 수 있지만 계산은 ' + max + ' 까지입니다']
            : []));
    }

    // 종목 검색 — 자동완성
    function initStockSearch(inputId, resultsId, onAddPortfolio, onAddBenchmark) {
        var input = document.getElementById(inputId);
        var resultsDiv = document.getElementById(resultsId);
        if (!input || !resultsDiv) return;
        var debounce = null;
        // 목록은 top layer(popover="manual") — 입력칸 줄 바로 아래, 같은 폭(옛 absolute 자리).
        window.TopLayer.follow(resultsDiv, resultsDiv.parentElement, { side: 'below', align: 'stretch', gap: 0 });

        // Esc 는 목록만 닫는다(입력칸 글자는 그대로).
        input.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && resultsDiv.matches(':popover-open')) { e.preventDefault(); window.TopLayer.hide(resultsDiv); }
        });

        input.addEventListener('input', function () {
            clearTimeout(debounce);
            var q = input.value.trim();
            if (q.length < 1) { window.TopLayer.hide(resultsDiv); return; }
            debounce = setTimeout(function () {
                // 종목 검색은 `/api/v1/stocks` 의 `q` 로 옮겼다(2026-08-19).
                // ⚠️ 옛 `/stocks/api/search` 응답에는 `stock_type` 이 아예 없어서
                //    `s.stock_type === 'COIN'` 은 **항상 거짓**이었다. 새 API 는 `type` 을 준다.
                fetch('/api/v1/stocks?q=' + encodeURIComponent(q) + '&size=10')
                    .then(function (r) {
                        if (!r.ok) throw new Error('HTTP ' + r.status);
                        return r.json();
                    })
                    .then(function (json) {
                        if (!json.items || json.items.length === 0) {
                            resultsDiv.innerHTML = '<div class="search-empty">검색 결과 없음</div>';
                            window.TopLayer.show(resultsDiv);
                            return;
                        }
                        var html = '';
                        json.items.forEach(function (s) {
                            var market = s.type === 'COIN' ? 'COIN' : (
                                ['NYSE', 'NASDAQ', 'AMEX'].indexOf(s.market) >= 0 ? 'US' : 'KR'
                            );
                            html += '<div class="search-result-item" data-code="' + escapeHtml(s.code) +
                                '" data-name="' + escapeHtml(s.name_kr || s.code) +
                                '" data-market="' + escapeHtml(market) + '">' +
                                '<span class="sr-name">' + escapeHtml(s.name_kr || s.code) + '</span>' +
                                '<span class="sr-code">' + escapeHtml(s.code) + '</span>' +
                                '<span class="sr-market badge-' + escapeHtml(market.toLowerCase()) + '">' + escapeHtml(market) + '</span>' +
                                '<span class="sr-actions">' +
                                '<button type="button" class="sr-add-btn sr-add-portfolio">+ 포폴</button>' +
                                '<button type="button" class="sr-add-btn sr-add-benchmark">+ 벤치</button>' +
                                '</span>' +
                                '</div>';
                        });
                        resultsDiv.innerHTML = html;
                        window.TopLayer.show(resultsDiv);

                        resultsDiv.querySelectorAll('.search-result-item').forEach(function (item) {
                            var stock = {
                                code: item.dataset.code,
                                name: item.dataset.name,
                                market: item.dataset.market
                            };
                            item.querySelector('.sr-add-portfolio').addEventListener('click', function (e) {
                                e.stopPropagation();
                                onAddPortfolio(stock);
                                window.TopLayer.hide(resultsDiv);
                            });
                            item.querySelector('.sr-add-benchmark').addEventListener('click', function (e) {
                                e.stopPropagation();
                                onAddBenchmark(stock);
                                window.TopLayer.hide(resultsDiv);
                            });
                        });
                    });
            }, 300);
        });

        // 바깥은 누르는 순간(pointerdown)에 판정한다 — click 이면 목록 안에서 글자·스크롤바를 끌다 밖에서 뗄 때
        // click 이 공통 조상에서 일어나 닫혔다(2026-10-13 점검).
        document.addEventListener('pointerdown', function (e) {
            if (!input.contains(e.target) && !resultsDiv.contains(e.target)) {
                window.TopLayer.hide(resultsDiv);
            }
        });
    }

    /* =========================================
       종목 구성 — 비중 표(2026-10-19)
       ========================================= */
    // 행 = 종목, 열 = 시점("처음", 25.12.15…), 칸 = 비중. 비운 칸은 "그 시점엔 안 담음". 띠·칩·탭을 거쳐(사용자: 직관적이지 않다)
    // 표로 정했다. 칸을 고칠 때는 표를 다시 그리지 않고 색·합계만 고친다(refreshTable) — 다시 그리면 Tab 으로 옮기던 포커스가 날아갔다.
    // 구조가 바뀔 때(행·열이 생기거나 사라질 때)만 다시 그린다(renderPortfolio).

    //: 결과 구성 띠의 **종목** 색(같은 종목은 어느 시점이든 같은 색).
    var PHASE_COLORS = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9'];
    var stockStarts = {};   // 코드 → 시세 첫날(시점보다 늦으면 그 칸에 !). 없으면 아직 안 물어봤다
    var popPhase = null;    // 시점 창이 고치고 있는 열(객체 — 날짜순 정렬로 번호가 바뀌어도 따라간다)
    //: 시점이 여럿일 때 검색으로 넣은 종목 — 빈 줄로 더하고 칸을 채우면 그 시점에 담긴다(어느 열에 넣을지 고르는 "고른 열"을 걷었다 —
    //  보라 테두리로 표시해야 했고 사용자가 그 강조를 원하지 않았다). 아무 칸도 안 채우면 설정에 들어가지 않는다.
    var extraRows = [];

    function slimStocks(list) {
        return list.map(function (s) { return { code: s.code, name: s.name, market: s.market, weight: s.weight }; });
    }

    function collectChanges() {
        return phases.slice(1).map(function (p) { return { date: p.date, spreadDays: p.spread, stocks: slimStocks(p.stocks) }; });
    }

    /** 표의 행 — 시점에 담긴 종목 + 아직 칸을 안 채운 빈 줄. */
    function tableRows() {
        var rows = allPhaseStocks(), seen = {};
        rows.forEach(function (s) { seen[s.code] = true; });
        extraRows = extraRows.filter(function (s) { return !seen[s.code]; });
        return rows.concat(extraRows);
    }

    /** 모든 시점의 종목(코드 하나에 한 번, 처음 나온 순서) — 시그널 대상·설정. */
    function allPhaseStocks() {
        var seen = {}, out = [];
        phases.forEach(function (p) {
            p.stocks.forEach(function (s) { if (!seen[s.code]) { seen[s.code] = true; out.push(s); } });
        });
        return out;
    }

    function shortDate(d) { return d ? d.slice(2).replace(/-/g, '.') : ''; }
    function colName(i) { return i === 0 ? (phases.length > 1 ? '처음' : '비중') : (shortDate(phases[i].date) || '날짜?'); }
    var SPREAD_LABEL = { 1: '한 번에', 5: '5일 분할', 10: '10일 분할', 20: '20일 분할', 60: '60일 분할' };

    /** 열 고르기 — 마지막으로 만진 열(`portfolio` 가 이 열의 목록 — 열이 하나면 검색으로 넣는 종목이 여기에). */
    function selectPhase(i) {
        selPhase = Math.max(0, Math.min(i, phases.length - 1));
        portfolio = phases[selPhase].stocks;
        refreshTable();
    }

    function setPhases(list) {
        phases = list.length ? list : [{ date: null, spread: 1, stocks: [] }];
        extraRows = [];
        selPhase = 0;
        portfolio = phases[0].stocks;
        renderPortfolio();
        updateSignalTargets();
    }

    /** 시점(열)을 날짜순으로 — 날짜를 바꾸면 저절로 자리를 잡는다("앞 시점보다 뒤여야" 오류가 없다). 고른 열은 따라간다. */
    function sortPhases() {
        var cur = phases[selPhase];
        var rest = phases.slice(1).sort(function (a, b) { return (a.date || '9999') < (b.date || '9999') ? -1 : (a.date || '9999') > (b.date || '9999') ? 1 : 0; });
        phases = [phases[0]].concat(rest);
        selPhase = Math.max(0, phases.indexOf(cur));
        portfolio = phases[selPhase].stocks;
    }

    /** 시점 i 의 문제(없으면 null) — 종목 수·비중 합·날짜(기간 안, 같은 날짜 둘 없음). */
    function phaseProblem(i) {
        var p = phases[i];
        if (!p.stocks.length) return '종목을 1개 이상 넣으세요.';
        var total = p.stocks.reduce(function (a, b) { return a + b.weight; }, 0);
        if (Math.abs(total - 100) > 0.5) return '비중 합계가 100%여야 합니다. (현재: ' + (Math.round(total * 100) / 100) + '%)';
        if (i === 0) return null;
        var start = document.getElementById('startDate').value, end = document.getElementById('endDate').value;
        if (!p.date) return '바꾸는 날을 고르세요.';
        if (start && p.date <= start) return '바꾸는 날은 시작일(' + start + ')보다 뒤여야 합니다.';
        if (end && p.date > end) return '바꾸는 날은 종료일(' + end + ')까지여야 합니다.';
        for (var k = 1; k < phases.length; k++) if (k !== i && phases[k].date === p.date) return '같은 날 바꾸는 시점이 이미 있습니다.';
        return null;
    }

    function weightOf(list, code) {
        for (var k = 0; k < list.length; k++) if (list[k].code === code) return list[k].weight;
        return null;
    }

    function tableTargets() {
        var out = [document.getElementById('selectedStocks')];
        var dlg = document.getElementById('phaseDlg');
        if (dlg && dlg.open) out.push(document.getElementById('phaseDlgBody'));
        return out.filter(Boolean);
    }

    function buildTable() {
        var rows = tableRows();
        var wrap = document.createElement('div');
        wrap.className = 'wt-wrap';
        var t = document.createElement('table');
        t.className = 'wt';
        var h = '<thead><tr><th class="wt-name">종목</th>';
        phases.forEach(function (p, i) {
            h += '<th class="wt-col" data-col="' + i + '"><button type="button" class="wt-head" data-col="' + i + '">' +
                '<b>' + escapeHtml(colName(i)) + '</b>' + (i > 0 ? '<small>' + escapeHtml(SPREAD_LABEL[p.spread] || p.spread + '일 분할') + '</small>' : '') +
                '</button></th>';
        });
        h += '</tr></thead><tbody>';
        rows.forEach(function (s) {
            h += '<tr><td class="wt-name"><span class="wt-name__text"><b>' + escapeHtml(s.name) + '</b><small>' + escapeHtml(s.code) +
                '<span class="ps-market badge-' + escapeHtml((s.market || '').toLowerCase()) + '">' + escapeHtml(s.market || '') + '</span></small></span>' +
                // Tab 순서에서 뺀다 — 칸끼리만 옮겨 다니게(줄 끝에서 ✕ 로 갔다). 키보드는 칸을 비워 뺀다.
                '<button type="button" class="wt-rm" tabindex="-1" data-code="' + escapeHtml(s.code) + '" aria-label="' + escapeHtml(s.name) + ' 빼기">&times;</button></td>';
            phases.forEach(function (p, i) {
                var w = weightOf(p.stocks, s.code);
                h += '<td class="wt-td"><span class="wt-box"><input type="number" class="wt-cell" data-col="' + i + '" data-code="' + escapeHtml(s.code) + '" min="0" max="100" step="1"' +
                    ' placeholder="—" value="' + (w === null ? '' : w) + '" aria-label="' + escapeHtml(s.name + ' · ' + colName(i)) + '"></span></td>';
            });
            h += '</tr>';
        });
        h += '</tbody><tfoot><tr><td class="wt-name">합계</td>';
        phases.forEach(function (p, i) { h += '<td class="wt-sum" data-col="' + i + '"></td>'; });
        h += '</tr></tfoot>';
        t.innerHTML = h;
        wrap.appendChild(t);
        return wrap;
    }

    // 포트폴리오 표 그리기(구조가 바뀔 때)
    function renderPortfolio() {
        fieldError('btStocksError', '');
        var rows = tableRows();
        tableTargets().forEach(function (box) {
            box.textContent = '';
            if (!rows.length) {
                box.innerHTML = '<p class="empty-hint">검색 결과에서 [+ 포트폴리오] 버튼을 눌러 추가하세요</p>';
                return;
            }
            box.appendChild(buildTable());
        });
        refreshTable();
        checkPhaseStarts();
    }

    /** 합계를 100% 로 — 비례로 맞춘다(직접 넣은 비율은 살린다 — 균등 배분은 그걸 지웠고 어느 열에 걸리는지도 애매했다, 사용자 A안). */
    function fitColumn(i) {
        var list = phases[i].stocks, total = list.reduce(function (a, b) { return a + b.weight; }, 0);
        if (!list.length || total <= 0) return;
        var big = 0;
        list.forEach(function (s, k) {
            s.weight = Math.round(s.weight * 10000 / total) / 100;
            if (s.weight > list[big].weight) big = k;
        });
        var rest = Math.round((100 - list.reduce(function (a, b) { return a + b.weight; }, 0)) * 100) / 100;
        list[big].weight = Math.round((list[big].weight + rest) * 100) / 100;   // 반올림 남은 것은 가장 큰 칸에
        renderPortfolio();
        updateRunButtonState();
        scheduleAutoRecalc();
    }

    /** 표를 다시 그리지 않고 고친다 — 고른 열·오류 점·앞 열 대비 색·합계·! 표시·[크게 보기]. */
    function refreshTable() {
        tableTargets().forEach(function (box) {
            box.querySelectorAll('.wt-col').forEach(function (th) {
                th.classList.toggle('has-error', !!phaseProblem(+th.dataset.col));
            });
            box.querySelectorAll('.wt-cell').forEach(function (inp) {
                var i = +inp.dataset.col, code = inp.dataset.code;
                var w = weightOf(phases[i].stocks, code), prev = i > 0 ? weightOf(phases[i - 1].stocks, code) : undefined;
                var cls = '';
                if (i > 0 && w !== null) cls = prev === null ? 'is-new' : w > prev ? 'is-up' : w < prev ? 'is-down' : '';
                inp.className = 'wt-cell' + (cls ? ' ' + cls : '');
                var td = inp.parentNode, warn = td.querySelector('.wt-warn');
                var start = stockStarts[code];
                var late = i > 0 && w !== null && start && phases[i].date && start > phases[i].date;
                if (late && !warn) {
                    warn = document.createElement('span');
                    warn.className = 'metric-info wt-warn';
                    warn.tabIndex = 0;
                    warn.innerHTML = '!<span class="metric-tooltip"></span>';
                    td.appendChild(warn);
                }
                if (warn && !late) warn.remove();
                else if (late) warn.querySelector('.metric-tooltip').textContent = start + '부터 시세 — 이 시점 구성은 그날 시작';
            });
            box.querySelectorAll('.wt-sum').forEach(function (td) {
                var i = +td.dataset.col, total = phases[i].stocks.reduce(function (a, b) { return a + b.weight; }, 0);
                var ok = Math.abs(total - 100) <= 0.5;
                td.textContent = (Math.round(total * 100) / 100) + (ok ? ' ✓' : ' ✗');
                td.classList.toggle('is-bad', !ok);
                if (!ok && total > 0) {   // 100 이 아닌 열에만 — 누르면 비례로 맞춘다
                    var fit = document.createElement('button');
                    fit.type = 'button';
                    fit.className = 'wt-fit';
                    fit.dataset.col = String(i);
                    fit.setAttribute('aria-label', '합계 100%로 맞추기');
                    fit.innerHTML = '<svg class="c-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"' +
                        ' stroke-linejoin="round" aria-hidden="true">' +
                        '<path d="m16 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="m2 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="M7 21h10"/><path d="M12 3v18"/><path d="M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2"/></svg>';   // 저울 — _icons.html 'balance'
                    td.appendChild(fit);
                }
            });
        });
        // [크게 보기]는 칸에 다 들어가지 않을 때만
        var wrap = document.querySelector('#selectedStocks .wt-wrap'), ex = document.getElementById('phaseExpand');
        if (ex) ex.hidden = !(wrap && wrap.scrollWidth > wrap.clientWidth + 2);
    }

    /** 칸 하나 고치기 — 비우거나 0 이면 그 시점에서 뺀다. 행이 생기거나 사라지면 표를 다시 그린다(포커스는 지킨다). */
    function setCell(code, i, raw) {
        var list = phases[i].stocks, idx = -1;
        for (var k = 0; k < list.length; k++) if (list[k].code === code) idx = k;
        var v = parseFloat(raw);
        var rowsBefore = tableRows().length;
        if (!(v > 0)) {
            if (idx >= 0) list.splice(idx, 1);
        } else if (idx >= 0) {
            list[idx].weight = v;
        } else {
            if (list.length >= MAX_STOCKS) { notify('한 시점에 ' + MAX_STOCKS + '개까지 담을 수 있습니다.'); renderPortfolio(); return; }
            var info = tableRows().filter(function (s) { return s.code === code; })[0];
            list.push({ code: code, name: info.name, market: info.market, weight: v });
        }
        if (tableRows().length !== rowsBefore) renderPortfolio();
        else refreshTable();
        updateSignalTargets();
        updateRunButtonState();
        updateDateRange();
        scheduleAutoRecalc();
    }

    /** 행 빼기 — 모든 시점에서. 묻지 않고 빼고 토스트 [되돌리기](되돌릴 수 있는 일). */
    function removeRow(code) {
        var snap = phases.map(function (p) { return { date: p.date, spread: p.spread, stocks: slimStocks(p.stocks) }; });
        var snapExtra = extraRows.slice();
        var name = (tableRows().filter(function (s) { return s.code === code; })[0] || {}).name || code;
        phases.forEach(function (p) { p.stocks = p.stocks.filter(function (s) { return s.code !== code; }); });
        extraRows = extraRows.filter(function (s) { return s.code !== code; });
        portfolio = phases[selPhase].stocks;
        renderPortfolio();
        updateSignalTargets();
        updateRunButtonState();
        updateDateRange();
        notify('"' + name + '"을 뺐습니다.', 'info', { action: { label: '되돌리기', onClick: function () {
            phases = snap;
            extraRows = snapExtra;
            selPhase = Math.min(selPhase, phases.length - 1);
            portfolio = phases[selPhase].stocks;
            renderPortfolio();
            updateSignalTargets();
            updateRunButtonState();
            updateDateRange();
        } } });
    }

    /** 시점마다 늦게 시작하는 종목을 알기 위해 시세 첫날을 한 번씩 묻는다(코드별로 기억). */
    function checkPhaseStarts() {
        if (phases.length < 2) return;
        allPhaseStocks().forEach(function (s) {
            if (s.code in stockStarts) return;
            stockStarts[s.code] = undefined;
            fetch('/api/v1/backtest/date-range?codes=' + encodeURIComponent(s.code) + '&markets=' + encodeURIComponent(s.market || ''))
                .then(function (r) { return r.ok ? r.json() : {}; })
                .then(function (j) { stockStarts[s.code] = (j && j.min) || null; refreshTable(); })
                .catch(function () { /* ! 만 못 띄운다 */ });
        });
    }

    /** [＋ 시점] — 마지막 열 비중을 복사한 새 열(날짜 = 마지막 시점과 종료일의 가운데), 곧바로 그 열의 창을 연다. */
    function addPhase() {
        if (phases.length > MAX_CHANGES) { notify('시점은 ' + (MAX_CHANGES + 1) + '개까지입니다.'); return; }
        var start = document.getElementById('startDate').value, end = document.getElementById('endDate').value;
        var last = phases.length === 1 ? start : phases[phases.length - 1].date;
        var a = Date.parse(last), b = Date.parse(end);
        var mid = (!isNaN(a) && !isNaN(b) && b > a) ? new Date(a + Math.round((b - a) / 2 / 864e5) * 864e5).toISOString().slice(0, 10) : '';
        var p = { date: mid, spread: 1, stocks: slimStocks(phases[phases.length - 1].stocks) };
        phases.push(p);
        selPhase = phases.length - 1;
        portfolio = p.stocks;
        renderPortfolio();
        updateRunButtonState();
        var head = document.querySelector('#' + (document.getElementById('phaseDlg').open ? 'phaseDlgBody' : 'selectedStocks') + ' .wt-head[data-col="' + selPhase + '"]');
        if (head) { head.scrollIntoView({ block: 'nearest', inline: 'nearest' }); openPhasePop(p, head); }
    }

    /** 시점 지우기 — 묻지 않고 지우고 토스트 [되돌리기]. */
    function removePhase(i) {
        if (i <= 0 || i >= phases.length) return;
        var gone = phases.splice(i, 1)[0];
        selPhase = Math.min(selPhase, phases.length - 1);
        portfolio = phases[selPhase].stocks;
        renderPortfolio();
        updateSignalTargets();
        updateRunButtonState();
        notify((gone.date ? shortDate(gone.date) + ' ' : '') + '시점을 지웠습니다.', 'info', { action: { label: '되돌리기', onClick: function () {
            phases.push(gone);
            sortPhases();
            renderPortfolio();
            updateSignalTargets();
            updateRunButtonState();
        } } });
    }

    /** 열 머리 아래에 시점 창(바꾸는 날·옮기는 방법·지우기). */
    function openPhasePop(p, anchor) {
        var pop = document.getElementById('phasePop');
        popPhase = p;
        var start = document.getElementById('startDate').value, end = document.getElementById('endDate').value;
        var dateEl = document.getElementById('phaseDate');
        dateEl.value = p.date || '';
        dateEl.min = start || '';
        dateEl.max = end || '';
        document.getElementById('phaseSpread').value = String(p.spread || 1);
        showPopError();
        var r = anchor.getBoundingClientRect(), w = Math.min(240, window.innerWidth - 16);
        pop.style.width = w + 'px';
        pop.style.top = Math.round(r.bottom + 6) + 'px';
        pop.style.left = Math.round(Math.max(8, Math.min(r.left + r.width / 2 - w / 2, window.innerWidth - w - 8))) + 'px';
        if (!pop.matches(':popover-open')) pop.showPopover();
    }

    function showPopError() {
        var i = phases.indexOf(popPhase), el = document.getElementById('phasePopError');
        var prob = i > 0 ? phaseProblem(i) : null;
        var dateProb = prob && /바꾸는 날|같은 날/.test(prob);
        el.textContent = dateProb ? prob : '';
        el.hidden = !dateProb;
    }

    /** 표 하나(카드·크게 보기 창)에 이벤트를 단다 — 칸 고치기·열 고르기·열 머리 창·행 빼기. 한 번만(위임). */
    function bindTable(box) {
        if (!box || box._wtBound) return;
        box._wtBound = true;
        box.addEventListener('change', function (e) {
            var inp = e.target.closest && e.target.closest('.wt-cell');
            if (inp) setCell(inp.dataset.code, +inp.dataset.col, inp.value);
        });
        box.addEventListener('focusin', function (e) {
            var inp = e.target.closest && e.target.closest('.wt-cell');
            if (!inp) return;
            if (+inp.dataset.col !== selPhase) selectPhase(+inp.dataset.col);
            // 들어가면 숫자 전체를 고른다(스프레드시트처럼) — 안 그러면 "60" 칸에 30 을 쳐 "3060" 이 됐다. 마우스 눌림이 선택을 풀지 않게 한 박자 뒤에.
            setTimeout(function () { if (document.activeElement === inp) inp.select(); }, 0);
        });
        box.addEventListener('keydown', function (e) {   // Enter 는 아래 칸
            var inp = e.target.closest && e.target.closest('.wt-cell');
            if (!inp || e.key !== 'Enter') return;
            e.preventDefault();
            var cells = [].slice.call(box.querySelectorAll('.wt-cell[data-col="' + inp.dataset.col + '"]'));
            var next = cells[cells.indexOf(inp) + 1];
            inp.blur();
            if (next) { next.focus(); next.select(); }
        });
        box.addEventListener('click', function (e) {
            var head = e.target.closest && e.target.closest('.wt-head');
            if (head) {
                var i = +head.dataset.col;
                selectPhase(i);
                if (i > 0) openPhasePop(phases[i], head);
                return;
            }
            var rm = e.target.closest && e.target.closest('.wt-rm');
            if (rm) { removeRow(rm.dataset.code); return; }
            var fit = e.target.closest && e.target.closest('.wt-fit');
            if (fit) fitColumn(+fit.dataset.col);
        });
    }

    // 시그널 타겟 옵션 업데이트
    function updateSignalTargets() {
        document.querySelectorAll('.signal-target').forEach(function (sel) {
            var currentVal = sel.value;
            sel.innerHTML = '';
            allPhaseStocks().forEach(function (s) {
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
        var hint = document.querySelector('#dcaDeferHint .metric-tooltip');
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

        // 세부 점수 — 레이더 차트
        var radarLabels = ['CAGR', '연간수익률', '총수익률', 'MDD', '샤프', '소르티노'];
        var radarKeys = ['cagr', 'avgAnnual', 'totalReturn', 'mdd', 'sharpe', 'sortino'];
        var radarData = radarKeys.map(function (k) { return Math.round(scoreResult.scores[k]); });

        var radarDatasets = [{
            label: '포트폴리오',
            data: radarData,
            backgroundColor: 'rgba(59, 130, 246, 0.2)',
            borderColor: 'rgba(59, 130, 246, 0.8)',
            borderWidth: 2,
            pointBackgroundColor: 'rgba(59, 130, 246, 1)',
            pointRadius: 3
        }];

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
            bmkResults.forEach(function (bmkItem, bmkIdx) {
                if (!bmkItem.metrics) return;
                var bm = bmkItem.metrics;
                var colorStyle = ' style="color:' + bmkItem.color + '"';
                var safeName = escapeHtml(bmkItem.name);
                var dotPrefix = '<span class="bmk-val" data-bmk="' + safeName + '"' + colorStyle + '><span class="bmk-dot" style="background:' + bmkItem.color + '"></span>';
                bmkLines.bmkTotalReturn.push(dotPrefix + formatPercent(bm.totalReturn) + '</span>');
                bmkLines.bmkAvgAnnual.push(dotPrefix + formatPercent(bm.avgAnnual) + '</span>');
                bmkLines.bmkCAGR.push(dotPrefix + formatPercent(bm.cagr) + '</span>');
                bmkLines.bmkMDD.push(dotPrefix + formatPercent(-bm.mdd) + '</span>');
                bmkLines.bmkSharpe.push(dotPrefix + (bm.sharpe === null || !isFinite(bm.sharpe) ? '∞' : bm.sharpe.toFixed(2)) + '</span>');
                bmkLines.bmkSortino.push(dotPrefix + (bm.sortino === null || !isFinite(bm.sortino) ? '∞' : bm.sortino.toFixed(2)) + '</span>');
                var bmkScore = calculateTotalScore(bm);
                bmkScoreLines.push('<span class="bmk-val" data-bmk="' + safeName + '"' + colorStyle + '><span class="bmk-dot" style="background:' + bmkItem.color + '"></span>' + bmkScore.total + '점 (' + bmkScore.grade + ')</span>');
                // 벤치마크 레이더 데이터셋 추가
                var bmkRadarData = radarKeys.map(function (k) { return Math.round(bmkScore.scores[k]); });
                radarDatasets.push({
                    label: bmkItem.name,
                    data: bmkRadarData,
                    backgroundColor: bmkItem.color.replace('rgb(', 'rgba(').replace(')', ', 0.1)'),
                    borderColor: bmkItem.color,
                    borderWidth: 1.5,
                    pointBackgroundColor: bmkItem.color,
                    pointRadius: 2
                });
            });
            bmkMetricIds.forEach(function (id) {
                var el = document.getElementById(id);
                if (el && bmkLines[id].length > 0) {
                    el.innerHTML = bmkLines[id].join(' ');
                    el.classList.add('visible');
                }
            });
            if (bmkScoreEl && bmkScoreLines.length > 0) {
                bmkScoreEl.innerHTML = bmkScoreLines.join(' ');
                bmkScoreEl.classList.add('visible');
            }
        }

        // 레이더 차트 렌더링
        renderScoreRadar(radarLabels, radarDatasets);

        // 차트
        renderChart(data.dailySeries, bmkResults, data.changedAt);
        renderPhaseStrip(data.changedAt, data.dailySeries);

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
        var nChanges = (data.changedAt || []).length;
        document.getElementById('tradePhaseStat').hidden = !nChanges;
        document.getElementById('tradePhaseCount').textContent = nChanges + '회';
    }

    /**
     * 구간별 구성 — 차트 아래 띠. 폭 = 실제 기간(바뀐 날 기준), 안 = 비중대로 나눈 막대(같은 종목은 어느 구간이든 같은 색).
     * 번호는 차트의 세로 점선 번호와 같다. 구성 변경이 없으면 숨는다.
     */
    function renderPhaseStrip(changedAt, series) {
        var box = document.getElementById('phaseStrip');
        if (!box) return;
        box.textContent = '';
        var ph = lastRunPhases || [];
        if (!changedAt || !changedAt.length || !series || !series.length || ph.length < 2) { box.hidden = true; return; }
        box.hidden = false;
        var row = document.createElement('div');
        row.className = 'phase-strip__row';
        box.appendChild(row);
        var first = series[0].date, last = series[series.length - 1].date;
        var starts = [first].concat(changedAt.map(function (c) { return c.date; }));
        var colorOf = {}, nColor = 0;
        ph.forEach(function (p) { p.stocks.forEach(function (s) { if (!(s.code in colorOf)) colorOf[s.code] = PHASE_COLORS[nColor++ % PHASE_COLORS.length]; }); });
        starts.forEach(function (d0, i) {
            var p = ph[changedAt[i - 1] ? changedAt[i - 1].phase : 0] || ph[i];
            var d1 = starts[i + 1] || last;
            var seg = document.createElement('div');
            seg.className = 'phase-strip__seg';
            seg.style.flexGrow = Math.max(1, (Date.parse(d1) - Date.parse(d0)) / 864e5);
            var bar = document.createElement('div');
            bar.className = 'phase-strip__bar';
            p.stocks.forEach(function (s) {
                var part = document.createElement('span');
                part.style.flexGrow = s.weight;
                part.style.background = colorOf[s.code];
                bar.appendChild(part);
            });
            var cap = document.createElement('div');
            cap.className = 'phase-strip__cap';
            cap.textContent = shortDate(d0) + ' — ' + p.stocks.map(function (s) { return s.name + ' ' + s.weight + '%'; }).join(' · ');
            seg.appendChild(bar);
            seg.appendChild(cap);
            row.appendChild(seg);
        });
        var legend = document.createElement('div');
        legend.className = 'phase-strip__legend';
        Object.keys(colorOf).forEach(function (code) {
            var st = null;
            ph.forEach(function (p) { p.stocks.forEach(function (s) { if (s.code === code && !st) st = s; }); });
            var item = document.createElement('span');
            var dot = document.createElement('i');
            dot.style.background = colorOf[code];
            item.appendChild(dot);
            item.appendChild(document.createTextNode((st && st.name) || code));
            legend.appendChild(item);
        });
        box.appendChild(legend);
    }

    // 설정 수집
    function collectConfig() {
        for (var pi = 0; pi < phases.length; pi++) if (phaseProblem(pi)) return null;
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
            stocks: slimStocks(phases[0].stocks),
            changes: collectChanges(),
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

    /**
     * 칸 옆 검증 오류 — 폼 검증은 토스트가 아니라 그 칸 옆에 보인다(정본 toast.md D2, 2026-10-13).
     * 글자를 주면 보이고 화면에 들어오게 하며, 빈 글자면 숨긴다.
     */
    function fieldError(id, message) {
        var el = document.getElementById(id);
        if (!el) return;
        el.textContent = message || '';
        el.hidden = !message;
        if (message) el.scrollIntoView({ block: 'nearest' });
    }

    function clearRunErrors() {
        ['btStocksError', 'btDateError', 'btRulesError'].forEach(function (id) { fieldError(id, ''); });
    }

    // 설정 수집 + 유효성 검사 (오류는 칸 옆에)
    function collectConfigWithAlert() {
        clearRunErrors();
        if (allPhaseStocks().length > MAX_UNIVERSE) {
            fieldError('btStocksError', '모든 구간을 합쳐 종목은 ' + MAX_UNIVERSE + '개까지입니다.');
            return null;
        }
        // 문제 있는 첫 시점을 골라 표 아래에 보인다(시점이 하나면 예전과 같은 문구)
        for (var pi = 0; pi < phases.length; pi++) {
            var prob = phaseProblem(pi);
            if (!prob) continue;
            if (pi !== selPhase) selectPhase(pi);
            var where = phases.length > 1 ? colName(pi) + ': ' : '';
            fieldError('btStocksError', where + (prob.indexOf('비중') === 0 ? '종목 ' + prob : prob.replace('넣으세요', '추가하세요')));
            return null;
        }
        var startDate = document.getElementById('startDate').value;
        var endDate = document.getElementById('endDate').value;
        if (!startDate || !endDate || startDate >= endDate) {
            fieldError('btDateError', '시작일이 종료일보다 앞서야 합니다.');
            return null;
        }
        var activeTab = document.querySelector('.strategy-tab.active');
        var strategy = activeTab ? activeTab.dataset.strategy : 'buyhold';
        if (strategy === 'signal') {
            var rules = document.querySelectorAll('.signal-rule');
            if (rules.length === 0) {
                fieldError('btRulesError', '시그널 기반 전략에는 최소 1개의 규칙이 필요합니다.');
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
        setRunLabel(btn, '실행 중...');
        var runPhases = phases.map(function (p) { return { date: p.date, spread: p.spread, stocks: slimStocks(p.stocks) }; });

        var progressDiv = document.getElementById('backtestProgress');
        var progressFill = document.getElementById('progressFill');
        var progressText = document.getElementById('progressText');

        progressDiv.style.display = '';
        progressFill.style.width = '30%';
        progressText.textContent = '서버에서 시뮬레이션 중...';

        // `save=true` 라야 랭킹에 들어간다 — 옛 API 는 항상 저장했다.
        apiFetchOptional('/api/v1/backtest/run?save=true', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        })
            .then(function (r) {
                if (!r.ok) return apiError(r).then(function (e) { throw e; });
                return r.json();
            })
            .then(function (json) {
                progressFill.style.width = '100%';
                progressDiv.style.display = 'none';
                // ⚠️ 결과가 한 겹 더 감싸여 있지 않다 — 엔진 결과 위에 `portfolio` 만 얹혀 온다.
                lastRunPhases = runPhases;
                displayResults(json);

                // 저장이 실패해도 계산 결과는 온다(그때는 `portfolio` 가 없다).
                if (json.portfolio && json.portfolio.id) {
                    updatePortfolioNameUI(json.portfolio.id, json.portfolio.name || '',
                                          json.portfolio.mine, json.portfolio.is_public, true, runPhases.length);
                }

                hasRunOnce = true;
                lastRunKey = JSON.stringify(config);
                btn.disabled = false;
                updateRunButtonState();

                document.getElementById('metricsCards').scrollIntoView({ behavior: 'smooth', block: 'start' });
            })
            .catch(function (err) {
                console.error('백테스트 에러:', err);
                if (!silent) notify(err.message || '시뮬레이션 중 오류가 발생했습니다.');
                btn.disabled = false;
                updateRunButtonState();
                progressDiv.style.display = 'none';
            });
    }

    /* =========================================
       포트폴리오 랭킹 연동
       ========================================= */
    var currentPortfolioId = null;

    /**
     * 포트폴리오 이름 편집 UI 업데이트
     */
    function updatePortfolioNameUI(id, name, mine, isPublic, ran, phaseCount) {
        currentPortfolioId = id;
        var section = document.getElementById('portfolioNameSection');
        var nameEl = document.getElementById('portfolioNameText');
        if (!section || !nameEl) return;
        nameEl.textContent = name || '';
        section.classList.remove('is-empty');
        // 이름 연필도 **내 것일 때만** — 남의 것·주인 없는 것은 저장하면 404 다(2026-10-13 점검).
        var editBtn = document.getElementById('portfolioNameEdit');
        if (editBtn) editBtn.hidden = !mine;
        // 공개 토글은 **내 것일 때만** 보인다. 비로그인이 돌린 것은 주인이 없어
        // 공개로 고정이고, 바꿀 수단을 주면 눌러도 403 만 돌아온다.
        // 실행 전(옛 프리셋에서 옮긴 것)은 점수가 없어 공개 토글을 숨긴다 — 0점이 랭킹에 오르지 않게. 실행하면 켜진다.
        // 구성 변경이 있으면 랭킹에 올리지 않는다 — 토글 대신 ⓘ 로 이유를 보인다(서버도 막는다)
        var staged = (phaseCount || 1) > 1;
        renderPublicToggle(!!mine && ran !== false && !staged, !!isPublic);
        var note = document.getElementById('portfolioRankNote');
        if (note) note.hidden = !(mine && staged);
    }

    /** ☆ 줄을 처음(실행 전 안내) 상태로 — 지금 연 포트폴리오를 목록에서 지웠을 때. */
    function clearPortfolioNameUI() {
        currentPortfolioId = null;
        var section = document.getElementById('portfolioNameSection');
        var nameEl = document.getElementById('portfolioNameText');
        var editBtn = document.getElementById('portfolioNameEdit');
        if (section) section.classList.add('is-empty');
        if (nameEl) nameEl.textContent = '실행하면 자동 저장됩니다';
        if (editBtn) editBtn.hidden = true;
        renderPublicToggle(false, false);
        var note = document.getElementById('portfolioRankNote');
        if (note) note.hidden = true;
    }

    /**
     * 공개/비공개 토글 표시 갱신
     */
    function renderPublicToggle(mine, isPublic) {
        var btn = document.getElementById('portfolioPublicToggle');
        var label = document.getElementById('portfolioPublicLabel');
        var info = document.getElementById('portfolioPublicInfo');
        if (!btn || !label) return;
        if (info) info.hidden = !mine;
        if (!mine) { btn.style.display = 'none'; return; }
        btn.style.display = '';
        btn.setAttribute('aria-pressed', isPublic ? 'true' : 'false');
        btn.classList.toggle('is-public', isPublic);
        label.textContent = isPublic ? '공개' : '비공개';
    }

    /**
     * 공개 여부 서버 저장
     */
    function savePortfolioPublic(next) {
        if (!currentPortfolioId) return;
        apiFetch('/api/v1/backtest/portfolios/' + encodeURIComponent(currentPortfolioId), {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_public: next })
        })
            .then(function (r) {
                if (!r.ok) return apiError(r).then(function (e) { throw e; });
                return r.json();
            })
            .then(function (json) {
                // 서버가 돌려준 값을 그대로 반영한다 — 눌린 값을 믿지 않는다.
                renderPublicToggle(true, json.is_public);
                notify(json.is_public ? '포트폴리오를 랭킹에 공개했습니다.' : '포트폴리오를 비공개로 바꿨습니다.', 'success');
            })
            .catch(function (err) { notify(err.message || '공개 여부를 바꾸지 못했습니다.'); });
    }

    /**
     * 포트폴리오 이름 서버 저장
     */
    function savePortfolioName(name, prevName) {
        if (!currentPortfolioId || !name) return;
        var id = currentPortfolioId;
        apiFetch('/api/v1/backtest/portfolios/' + encodeURIComponent(currentPortfolioId), {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name })
        })
            .then(function (r) {
                if (!r.ok) return apiError(r).then(function (e) { throw e; });
                notify('포트폴리오 이름을 바꿨습니다.', 'success');
            })
            .catch(function (err) {
                // 먼저 바꿔 보인 이름을 되돌린다(그사이 다른 포트폴리오로 바뀌었으면 그대로 둔다).
                var nameEl = document.getElementById('portfolioNameText');
                if (nameEl && currentPortfolioId === id && nameEl.textContent === name) nameEl.textContent = prevName;
                notify(err.message || '포트폴리오 이름을 바꾸지 못했습니다.');
            });
    }

    /**
     * URL 파라미터에서 포트폴리오 ID로 설정 로드
     */
    function loadFromPortfolioId(id) {
        // 랭킹에서 넘어온 비로그인 방문자도 공개분은 열 수 있어야 한다 — 토큰은 선택이다.
        return apiFetchOptional('/api/v1/backtest/portfolios/' + encodeURIComponent(id))
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (json) {
                if (!json || !json.config) return false;
                applyConfig(json.config);
                updatePortfolioNameUI(json.id, json.name, json.mine, json.is_public, json.ran, json.phases);
                return true;
            })
            .catch(function () { return false; });
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
            portfolio: slimStocks(phases[0].stocks),
            changes: collectChanges(),
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
            // ⚠️ 기간은 담지 않는다 — 프리셋과 같은 규칙이다(withoutDates 주석 참조).
            riskFreeRate: document.getElementById('riskFreeRate').value,
            savedAt: new Date().toISOString()
        };

        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
            notify('설정을 이 브라우저에 저장했습니다.', 'success');
        } catch (e) {
            notify('설정 저장에 실패했습니다.');
        }
    }

    function loadConfigFromStorage() {
        try {
            var raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) { notify('저장된 설정이 없습니다.'); return; }
            var data = JSON.parse(raw);

            setPhases([{ date: null, spread: 1, stocks: (data.portfolio || []).map(function (s) {
                return { code: s.code, name: s.name, market: s.market, weight: s.weight };
            }) }].concat((data.changes || []).map(function (c) {
                return { date: c.date, spread: c.spreadDays || 1, stocks: c.stocks.map(function (s) {
                    return { code: s.code, name: s.name, market: s.market, weight: s.weight }; }) };
            })));

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
            // 기간은 복원하지 않는다 — 옛 저장본에 남아 있어도 화면 값을 그대로 둔다.
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

            notify('저장해 둔 설정을 불러왔습니다.', 'success');
            updateDateRange();
        } catch (e) {
            notify('설정 불러오기에 실패했습니다.');
        }
    }

    function clearStoredConfig() {
        localStorage.removeItem(STORAGE_KEY);
        notify('저장해 둔 설정을 지웠습니다.', 'success');
    }

    /* =========================================
       내 포트폴리오 (로그인 사용자 — 2026-10-19 프리셋을 여기로 합쳤다)
       ========================================= */

    /**
     * 프리셋에 담지 않을 것 — **기간**(2026-08-23 사용자 지시).
     *
     * 프리셋은 "이 종목 조합·전략" 을 기억하는 것이지 "그때 봤던 기간" 이 아니다.
     * 기간까지 들어 있으면 불러올 때마다 화면의 날짜가 예전 값으로 되돌아간다.
     * ⚠️ 이미 날짜가 들어간 채 저장된 옛 프리셋이 있으므로, **불러올 때도** 걷어낸다.
     */
    function withoutDates(config) {
        var copy = {};
        Object.keys(config || {}).forEach(function (k) {
            if (k !== 'startDate' && k !== 'endDate') copy[k] = config[k];
        });
        return copy;
    }

    var STRATEGY_LABEL = { buyhold: 'B&H', rebalance: '리밸', signal: '시그널' };
    var TRASH_SVG = '<svg class="c-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18"/>' +
        '<path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2"/><path d="m19 6-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>';

    /**
     * ☆ 줄 끝 목록 버튼 → "내 포트폴리오"(popover). 열 때마다 서버에서 다시 읽는다(☆ 줄에서 이름·공개를 바꿨을 수 있다).
     * 이름을 누르면 그 설정을 불러오고(기간은 화면 것 그대로 — withoutDates) ☆ 줄이 그 포트폴리오가 된다.
     */
    function initPortfolioMenu() {
        var menu = document.getElementById('portfolioMenu');
        var btn = document.getElementById('portfolioListBtn');
        if (!menu || !btn) return;
        // 목록 버튼 아래, 오른쪽 끝을 맞춘다(화면 밖으로 나가지 않게). 창은 화면에 고정(top layer)이라 페이지를 스크롤하면
        // 버튼만 움직여 떨어졌다(2026-10-19 사용자) — 스크롤·창 크기가 바뀔 때마다 다시 붙이고, 버튼이 화면 밖으로 나가면 닫는다.
        function place() {
            var r = btn.getBoundingClientRect(), w = Math.min(416, window.innerWidth - 16);
            if (r.bottom < 0 || r.top > window.innerHeight) { menu.hidePopover(); return; }
            menu.style.width = w + 'px';
            menu.style.top = Math.round(r.bottom + 6) + 'px';
            menu.style.left = Math.round(Math.max(8, Math.min(r.right - w, window.innerWidth - w - 8))) + 'px';
        }
        function follow(e) {
            // 목록 안의 스크롤은 무시. ⚠️ resize 는 대상이 window 라 Node 인지 먼저 본다(contains 가 던졌다)
            if (e && e.target instanceof Node && e.target !== document && menu.contains(e.target)) return;
            if (menu.matches(':popover-open')) place();
        }
        menu.addEventListener('beforetoggle', function (e) {
            var open = e.newState === 'open';
            btn.setAttribute('aria-expanded', String(open));
            if (!open) return;
            place();
            renderPortfolioMenu();
        });
        document.addEventListener('scroll', follow, { capture: true, passive: true });
        window.addEventListener('resize', follow);
    }

    function renderPortfolioMenu() {
        var list = document.getElementById('portfolioMenuList');
        var count = document.getElementById('portfolioMenuCount');
        list.innerHTML = '<li class="portfolio-menu__empty">불러오는 중…</li>';
        apiFetch('/api/v1/backtest/portfolios')
            .then(function (r) {
                if (!r.ok) return apiError(r).then(function (e) { throw e; });
                return r.json();
            })
            .then(function (rows) {
                count.textContent = rows.length ? ' · ' + rows.length : '';
                list.textContent = '';
                if (!rows.length) {
                    list.innerHTML = '<li class="portfolio-menu__empty">아직 없습니다 — 실행하면 자동으로 저장됩니다</li>';
                    return;
                }
                rows.forEach(function (p) {
                    var li = document.createElement('li');
                    li.className = 'portfolio-menu__item' + (p.id === currentPortfolioId ? ' is-current' : '');
                    var load = document.createElement('button');
                    load.type = 'button';
                    load.className = 'portfolio-menu__load';
                    var name = document.createElement('span');
                    name.className = 'portfolio-menu__name';
                    name.textContent = p.name;
                    var sub = document.createElement('span');
                    sub.className = 'portfolio-menu__sub';
                    sub.textContent = p.stock_summary || '';
                    load.appendChild(name);
                    load.appendChild(sub);
                    load.addEventListener('click', function () { openPortfolio(p.id); });
                    var grade = document.createElement('span');
                    grade.className = 'portfolio-menu__grade' + (p.ran ? '' : ' is-new');
                    grade.textContent = p.ran ? (p.ranking_grade || '-') + ' ' + Math.round(p.ranking_score || 0) : '실행 전';
                    var tags = document.createElement('span');
                    tags.className = 'portfolio-menu__tags';
                    tags.textContent = (STRATEGY_LABEL[p.strategy] || p.strategy || '') + (p.phases > 1 ? ' · 구성 변경 ' + (p.phases - 1) + '회' : '')
                        + (p.is_public ? ' · 공개' : '');
                    var del = document.createElement('button');
                    del.type = 'button';
                    del.className = 'c-btn portfolio-menu__del';
                    del.innerHTML = TRASH_SVG + '<span>지우기</span>';
                    del.addEventListener('click', function () { deletePortfolio(p); });
                    li.appendChild(load);
                    li.appendChild(grade);
                    li.appendChild(tags);
                    li.appendChild(del);
                    list.appendChild(li);
                });
            })
            .catch(function (err) {
                list.innerHTML = '';
                var li = document.createElement('li');
                li.className = 'portfolio-menu__empty';
                li.textContent = '목록을 불러오지 못했습니다: ' + (err.message || '');
                list.appendChild(li);
            });
    }

    function openPortfolio(id) {
        apiFetch('/api/v1/backtest/portfolios/' + encodeURIComponent(id))
            .then(function (r) {
                if (!r.ok) return apiError(r).then(function (e) { throw e; });
                return r.json();
            })
            .then(function (json) {
                if (!json.config) throw new Error('설정이 없는 포트폴리오입니다.');
                applyConfig(withoutDates(json.config));   // 기간은 화면 것을 그대로 둔다(2026-08-23 사용자 지시)
                updatePortfolioNameUI(json.id, json.name, json.mine, json.is_public, json.ran, json.phases);
                document.getElementById('portfolioMenu').hidePopover();
                notify('"' + json.name + '" 포트폴리오를 불러왔습니다.' + (json.ran ? '' : ' 실행하면 결과가 저장됩니다.'), 'success');
            })
            .catch(function (err) { notify(err.message || '포트폴리오를 불러오지 못했습니다.'); });
    }

    function deletePortfolio(p) {
        if (!confirm('"' + p.name + '" 포트폴리오를 지울까요?' + (p.is_public ? ' 랭킹에서도 빠집니다.' : ''))) return;
        apiFetch('/api/v1/backtest/portfolios/' + encodeURIComponent(p.id), { method: 'DELETE' })
            .then(function (r) {
                if (!r.ok) return apiError(r).then(function (e) { throw e; });
                if (p.id === currentPortfolioId) clearPortfolioNameUI();
                notify('"' + p.name + '" 포트폴리오를 지웠습니다.', 'success');
                renderPortfolioMenu();
            })
            .catch(function (err) { notify(err.message || '포트폴리오를 지우지 못했습니다.'); });
    }

    /**
     * 유효성 검사 없이 현재 폼 상태를 수집 (AI 상담 화면 맥락 — 저장 안 한 것 그대로)
     */
    function collectConfigRaw() {
        if (phases[0].stocks.length === 0) return null;
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
        }
        return {
            stocks: slimStocks(phases[0].stocks),
            changes: collectChanges(),
            benchmarks: benchmarks.map(function (b) { return { code: b.code, market: b.market, name: b.name }; }),
            startDate: document.getElementById('startDate').value,
            endDate: document.getElementById('endDate').value,
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

    /**
     * config 객체를 UI에 반영하는 공통 함수
     */
    function applyConfig(cfg) {
        var map = function (list) {
            return (list || []).map(function (s) { return { code: s.code, name: s.name || s.code, market: s.market, weight: s.weight }; });
        };
        setPhases([{ date: null, spread: 1, stocks: map(cfg.stocks) }].concat((cfg.changes || []).map(function (c) {
            return { date: c.date, spread: c.spreadDays || 1, stocks: map(c.stocks) };
        })));

        benchmarks = (cfg.benchmarks || []).map(function (b) {
            return { code: b.code, name: b.name || b.code, market: b.market };
        });
        renderBenchmark();

        document.querySelectorAll('.strategy-tab').forEach(function (t) { t.classList.remove('active'); });
        var targetTab = document.querySelector('.strategy-tab[data-strategy="' + (cfg.strategy || 'buyhold') + '"]');
        if (targetTab) targetTab.classList.add('active');
        document.getElementById('rebalanceConfig').style.display = cfg.strategy === 'rebalance' ? '' : 'none';
        document.getElementById('signalConfig').style.display = cfg.strategy === 'signal' ? '' : 'none';

        document.getElementById('rebalancePeriod').value = cfg.rebalancePeriod || 'quarterly';
        document.getElementById('signalCombine').value = cfg.signalCombine || 'or';

        document.getElementById('initialCapital').value = cfg.initialCapital ? (cfg.initialCapital / 10000) : '1000';
        document.getElementById('monthlyDCA').value = cfg.monthlyDCA ? (cfg.monthlyDCA / 10000) : '100';
        document.getElementById('dcaDeferIndicator').value = (cfg.dcaDefer && cfg.dcaDefer.indicator) || 'none';
        updateDcaDeferHint();

        if (cfg.fees) {
            document.getElementById('feeKR').value = cfg.fees.KR || '0.015';
            document.getElementById('feeUS').value = cfg.fees.US || '0.2';
            document.getElementById('feeCOIN').value = cfg.fees.COIN || '0.015';
        }
        document.getElementById('riskFreeRate').value = cfg.riskFreeRate || '3.0';

        if (cfg.startDate) document.getElementById('startDate').value = cfg.startDate;
        if (cfg.endDate) document.getElementById('endDate').value = cfg.endDate;

        document.getElementById('signalRules').innerHTML = '';
        (cfg.signalRules || []).forEach(function (rule) {
            addSignalRule();
            var rules = document.querySelectorAll('.signal-rule');
            var last = rules[rules.length - 1];
            last.querySelector('.signal-indicator').value = rule.indicator;
            updateSignalTargets();
            if (rule.targetCode) last.querySelector('.signal-target').value = rule.targetCode;
        });

        updateDateRange();
        updateRunButtonState();
    }

    /* =========================================
       설정 패널 고정 (2026-08-23 사용자 요청)

       결과가 2,000px 넘게 길어서, 아래를 보다 보면 오른쪽 설정 패널이 화면 밖으로
       사라져 매번 위로 올라가야 했다. 그래서 CSS 에서 `position: sticky` 로 붙였다.

       ⚠️ `top` 은 여기서 정한다. 패널이 창보다 길면 `top: 20px` 로는 붙일 수 없다 —
          맨 아래 [백테스트 실행] 이 화면 밖으로 밀려, 붙어 있는 동안 **영영 못 누른다**.
          그래서 그때는 음수 top 으로 **아래를 맞춰** 붙인다(위쪽은 페이지를 올리면 나온다).
       ========================================= */
    function updateConfigStickyTop() {
        var panel = document.querySelector('.backtest-config');
        if (!panel) return;
        // 한 컬럼(≤1024px)에서는 CSS 가 static 으로 되돌린다 — 계산할 것이 없다.
        if (getComputedStyle(panel).position !== 'sticky') { panel.style.top = ''; return; }
        // ⚠️ 상단바가 sticky 56px 라 그 높이를 더해야 패널이 그 뒤로 안 들어간다.
        //    CSS 토큰을 읽지 않고 **실제 높이를 재는** 이유는 안전영역(노치) 패딩이
        //    더해져 기기마다 값이 다르기 때문이다. 상단바가 없으면 0 이라 옛 동작 그대로다.
        var bar = document.querySelector('.c-topbar');
        var barH = bar ? Math.round(bar.getBoundingClientRect().height) : 0;
        var gap = barH + 20;
        var over = panel.offsetHeight + gap + 20 - window.innerHeight;
        panel.style.top = (over > 0 ? gap - over : gap) + 'px';
    }

    function initConfigSticky() {
        var panel = document.querySelector('.backtest-config');
        if (!panel) return;
        updateConfigStickyTop();
        window.addEventListener('resize', updateConfigStickyTop);
        // 종목 추가·고급 설정 펼침·프리셋 목록 로드로 패널 높이가 계속 바뀐다.
        if (window.ResizeObserver) {
            new ResizeObserver(updateConfigStickyTop).observe(panel);
        }
    }

    /* =========================================
       초기화
       ========================================= */
    function init() {
        // ⚠️ 상단바 종목 검색(layout.html)이 stockSearchInput·stockSearchResults 를 쓴다 — 같은 id 를 쓰면 이쪽이 상단바에 붙는다.
        initStockSearch('btStockSearchInput', 'btStockSearchResults',
            function (stock) {
                if (phases.length > 1) {
                    // 시점이 여럿이면 빈 줄로 — 칸마다 직접 비중을 넣는다(마지막 시점 칸에 커서)
                    if (tableRows().some(function (s) { return s.code === stock.code; })) { notify('이미 추가된 종목입니다.'); return; }
                    if (tableRows().length >= MAX_UNIVERSE) { notify('모든 시점을 합쳐 종목은 ' + MAX_UNIVERSE + '개까지입니다.'); return; }
                    extraRows.push({ code: stock.code, name: stock.name, market: stock.market });
                    renderPortfolio();
                    document.getElementById('btSearchPop').hidePopover();
                    var where = document.getElementById('phaseDlg').open ? '#phaseDlgBody' : '#selectedStocks';
                    var cellEl = document.querySelector(where + ' .wt-cell[data-code="' + stock.code + '"][data-col="' + (phases.length - 1) + '"]');
                    if (cellEl) { cellEl.scrollIntoView({ block: 'nearest', inline: 'nearest' }); cellEl.focus(); }
                    return;
                }
                if (portfolio.length >= MAX_STOCKS) { notify('최대 ' + MAX_STOCKS + '개까지 추가 가능합니다.'); return; }
                if (portfolio.some(function (s) { return s.code === stock.code; })) { notify('이미 추가된 종목입니다.'); return; }
                if (!allPhaseStocks().some(function (s) { return s.code === stock.code; }) && allPhaseStocks().length >= MAX_UNIVERSE) {
                    notify('모든 구간을 합쳐 종목은 ' + MAX_UNIVERSE + '개까지입니다.'); return;
                }
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
                var si = document.getElementById('btStockSearchInput');
                si.value = '';
                si.focus();
            },
            function (stock) {
                if (benchmarks.length >= MAX_BENCHMARKS) { notify('벤치마크는 최대 ' + MAX_BENCHMARKS + '개까지 추가 가능합니다.'); return; }
                if (benchmarks.some(function (b) { return b.code === stock.code; })) { notify('이미 추가된 벤치마크입니다.'); return; }
                benchmarks.push(stock);
                renderBenchmark();
                updateRunButtonState();
                updateDateRange();
                var si = document.getElementById('btStockSearchInput');
                si.value = '';
                si.focus();
            }
        );

        initStrategyTabs();

        // 종목 추가 — 작은 버튼 아래에 뜨는 검색창. 누른 버튼을 기억해 그 아래에 둔다(click 이 popovertarget 보다 먼저 온다).
        var searchPop = document.getElementById('btSearchPop'), searchAnchor = null;
        var searchInput = document.getElementById('btStockSearchInput');
        // 버튼 아래, 오른쪽 끝을 맞추되 화면 안으로(좁은 화면에서 왼쪽 밖으로 잘렸다)
        var setSearchPlace = function () {
            var r = searchAnchor.getBoundingClientRect(), w = Math.min(320, window.innerWidth - 16);
            searchPop.style.width = w + 'px';
            searchPop.style.top = Math.round(r.bottom + 6) + 'px';
            searchPop.style.left = Math.round(Math.max(8, Math.min(r.right - w, window.innerWidth - w - 8))) + 'px';
        };
        var placeSearch = function () {
            if (!searchAnchor || !searchPop.matches(':popover-open')) return;
            var r = searchAnchor.getBoundingClientRect();
            if (r.bottom < 0 || r.top > window.innerHeight) { searchPop.hidePopover(); return; }
            setSearchPlace();
        };
        if (searchPop) {
            document.querySelectorAll('[data-open-search]').forEach(function (b) {
                b.addEventListener('click', function () { searchAnchor = b; });
            });
            searchPop.addEventListener('beforetoggle', function (e) {
                if (e.newState !== 'open') { window.TopLayer.hide(document.getElementById('btStockSearchResults')); return; }
                if (searchAnchor) setSearchPlace();
            });
            searchPop.addEventListener('toggle', function (e) { if (e.newState === 'open') { searchInput.focus(); searchInput.select(); } });
            document.addEventListener('scroll', function (e) {
                if (!(e.target instanceof Node) || !searchPop.contains(e.target)) placeSearch();
            }, { capture: true, passive: true });
            window.addEventListener('resize', placeSearch);
        }

        // 비중 표 — 시점 추가·시점 창·크게 보기
        bindTable(document.getElementById('selectedStocks'));
        bindTable(document.getElementById('phaseDlgBody'));
        document.querySelectorAll('[data-phase-add]').forEach(function (b) { b.addEventListener('click', addPhase); });
        var phaseDel = document.getElementById('phaseDel');
        if (phaseDel) phaseDel.addEventListener('click', function () {
            document.getElementById('phasePop').hidePopover();
            removePhase(phases.indexOf(popPhase));
        });
        var phaseDate = document.getElementById('phaseDate');
        if (phaseDate) phaseDate.addEventListener('change', function () {
            if (!popPhase) return;
            popPhase.date = phaseDate.value;
            selPhase = phases.indexOf(popPhase);
            sortPhases();               // 날짜순으로 자리를 잡는다
            renderPortfolio();
            showPopError();
            var head = document.querySelector('#' + (document.getElementById('phaseDlg').open ? 'phaseDlgBody' : 'selectedStocks') +
                                              ' .wt-head[data-col="' + phases.indexOf(popPhase) + '"]');
            if (head) openPhasePop(popPhase, head);   // 창을 옮겨 간 열 아래로
            updateRunButtonState();
            scheduleAutoRecalc();
        });
        var phaseSpread = document.getElementById('phaseSpread');
        if (phaseSpread) phaseSpread.addEventListener('change', function () {
            if (!popPhase) return;
            popPhase.spread = parseInt(phaseSpread.value, 10) || 1;
            renderPortfolio();
            updateRunButtonState();
            scheduleAutoRecalc();
        });
        var dlg = document.getElementById('phaseDlg');
        if (dlg) {
            window.TopLayer.bindModal(dlg);
            // ⚠️ 모달이 열리면 창 밖은 눌리지 않는다(inert) — 검색창·시점 창을 창 안으로 옮겼다가 닫히면 제자리로
            var floating = ['btSearchPop', 'phasePop'].map(function (id) {
                var el = document.getElementById(id);
                return { el: el, home: el.parentNode };
            });
            document.getElementById('phaseExpand').addEventListener('click', function () {
                floating.forEach(function (f) { if (f.el.matches(':popover-open')) f.el.hidePopover(); dlg.appendChild(f.el); });
                window.TopLayer.openModal(dlg);
                renderPortfolio();
            });
            dlg.addEventListener('close', function () {
                floating.forEach(function (f) { if (f.el.matches(':popover-open')) f.el.hidePopover(); f.home.appendChild(f.el); });
                document.getElementById('phaseDlgBody').textContent = '';
                renderPortfolio();
            });
        }
        window.addEventListener('resize', refreshTable);
        ['startDate', 'endDate'].forEach(function (id) {
            var el = document.getElementById(id);
            if (el) el.addEventListener('change', refreshTable);
        });

        var dcaDeferSel = document.getElementById('dcaDeferIndicator');
        if (dcaDeferSel) dcaDeferSel.addEventListener('change', updateDcaDeferHint);

        var addBtn = document.getElementById('addSignalRule');
        if (addBtn) addBtn.addEventListener('click', function () { addSignalRule(); fieldError('btRulesError', ''); });

        // 칸 옆 검증 오류는 그 칸을 고치면 걷는다.
        ['startDate', 'endDate'].forEach(function (id) {
            var d = document.getElementById(id);
            if (d) d.addEventListener('change', function () { fieldError('btDateError', ''); });
        });
        var stocksBox = document.getElementById('selectedStocks');
        if (stocksBox) stocksBox.addEventListener('input', function () { fieldError('btStocksError', ''); });

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

        initPortfolioMenu();

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

        // 포트폴리오 공개/비공개 토글
        var publicBtn = document.getElementById('portfolioPublicToggle');
        if (publicBtn) {
            publicBtn.addEventListener('click', function () {
                // 지금 상태의 반대로 보낸다. 서버가 소유권을 다시 보므로 화면 상태를
                // 믿고 보내도 남의 것은 403 으로 막힌다.
                savePortfolioPublic(publicBtn.getAttribute('aria-pressed') !== 'true');
            });
        }

        // 포트폴리오 이름 인라인 편집
        var nameEditBtn = document.getElementById('portfolioNameEdit');
        var nameText = document.getElementById('portfolioNameText');
        var nameInput = document.getElementById('portfolioNameInput');
        // 연필이 기본, 이름 더블클릭이 보조. Enter·blur = 저장, Esc = 취소, 빈 이름은 저장하지 않는다.
        // ⚠️ 입력칸을 숨기면 blur 가 따라온다 — `editing` 으로 한 번만 끝낸다(예전에는 Esc 뒤 blur 가 저장했다).
        if (nameEditBtn && nameText && nameInput) {
            var editing = false;
            var startNameEdit = function () {
                if (nameEditBtn.hidden || editing) return;
                editing = true;
                nameInput.value = nameText.textContent;
                nameText.style.display = 'none';
                nameEditBtn.style.display = 'none';
                nameInput.style.display = '';
                nameInput.focus();
                nameInput.select();
            };
            var endNameEdit = function (save) {
                if (!editing) return;
                editing = false;
                var prevName = nameText.textContent;
                var newName = nameInput.value.trim();
                nameInput.style.display = 'none';
                nameText.style.display = '';
                nameEditBtn.style.display = '';
                if (save && newName && newName !== prevName) {
                    nameText.textContent = newName;
                    savePortfolioName(newName, prevName);
                }
            };
            nameEditBtn.addEventListener('click', startNameEdit);
            nameText.addEventListener('dblclick', startNameEdit);
            nameInput.addEventListener('blur', function () { endNameEdit(true); });
            nameInput.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') { e.preventDefault(); endNameEdit(true); }
                if (e.key === 'Escape') { e.preventDefault(); endNameEdit(false); }
            });
        }

        initConfigSticky();

        // URL 파라미터 ?portfolio=ID 확인 (localStorage보다 우선)
        var urlParams = new URLSearchParams(window.location.search);
        var portfolioParam = urlParams.get('portfolio');
        if (portfolioParam && parseInt(portfolioParam) > 0) {
            loadFromPortfolioId(parseInt(portfolioParam));
        } else if (localStorage.getItem(STORAGE_KEY) || localStorage.getItem('backtest_config_v1')) {
            // 저장된 설정이 있으면 자동 복원
            if (!localStorage.getItem(STORAGE_KEY) && localStorage.getItem('backtest_config_v1')) {
                localStorage.setItem(STORAGE_KEY, localStorage.getItem('backtest_config_v1'));
                localStorage.removeItem('backtest_config_v1');
            }
            loadConfigFromStorage();
        }
    }

    // AI 상담 시트(assistant.js)에 보내는 화면 맥락 — 지금 폼의 설정(저장 안 한 것 그대로, 검사 없이)
    window.assistantContext = function () { return { config: collectConfigRaw() }; };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
