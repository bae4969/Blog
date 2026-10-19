/**
 * 투자 계획(`/stocks/plan`) — 2026-10-10. root 본인 전용.
 *
 * - 트리(2026-10-10 사용자 스케치): 왼쪽 세로 날짜축(아래가 미래), 날짜마다 가로 점선, 노드는 원("시작"·가지 결과).
 *   이벤트는 원이 아니라 **갈라지는 지점과 축 라벨**이다. 원·라벨은 HTML(포커스·클릭), 선만 SVG 로 그린다.
 * - 상세: 날짜 라벨이나 원을 누르면 트리 위에 떠 있는 창. 원은 자산군 파이 + 주식·채권 종목별 파이와
 *   실행 전 대비 비중 변화(%p), 이벤트는 가지별 비중 막대와 직전 비중.
 * - 상담은 모든 화면 아래의 AI 시트(`assistant.js`, 2026-10-19 떼어 냄)다. AI 가 계획을 고치면 `assistant:changed`
 *   (source "plan")가 오고 여기서 다시 그린다. 상담에 보낼 화면 맥락은 `window.assistantContext()` — 지금 연 원·라벨.
 *
 * ⚠️ 금액은 서버가 오늘 시세로 낸다(`values`). 미래 노드도 오늘 시세라 **비율**을 보라는 뜻이다.
 * ⚠️ 개인 데이터라 읽기도 Bearer 다 — 쿠키 세션에서 `/api/v1/auth/token` 으로 받는다(watchlist.js 와 같은 길).
 * ⚠️ AI 답은 글자 그대로(`textContent`) 넣는다. HTML 로 넣으면 답에 섞인 마크업이 그대로 실행된다.
 */
(function () {
    'use strict';

    var CLASS_LABEL = { stock: '주식', bond: '채권', cash: '현금', crypto: '코인', other: '기타' };
    //: 자산군 비중의 칸 — 서버가 줄마다 `group` 으로 준다(주식·채권은 국내/해외, 2026-10-11)
    var GROUPS = [['stock_kr', '국내주식'], ['stock_global', '해외주식'], ['bond_kr', '국내채권'], ['bond_global', '해외채권'],
                  ['cash', '현금'], ['crypto', '코인'], ['other', '기타']];
    var TYPES = [['cash', '현금성'], ['saving', '저축성'], ['invest', '투자성'], ['pension', '연금성'], ['housing', '주택']];
    var STATUS_LABEL = { pending: '대기', realized: '실현', dropped: '접힘' };
    //: 분류 색 — plan.css 의 `--series-N`. 순서 고정, 8번째부터는 "기타" 회색으로 접는다.
    var SERIES = 7;

    // 트리 배치(px) — 날짜축 칸 폭·축 x·원 칸 폭·줄 높이·첫 줄 y·원 반지름
    var AXIS_MAX = 168, AXIS_MIN = 96, AXIS_X = 14, SLOT_W = 136, ROW_H = 80, TOP = 40, R = 9;
    //: 날짜축 칸 폭 — 가장 긴 라벨에 맞춘다(layout). 고정 168px 이면 라벨 오른쪽에 빈 구간이 남았다(사용자 지적).
    var AXIS_W = AXIS_MAX;
    var SMALL_W = 22, SMALL_R = 5;   // 초점 밖의 작은 점 — 칸 폭, 반지름
    //: 지금 배치에서 쓰는 큰 원 칸 폭 — 칸이 좁으면 layout 이 줄인다(SLOT_W 는 넉넉할 때의 값).
    var slotW = SLOT_W;

    var treeEl = document.getElementById('planTree');
    var todoEl = document.getElementById('planTodo');
    var floatEl = document.getElementById('planFloat');
    var floatTitle = document.getElementById('planFloatTitle');
    var floatSub = document.getElementById('planFloatSub');
    var detailEl = document.getElementById('planDetail');
    var historyDlg = document.getElementById('planHistory');
    var historyList = document.getElementById('planHistoryList');
    if (!treeEl) return;

    var plan = null;          // GET /api/v1/plan 의 응답
    var selected = null;      // 상세 창에 연 원(id) — 없으면 null
    //: 좁은 화면 — 상세 창이 아래 시트가 되어 AI 상담 시트와 자리가 겹친다(그동안 상담 시트를 내린다)
    var narrow = window.matchMedia('(max-width: 63.99rem)');

    // ── API ────────────────────────────────────────────────

    var token = null, tokenExpiresAt = 0;

    function authToken() {
        if (token && Date.now() < tokenExpiresAt) return Promise.resolve(token);
        return fetch('/api/v1/auth/token', { method: 'POST' })
            .then(function (r) {
                if (!r.ok) throw new Error('로그인이 필요합니다');
                return r.json();
            })
            .then(function (j) {
                token = j.access_token;
                tokenExpiresAt = Date.now() + Math.max(0, (j.expires_in - 30)) * 1000;
                return token;
            });
    }

    function api(method, url, body) {
        return authToken().then(function (t) {
            var opt = { method: method, headers: { Authorization: 'Bearer ' + t } };
            if (body !== undefined) {
                opt.headers['Content-Type'] = 'application/json';
                opt.body = JSON.stringify(body);
            }
            return fetch(url, opt);
        }).then(function (r) {
            return r.json().catch(function () { return {}; }).then(function (j) {
                if (!r.ok) {
                    var err = new Error(typeof j.detail === 'string' ? j.detail : '요청 실패(' + r.status + ')');
                    err.status = r.status;   // 없으면 서버에 닿지 못한 것(연결 끊김) — send() 가 가른다
                    throw err;
                }
                return j;
            });
        });
    }

    // ── 도우미 ─────────────────────────────────────────────

    function el(tag, className, text) {
        var e = document.createElement(tag);
        if (className) e.className = className;
        if (text != null) e.textContent = text;
        return e;
    }

    function svg(tag, attrs) {
        var e = document.createElementNS('http://www.w3.org/2000/svg', tag);
        Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
        return e;
    }

    function won(v) {
        if (v == null) return '—';
        var a = Math.abs(v), s = v < 0 ? '-' : '';
        if (a >= 1e8) return s + (a / 1e8).toFixed(2) + '억';
        if (a >= 1e4) return s + Math.round(a / 1e4).toLocaleString('ko-KR') + '만';
        return s + Math.round(a).toLocaleString('ko-KR') + '원';
    }

    function pct(v) { return (v * 100).toFixed(1) + '%'; }

    function delta(v) {
        if (v == null) return '—';
        var p = v * 100;
        if (Math.abs(p) < 0.05) return '0.0';
        return (p > 0 ? '+' : '−') + Math.abs(p).toFixed(1);
    }

    function when(iso) {
        if (!iso) return '';
        var m = /^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d)/.exec(iso);
        return m ? m[1] + '.' + m[2] + '.' + m[3] + ' ' + m[4] + ':' + m[5] : iso;
    }

    function color(i) { return i < SERIES ? 'var(--series-' + (i + 1) + ')' : 'var(--series-other)'; }

    function nodesById() {
        var map = {};
        plan.doc.nodes.forEach(function (n) { map[n.id] = n; });
        return map;
    }

    /** 이 노드 화면의 비교 기준 — 가지는 부모 이벤트 시점(실행 전), 나머지는 없다. */
    function baseOf(id) {
        if (id === 'root') return null;
        var n = nodesById()[id];
        return n && n.kind === 'branch' ? plan.values[n.parent] : null;
    }

    /** 자산군별 합계 [{key, label, value, color}] — 값이 없는(시세 없음) 줄은 뺀다. */
    function classMix(state) {
        var sum = {};
        state.rows.forEach(function (r) { if (r.value != null) sum[r.group] = (sum[r.group] || 0) + r.value; });
        return GROUPS.map(function (g, i) {
            return { key: g[0], label: g[1], value: sum[g[0]] || 0, color: color(i) };
        });
    }

    /** 종목 색 — 문서 전체에서 처음 나온 순서로 고정한다. 노드를 옮겨 가도 같은 종목은 같은 색이다. */
    function tickerColors() {
        var order = {};
        function see(h) {
            var list = order[h.kind] || (order[h.kind] = []);
            var key = h.code || h.name;
            if (list.indexOf(key) < 0) list.push(key);
        }
        plan.doc.holdings.forEach(see);
        plan.doc.nodes.forEach(function (n) { (n.holdings || []).forEach(see); });
        return order;
    }

    function tickerMix(state, kind, order) {
        var map = {}, keys = [];
        state.rows.forEach(function (r) {
            if (r.kind !== kind) return;
            var key = r.code || r.name;
            if (!map[key]) { map[key] = { key: key, label: r.name, value: 0, qty: null, unpriced: false }; keys.push(key); }
            map[key].value += r.value || 0;
            // 수량은 수량이 있는 줄만 더한다 — 평가액으로만 넣은 줄(DC 등)이 끼면 "0" 이 아니라 아는 만큼만 보인다
            if (r.qty != null) map[key].qty = (map[key].qty || 0) + r.qty;
            if (r.value == null) map[key].unpriced = true;
        });
        var list = order[kind] || [];
        var out = [], other = null;
        keys.forEach(function (k) {
            var i = list.indexOf(k);
            if (i >= 0 && i < SERIES) {
                out.push(Object.assign(map[k], { color: color(i), order: i }));
            } else {
                other = other || { key: '__other', label: '기타', value: 0, qty: null, color: color(SERIES), order: SERIES, count: 0 };
                other.value += map[k].value;
                other.count += 1;
            }
        });
        out.sort(function (a, b) { return a.order - b.order; });
        if (other) { other.label = '기타 ' + other.count + '종목'; out.push(other); }
        return out;
    }

    /** 유형별 합계(2026-10-11, 계좌별을 대신한다) — 유형이 하나도 없는 옛 문서는 빈 배열. 주택은 문서에 순액으로 적는다. */
    function typeMix(state) {
        if (!state.rows.some(function (r) { return r.type; })) return [];
        var sum = {};
        state.rows.forEach(function (r) { if (r.value != null) { var k = r.type || ''; sum[k] = (sum[k] || 0) + r.value; } });
        var out = TYPES.map(function (t, i) { return { key: 'type:' + t[0], label: t[1], value: sum[t[0]] || 0, color: color(i) }; });
        if (sum['']) out.push({ key: 'type:', label: '유형 미지정', value: sum[''], color: color(SERIES) });
        return out;
    }

    function shareOf(list, key) {
        var total = list.reduce(function (s, x) { return s + x.value; }, 0);
        var hit = list.filter(function (x) { return x.key === key; })[0];
        return total > 0 && hit ? hit.value / total : 0;
    }

    function bar(state) {
        var b = el('div', 'plan-bar');
        var mix = classMix(state), total = mix.reduce(function (s, x) { return s + x.value; }, 0);
        if (total <= 0) return b;
        mix.forEach(function (m) {
            if (m.value <= 0) return;
            var s = el('span');
            s.style.flexGrow = String(m.value / total);
            s.style.background = m.color;
            b.appendChild(s);
        });
        b.setAttribute('aria-hidden', 'true');
        return b;
    }

    // ── 매매표·지금 할 일(2026-10-11) ───────────────────────
    //    AI 가 가지를 고른 뒤 실제로 무엇을 몇 주 사고팔지 — 서버가 직전 보유와 가지 보유를 견줘 `trades` 로 준다.

    var CHECK_SVG = '<svg class="c-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"'
                  + ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>';

    /** 계좌 · 종목 · 매매 · 수량 · 금액. 현금(평가액으로 적은 것)은 수량 없이 증가·감소. 매매가 없으면 null. */
    /** 잔고가 바뀌어 다시 짜야 하는 가지 — 서버 `stale_branches`. 매매표가 엉뚱한 매도·매수를 낼 수 있어 표 대신 경고를 보인다. */
    function isStale(id) { return (plan.stale || []).indexOf(id) >= 0; }

    function staleNote() {
        return el('p', 'plan-stale', '잔고가 바뀌어 이 가지의 매매를 다시 짜야 합니다 — 상담에서 정해 주세요');
    }

    function tradeTable(id) {
        if (isStale(id)) return staleNote();
        var list = (plan.trades || {})[id];
        if (!list || !list.length) return null;
        var wrap = el('div', 'plan-trades');
        var table = el('table', 'plan-legend');
        var head = el('tr');
        ['계좌', '종목', '매매', '수량', '금액'].forEach(function (h) { head.appendChild(el('th', null, h)); });
        var thead = el('thead'); thead.appendChild(head); table.appendChild(thead);
        var tbody = el('tbody');
        list.forEach(function (t) {
            var row = el('tr'), buy = t.side === 'buy', cash = t.qty == null;
            row.appendChild(el('td', null, t.account || '—'));
            var name = el('td', 'plan-trades__name', t.name);
            if (t.code && t.code !== t.name) name.appendChild(el('small', null, ' ' + t.code));
            row.appendChild(name);
            row.appendChild(el('td', buy ? 'q-up' : 'q-down', cash ? (buy ? '증가' : '감소') : (buy ? '매수' : '매도')));
            row.appendChild(el('td', null, cash ? '' : String(+t.qty.toFixed(4))));
            row.appendChild(el('td', null, (cash ? '' : '약 ') + won(t.value)));
            tbody.appendChild(row);
        });
        table.appendChild(tbody);
        wrap.appendChild(table);
        return wrap;
    }

    /** 조상 가지 중 접힌 것이 있으면 true — 그 경로는 더 오지 않는다(서버 `on_dropped_path` 와 같은 규칙). */
    function onDroppedPath(n) {
        var byId = nodesById();
        for (var cur = n; cur; cur = cur.parent ? byId[cur.parent] : null) {
            if (cur.kind === 'branch' && cur.status === 'dropped') return true;
        }
        return false;
    }

    /** 실현됐는데 아직 매매하지 않은 가지 — 매매표나 실행할 일이 있는 것만, 접힌 경로 아래 것은 뺀다. */
    function todoBranches() {
        return plan.doc.nodes.filter(function (n) {
            return n.kind === 'branch' && n.status === 'realized' && !n.executed_at && !onDroppedPath(n)
                && (((plan.trades || {})[n.id] || []).length || n.actions.length);
        });
    }

    function executedButton(n) {
        var b = el('button', 'c-btn');
        b.type = 'button';
        b.innerHTML = CHECK_SVG;
        b.appendChild(el('span', null, '실행함'));
        b.addEventListener('click', function (ev) {
            ev.stopPropagation();
            b.disabled = true;
            api('POST', '/api/v1/plan/nodes/' + encodeURIComponent(n.id) + '/executed').then(function (p) {
                setPlan(p);
                var opt = p.prev_rev_id ? { action: { label: '되돌리기', onClick: function () { restore(p.prev_rev_id, p.rev_id); } }, duration: 8000 } : {};
                window.toast('‘' + n.title + '’ 매매를 실행함으로 표시했습니다 — 잔고 화면을 상담에 올리면 실제 보유로 갱신합니다', 'success', opt);
            }).catch(function (e) {
                b.disabled = false;
                window.toast('표시하지 못했습니다: ' + e.message, 'error');
            });
        });
        return b;
    }

    /** 트리 위 "지금 할 일" — 가지마다 이벤트 · 가지 이름(누르면 상세), [실행함], 매매표(없으면 실행할 일). */
    function renderTodo() {
        if (!todoEl) return;
        todoEl.textContent = '';
        var list = todoBranches(), byId = nodesById();
        todoEl.hidden = !list.length;
        if (!list.length) return;
        todoEl.appendChild(el('h2', 'plan-todo__title', '지금 할 일'));
        list.forEach(function (n) {
            var item = el('div', 'plan-todo__item');
            var head = el('div', 'plan-todo__head');
            var open = el('button', 'plan-todo__name');
            open.type = 'button';
            open.appendChild(el('small', null, byId[n.parent].title + ' · ' + shortDate(byId[n.parent].at)));
            open.appendChild(el('b', null, n.title));
            open.addEventListener('click', function () { select(n.id); });
            head.appendChild(open);
            if (!isStale(n.id)) head.appendChild(executedButton(n));
            item.appendChild(head);
            var table = tradeTable(n.id);
            if (table) item.appendChild(table);
            else {
                var ul = el('ul', 'plan-sec__list');
                n.actions.forEach(function (a) { ul.appendChild(el('li', null, a)); });
                item.appendChild(ul);
            }
            todoEl.appendChild(item);
        });
    }

    // ── 트리 — 왼쪽 날짜축 + 원 ────────────────────────────

    function timeKey(iso) { return String(Date.parse(iso)); }

    /**
     * 배치. 원은 "시작"과 가지뿐이다 — 이벤트는 갈라지는 지점과 날짜축 라벨로만 나타난다.
     * 줄: 0 = 지금, 그 아래로 이벤트 시각을 날짜순으로 **균등하게**(날짜 차이에 비례하지 않는다).
     *     가지 원은 부모 이벤트의 줄에 놓인다. 다른 가지의 같은 시각 이벤트는 한 줄을 함께 쓴다.
     * 칸: 잎 원마다 한 칸, 부모 원은 자식 원들의 가운데.
     */
    //: 초점 원 — 그 원까지의 경로와 바로 아래 가지는 늘 크게, 나머지는 화면 폭이 허락하는 만큼 크게 하고 넘치면
    //: 이름 없는 작은 점(2026-10-10 사용자 결정).
    //: 원을 고르면 그 원으로 옮긴다. 상세 창을 닫아도 그대로 둔다(닫을 때마다 배치가 바뀌면 어지럽다). null = 기본 초점.
    var focusId = null;

    /** 기본 초점 — 시작에서 채택(realized) 가지를 따라 내려간 끝. 채택이 없으면 시작. */
    function defaultFocus(byId, eventsUnder, branchesOf) {
        var id = 'root';
        for (;;) {
            var next = null;
            eventsUnder[id].forEach(function (e) {
                branchesOf[e.id].forEach(function (b) { if (!next && b.status === 'realized') next = b.id; });
            });
            if (!next) return id;
            id = next;
        }
    }

    function layout() {
        var nodes = plan.doc.nodes, byId = {}, eventsUnder = { root: [] }, branchesOf = {};
        nodes.forEach(function (n) {
            byId[n.id] = n;
            if (n.kind === 'branch') eventsUnder[n.id] = [];
            else branchesOf[n.id] = [];
        });
        nodes.forEach(function (n) {
            if (n.kind === 'event') eventsUnder[n.parent || 'root'].push(n);
            else branchesOf[n.parent].push(n);
        });
        function kidsOf(id) {
            var k = [];
            eventsUnder[id].forEach(function (e) { branchesOf[e.id].forEach(function (b) { k.push(b.id); }); });
            return k;
        }

        // 크게 그릴 원 — 초점까지의 경로(조상)와 그 형제 가지 + 초점 + 초점 바로 아래 가지
        var focus = focusId && (focusId === 'root' || byId[focusId]) ? focusId : defaultFocus(byId, eventsUnder, branchesOf);
        // 경로 위 이벤트의 **다른 가지**(채택되지 않은 쪽)도 크게 — 무엇과 갈렸는지 이름이 보여야 한다(사용자 요청).
        // 그 가지들의 자식은 작은 점 그대로다.
        var big = { root: true }, path = ['root'];
        for (var id = focus; id && id !== 'root'; id = byId[byId[id].parent].parent || 'root') {
            path.push(id);
            branchesOf[byId[id].parent].forEach(function (b) { big[b.id] = true; });
        }
        big[focus] = true;
        kidsOf(focus).forEach(function (k) { big[k] = true; });
        // 경로에 걸린 **결과 대기** 이벤트의 가지도 늘 크게 — 다음에 내릴 결정이다. (지난 이벤트를 나중에 따로 붙이면
        // 기본 초점이 그쪽 채택 가지로 가서, 시작 아래 걸린 다가올 이벤트 가지가 작은 점으로만 보였다 — 처음부터 검증 2026-10-11)
        path.forEach(function (pid) {
            eventsUnder[pid].forEach(function (e) {
                if (e.status === 'pending') branchesOf[e.id].forEach(function (b) { big[b.id] = true; });
            });
        });

        var rows = [{ key: 'root', at: null, events: [] }], rowOf = {};
        nodes.filter(function (n) { return n.kind === 'event'; })
            .sort(function (a, b) { return Date.parse(a.at) - Date.parse(b.at); })
            .forEach(function (e) {
                var k = timeKey(e.at);
                if (rowOf[k] == null) { rowOf[k] = rows.length; rows.push({ key: k, at: e.at, events: [] }); }
                rows[rowOf[k]].events.push(e);
            });

        // 줄별 윤곽으로 붙이는 나무 배치(Reingold–Tilford 식) — 형제 가지는 **실제로 원이 있는 줄에서만** 겹치지 않게
        // 붙인다. 자식 없는 가지(지난 접힌 가지 등)가 그 아래 모든 줄의 폭을 잡아먹지 않아, 깊은 가지가 그 아래 빈 공간을
        // 쓴다(전에는 원마다 폭을 통째로 잡아 칸에 빈 폭이 남는데도 먼 단계 점들이 겹쳤다 — 사용자 지적 "너무 컴팩트").
        // 원 폭: 큰 원 slotW, 작은 점 dotW. 결과: 원마다 뿌리 기준 상대 x, 전체 폭.
        function rowOfNode(id) { return id === 'root' ? 0 : rowOf[timeKey(byId[byId[id].parent].at)]; }
        function lay(id) {
            var half = (big[id] ? slotW : dotW) / 2, rel = {}, contour = {}, r0 = rowOfNode(id);
            rel[id] = 0;
            contour[r0] = [-half, half];
            var acc = null, xs = [];
            eventsUnder[id].forEach(function (e) {
                var sub = layEvent(e, r0), off = xs.length ? xs[xs.length - 1] + dotW : 0;
                if (acc) {
                    Object.keys(sub.contour).forEach(function (r) {
                        if (acc[r]) off = Math.max(off, acc[r][1] - sub.contour[r][0]);
                    });
                }
                Object.keys(sub.rel).forEach(function (n) { rel[n] = sub.rel[n] + off; });
                acc = mergeContour(acc, sub.contour, off);
                xs.push(off);
            });
            if (xs.length) {
                var mid = (xs[0] + xs[xs.length - 1]) / 2;   // 부모는 이벤트 묶음들의 가운데 위
                Object.keys(rel).forEach(function (n) { if (n !== id) rel[n] -= mid; });
                contour = mergeContour(contour, acc, -mid);
            }
            return { rel: rel, contour: contour };
        }
        /** 이벤트 하나 — 그 가지들을 나란히 붙이고 가운데를 0 으로. 키 `ev:<id>` 가 갈래 줄기의 x 다. */
        function layEvent(e, r0) {
            var rE = rowOf[timeKey(e.at)], rel = {}, acc = {}, xs = [];
            branchesOf[e.id].forEach(function (b) {
                var sub = lay(b.id), off = xs.length ? xs[xs.length - 1] + dotW : 0;
                Object.keys(sub.contour).forEach(function (r) {
                    if (acc[r]) off = Math.max(off, acc[r][1] - sub.contour[r][0]);
                });
                Object.keys(sub.rel).forEach(function (n) { rel[n] = sub.rel[n] + off; });
                acc = mergeContour(acc, sub.contour, off);
                xs.push(off);
            });
            var mid = xs.length ? (xs[0] + xs[xs.length - 1]) / 2 : 0;
            Object.keys(rel).forEach(function (n) { rel[n] -= mid; });
            rel['ev:' + e.id] = 0;
            // 여러 줄을 건너뛰는 갈래(부모 줄과 이벤트 줄 사이에 다른 줄이 있다)는 그 사이 줄에 **줄기 자리**를 잡는다 —
            // 안 잡으면 다른 가지의 원이 줄기 위에 놓여 선이 그 원을 뚫고 지나갔다(시작 → 2028 청년도약 만기, 2026-10-11 사용자 지적).
            var contour = mergeContour({}, acc, -mid), t = dotW / 2;
            for (var r = r0 + 1; r < (xs.length ? rE : rE + 1); r++) contour = mergeContour(contour, (function () { var o = {}; o[r] = [-t, t]; return o; })(), 0);
            return { rel: rel, contour: contour };
        }
        /** 윤곽 합치기 — `into` 의 줄마다 `c` 를 `off` 만큼 옮겨 넓힌다. */
        function mergeContour(into, c, off) {
            into = into || {};
            Object.keys(c).forEach(function (r) {
                var v = [c[r][0] + off, c[r][1] + off];
                into[r] = into[r] ? [Math.min(into[r][0], v[0]), Math.max(into[r][1], v[1])] : v;
            });
            return into;
        }
        var tree;
        function measure() {
            tree = lay('root');
            var lo = Infinity, hi = -Infinity;
            Object.keys(tree.contour).forEach(function (r) { lo = Math.min(lo, tree.contour[r][0]); hi = Math.max(hi, tree.contour[r][1]); });
            tree.lo = lo;
            return (tree.width = hi - lo);
        }
        AXIS_W = axisWidth(rows);
        var budget = Math.max(0, treeEl.clientWidth - AXIS_W - 16), dotW = SMALL_W;
        // 필수(초점 경로와 그 형제 + 초점 아래 가지)만으로도 칸을 넘으면 줄여서 맞춘다 — 작은 점 간격부터, 그래도 넘으면 큰 원 칸까지.
        var FITS = [[SLOT_W, SMALL_W], [SLOT_W, 16], [SLOT_W, 12], [SLOT_W, 8], [120, 8], [104, 8], [96, 6], [88, 6]];
        for (var f = 0; f < FITS.length; f++) {
            slotW = FITS[f][0];
            dotW = FITS[f][1];
            if (measure() <= budget) break;
        }

        // 화면 폭에 맞춰 자세히(사용자 결정 2026-10-10) — 초점 경로 다음으로, 이미 큰 원 아래의 형제 묶음을 얕은 것부터
        // (접힌 가지 쪽은 마지막에) 크게 바꿔 보고, 트리 폭이 칸 폭을 넘으면 그 묶음은 작은 점으로 되돌린다.
        // 넓은 화면은 거의 다 크게, 좁은 화면은 초점 주변만 크게 — 창 크기가 바뀌면 다시 맞춘다(아래 resize).
        var depth = { root: 0 }, gone = {};
        (function walk(id, d, dropped) {
            depth[id] = d;
            kidsOf(id).forEach(function (k) {
                var isGone = dropped || byId[k].status === 'dropped';
                if (isGone) gone[k] = true;
                walk(k, d + 1, isGone);
            });
        })('root', 0, false);
        var tried = {};
        for (;;) {
            // 앞으로 볼 가지(접히지 않은 것) 묶음이 먼저, 그 안에서는 얕은 것부터. 접힌 가지 묶음은 마지막에.
            // ⚠️ 이미 큰 원인 형제(채택 가지)는 빼고, 이번에 키울 원들만 본다 — 같이 보면 지난 접힌 가지가 먼저 커졌다.
            var allGone = function (id) { return kidsOf(id).filter(function (k) { return !big[k]; }).every(function (k) { return gone[k]; }); };
            var groups = Object.keys(big).filter(function (id) {
                return !tried[id] && kidsOf(id).some(function (k) { return !big[k]; });
            }).sort(function (a, b) { return (allGone(a) - allGone(b)) || (depth[a] - depth[b]); });
            if (!groups.length) break;
            var parent = groups[0], add = kidsOf(parent).filter(function (k) { return !big[k]; });
            tried[parent] = true;
            add.forEach(function (k) { big[k] = true; });
            if (measure() > budget) add.forEach(function (k) { delete big[k]; });
        }
        measure();

        // 트리가 칸보다 좁으면 남는 폭의 가운데에 — 캔버스는 칸 폭만큼 잡아 회색 띠·점선이 오른쪽 끝까지 가게 한다.
        var full = Math.max(AXIS_W + tree.width + 16, treeEl.clientWidth);
        var originX = AXIS_W + (full - (AXIS_W + tree.width + 16)) / 2 - tree.lo;
        var pos = {};
        (function setPos(id, dropped) {
            var n = byId[id], isDropped = dropped || !!(n && n.status === 'dropped');
            // dotW 가 점보다 좁으면 아주 작은 점으로 — 겹쳐도 깨진 고리처럼 보이지 않게
            pos[id] = { x: originX + tree.rel[id], row: rowOfNode(id), dropped: isDropped, big: !!big[id], tiny: !big[id] && dotW < SMALL_W,
                        size: Math.max(8, Math.min(SMALL_W, dotW)) };   // 작은 점 버튼 크기 — 간격보다 크면 옆 점과 겹친다
            kidsOf(id).forEach(function (k) { setPos(k, isDropped); });
        })('root', false);

        var evX = {};   // 이벤트 갈래 줄기의 x — 여러 줄을 건너뛰는 갈래는 부모 밑에서 여기로 옮겨 와 내려간다
        Object.keys(tree.rel).forEach(function (k) { if (k.indexOf('ev:') === 0) evX[k.slice(3)] = originX + tree.rel[k]; });

        // 줄 높이는 모두 같다(ROW_H) — 줄마다 다르게 했더니 세대 간격이 들쭉날쭉해 보였다(사용자 지적).
        // rowBig 은 지난 구간 띠의 아래 끝을 정할 때만 쓴다(큰 원 줄이면 이름 밑까지).
        var rowBig = rows.map(function () { return false; });
        Object.keys(pos).forEach(function (k) { if (pos[k].big) rowBig[pos[k].row] = true; });
        var rowY = rows.map(function (_, r) { return TOP + r * ROW_H; });
        return { byId: byId, rows: rows, rowOf: rowOf, pos: pos, evX: evX, eventsUnder: eventsUnder, branchesOf: branchesOf,
                 rowY: rowY, rowBig: rowBig, focus: focus, width: full,
                 height: rowY[rows.length - 1] + ROW_H + 8 };
    }

    //: 라벨 글자 폭을 재는 캔버스 — 라벨을 그리기 전에 날짜축 칸 폭을 정해야 해서(트리 배치가 그 폭에서 시작한다).
    var measureCtx = document.createElement('canvas').getContext('2d');

    /** 날짜축 칸 폭 = 가장 긴 라벨(날짜 또는 이벤트 이름 알약) + 앞뒤 여백. AXIS_MIN~AXIS_MAX 사이로. */
    function axisWidth(rows) {
        var family = getComputedStyle(document.body).fontFamily, widest = 0;
        function w(text, font) { measureCtx.font = font + ' ' + family; return measureCtx.measureText(text).width; }
        rows.forEach(function (row) {
            if (!row.at) {
                widest = Math.max(widest, w('시작', '700 13px'), w(asOfLabel(), '400 11px'));
                return;
            }
            widest = Math.max(widest, w(shortDate(row.at), '700 13px'));
            var titles = [];
            row.events.forEach(function (e) { if (titles.indexOf(e.title) < 0) titles.push(e.title); });
            (titles.length > 2 ? ['이벤트 ' + titles.length + '개'] : titles).forEach(function (t) {
                widest = Math.max(widest, w(t, '400 12px') + 18);   // 알약 안쪽 여백(0.5rem×2) + 테두리
            });
        });
        return Math.round(Math.min(AXIS_MAX, Math.max(AXIS_MIN, AXIS_X + 12 + widest + 14)));
    }

    var curRowY = [TOP];   // 지금 배치의 줄 y(layout 이 정한다)
    function px(p) { return { x: p.x, y: curRowY[p.row] }; }

    function shortDate(iso) {
        var d = new Date(iso);
        var two = function (v) { return (v < 10 ? '0' : '') + v; };
        // 브라우저 시각대가 아니라 KST 로 읽는다 — 서버가 +09:00 으로 준다.
        var k = new Date(d.getTime() + 9 * 3600 * 1000);
        // YY.MM.DD — 시각은 보이지 않는다(사용자: 시간 단위로 관리하지 않는다, 2026-10-11)
        return two(k.getUTCFullYear() % 100) + '.' + two(k.getUTCMonth() + 1) + '.' + two(k.getUTCDate());
    }

    /** 보유 기준일 'YYYY-MM-DD' → 'YY.MM.DD'(날짜축 표기와 같게). */
    function asOfLabel() { return plan.doc.as_of ? plan.doc.as_of.slice(2).replace(/-/g, '.') : ''; }

    function renderTree() {
        var L = layout(), canvas = el('div', 'plan-tree__canvas');
        curRowY = L.rowY;
        canvas.style.inlineSize = L.width + 'px';
        canvas.style.blockSize = L.height + 'px';
        // 날짜축 칸 — 가로로 스크롤해도 왼쪽에 붙어 있다(sticky). 줄마다 점과 라벨.
        // 세로선은 CSS(`.plan-axis-col::before`)가 그린다 — 칸 맨 아래까지 늘 내려가야 해서다.
        var axis = el('div', 'plan-axis-col');
        axis.style.inlineSize = AXIS_W + 'px';
        var ag = svg('svg', { width: AXIS_W, height: L.height, 'aria-hidden': 'true' });
        axis.appendChild(ag);
        canvas.appendChild(axis);

        // 트리 선 — 줄마다 가로 점선, 갈래
        var g = svg('svg', { class: 'plan-tree__lines', width: L.width, height: L.height, 'aria-hidden': 'true' });
        canvas.appendChild(g);
        // 지난 구간(아래 띠)을 정하려고 마지막으로 날짜가 지난 줄을 찾는다 — 줄은 날짜순이라 지난 줄은 늘 위쪽에 이어 있다.
        var now = Date.now(), lastPast = -1;
        L.rows.forEach(function (row, i) { if (row.at && Date.parse(row.at) <= now) lastPast = i; });
        L.rows.forEach(function (row, i) {
            var y = L.rowY[i];
            g.appendChild(svg('path', { class: 'plan-guide', d: 'M' + AXIS_W + ',' + y + ' H' + L.width }));
            ag.appendChild(svg('path', { class: 'plan-guide', d: 'M' + (AXIS_X + 8) + ',' + y + ' H' + AXIS_W }));
            ag.appendChild(svg('circle', { class: 'plan-axis__dot', cx: AXIS_X, cy: y, r: 4 }));
            var label = axisLabel(row, y);
            if (i > 0 && i <= lastPast) label.classList.add('is-past');
            axis.appendChild(label);
        });

        Object.keys(L.pos).forEach(function (id) { canvas.appendChild(dotEl(id, L.byId[id], L.pos[id])); });

        var first = !treeEl.querySelector('.plan-tree__canvas'), keep = treeEl.scrollLeft;
        treeEl.textContent = '';
        treeEl.appendChild(canvas);

        // 원 아래 이름·금액·막대 묶음의 실제 높이 — 갈래 선은 그 밑에서 시작한다(글꼴에 따라 달라 어림값을 쓰지 않는다).
        // 원 버튼은 원 중심보다 14px 위에서 시작한다(dotEl).
        var labelH = canvas.querySelector('.plan-dot:not(.plan-dot--small)').offsetHeight - 14 + 4;

        // 지난 구간 — 맨 위("시작")부터 마지막으로 지난 줄의 원 아래 묶음까지 회색 띠로 덮는다(사용자 요청).
        // ⚠️ 반투명 층 하나를 날짜축 칸 **위로** 얹는다 — 축 칸 배경 밑에 따로 깔면 두 번 겹쳐 경계가 생겼다.
        if (lastPast > 0) {
            var band = el('div', 'plan-past');
            band.style.width = L.width + 'px';
            band.style.height = (L.rowY[lastPast] + (L.rowBig[lastPast] ? labelH : SMALL_R + 4) + 6) + 'px';
            canvas.appendChild(band);
        }

        // 갈래 — 부모 원에서 곧장 내려와 이벤트 줄 위에서 갈라진다
        plan.doc.nodes.forEach(function (n) {
            if (n.kind !== 'event') return;
            var row = L.rowOf[timeKey(n.at)], pp = L.pos[n.parent || 'root'], p = px(pp), rowY = L.rowY[row];
            var gap = rowY - L.rowY[row - 1];
            // 큰 원은 그 아래 이름·금액·막대 밑에서, 작은 점은 점 바로 밑에서 내려온다
            var start = p.y + (pp.big ? labelH : SMALL_R + 2), fork = Math.max(start + 6, rowY - gap * 0.45);
            // 여러 줄을 건너뛰는 갈래 — 부모 바로 밑에서 줄기 자리(evX, 배치가 비워 둔 곳)로 옮겨 가 그 줄기로 내려온다
            var sx = p.x, head = 'M' + p.x + ',' + start;
            if (row - pp.row > 1) {
                // 꺾는 곡선은 바로 아랫줄로 가는 갈래와 **같은 높이·같은 꼴**로 — 따로 잡았더니 옆 가지 선을 가로지르고 원 위를 스쳤다
                var g1 = L.rowY[pp.row + 1] - L.rowY[pp.row], f1 = Math.max(start + 6, L.rowY[pp.row + 1] - g1 * 0.45);
                var d1 = (L.rowY[pp.row + 1] - R - f1) * 0.5;
                sx = L.evX[n.id];
                head += ' V' + f1 + ' C' + p.x + ',' + (f1 + d1) + ' ' + sx + ',' + f1 + ' ' + sx + ',' + (f1 + d1);
            }
            var kids = L.branchesOf[n.id];
            if (!kids.length) {
                // 가지가 아직 없는 이벤트 — 줄까지 내려와 빈 점으로 끝낸다
                g.appendChild(svg('path', { class: 'plan-edge is-pending', d: head + ' V' + (rowY - 5) }));
                g.appendChild(svg('circle', { class: 'plan-edge__end', cx: sx, cy: rowY, r: 4 }));
                return;
            }
            kids.forEach(function (b) {
                var cp = L.pos[b.id], c = px(cp), r = cp.big ? R : SMALL_R, d = (c.y - r - fork) * 0.5;
                var path = svg('path', { class: 'plan-edge' + (cp.big ? '' : ' is-small'), d: head + ' V' + fork
                    + ' C' + sx + ',' + (fork + d) + ' ' + c.x + ',' + fork + ' ' + c.x + ',' + (fork + d) + ' V' + (c.y - r) });
                if (L.pos[b.id].dropped) path.classList.add('is-dropped');
                else if (b.status === 'realized') path.classList.add('is-realized');
                g.appendChild(path);
            });
        });

        if (!plan.doc.nodes.length) {
            treeEl.appendChild(el('p', 'plan-empty',
                plan.doc.holdings.length
                    ? '아직 이벤트가 없습니다. 오른쪽 상담에서 다가오는 이벤트와 대응 전략을 이야기해 보세요.'
                    : '보유 자산이 없습니다. 증권사·은행 화면 이미지를 첨부하거나 보유 내역을 적어 보내 주세요.'));
        }
        // 다시 그릴 때(계획이 바뀜)는 보던 자리를 지킨다. 처음 열 때는 초점 원(채택 경로의 끝)을 가로 가운데로.
        var fd = canvas.querySelector('.plan-dot[data-id="' + L.focus + '"]');
        treeEl.scrollLeft = first && fd ? Math.max(0, fd.offsetLeft + fd.offsetWidth / 2 - (AXIS_W + (treeEl.clientWidth - AXIS_W) / 2)) : keep;
    }

    function axisLabel(row, y) {
        var box = el('div', 'plan-axis__label');
        box.style.top = (y - 9) + 'px';
        box.style.left = (AXIS_X + 12) + 'px';
        box.style.width = (AXIS_W - AXIS_X - 24) + 'px';
        if (!row.at) {
            box.appendChild(el('span', 'plan-axis__date', '시작'));
            box.appendChild(el('span', 'plan-axis__sub', asOfLabel()));
            return box;
        }
        box.appendChild(el('span', 'plan-axis__date', shortDate(row.at)));
        var titles = [];
        row.events.forEach(function (e) { if (titles.indexOf(e.title) < 0) titles.push(e.title); });
        // 같은 시각의 이벤트 이름이 셋 이상이면 하나로 묶는다 — 다 늘어놓으면 아래 줄까지 넘쳤다(깊이 시험에서 27개).
        // 누르면 상세 창에 그 시각의 이벤트 목록이 뜬다.
        (titles.length > 2 ? [null] : titles).forEach(function (title) {
            var b = el('button', 'plan-axis__ev', title == null ? '이벤트 ' + titles.length + '개' : title);
            b.type = 'button';
            b.dataset.row = row.key;
            b.dataset.title = title || '';
            b.addEventListener('click', function () { openEvent(row.key, title); });
            box.appendChild(b);
        });
        return box;
    }

    function dotEl(id, n, p) {
        var c = px(p), b = el('button', 'plan-dot' + (n ? '' : ' plan-dot--root'));
        b.type = 'button';
        b.dataset.id = id;
        if (!p.big) {
            // 초점 밖 — 이름 없는 작은 점. 올리면 이름(title), 누르면 그쪽이 초점이 된다.
            b.classList.add('plan-dot--small');
            if (p.tiny) b.classList.add('is-tiny');
            b.style.left = (c.x - p.size / 2) + 'px';
            b.style.top = (c.y - p.size / 2) + 'px';
            b.style.width = b.style.height = p.size + 'px';
            if (p.dropped) b.classList.add('is-dropped');
            else if (n.status === 'realized') b.classList.add('is-realized');
            if (id === selected) b.classList.add('is-selected');
            b.appendChild(el('span', 'plan-dot__ring'));
            b.title = n.title;
            b.setAttribute('aria-label', n.title);
            b.addEventListener('click', function () { select(id); });
            return b;
        }
        b.style.left = (c.x - slotW / 2 + 6) + 'px';
        b.style.top = (c.y - 14) + 'px';
        b.style.width = (slotW - 12) + 'px';
        if (p.dropped) b.classList.add('is-dropped');
        else if (n && n.status === 'realized') b.classList.add('is-realized');
        if (id === selected) b.classList.add('is-selected');
        var name = n ? n.title : '시작';
        // 원 아래는 이름만 — 금액·비중 막대는 걷었다(가지끼리 거의 같아 정보가 안 됐다, 사용자 결정). 상세 창에서 본다.
        b.appendChild(el('span', 'plan-dot__ring'));
        b.appendChild(el('span', 'plan-dot__title', name));
        // 줄여 보이는 이름 전체 — `.c-ico` 가 없어 tooltip.js 풍선과 겹치지 않는다.
        b.title = name;
        b.addEventListener('click', function () { select(id); });
        return b;
    }

    function mark() {
        Array.prototype.forEach.call(treeEl.querySelectorAll('.plan-dot'), function (b) {
            b.classList.toggle('is-selected', b.dataset.id === selected);
        });
        Array.prototype.forEach.call(treeEl.querySelectorAll('.plan-axis__ev'), function (b) {
            b.classList.toggle('is-selected', !!openedEvent && b.dataset.row === openedEvent.row && b.dataset.title === (openedEvent.title || ''));
        });
    }

    var dragMoved = false;    // 방금 끌어 옮겼다 — 이어지는 click 은 상세 창 닫기로 치지 않는다

    // 트리 빈 곳을 끌어 옮긴다 — 스크롤바를 숨겨서 마우스로는 가로로 옮길 길이 이것뿐이다.
    // 원·라벨(버튼) 위에서 시작한 끌기는 무시한다(누르기가 먼저다). 터치는 브라우저 스크롤에 맡긴다.
    (function () {
        var drag = null;
        treeEl.addEventListener('pointerdown', function (e) {
            if (e.pointerType !== 'mouse' || e.button !== 0 || e.target.closest('button')) return;
            dragMoved = false;
            drag = { x: e.clientX, y: e.clientY, left: treeEl.scrollLeft, top: treeEl.scrollTop };
            treeEl.setPointerCapture(e.pointerId);
            treeEl.classList.add('is-dragging');
        });
        treeEl.addEventListener('pointermove', function (e) {
            if (!drag) return;
            if (Math.abs(e.clientX - drag.x) + Math.abs(e.clientY - drag.y) > 4) dragMoved = true;
            treeEl.scrollLeft = drag.left - (e.clientX - drag.x);
            treeEl.scrollTop = drag.top - (e.clientY - drag.y);
        });
        function end() { drag = null; treeEl.classList.remove('is-dragging'); }
        treeEl.addEventListener('pointerup', end);
        treeEl.addEventListener('pointercancel', end);
    })();

    /**
     * 상자 위의 휠은 창(페이지)을 움직이지 않고 그 상자 것만 움직인다(사용자 요청 — 트리·상담·상세 창).
     * `pick(e)` 가 움직일 요소를 고른다.
     * ⚠️ preventDefault 를 쓰려면 passive: false 여야 한다. 확대·축소(ctrl+휠, 핀치)는 브라우저에 맡긴다.
     */
    function trapWheel(box, pick) {
        box.addEventListener('wheel', function (e) {
            if (e.ctrlKey) return;
            e.preventDefault();
            var el = pick(e), unit = e.deltaMode === 1 ? 16 : 1;   // 줄 단위로 오는 장치(Firefox 마우스)
            // 휠은 위아래, shift+휠은 좌우(사용자 지정). 가로 막대는 숨겼다 — 트랙패드 좌우·끌기로도 옮긴다.
            // ⚠️ shift+휠의 양이 deltaY 로 오는 브라우저(Firefox)와 deltaX 로 오는 브라우저(Chrome)가 있다.
            if (e.shiftKey) {
                el.scrollLeft += (e.deltaX || e.deltaY) * unit;
            } else {
                el.scrollTop += e.deltaY * unit;
                el.scrollLeft += e.deltaX * unit;
            }
        }, { passive: false });
    }

    trapWheel(treeEl, function () { return treeEl; });

    // ── 떠 있는 상세 창 ─────────────────────────────────────

    var openedEvent = null;   // {row, title} — 날짜 라벨로 연 이벤트 상세

    function showFloat(title, sub) {
        floatTitle.textContent = title;
        floatSub.textContent = sub;
        detailEl.textContent = '';
        floatEl.hidden = false;
        floatEl.scrollTop = 0;
        askedAbout = {};
        if (window.assistant && narrow.matches) window.assistant.away(true);
    }

    function closeFloat() {
        floatEl.hidden = true;
        if (window.assistant) window.assistant.away(false);
        selected = null;
        openedEvent = null;
        mark();
    }

    /** 초점을 옮기고 다시 배치한다. `anchor` 원이 화면의 같은 자리에 머물게 스크롤을 맞춘다(배치가 바뀌어 멀리 밀리지 않게). */
    function refocus(id, anchor) {
        if (focusId === id) return false;
        var sel = '.plan-dot[data-id="' + anchor + '"]', d = treeEl.querySelector(sel);
        var x0 = d ? d.offsetLeft + d.offsetWidth / 2 - treeEl.scrollLeft : null, y0 = d ? d.offsetTop - treeEl.scrollTop : null;
        focusId = id;
        renderTree();
        d = treeEl.querySelector(sel);
        if (d && x0 != null) {
            treeEl.scrollLeft = d.offsetLeft + d.offsetWidth / 2 - x0;
            treeEl.scrollTop = d.offsetTop - y0;
        }
        return true;
    }

    function select(id) {
        selected = id;
        openedEvent = null;
        refocus(id, id);
        mark();
        renderNode();
    }

    function openEvent(rowKey, title) {
        selected = null;
        openedEvent = { row: rowKey, title: title };
        // 이름으로 고른 이벤트면 그 가지들이 크게 보이게 — 초점을 이벤트의 부모(가지 또는 시작)로
        var ev = title != null && plan.doc.nodes.filter(function (n) {
            return n.kind === 'event' && timeKey(n.at) === rowKey && n.title === title;
        })[0];
        if (ev) refocus(ev.parent || 'root', ev.parent || 'root');
        mark();
        renderEvent();
    }

    /** 계획이 바뀌면 열린 창을 새 내용으로 — 그 노드·이벤트가 사라졌으면 닫는다. */
    function refreshFloat() {
        if (floatEl.hidden) return;
        if (openedEvent) renderEvent();
        else if (selected === 'root' || nodesById()[selected]) renderNode();
        else closeFloat();
    }

    // ── 파이 ───────────────────────────────────────────────

    var tip = null;

    function showTip(text, ev) {
        // 겉모양은 버튼 이름 풍선(`.c-tip`, ui.css)과 같다 — 자리만 마우스를 따라간다.
        if (!tip) { tip = el('div', 'c-tip is-on'); tip.setAttribute('popover', 'manual'); document.body.appendChild(tip); }
        tip.textContent = text;
        if (!tip.matches(':popover-open')) tip.showPopover();   // top layer — 크기를 재려면 먼저 띄운다
        var x = Math.min(ev.clientX + 12, window.innerWidth - tip.offsetWidth - 8);
        tip.style.left = x + 'px';
        tip.style.top = (ev.clientY + 14) + 'px';
    }

    function hideTip() { if (tip && tip.matches(':popover-open')) tip.hidePopover(); }
    // 마우스를 따라가는 풍선이라 스크롤하면 조각과 어긋난 채 남는다 — 거둔다(2026-10-13 점검).
    document.addEventListener('scroll', hideTip, true);

    function arc(cx, cy, r1, r0, a0, a1) {
        // 한 조각이 전부(100%)면 시작·끝이 같아 호가 사라진다 — 살짝 덜 그린다.
        if (a1 - a0 >= Math.PI * 2) a1 = a0 + Math.PI * 2 - 0.0001;
        var large = a1 - a0 > Math.PI ? 1 : 0;
        function pt(r, a) { return (cx + r * Math.sin(a)).toFixed(2) + ',' + (cy - r * Math.cos(a)).toFixed(2); }
        return 'M' + pt(r1, a0) + ' A' + r1 + ',' + r1 + ' 0 ' + large + ' 1 ' + pt(r1, a1)
             + ' L' + pt(r0, a1) + ' A' + r0 + ',' + r0 + ' 0 ' + large + ' 0 ' + pt(r0, a0) + ' Z';
    }

    /**
     * 파이(도넛) + 범례 겸 표. `cols` 는 표의 추가 칸 [{head, cell(item)}].
     * 색만으로 구분하지 않게 이름·비중을 표에 글자로 둔다. 조각·줄에 올리면 서로 짝이 밝아진다.
     */
    function pie(title, items, cols) {
        var wrap = el('div', 'plan-pie');
        wrap.appendChild(el('h3', null, title));
        var body = el('div', 'plan-pie__body');
        var total = items.reduce(function (s, x) { return s + x.value; }, 0);
        var g = svg('svg', { viewBox: '0 0 120 120', role: 'img', 'aria-label': title + ' 비중' });
        var table = el('table', 'plan-legend');
        var head = el('tr');
        head.appendChild(el('th', null, '이름'));
        head.appendChild(el('th', null, '비중'));
        cols.forEach(function (c) { head.appendChild(el('th', null, c.head)); });
        var thead = el('thead'); thead.appendChild(head); table.appendChild(thead);
        var tbody = el('tbody');

        var a = 0;
        items.forEach(function (it) {
            var share = total > 0 ? it.value / total : 0;
            var row = el('tr');
            var name = el('td');
            var sw = el('span', 'plan-swatch'); sw.style.background = it.color;
            name.appendChild(sw);
            name.appendChild(document.createTextNode(it.label));
            row.appendChild(name);
            row.appendChild(el('td', null, it.unpriced ? '시세 없음' : pct(share)));
            cols.forEach(function (c) { row.appendChild(el('td', null, c.cell(it))); });
            tbody.appendChild(row);
            if (share <= 0) return;
            var path = svg('path', { d: arc(60, 60, 56, 34, a, a + share * Math.PI * 2), fill: it.color });
            a += share * Math.PI * 2;
            var label = it.label + ' ' + pct(share) + ' · ' + won(it.value);
            function on(ev) { path.classList.add('is-hot'); row.classList.add('is-hot'); if (ev) showTip(label, ev); }
            function off() { path.classList.remove('is-hot'); row.classList.remove('is-hot'); hideTip(); }
            path.addEventListener('mousemove', on);
            path.addEventListener('mouseleave', off);
            row.addEventListener('mouseenter', function () { on(); });
            row.addEventListener('mouseleave', off);
            g.appendChild(path);
        });
        table.appendChild(tbody);
        var t = svg('text', { x: 60, y: 64, 'text-anchor': 'middle', class: 'plan-pie__center' });
        t.textContent = won(total);
        g.appendChild(t);
        body.appendChild(g);
        body.appendChild(table);
        wrap.appendChild(body);
        return wrap;
    }

    /** 자산군 파이 + 유형별 파이 + 주식·채권 종목별 파이. `base` 가 있으면 비중 변화(%p) 칸을 붙인다. */
    function pies(state, base) {
        var box = el('div', 'plan-pies');
        var positive = function (m) { return m.value > 0; };
        var mix = classMix(state).filter(positive);
        var baseMix = base ? classMix(base).filter(positive) : null;
        if (baseMix) {
            // 실행 전에는 있었는데 이제 없는 것도 남긴다(−비중이 보여야 한다)
            baseMix.forEach(function (bm) {
                if (!mix.some(function (m) { return m.key === bm.key; })) mix.push(Object.assign({}, bm, { value: 0 }));
            });
        }
        if (mix.length) {
            box.appendChild(pie('자산군 비중', mix, baseMix ? [{ head: '변화(%p)', cell: function (it) {
                return delta(shareOf(mix, it.key) - shareOf(baseMix, it.key));
            } }] : []));
        }
        var acc = typeMix(state).filter(positive);
        var baseAcc = base ? typeMix(base).filter(positive) : null;
        if (baseAcc) {
            baseAcc.forEach(function (ba) {
                if (!acc.some(function (a) { return a.key === ba.key; })) acc.push(Object.assign({}, ba, { value: 0 }));
            });
        }
        if (acc.length) {
            box.appendChild(pie('유형별', acc, baseAcc ? [{ head: '변화(%p)', cell: function (it) {
                return delta(shareOf(acc, it.key) - shareOf(baseAcc, it.key));
            } }] : []));
        }
        var order = tickerColors();
        ['stock', 'bond'].forEach(function (kind) {
            var items = tickerMix(state, kind, order);
            var before = base ? tickerMix(base, kind, order) : null;
            if (before) {
                before.forEach(function (b) {
                    if (b.value > 0 && !items.some(function (i) { return i.key === b.key; })) items.push(Object.assign({}, b, { value: 0, qty: 0 }));
                });
            }
            if (!items.length) return;
            var cols = [{ head: '수량', cell: function (it) { return it.qty == null ? '' : String(+it.qty.toFixed(4)); } }];
            if (before) cols.push({ head: '변화(%p)', cell: function (it) { return delta(shareOf(items, it.key) - shareOf(before, it.key)); } });
            box.appendChild(pie(CLASS_LABEL[kind] + ' 종목별', items, cols));
        });
        return box.children.length ? box : el('p', 'plan-empty', '보유 자산이 없습니다.');
    }

    // ── 상세 내용 ──────────────────────────────────────────

    /** 상세 창의 한 덩어리 — 제목 + 글(또는 요소). 글이 비면 아무것도 붙이지 않는다. */
    function section(title, body, parent) {
        if (!body || (Array.isArray(body) && !body.length)) return;
        var sec = el('section', 'plan-sec');
        sec.appendChild(el('h3', 'plan-sec__title', title));
        if (typeof body === 'string') sec.appendChild(el('p', 'plan-sec__text', body));
        else if (Array.isArray(body)) {
            var ul = el('ul', 'plan-sec__list');
            body.forEach(function (t) { ul.appendChild(el('li', null, t)); });
            sec.appendChild(ul);
        } else sec.appendChild(body);
        (parent || detailEl).appendChild(sec);
        return sec;
    }

    var FLOW_KINDS = [['income', '수입'], ['fixed', '고정 지출'], ['living', '생활비'], ['saving', '저축·납입']];

    /** 월 현금흐름 표(2026-10-11) — 종류별 합계와 수입 대비 비율, 그 아래 항목, 끝에 여유. */
    function flowTable() {
        var sum = plan.cashflow, income = sum.income;
        var table = el('table', 'plan-legend plan-flow'), tbody = el('tbody');
        function row(cls, name, amount, share) {
            var tr = el('tr', cls);
            tr.appendChild(el('td', null, name));
            tr.appendChild(el('td', null, won(amount)));
            tr.appendChild(el('td', null, share == null ? '' : pct(share)));
            tbody.appendChild(tr);
        }
        FLOW_KINDS.forEach(function (k) {
            var items = plan.doc.cashflow.filter(function (f) { return f.kind === k[0]; });
            if (!items.length) return;
            row('plan-flow__kind', k[1], sum[k[0]], k[0] === 'income' || !income ? null : sum[k[0]] / income);
            items.forEach(function (f) { row('plan-flow__item', f.name + (f.account ? ' · ' + f.account : ''), f.amount, null); });
        });
        row('plan-flow__kind', '여유', sum.surplus, income ? sum.surplus / income : null);
        table.appendChild(tbody);
        return table;
    }

    /** 계좌 표(2026-10-17) — 계좌(기관)·지금 평가·원금 대비·월 납입, 그 아래 목적. 계좌 목록이 비면(옛 문서) 없다. */
    function accountTable() {
        var list = plan.accounts || [];
        if (!list.length) return null;
        var table = el('table', 'plan-legend plan-flow plan-acc'), thead = el('thead'), hr = el('tr'), tbody = el('tbody');
        ['계좌', '평가', '원금 대비', '월 납입'].forEach(function (h) { hr.appendChild(el('th', null, h)); });
        thead.appendChild(hr);
        list.forEach(function (a) {
            var tr = el('tr'), name = el('td');
            name.appendChild(el('b', null, a.name));
            if (a.institution) name.appendChild(el('small', null, ' ' + a.institution));
            if (a.purpose || a.maturity) name.appendChild(el('span', 'plan-acc__purpose', [a.purpose, a.maturity ? '만기 ' + a.maturity : ''].filter(Boolean).join(' · ')));
            tr.appendChild(name);
            tr.appendChild(el('td', null, a.value == null ? '—' : won(a.value)));
            var p = el('td');
            if (a.pnl != null) p.appendChild(changeEl(a.pnl, a.pnl_pct));
            else p.textContent = a.debt ? '부채 ' + won(a.debt) : '';
            tr.appendChild(p);
            tr.appendChild(el('td', null, a.monthly ? won(a.monthly) : ''));
            tbody.appendChild(tr);
        });
        table.appendChild(thead);
        table.appendChild(tbody);
        return table;
    }

    /** 부채 표(2026-10-17) — 빌린 곳·잔액·연 금리·만기. 모르는 칸은 비워 둔다(AI 가 채우게). */
    function debtTable() {
        var list = plan.doc.debts || [];
        if (!list.length) return null;
        var table = el('table', 'plan-legend plan-flow plan-acc'), thead = el('thead'), hr = el('tr'), tbody = el('tbody');
        ['부채', '잔액', '금리', '만기'].forEach(function (h) { hr.appendChild(el('th', null, h)); });
        thead.appendChild(hr);
        list.forEach(function (x) {
            var tr = el('tr'), name = el('td');
            name.appendChild(el('b', null, x.name));
            if (x.lender) name.appendChild(el('small', null, ' ' + x.lender));
            if (x.note) name.appendChild(el('span', 'plan-acc__purpose', x.note));
            tr.appendChild(name);
            tr.appendChild(el('td', null, won(x.balance)));
            tr.appendChild(el('td', null, x.rate == null ? '모름' : x.rate + '%' + (x.rate_type ? (x.rate_type === 'fixed' ? ' 고정' : ' 변동') : '')));
            tr.appendChild(el('td', null, x.maturity || '모름'));
            tbody.appendChild(tr);
        });
        table.appendChild(thead);
        table.appendChild(tbody);
        return table;
    }

    /** 그 노드(가지는 자기 이벤트) 날짜까지 쌓이는 저축·납입 — 보유 평가와 따로 보인다. */
    function accrualBox(id) {
        var a = (plan.accrual || {})[id];
        if (!a) return null;
        var box = el('div', 'plan-total');
        box.appendChild(el('strong', null, '+' + won(a.total)));
        box.appendChild(el('span', null, a.months + '개월 · ' + Object.keys(a.by_account).map(function (k) {
            return (k || '계좌 미지정') + ' +' + won(a.by_account[k]);
        }).join(' · ')));
        return box;
    }

    /** 원 — "시작" 또는 가지(대응 방법): 조건 → 매매표 → 실행할 일 → 근거 → 총자산 변화 → 예상 적립 → 비중 파이. 시작은 월 현금흐름도. */
    function renderNode() {
        var byId = nodesById(), n = byId[selected], ev = n && byId[n.parent];
        var state = plan.values[selected], base = baseOf(selected);
        showFloat(n ? n.title : '시작', n
            ? '대응 · ' + ev.title + ' ' + when(ev.at) + ' · ' + STATUS_LABEL[n.status] + (n.executed_at ? ' · 실행함 ' + shortDate(n.executed_at) : '')
            : '기준일 ' + (plan.doc.as_of || '—') + (plan.usdkrw ? ' · 환율 ' + plan.usdkrw.toLocaleString('ko-KR') + '원/달러' : ''));

        if (n) {
            section('조건', n.condition);
            var tradeSec = section('매매', tradeTable(n.id));
            if (tradeSec && !isStale(n.id) && n.status === 'realized' && !n.executed_at) {
                // [실행함] 은 제목 줄 오른쪽에 — 표 위에 따로 두면 버튼 하나가 한 줄을 차지했다
                var h = tradeSec.firstChild;
                h.classList.add('plan-sec__title--act');
                h.appendChild(executedButton(n));
            }
            // 주문은 서버 매매표가 정한다 — AI 가 쓴 actions 는 표가 있으면 메모로만(2026-10-14 검토, 메일도 같다).
            section(tradeSec ? '메모' : '실행할 일', n.actions.length ? n.actions : (n.holdings ? null : '매매 없이 유지'));
            section('근거', n.note);
            section('복기', retroBox(n, byId));
        }
        // 부채가 있으면 순자산(보유 − 부채)이 머리 숫자다 — 주거를 보증금 전액으로 적게 바꿨다(2026-10-17).
        var debt = plan.debt_total || 0, worth = function (st) { return debt ? st.net : st.total; };
        var tot = el('div', 'plan-total');
        tot.appendChild(el('strong', null, won(worth(state))));
        if (base) {
            var d = state.total - base.total;
            tot.appendChild(el('span', null, '실행 전 ' + won(worth(base)) + ' 대비 ' + (d >= 0 ? '+' : '') + won(d)));
        } else if (debt) {
            tot.appendChild(el('span', null, '자산 ' + won(state.total) + ' − 부채 ' + won(debt)));
        }
        section(n ? (debt ? '실행 뒤 순자산' : '실행 뒤 자산') : (debt ? '순자산' : '총자산'), tot);
        if (n) section('그때까지 예상 적립', accrualBox(n.id));
        else {
            section('계좌', accountTable());
            section('부채', debtTable());
            if (plan.cashflow) section('월 현금흐름', flowTable());
        }
        detailEl.appendChild(pies(state, base));
    }

    function signed(v) { return (v >= 0 ? '+' : '−') + won(Math.abs(v)); }

    function changeEl(change, pct) {
        // 그때와 지금 시세가 없는 보유가 다르면 서버가 변화를 비운다(retrospect) — 견줄 수 없는 숫자를 내지 않는다.
        if (change == null) return el('span', null, '비교 불가');
        var c = el('span', change > 0 ? 'q-up' : change < 0 ? 'q-down' : '', signed(change) + (pct == null ? '' : ' (' + (pct >= 0 ? '+' : '−') + Math.abs(pct).toFixed(1) + '%)'));
        return c;
    }

    /**
     * 복기 — 이벤트 날짜가 지난 가지: 그때(이벤트 시각 시세) → 지금(오늘 시세). 접힌 가지는 "채택했다면" 채택한 계획(채택 가지)과 견준다.
     * 가지의 보유는 계획상 수량이다(실제 체결과 다를 수 있다).
     */
    function retroBox(n, byId) {
        var r = (plan.retro || {})[n.id];
        if (!r) return null;
        var box = el('div', 'plan-retro');
        var line = el('p', 'plan-retro__line');
        line.appendChild(document.createTextNode('그때(' + shortDate(r.at) + ') ' + won(r.then) + ' → 지금 ' + won(r.now) + '  '));
        line.appendChild(changeEl(r.change, r.pct));
        box.appendChild(line);
        if (n.status !== 'realized') {
            var taken = plan.doc.nodes.filter(function (k) {
                return k.parent === n.parent && k.status === 'realized' && (plan.retro || {})[k.id];
            })[0];
            var t = taken && plan.retro[taken.id];
            if (t && r.pct != null && t.pct != null) {
                // 가지마다 출발 금액이 다를 수 있어 금액이 아니라 **변화율**로 견준다.
                var diff = r.pct - t.pct, cmp = el('p', 'plan-retro__line');
                cmp.appendChild(document.createTextNode('채택했다면 ' + (r.pct >= 0 ? '+' : '−') + Math.abs(r.pct).toFixed(1)
                    + '% — 채택한 계획(‘' + taken.title + '’) ' + (t.pct >= 0 ? '+' : '−') + Math.abs(t.pct).toFixed(1) + '%보다 '));
                cmp.appendChild(el('span', diff > 0 ? 'q-up' : diff < 0 ? 'q-down' : '',
                    Math.abs(diff).toFixed(1) + '%p ' + (diff > 0 ? '나음' : diff < 0 ? '못함' : '같음')));
                box.appendChild(cmp);
            }
        }
        if (r.missing) box.appendChild(el('p', 'plan-retro__note', '보유 ' + r.missing + '개는 그때 시세가 없어 빠졌습니다'
            + (r.change == null ? ' — 지금과 범위가 달라 비교하지 않습니다' : '')));
        return box;
    }

    function linkList(links) {
        if (!links.length) return null;
        var ul = el('ul', 'plan-sec__list plan-sec__links');
        links.forEach(function (l) {
            var li = el('li'), a = el('a', null, l.title);
            a.href = l.url;
            a.target = '_blank';
            a.rel = 'noopener noreferrer';
            li.appendChild(a);
            ul.appendChild(li);
        });
        return ul;
    }

    /**
     * 날짜 라벨로 연 이벤트: 개요 → 시장 예상 → 메모 → 대응 가지(조건·비중·총자산, 누르면 가지 상세) → 직전 비중 → 출처.
     * 같은 시각·같은 이름의 이벤트가 여러 가지 아래 있으면 개요·예상은 첫 것에서, 대응은 가지마다 한 덩어리씩.
     */
    function renderEvent() {
        var byId = nodesById();
        if (openedEvent.title == null) { renderEventList(); return; }
        var list = plan.doc.nodes.filter(function (n) {
            return n.kind === 'event' && timeKey(n.at) === openedEvent.row && n.title === openedEvent.title;
        });
        if (!list.length) { closeFloat(); return; }
        var pending = list.some(function (e) { return e.status === 'pending'; });
        var first = list.filter(function (e) { return e.about || e.expect; })[0] || list[0];
        showFloat(openedEvent.title, '이벤트 · ' + when(list[0].at) + ' · ' + (pending ? '결과 대기' : '결과 확정'));

        section('개요', first.about);
        section('시장 예상', first.expect);
        section('그때까지 예상 적립', accrualBox(list[0].id));

        list.forEach(function (e) {
            var box = el('div', 'plan-event');
            var from = list.length > 1 ? ' — ‘' + (e.parent ? byId[e.parent].title : '시작') + '’ 다음' : '';
            if (e.note) section('메모' + from, e.note, box);
            var kids = plan.doc.nodes.filter(function (k) { return k.parent === e.id; });
            if (!kids.length) {
                section('대응 방법' + from, '아직 없습니다.', box);
            } else {
                var ul = el('ul', 'plan-branches');
                kids.forEach(function (k) {
                    var li = el('li'), b = el('button', 'plan-branch');
                    b.type = 'button';
                    var head = el('span', 'plan-branch__head');
                    head.appendChild(el('b', null, k.title + (k.status !== 'pending' ? ' (' + STATUS_LABEL[k.status] + ')' : '')));
                    head.appendChild(el('small', null, won(plan.debt_total ? plan.values[k.id].net : plan.values[k.id].total)));
                    b.appendChild(head);
                    if (k.condition) b.appendChild(el('span', 'plan-branch__cond', k.condition));
                    var r = (plan.retro || {})[k.id];
                    if (r) {
                        var rl = el('span', 'plan-branch__retro', '그때 ' + won(r.then) + ' → 지금 ' + won(r.now) + '  ');
                        rl.appendChild(changeEl(r.change, r.pct));
                        b.appendChild(rl);
                    }
                    b.appendChild(bar(plan.values[k.id]));
                    b.addEventListener('click', function () { select(k.id); });
                    li.appendChild(b);
                    ul.appendChild(li);
                });
                section('대응 방법' + from, ul, box);
            }
            var mix = classMix(plan.values[e.id]).filter(function (m) { return m.value > 0; });
            if (mix.length) {
                var before = el('div', 'plan-pies');
                before.appendChild(pie('직전 자산군 비중', mix, []));
                box.appendChild(before);
            }
            detailEl.appendChild(box);
        });
        var links = [];
        list.forEach(function (e) { e.links.forEach(function (l) { if (!links.some(function (x) { return x.url === l.url; })) links.push(l); }); });
        section('출처', linkList(links));
    }

    /** 날짜축에서 묶인 "이벤트 N개" — 그 시각의 이벤트 이름 목록. 누르면 그 이벤트 상세로 간다. */
    function renderEventList() {
        var list = plan.doc.nodes.filter(function (n) { return n.kind === 'event' && timeKey(n.at) === openedEvent.row; });
        if (!list.length) { closeFloat(); return; }
        var titles = [];
        list.forEach(function (e) { if (titles.indexOf(e.title) < 0) titles.push(e.title); });
        showFloat(when(list[0].at), '이벤트 ' + titles.length + '개');
        var ul = el('ul', 'plan-branches');
        titles.forEach(function (t) {
            var li = el('li'), b = el('button', 'plan-branch');
            b.type = 'button';
            var head = el('span', 'plan-branch__head');
            head.appendChild(el('b', null, t));
            b.appendChild(head);
            b.addEventListener('click', function () { openEvent(openedEvent.row, t); });
            li.appendChild(b);
            ul.appendChild(li);
        });
        detailEl.appendChild(ul);
    }

    function render() {
        renderTodo();
        renderTree();
        refreshFloat();
    }

    function setPlan(next) {
        plan = next;
        render();
    }

    // `expect` — 토스트의 [되돌리기]는 그때 만든 버전이 아직 최신일 때만 되돌린다(그 사이 상담·저장이 끼면 서버가 409).
    function restore(revId, expect) {
        var q = expect ? '?expect=' + expect : '';
        return api('POST', '/api/v1/plan/revisions/' + revId + '/restore' + q).then(function (p) {
            setPlan(p);
            window.toast('계획을 ' + revId + '번 버전으로 되돌렸습니다', 'success');
        }).catch(function (e) { window.toast('되돌리지 못했습니다: ' + e.message, 'error'); });
    }

    // 창 크기가 바뀌면 트리를 칸 폭에 다시 맞춘다(큰 원·작은 점 배분이 폭에 달렸다).
    var resizeTimer = null, lastTreeW = 0;
    window.addEventListener('resize', function () {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(function () {
            if (plan && treeEl.clientWidth !== lastTreeW) { lastTreeW = treeEl.clientWidth; renderTree(); }
        }, 150);
    });

    // 상세 창은 그 본문만 움직인다.
    trapWheel(floatEl, function () { return detailEl; });

    // ── AI 상담 시트와 잇기 ────────────────────────────────
    //    상담은 이 화면을 모른다 — AI 가 계획을 고쳤거나(source "plan") 무엇이 바뀌었는지 모를 때(null) 알려 주면 다시 그리고,
    //    상담 시트가 열리면 상세 창을 닫는다(좁은 화면에서 두 시트가 겹친다).

    document.addEventListener('assistant:changed', function (e) {
        var d = e.detail || {};
        if (d.source && d.source !== 'plan') return;
        if (d.data && d.data.doc) { setPlan(d.data); return; }
        api('GET', '/api/v1/plan').then(setPlan).catch(function (err) {
            window.toast('계획을 다시 읽지 못했습니다: ' + err.message, 'error');
        });
    });
    //: 상담 시트를 열며 닫은 상세 창의 맥락 — 그 원·이벤트에 대해 물으려고 연 것이라 닫혀도 함께 보낸다(다른 창을 열면 지운다)
    var askedAbout = {};
    document.addEventListener('assistant:open', function () {
        if (floatEl.hidden) return;
        askedAbout = window.assistantContext();
        closeFloat();
    });

    /** 상담에 보낼 지금 화면 — 연 원(가지·시작)의 id, 날짜 라벨로 연 이벤트면 그 이벤트들의 id. */
    window.assistantContext = function () {
        if (selected) return { node: selected };
        if (!openedEvent || !plan) return askedAbout;
        return { events: plan.doc.nodes.filter(function (n) {
            return n.kind === 'event' && timeKey(n.at) === openedEvent.row && (openedEvent.title == null || n.title === openedEvent.title);
        }).map(function (n) { return n.id; }) };
    };

    // ── 상세 창 닫기 ───────────────────────────────────────

    document.getElementById('planFloatClose').addEventListener('click', closeFloat);
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && !floatEl.hidden && !historyDlg.open && !document.getElementById('planNotes').open) closeFloat();
    });
    // 바깥을 누르면 닫는다. 다른 원·날짜 라벨·할 일의 가지 이름은 그 상세로 바꾸는 자리라 빼고, 토스트(되돌리기 등)도 뺀다.
    // ⚠️ 창 안의 가지 버튼은 누르는 순간 창이 다시 그려져 문서에서 빠진다 — `contains` 로는 바깥으로 오판한다.
    //    이벤트 시점의 경로(composedPath)로 판정한다.
    function outsideFloat(e) {
        var path = e.composedPath();
        return path.indexOf(floatEl) < 0 && !path.some(function (n) {
            return n.nodeType === 1 && n.matches('.plan-dot, .plan-axis__ev, .plan-todo__name, .c-toast-host');
        });
    }
    // 누르기 시작(pointerdown)과 떼기(pointerup)가 **둘 다** 바깥일 때만 닫는다 — click 하나로 보면 창 안 표·숫자를
    // 끌어 고르다 밖에서 뗄 때(또는 그 반대) click 이 공통 조상에서 일어나 닫혔다(2026-10-13 점검, 정본 bindModal 조건).
    var downOutside = false, upOutside = false;
    document.addEventListener('pointerdown', function (e) { downOutside = outsideFloat(e); }, true);
    document.addEventListener('pointerup', function (e) { upOutside = outsideFloat(e); }, true);
    document.addEventListener('click', function () {
        var outside = downOutside && upOutside;
        downOutside = upOutside = false;
        if (floatEl.hidden || historyDlg.open || document.getElementById('planNotes').open || dragMoved) { dragMoved = false; return; }
        if (outside) closeFloat();
    });

    // ── 버전 기록 ──────────────────────────────────────────

    document.getElementById('planHistoryOpen').addEventListener('click', function () {
        historyList.textContent = '';
        historyList.appendChild(el('li', 'plan-empty', '불러오는 중…'));
        // 정본 openModal — 포커스는 창 자신에(첫 버튼에 주면 강조 테두리·이름 풍선이 뜬다), 떠 있던 토스트는 다시 위로.
        window.TopLayer.openModal(historyDlg);
        api('GET', '/api/v1/plan/revisions').then(function (revs) {
            historyList.textContent = '';
            if (!revs.length) { historyList.appendChild(el('li', 'plan-empty', '아직 버전이 없습니다.')); return; }
            revs.forEach(function (r, i) {
                var li = el('li');
                var d = el('div');
                d.appendChild(el('b', null, '#' + r.rev_id + (i === 0 ? ' (지금)' : '')));
                d.appendChild(el('small', null, when(r.created_at) + ' · ' + (r.summary || '')));
                li.appendChild(d);
                if (i > 0) {
                    var b = el('button', 'c-btn');
                    b.type = 'button';
                    b.innerHTML = '<svg class="c-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"'
                                + ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
                                + '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.7 2.7L3 8"/><path d="M3 3v5h5"/></svg>';
                    b.appendChild(el('span', null, '이 버전으로 되돌리기'));
                    b.addEventListener('click', function () {
                        if (!confirm('#' + r.rev_id + ' 버전으로 되돌릴까요? 지금 계획은 버전 기록에 남습니다.')) return;
                        historyDlg.close();
                        restore(r.rev_id);
                    });
                    li.appendChild(b);
                }
                historyList.appendChild(li);
            });
        }).catch(function (e) { historyDlg.close(); window.toast('버전 기록을 불러오지 못했습니다: ' + e.message, 'error'); });
    });
    document.getElementById('planHistoryClose').addEventListener('click', function () { historyDlg.close(); });
    // 떠 있는 창 규칙 — 바깥(막)을 누르면 닫는다. 정본처럼 **누르기 시작과 떼기가 모두 창 밖**일 때만이다
    // (창 안에서 글자를 끌다 밖에서 떼면 안 닫힌다). Esc 는 dialog 기본(cancel)으로 닫힌다.
    window.TopLayer.bindModal(historyDlg);

    // ── 원칙·기억 ──────────────────────────────────────────
    //
    // 열 때 지금 계획의 목록으로 채우고, [저장]에서 두 목록을 통째로 보낸다(PUT /notes — 연 버전과 다르면 409).

    var notesDlg = document.getElementById('planNotes');
    var notesBase = null;   // 열 때의 버전 — 그 사이 상담이 고쳤으면 서버가 거절한다

    function iconSvg(paths) {
        return '<svg class="c-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"'
             + ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + paths + '</svg>';
    }

    function noteRow(list, value) {
        var li = el('li');
        var ta = el('textarea');
        ta.rows = 1;
        ta.maxLength = 300;
        ta.value = value;
        ta.setAttribute('aria-label', list.parentNode.dataset.label);
        var del = el('button', 'c-btn');
        del.type = 'button';
        del.innerHTML = iconSvg('<path d="M3 6h18"/><path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2"/>'
                              + '<path d="m19 6-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>');
        del.appendChild(el('span', null, '지우기'));
        del.addEventListener('click', function () { li.remove(); syncAdd(list); });
        li.appendChild(ta);
        li.appendChild(del);
        list.appendChild(li);
        return ta;
    }

    // 한도(원칙 30·기억 50)에 닿으면 추가 버튼을 끈다.
    function syncAdd(list) {
        var sec = list.parentNode;
        sec.querySelector('.plan-notes__add').disabled = list.children.length >= +sec.dataset.max;
    }

    notesDlg.querySelectorAll('.plan-notes__sec').forEach(function (sec) {
        var list = sec.querySelector('.plan-notes__list');
        var add = el('button', 'c-btn plan-notes__add');
        add.type = 'button';
        add.innerHTML = iconSvg('<path d="M12 5v14"/><path d="M5 12h14"/>');
        add.appendChild(el('span', null, sec.dataset.label + ' 추가'));
        add.addEventListener('click', function () { noteRow(list, '').focus(); syncAdd(list); });
        sec.appendChild(add);
    });

    function notesOf(key) {
        return Array.prototype.map.call(notesDlg.querySelectorAll('[data-key="' + key + '"] textarea'), function (t) {
            return t.value.trim();
        }).filter(Boolean);
    }

    document.getElementById('planNotesOpen').addEventListener('click', function () {
        if (!plan) return;
        notesBase = plan.rev_id;
        notesDlg.querySelectorAll('.plan-notes__sec').forEach(function (sec) {
            var list = sec.querySelector('.plan-notes__list');
            list.textContent = '';
            (plan.doc[sec.dataset.key] || []).forEach(function (v) { noteRow(list, v); });
            syncAdd(list);
        });
        window.TopLayer.openModal(notesDlg);
    });
    document.getElementById('planNotesClose').addEventListener('click', function () { notesDlg.close(); });
    window.TopLayer.bindModal(notesDlg);

    document.getElementById('planNotesSave').addEventListener('click', function () {
        var btn = this;
        btn.disabled = true;
        api('PUT', '/api/v1/plan/notes', { rules: notesOf('rules'), memory: notesOf('memory'), base_rev_id: notesBase })
            .then(function (p) {
                notesDlg.close();
                setPlan(p);
                if (!p.saved) { window.toast('원칙·기억이 바뀌지 않았습니다', 'info'); return; }
                window.toast('원칙·기억을 저장했습니다', 'success', p.prev_rev_id
                    ? { action: { label: '되돌리기', onClick: function () { restore(p.prev_rev_id, p.rev_id); } }, duration: 8000 } : {});
            })
            .catch(function (e) { window.toast('원칙·기억을 저장하지 못했습니다: ' + e.message, 'error'); })
            .then(function () { btn.disabled = false; });
    });

    // ── 시작 ───────────────────────────────────────────────

    api('GET', '/api/v1/plan').then(setPlan).catch(function (e) {
        treeEl.textContent = '';
        treeEl.appendChild(el('p', 'plan-empty', '계획을 불러오지 못했습니다: ' + e.message));
        window.toast('계획을 불러오지 못했습니다', 'error', { action: { label: '다시 시도', onClick: function () { location.reload(); } } });
    });
})();
