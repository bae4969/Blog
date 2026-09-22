/**
 * 토스트 — 안내 메시지는 **화면 아래 가운데**에 띄운다.
 *
 * 프로젝트 디자인 규칙(2026-09-22 사용자 지시). 전에는 화면마다 제각각이었다:
 * 목록은 본문 위에 `.alert` 를 끼워 넣어 레이아웃을 밀어내고, 에디터는 오른쪽 위에
 * `.notification` 을 띄우고, 관리자는 서버가 그린 `.alert` 가 표 위에 남아 있었다.
 *
 * 쓰는 법:
 *     toast('저장했습니다', 'success');
 *     toast('목록을 불러오지 못했습니다', 'error', { action: { label: '다시 시도', onClick: retry } });
 *
 * ⚠️ **로딩 표시·빈 상태는 토스트가 아니다.** "불러오는 중…", "글이 없습니다" 는 그
 *    자리를 설명하는 문구라 제자리에 둔다. 토스트는 **일어난 일을 알리는** 것 전용이다.
 * ⚠️ 전역 하나만 만든다(`window.toast`). 화면마다 따로 구현하면 또 갈라진다.
 */
(function () {
    'use strict';

    var HOST_ID = 'toastHost';
    var LIFE = { info: 3200, success: 2600, error: 5200 };

    //: 종류별 아이콘. 템플릿의 `_icons.html` 과 같은 선 두께·모서리를 쓴다.
    var PATHS = {
        info:    '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
        success: '<circle cx="12" cy="12" r="9"/><path d="m8.5 12.2 2.4 2.4 4.6-4.9"/>',
        error:   '<path d="M10.3 3.9 1.9 18a2 2 0 0 0 1.7 3h16.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/>'
                 + '<path d="M12 9v4"/><path d="M12 17h.01"/>'
    };

    function host() {
        var h = document.getElementById(HOST_ID);
        if (!h) {
            h = document.createElement('div');
            h.id = HOST_ID;
            h.className = 'c-toast-host';
            // ⚠️ `role="status"` + `aria-live="polite"` 라야 보조기기가 읽는다. 화면을
            //    가리지 않으려고 `aria-atomic` 은 끄고 새로 들어온 것만 읽게 둔다.
            h.setAttribute('role', 'status');
            h.setAttribute('aria-live', 'polite');
            document.body.appendChild(h);
        }
        return h;
    }

    function icon(type) {
        return '<svg class="c-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
             + ' stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
             + (PATHS[type] || PATHS.info) + '</svg>';
    }

    function dismiss(el) {
        if (!el || el.dataset.leaving) return;
        el.dataset.leaving = '1';
        el.classList.add('is-leaving');
        // 애니메이션이 꺼져 있을 수도 있으니 시간으로도 지운다.
        var done = function () { if (el.parentNode) el.parentNode.removeChild(el); };
        el.addEventListener('transitionend', done, { once: true });
        setTimeout(done, 400);
    }

    window.toast = function (message, type, opts) {
        if (!message) return null;
        type = PATHS[type] ? type : 'info';
        opts = opts || {};

        var h = host();
        // 같은 문구가 연달아 쌓이지 않게 — 재시도 버튼을 연타해도 한 줄만 남는다.
        Array.prototype.forEach.call(h.children, function (prev) {
            if (prev.dataset.msg === message) dismiss(prev);
        });

        var box = document.createElement('div');
        box.className = 'c-toast c-toast--' + type;
        box.dataset.msg = message;
        box.innerHTML = icon(type);

        var text = document.createElement('span');
        text.className = 'c-toast__msg';
        // ⚠️ 항상 textContent — 메시지에 서버 값이나 사용자 입력이 섞일 수 있다.
        text.textContent = message;
        box.appendChild(text);

        if (opts.action && opts.action.label) {
            var act = document.createElement('button');
            act.type = 'button';
            act.className = 'c-toast__action';
            act.textContent = opts.action.label;
            act.addEventListener('click', function () {
                dismiss(box);
                if (typeof opts.action.onClick === 'function') opts.action.onClick();
            });
            box.appendChild(act);
        }

        var close = document.createElement('button');
        close.type = 'button';
        close.className = 'c-toast__close';
        close.setAttribute('aria-label', '알림 닫기');
        close.innerHTML = '<svg class="c-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
                        + ' stroke-width="1.75" stroke-linecap="round" aria-hidden="true">'
                        + '<path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>';
        close.addEventListener('click', function () { dismiss(box); });
        box.appendChild(close);

        h.appendChild(box);
        // 들어오는 애니메이션 — 붙인 다음 프레임에 클래스를 줘야 전환이 걸린다.
        requestAnimationFrame(function () { box.classList.add('is-in'); });

        var life = opts.duration || LIFE[type];
        // 오류는 사용자가 읽고 조치해야 하므로 마우스를 올리면 사라지지 않는다.
        var timer = setTimeout(function () { dismiss(box); }, life);
        box.addEventListener('mouseenter', function () { clearTimeout(timer); });
        box.addEventListener('mouseleave', function () {
            timer = setTimeout(function () { dismiss(box); }, 1200);
        });

        return box;
    };
})();
