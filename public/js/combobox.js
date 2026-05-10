(function () {
    'use strict';

    function init(root) {
        var hiddenInput = root.querySelector('input[type="hidden"][data-combobox-value]');
        var search = root.querySelector('[data-combobox-search]');
        var list = root.querySelector('[data-combobox-list]');
        if (!hiddenInput || !search || !list) {
            return;
        }

        var items = Array.prototype.slice.call(list.querySelectorAll('[data-combobox-item]'));
        var activeIndex = -1;

        function open() {
            root.classList.add('combobox-open');
            filter(search.value);
            scrollToActive();
        }

        function close() {
            root.classList.remove('combobox-open');
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

        list.addEventListener('mousedown', function (e) {
            var target = e.target.closest('[data-combobox-item]');
            if (target) {
                e.preventDefault();
                selectItem(target);
            }
        });

        document.addEventListener('mousedown', function (e) {
            if (!root.contains(e.target)) {
                close();
            }
        });

        search.addEventListener('blur', function () {
            setTimeout(function () {
                if (!root.contains(document.activeElement)) {
                    close();
                }
            }, 100);
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
