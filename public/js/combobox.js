(function () {
    'use strict';

    function init(root) {
        var hiddenInput = root.querySelector('input[type="hidden"][data-combobox-value]');
        var search = root.querySelector('[data-combobox-search]');
        var list = root.querySelector('[data-combobox-list]');
        // 목록 상자는 top layer(popover="manual", 2026-10-13) — 입력칸을 눌러도 닫히면 안 되는 자동완성이라 manual.
        // 자리는 콤보 아래 4px·같은 폭(옛 absolute 자리), 바깥 클릭·Esc·blur 닫기는 아래 그대로.
        var dropdown = root.querySelector('.combobox-dropdown');
        dropdown.setAttribute('popover', 'manual');
        window.TopLayer.follow(dropdown, root, { side: 'below', align: 'stretch', gap: 4 });
        // 콤보가 상단바 뒤로 스크롤돼 toplayer.js 가 목록을 닫으면 열림 표시도 맞춘다.
        dropdown.addEventListener('toggle', function (e) {
            if (e.newState === 'closed') root.classList.remove('combobox-open');
        });
        if (!hiddenInput || !search || !list) {
            return;
        }

        var items = Array.prototype.slice.call(list.querySelectorAll('[data-combobox-item]'));
        var activeIndex = -1;

        function open() {
            root.classList.add('combobox-open');
            window.TopLayer.show(dropdown);
            filter(search.value);
            scrollToActive();
        }

        function close() {
            root.classList.remove('combobox-open');
            window.TopLayer.hide(dropdown);
            activeIndex = -1;
            updateActiveClass();
        }

        function isOpen() {
            return root.classList.contains('combobox-open');
        }

        function normalize(s) {
            return (s || '').toString().toLowerCase().trim();
        }

        function filter(query) {
            var q = normalize(query);
            var anyVisible = false;
            items.forEach(function (item) {
                var value = normalize(item.getAttribute('data-value'));
                var label = normalize(item.textContent);
                var match = q === '' || value.indexOf(q) !== -1 || label.indexOf(q) !== -1;
                item.hidden = !match;
                if (match) {
                    anyVisible = true;
                }
            });
            var empty = root.querySelector('[data-combobox-empty]');
            if (empty) {
                empty.hidden = anyVisible;
            }
            activeIndex = items.findIndex(function (i) { return !i.hidden; });
            updateActiveClass();
        }

        function visibleItems() {
            return items.filter(function (i) { return !i.hidden; });
        }

        function updateActiveClass() {
            items.forEach(function (item, idx) {
                if (idx === activeIndex) {
                    item.classList.add('combobox-item-active');
                } else {
                    item.classList.remove('combobox-item-active');
                }
            });
        }

        function moveActive(delta) {
            var visible = visibleItems();
            if (visible.length === 0) {
                return;
            }
            var currentVisibleIdx = visible.indexOf(items[activeIndex]);
            if (currentVisibleIdx === -1) {
                currentVisibleIdx = 0;
            } else {
                currentVisibleIdx = (currentVisibleIdx + delta + visible.length) % visible.length;
            }
            activeIndex = items.indexOf(visible[currentVisibleIdx]);
            updateActiveClass();
            scrollToActive();
        }

        function scrollToActive() {
            if (activeIndex < 0 || !items[activeIndex]) {
                return;
            }
            var item = items[activeIndex];
            var listRect = list.getBoundingClientRect();
            var itemRect = item.getBoundingClientRect();
            if (itemRect.top < listRect.top) {
                list.scrollTop -= (listRect.top - itemRect.top);
            } else if (itemRect.bottom > listRect.bottom) {
                list.scrollTop += (itemRect.bottom - listRect.bottom);
            }
        }

        function selectItem(item) {
            if (!item) {
                return;
            }
            var value = item.getAttribute('data-value') || '';
            hiddenInput.value = value;
            search.value = value;
            close();
            search.dispatchEvent(new Event('change', { bubbles: true }));
        }

        search.addEventListener('focus', open);
        search.addEventListener('click', open);

        search.addEventListener('input', function () {
            hiddenInput.value = search.value;
            if (!isOpen()) {
                open();
            } else {
                filter(search.value);
            }
        });

        search.addEventListener('keydown', function (e) {
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                if (!isOpen()) { open(); }
                moveActive(1);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                if (!isOpen()) { open(); }
                moveActive(-1);
            } else if (e.key === 'Enter') {
                if (isOpen() && activeIndex >= 0) {
                    e.preventDefault();
                    selectItem(items[activeIndex]);
                }
            } else if (e.key === 'Escape') {
                if (isOpen()) {
                    e.preventDefault();
                    close();
                }
            }
        });

        // 목록 상자(스크롤바·빈 곳 포함)를 눌러도 포커스가 입력칸에 남게 한다.
        dropdown.addEventListener('mousedown', function (e) {
            e.preventDefault();
            var target = e.target.closest('[data-combobox-item]');
            if (target) {
                selectItem(target);
            }
        });

        document.addEventListener('pointerdown', function (e) {
            if (!root.contains(e.target)) {
                close();
            }
        });

        // 키보드(Tab)로 포커스가 다른 칸으로 옮겨 갈 때만 닫는다 — 마우스로 바깥을 누른 것은 위 pointerdown 이 닫는다.
        // ⚠️ 예전에는 blur 뒤 100ms 에 닫아 스크롤바를 누르면 닫힐 수 있었다(2026-10-13 점검).
        search.addEventListener('blur', function (e) {
            if (e.relatedTarget && !root.contains(e.relatedTarget)) {
                close();
            }
        });
    }

    function initAll() {
        document.querySelectorAll('[data-combobox]').forEach(init);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAll);
    } else {
        initAll();
    }
})();
