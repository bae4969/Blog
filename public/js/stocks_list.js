/**
 * 종목 목록 — 서버가 아니라 `/api/v1/stocks*` 를 읽어 그린다.
 *
 * 블로그 목록(`blog_list.js`)에 이은 SPA 2단계다. 껍데기(시장 통계 바·검색폼·포트폴리오
 * TOP10)는 서버가 그대로 그리고, 여기서 맡는 것은 **표·페이저·거래대금 TOP10** 이다.
 *
 * ⚠️ **숫자 포맷이 이 화면의 함정이다.** 템플릿에 `won`·`qty`·`amt` 세 매크로가 있는데
 *    같은 단위라도 소수 자릿수가 서로 다르다(억을 won 은 정수로, qty 는 소수 1자리로).
 *    눈에 잘 안 띄어서, 그대로 옮기지 않으면 숫자가 조용히 달라진다.
 *
 * ⚠️ 상세 URL 의 코인 판정이 **목록과 TOP10 이 서로 다르다.** 목록은 `type === 'COIN'`,
 *    TOP10 은 `market === 'Bithumb'` 이다 — 두 쿼리가 시장 이름을 다르게 돌려준다.
 *
 * ⚠️ 가격은 API 가 이미 candle 최신 종가를 씌워 준다. 여기서 다시 손대지 않는다.
 */
(function () {
    'use strict';

    var PER_PAGE = 50;                       // 서버 `_PER_PAGE` 와 같아야 쪽 번호가 맞는다
    var MAX_SEARCH = 50;                     // API `max_length=50`. 넘기면 422 다
    var US_MARKETS = ['NYSE', 'NASDAQ', 'AMEX'];
    var GROUPS = ['KR', 'US', 'COIN'];

    var rootEl, tbodyEl, pagerEl, topEl, qtyHeadEl, formEl, tabEls;
    var defaultMarket = 'KR';

    function readState() {
        var p = new URLSearchParams(location.search);
        var m = (p.get('market') || '').toUpperCase();
        return {
            // ⚠️ 주소에 market 이 없으면 **서버가 정한 기본 탭**을 쓴다. 기본값은 시간대에
            //    따라 KR/US 로 갈리므로(`_default_market`) JS 가 제 맘대로 정하면 안 된다.
            market: GROUPS.indexOf(m) >= 0 ? m : defaultMarket,
            page: Math.max(1, parseInt(p.get('page') || '1', 10) || 1),
            search: (p.get('search') || '').trim().slice(0, MAX_SEARCH)
        };
    }

    /** 상태 → 주소. 서버 `q()` 매크로와 같은 규칙이다(market 은 항상 붙인다). */
    function toQuery(s) {
        var parts = [];
        if (s.page > 1) parts.push('page=' + s.page);
        if (s.market) parts.push('market=' + s.market);
        if (s.search) parts.push('search=' + encodeURIComponent(s.search));
        return parts.length ? '?' + parts.join('&') : '';
    }

    function n(v, d) {
        return (v || 0).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
    }

    /** 시가총액 — 템플릿 `won`. ⚠️ 억·만은 **정수**다. */
    function won(v) {
        if (!v) return '0';
        if (v >= 1e20) return n(v / 1e20, 2) + '해';
        if (v >= 1e16) return n(v / 1e16, 2) + '경';
        if (v >= 1e12) return n(v / 1e12, 2) + '조';
        if (v >= 1e8) return n(v / 1e8, 0) + '억';
        if (v >= 1e4) return n(v / 1e4, 0) + '만';
        return n(v, 0);
    }

    /** 상장주식수·발행량 — 템플릿 `qty`. ⚠️ 억·만이 **소수 1자리**이고 해 단위가 없다. */
    function qty(v) {
        if (!v) return '0';
        if (v >= 1e16) return n(v / 1e16, 2) + '경';
        if (v >= 1e12) return n(v / 1e12, 2) + '조';
        if (v >= 1e8) return n(v / 1e8, 1) + '억';
        if (v >= 1e4) return n(v / 1e4, 1) + '만';
        return n(v, 0);
    }

    /** 거래대금 — 템플릿 `amt`. ⚠️ 해·경·조가 **소수 1자리**다(won 은 2자리). */
    function amt(v) {
        if (!v) return '0';
        if (v >= 1e20) return n(v / 1e20, 1) + '해';
        if (v >= 1e16) return n(v / 1e16, 1) + '경';
        if (v >= 1e12) return n(v / 1e12, 1) + '조';
        if (v >= 1e8) return n(v / 1e8, 0) + '억';
        if (v >= 1e4) return n(v / 1e4, 0) + '만';
        return n(v, 0);
    }

    function isUS(market) { return US_MARKETS.indexOf(market) >= 0; }
    function price(v, market) { return isUS(market) ? '$' + n(v, 2) : n(v, 0) + '원'; }
    function cap(v, market) { return isUS(market) ? '$' + n((v || 0) / 1e9, 2) + 'B' : won(v); }

    function el(tag, cls, text) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        // ⚠️ 항상 textContent 다. 종목명은 외부에서 온 값이라 innerHTML 로 넣으면 XSS 다
        //    (서버 렌더 때는 Jinja 가 자동 이스케이프해 줬다).
        if (text != null) e.textContent = text;
        return e;
    }

    function detailUrl(code, isCoin) {
        return '/stocks/view?code=' + encodeURIComponent(code) + (isCoin ? '&market=COIN' : '');
    }

    function fullRow(cls, text) {
        var tr = document.createElement('tr');
        var td = el('td', cls, text);
        td.colSpan = 7;
        tr.appendChild(td);
        return tr;
    }

    function row(s) {
        var tr = el('tr', 'stock-row');
        var url = detailUrl(s.code, s.type === 'COIN');
        tr.addEventListener('click', function () { location.href = url; });

        var nameCell = el('td', 'stock-name-cell');
        nameCell.appendChild(el('div', 'stock-name-kr', s.name_kr || s.code));
        if (s.name_en) nameCell.appendChild(el('div', 'stock-name-en', s.name_en));
        tr.appendChild(nameCell);

        tr.appendChild(el('td', 'stock-code', s.code));

        var mtd = document.createElement('td');
        mtd.appendChild(el('span', 'market-badge market-' + String(s.market || '').toLowerCase(),
                           s.market || ''));
        tr.appendChild(mtd);

        var ttd = document.createElement('td');
        ttd.appendChild(el('span', 'type-badge type-' + String(s.type || '').toLowerCase(),
                           s.type || ''));
        tr.appendChild(ttd);

        tr.appendChild(el('td', 'stock-price', price(s.price || 0, s.market)));
        tr.appendChild(el('td', 'stock-cap', cap(s.market_cap || 0, s.market)));
        tr.appendChild(el('td', null, qty(s.quantity || 0)));
        return tr;
    }

    /** 페이저 — 현재 쪽 ±4, 잘린 끝에 첫·마지막과 `…`. 서버 규칙과 같다. */
    function renderPager(state, pages) {
        pagerEl.innerHTML = '';
        // ⚠️ 비워 두는 것만으로는 부족하다. `.pagination` 은 `margin-top: 20px` 이라
        //    빈 채로 남으면 한 쪽짜리 목록 밑에 여백만 생긴다(서버 렌더는 아예 안 그렸다).
        pagerEl.style.display = pages > 1 ? '' : 'none';
        if (pages <= 1) return;
        var start = Math.max(1, state.page - 4), end = Math.min(pages, state.page + 4);

        function link(p, label) {
            var a = el('a', 'page-link', label == null ? String(p) : label);
            a.href = toQuery({ page: p, market: state.market, search: state.search }) || '/stocks';
            a.addEventListener('click', function (ev) { ev.preventDefault(); go({ page: p }); });
            return a;
        }
        function dots() { return el('span', 'page-ellipsis', '…'); }

        if (state.page > 1) pagerEl.appendChild(link(state.page - 1, '←'));
        if (start > 1) {
            pagerEl.appendChild(link(1));
            if (start > 2) pagerEl.appendChild(dots());
        }
        for (var p = start; p <= end; p++) {
            // ⚠️ 현재 쪽도 `page-link` 를 함께 받아야 한다 — 버튼 모양이 거기서 온다.
            if (p === state.page) pagerEl.appendChild(el('span', 'page-link page-current', String(p)));
            else pagerEl.appendChild(link(p));
        }
        if (end < pages) {
            if (end < pages - 1) pagerEl.appendChild(dots());
            pagerEl.appendChild(link(pages));
        }
        if (state.page < pages) pagerEl.appendChild(link(state.page + 1, '→'));
    }

    function renderTop(list) {
        if (!topEl) return;
        topEl.innerHTML = '';
        if (!list.length) {
            topEl.appendChild(el('div', 'top10-empty', '데이터가 없습니다.'));
            return;
        }
        list.forEach(function (s, i) {
            var item = el('div', 'top10-item');
            // ⚠️ 여기서 코인은 `market === 'Bithumb'` 이다. 목록 쪽 판정과 다르다.
            var url = detailUrl(s.code, s.market === 'Bithumb');
            item.addEventListener('click', function () { location.href = url; });

            item.appendChild(el('div', 'top10-rank', String(i + 1)));
            var info = el('div', 'top10-info');
            info.appendChild(el('div', 'top10-name', s.name_kr || s.code));
            info.appendChild(el('div', 'top10-code', s.code));
            item.appendChild(info);

            var val = el('div', 'top10-value');
            val.appendChild(el('div', 'top10-primary', price(s.price || 0, s.market)));
            val.appendChild(el('div', 'top10-secondary', amt(s.trading_amount || 0)));
            item.appendChild(val);
            topEl.appendChild(item);
        });
    }

    /** 탭 표시·헤더 라벨·검색폼의 숨은 market — 서버가 하던 일. */
    function syncChrome(state) {
        tabEls.forEach(function (t) {
            t.classList.toggle('active', t.getAttribute('data-group') === state.market);
        });
        if (qtyHeadEl) qtyHeadEl.textContent = state.market === 'COIN' ? '총 발행량' : '상장주식수';
        if (formEl) {
            var hidden = formEl.querySelector('input[name="market"]');
            if (hidden) hidden.value = state.market;
        }
        // 상세 화면의 "목록으로"(goBackToStockList)가 읽는 값. 탭이 이제 페이지 이동 없이
        // 바뀌므로 주소가 바뀔 때마다 다시 쓴다.
        try {
            var raw = (new URLSearchParams(location.search).get('market') || '').toUpperCase();
            if (GROUPS.indexOf(raw) >= 0) sessionStorage.setItem('stock_market_preference', raw);
            else sessionStorage.removeItem('stock_market_preference');
        } catch (e) { /* 사생활 보호 모드 등 — 무시한다 */ }
    }

    var reqId = 0;

    function load(state, retried) {
        var mine = ++reqId;                  // 늦게 온 옛 응답이 새 화면을 덮지 않게
        syncChrome(state);

        tbodyEl.innerHTML = '';
        tbodyEl.appendChild(fullRow('no-data', '불러오는 중…'));

        var q = ['size=' + PER_PAGE, 'page=' + state.page, 'market=' + state.market];
        if (state.search) q.push('q=' + encodeURIComponent(state.search));

        return Promise.all([
            fetch('/api/v1/stocks?' + q.join('&'), { headers: { 'Accept': 'application/json' } })
                .then(function (r) {
                    if (!r.ok) throw new Error('HTTP ' + r.status);
                    return r.json();
                }),
            fetch('/api/v1/stocks/top?limit=10&market=' + state.market)
                .then(function (r) { return r.ok ? r.json() : []; })
                .catch(function () { return []; })      // TOP10 이 없다고 표까지 죽이진 않는다
        ]).then(function (res) {
            if (mine !== reqId) return;
            var data = res[0];

            // 서버는 범위를 넘은 쪽을 마지막 쪽으로 당겼다. 딥링크·뒤로가기가 빈 표를
            // 보지 않게 같은 규칙을 둔다(한 번만 — 되풀이하면 무한 루프다).
            if (state.page > data.pages && !retried) {
                var fixed = Object.assign({}, state, { page: data.pages });
                history.replaceState(null, '', '/stocks' + toQuery(fixed));
                return load(fixed, true);
            }

            tbodyEl.innerHTML = '';
            if (!data.items.length) tbodyEl.appendChild(fullRow('no-data', '조회된 종목이 없습니다.'));
            else data.items.forEach(function (s) { tbodyEl.appendChild(row(s)); });

            renderPager(state, data.pages);
            renderTop(res[1] || []);
        }).catch(function (e) {
            if (mine !== reqId) return;
            // ⚠️ 조용히 빈 표를 두지 않는다. 서버 렌더 때는 실패가 곧 500 이라 눈에
            //    보였는데, 클라이언트 렌더는 "종목이 없는 화면" 처럼 보인다.
            tbodyEl.innerHTML = '';
            tbodyEl.appendChild(fullRow('no-data', '목록을 불러오지 못했습니다. 새로고침 해주세요.'));
            pagerEl.innerHTML = '';
            if (window.console) console.error('종목 목록 로드 실패', e);
        });
    }

    function go(patch) {
        var state = Object.assign(readState(), patch);
        if (patch.page === undefined) state.page = 1;      // 탭·검색이 바뀌면 1쪽으로
        history.pushState(null, '', '/stocks' + toQuery(state));
        load(state);
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    function init() {
        rootEl = document.getElementById('stocksRoot');
        if (!rootEl) return;
        tbodyEl = document.getElementById('stockRows');
        pagerEl = document.getElementById('stockPager');
        if (!tbodyEl || !pagerEl) return;

        topEl = document.getElementById('stockTop10');
        qtyHeadEl = document.getElementById('stockQtyHead');
        formEl = document.getElementById('stockSearchForm');
        defaultMarket = (rootEl.getAttribute('data-market') || 'KR').toUpperCase();

        tabEls = Array.prototype.slice.call(
            document.querySelectorAll('.market-stat-item-h[data-group]'));
        tabEls.forEach(function (t) {
            t.addEventListener('click', function () {
                go({ market: t.getAttribute('data-group') });
            });
        });

        if (formEl) {
            formEl.addEventListener('submit', function (ev) {
                ev.preventDefault();
                var input = formEl.querySelector('input[name="search"]');
                go({ search: input ? input.value.trim().slice(0, MAX_SEARCH) : '' });
            });
        }

        window.addEventListener('popstate', function () { load(readState()); });
        load(readState());
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
