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

    function api(method, url, body) {
        return authToken().then(function (t) {
            var headers = { 'Authorization': 'Bearer ' + t, 'Accept': 'application/json' };
            if (body !== undefined) headers['Content-Type'] = 'application/json';
            return fetch(url, { method: method, headers: headers, body: body === undefined ? undefined : JSON.stringify(body) });
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

    /** 아이콘 — `_icons.html` 과 같은 그림(프로젝트 디자인 규칙: 버튼엔 SVG). `parts` 는 [태그, 속성] 목록. */
    function icon(parts) {
        var ns = 'http://www.w3.org/2000/svg';
        var svg = document.createElementNS(ns, 'svg');
        svg.setAttribute('class', 'c-ico');
        svg.setAttribute('viewBox', '0 0 24 24');
        svg.setAttribute('fill', 'none');
        svg.setAttribute('stroke', 'currentColor');
        svg.setAttribute('stroke-width', '2');
        svg.setAttribute('stroke-linecap', 'round');
        svg.setAttribute('stroke-linejoin', 'round');
        svg.setAttribute('aria-hidden', 'true');
        parts.forEach(function (part) {
            var node = document.createElementNS(ns, part[0]);
            Object.keys(part[1]).forEach(function (k) { node.setAttribute(k, part[1][k]); });
            svg.appendChild(node);
        });
        return svg;
    }

    var ICON = {
        cancel: [['path', { d: 'M18 6 6 18' }], ['path', { d: 'm6 6 12 12' }]],
        up: [['path', { d: 'm6 15 6-6 6 6' }]],
        down: [['path', { d: 'm6 9 6 6 6-6' }]],
        grip: [[9, 5], [15, 5], [9, 12], [15, 12], [9, 19], [15, 19]].map(function (c) {
            return ['circle', { cx: c[0], cy: c[1], r: 1 }];
        })
    };

    function key(item) { return item.market + ':' + item.code; }

    function iconButton(cls, label, name, onClick) {
        var b = el('button', cls);
        b.type = 'button';
        b.setAttribute('aria-label', label);
        b.appendChild(icon(ICON[name]));
        b.addEventListener('click', onClick);
        return b;
    }

    function render() {
        countEl.textContent = items && items.length ? String(items.length) : '';
        if (!items.length) {
            message('종목 화면의 ☆ 관심 버튼으로 담아 보세요.');
            return;
        }
        // 다시 그려도(1분마다 시세) 키보드로 옮기던 손잡이·↑↓ 에 포커스를 돌려준다.
        var focused = document.activeElement && document.activeElement.closest &&
                      document.activeElement.closest('.c-watch__item');
        var focusKey = focused ? focused.dataset.key : null;
        var focusCls = focused ? document.activeElement.className : null;

        var ul = el('ul', 'c-watch');
        items.forEach(function (item, idx) {
            var li = el('li', 'c-watch__item');
            li.dataset.key = key(item);

            // 순서 — 손잡이만 끈다(행은 링크라 통째로 끌면 링크가 끌린다). 정본 drag-reorder.md 정렬 표준.
            var grip = el('span', 'c-watch__grip');
            grip.draggable = true;
            grip.tabIndex = 0;
            grip.title = '끌어서 순서 변경';
            grip.setAttribute('aria-label', '순서 변경 (위·아래 방향키)');
            grip.appendChild(icon(ICON.grip));
            li.appendChild(grip);

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
            rm.appendChild(icon(ICON.cancel));
            rm.addEventListener('click', function () { setWatched(item, false); });
            li.appendChild(rm);

            // 터치가 있는 기기에서는 끌기가 없어 ↑↓ 도 둔다(CSS 가 any-pointer: coarse 에서만 보인다).
            var up = iconButton('c-watch__mv c-watch__mv--up', '위로', 'up', function () { move(li, -1, up); });
            var down = iconButton('c-watch__mv c-watch__mv--down', '아래로', 'down', function () { move(li, 1, down); });
            up.disabled = idx === 0;
            down.disabled = idx === items.length - 1;
            li.appendChild(up);
            li.appendChild(down);
            ul.appendChild(li);
        });
        wireReorder(ul);
        listEl.innerHTML = '';
        listEl.appendChild(ul);
        if (focusKey) {
            var again = ul.querySelector('[data-key="' + focusKey + '"] .' + String(focusCls).split(' ').pop());
            if (again) again.focus();
        }
    }

    /* ── 순서 바꾸기 ───────────────────────────────────────────────── */
    // 화면 먼저 바꾸고(낙관적) 400ms 모아 마지막 순서만 보낸다. 저장 중·끄는 중에는 1분 갱신이 다시 그리지 않는다.
    var dragLi = null;
    var dropLine = null;
    var saveTimer = null;
    var saving = false;

    function busy() { return !!dragLi || !!saveTimer || saving; }

    /** DOM 의 행 순서를 `items` 에 옮기고 ↑↓ 비활성을 맞춘다. */
    function syncOrder(ul) {
        var byKey = {};
        items.forEach(function (it) { byKey[key(it)] = it; });
        var lis = Array.prototype.slice.call(ul.children);
        items = lis.map(function (li) { return byKey[li.dataset.key]; });
        lis.forEach(function (li, i) {
            li.querySelector('.c-watch__mv--up').disabled = i === 0;
            li.querySelector('.c-watch__mv--down').disabled = i === lis.length - 1;
        });
    }

    function scheduleSave() {
        clearTimeout(saveTimer);
        saveTimer = setTimeout(function () {
            saveTimer = null;
            saving = true;
            api('PUT', '/api/v1/watchlist', { items: items.map(function (it) { return { code: it.code, market: it.market }; }) })
                .then(function () {
                    if (window.toast) window.toast('관심 종목 순서를 바꿨습니다.', 'success');
                })
                .catch(function (error) {
                    // 그사이 다른 기기에서 담거나 뺐으면(409) 서버 순서로 다시 그린다. 그 밖에는 화면 순서를 둔다.
                    var stale = error.status === 409;
                    if (window.toast) {
                        window.toast(stale ? '관심 종목이 그사이 바뀌어 다시 불러왔습니다.'
                                           : '관심 종목 순서를 저장하지 못했습니다.', 'error');
                    }
                    if (stale) { saving = false; load(); }
                })
                .then(function () { saving = false; });
        }, 400);
    }

    /** 한 칸 옮긴다(↑↓ 버튼·방향키). 옮긴 뒤 같은 항목의 같은 조작 요소에 포커스를 둔다. */
    function move(li, dir, focusEl) {
        var ul = li.parentNode;
        var to = dir < 0 ? li.previousElementSibling : li.nextElementSibling;
        if (!to) return;
        ul.insertBefore(li, dir < 0 ? to : to.nextSibling);
        syncOrder(ul);
        // 누른 ↑ 가 맨 위로 와서 꺼지면 같은 행의 ↓, 그것도 안 되면 손잡이(보일 때)로.
        var next = [focusEl, li.querySelector('.c-watch__mv--' + (dir < 0 ? 'down' : 'up')), li.querySelector('.c-watch__grip')]
            .filter(function (n) { return n && !n.disabled && n.offsetParent !== null; })[0];
        if (next) next.focus();
        scheduleSave();
    }

    // 놓을 자리 = 커서 Y 가 넘은 (끄는 행을 뺀) 행 중앙선 수. 제자리면 옮길 곳이 없다.
    function computeDrop(ul, y) {
        var others = Array.prototype.filter.call(ul.children, function (n) { return n !== dragLi; });
        var idx = 0;
        others.forEach(function (n) {
            var b = n.getBoundingClientRect();
            if (y > b.top + b.height / 2) idx++;
        });
        if (idx === Array.prototype.indexOf.call(ul.children, dragLi)) return null;
        return idx < others.length ? { anchor: others[idx], before: true } : { anchor: others[others.length - 1], before: false };
    }

    function showLine(drop) {
        if (!dropLine) { dropLine = el('div', 'c-watch__drop'); document.body.appendChild(dropLine); }
        var r = drop.anchor.getBoundingClientRect();
        dropLine.style.left = r.left + 'px';
        dropLine.style.width = r.width + 'px';
        dropLine.style.top = (drop.before ? r.top : r.bottom) - 1 + 'px';
        dropLine.hidden = false;
    }

    function hideLine() { if (dropLine) dropLine.hidden = true; }

    function wireReorder(ul) {
        ul.addEventListener('dragstart', function (e) {
            var grip = e.target.closest && e.target.closest('.c-watch__grip');
            if (!grip) return;
            dragLi = grip.closest('li');
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', dragLi.dataset.key);   // Firefox 는 데이터가 없으면 끌기를 시작하지 않는다
            e.dataTransfer.setDragImage(dragLi, 8, 16);
            dragLi.classList.add('is-dragging');
        });
        ul.addEventListener('dragover', function (e) {
            if (!dragLi) return;
            var drop = computeDrop(ul, e.clientY);
            if (!drop) { hideLine(); e.dataTransfer.dropEffect = 'none'; return; }   // preventDefault 없음 → 금지 커서
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            showLine(drop);
        });
        ul.addEventListener('drop', function (e) {
            if (!dragLi) return;
            var drop = computeDrop(ul, e.clientY);
            if (!drop) return;
            e.preventDefault();
            ul.insertBefore(dragLi, drop.before ? drop.anchor : drop.anchor.nextSibling);
            syncOrder(ul);
            scheduleSave();
        });
        ul.addEventListener('dragend', function () {
            if (dragLi) dragLi.classList.remove('is-dragging');
            dragLi = null;
            hideLine();
        });
        ul.addEventListener('keydown', function (e) {
            var grip = e.target.closest && e.target.closest('.c-watch__grip');
            if (!grip || (e.key !== 'ArrowUp' && e.key !== 'ArrowDown')) return;
            e.preventDefault();   // 레일이 스크롤되지 않게
            move(grip.closest('li'), e.key === 'ArrowUp' ? -1 : 1, grip);
        });
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
                // 끄는 중·순서를 저장하는 중에는 다시 그리지 않는다 — 붙잡은 행이 문서에서 빠지면 끌기가 굳는다.
                if (busy() && items) return;
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
