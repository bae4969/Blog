/**
 * 투자 계획(`/stocks/plan`) — 2026-10-10. root 본인 전용.
 *
 * - 트리(2026-10-10 사용자 스케치): 왼쪽 세로 날짜축(아래가 미래), 날짜마다 가로 점선, 노드는 원("지금"·가지 결과).
 *   이벤트는 원이 아니라 **갈라지는 지점과 축 라벨**이다. 원·라벨은 HTML(포커스·클릭), 선만 SVG 로 그린다.
 * - 상세: 날짜 라벨이나 원을 누르면 트리 위에 떠 있는 창. 원은 자산군 파이 + 주식·채권 종목별 파이와
 *   실행 전 대비 비중 변화(%p), 이벤트는 가지별 비중 막대와 직전 비중.
 * - 상담: `/api/v1/plan/chat` — AI 가 계획을 고치면 새 버전이 오고, 토스트의 [되돌리기] 로 직전 버전을 다시 쌓는다.
 *
 * ⚠️ 금액은 서버가 오늘 시세로 낸다(`values`). 미래 노드도 오늘 시세라 **비율**을 보라는 뜻이다.
 * ⚠️ 개인 데이터라 읽기도 Bearer 다 — 쿠키 세션에서 `/api/v1/auth/token` 으로 받는다(watchlist.js 와 같은 길).
 * ⚠️ AI 답은 글자 그대로(`textContent`) 넣는다. HTML 로 넣으면 답에 섞인 마크업이 그대로 실행된다.
 */
(function () {
    'use strict';

    var CLASSES = ['stock', 'bond', 'cash', 'crypto', 'other'];
    var CLASS_LABEL = { stock: '주식', bond: '채권', cash: '현금', crypto: '코인', other: '기타' };
    var STATUS_LABEL = { pending: '대기', realized: '실현', dropped: '접힘' };
    //: 분류 색 — plan.css 의 `--series-N`. 순서 고정, 8번째부터는 "기타" 회색으로 접는다.
    var SERIES = 7;
    var MAX_IMAGES = 4;
    var IMAGE_SIDE = 1600;

    // 트리 배치(px) — 날짜축 칸 폭·축 x·원 칸 폭·줄 높이·첫 줄 y·원 반지름
    var AXIS_W = 168, AXIS_X = 14, SLOT_W = 136, ROW_H = 128, TOP = 40, R = 9;

    var treeEl = document.getElementById('planTree');
    var floatEl = document.getElementById('planFloat');
    var floatTitle = document.getElementById('planFloatTitle');
    var floatSub = document.getElementById('planFloatSub');
    var detailEl = document.getElementById('planDetail');
    var logEl = document.getElementById('planChatLog');
    var form = document.getElementById('planChatForm');
    var input = document.getElementById('planChatInput');
    var fileInput = document.getElementById('planChatFile');
    var thumbsEl = document.getElementById('planChatThumbs');
    var sendBtn = document.getElementById('planChatSend');
    var historyDlg = document.getElementById('planHistory');
    var historyList = document.getElementById('planHistoryList');
    if (!treeEl) return;

    var plan = null;          // GET /api/v1/plan 의 응답
    var selected = null;      // 상세 창에 연 원(id) — 없으면 null
    var images = [];          // 보낼 이미지 data URL
    var busy = false;

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
                if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : '요청 실패(' + r.status + ')');
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
        state.rows.forEach(function (r) { if (r.value != null) sum[r.kind] = (sum[r.kind] || 0) + r.value; });
        return CLASSES.map(function (k, i) {
            return { key: k, label: CLASS_LABEL[k], value: sum[k] || 0, color: color(i) };
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
            if (!map[key]) { map[key] = { key: key, label: r.name, value: 0, qty: 0, unpriced: false }; keys.push(key); }
            map[key].value += r.value || 0;
            map[key].qty += r.qty || 0;
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

    // ── 트리 — 왼쪽 날짜축 + 원 ────────────────────────────

    function timeKey(iso) { return String(Date.parse(iso)); }

    /**
     * 배치. 원은 "지금"과 가지뿐이다 — 이벤트는 갈라지는 지점과 날짜축 라벨로만 나타난다.
     * 줄: 0 = 지금, 그 아래로 이벤트 시각을 날짜순으로 **균등하게**(날짜 차이에 비례하지 않는다).
     *     가지 원은 부모 이벤트의 줄에 놓인다. 다른 가지의 같은 시각 이벤트는 한 줄을 함께 쓴다.
     * 칸: 잎 원마다 한 칸, 부모 원은 자식 원들의 가운데.
     */
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

        var rows = [{ key: 'root', at: null, events: [] }], rowOf = {};
        nodes.filter(function (n) { return n.kind === 'event'; })
            .sort(function (a, b) { return Date.parse(a.at) - Date.parse(b.at); })
            .forEach(function (e) {
                var k = timeKey(e.at);
                if (rowOf[k] == null) { rowOf[k] = rows.length; rows.push({ key: k, at: e.at, events: [] }); }
                rows[rowOf[k]].events.push(e);
            });

        var pos = {}, leaf = 0;
        function walk(id, dropped) {
            var n = byId[id], isDropped = dropped || !!(n && n.status === 'dropped');
            var kids = [];
            eventsUnder[id].forEach(function (e) { branchesOf[e.id].forEach(function (b) { kids.push(b.id); }); });
            kids.forEach(function (k) { walk(k, isDropped); });
            pos[id] = {
                slot: kids.length ? (pos[kids[0]].slot + pos[kids[kids.length - 1]].slot) / 2 : leaf++,
                row: n ? rowOf[timeKey(byId[n.parent].at)] : 0,
                dropped: isDropped
            };
        }
        walk('root', false);
        return { byId: byId, rows: rows, rowOf: rowOf, pos: pos, eventsUnder: eventsUnder, branchesOf: branchesOf,
                 width: AXIS_W + Math.max(1, leaf) * SLOT_W + 16, height: TOP + rows.length * ROW_H + 8 };
    }

    function px(p) { return { x: AXIS_W + p.slot * SLOT_W + SLOT_W / 2, y: TOP + p.row * ROW_H }; }

    function shortDate(iso) {
        var d = new Date(iso);
        var two = function (v) { return (v < 10 ? '0' : '') + v; };
        // 브라우저 시각대가 아니라 KST 로 읽는다 — 서버가 +09:00 으로 준다.
        var k = new Date(d.getTime() + 9 * 3600 * 1000);
        return (k.getUTCMonth() + 1) + '.' + two(k.getUTCDate()) + ' ' + two(k.getUTCHours()) + ':' + two(k.getUTCMinutes());
    }

    function renderTree() {
        var L = layout(), canvas = el('div', 'plan-tree__canvas');
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
        L.rows.forEach(function (row, i) {
            var y = TOP + i * ROW_H;
            g.appendChild(svg('path', { class: 'plan-guide', d: 'M' + AXIS_W + ',' + y + ' H' + L.width }));
            ag.appendChild(svg('path', { class: 'plan-guide', d: 'M' + (AXIS_X + 8) + ',' + y + ' H' + AXIS_W }));
            ag.appendChild(svg('circle', { class: 'plan-axis__dot', cx: AXIS_X, cy: y, r: 4 }));
            axis.appendChild(axisLabel(row, y));
        });

        Object.keys(L.pos).forEach(function (id) { canvas.appendChild(dotEl(id, L.byId[id], L.pos[id])); });

        var first = !treeEl.querySelector('.plan-tree__canvas'), keep = treeEl.scrollLeft;
        treeEl.textContent = '';
        treeEl.appendChild(canvas);

        // 원 아래 이름·금액·막대 묶음의 실제 높이 — 갈래 선은 그 밑에서 시작한다(글꼴에 따라 달라 어림값을 쓰지 않는다).
        // 원 버튼은 원 중심보다 14px 위에서 시작한다(dotEl).
        var labelH = canvas.querySelector('.plan-dot').offsetHeight - 14 + 4;

        // 갈래 — 부모 원에서 곧장 내려와 이벤트 줄 위에서 갈라진다
        plan.doc.nodes.forEach(function (n) {
            if (n.kind !== 'event') return;
            var p = px(L.pos[n.parent || 'root']), rowY = TOP + L.rowOf[timeKey(n.at)] * ROW_H;
            var start = p.y + labelH, fork = Math.max(start + 8, rowY - ROW_H * 0.45);
            var kids = L.branchesOf[n.id];
            if (!kids.length) {
                // 가지가 아직 없는 이벤트 — 줄까지 내려와 빈 점으로 끝낸다
                g.appendChild(svg('path', { class: 'plan-edge is-pending', d: 'M' + p.x + ',' + start + ' V' + (rowY - 5) }));
                g.appendChild(svg('circle', { class: 'plan-edge__end', cx: p.x, cy: rowY, r: 4 }));
                return;
            }
            kids.forEach(function (b) {
                var c = px(L.pos[b.id]), d = (c.y - R - fork) * 0.5;
                var path = svg('path', { class: 'plan-edge', d: 'M' + p.x + ',' + start + ' V' + fork
                    + ' C' + p.x + ',' + (fork + d) + ' ' + c.x + ',' + fork + ' ' + c.x + ',' + (fork + d) + ' V' + (c.y - R) });
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
        // 다시 그릴 때(계획이 바뀜)는 보던 자리를 지킨다. 처음 열 때만 "지금"이 화면 밖이면 **겨우 보일 만큼만** 민다 —
        // 더 밀면 그만큼 왼쪽 원이 날짜축 칸 밑에 가린다.
        var root = canvas.querySelector('.plan-dot[data-id="root"]');
        treeEl.scrollLeft = first ? Math.max(0, root.offsetLeft + root.offsetWidth + 8 - treeEl.clientWidth) : keep;
    }

    function axisLabel(row, y) {
        var box = el('div', 'plan-axis__label');
        box.style.top = (y - 9) + 'px';
        box.style.left = (AXIS_X + 12) + 'px';
        box.style.width = (AXIS_W - AXIS_X - 24) + 'px';
        if (!row.at) {
            box.appendChild(el('span', 'plan-axis__date', '지금'));
            box.appendChild(el('span', 'plan-axis__sub', plan.doc.as_of || ''));
            return box;
        }
        box.appendChild(el('span', 'plan-axis__date', shortDate(row.at)));
        var seen = [];
        row.events.forEach(function (e) {
            if (seen.indexOf(e.title) >= 0) return;
            seen.push(e.title);
            var b = el('button', 'plan-axis__ev', e.title);
            b.type = 'button';
            b.dataset.row = row.key;
            b.dataset.title = e.title;
            b.addEventListener('click', function () { openEvent(row.key, e.title); });
            box.appendChild(b);
        });
        return box;
    }

    function dotEl(id, n, p) {
        var c = px(p), b = el('button', 'plan-dot' + (n ? '' : ' plan-dot--root'));
        b.type = 'button';
        b.dataset.id = id;
        b.style.left = (c.x - SLOT_W / 2 + 6) + 'px';
        b.style.top = (c.y - 14) + 'px';
        b.style.width = (SLOT_W - 12) + 'px';
        if (p.dropped) b.classList.add('is-dropped');
        else if (n && n.status === 'realized') b.classList.add('is-realized');
        if (id === selected) b.classList.add('is-selected');
        var name = n ? n.title : '지금';
        b.appendChild(el('span', 'plan-dot__ring'));
        b.appendChild(el('span', 'plan-dot__title', name));
        b.appendChild(el('span', 'plan-dot__total', won(plan.values[id].total)));
        b.appendChild(bar(plan.values[id]));
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
            b.classList.toggle('is-selected', !!openedEvent && b.dataset.row === openedEvent.row && b.dataset.title === openedEvent.title);
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

    // ── 떠 있는 상세 창 ─────────────────────────────────────

    var openedEvent = null;   // {row, title} — 날짜 라벨로 연 이벤트 상세

    function showFloat(title, sub) {
        floatTitle.textContent = title;
        floatSub.textContent = sub;
        detailEl.textContent = '';
        floatEl.hidden = false;
        floatEl.scrollTop = 0;
    }

    function closeFloat() {
        floatEl.hidden = true;
        selected = null;
        openedEvent = null;
        mark();
    }

    function select(id) {
        selected = id;
        openedEvent = null;
        mark();
        renderNode();
    }

    function openEvent(rowKey, title) {
        selected = null;
        openedEvent = { row: rowKey, title: title };
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
        if (!tip) { tip = el('div', 'plan-tip'); document.body.appendChild(tip); }
        tip.textContent = text;
        tip.hidden = false;
        var x = Math.min(ev.clientX + 12, window.innerWidth - tip.offsetWidth - 8);
        tip.style.left = x + 'px';
        tip.style.top = (ev.clientY + 14) + 'px';
    }

    function hideTip() { if (tip) tip.hidden = true; }

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

    /** 자산군 파이 + 주식·채권 종목별 파이. `base` 가 있으면 비중 변화(%p) 칸을 붙인다. */
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
    }

    /** 원 — "지금" 또는 가지(대응 방법): 조건 → 실행할 일 → 근거 → 총자산 변화 → 비중 파이. */
    function renderNode() {
        var byId = nodesById(), n = byId[selected], ev = n && byId[n.parent];
        var state = plan.values[selected], base = baseOf(selected);
        showFloat(n ? n.title : '지금 보유', n
            ? '대응 · ' + ev.title + ' ' + when(ev.at) + ' · ' + STATUS_LABEL[n.status]
            : '기준일 ' + (plan.doc.as_of || '—') + (plan.usdkrw ? ' · 환율 ' + plan.usdkrw.toLocaleString('ko-KR') + '원/달러' : ''));

        if (n) {
            section('조건', n.condition);
            section('실행할 일', n.actions.length ? n.actions : (n.holdings ? null : '매매 없이 유지'));
            section('근거', n.note);
        }
        var tot = el('div', 'plan-total');
        tot.appendChild(el('strong', null, won(state.total)));
        if (base) {
            var d = state.total - base.total;
            tot.appendChild(el('span', null, '실행 전 ' + won(base.total) + ' 대비 ' + (d >= 0 ? '+' : '') + won(d)));
        }
        section(n ? '실행 뒤 자산' : '총자산', tot);
        detailEl.appendChild(pies(state, base));
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
        var list = plan.doc.nodes.filter(function (n) {
            return n.kind === 'event' && timeKey(n.at) === openedEvent.row && n.title === openedEvent.title;
        });
        if (!list.length) { closeFloat(); return; }
        var pending = list.some(function (e) { return e.status === 'pending'; });
        var first = list.filter(function (e) { return e.about || e.expect; })[0] || list[0];
        showFloat(openedEvent.title, '이벤트 · ' + when(list[0].at) + ' · ' + (pending ? '결과 대기' : '결과 확정'));

        section('개요', first.about);
        section('시장 예상', first.expect);

        list.forEach(function (e) {
            var box = el('div', 'plan-event');
            var from = list.length > 1 ? ' — ‘' + (e.parent ? byId[e.parent].title : '지금') + '’ 다음' : '';
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
                    head.appendChild(el('small', null, won(plan.values[k.id].total)));
                    b.appendChild(head);
                    if (k.condition) b.appendChild(el('span', 'plan-branch__cond', k.condition));
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

    function render() {
        renderTree();
        refreshFloat();
    }

    // ── 상담 — 생김새는 30.ai_center 대화 화면을 따른다 ─────────
    //    내 말 = 오른쪽 연보라 말풍선(원문 그대로), AI = 전폭 카드("ASSISTANT"·시각), 아래에 떠 있는 입력 상자.

    /**
     * AI 답의 `**굵게**`·`` `코드` ``·`[이름](http…)` 만 살린다. 나머지는 글자 그대로다(줄바꿈은 CSS pre-wrap).
     * ⚠️ innerHTML 을 쓰지 않는다 — 조각마다 텍스트 노드·요소를 만들고, 링크는 http(s) 만 받는다.
     */
    function richText(target, text) {
        var re = /\*\*([^*]+)\*\*|`([^`\n]+)`|\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, last = 0, m;
        while ((m = re.exec(text))) {
            target.appendChild(document.createTextNode(text.slice(last, m.index)));
            if (m[1] != null) target.appendChild(el('strong', null, m[1]));
            else if (m[2] != null) target.appendChild(el('code', null, m[2]));
            else {
                var a = el('a', null, m[3]);
                a.href = m[4];
                a.target = '_blank';
                a.rel = 'noopener noreferrer';
                target.appendChild(a);
            }
            last = re.lastIndex;
        }
        target.appendChild(document.createTextNode(text.slice(last)));
    }

    function clock(iso) {
        var d = iso ? new Date(iso.length === 19 ? iso + '+09:00' : iso) : new Date();
        var k = new Date(d.getTime() + 9 * 3600 * 1000), now = new Date(Date.now() + 9 * 3600 * 1000);
        var two = function (v) { return (v < 10 ? '0' : '') + v; };
        var hm = two(k.getUTCHours()) + ':' + two(k.getUTCMinutes());
        return k.toISOString().slice(0, 10) === now.toISOString().slice(0, 10) ? hm : (k.getUTCMonth() + 1) + '/' + k.getUTCDate() + ' ' + hm;
    }

    function clearEmpty() {
        var empty = logEl.querySelector('.plan-chat__empty');
        if (empty) empty.remove();
    }

    function addMessage(m) {
        clearEmpty();
        var div;
        if (m.role === 'user') {
            div = el('div', 'plan-msg plan-msg--user');
            div.appendChild(el('div', 'plan-bubble', m.content));
        } else {
            div = el('article', 'plan-msg plan-msg--ai');
            var head = el('header', 'plan-msg__head', 'assistant');
            head.appendChild(el('time', 'plan-msg__time', clock(m.created_at)));
            div.appendChild(head);
            var body = el('div', 'plan-msg__body');
            richText(body, m.content);
            div.appendChild(body);
            if (m.rev_id) div.appendChild(el('span', 'plan-msg__rev', '계획 버전 #' + m.rev_id));
        }
        logEl.insertBefore(div, waitEl.parentNode ? waitEl : null);
        logEl.scrollTop = logEl.scrollHeight;
        return div;
    }

    function emptyChat() {
        var box = el('div', 'plan-chat__empty');
        box.appendChild(el('div', 'plan-chat__empty-mark', '∅'));
        box.appendChild(el('p', null, '보유 자산 화면을 첨부하거나, 다가오는 이벤트와 고민을 적어 상담을 시작하세요.'));
        logEl.appendChild(box);
    }

    function renderChips() {
        thumbsEl.textContent = '';
        thumbsEl.hidden = !images.length;
        images.forEach(function (src, i) {
            var chip = el('span', 'plan-chip');
            var img = el('img'); img.src = src; img.alt = '';
            chip.appendChild(img);
            chip.appendChild(el('span', 'plan-chip__name', '이미지 ' + (i + 1)));
            chip.appendChild(el('span', 'plan-chip__size', '(' + Math.round(src.length * 0.75 / 1024) + ' KB)'));
            var x = el('button', 'plan-chip__x');
            x.type = 'button';
            x.setAttribute('aria-label', '이미지 ' + (i + 1) + ' 빼기');
            x.innerHTML = '<svg class="c-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"'
                        + ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>';
            x.addEventListener('click', function () { images.splice(i, 1); renderChips(); });
            chip.appendChild(x);
            thumbsEl.appendChild(chip);
        });
    }

    /** 긴 변을 1600px 로 줄여 JPEG 로 — 휴대폰 사진 그대로면 수 MB 라 서버 상한(3MB)을 넘는다. */
    function shrink(file) {
        return new Promise(function (resolve, reject) {
            var url = URL.createObjectURL(file), img = new Image();
            img.onload = function () {
                var s = Math.min(1, IMAGE_SIDE / Math.max(img.naturalWidth, img.naturalHeight));
                var c = document.createElement('canvas');
                c.width = Math.round(img.naturalWidth * s);
                c.height = Math.round(img.naturalHeight * s);
                c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
                URL.revokeObjectURL(url);
                resolve(c.toDataURL('image/jpeg', 0.85));
            };
            img.onerror = function () { URL.revokeObjectURL(url); reject(new Error('이미지를 읽지 못했습니다')); };
            img.src = url;
        });
    }

    function addFiles(files) {
        var list = Array.prototype.filter.call(files, function (f) { return /^image\//.test(f.type); });
        if (images.length + list.length > MAX_IMAGES) window.toast('이미지는 한 번에 ' + MAX_IMAGES + '장까지 보낼 수 있습니다', 'error');
        list = list.slice(0, Math.max(0, MAX_IMAGES - images.length));
        Promise.all(list.map(shrink)).then(function (urls) {
            images = images.concat(urls);
            renderChips();
        }).catch(function (e) { window.toast(e.message, 'error'); });
    }

    //: 대화 끝의 "요청중..." 줄(점은 CSS 가 움직인다) — 30.ai_center 와 같은 대기 표시.
    var waitEl = el('div', 'plan-wait', '요청중');
    var timer = null;

    function setBusy(on) {
        busy = on;
        sendBtn.disabled = on;
        clearInterval(timer);
        if (on) {
            var t0 = Date.now();
            waitEl.textContent = '요청중';
            logEl.appendChild(waitEl);
            timer = setInterval(function () { waitEl.textContent = '요청중 · ' + Math.round((Date.now() - t0) / 1000) + '초'; }, 1000);
        } else if (waitEl.parentNode) {
            waitEl.remove();
        }
        logEl.scrollTop = logEl.scrollHeight;
    }

    function setPlan(next) {
        plan = next;
        render();
    }

    function restore(revId) {
        return api('POST', '/api/v1/plan/revisions/' + revId + '/restore').then(function (p) {
            setPlan(p);
            window.toast('계획을 ' + revId + '번 버전으로 되돌렸습니다', 'success');
        }).catch(function (e) { window.toast('되돌리지 못했습니다: ' + e.message, 'error'); });
    }

    function send() {
        if (busy) return;
        var text = input.value.trim();
        if (!text && !images.length) return;
        var sent = { message: text, images: images.slice() };
        var mine = addMessage({ role: 'user', content: text + (sent.images.length ? '\n[이미지 ' + sent.images.length + '장]' : '') });
        input.value = '';
        images = [];
        renderChips();
        setBusy(true);

        api('POST', '/api/v1/plan/chat', sent).then(function (r) {
            setBusy(false);
            addMessage({ role: 'assistant', content: r.reply || '(계획을 고쳤습니다)', rev_id: r.rev_id });
            if (r.plan) {
                setPlan(r.plan);
                var opt = r.prev_rev_id ? { action: { label: '되돌리기', onClick: function () { restore(r.prev_rev_id); } }, duration: 8000 } : {};
                window.toast('계획을 고쳤습니다: ' + r.summary, 'success', opt);
            }
            if (r.note) window.toast(r.note, 'error');
        }).catch(function (e) {
            setBusy(false);
            // 보낸 것을 되살려 다시 보낼 수 있게 한다.
            mine.remove();
            input.value = sent.message;
            images = sent.images;
            renderChips();
            if (!logEl.querySelector('.plan-msg')) emptyChat();
            window.toast('상담 실패: ' + e.message, 'error', { action: { label: '다시 시도', onClick: send } });
        });
    }

    form.addEventListener('submit', function (e) { e.preventDefault(); send(); });
    input.addEventListener('keydown', function (e) {
        // 한글 조합 중 Enter 는 글자 확정이다 — 보내지 않는다.
        if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
    });
    input.addEventListener('paste', function (e) {
        var files = Array.prototype.map.call((e.clipboardData && e.clipboardData.items) || [], function (it) {
            return it.kind === 'file' ? it.getAsFile() : null;
        }).filter(Boolean);
        if (files.length) { e.preventDefault(); addFiles(files); }
    });
    document.getElementById('planChatAttach').addEventListener('click', function () { fileInput.click(); });
    fileInput.addEventListener('change', function () { addFiles(fileInput.files); fileInput.value = ''; });

    // ── 상세 창 닫기 ───────────────────────────────────────

    document.getElementById('planFloatClose').addEventListener('click', closeFloat);
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && !floatEl.hidden && !historyDlg.open) closeFloat();
    });
    // 바깥을 누르면 닫는다. 다른 원·날짜 라벨은 그 상세로 바꾸는 자리라 빼고, 토스트(되돌리기 등)도 뺀다.
    document.addEventListener('click', function (e) {
        if (floatEl.hidden || historyDlg.open || dragMoved) { dragMoved = false; return; }
        // ⚠️ 창 안의 가지 버튼은 누르는 순간 창이 다시 그려져 문서에서 빠진다 — `contains` 로는 바깥으로 오판한다.
        //    누른 시점의 경로(composedPath)로 판정한다.
        var path = e.composedPath();
        if (path.indexOf(floatEl) >= 0 || path.some(function (n) {
            return n.nodeType === 1 && n.matches('.plan-dot, .plan-axis__ev, .c-toast-host');
        })) return;
        closeFloat();
    });

    // ── 버전 기록 ──────────────────────────────────────────

    document.getElementById('planHistoryOpen').addEventListener('click', function () {
        historyList.textContent = '';
        historyList.appendChild(el('li', 'plan-empty', '불러오는 중…'));
        historyDlg.showModal();
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
                    b.innerHTML = '<svg class="c-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"'
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

    // ── 시작 ───────────────────────────────────────────────

    Promise.all([api('GET', '/api/v1/plan'), api('GET', '/api/v1/plan/chat')]).then(function (res) {
        setPlan(res[0]);
        logEl.textContent = '';
        if (!res[1].length) emptyChat();
        res[1].forEach(addMessage);
    }).catch(function (e) {
        treeEl.textContent = '';
        treeEl.appendChild(el('p', 'plan-empty', '계획을 불러오지 못했습니다: ' + e.message));
        logEl.textContent = '';
        window.toast('계획을 불러오지 못했습니다', 'error', { action: { label: '다시 시도', onClick: function () { location.reload(); } } });
    });
})();
