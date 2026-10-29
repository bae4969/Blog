/** 현재 보유 자산 패널. 인증·조회는 plan.js가 넘기며 상담 시트는 건드리지 않는다. */
(function () {
    'use strict';
    window.PlanAssets = function (root, load, changed) {
        var data = null, hidden = false, busy = false;
        var groupsEl = document.getElementById('planAssetsGroups');
        var totalEl = document.getElementById('planAssetsTotal');
        var changeEl = document.getElementById('planAssetsChange');
        var timeEl = document.getElementById('planAssetsTime');
        var otherEl = document.getElementById('planAssetsOther');
        var statusEl = document.getElementById('planAssetsStatus');
        var footEl = document.getElementById('planAssetsFoot');
        var refreshBtn = document.getElementById('planAssetsRefresh');
        var hideBtn = document.getElementById('planAssetsHide');
        var icons = document.getElementById('planAssetIcons').content;

        function el(tag, cls, text) {
            var node = document.createElement(tag);
            if (cls) node.className = cls;
            if (text != null) node.textContent = text;
            return node;
        }
        function money(value, options) {
            options = options || {};
            var node = el(options.tag || 'span', options.cls);
            var number = value == null ? '—' : Math.round(value).toLocaleString('ko-KR');
            node.dataset.assetMoney = (options.positive && value > 0 ? '+' : '') + number
                + (value == null || options.unit === false ? '' : '원');
            node.textContent = hidden ? '••••••' : node.dataset.assetMoney;
            return node;
        }
        function applyPrivacy() {
            root.querySelectorAll('[data-asset-money]').forEach(function (node) {
                node.textContent = hidden ? '••••••' : node.dataset.assetMoney;
            });
            root.querySelectorAll('[data-asset-unit]').forEach(function (node) { node.hidden = hidden; });
        }
        function icon(name, cls) {
            var node = el('span', cls);
            node.appendChild(icons.querySelector('[data-icon="' + name + '"] svg').cloneNode(true));
            return node;
        }
        function change(value) {
            return money(value, { cls: value > 0 ? 'plan-assets__up' : value < 0 ? 'plan-assets__down' : '', positive: true });
        }
        function localTime(iso) {
            // 서버가 시세를 KST로 바꿔 준다. 브라우저의 현지 시간대에 다시 맞추지 않는다.
            return iso ? iso.slice(5, 16).replace('T', ' ') : '';
        }
        function holdingRow(row) {
            var node = el('div', 'plan-assets__holding');
            var name = el('span', null, row.name);
            var info = [];
            if (row.qty != null) info.push(row.qty.toLocaleString('ko-KR', { maximumFractionDigits: 8 }) + (row.market === 'COIN' ? '개' : '주'));
            if (row.code) info.push(row.code);
            if (info.length) name.appendChild(el('small', 'plan-assets__meta', info.join(' · ')));
            var value = el('span');
            value.appendChild(money(row.value));
            var source = row.quote_at ? '시세 ' + localTime(row.quote_at)
                : '입력 평가액' + (data.holdings_as_of ? ' · ' + data.holdings_as_of : '');
            if (row.value == null) source = '시세 미확인';
            value.appendChild(el('small', 'plan-assets__meta', source));
            node.append(name, value);
            return node;
        }
        function housingDisplay(item) {
            // 옛 주거 자료는 이름에 "보증금 − 은행 − 부모님", 금액에는 순액만 저장했다.
            // 저장값을 바꾸지 않고, 항목이 명시돼 있고 순액까지 일치할 때만 표시를 풀어 쓴다.
            if (item.debts.length || item.rows.length !== 1 || item.rows[0].currency !== 'KRW') return item;
            var parts = item.rows[0].name.split(/\s*[−-]\s*/);
            if (parts.length < 2) return item;
            var original = Object.assign({}, item, { grossLabel: '등록 금액' });
            var parsed = parts.map(function (part) {
                var match = /^(.*?)\s*([0-9][0-9,.]*)\s*(억|만|원)$/.exec(part.trim());
                if (!match || !match[1].trim()) return null;
                var value = Number(match[2].replace(/,/g, '')) * ({ '억': 1e8, '만': 1e4, '원': 1 }[match[3]]);
                return isFinite(value) ? { name: match[1].trim(), balance: value } : null;
            });
            if (parsed.some(function (part) { return !part; }) || item.value == null) return original;
            var debts = parsed.slice(1);
            var net = parsed[0].balance - debts.reduce(function (sum, debt) { return sum + debt.balance; }, 0);
            if (Math.abs(net - item.value) > 0.5) return original;
            return Object.assign({}, item, { displayName: parsed[0].name, gross: parsed[0].balance, debts: debts });
        }
        function account(item, group) {
            var housing = group.key === 'housing';
            if (housing) item = housingDisplay(item);
            var node = el(housing ? 'div' : 'details', 'plan-assets__account');
            node.dataset.assetKey = group.key + ':' + item.name;
            var row = el(housing ? 'div' : 'summary', 'plan-assets__row');
            var type = housing ? 'housing' : item.type === 'saving' ? 'saving'
                : item.type === 'pension' ? 'pension' : group.key;
            row.appendChild(icon(type, 'plan-assets__mark plan-assets__mark--' + type));
            var name = el('span', 'plan-assets__name', item.displayName || (housing && item.rows.length === 1 ? item.rows[0].name : item.name));
            var meta = housing ? '차감 후 내 금액' : item.institution || (item.rows.length + '개 자산');
            name.appendChild(el('small', 'plan-assets__meta', meta));
            row.appendChild(name);
            var amount = el('span', 'plan-assets__amount');
            amount.appendChild(money(item.value));
            if (item.change != null) {
                var daily = el('small');
                daily.appendChild(change(item.change));
                amount.appendChild(daily);
            }
            row.appendChild(amount);
            if (!housing) row.appendChild(icon('chevron', 'plan-assets__chevron'));
            node.appendChild(row);
            if (housing) {
                var calc = el('div', 'plan-assets__housing-calc');
                var gross = el('div');
                gross.append(el('span', null, item.grossLabel || '원래 금액'), money(item.gross));
                calc.appendChild(gross);
                item.debts.forEach(function (debt) {
                    var line = el('div');
                    line.append(el('span', null, debt.name), money(-debt.balance));
                    calc.appendChild(line);
                });
                node.appendChild(calc);
            } else {
                var rows = el('div', 'plan-assets__holdings');
                item.rows.forEach(function (holding) { rows.appendChild(holdingRow(holding)); });
                node.appendChild(rows);
            }
            return node;
        }
        function renderGroups() {
            var opened = {};
            groupsEl.querySelectorAll('details').forEach(function (node) { opened[node.dataset.assetKey] = node.open; });
            var active = document.activeElement;
            var focusKey = active && active.tagName === 'SUMMARY' ? active.parentElement.dataset.assetKey : null;
            var fragment = document.createDocumentFragment();
            data.groups.forEach(function (group) {
                var node = el('div', 'plan-assets__group');
                node.dataset.assetKey = group.key;
                var head = el('div', 'plan-assets__group-head');
                head.append(el('h3', null, group.label), el('span', 'plan-assets__count', group.items.length),
                    money(group.value, { cls: 'plan-assets__sum' }));
                node.appendChild(head);
                group.items.forEach(function (item) { node.appendChild(account(item, group)); });
                fragment.appendChild(node);
            });
            groupsEl.replaceChildren(fragment);
            groupsEl.querySelectorAll('details').forEach(function (node) {
                if (Object.prototype.hasOwnProperty.call(opened, node.dataset.assetKey)) node.open = opened[node.dataset.assetKey];
                if (node.dataset.assetKey === focusKey) node.querySelector('summary').focus({ preventScroll: true });
            });
        }
        function setData(next) {
            if (!next) return;
            // 상담·되돌리기가 먼저 끝났다면 이전 버전의 느린 자동 갱신으로 덮지 않는다.
            if (data && ((next.rev_id || 0) < (data.rev_id || 0)
                || (next.rev_id === data.rev_id && next.checked_at < data.checked_at))) return;
            data = next;
            totalEl.replaceChildren(money(data.total, { unit: false }));
            var unit = el('small', null, '원');
            unit.dataset.assetUnit = '';
            totalEl.appendChild(unit);
            changeEl.hidden = data.change == null;
            changeEl.replaceChildren(el('span', null, '시세 변동'));
            if (data.change != null) changeEl.appendChild(change(data.change));
            timeEl.textContent = '갱신 ' + localTime(data.checked_at);
            renderGroups();
            otherEl.hidden = !data.other_debt;
            otherEl.replaceChildren(el('span', null, '기타 부채'), money(-data.other_debt));
            var messages = [];
            if (data.missing) messages.push('시세 미확인 ' + data.missing + '개');
            if (data.estimated) messages.push('입력 평가액 사용 ' + data.estimated + '개');
            statusEl.hidden = !messages.length;
            statusEl.textContent = messages.join(' · ');
            var have = data.groups.some(function (g) { return g.items.length; });
            footEl.textContent = have ? '부동산은 대출을 뺀 순액이에요'
                : '등록된 자산이 없습니다. 상담에서 보유 자산을 알려주세요.';
            applyPrivacy();
        }
        function refresh(manual) {
            if (busy || (!manual && document.hidden)) return;
            busy = true;
            refreshBtn.disabled = true;
            return load().then(function (next) {
                setData(next);
                changed(next);
                if (manual) window.toast('자산 평가액을 갱신했습니다', 'success');
            }).catch(function () {
                timeEl.textContent = data ? '갱신 지연 · 마지막 평가액' : '자산을 불러오지 못했습니다';
                if (manual) window.toast('자산을 갱신하지 못했습니다', 'error');
            }).then(function () { busy = false; refreshBtn.disabled = false; });
        }
        hideBtn.addEventListener('click', function () {
            hidden = !hidden;
            hideBtn.setAttribute('aria-pressed', String(hidden));
            hideBtn.querySelector('span').textContent = hidden ? '금액 보기' : '금액 숨기기';
            applyPrivacy();
        });
        refreshBtn.addEventListener('click', function () { refresh(true); });
        setInterval(function () { refresh(false); }, 30000);
        document.addEventListener('visibilitychange', function () { if (!document.hidden) refresh(false); });
        return { setData: setData };
    };
})();
