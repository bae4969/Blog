/**
 * 툴팁 — 버튼은 **아이콘만** 보이고, 이름은 마우스를 올리거나 키보드로 옮겨 왔을 때 풍선으로 띄운다.
 *
 * 프로젝트 디자인 규칙(2026-09-27 사용자 지시). 이름은 버튼 안에 그대로 있다 — 템플릿의
 * `<span>이름</span>` 은 ui.css 가 눈에만 숨기고(보조기기는 읽는다), 처음부터 아이콘만 있던 버튼은
 * `aria-label` 이 이름이다. 이 파일은 그 이름을 읽어 보여 주기만 한다.
 *
 * ⚠️ 풍선은 `body` 에 붙여 `position: fixed` 로 띄운다. 버튼 옆에 CSS `::after` 로 붙이면
 *    관리자 표처럼 `overflow: auto` 인 상자 안에서 잘리고, 삐져나온 만큼 가로 스크롤이 생긴다.
 * ⚠️ 손가락으로 누를 때는 띄우지 않는다 — 누르면 바로 동작하므로 풍선이 남아 화면만 가린다.
 * ⚠️ 제 풍선이 따로 있는 버튼(차트 지표 설명)은 `data-no-tip` 으로 뺀다.
 */
(function () {
    'use strict';

    //: ⚠️ ui.css 의 "버튼은 아이콘만" 선택자와 짝이다 — 한쪽만 고치면 이름을 볼 길이 없는 버튼이 생긴다.
    var TARGET = '.btn, .c-btn, .sidebar-toggle, .rotator-expand, .stock-admin-view-link,'
               + ' button[aria-label], a[aria-label]';
    var GAP = 6;     // 버튼과 풍선 사이
    var EDGE = 8;    // 화면 가장자리 여유

    var tip = null;
    var owner = null;

    function labelOf(el) {
        if (el.hasAttribute('data-no-tip') || !el.querySelector('.c-ico')) return '';
        // `innerText` 라야 `display:none` 인 글자("작성 중...")를 빼고 지금의 이름만 읽는다.
        return (el.getAttribute('aria-label') || el.innerText || '').trim();
    }

    function show(el) {
        var text = labelOf(el);
        if (!text) return;
        if (!tip) {
            tip = document.createElement('div');
            tip.className = 'c-tip';
            // 이름은 버튼이 이미 갖고 있다 — 보조기기가 두 번 읽지 않게 숨긴다.
            tip.setAttribute('aria-hidden', 'true');
            document.body.appendChild(tip);
        }
        owner = el;
        tip.textContent = text;

        var r = el.getBoundingClientRect();
        var w = tip.offsetWidth;
        var h = tip.offsetHeight;
        var x = Math.min(Math.max(r.left + r.width / 2 - w / 2, EDGE), window.innerWidth - w - EDGE);
        // 위에 자리가 없으면(상단바 버튼) 아래로 띄운다.
        var y = r.top - h - GAP >= EDGE ? r.top - h - GAP : r.bottom + GAP;
        tip.style.transform = 'translate(' + Math.round(x) + 'px, ' + Math.round(y) + 'px)';
        tip.classList.add('is-on');
    }

    function hide() {
        owner = null;
        if (tip) tip.classList.remove('is-on');
    }

    document.addEventListener('pointerover', function (e) {
        if (e.pointerType !== 'mouse') return;
        var el = e.target.closest(TARGET);
        if (el && el !== owner) show(el);
    });
    document.addEventListener('pointerout', function (e) {
        if (owner && !owner.contains(e.relatedTarget)) hide();
    });

    // 키보드로 옮겨 왔을 때만 — 손가락으로 누른 버튼에도 포커스는 가지만 `:focus-visible` 이 아니다.
    document.addEventListener('focusin', function (e) {
        var el = e.target.closest && e.target.closest(TARGET);
        if (el && el.matches(':focus-visible')) show(el);
    });
    document.addEventListener('focusout', function (e) {
        if (owner && owner.contains(e.target)) hide();
    });

    // 누르면 화면이 바뀌거나 버튼이 사라질 수 있고, 스크롤하면 버튼만 움직인다 — 풍선을 거둔다.
    document.addEventListener('pointerdown', hide, true);
    window.addEventListener('scroll', hide, true);
    window.addEventListener('resize', hide);
})();
