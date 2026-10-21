/**
 * 값 고르기 select — 앱 모양 버튼 + 아래 뜨는 목록(11.web_design 결정 #13, 정본 30.ai_center `custom_select.js` 이식).
 * 네이티브 펼침 목록은 OS 모양이라 테마에 못 맞춘다 — 문서의 모든 `<select>` 를 이것으로 그린다.
 *
 *   · select 는 숨겨(`cs-native`) **값·옵션·이벤트의 주인**으로 남는다 — 쓰는 코드는 `.value`·`change`·`options` 를 그대로 쓴다.
 *   · 버튼은 select **바로 앞**(버튼 → 목록 → select), class 는 select 의 class 를 그대로 받는다(겉모양이 그대로 먹게).
 *     ⚠️ 그래서 클래스로 select 를 찾는 코드는 `select.이름` 으로 좁힌다 — 버튼이 앞에 있어 먼저 잡힌다.
 *   · 목록은 `popover="auto"`(같은 버튼·바깥·Esc 로 닫힘, 한 번에 하나), 자리는 `TopLayer.follow`(flip — 아래가 모자라면 위로,
 *     앵커가 가려지면 닫힘). 창 안 목록이 열린 채 막을 누르면 목록만 닫힌다(`TopLayer.bindModal`).
 *   · 키: 버튼 ↑↓ 로 열기, 목록 ↑↓·Home/End·글자 찾기(700ms 이어 치기)·Enter/Space 고르기·Tab 닫기, Esc 는 목록만.
 *   · `multiple`·`size > 1`·`data-native`·Quill 도구 막대는 네이티브로 둔다. 나중에 붙는 select(템플릿 복제 등)도 저절로 바뀐다.
 * 값은 `ui.css` `.cs-*`. toplayer.js 뒤에 싣는다.
 */
(function () {
    'use strict';
    if (window.CustomSelect) return;   // 두 번 실리면 prototype setter 를 이중으로 감싼다

    var CHEVRON = '<svg class="cs-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>';
    var PLACE = { side: 'below', align: 'left', gap: 4, flip: true, minBelow: 200, margin: 32 };   // 아래 200px 남으면 아래 · 화면 끝과 32px

    var ui = new WeakMap();   // select → { btn, label, menu }
    var open = null;          // 열린 목록의 select(한 번에 하나 — popover=auto)

    function el(tag, cls, attrs) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        if (attrs) Object.keys(attrs).forEach(function (k) { e.setAttribute(k, attrs[k]); });
        return e;
    }

    // 글 편집기(Quill)의 도구 막대 select 는 Quill 이 숨기고 자기 목록(picker)을 그린다 — 건드리지 않는다
    function skip(sel) { return sel.multiple || sel.size > 1 || sel.hasAttribute('data-native') || !!sel.closest('.ql-toolbar'); }

    function text(opt) {
        var s = el('span', 'cs-text');
        s.textContent = opt.text || ' ';
        return s;
    }

    function syncAttrs(sel, u) {
        u.btn.className = sel.className.replace(/\bcs-native\b/, '').trim() + ' cs-btn';
        u.btn.hidden = sel.hidden;
        u.btn.disabled = sel.disabled;
        var name = sel.getAttribute('aria-label') || sel.getAttribute('title');
        if (name) u.btn.setAttribute('aria-label', name); else u.btn.removeAttribute('aria-label');
    }

    /** 버튼 라벨(모든 항목을 한 칸에 겹쳐 두고 지금 것만 보인다 — 폭 = 가장 긴 항목)과 목록을 새로 그린다. */
    function render(sel) {
        var u = ui.get(sel);
        if (!u) return;
        var opts = Array.prototype.slice.call(sel.options);
        u.label.textContent = '';
        opts.forEach(function (o) { var s = el('span', 'cs-opt'); s.appendChild(text(o)); u.label.appendChild(s); });
        if (!opts.length) u.label.appendChild(el('span', 'cs-opt cs-cur'));   // 빈 select 도 높이를 지킨다
        u.menu.textContent = '';
        opts.forEach(function (o, i) {
            var item = el('button', 'cs-item', { type: 'button', role: 'option', 'data-index': String(i) });
            item.appendChild(text(o));
            item.disabled = o.disabled;
            item.addEventListener('click', function () { pick(sel, i); });
            u.menu.appendChild(item);
        });
        sync(sel);
    }

    function sync(sel) {
        var u = ui.get(sel);
        if (!u) return;
        var idx = sel.selectedIndex;
        Array.prototype.forEach.call(u.label.children, function (s, i) {
            s.classList.toggle('cs-cur', i === idx || (idx < 0 && i === 0 && !sel.options.length));
        });
        Array.prototype.forEach.call(u.menu.children, function (item, i) {
            item.setAttribute('aria-selected', i === idx ? 'true' : 'false');
        });
    }

    // 여러 번 바뀌어도 한 번에 — 마이크로태스크로 모은다
    var pending = [];
    function later(sel, full) {
        if (!ui.has(sel)) return;
        if (!pending.length) queueMicrotask(flush);
        if (pending.indexOf(sel) < 0) pending.push(sel);
        if (full) sel._csFull = true;
    }
    function flush() {
        var list = pending;
        pending = [];
        list.forEach(function (sel) {
            if (sel._csFull) { sel._csFull = false; render(sel); } else sync(sel);
        });
    }

    /** 고르기 — 닫고, 값이 바뀌었을 때만 input·change 를 select 에서. */
    function pick(sel, i) {
        ui.get(sel).menu.hidePopover();
        if (sel.selectedIndex === i) return;
        sel.selectedIndex = i;
        sel.dispatchEvent(new Event('input', { bubbles: true }));
        sel.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function items(sel) {
        return Array.prototype.filter.call(ui.get(sel).menu.children, function (b) { return !b.disabled; });
    }

    function enhance(sel) {
        if (ui.has(sel) || skip(sel)) return;
        // data-no-tip — 값이 보이는 버튼이라 이름 풍선(tooltip.js)은 띄우지 않는다
        var btn = el('button', '', { type: 'button', 'aria-haspopup': 'listbox', 'aria-expanded': 'false', 'data-no-tip': '' });
        var label = el('span', 'cs-label');
        btn.appendChild(label);
        btn.insertAdjacentHTML('beforeend', CHEVRON);
        var menu = el('div', 'cs-menu', { role: 'listbox', popover: 'auto' });
        var u = { btn: btn, label: label, menu: menu };
        ui.set(sel, u);
        sel.classList.add('cs-native');
        sel.before(btn, menu);
        syncAttrs(sel, u);
        render(sel);

        btn.popoverTargetElement = menu;   // 여닫기 — 열린 채 버튼을 누르면 닫힌다
        btn.addEventListener('keydown', function (e) {
            if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); menu.showPopover(); }
        });
        window.TopLayer.follow(menu, btn, PLACE);
        menu.addEventListener('beforetoggle', function (e) {
            if (e.newState !== 'open') return;
            var r = btn.getBoundingClientRect();
            menu.style.minWidth = r.width + 'px';
            menu.style.maxWidth = Math.max(r.width, document.documentElement.clientWidth - r.left - 8) + 'px';
        });
        menu.addEventListener('toggle', function (e) {
            var on = e.newState === 'open';
            btn.setAttribute('aria-expanded', on ? 'true' : 'false');
            if (on) {
                open = sel;
                var cur = menu.querySelector('[aria-selected="true"]:not(:disabled)') || items(sel)[0];
                if (cur) { cur.focus({ preventScroll: true }); cur.scrollIntoView({ block: 'nearest' }); }
            } else {
                if (open === sel) open = null;
                if (menu.contains(document.activeElement) || document.activeElement === document.body) btn.focus({ preventScroll: true });
            }
        });
        // 목록 안 키보드 — 쓴 키는 막아 밖 단축키로 새지 않게
        var typed = '', typedAt = 0;
        menu.addEventListener('keydown', function (e) {
            var list = items(sel), i = list.indexOf(document.activeElement), to = null;
            if (e.key === 'ArrowDown') to = list[Math.min(list.length - 1, i + 1)];
            else if (e.key === 'ArrowUp') to = list[Math.max(0, i - 1)];
            else if (e.key === 'Home') to = list[0];
            else if (e.key === 'End') to = list[list.length - 1];
            else if (e.key === 'Tab') { menu.hidePopover(); return; }
            else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey && e.key !== ' ') {
                var now = Date.now();
                typed = (now - typedAt < 700 ? typed : '') + e.key.toLowerCase();
                typedAt = now;
                var start = typed.length === 1 ? i + 1 : Math.max(0, i);
                var ordered = list.slice(start).concat(list.slice(0, start));
                to = ordered.find(function (b) { return b.textContent.trim().toLowerCase().indexOf(typed) === 0; }) || null;
                if (!to) { e.stopPropagation(); return; }
            } else {
                if (e.key === 'Enter' || e.key === ' ') e.stopPropagation();   // 버튼 click 이 고른다
                return;
            }
            e.preventDefault();
            e.stopPropagation();
            if (to) { to.focus({ preventScroll: true }); to.scrollIntoView({ block: 'nearest' }); }
        });
        // required 인데 비어 제출이 막히면 — 숨은 select 라 브라우저 말풍선이 안 뜬다, 목록을 연다
        sel.addEventListener('invalid', function () { btn.focus(); if (sel.options.length) menu.showPopover(); });

        new MutationObserver(function (recs) {
            var full = false;
            recs.forEach(function (r) {
                if (r.type === 'attributes' && r.target === sel) syncAttrs(sel, u);
                else full = true;
            });
            if (full) later(sel, true);
        }).observe(sel, { childList: true, subtree: true, characterData: true, attributes: true,
            attributeFilter: ['class', 'hidden', 'disabled', 'title', 'aria-label', 'label', 'value'] });
    }

    /** 버튼·목록을 select 바로 앞으로, select 가 빠졌으면 같이 뺀다. */
    function place(sel) {
        var u = ui.get(sel);
        if (!u) return;
        if (!sel.isConnected) { u.btn.remove(); u.menu.remove(); return; }
        if (sel.previousElementSibling !== u.menu || u.menu.previousElementSibling !== u.btn) sel.before(u.btn, u.menu);
    }

    // 코드가 .value·.selectedIndex·option.selected 를 바꿔도 표시가 따라온다 · 숨은 select 의 focus() 는 버튼으로
    function wrap(proto, prop, selOf) {
        var d = Object.getOwnPropertyDescriptor(proto, prop);
        Object.defineProperty(proto, prop, {
            configurable: true, enumerable: d.enumerable, get: d.get,
            set: function (v) { d.set.call(this, v); var s = selOf(this); if (s) later(s, false); },
        });
    }
    wrap(HTMLSelectElement.prototype, 'value', function (x) { return x; });
    wrap(HTMLSelectElement.prototype, 'selectedIndex', function (x) { return x; });
    wrap(HTMLOptionElement.prototype, 'selected', function (o) { return o.parentElement && o.parentElement.closest('select'); });
    var nativeFocus = HTMLSelectElement.prototype.focus;
    HTMLSelectElement.prototype.focus = function (o) {
        var u = ui.get(this);
        return u ? u.btn.focus(o) : nativeFocus.call(this, o);
    };

    // 목록이 열린 동안 Esc 는 목록만 닫는다(window capture — 떠 있는 창·모달·AI 시트보다 먼저)
    window.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape' || !open) return;
        e.preventDefault();
        e.stopPropagation();
        ui.get(open).menu.hidePopover();
    }, true);

    // 문서의 select 전부 + 나중에 붙는 것
    function scan(root) {
        if (root.tagName === 'SELECT') { enhance(root); place(root); return; }
        if (root.getElementsByTagName) Array.prototype.forEach.call(root.getElementsByTagName('select'), function (s) { enhance(s); place(s); });
    }
    function start() {
        scan(document.body);
        new MutationObserver(function (recs) {
            recs.forEach(function (r) {
                r.addedNodes.forEach(function (n) { if (n.nodeType === 1) scan(n); });
                r.removedNodes.forEach(function (n) {
                    if (n.nodeType !== 1) return;
                    if (n.tagName === 'SELECT') place(n);
                    else if (n.getElementsByTagName) Array.prototype.forEach.call(n.getElementsByTagName('select'), place);
                });
            });
        }).observe(document.body, { childList: true, subtree: true });
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();

    window.CustomSelect = { enhance: enhance, skip: skip };
})();
