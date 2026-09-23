/**
 * `/stocks` 홈의 순위 표 — 거래대금 · 상승률 · 하락률 × 한국 · 미국 · 코인.
 *
 * · 거래대금: `/api/v1/stocks/top` (⚠️ 최근 30일 합계 — 화면 머리 아래에 그렇게 적는다)
 * · 상승률·하락률: `quotes.js` 가 히트맵을 받을 때마다 보내는 `stock-dashboard-heatmap` 이벤트의
 *   행(구독 종목 전체)을 등락률로 정렬한다. API 를 한 번 더 부르지 않는다.
 *
 * 시장은 화면 하나의 상태다 — 이 표의 시장 버튼도 `quotes.js` 가 히트맵 탭과 함께 잡는다.
 * 여기서는 `stock-dashboard-market-change` 를 듣기만 한다.
 *
 * (종목 검색은 2026-09-23 상단바로 옮겼다 — `stock_search.js`)
 */
(function () {
    'use strict';

    var US_MARKETS = ['NYSE', 'NASDAQ', 'AMEX'];
    var LIMIT = 10;
    var NOTE = {
        amount: '최근 30일 거래대금 합계',
        up: '구독 종목 기준 · 직전 거래일 대비',
        down: '구독 종목 기준 · 직전 거래일 대비'
    };

    var listEl, noteEl, metricEl, kindEls;
    var kind = 'amount';
    var market = 'KR';
    var requestId = 0;
    // 마지막으로 받은 히트맵 — 상승률·하락률은 여기서 만든다. 시장이 다르면 아직 안 온 것이다.
    var heat = { market: null, rows: [], failed: false };

    function n(v, digits) {
        return Number(v || 0).toLocaleString('en-US', {
            minimumFractionDigits: digits,
            maximumFractionDigits: digits
        });
    }

    function pctText(value) {
        if (value === null || value === undefined) return '-';
        return (value > 0 ? '+' : '') + n(value, 2) + '%';
    }

    function pctClass(value) {
        if (value === null || value === undefined) return 'q-flat';
        if (value > 0) return 'q-up';
        if (value < 0) return 'q-down';
        return 'q-flat';
    }

    function isUS(item) {
        return US_MARKETS.indexOf(item.market) >= 0;
    }

    function isCoin(item) {
        return item.type === 'COIN' || item.market === 'Bithumb' || item.market === 'COIN' || market === 'COIN';
    }

    function price(value, item) {
        if (value === null || value === undefined) return '-';
        if (isUS(item)) return '$' + n(value, 2);
        // 코인은 1원 아래 값이 있다 — 정수로 자르면 0원이 된다.
        return (value < 100 ? n(value, value < 1 ? 4 : 2) : n(value, 0)) + '원';
    }

    /** 거래대금·시가총액. 원화는 조·억, 달러는 B·M. */
    function money(value, item) {
        if (!value) return '-';
        if (isUS(item)) {
            if (value >= 1e12) return '$' + n(value / 1e12, 2) + 'T';
            if (value >= 1e9) return '$' + n(value / 1e9, 1) + 'B';
            if (value >= 1e6) return '$' + n(value / 1e6, 1) + 'M';
            return '$' + n(value, 0);
        }
        if (value >= 1e16) return n(value / 1e16, 1) + '경';
        if (value >= 1e12) return n(value / 1e12, 1) + '조';
        if (value >= 1e8) return n(value / 1e8, 0) + '억';
        if (value >= 1e4) return n(value / 1e4, 0) + '만';
        return n(value, 0);
    }

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined && text !== null) node.textContent = text;
        return node;
    }

    function detailUrl(item) {
        var query = 'code=' + encodeURIComponent(item.code);
        if (isCoin(item)) query += '&market=COIN';
        return '/stocks/view?' + query;
    }

    function message(text) {
        listEl.classList.remove('is-stale');
        listEl.removeAttribute('aria-busy');
        listEl.innerHTML = '';
        listEl.appendChild(el('li', 'sh-rank__empty', text));
    }

    /**
     * 행: `li > a.sh-rank__row > (순위, 이름, [코드·기준값], 현재가, 등락률)`
     * 넓은 화면에서는 `.sh-rank__sub` 가 `display: contents` 라 코드와 기준값이 제 칸으로 가고,
     * 좁은 화면에서는 이름 밑에 "코드 · 기준값" 한 줄로 붙는다(`stock_home.css`).
     */
    function render(rows) {
        listEl.classList.remove('is-stale');
        listEl.removeAttribute('aria-busy');
        listEl.innerHTML = '';
        if (!rows.length) {
            listEl.appendChild(el('li', 'sh-rank__empty', '데이터가 없습니다.'));
            return;
        }
        rows.forEach(function (item, i) {
            var li = el('li', 'sh-rank__item');
            var a = el('a', 'sh-rank__row');
            a.href = detailUrl(item);

            a.appendChild(el('span', 'sh-rank__n', String(i + 1)));
            var nm = el('span', 'sh-rank__nm', item.name_kr || item.code);
            nm.title = item.name_kr || item.code;
            a.appendChild(nm);

            var sub = el('span', 'sh-rank__sub');
            sub.appendChild(el('span', 'sh-rank__cd', item.code));
            sub.appendChild(el('span', 'sh-rank__mt',
                               money(kind === 'amount' ? item.trading_amount : item.market_cap, item)));
            a.appendChild(sub);

            a.appendChild(el('span', 'sh-rank__px', price(item.price, item)));
            a.appendChild(el('span', 'sh-rank__ch ' + pctClass(item.change_pct), pctText(item.change_pct)));
            li.appendChild(a);
            listEl.appendChild(li);
        });
    }

    /** 새 목록이 올 때까지 옛 목록을 흐리게 남긴다 — 비우면 표 높이가 출렁인다. */
    function markStale() {
        if (listEl.querySelector('.sh-rank__item')) {
            listEl.classList.add('is-stale');
            listEl.setAttribute('aria-busy', 'true');
        } else {
            message('불러오는 중…');
        }
    }

    function fromHeatmap() {
        if (heat.market !== market) { markStale(); return; }   // 히트맵이 오면 다시 부른다
        if (heat.failed) { message('불러오지 못했습니다.'); return; }
        var rows = heat.rows.filter(function (r) {
            return r.change_pct !== null && r.change_pct !== undefined &&
                   (kind === 'up' ? r.change_pct > 0 : r.change_pct < 0);
        });
        rows.sort(function (a, b) {
            return kind === 'up' ? b.change_pct - a.change_pct : a.change_pct - b.change_pct;
        });
        render(rows.slice(0, LIMIT));
    }

    function fromTop(quiet) {
        var mine = ++requestId;
        var asked = market;
        if (!quiet) markStale();
        fetch('/api/v1/stocks/top?limit=' + LIMIT + '&market=' + encodeURIComponent(asked))
            .then(function (response) {
                if (!response.ok) throw new Error('HTTP ' + response.status);
                return response.json();
            })
            .then(function (rows) {
                if (mine === requestId && kind === 'amount') render(rows || []);
            })
            .catch(function (error) {
                if (mine !== requestId || kind !== 'amount') return;
                // 흐리게 남겨 둔 목록은 **다른 시장의 것**일 수 있다 — 비우고 자리 설명을 남긴다.
                // 무슨 일이 있었는지는 토스트로(프로젝트 디자인 규칙).
                message('불러오지 못했습니다.');
                if (window.toast) {
                    window.toast('거래대금 순위를 불러오지 못했습니다.', 'error',
                                 { action: { label: '다시 시도', onClick: function () { show(); } } });
                }
                if (window.console) console.error('거래대금 순위 로드 실패', error);
            });
    }

    function show(quiet) {
        noteEl.textContent = NOTE[kind];
        metricEl.textContent = kind === 'amount' ? '거래대금' : '시가총액';
        if (kind === 'amount') fromTop(quiet);
        else { requestId += 1; fromHeatmap(); }
    }

    function setKind(next) {
        if (!NOTE[next] || next === kind) return;
        kind = next;
        kindEls.forEach(function (b) {
            b.setAttribute('aria-pressed', b.dataset.rankKind === kind ? 'true' : 'false');
        });
        show();
    }

    function init() {
        var rootEl = document.getElementById('quotesRoot');
        listEl = document.getElementById('rankList');
        noteEl = document.getElementById('rankNote');
        metricEl = document.getElementById('rankMetricLabel');
        if (!rootEl || !listEl || !noteEl || !metricEl) return;
        kindEls = Array.prototype.slice.call(document.querySelectorAll('[data-rank-kind]'));

        var m = (rootEl.dataset.market || '').toUpperCase();
        market = ['KR', 'US', 'COIN'].indexOf(m) >= 0 ? m : 'KR';

        kindEls.forEach(function (b) {
            b.addEventListener('click', function () { setKind(b.dataset.rankKind); });
        });
        document.addEventListener('stock-dashboard-market-change', function (event) {
            var next = event.detail && event.detail.market;
            if (!next || next === market) return;
            market = next;
            show();
        });
        document.addEventListener('stock-dashboard-heatmap', function (event) {
            var d = event.detail || {};
            heat = { market: d.market, rows: d.rows || [], failed: !!d.failed };
            if (kind !== 'amount') fromHeatmap();
        });
        // 앱으로 돌아왔을 때 quotes.js 가 보낸다(상승·하락은 히트맵 이벤트로 따라온다).
        document.addEventListener('stock-dashboard-refresh', function () {
            if (kind === 'amount') fromTop(true);
        });

        show();
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
