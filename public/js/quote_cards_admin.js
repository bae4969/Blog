/**
 * 주식 홈 지수·환율 카드 구성 — 관리자 지수·환율 구독 화면(`admin_quotes.html` #quoteCards, 2026-10-13).
 *
 * 세트 셋 · 6장씩 · 앞 둘은 지수 · 마지막은 환율(모바일이 그렇게 넘긴다) · 구독 중인 것만 · 겹치지 않게.
 * 서버(`app/ui/quotes.py` card_set_errors)도 같은 규칙으로 다시 본다 — 고치면 둘 다.
 *
 * 순서(정본 drag-reorder.md 정렬 표준): 손잡이(점 2×3)만 끌고(세트 안에서), 손잡이에 포커스를 두고 ↑/↓ 로
 * 한 칸씩, 주 포인터가 손가락인 기기는 ↑↓ 버튼(CSS 가 pointer: coarse 에서만 보인다). 고른 것은 [저장]으로 한 번에
 * 보낸다 — 저장 버튼으로 저장하는 편집 목록이라 디바운스는 없다. 규칙에 어긋나면 그 세트 아래에(D2),
 * 네트워크·서버 실패는 토스트로 알린다.
 */
(function () {
    'use strict';

    var root = document.getElementById('quoteCards');
    var dataEl = document.getElementById('quoteCardsData');
    if (!root || !dataEl) return;
    var data = JSON.parse(dataEl.textContent);
    var sets = data.sets.map(function (s) { return s.slice(); });
    var size = data.rules.size;
    var kinds = data.rules.kinds;
    var byCode = {};
    data.options.forEach(function (o) { byCode[o.code] = o; });

    var boxes = Array.prototype.slice.call(root.querySelectorAll('.qc-set'));
    var saveBtn = document.getElementById('quoteCardsSave');

    var SVG = {
        grip: '<circle cx="9" cy="5" r="1"/><circle cx="15" cy="5" r="1"/><circle cx="9" cy="12" r="1"/>' +
              '<circle cx="15" cy="12" r="1"/><circle cx="9" cy="19" r="1"/><circle cx="15" cy="19" r="1"/>',
        up: '<path d="m6 15 6-6 6 6"/>',
        down: '<path d="m6 9 6 6 6-6"/>',
        cancel: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>'
    };

    // 그림은 `_icons.html` 과 같다(grip·up·down·cancel).
    function icon(name) {
        return '<svg class="c-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
               'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + SVG[name] + '</svg>';
    }

    function esc(s) {
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function label(code) { return byCode[code] ? byCode[code].name : code; }

    /** 세트 번호 → 오류. 서버 `card_set_errors` 와 같은 규칙. */
    function check() {
        var errors = {};
        var seen = {};
        sets.forEach(function (codes, i) {
            if (codes.length !== size) { errors[i] = '카드를 ' + size + '장 골라야 합니다(지금 ' + codes.length + '장)'; return; }
            for (var k = 0; k < codes.length; k++) {
                var c = codes[k], o = byCode[c];
                if (!o) { errors[i] = '구독하지 않은 항목은 고를 수 없습니다: ' + c; return; }
                if (kinds[i].indexOf(o.category) < 0) {
                    errors[i] = (kinds[i].length === 1 && kinds[i][0] === 'FX' ? '이 세트는 환율만' : '이 세트는 지수만') + ' 고를 수 있습니다: ' + c;
                    return;
                }
                if (seen[c]) { errors[i] = '다른 세트에 이미 있습니다: ' + c; return; }
                seen[c] = true;
            }
        });
        return errors;
    }

    function showErrors(errors) {
        boxes.forEach(function (box, i) {
            var p = box.querySelector('.field-error');
            p.textContent = errors[i] || '';
            p.hidden = !errors[i];
        });
    }

    function render() {
        // 다시 그려도 키보드로 옮기던 손잡이·↑↓ 에 포커스를 돌려준다.
        var a = document.activeElement;
        var focusCode = a && a.closest && a.closest('.qc-item') ? a.closest('.qc-item').dataset.code : null;
        var focusRole = focusCode ? a.dataset.role : null;

        var used = {};
        sets.forEach(function (s) { s.forEach(function (c) { used[c] = true; }); });
        boxes.forEach(function (box, i) {
            var codes = sets[i];
            box.querySelector('.qc-set__count').textContent = codes.length + '/' + size;
            box.querySelector('.qc-list').innerHTML = codes.map(function (c, k) {
                var off = !byCode[c];
                return '<li class="qc-item' + (off ? ' is-off' : '') + '" data-code="' + esc(c) + '">' +
                    '<span class="qc-grip" draggable="true" tabindex="0" data-role="grip" title="끌어서 순서 변경" ' +
                    'aria-label="순서 변경 (위·아래 방향키)">' + icon('grip') + '</span>' +
                    '<span class="qc-name">' + esc(label(c)) + ' <span class="qc-code">' + esc(c) + '</span>' +
                    (off ? ' <span class="qc-off">구독 안 함</span>' : '') + '</span>' +
                    '<button type="button" class="qc-mv" data-role="up" aria-label="위로"' + (k === 0 ? ' disabled' : '') + '>' + icon('up') + '</button>' +
                    '<button type="button" class="qc-mv" data-role="down" aria-label="아래로"' + (k === codes.length - 1 ? ' disabled' : '') + '>' + icon('down') + '</button>' +
                    '<button type="button" class="qc-rm" data-role="rm" aria-label="빼기: ' + esc(label(c)) + '">' + icon('cancel') + '</button>' +
                    '</li>';
            }).join('');
            // 더 고를 수 있는 것 — 구독 중 · 이 세트 분류 · 아직 안 쓴 것.
            var add = box.querySelector('.qc-add');
            var free = data.options.filter(function (o) { return kinds[i].indexOf(o.category) >= 0 && !used[o.code]; });
            add.innerHTML = '<option value="">' + (codes.length >= size ? '6장을 다 골랐습니다' : '+ 카드 추가') + '</option>' +
                free.map(function (o) { return '<option value="' + esc(o.code) + '">' + esc(o.name) + ' (' + esc(o.code) + ')</option>'; }).join('');
            add.disabled = codes.length >= size || !free.length;
        });
        if (focusCode) {
            var li = root.querySelector('.qc-item[data-code="' + focusCode + '"]');
            var target = li && [li.querySelector('[data-role="' + focusRole + '"]'), li.querySelector('.qc-mv:not([disabled])'), li.querySelector('.qc-grip')]
                .filter(function (n) { return n && !n.disabled && n.offsetParent !== null; })[0];
            if (target) target.focus();
        }
    }

    function changed(i) {
        saveBtn.disabled = false;
        var p = boxes[i].querySelector('.field-error');
        p.textContent = '';
        p.hidden = true;
        render();
    }

    function move(i, from, to) {
        if (to < 0 || to >= sets[i].length || to === from) return;
        var c = sets[i].splice(from, 1)[0];
        sets[i].splice(to, 0, c);
        changed(i);
    }

    // ── 끌기(세트 안에서만) ─────────────────────────────────────────
    var drag = null;    // { set, li }
    var line = null;

    function computeDrop(list, y) {
        var others = Array.prototype.filter.call(list.children, function (n) { return n !== drag.li; });
        var idx = 0;
        others.forEach(function (n) {
            var b = n.getBoundingClientRect();
            if (y > b.top + b.height / 2) idx++;
        });
        if (idx === Array.prototype.indexOf.call(list.children, drag.li)) return null;   // 제자리
        return { to: idx, anchor: idx < others.length ? others[idx] : others[others.length - 1], before: idx < others.length };
    }

    function showLine(drop) {
        if (!line) { line = document.createElement('div'); line.className = 'cat-drop-line'; document.body.appendChild(line); }
        var r = drop.anchor.getBoundingClientRect();
        line.style.left = r.left + 'px';
        line.style.width = r.width + 'px';
        line.style.top = (drop.before ? r.top : r.bottom) - 1 + 'px';
        line.hidden = false;
    }

    function hideLine() { if (line) line.hidden = true; }

    boxes.forEach(function (box, i) {
        var list = box.querySelector('.qc-list');
        list.addEventListener('dragstart', function (e) {
            var grip = e.target.closest && e.target.closest('.qc-grip');
            if (!grip) return;
            drag = { set: i, li: grip.closest('li') };
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', drag.li.dataset.code);   // Firefox 는 데이터가 없으면 끌기를 시작하지 않는다
            e.dataTransfer.setDragImage(drag.li, 8, 16);
            drag.li.classList.add('is-dragging');
        });
        list.addEventListener('dragover', function (e) {
            var drop = drag && drag.set === i ? computeDrop(list, e.clientY) : null;
            if (!drop) { hideLine(); if (drag) e.dataTransfer.dropEffect = 'none'; return; }   // preventDefault 없음 → 금지 커서
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            showLine(drop);
        });
        list.addEventListener('drop', function (e) {
            var drop = drag && drag.set === i ? computeDrop(list, e.clientY) : null;
            if (!drop) return;
            e.preventDefault();
            move(i, Array.prototype.indexOf.call(list.children, drag.li), drop.to);
        });
        list.addEventListener('dragend', function () {
            if (drag && drag.li) drag.li.classList.remove('is-dragging');
            drag = null;
            hideLine();
        });
        list.addEventListener('keydown', function (e) {
            var grip = e.target.closest && e.target.closest('.qc-grip');
            if (!grip || (e.key !== 'ArrowUp' && e.key !== 'ArrowDown')) return;
            e.preventDefault();
            var k = sets[i].indexOf(grip.closest('li').dataset.code);
            move(i, k, k + (e.key === 'ArrowUp' ? -1 : 1));
        });
        list.addEventListener('click', function (e) {
            var btn = e.target.closest && e.target.closest('button');
            if (!btn) return;
            var k = sets[i].indexOf(btn.closest('li').dataset.code);
            if (btn.dataset.role === 'up') move(i, k, k - 1);
            else if (btn.dataset.role === 'down') move(i, k, k + 1);
            else if (btn.dataset.role === 'rm') { sets[i].splice(k, 1); changed(i); }
        });
        box.querySelector('.qc-add').addEventListener('change', function () {
            if (!this.value) return;
            sets[i].push(this.value);
            changed(i);
        });
    });

    saveBtn.addEventListener('click', function () {
        var errors = check();
        showErrors(errors);
        if (Object.keys(errors).length) {
            var first = boxes[+Object.keys(errors)[0]];
            first.scrollIntoView({ block: 'nearest' });
            return;
        }
        var fd = new FormData();
        fd.append('csrf_token', data.csrf);
        fd.append('sets', JSON.stringify(sets));
        saveBtn.disabled = true;
        fetch('/admin/quotes/cards', { method: 'POST', body: fd })
            .then(function (r) {
                return r.json().catch(function () { return {}; }).then(function (j) {
                    if (r.ok) { window.toast('주식 홈 카드 구성을 저장했습니다.', 'success'); return; }
                    saveBtn.disabled = false;
                    if (r.status === 400 && j.errors) { showErrors(j.errors); return; }   // 규칙 위반은 그 세트 아래에
                    throw new Error(j.detail || ('HTTP ' + r.status));
                });
            })
            .catch(function (e) {
                saveBtn.disabled = false;
                window.toast('카드 구성을 저장하지 못했습니다 — ' + e.message, 'error');
            });
    });

    render();
})();
