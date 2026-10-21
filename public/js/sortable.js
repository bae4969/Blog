/**
 * 손잡이 끌기 정렬 — Pointer Events(11.web_design 결정 #14, `examples/drag-reorder-touch.html` 의 makeSortable 이식).
 * HTML5 드래그는 터치에 없어 폰·태블릿에서 순서를 못 바꿨다(그동안은 터치 전용 ↑↓ — 결정으로 없앴다). 마우스·손가락이 같은 조작이다.
 *
 *   makeSortable(list, { rowSelector, gripSelector, onMove(from, to), onStart(), onEnd() })
 *   · 시작은 손잡이 pointerdown 만(모든 pointerType) → setPointerCapture. 손잡이가 끌기 전용이라 클릭/끌기 임계값이 없다.
 *     손잡이에만 `touch-action: none`(CSS) — 행·목록을 짚은 손가락은 그대로 스크롤이다.
 *   · 자리는 pointermove 의 clientY 하나로 행 중앙선을 센다(정본 computeRowDrop). 선과 놓기가 같은 계산, 제자리면 선이 없다.
 *   · pointerup 적용 · pointercancel/lostpointercapture/Esc 취소 — 셋이 같은 해제 함수를 부른다.
 *   · 스크롤 칸(없으면 문서 — 위 끝은 고정 상단바 아래) 위·아래 끝 24px 안이면 프레임마다 굴린다(최대 12px).
 *   · 손가락을 따라가는 행 복제(HTML5 고스트 대신), 끄는 행은 0.45. 키보드는 손잡이 포커스 + ↑/↓ 로 한 칸(포커스 유지).
 *   onMove 가 실제로 옮기고(데이터·DOM) 저장한다. onStart/onEnd 는 끄는 동안 다시 그리기를 미룰 때.
 */
(function () {
    'use strict';

    var EDGE = 24, MAX_STEP = 12;
    var line = null;
    var cancelActive = null;   // 지금 끄는 목록의 취소 — 한 번에 하나

    // Esc 는 끌기 취소만 — 같은 Esc 가 AI 시트·창까지 닫지 않게(한 겹씩). 목록마다 걸면 다시 그릴 때마다 쌓인다 — 하나만.
    window.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && cancelActive) { e.preventDefault(); e.stopPropagation(); cancelActive(); }
    }, true);

    /** 행 중앙선을 커서가 넘은 수 = 놓을 자리(끄는 행을 뺀 목록 기준). */
    function computeRowDrop(els, from, y) {
        if (from < 0 || els.length < 2) return { ok: false };
        var index = 0;
        for (var i = 0; i < els.length; i++) {
            var r = els[i].getBoundingClientRect();
            if (y > (r.top + r.bottom) / 2) index++;
            else break;
        }
        var at = els[index];
        return { ok: true, index: index > from ? index - 1 : index, anchor: at || els[els.length - 1], before: !!at };
    }

    // 놓을 자리 선 하나를 재사용한다(fixed — 스크롤 계산이 없다). 창(dialog·popover) 안 목록이면 그 안에 둬야 보인다.
    function showLine(drop) {
        if (!line) { line = document.createElement('div'); line.className = 'c-drop-line'; }
        var host = drop.anchor.closest('dialog, [popover]') || document.body;
        if (line.parentNode !== host) host.appendChild(line);
        var r = drop.anchor.getBoundingClientRect();
        line.style.left = r.left + 'px';
        line.style.width = r.width + 'px';
        line.style.top = (drop.before ? r.top : r.bottom) - 1 + 'px';
        line.hidden = false;
    }
    function hideLine() { if (line) line.hidden = true; }

    /** 가장 가까운 세로 스크롤 칸 — 없으면 null(문서). */
    function scroller(el) {
        for (var p = el.parentElement; p && p !== document.body && p !== document.documentElement; p = p.parentElement) {
            if (/(auto|scroll)/.test(getComputedStyle(p).overflowY) && p.scrollHeight > p.clientHeight) return p;
        }
        return null;
    }

    /** 손가락을 따라가는 복제 — id·name·form 은 떼고(같은 id 가 둘이 된다), 안의 select 는 앱 모양으로 바꾸지 않는다. */
    function ghostOf(row, r) {
        var g, tr = row.cloneNode(true);
        if (row.tagName === 'TR') {   // 행만 떼면 표 밖에서 칸이 무너진다 — 같은 표(빈 껍데기)에 칸 폭을 맞춰 담는다
            Array.prototype.forEach.call(row.children, function (td, i) { tr.children[i].style.width = td.getBoundingClientRect().width + 'px'; });
            tr.style.background = 'var(--bae-surface-alt)';   // 좁은 화면 카드 모양(행이 블록)에서는 표 바탕이 행을 다 덮지 못했다
            g = row.closest('table').cloneNode(false);
            var tb = document.createElement('tbody');
            tb.appendChild(tr);
            g.appendChild(tb);
        } else {
            g = tr;
        }
        g.querySelectorAll('[id]').forEach(function (n) { n.removeAttribute('id'); });
        g.querySelectorAll('[name], [form]').forEach(function (n) { n.removeAttribute('name'); n.removeAttribute('form'); });
        g.querySelectorAll('select').forEach(function (n) { n.setAttribute('data-native', ''); });
        g.removeAttribute('id');
        g.setAttribute('aria-hidden', 'true');
        g.style.cssText += ';position:fixed;left:0;top:0;margin:0;width:' + r.width + 'px;pointer-events:none;z-index:1000;' +
            'opacity:.9;background:var(--bae-surface-alt);box-shadow:0 4px 12px rgba(0,0,0,.35);will-change:transform;';
        return g;
    }

    window.makeSortable = function (list, opts) {
        var drag = null;   // { row, grip, ghost, pointerId, from, lastY, offX, offY, raf, drop, sc }

        function rows() { return Array.prototype.slice.call(list.querySelectorAll(opts.rowSelector)); }

        function computeDrop(y) {
            var drop = computeRowDrop(rows(), drag.from, y);
            if (drop.ok && drop.index === drag.from) drop.ok = false;   // 제자리 — 선 없음
            return drop;
        }

        function show(drop) { if (drop.ok) showLine(drop); else hideLine(); }

        function autoScroll() {
            if (!drag) return;
            var top, bottom;
            if (drag.sc) {
                var r = drag.sc.getBoundingClientRect();
                top = r.top; bottom = r.bottom;
            } else {
                var bar = document.querySelector('.c-topbar');
                top = bar ? Math.max(0, bar.getBoundingClientRect().bottom) : 0;
                bottom = window.innerHeight;
            }
            var y = drag.lastY, dy = 0;
            if (y < top + EDGE) dy = -Math.min(MAX_STEP, Math.ceil((top + EDGE - y) / 2));
            else if (y > bottom - EDGE) dy = Math.min(MAX_STEP, Math.ceil((y - (bottom - EDGE)) / 2));
            if (dy) {
                if (drag.sc) drag.sc.scrollTop += dy; else window.scrollBy(0, dy);
                drag.drop = computeDrop(y);
                show(drag.drop);
            }
            drag.raf = requestAnimationFrame(autoScroll);
        }

        function moveGhost(x, y) { drag.ghost.style.transform = 'translate(' + (x - drag.offX) + 'px,' + (y - drag.offY) + 'px)'; }

        function start(e) {
            if (e.button !== 0 || drag) return;   // 주 버튼만(터치·펜의 접촉도 0)
            var grip = e.target.closest && e.target.closest(opts.gripSelector);
            var row = grip && grip.closest(opts.rowSelector);
            if (!row || !list.contains(row)) return;
            var r = row.getBoundingClientRect();
            var ghost = ghostOf(row, r);
            (row.closest('dialog, [popover]') || document.body).appendChild(ghost);
            drag = { row: row, grip: grip, ghost: ghost, pointerId: e.pointerId, from: rows().indexOf(row), lastY: e.clientY,
                     offX: e.clientX - r.left, offY: e.clientY - r.top, raf: 0, drop: { ok: false }, sc: scroller(list) };
            row.classList.add('is-dragging');
            cancelActive = function () { end(null, false); };
            document.documentElement.style.cursor = 'grabbing';
            grip.setPointerCapture(e.pointerId);   // 손가락이 손잡이 밖으로 나가도 pointermove 가 계속 온다
            moveGhost(e.clientX, e.clientY);
            drag.raf = requestAnimationFrame(autoScroll);
            if (opts.onStart) opts.onStart();
        }

        function move(e) {
            if (!drag || e.pointerId !== drag.pointerId) return;
            drag.lastY = e.clientY;
            moveGhost(e.clientX, e.clientY);
            drag.drop = computeDrop(e.clientY);
            show(drag.drop);
        }

        // 놓기·취소·포인터 잃음 — 전부 여기로. apply 일 때만 옮긴다.
        function end(e, apply) {
            if (!drag || (e && e.pointerId !== undefined && e.pointerId !== drag.pointerId)) return;
            var d = drag;
            drag = null;
            cancelActive = null;
            cancelAnimationFrame(d.raf);
            hideLine();
            d.ghost.remove();
            d.row.classList.remove('is-dragging');
            document.documentElement.style.cursor = '';
            try { d.grip.releasePointerCapture(d.pointerId); } catch (err) { /* 이미 풀림 */ }
            if (apply && d.drop.ok) opts.onMove(d.from, d.drop.index);
            if (opts.onEnd) opts.onEnd();
        }

        list.addEventListener('pointerdown', start);
        list.addEventListener('pointermove', move);
        list.addEventListener('pointerup', function (e) { end(e, true); });
        list.addEventListener('pointercancel', function (e) { end(e, false); });
        list.addEventListener('lostpointercapture', function (e) { end(e, false); });

        // 키보드 — 손잡이 포커스 + ↑/↓ 한 칸. 옮긴 뒤에도 같은 항목의 손잡이에 포커스.
        list.addEventListener('keydown', function (e) {
            var grip = e.target.closest && e.target.closest(opts.gripSelector);
            var dir = e.key === 'ArrowUp' ? -1 : e.key === 'ArrowDown' ? 1 : 0;
            if (!grip || !dir) return;
            e.preventDefault();   // 목록·문서가 스크롤되지 않게
            var all = rows(), from = all.indexOf(grip.closest(opts.rowSelector)), to = from + dir;
            if (from < 0 || to < 0 || to >= all.length) return;
            opts.onMove(from, to);
            var again = rows()[to];
            again = again && again.querySelector(opts.gripSelector);
            if (again) again.focus();
        });
    };
})();
