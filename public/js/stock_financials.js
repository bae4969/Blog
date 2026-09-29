/**
 * 종목 상세의 실적 카드 — `/api/v1/stocks/{code}/financials` 의 분기(3개월) 값을 막대로 그린다.
 *
 * Chart.js 는 `stocks.js` 가 불러온다(`waitForChartReady`·`chartColors` 도 그쪽 전역).
 * ⚠️ `stocks.js` 가 십자선·캔들 플러그인을 **전역 등록**한다 — 이 차트에서는 끈다. 켜 두면 막대 위에
 *    가격 라벨이 붙은 십자선이 그려진다.
 * ⚠️ 빨강·파랑은 등락 전용이다 — 막대는 중립색, 적자 분기만 흐린 색으로 아래로 내린다.
 */
(function () {
    'use strict';

    var card = document.querySelector('[data-fin-code]');
    if (!card) return;

    var plot = card.querySelector('.sd-fin__plot');
    var chart = null;
    var data = null;
    var key = 'revenue';

    /** 원 → "74.57조" · "4,676억". */
    function won(v) {
        var a = Math.abs(v), sign = v < 0 ? '-' : '';
        if (a === 0) return '0';
        if (a >= 1e12) return sign + (a / 1e12).toLocaleString('ko-KR', { maximumFractionDigits: 2 }) + '조';
        if (a >= 1e8) return sign + Math.round(a / 1e8).toLocaleString('ko-KR') + '억';
        return sign + Math.round(a / 1e4).toLocaleString('ko-KR') + '만';
    }

    function message(text) {
        if (chart) { chart.destroy(); chart = null; }
        var p = document.createElement('p');
        p.className = 'sd-exec__empty';
        p.textContent = text;
        plot.replaceChildren(p);
    }

    function draw() {
        var qs = data.quarters;
        var values = qs.map(function (q) { return q[key]; });
        var muted = chartColors.textMuted, main = chartColors.primary;
        var cfg = {
            labels: qs.map(function (q) { return String(q.year).slice(2) + '.' + q.quarter + 'Q'; }),
            datasets: [{
                data: values,
                backgroundColor: values.map(function (v) { return v < 0 ? muted : main; }),
                borderRadius: 3,
                maxBarThickness: 28
            }]
        };
        if (chart) {
            chart.data = cfg;
            chart.update();
            return;
        }
        chart = new Chart(document.getElementById('finChart'), {
            type: 'bar',
            data: cfg,
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: { duration: 200 },
                plugins: {
                    legend: { display: false },
                    crosshairPlugin: false,
                    candleDrawPlugin: false,
                    tooltip: {
                        displayColors: false,
                        backgroundColor: chartColors.tooltipBg,
                        callbacks: {
                            title: function (items) {
                                var q = data.quarters[items[0].dataIndex];
                                return q.year + '년 ' + q.quarter + '분기';
                            },
                            label: function (ctx) {
                                var q = data.quarters[ctx.dataIndex];
                                var v = q[key], yoy = q[key + '_yoy'];
                                var lines = [v == null ? '-' : won(v)];
                                if (yoy != null) lines.push('전년 대비 ' + (yoy >= 0 ? '+' : '') + yoy.toFixed(1) + '%');
                                return lines;
                            }
                        }
                    }
                },
                scales: {
                    x: { grid: { display: false }, ticks: { color: chartColors.textMuted, font: { size: 11 } } },
                    y: {
                        grid: { color: chartColors.grid },
                        border: { display: false },
                        ticks: { color: chartColors.textMuted, font: { size: 11 }, maxTicksLimit: 5,
                                 callback: function (v) { return won(v); } }
                    }
                }
            }
        });
    }

    card.querySelectorAll('[data-fin-key]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            if (!data || btn.getAttribute('aria-pressed') === 'true') return;
            card.querySelectorAll('[data-fin-key]').forEach(function (b) {
                b.setAttribute('aria-pressed', b === btn ? 'true' : 'false');
            });
            key = btn.getAttribute('data-fin-key');
            draw();
        });
    });

    Promise.all([
        fetch('/api/v1/stocks/' + encodeURIComponent(card.getAttribute('data-fin-code')) + '/financials')
            .then(function (r) {
                if (r.status === 404) return null;
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            }),
        waitForChartReady()
    ]).then(function (res) {
        data = res[0];
        if (!data || !data.quarters.length) return message('실적 데이터가 없습니다.');
        if (typeof Chart === 'undefined') return message('차트를 불러올 수 없습니다.');
        document.getElementById('finSub').textContent = (data.fs_div === 'CFS' ? '연결' : '개별') + ' · 분기';
        // 금융사는 매출 계정이 없다 — 칩을 숨기고 영업이익부터 보인다.
        if (data.quarters.every(function (q) { return q.revenue == null; })) {
            key = 'operating_income';
            card.querySelectorAll('[data-fin-key]').forEach(function (b) {
                b.setAttribute('aria-pressed', b.dataset.finKey === key ? 'true' : 'false');
                if (b.dataset.finKey === 'revenue') b.hidden = true;
            });
        }
        draw();
    }).catch(function (e) {
        console.error('실적 로드 실패:', e);
        message('실적을 불러올 수 없습니다.');
    });
})();
