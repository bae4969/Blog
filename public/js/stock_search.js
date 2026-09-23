/**
 * 상단바 종목 검색 — 모든 화면에서 쓴다(`layout.html` 이 전역으로 싣는다).
 *
 * 2026-09-23 주식이 메인이 되며 `/stocks` 오른쪽 열에 있던 검색을 상단바로 올렸다
 * (토스증권 PC 처럼 어느 화면에서든 바로 종목을 찾는다). 검색 로직은 `stocks_dashboard.js`
 * 에 있던 것을 그대로 옮겼다 — 한국·미국 8개 + 코인 4개를 나란히 받아 합친다.
 *
 * 64rem 보다 좁으면 입력칸이 접혀 있고 돋보기 버튼이 연다. 열리면 상단바가
 * `is-searching` 이 되어 입력칸이 한 줄을 다 쓴다(CSS 가 나머지를 숨긴다).
 */
(function () {
    'use strict';

    var US_MARKETS = ['NYSE', 'NASDAQ', 'AMEX'];
    var barEl, formEl, inputEl, resultsEl;
    var requestId = 0;
    var timer = null;
    var dismissed = false;

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

    /** 종목 화면의 "목록으로" 가 이 시장 탭으로 돌아오게 한다(`stocks_show.html`). */
    function rememberMarket(group) {
        try {
            sessionStorage.setItem('stock_market_preference', group);
        } catch (e) { /* 사생활 보호 모드 등 — 무시한다 */ }
    }

    function setOpen(open) {
        resultsEl.hidden = !open;
        inputEl.setAttribute('aria-expanded', open ? 'true' : 'false');
    }

    function message(text) {
        resultsEl.innerHTML = '';
        resultsEl.appendChild(el('div', 'c-stocksearch__msg', text));
        setOpen(true);
    }

    var MARKET_LABEL = { KR: '한국', US: '미국', COIN: '코인' };

    function render(rows) {
        resultsEl.innerHTML = '';
        if (!rows.length) {
            message('검색 결과가 없습니다.');
            if (dismissed) setOpen(false);
            return;
        }

        rows.slice(0, 12).forEach(function (item) {
            var group = marketGroup(item);
            var link = el('a', 'c-stocksearch__item');
            link.href = detailUrl(item);
            link.setAttribute('role', 'option');
            link.addEventListener('click', function () { rememberMarket(group); });

            var info = el('span', 'c-stocksearch__info');
            info.appendChild(el('span', 'c-stocksearch__name', item.name_kr || item.code));
            var sub = el('span', 'c-stocksearch__sub');
            sub.appendChild(el('span', null, item.code));
            sub.appendChild(el('span', 'c-stocksearch__mkt', MARKET_LABEL[group]));
            info.appendChild(sub);
            link.appendChild(info);

            // 가격은 중립, 방향은 등락률 한 곳에서만 색으로 말한다(순위 목록과 같은 규칙).
            var quote = el('span', 'c-stocksearch__quote');
            quote.appendChild(el('span', 'c-stocksearch__px', price(item.price, item.market)));
            quote.appendChild(el('span', 'c-stocksearch__ch ' + pctClass(item.change_pct), pctText(item.change_pct)));
            link.appendChild(quote);
            resultsEl.appendChild(link);
        });
        setOpen(!dismissed);
    }

    function fetchJson(url) {
        return fetch(url, { headers: { 'Accept': 'application/json' } })
            .then(function (response) {
                if (!response.ok) throw new Error('HTTP ' + response.status);
                return response.json();
            });
    }

    function search(query) {
        var mine = ++requestId;
        var encoded = encodeURIComponent(query);
        Promise.all([
            fetchJson('/api/v1/stocks?size=8&page=1&q=' + encoded),
            fetchJson('/api/v1/stocks?size=4&page=1&market=COIN&q=' + encoded)
        ]).then(function (responses) {
            if (mine !== requestId) return;
            render((responses[0].items || []).concat(responses[1].items || []));
        }).catch(function (error) {
            if (mine !== requestId) return;
            message('검색 결과를 불러오지 못했습니다.');
            if (dismissed) setOpen(false);
            if (window.console) console.error('종목 검색 실패', error);
        });
    }

    function schedule() {
        clearTimeout(timer);
        var query = inputEl.value.trim().slice(0, 50);
        if (!query) {
            requestId += 1;
            setOpen(false);
            resultsEl.innerHTML = '';
            return;
        }
        dismissed = false;
        message('검색 중…');
        timer = setTimeout(function () { search(query); }, 250);
    }

    function close() {
        clearTimeout(timer);
        requestId += 1;
        dismissed = true;
        setOpen(false);
    }

    /** 좁은 화면의 펼침 상태. 넓은 화면에서는 CSS 가 이 클래스를 무시한다. */
    function expand(on) {
        barEl.classList.toggle('is-searching', on);
        if (on) {
            inputEl.focus();
        } else {
            close();
            inputEl.value = '';
            resultsEl.innerHTML = '';
        }
    }

    function init() {
        formEl = document.getElementById('stockSearchForm');
        inputEl = document.getElementById('stockSearchInput');
        resultsEl = document.getElementById('stockSearchResults');
        barEl = formEl && formEl.closest('.c-topbar');
        if (!formEl || !inputEl || !resultsEl || !barEl) return;

        inputEl.addEventListener('input', schedule);
        inputEl.addEventListener('focus', function () {
            dismissed = false;
            if (inputEl.value.trim() && resultsEl.childElementCount) setOpen(true);
        });
        inputEl.addEventListener('keydown', function (event) {
            if (event.key !== 'Escape') return;
            if (barEl.classList.contains('is-searching')) expand(false);
            else { close(); inputEl.blur(); }
        });
        formEl.addEventListener('submit', function (event) {
            event.preventDefault();
            var first = resultsEl.querySelector('a.c-stocksearch__item');
            if (first && !resultsEl.hidden) first.click();
            else schedule();
        });
        barEl.querySelectorAll('[data-search-open]').forEach(function (b) {
            b.addEventListener('click', function () { expand(true); });
        });
        barEl.querySelectorAll('[data-search-close]').forEach(function (b) {
            b.addEventListener('click', function () { expand(false); });
        });
        document.addEventListener('mousedown', function (event) {
            if (!formEl.contains(event.target)) {
                dismissed = true;
                setOpen(false);
            }
        });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
