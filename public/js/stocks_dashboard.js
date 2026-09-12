/** `/stocks` 오른쪽 열 — 통합 종목 검색과 거래대금 TOP10. */
(function () {
    'use strict';

    var US_MARKETS = ['NYSE', 'NASDAQ', 'AMEX'];
    var topEl, formEl, inputEl, resultsEl, rootEl;
    var topRequestId = 0;
    var searchRequestId = 0;
    var searchTimer = null;
    var searchDismissed = false;

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

    function amount(value) {
        if (!value) return '0';
        if (value >= 1e20) return n(value / 1e20, 1) + '해';
        if (value >= 1e16) return n(value / 1e16, 1) + '경';
        if (value >= 1e12) return n(value / 1e12, 1) + '조';
        if (value >= 1e8) return n(value / 1e8, 0) + '억';
        if (value >= 1e4) return n(value / 1e4, 0) + '만';
        return n(value, 0);
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

    function rememberMarket(group) {
        try {
            if (group === 'KR' || group === 'US' || group === 'COIN') {
                sessionStorage.setItem('stock_market_preference', group);
            } else {
                sessionStorage.removeItem('stock_market_preference');
            }
        } catch (e) { /* 사생활 보호 모드 등 — 무시한다 */ }
    }

    function renderTop(rows) {
        topEl.innerHTML = '';
        if (!rows.length) {
            topEl.appendChild(el('div', 'top10-empty', '데이터가 없습니다.'));
            return;
        }

        rows.forEach(function (item, index) {
            var link = el('a', 'top10-item');
            link.href = detailUrl(item);
            link.appendChild(el('div', 'top10-rank', String(index + 1)));

            var info = el('div', 'top10-info');
            info.appendChild(el('div', 'top10-name', item.name_kr || item.code));
            info.appendChild(el('div', 'top10-code', item.code));
            link.appendChild(info);

            var value = el('div', 'top10-value');
            var cls = pctClass(item.change_pct);
            value.appendChild(el('div', 'top10-primary ' + cls, price(item.price, item.market)));
            var secondary = el('div', 'top10-secondary');
            secondary.appendChild(el('span', 'top10-change ' + cls, pctText(item.change_pct)));
            secondary.appendChild(el('span', 'top10-amt', amount(item.trading_amount)));
            value.appendChild(secondary);
            link.appendChild(value);
            topEl.appendChild(link);
        });
    }

    function loadTop(market) {
        if (!topEl || ['KR', 'US', 'COIN'].indexOf(market) < 0) return;
        var mine = ++topRequestId;
        topEl.innerHTML = '<div class="top10-empty">불러오는 중…</div>';
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
                topEl.innerHTML = '<div class="top10-empty">불러오지 못했습니다.</div>';
                if (window.console) console.error('거래대금 TOP10 로드 실패', error);
            });
    }

    function setSearchOpen(open) {
        resultsEl.hidden = !open;
        inputEl.setAttribute('aria-expanded', open ? 'true' : 'false');
    }

    function searchMessage(message) {
        resultsEl.innerHTML = '';
        resultsEl.appendChild(el('div', 'stock-floating-search-message', message));
        setSearchOpen(true);
    }

    function renderSearch(rows) {
        resultsEl.innerHTML = '';
        if (!rows.length) {
            searchMessage('검색 결과가 없습니다.');
            if (searchDismissed) setSearchOpen(false);
            return;
        }

        rows.slice(0, 12).forEach(function (item) {
            var group = marketGroup(item);
            var link = el('a', 'stock-floating-result');
            link.href = detailUrl(item);
            link.setAttribute('role', 'option');
            link.addEventListener('click', function () { rememberMarket(group); });

            var info = el('span', 'stock-floating-result-info');
            info.appendChild(el('span', 'stock-floating-result-name', item.name_kr || item.code));
            info.appendChild(el('span', 'stock-floating-result-code', item.code));
            link.appendChild(info);
            link.appendChild(el('span', 'stock-floating-result-market badge-' + group.toLowerCase(), group));
            link.appendChild(el('span', 'stock-floating-result-price ' + pctClass(item.change_pct),
                                price(item.price, item.market)));
            resultsEl.appendChild(link);
        });
        setSearchOpen(!searchDismissed);
    }

    function fetchJson(url) {
        return fetch(url, { headers: { 'Accept': 'application/json' } })
            .then(function (response) {
                if (!response.ok) throw new Error('HTTP ' + response.status);
                return response.json();
            });
    }

    function search(query) {
        var mine = ++searchRequestId;
        var encoded = encodeURIComponent(query);
        searchMessage('검색 중…');
        Promise.all([
            fetchJson('/api/v1/stocks?size=8&page=1&q=' + encoded),
            fetchJson('/api/v1/stocks?size=4&page=1&market=COIN&q=' + encoded)
        ]).then(function (responses) {
            if (mine !== searchRequestId) return;
            renderSearch((responses[0].items || []).concat(responses[1].items || []));
        }).catch(function (error) {
            if (mine !== searchRequestId) return;
            searchMessage('검색 결과를 불러오지 못했습니다.');
            if (searchDismissed) setSearchOpen(false);
            if (window.console) console.error('종목 검색 실패', error);
        });
    }

    function scheduleSearch() {
        clearTimeout(searchTimer);
        var query = inputEl.value.trim().slice(0, 50);
        if (!query) {
            searchRequestId += 1;
            setSearchOpen(false);
            resultsEl.innerHTML = '';
            return;
        }
        searchDismissed = false;
        searchMessage('검색 중…');
        searchTimer = setTimeout(function () { search(query); }, 250);
    }

    function init() {
        rootEl = document.getElementById('quotesRoot');
        topEl = document.getElementById('stockTop10');
        formEl = document.getElementById('stockSearchForm');
        inputEl = document.getElementById('stockSearchInput');
        resultsEl = document.getElementById('stockSearchResults');
        if (!rootEl || !topEl || !formEl || !inputEl || !resultsEl) return;

        var market = (rootEl.dataset.market || '').toUpperCase();
        loadTop(['KR', 'US', 'COIN'].indexOf(market) >= 0 ? market : 'KR');

        document.addEventListener('stock-dashboard-market-change', function (event) {
            loadTop(event.detail && event.detail.market);
        });
        inputEl.addEventListener('input', scheduleSearch);
        inputEl.addEventListener('focus', function () {
            searchDismissed = false;
            if (inputEl.value.trim() && resultsEl.childElementCount) setSearchOpen(true);
        });
        inputEl.addEventListener('keydown', function (event) {
            if (event.key === 'Escape') {
                clearTimeout(searchTimer);
                searchRequestId += 1;
                searchDismissed = true;
                setSearchOpen(false);
                inputEl.blur();
            }
        });
        formEl.addEventListener('submit', function (event) {
            event.preventDefault();
            var first = resultsEl.querySelector('a.stock-floating-result');
            if (first && !resultsEl.hidden) first.click();
            else scheduleSearch();
        });
        document.addEventListener('mousedown', function (event) {
            if (!formEl.contains(event.target)) {
                searchDismissed = true;
                setSearchOpen(false);
            }
        });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
