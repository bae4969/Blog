/**
 * top layer(popover · dialog) 공용 — 정본 30.ai_center `ui_modal.js` 의 placePopover · followAnchor ·
 * bindModal 과 같은 규칙(2026-10-13 현대화 D).
 *
 * top layer 는 z-index 와 상관없이 문서 위에 그려지고, 그 안의 순서는 **연 순서**다. 그래서
 *   · 토스트는 다른 것이 뒤에 열리면 다시 올린다(`changed()` → toast.js 의 `__raiseToasts`).
 *   · 툴팁은 띄울 때마다 다시 연다(tooltip.js) — 모달·토스트 위.
 * ⚠️ popover 는 top layer 라 `position: absolute` 의 기준(부모)이 사라진다 — 앵커의 화면 좌표로
 *    `fixed` 자리를 잡는다(`place`). 열린 동안 창 크기·스크롤·앵커 크기가 바뀌면 다시 잡는다(`follow`).
 */
(function () {
    'use strict';

    var TL = window.TopLayer = window.TopLayer || {};
    TL.seq = 0;

    /** 무엇이 top layer 에 새로 떴다 — 떠 있던 토스트를 그 위로 다시 올린다. */
    TL.changed = function () {
        TL.seq++;
        if (window.__raiseToasts) window.__raiseToasts();
    };

    /**
     * 앵커의 padding box(테두리 안쪽 — 옛 `absolute` 의 기준) 좌표로 fixed 자리를 준다.
     *   place.side  — 'below'(앵커 아래) | 'above'
     *   place.align — 'left' | 'right'(그 변을 맞춘다) | 'stretch'(앵커와 같은 폭)
     *   place.gap   — 앵커와 사이(px)
     *   place.minWidth — 'stretch'·'right' 에서 폭을 max(앵커 폭, minWidth) 로(옛 `max(100%, 24rem)`)
     */
    TL.place = function (pop, anchor, place) {
        var b = anchor.getBoundingClientRect();
        var left = b.left + anchor.clientLeft, top = b.top + anchor.clientTop;
        var r = { left: left, top: top, right: left + anchor.clientWidth, bottom: top + anchor.clientHeight };
        var vw = document.documentElement.clientWidth, vh = document.documentElement.clientHeight;
        var st = pop.style;
        st.left = st.right = st.top = st.bottom = st.width = '';
        var w = null;
        if (place.align === 'stretch' || place.minWidth) {
            w = Math.max(r.right - r.left, place.minWidth || 0);
            st.width = w + 'px';
        }
        // ⚠️ 오른쪽 맞춤은 폭을 알면 `left` 로 준다 — fixed 의 `right` 기준은 스크롤바 자리(`scrollbar-gutter: stable`)
        //    만큼 어긋났다(1600px 에서 15px).
        if (place.align === 'right') {
            if (w !== null) st.left = (r.right - w) + 'px';
            else st.right = (vw - r.right) + 'px';
        } else {
            st.left = r.left + 'px';
        }
        var gap = place.gap || 0;
        if (place.side === 'above') st.bottom = (vh - r.top + gap) + 'px';
        else st.top = (r.bottom + gap) + 'px';
    };

    /**
     * 앵커가 보이지 않는가 — 화면 밖, 잘라 내는 스크롤 부모 밖, 또는 고정 상단바(`.c-topbar`)에 통째로 가려졌다.
     * 상단바 안의 앵커(상단바 검색)는 상단바에 가려지지 않는다.
     */
    function anchorHidden(anchor) {
        var r = anchor.getBoundingClientRect();
        var top = 0, left = 0;
        var bottom = document.documentElement.clientHeight, right = document.documentElement.clientWidth;
        var bar = document.querySelector('.c-topbar');
        if (bar && !bar.contains(anchor)) top = Math.max(top, bar.getBoundingClientRect().bottom);
        for (var p = anchor.parentElement; p && p !== document.body && p !== document.documentElement; p = p.parentElement) {
            var cs = getComputedStyle(p);
            if (/(auto|scroll|hidden|clip)/.test(cs.overflowX + cs.overflowY)) {
                var q = p.getBoundingClientRect();
                top = Math.max(top, q.top); left = Math.max(left, q.left);
                bottom = Math.min(bottom, q.bottom); right = Math.min(right, q.right);
            }
        }
        return r.bottom <= top || r.top >= bottom || r.right <= left || r.left >= right;
    }

    /**
     * 열린 동안 자리를 따라간다. `getPlace` 는 열 때마다 부르는 함수(화면 폭에 따라 자리가 바뀌는 곳)이거나 값.
     * 연 뒤에는 토스트를 다시 올린다.
     * 앵커가 보이지 않게 되면(스크롤로 화면·상단바 뒤로) 닫는다 — 앵커 없이 상단바 위에 떠 있었다(2026-10-13 D14).
     * 닫힘 정리가 필요한 쪽은 popover `toggle`(newState 'closed')을 듣는다.
     */
    TL.follow = function (pop, anchor, getPlace) {
        function cur() { return typeof getPlace === 'function' ? getPlace() : getPlace; }
        function re() {
            if (!pop.matches(':popover-open')) return;
            if (anchorHidden(anchor)) { TL.hide(pop); return; }
            TL.place(pop, anchor, cur());
        }
        var ro = new ResizeObserver(re);
        // beforetoggle 은 보이기 직전(동기)이라 첫 그림부터 제자리다.
        pop.addEventListener('beforetoggle', function (e) {
            if (e.newState === 'open') {
                TL.place(pop, anchor, cur());
                ro.observe(anchor);
                window.addEventListener('resize', re);
                document.addEventListener('scroll', re, true);
            } else {
                ro.disconnect();
                window.removeEventListener('resize', re);
                document.removeEventListener('scroll', re, true);
            }
        });
        pop.addEventListener('toggle', function (e) { if (e.newState === 'open') TL.changed(); });
        return re;
    };

    TL.show = function (pop) { if (!pop.matches(':popover-open')) pop.showPopover(); };
    TL.hide = function (pop) { if (pop.matches(':popover-open')) pop.hidePopover(); };

    /**
     * 모달 `<dialog>` — 정본 bindModal 조건: 바깥(막) 클릭은 **pointerdown 과 click 이 모두 창 밖**일 때만
     * 닫는다(안에서 글자를 끌다 밖에서 떼면 안 닫힌다). Esc 는 dialog 기본(cancel)으로 닫힌다.
     * 창 상자가 dialog 자신이라 막 클릭도 target 이 dialog 다 — 좌표로 가른다.
     */
    TL.bindModal = function (dlg) {
        function outside(e) {
            if (e.target !== dlg) return false;
            var r = dlg.getBoundingClientRect();
            return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
        }
        var downOut = false;
        dlg.addEventListener('pointerdown', function (e) { downOut = outside(e); });
        dlg.addEventListener('click', function (e) {
            if (downOut && outside(e)) dlg.close();
            downOut = false;
        });
    };

    /** 연다 — 포커스는 창 자신에(첫 버튼에 주면 강조 테두리·이름 풍선이 뜬다), 닫히면 브라우저가 연 버튼으로 돌린다. */
    TL.openModal = function (dlg) {
        if (!dlg.open) {
            dlg.showModal();
            if (!dlg.querySelector('[autofocus]')) { dlg.tabIndex = -1; dlg.focus(); }
        }
        TL.changed();
    };
})();
