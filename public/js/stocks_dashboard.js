/** `/stocks` 오른쪽 열 — 거래대금 TOP10. (종목 검색은 2026-09-23 상단바로 옮겼다 — `stock_search.js`) */
(function () {
    'use strict';

    var US_MARKETS = ['NYSE', 'NASDAQ', 'AMEX'];
    var topEl, rootEl;
    var topRequestId = 0;
    var topMarket = null;

    function n(v, digits) {
        return Number(v || 0).toLocaleString('en-US', {
            minimumFractionDigits: digits,
            maximumFractionDigits: digits
        });
    }

    function pctText(value) {
        if (value === null || value === undefined) return '-';
        return (value >= 0 ? '+' : '') + n(value, 2) + '%';
    }

    function pctClass(value) {
        if (value === null || value === undefined) return 'q-flat';
        if (value > 0) return 'q-up';
        if (value < 0) return 'q-down';
        return 'q-flat';
    }

    /** 거래대금 → [숫자, 단위]. 단위를 떼어 두는 것은 숫자를 먼저 읽히고 단위(`조`)를 작게
     *  흐리게 붙이기 위해서다(순위 목록의 1행 오른쪽 값). */
    function amountParts(value) {
        if (!value) return ['0', ''];
        if (value >= 1e20) return [n(value / 1e20, 1), '해'];
        if (value >= 1e16) return [n(value / 1e16, 1), '경'];
        if (value >= 1e12) return [n(value / 1e12, 1), '조'];
        if (value >= 1e8) return [n(value / 1e8, 0), '억'];
        if (value >= 1e4) return [n(value / 1e4, 0), '만'];
        return [n(value, 0), ''];
    }

    function isUS(market) {
        return US_MARKETS.indexOf(market) >= 0;
    }

    function price(value, market) {
        if (value === null || value === undefined) return '-';
        return isUS(market) ? '$' + n(value, 2) : n(value, 0) + '원';
    }

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined && text !== null) node.textContent = text;
        return node;
    }

    function marketGroup(item) {
        if (item.type === 'COIN' || item.market === 'Bithumb') return 'COIN';
        return isUS(item.market) ? 'US' : 'KR';
    }

    function detailUrl(item) {
        var query = 'code=' + encodeURIComponent(item.code);
        if (marketGroup(item) === 'COIN') query += '&market=COIN';
        return '/stocks/view?' + query;
    }

    /**
     * 거래대금 순위를 그린다. 형태·근거는 `stocks_index.html` 의 순위 목록 주석 참조.
     *
     * 행: `li.top10-item > a.top10-link > (순위, 몸통)`
     *   1행 — 이름 · 거래대금(순위 기준, 가장 진하게)
     *   막대 — 1위 대비 비율(`--pct`). 상한이 없는 값이라 트랙은 두지 않는다.
     *   2행 — 코드 · 가격 · 등락
     * ⚠️ 가격은 중립 색이다. 185만원과 2.6만원은 행끼리 비교할 의미가 없는 값이라 보조로
     *    내리고, 방향은 등락률 한 곳에서만 색으로 말한다.
     */
    function renderTop(rows) {
        topEl.classList.remove('is-stale');
        topEl.removeAttribute('aria-busy');
        topEl.innerHTML = '';
        if (!rows.length) {
            topEl.appendChild(el('li', 'top10-empty', '데이터가 없습니다.'));
            return;
        }

        // 정렬돼 오지만 믿지 않는다 — 막대의 기준은 목록 안 최댓값이다.
        var max = rows.reduce(function (m, r) { return Math.max(m, r.trading_amount || 0); }, 0) || 1;

        rows.forEach(function (item, index) {
            var li = el('li', 'top10-item');
            li.style.setProperty('--pct', ((item.trading_amount || 0) / max * 100).toFixed(1));

            var link = el('a', 'top10-link');
            link.href = detailUrl(item);
            link.appendChild(el('span', 'top10-n', String(index + 1)));

            var body = el('span', 'top10-body');

            var l1 = el('span', 'top10-l1');
            var nm = el('span', 'top10-nm', item.name_kr || item.code);
            nm.title = item.name_kr || item.code;   // 좁은 칸에서 잘리면 마우스로 전체 이름을 본다
            l1.appendChild(nm);
            var parts = amountParts(item.trading_amount);
            var val = el('span', 'top10-val', parts[0]);
            if (parts[1]) val.appendChild(el('small', null, parts[1]));
            l1.appendChild(val);
            body.appendChild(l1);

            var bar = el('span', 'top10-bar');
            bar.setAttribute('aria-hidden', 'true');   // 값은 글자로 이미 있다
            bar.appendChild(el('i'));
            body.appendChild(bar);

            var l2 = el('span', 'top10-l2');
            l2.appendChild(el('span', 'top10-cd', item.code));
            l2.appendChild(el('span', 'top10-px', price(item.price, item.market)));
            l2.appendChild(el('span', 'top10-ch ' + pctClass(item.change_pct), pctText(item.change_pct)));
            body.appendChild(l2);

            link.appendChild(body);
            li.appendChild(link);
            topEl.appendChild(li);
        });
    }

    /** 범위 칩 — 목록이 어느 시장을 따르는지. 시장 탭의 이름을 그대로 쓴다. */
    function setTopScope(market) {
        var scope = document.getElementById('stockTop10Scope');
        var tab = document.querySelector('.market-stat-item-h[data-group="' + market + '"] .market-name span');
        if (scope && tab) scope.textContent = tab.textContent;
    }

    /**
     * `quiet` 이면 아무 표시 없이 바꿔 끼운다 — 앱으로 돌아와 다시 받을 때 깜빡이지 않게.
     *
     * ⚠️ 시장을 바꿀 때 목록을 "불러오는 중…" 한 줄로 비우지 않는다. 그러면 사이드바가
     *    10행 → 1행 → 10행으로 **접혔다 펴지며 튄다.** 이전 목록을 흐리게 둔 채 받아서
     *    바꿔 끼운다. 비어 있을 때(첫 로드)만 안내 문구를 쓴다.
     */
    function loadTop(market, quiet) {
        if (!topEl || ['KR', 'US', 'COIN'].indexOf(market) < 0) return;
        topMarket = market;
        var mine = ++topRequestId;
        setTopScope(market);
        if (!quiet) {
            if (topEl.querySelector('.top10-item')) {
                topEl.classList.add('is-stale');
                topEl.setAttribute('aria-busy', 'true');
            } else {
                topEl.innerHTML = '<li class="top10-empty">불러오는 중…</li>';
            }
        }
        fetch('/api/v1/stocks/top?limit=10&market=' + market)
            .then(function (response) {
                if (!response.ok) throw new Error('HTTP ' + response.status);
                return response.json();
            })
            .then(function (rows) {
                if (mine === topRequestId) renderTop(rows || []);
            })
            .catch(function (error) {
                if (mine !== topRequestId) return;
                // 흐리게 남겨 둔 목록은 **다른 시장의 것**이라 그대로 두면 안 된다 — 비우고
                // 자리 설명을 남긴다. 무슨 일이 있었는지는 토스트로(프로젝트 디자인 규칙).
                topEl.classList.remove('is-stale');
                topEl.removeAttribute('aria-busy');
                topEl.innerHTML = '<li class="top10-empty">불러오지 못했습니다.</li>';
                if (window.toast) {
                    window.toast('거래대금 순위를 불러오지 못했습니다.', 'error',
                                 { action: { label: '다시 시도', onClick: function () { loadTop(market); } } });
                }
                if (window.console) console.error('거래대금 TOP10 로드 실패', error);
            });
    }

    function init() {
        rootEl = document.getElementById('quotesRoot');
        topEl = document.getElementById('stockTop10');
        if (!rootEl || !topEl) return;

        var market = (rootEl.dataset.market || '').toUpperCase();
        loadTop(['KR', 'US', 'COIN'].indexOf(market) >= 0 ? market : 'KR');

        document.addEventListener('stock-dashboard-market-change', function (event) {
            loadTop(event.detail && event.detail.market);
        });
        // 앱으로 돌아왔을 때 quotes.js 가 보낸다.
        document.addEventListener('stock-dashboard-refresh', function () {
            loadTop(topMarket, true);
        });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
