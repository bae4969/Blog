/**
 * 이름 인라인 편집 — 관리자 카테고리·WOL 장치(정본 inline-edit.md, 2026-10-13).
 *
 * 마크업(`.inline-name`):
 *   <input type="hidden" name="<필드>" value="이름">        ← 행의 수정 폼 안(서버에 보낼 값)
 *   <div class="inline-name" data-form="<폼 id>" data-field="<필드>">
 *     <span class="inline-name__text">이름</span>
 *     <input type="text" class="inline-input inline-name__input" maxlength="…" hidden>
 *     <button type="button" class="inline-name__pencil" aria-label="이름 바꾸기">…</button>
 *   </div>
 *
 * 연필이 기본, 이름 더블클릭이 보조. Enter·blur = 저장, Esc = 취소, 빈 이름은 저장하지 않는다.
 * 저장은 그 행의 수정 폼 경로에 `fetch`(Accept: application/json)로 보낸다 — 이름 말고 다른 칸은
 * **서버에 저장된 값**(defaultValue·defaultSelected)을 실어, 아직 [저장] 안 한 다른 칸의 변경이 딸려 가지 않게 한다.
 * 실패하면 원래 이름으로 되돌리고 오류 토스트.
 */
(function () {
    'use strict';

    // 폼의 칸을 서버에 저장된 값으로 모은다(지금 화면 값이 아니라).
    function savedData(form) {
        var fd = new FormData();
        Array.prototype.forEach.call(form.elements, function (el) {
            if (!el.name || el.disabled || el.type === 'submit' || el.type === 'button') return;
            if (el.tagName === 'SELECT') {
                var o = Array.prototype.find.call(el.options, function (o) { return o.defaultSelected; }) || el.options[0];
                if (o) fd.append(el.name, o.value);
            } else {
                fd.append(el.name, el.defaultValue);
            }
        });
        return fd;
    }

    function init(box) {
        var form = document.getElementById(box.dataset.form);
        var field = form && form.elements[box.dataset.field];
        var text = box.querySelector('.inline-name__text');
        var input = box.querySelector('.inline-name__input');
        var pencil = box.querySelector('.inline-name__pencil');
        if (!field || !text || !input || !pencil) return;
        var editing = false;

        function start() {
            if (editing) return;
            editing = true;
            input.value = text.textContent;
            text.hidden = true;
            pencil.hidden = true;
            input.hidden = false;
            input.focus();
            input.select();
        }

        // ⚠️ 입력칸을 숨기면 blur 가 따라온다 — `editing` 으로 한 번만 끝낸다.
        function end(save) {
            if (!editing) return;
            editing = false;
            var prev = text.textContent;
            var next = input.value.trim();
            input.hidden = true;
            text.hidden = false;
            pencil.hidden = false;
            if (!save || !next || next === prev) return;
            text.textContent = next;
            var fd = savedData(form);
            fd.set(field.name, next);
            fetch(form.action, { method: 'POST', body: fd, headers: { 'Accept': 'application/json' } })
                .then(function (r) {
                    return r.json().catch(function () { return {}; }).then(function (j) {
                        if (!r.ok) throw new Error(j.detail || ('HTTP ' + r.status));
                    });
                })
                .then(function () {
                    field.value = next;
                    field.defaultValue = next;
                    window.toast('이름을 바꿨습니다.', 'success');
                })
                .catch(function (e) {
                    if (text.textContent === next) text.textContent = prev;
                    window.toast('이름을 바꾸지 못했습니다 — ' + e.message, 'error');
                });
        }

        pencil.addEventListener('click', start);
        text.addEventListener('dblclick', start);
        input.addEventListener('blur', function () { end(true); });
        input.addEventListener('keydown', function (e) {
            // Enter 가 행의 수정 폼을 제출하지 않게 막는다.
            if (e.key === 'Enter') { e.preventDefault(); end(true); }
            if (e.key === 'Escape') { e.preventDefault(); end(false); }
        });
    }

    function initAll() { document.querySelectorAll('.inline-name').forEach(init); }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initAll);
    else initAll();
})();
