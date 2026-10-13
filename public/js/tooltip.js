/**
 * 툴팁 — 버튼은 **아이콘만** 보이고, 이름은 마우스를 올리거나 키보드로 옮겨 왔을 때 풍선으로 띄운다.
 *
 * 프로젝트 디자인 규칙(2026-09-27 사용자 지시). 이름은 버튼 안에 그대로 있다 — 템플릿의
 * `<span>이름</span>` 은 ui.css 가 눈에만 숨기고(보조기기는 읽는다), 처음부터 아이콘만 있던 버튼은
 * `aria-label` 이 이름이다. 이 파일은 그 이름을 읽어 보여 주기만 한다.
 *
 * ⚠️ 풍선은 `body` 에 붙여 `position: fixed` 로 띄운다. 버튼 옆에 CSS `::after` 로 붙이면
 *    관리자 표처럼 `overflow: auto` 인 상자 안에서 잘리고, 삐져나온 만큼 가로 스크롤이 생긴다.
 * ⚠️ 풍선은 top layer(`popover="manual"`, 2026-10-13)라 띄울 때마다 다시 연다 — top layer 는 연 순서라
 *    그래야 열린 모달 `<dialog>`·토스트 위에 뜬다(10-11 에는 dialog 안에 옮겨 붙이는 우회를 썼다).
 * ⚠️ 손가락으로 누를 때는 띄우지 않는다 — 누르면 바로 동작하므로 풍선이 남아 화면만 가린다.
 *    단 부가 설명 ⓘ 는 누를 동작이 없으니 **탭으로 열고 다시 탭하면 닫는다**(아래 "ⓘ 탭 토글").
 *    ⓘ 는 두 가지다 — 관리자 `data-tip-tap`(이 풍선)과 백테스트 `.metric-info`(제 CSS 풍선 `.metric-tooltip`,
 *    `.is-open`). 동작은 같게 여기서 함께 다룬다.
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
            tip.setAttribute('popover', 'manual');
            document.body.appendChild(tip);
        }
        owner = el;
        tip.textContent = text;
        // 크기를 재려면 먼저 보여야 한다(popover 는 닫힌 동안 display:none).
        if (tip.matches(':popover-open')) tip.hidePopover();
        tip.showPopover();

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
        if (!tip) return;
        tip.classList.remove('is-on');
        if (tip.matches(':popover-open')) tip.hidePopover();
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

    // ── ⓘ 탭 토글(정본 tooltip.md "부가 설명", 2026-10-13 통일) ─────────────
    // 마우스는 올리면(관리자: pointerover, 백테스트: CSS :hover), 키보드는 포커스로 뜬다. 손가락은 탭으로 열고
    // **같은 ⓘ 를 다시 탭하면 닫는다**. 바깥을 누르거나 스크롤하면 닫히고, 한 번에 하나만 열린다.
    // 클릭은 부모로 새지 않는다 — 라벨 안 ⓘ 를 눌러 옆 입력칸이 포커스되거나 카드가 눌리지 않게 capture 에서 끊는다.
    var MARK = '[data-tip-tap], .metric-info';
    var openInfo = null;     // 탭으로 연 `.metric-info`
    var tapped = null;       // 누르기 직전에 이미 열려 있던 ⓘ — 이어지는 click 은 닫기로 끝낸다
    var pointer = '';        // 마지막으로 누른 포인터 종류(click 에는 없는 브라우저가 있다)

    function closeInfo() {
        if (!openInfo) return;
        openInfo.classList.remove('is-open');
        openInfo.querySelector('.metric-tooltip').style.transform = '';
        openInfo = null;
    }

    // `.metric-tooltip` 은 ⓘ 오른쪽 끝에 맞춰 왼쪽으로 펼쳐진다 — 좁은 화면 왼쪽 칸의 카드에서는 화면 밖으로
    // 나간다(390px 에서 -19px). 탭으로 열 때 화면 안으로 민다.
    function openMetricInfo(mark) {
        openInfo = mark;
        mark.classList.add('is-open');
        var t = mark.querySelector('.metric-tooltip');
        var r = t.getBoundingClientRect();
        var vw = document.documentElement.clientWidth;
        var dx = r.left < EDGE ? EDGE - r.left : (r.right > vw - EDGE ? vw - EDGE - r.right : 0);
        if (dx) t.style.transform = 'translateX(' + Math.round(dx) + 'px)';
    }

    function hideAll() { hide(); closeInfo(); }

    // 누르면 화면이 바뀌거나 버튼이 사라질 수 있다 — 어디를 누르든 먼저 거둔다.
    document.addEventListener('pointerdown', function (e) {
        pointer = e.pointerType;
        var mark = e.target.closest && e.target.closest(MARK);
        tapped = mark && (mark === owner || mark === openInfo) ? mark : null;
        hideAll();
    }, true);
    document.addEventListener('keydown', function () { pointer = ''; }, true);

    document.addEventListener('click', function (e) {
        var mark = e.target.closest && e.target.closest(MARK);
        if (!mark) return;
        e.preventDefault();
        e.stopPropagation();
        var wasOpen = tapped === mark;
        tapped = null;
        var touch = pointer === 'touch' || pointer === 'pen';
        if (!touch) {
            // 마우스·키보드는 올림·포커스가 띄운다 — 누를 때 거둔 관리자 풍선만 되살린다.
            if (mark.matches('[data-tip-tap]')) show(mark);
            return;
        }
        if (wasOpen) return;
        if (mark.matches('[data-tip-tap]')) show(mark);
        else openMetricInfo(mark);
    }, true);

    // 스크롤하면 표식만 움직인다 — 풍선을 거둔다.
    window.addEventListener('scroll', hideAll, true);
    window.addEventListener('resize', hideAll);
})();
