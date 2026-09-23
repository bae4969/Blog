/**
 * 관심 종목(2026-09-23) — 오른쪽 레일(`_watchlist.html`)과 종목 화면의 ☆ 버튼.
 *
 * 목록은 계정마다 서버에 있다(`/api/v1/watchlist`). 개인 데이터라 **읽기도 Bearer** 이고,
 * 인증 쿠키는 `httponly` 라 JS 가 못 읽으므로 `/api/v1/auth/token` 에서 지금 세션의 토큰을 받아
 * 싣는다(백테스트 프리셋과 같은 길 — `backtest.js` 참조). 토큰 수명은 10분이라 캐시해 두고
 * 만료 30초 전에 다시 받는다.
 *
 * 레일 여닫기
 * · 넓은 화면(≥ 90rem): 오른쪽에 붙고 본문이 비켜선다(`html.rail-open`). 기본은 열림, 고른
 *   상태를 기억한다. ⚠️ 첫 상태는 `layout.html` <head> 가 정한다 — `preferredOpen()` 과 조건을 맞출 것.
 * · 좁은 화면: 본문을 덮는 서랍. 늘 닫힌 채로 시작하고, 바깥·Esc·✕ 로 닫힌다.
 */
(function () {
    'use strict';

    var WIDE = window.matchMedia('(min-width: 90rem)');
    var PREF_KEY = 'watchRail';
    var US_MARKETS = ['US'];

    var railEl, listEl, countEl, toggleEls, starEl;
    var loggedIn = false;
    var loginUrl = '';
    var items = null;          // null = 아직 안 받음
    var refreshTimer = null;
    var token = null;
    var tokenExpiresAt = 0;

    /* ── 토큰 ──────────────────────────────────────────────────────── */
    function authToken() {
        if (token && Date.now() < tokenExpiresAt) return Promise.resolve(token);
        return fetch('/api/v1/auth/token', { method: 'POST' })
            .then(function (r) {
                if (!r.ok) throw new Error('로그인이 필요합니다');
                return r.json();
            })
            .then(function (j) {
                token = j.access_token;
                tokenExpiresAt = Date.now() + Math.max(0, (j.expires_in - 30)) * 1000;
                return token;
            });
    }

    function api(method, url) {
        return authToken().then(function (t) {
            return fetch(url, { method: method, headers: { 'Authorization': 'Bearer ' + t, 'Accept': 'application/json' } });
        }).then(function (r) {
            if (!r.ok) {
                var err = new Error('HTTP ' + r.status);
                err.status = r.status;
                throw err;
            }
            return r.status === 204 ? null : r.json();
        });
    }

    /* ── 그리기 ────────────────────────────────────────────────────── */
    function n(v, digits) {
        return Number(v || 0).toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
    }

    function price(item) {
        var v = item.price;
        if (v === null || v === undefined) return '-';
        if (US_MARKETS.indexOf(item.market) >= 0) return '$' + n(v, 2);
        return (v < 100 ? n(v, v < 1 ? 4 : 2) : n(v, 0)) + '원';
    }

    function pct(v) {
        if (v === null || v === undefined) return { text: '-', cls: 'q-flat' };
        return { text: (v > 0 ? '+' : '') + n(v, 2) + '%', cls: v > 0 ? 'q-up' : (v < 0 ? 'q-down' : 'q-flat') };
    }

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined && text !== null) node.textContent = text;
        return node;
    }

    function detailUrl(item) {
        return '/stocks/view?code=' + encodeURIComponent(item.code) + (item.market === 'COIN' ? '&market=COIN' : '');
    }

    function message(text) {
        listEl.innerHTML = '';
        listEl.appendChild(el('p', 'c-rail__msg', text));
    }

    /** ✕ 아이콘 — `_icons.html` 의 'cancel' 과 같은 그림(프로젝트 디자인 규칙: 버튼엔 SVG). */
    function removeIcon() {
        var ns = 'http://www.w3.org/2000/svg';
        var svg = document.createElementNS(ns, 'svg');
        svg.setAttribute('class', 'c-ico');
        svg.setAttribute('viewBox', '0 0 24 24');
        svg.setAttribute('fill', 'none');
        svg.setAttribute('stroke', 'currentColor');
        svg.setAttribute('stroke-width', '1.75');
        svg.setAttribute('stroke-linecap', 'round');
        svg.setAttribute('aria-hidden', 'true');
        ['M18 6 6 18', 'm6 6 12 12'].forEach(function (d) {
            var p = document.createElementNS(ns, 'path');
            p.setAttribute('d', d);
            svg.appendChild(p);
        });
        return svg;
    }

    function render() {
        countEl.textContent = items && items.length ? String(items.length) : '';
        if (!items.length) {
            message('종목 화면의 ☆ 관심 버튼으로 담아 보세요.');
            return;
        }
        var ul = el('ul', 'c-watch');
        items.forEach(function (item) {
            var li = el('li', 'c-watch__item');
            var a = el('a', 'c-watch__row');
            a.href = detailUrl(item);
            var nm = el('span', 'c-watch__nm', item.name_kr || item.code);
            nm.title = item.name_kr || item.code;
            a.appendChild(nm);
            a.appendChild(el('span', 'c-watch__px', price(item)));
            a.appendChild(el('span', 'c-watch__cd', item.code));
            var p = pct(item.change_pct);
            a.appendChild(el('span', 'c-watch__ch ' + p.cls, p.text));
            li.appendChild(a);

            var rm = el('button', 'c-watch__rm');
            rm.type = 'button';
            rm.setAttribute('aria-label', '관심 해제: ' + (item.name_kr || item.code));
            rm.appendChild(removeIcon());
            rm.addEventListener('click', function () { setWatched(item, false); });
            li.appendChild(rm);
            ul.appendChild(li);
        });
        listEl.innerHTML = '';
        listEl.appendChild(ul);
    }

    function syncStar() {
        if (!starEl) return;
        var on = !!items && items.some(function (i) {
            return i.code === starEl.dataset.watchCode && sameGroup(i.market, starEl.dataset.watchMarket);
        });
        starEl.setAttribute('aria-pressed', on ? 'true' : 'false');
    }

    function sameGroup(a, b) {
        return (a === 'COIN') === (b === 'COIN');
    }

    /* ── 서버 ──────────────────────────────────────────────────────── */
    var pending = null;   // 받는 중이면 그 약속을 같이 쓴다 — ☆ 와 레일이 동시에 부르면 두 번 받는다

    function load() {
        if (!loggedIn) return Promise.resolve();
        if (pending) return pending;
        pending = api('GET', '/api/v1/watchlist')
            .then(function (rows) {
                items = rows || [];
                render();
                syncStar();
            })
            .catch(function (error) {
                if (items === null) message('불러오지 못했습니다.');
                if (window.console) console.error('관심 종목 로드 실패', error);
            })
            .then(function () { pending = null; });
        return pending;
    }

    function setWatched(item, on) {
        if (!loggedIn) {
            if (window.toast) {
                window.toast('로그인하면 관심 종목을 담을 수 있습니다.', 'info',
                             { action: { label: '로그인', onClick: function () { location.href = loginUrl; } } });
            }
            return;
        }
        var url = '/api/v1/watchlist/' + encodeURIComponent(item.code) + '?market=' + encodeURIComponent(item.market);
        api(on ? 'PUT' : 'DELETE', url)
            .then(function () {
                if (window.toast) {
                    window.toast((item.name_kr || item.code) + (on ? ' — 관심 종목에 담았습니다.' : ' — 관심 종목에서 뺐습니다.'),
                                 'success',
                                 on ? {} : { action: { label: '되돌리기', onClick: function () { setWatched(item, true); } } });
                }
                return load();
            })
            .catch(function (error) {
                var msg = error.status === 409 ? '관심 종목이 가득 찼습니다(50개).' : '관심 종목을 바꾸지 못했습니다.';
                if (window.toast) window.toast(msg, 'error');
                if (window.console) console.error('관심 종목 변경 실패', error);
            });
    }

    /* ── 레일 여닫기 ───────────────────────────────────────────────── */
    /** 열림은 `<html class="rail-open">` 하나다 — <head> 인라인 스크립트가 첫 그림 전에 붙이고,
     *  여기서는 그 뒤의 여닫기만 한다(CSS 가 레일·바깥·본문 비켜서기를 모두 이 클래스로 본다). */
    function isOpen() {
        return document.documentElement.classList.contains('rail-open');
    }

    function setOpen(open, remember) {
        document.documentElement.classList.toggle('rail-open', open);
        toggleEls.forEach(function (b) { b.setAttribute('aria-expanded', open ? 'true' : 'false'); });
        if (remember && WIDE.matches) {
            try { localStorage.setItem(PREF_KEY, open ? 'open' : 'closed'); } catch (e) { /* 무시 */ }
        }
        clearInterval(refreshTimer);
        if (open) {
            if (items === null) load();
            // 열려 있는 동안만 1분마다 시세를 다시 받는다.
            refreshTimer = setInterval(function () {
                if (document.visibilityState === 'visible') load();
            }, 60000);
            if (!WIDE.matches) railEl.querySelector('[data-rail-close]').focus();
        }
    }

    function preferredOpen() {
        if (!WIDE.matches) return false;
        try { return localStorage.getItem(PREF_KEY) !== 'closed'; } catch (e) { return true; }
    }

    function init() {
        railEl = document.getElementById('watchRail');
        if (!railEl) return;
        listEl = document.getElementById('watchList');
        countEl = document.getElementById('watchCount');
        toggleEls = Array.prototype.slice.call(document.querySelectorAll('.c-rail-toggle'));
        starEl = document.querySelector('[data-watch-code]');
        loggedIn = railEl.dataset.loggedIn === 'true';
        loginUrl = railEl.dataset.loginUrl || '/';

        toggleEls.forEach(function (b) {
            b.addEventListener('click', function () { setOpen(!isOpen(), true); });
        });
        document.querySelectorAll('[data-rail-close]').forEach(function (b) {
            b.addEventListener('click', function () { setOpen(false, true); });
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && isOpen() && !WIDE.matches) setOpen(false, false);
        });
        WIDE.addEventListener('change', function () { setOpen(preferredOpen(), false); });

        if (starEl) {
            starEl.addEventListener('click', function () {
                setWatched({ code: starEl.dataset.watchCode, market: starEl.dataset.watchMarket,
                             name_kr: starEl.dataset.watchName }, starEl.getAttribute('aria-pressed') !== 'true');
            });
            // ☆ 상태를 알려면 목록이 있어야 한다 — 레일이 닫혀 있어도 한 번은 받는다.
            load();
        }
        setOpen(preferredOpen(), false);
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
