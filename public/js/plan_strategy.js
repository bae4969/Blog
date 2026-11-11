/* 목표·결정·관찰은 날짜순 표시와 의존 관계를 분리한다. 모든 사용자 글은 textContent로 렌더한다. */
(function () {
    'use strict';
    window.PlanStrategy = function (root, api, changed) {
        var tab = 'decisions', current, opened = new Set();
        var states = {draft: '초안', selected: '선택', discarded: '폐기', confirmed: '확인 완료', superseded: '대체됨',
                      pending: '관찰 대기', observed: '관찰 완료', cancelled: '취소', reported: '실행 보고', partial: '부분 확인', corrected: '정정'};
        var actions = {observe: '관찰', hold: '유지', buy: '추가 매수', reduce: '축소', defer: '보류'};
        function el(tag, cls, text) {
            var e = document.createElement(tag);
            if (cls) e.className = cls;
            if (text != null) e.textContent = text;
            return e;
        }
        function money(value) { return value == null ? '미확인' : Number(value).toLocaleString('ko-KR') + '원'; }
        function field(parent, label, value) {
            if (value == null || value === '') return;
            var row = el('div', 'plan-strategy__field');
            row.append(el('dt', '', label), el('dd', '', value));
            parent.appendChild(row);
        }
        function details(key, title, status, open) {
            var item = el('details', 'plan-strategy__item');
            item.dataset.key = key;
            item.open = opened.has(key) || !!open;
            var heading = el('summary', 'plan-strategy__summary');
            var name = el('span', 'plan-strategy__title', title);
            name.title = title;
            heading.append(name);
            if (status) heading.append(el('small', '', states[status] || status));
            item.appendChild(heading);
            item.addEventListener('toggle', function () {
                if (!item.isConnected) return;
                if (item.open) opened.add(key); else opened.delete(key);
            });
            return item;
        }
        function button(icon, label, fn) {
            var b = el('button', 'c-btn');
            b.type = 'button';
            var source = document.querySelector('#planStrategyIcons [data-icon="' + icon + '"]');
            if (source) b.appendChild(source.firstElementChild.cloneNode(true));
            b.appendChild(el('span', '', label));
            b.addEventListener('click', function () {
                b.disabled = true;
                Promise.resolve(fn()).catch(function (err) { window.toast(err.message, 'error'); })
                    .finally(function () { b.disabled = false; });
            });
            return b;
        }
        function body(item) { var d = el('dl', 'plan-strategy__body'); item.appendChild(d); return d; }
        function scenario(parent, s, selected, review) {
            var box = details('scenario:' + s.id + ':' + parent.dataset.key, s.title, selected ? 'selected' : '', selected);
            var d = body(box);
            field(d, '대응', actions[s.action]);
            field(d, '가정', s.assumption);
            field(d, '판단 이유', s.rationale);
            field(d, '조건', s.condition || '미정');
            field(d, '확인 자료', s.condition_source);
            field(d, '조건 확인', {unknown: '미확인', met: '충족', not_met: '불충족'}[s.condition_state]);
            field(d, '계좌', s.account);
            if (s.budget) field(d, '예산', money(s.budget));
            field(d, '중단 조건', s.invalidation);
            field(d, '조건 미발생', s.fallback);
            field(d, '재검토', s.review_on);
            field(d, '근거', (s.evidence || []).join('\n'));
            Object.keys(s.shocks || {}).forEach(function (code) { field(d, code + ' 가격 가정', (s.shocks[code] * 100) + '%'); });
            if (review && review.stress_change != null) field(d, '가정에 따른 평가 변화', money(review.stress_change) + ' · 예측 아님');
            parent.appendChild(box);
        }
        function decision(d, review) {
            var item = details('decision:' + d.id, d.title, d.status);
            var fields = body(item);
            field(fields, '결정할 문제', d.question);
            field(fields, '미결 질문', (d.open_questions || []).join('\n'));
            if (review) {
                field(fields, '확인 필요', review.issues.join('\n'));
                if (review.execution_state !== 'unexecuted') field(fields, '실행', states[review.execution_state]);
            }
            d.scenarios.forEach(function (s) {
                scenario(item, s, d.selected_id === s.id, review && review.scenarios.find(function (r) { return r.id === s.id; }));
            });
            return item;
        }
        function policy(p) {
            var item = details('policy:' + p.id, p.title, p.status), d = body(item);
            field(d, '계좌', p.account);
            field(d, '기준', 'ETF 잔고 비중 · 현금 제외');
            p.targets.forEach(function (t) { field(d, t.name + ' (' + t.code + ')', (t.weight * 100).toFixed(1) + '%'); });
            field(d, '매도', p.buy_only ? '금지' : '허용');
            field(d, '보존 현금', money(p.reserve_cash));
            field(d, '확인 근거', p.evidence && p.evidence.source);
            return item;
        }
        function change(p) {
            var item = details('change:' + p.change_id, '변경안 검토', '', true);
            var list = el('ul', 'plan-strategy__changes');
            p.summary.forEach(function (s) { list.appendChild(el('li', '', s)); });
            item.appendChild(list);
            p.operations.forEach(function (op) {
                if (op.kind === 'decision_upsert') item.appendChild(decision(op.data));
                if (op.kind === 'policy_upsert') item.appendChild(policy(op.data));
            });
            var foot = el('div', 'plan-strategy__actions');
            var apply = button('check', '변경안 반영', function () {
                return api('POST', '/api/v1/plan/changes/' + p.change_id + '/apply').then(function (data) {
                    changed(data); window.toast('투자계획 변경안을 반영했습니다', 'success');
                });
            });
            if (p.base_rev !== (current.rev_id || 0)) {
                apply.disabled = true;
                item.appendChild(el('p', 'plan-strategy__warning', '계획이 변경됐습니다. 상담에서 변경안을 다시 검토해 주세요.'));
            }
            foot.append(apply, button('cancel', '변경안 폐기', function () {
                return api('POST', '/api/v1/plan/changes/' + p.change_id + '/dismiss').then(function (data) {
                    changed(data); window.toast('변경안을 폐기했습니다', 'info');
                });
            }));
            item.appendChild(foot);
            return item;
        }
        function render(data) {
            root.querySelectorAll('details[open]').forEach(function (d) { opened.add(d.dataset.key); });
            current = data;
            var s = data.doc.strategy || {goals: [], policies: [], decisions: [], observations: []};
            var changes = data.changes || [];
            root.hidden = !changes.length && !s.goals.length && !s.policies.length && !s.decisions.length && !s.observations.length && !(data.doc.execution_log || []).length;
            root.replaceChildren();
            if (root.hidden) return;
            changes.forEach(function (p) { root.appendChild(change(p)); });
            var tabs = el('div', 'plan-strategy__tabs');
            tabs.setAttribute('role', 'tablist');
            tabs.setAttribute('aria-label', '투자계획 정보');
            [['decisions', '결정·관찰'], ['policies', '목표·원칙'], ['execution', '실행 기록']].forEach(function (entry) {
                var b = el('button', '', entry[1]);
                b.type = 'button'; b.setAttribute('role', 'tab'); b.setAttribute('aria-selected', String(tab === entry[0]));
                b.addEventListener('click', function () { tab = entry[0]; render(current); root.querySelector('[aria-selected="true"]').focus(); });
                tabs.appendChild(b);
            });
            root.appendChild(tabs);
            var content = el('div', 'plan-strategy__content');
            content.setAttribute('role', 'tabpanel');
            root.appendChild(content);
            if (tab === 'decisions') {
                var review = (data.strategy_review || {}).decisions || [];
                var timeline = s.decisions.filter(function (d) { return d.status !== 'discarded'; }).map(function (d) {
                    var selected = d.scenarios.find(function (r) { return r.id === d.selected_id; });
                    return {at: selected && selected.review_on || '', node: decision(d, review.find(function (r) { return r.id === d.id; }))};
                });
                s.observations.forEach(function (o) {
                    var item = details('observation:' + o.id, o.title, o.status), fields = body(item);
                    field(fields, '관찰 시점', o.at.replace('T', ' ').slice(0, 16));
                    field(fields, '목적', o.purpose); field(fields, '확인 자료', o.source); field(fields, '관찰 결과', o.finding);
                    var linked = s.decisions.find(function (d) { return d.id === o.decision_id; });
                    field(fields, '연결된 결정', linked && linked.title);
                    timeline.push({at: o.at, node: item});
                });
                timeline.sort(function (a, b) { return a.at.localeCompare(b.at); }).forEach(function (entry) { content.appendChild(entry.node); });
            } else if (tab === 'policies') {
                s.goals.forEach(function (g) {
                    var item = details('goal:' + g.id, g.title), fields = body(item);
                    field(fields, '목적', g.purpose); field(fields, '사용 시점', g.horizon); field(fields, '필요 자금', g.amount == null ? null : money(g.amount));
                    field(fields, '보존 자금', g.reserve == null ? null : money(g.reserve));
                    field(fields, '감당 가능한 손실', g.loss_capacity == null ? null : money(g.loss_capacity));
                    field(fields, '위험 선호', g.risk_preference); field(fields, '미결 질문', g.open_questions.join('\n'));
                    content.appendChild(item);
                });
                s.policies.forEach(function (p) { content.appendChild(policy(p)); });
            } else {
                (data.doc.execution_log || []).slice().reverse().forEach(function (r) {
                    var item = details('execution:' + r.id, r.title, r.status), fields = body(item);
                    field(fields, '실행일', r.at); field(fields, '근거', r.source); field(fields, '정정 대상', r.correction_of);
                    (r.after || []).forEach(function (h) {
                        var before = (r.before || []).find(function (b) { return b.account === h.account && b.code === h.code && b.name === h.name; });
                        field(fields, h.account + ' · ' + h.name, (before && before.qty != null ? before.qty : '미확인') + ' → ' + h.qty);
                    });
                    content.appendChild(item);
                });
            }
            if (!content.children.length) content.appendChild(el('p', 'plan-empty', '기록이 없습니다.'));
        }
        root.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') { root.querySelectorAll('details[open]').forEach(function (d) { d.open = false; }); }
        });
        return {render: render};
    };
}());
