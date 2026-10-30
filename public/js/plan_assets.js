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
            var number = value == null ? '—' : options.decimals == null ? Math.round(value).toLocaleString('ko-KR')
                : value.toLocaleString('ko-KR', { maximumFractionDigits: options.decimals });
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
        function change(value, balance) {
            if (value == null || balance == null || balance - value <= 0) return null;
            return percentage(value / (balance - value) * 100);
        }
        function percentage(pct) {
            if (!Number.isFinite(pct)) return null;
            var rounded = Number(pct.toFixed(2)) || 0;
            var text = (rounded > 0 ? '+' : '') + rounded.toLocaleString('ko-KR', {
                minimumFractionDigits: 2, maximumFractionDigits: 2
            }) + '%';
            var node = el('span', rounded > 0 ? 'plan-assets__up' : rounded < 0 ? 'plan-assets__down' : '', text);
            node.dataset.assetMoney = text;
            return node;
        }
        function movement(row) {
            var profit = row.pnl_pct != null;
            var node = profit ? percentage(row.pnl_pct) : row.buy_cost_krw != null ? null : change(row.change, row.value);
            if (node) {
                node.dataset.assetMoney = (profit ? '매수 대비 ' : '전일 ') + node.dataset.assetMoney;
                node.textContent = node.dataset.assetMoney;
            }
            return node;
        }
        function holdingRow(row) {
            var node = el('div', 'plan-assets__holding');
            var title = el('div', 'plan-assets__holding-title');
            var holdingName = el('span', 'plan-assets__holding-name', row.name);
            holdingName.title = row.name;
            title.appendChild(holdingName);
            node.appendChild(title);

            var unit = row.quantity_unit === 'KRW' ? '원' : row.quantity_unit || (row.market === 'COIN' ? '개' : '주');
            var separator = /^[A-Z]{3}$/.test(unit) ? ' ' : '';
            var position = el('div', 'plan-assets__holding-position');
            var quantityText = row.valuation === 'fixed' ? '원화 잔액' : row.qty == null ? '수량 미확인'
                : row.qty.toLocaleString('ko-KR', { maximumFractionDigits: 8 }) + separator + unit;
            var quantity = el('span', 'plan-assets__holding-quantity', quantityText);
            if (row.qty == null) quantity.classList.add('is-missing');
            if (row.kind === 'cash' && row.qty != null && row.valuation !== 'fixed') quantity.dataset.assetMoney = quantityText;
            position.appendChild(quantity);
            if (row.unit_value_krw != null && row.valuation !== 'fixed') {
                var priceLabel = /^[A-Z]{3}$/.test(unit) ? '1 ' + unit + ' = ' : unit + '당 ';
                var price = el('span', 'plan-assets__holding-price', priceLabel);
                price.appendChild(money(row.unit_value_krw, { decimals: row.valuation === 'fx' || unit === '개' ? 6 : 2 }));
                position.appendChild(price);
            }
            node.append(money(row.value, { cls: 'plan-assets__holding-value' }), position);
            var rowChange = movement(row);
            if (rowChange) {
                rowChange.classList.add('plan-assets__holding-change');
                node.appendChild(rowChange);
            }

            var sourceLabel = row.value == null ? '시세 미확인' : row.valuation === 'input' ? '입력 평가액' : '';
            if (sourceLabel || row.quote_stale) {
                var source = el('div', 'plan-assets__holding-source');
                if (sourceLabel) source.appendChild(el('span', null, sourceLabel));
                if (row.quote_stale) source.appendChild(el('span', 'plan-assets__holding-delayed', '갱신 지연'));
                node.appendChild(source);
            }
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
            var node = el('details', 'plan-assets__account');
            node.dataset.assetKey = group.key + ':' + item.name;
            var row = el('summary', 'plan-assets__row');
            var type = housing ? 'housing' : item.type === 'saving' ? 'saving'
                : item.type === 'pension' ? 'pension' : group.key;
            row.appendChild(icon(type, 'plan-assets__mark plan-assets__mark--' + type));
            var name = el('span', 'plan-assets__name', item.displayName || (housing && item.rows.length === 1 ? item.rows[0].name : item.name));
            var meta = housing ? '차감 후 내 금액' : (item.institution || '').split(/[（(]/)[0].trim() || (item.rows.length + '개 자산');
            name.appendChild(el('small', 'plan-assets__meta', meta));
            row.appendChild(name);
            var amount = el('span', 'plan-assets__amount');
            amount.appendChild(money(item.value));
            var accountChange = movement(item);
            if (accountChange || item.pnl != null) {
                var daily = el('small');
                if (item.pnl != null) {
                    daily.appendChild(money(item.pnl, { positive: true, cls: item.pnl > 0 ? 'plan-assets__up' : item.pnl < 0 ? 'plan-assets__down' : '' }));
                    if (accountChange) accountChange.classList.add('plan-assets__account-return');
                }
                if (accountChange) daily.appendChild(accountChange);
                amount.appendChild(daily);
            }
            row.appendChild(amount);
            row.appendChild(icon('chevron', 'plan-assets__chevron'));
            node.appendChild(row);
            if (housing) {
                var calc = el('div', 'plan-assets__housing-calc');
                var gross = el('div');
                gross.append(el('span', null, item.grossLabel || item.displayName || (item.rows.length === 1 ? item.rows[0].name : '원래 금액')), money(item.gross));
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
            var totalChange = change(data.change, data.total);
            changeEl.hidden = !totalChange;
            changeEl.replaceChildren(el('span', null, '시세 변동'));
            if (totalChange) changeEl.appendChild(totalChange);
            timeEl.hidden = !data.stale;
            timeEl.textContent = data.stale ? '일부 시세 갱신 지연' : '';
            renderGroups();
            otherEl.hidden = !data.other_debt;
            otherEl.replaceChildren(el('span', null, '기타 부채'), money(-data.other_debt));
            var messages = [];
            if (data.missing) messages.push('시세 미확인 ' + data.missing + '개');
            if (data.estimated) messages.push('입력 평가액 사용 ' + data.estimated + '개');
            if (data.quantity_missing) messages.push('수량 확인 필요 ' + data.quantity_missing + '개');
            if (data.stale) messages.push('금현물 시세 갱신 지연');
            if (data.consistency && data.consistency.length) messages.push('기억과 계획의 금액·일정 확인 필요');
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
                timeEl.hidden = false;
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
        window.addEventListener('focus', function () { refresh(false); });
        return { setData: setData };
    };
})();
