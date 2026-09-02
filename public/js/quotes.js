/**
 * 지수·환율 화면 — `/quotes`.
 *
 * 서버는 껍데기만 주고 여기서 `/api/v1/quotes`·`/api/v1/stocks/heatmap` 을 읽어 그린다
 * (`stocks_list.js` 와 같은 방식).
 *
 * ⚠️ **오르면 빨강, 내리면 청록이다.** finviz 는 반대(오르면 초록)지만 이 사이트는 이미
 *    차트가 `--chart-up-color: #ef5350` / `--chart-down-color: #26a69a` 로 한국 관행을
 *    쓴다. 화면마다 색이 뒤집히면 그게 더 위험하다.
 *
 * ⚠️ 등락률이 **없을 수 있다**(`change_pct === null`). 지수·환율은 수집 시작이
 *    2026-09-02 라 직전 거래일이 쌓이기 전에는 계산할 수 없다. 이때 0% 로 칠하면
 *    "보합"으로 읽히므로 중립색 + `-` 로 둔다.
 */
(function () {
    'use strict';

    var GROUPS = ['KR', 'US', 'COIN'];

    /** 색이 최대로 진해지는 등락률(%). finviz 와 같이 ±3% 에서 포화시킨다. */
    var COLOR_CAP = 3;

    /** 타일에 글씨를 넣을 최소 크기(px). 이보다 작으면 색만 남긴다. */
    var LABEL_MIN_W = 46;
    var LABEL_MIN_H = 26;

    var UP = [239, 83, 80];        /* --chart-up-color   #ef5350 */
    var DOWN = [38, 166, 154];     /* --chart-down-color #26a69a */
    var FLAT = [58, 58, 58];       /* --bae-border       #3A3A3A */

    var rootEl, boxEl, tooltipEl, tabEls, footEl, legendEl;
    var market = 'KR';
    var heatmapData = [];
    var resizeTimer = null;

    /* ── 포맷 ──────────────────────────────────────────────────────────── */

    function n(v, d) {
        return (v || 0).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
    }

    /** 시가총액 — 템플릿 `won` 매크로와 같은 규칙(억·만은 정수). */
    function won(v) {
        if (!v) return '0';
        if (v >= 1e20) return n(v / 1e20, 2) + '해';
        if (v >= 1e16) return n(v / 1e16, 2) + '경';
        if (v >= 1e12) return n(v / 1e12, 2) + '조';
        if (v >= 1e8) return n(v / 1e8, 0) + '억';
        if (v >= 1e4) return n(v / 1e4, 0) + '만';
        return n(v, 0);
    }

    /** 지수·환율 값. 자릿수가 종류마다 달라(6562.72 / 1362.7 / 8.5739) 크기로 정한다. */
    function quoteValue(v) {
        if (v === null || v === undefined) return '-';
        if (v >= 1000) return n(v, 2);
        if (v >= 10) return n(v, 2);
        return n(v, 4);
    }

    function pctText(p) {
        if (p === null || p === undefined) return '-';
        return (p >= 0 ? '+' : '') + n(p, 2) + '%';
    }

    /** 등락 방향 → 클래스. 값이 없으면 중립이다(0% 와 구분한다). */
    function pctClass(p) {
        if (p === null || p === undefined) return 'q-flat';
        if (p > 0) return 'q-up';
        if (p < 0) return 'q-down';
        return 'q-flat';
    }

    /* ── 색 ────────────────────────────────────────────────────────────── */

    function mix(a, b, t) {
        return 'rgb(' + Math.round(a[0] + (b[0] - a[0]) * t) + ','
            + Math.round(a[1] + (b[1] - a[1]) * t) + ','
            + Math.round(a[2] + (b[2] - a[2]) * t) + ')';
    }

    /**
     * 등락률 → 타일 색.
     *
     * 선형으로 섞으면 ±0.5% 대가 거의 배경과 같아 보인다. 지수 0.7 로 눌러 작은 변동도
     * 눈에 남게 하되, 포화점(±3%)은 그대로 둔다.
     */
    function tileColor(p) {
        if (p === null || p === undefined) return mix(FLAT, FLAT, 0);
        var t = Math.pow(Math.min(Math.abs(p) / COLOR_CAP, 1), 0.7);
        return mix(FLAT, p >= 0 ? UP : DOWN, t);
    }

    /* ── squarified treemap ────────────────────────────────────────────── */

    /**
     * 한 줄의 "최악 종횡비". Bruls-Huizing-van Wijk 의 worst() 그대로다.
     * `areas` 는 이미 픽셀 넓이로 환산돼 있고, `len` 은 줄이 놓이는 변의 길이다.
     */
    function worstRatio(areas, len, sum) {
        var max = -Infinity, min = Infinity;
        for (var i = 0; i < areas.length; i++) {
            if (areas[i] > max) max = areas[i];
            if (areas[i] < min) min = areas[i];
        }
        var s2 = sum * sum, l2 = len * len;
        return Math.max((l2 * max) / s2, s2 / (l2 * min));
    }

    /**
     * 넓이 배열 → 사각형 배열. 입력은 **내림차순**이어야 하고 합이 `w*h` 여야 한다.
     *
     * **squarified treemap** (Bruls-Huizing-van Wijk) — finviz 가 쓰는 방식이다. 남은
     * 영역의 **짧은 변**을 따라 줄을 채우고 그만큼 잘라낸 뒤 반복한다. 방향은 고정이
     * 아니라 남은 영역 모양에서 따라 나온다(넓적하면 세로로, 길쭉하면 가로로 자른다).
     *
     * ⚠️ 2026-09-02 에 "가로·세로를 엄격히 번갈아" 자르는 방식으로 바꿨다가 되돌렸다.
     *    같은 데이터(한국 267종목)로 잰 차이가 컸다 — 종횡비 중앙값 1.10 대 11.03,
     *    3배 넘는 타일 0개 대 236개, 코인 탭 배치 20/30 대 6/30. 방향을 고정하면 남은
     *    영역이 납작할 때도 그대로 잘라서 그렇다. **다시 바꾸기 전에 이 수치를 볼 것.**
     */
    function squarify(areas, x0, y0, w0, h0) {
        var out = [];
        var x = x0, y = y0, w = w0, h = h0;
        var i = 0;

        while (i < areas.length && w > 0.5 && h > 0.5) {
            var len = Math.min(w, h);
            var row = [];
            var sum = 0;
            var best = Infinity;

            while (i + row.length < areas.length) {
                var next = areas[i + row.length];
                if (next <= 0) break;
                var cand = row.concat([next]);
                var candSum = sum + next;
                var ratio = worstRatio(cand, len, candSum);
                if (row.length && ratio > best) break;
                row = cand;
                sum = candSum;
                best = ratio;
            }
            if (!row.length) break;

            // 남은 영역이 줄 하나로 다 차면 두께가 남은 변을 넘지 않게 잘라 둔다.
            var thick = Math.min(sum / len, w >= h ? w : h);
            var off = 0;
            for (var k = 0; k < row.length; k++) {
                var side = (row[k] / sum) * len;
                if (w >= h) out.push({ x: x, y: y + off, w: thick, h: side });
                else out.push({ x: x + off, y: y, w: side, h: thick });
                off += side;
            }

            if (w >= h) { x += thick; w -= thick; }
            else { y += thick; h -= thick; }
            i += row.length;
        }
        return out;
    }

    /* ── 히트맵 ────────────────────────────────────────────────────────── */

    function detailUrl(item) {
        return '/stocks/view?code=' + encodeURIComponent(item.code)
            + (item.market === 'COIN' ? '&market=COIN' : '');
    }

    function renderHeatmap() {
        if (!boxEl) return;

        var items = heatmapData.filter(function (d) { return (d.market_cap || 0) > 0; });
        if (!items.length) {
            boxEl.innerHTML = '<div class="quote-empty">표시할 종목이 없습니다.</div>';
            if (footEl) footEl.textContent = '';
            return;
        }

        var w = boxEl.clientWidth;
        var h = boxEl.clientHeight;
        if (w < 2 || h < 2) return;

        var total = 0;
        for (var i = 0; i < items.length; i++) total += items[i].market_cap;

        var areas = items.map(function (d) { return (d.market_cap / total) * w * h; });
        var rects = squarify(areas, 0, 0, w, h);

        // ⚠️ `squarify` 는 남은 자리가 1px 아래로 얇아지면 거기서 멈춘다 — 시가총액 편차가
        //    극단이면(코인 탭의 BTC 가 98.5%) 뒤쪽 항목이 자리를 못 받는다. 그걸 **말없이
        //    빠뜨리지 않고** 아래 footer 에 몇 개가 생략됐는지 적는다.
        var shown = Math.min(rects.length, items.length);

        var frag = document.createDocumentFragment();
        for (var j = 0; j < shown; j++) {
            var r = rects[j], d = items[j];
            var el = document.createElement('a');
            el.className = 'heat-tile';
            el.href = detailUrl(d);
            el.style.left = r.x + 'px';
            el.style.top = r.y + 'px';
            el.style.width = Math.max(0, r.w - 1) + 'px';
            el.style.height = Math.max(0, r.h - 1) + 'px';
            el.style.background = tileColor(d.change_pct);
            el.dataset.idx = String(j);

            if (r.w >= LABEL_MIN_W && r.h >= LABEL_MIN_H) {
                var name = document.createElement('span');
                name.className = 'heat-tile-name';
                name.textContent = d.name_kr || d.code;
                el.appendChild(name);
                // 등락률은 타일이 조금 더 클 때만. 이름이 잘리는 것보다 낫다.
                if (r.h >= LABEL_MIN_H + 14) {
                    var pct = document.createElement('span');
                    pct.className = 'heat-tile-pct';
                    pct.textContent = pctText(d.change_pct);
                    el.appendChild(pct);
                }
            }
            frag.appendChild(el);
        }

        boxEl.innerHTML = '';
        boxEl.appendChild(frag);

        var noChg = items.filter(function (d) { return d.change_pct === null || d.change_pct === undefined; }).length;
        if (footEl) {
            var parts = [items.length + '종목 · 시가총액 순'];
            if (shown < items.length) parts.push('자리가 없어 생략 ' + (items.length - shown) + '종목');
            if (noChg) parts.push('등락률 없음 ' + noChg + '종목');
            footEl.textContent = parts.join(' · ');
        }
    }

    function renderLegend() {
        if (!legendEl) return;
        var stops = [-3, -2, -1, 0, 1, 2, 3];
        var html = '<span class="heat-legend-label">전일 대비</span>';
        for (var i = 0; i < stops.length; i++) {
            html += '<span class="heat-legend-chip" style="background:' + tileColor(stops[i]) + '">'
                + (stops[i] > 0 ? '+' : '') + stops[i] + '%</span>';
        }
        legendEl.innerHTML = html;
    }

    /* ── 툴팁 ──────────────────────────────────────────────────────────── */

    function showTooltip(evt, d) {
        if (!tooltipEl) return;
        tooltipEl.innerHTML =
            '<div class="tip-name">' + escapeHtml(d.name_kr || d.code) + '</div>'
            + '<div class="tip-row"><span>코드</span><b>' + escapeHtml(d.code) + '</b></div>'
            + '<div class="tip-row"><span>현재가</span><b>' + quoteValue(d.price) + '</b></div>'
            + '<div class="tip-row"><span>전일</span><b>' + quoteValue(d.prev_price) + '</b></div>'
            + '<div class="tip-row"><span>등락</span><b class="' + pctClass(d.change_pct) + '">'
            + pctText(d.change_pct) + '</b></div>'
            + '<div class="tip-row"><span>시가총액</span><b>' + won(d.market_cap) + '</b></div>';
        tooltipEl.hidden = false;
        moveTooltip(evt);
    }

    function moveTooltip(evt) {
        if (!tooltipEl || tooltipEl.hidden) return;
        var pad = 14;
        var rect = tooltipEl.getBoundingClientRect();
        var x = evt.clientX + pad;
        var y = evt.clientY + pad;
        if (x + rect.width > window.innerWidth - 8) x = evt.clientX - rect.width - pad;
        if (y + rect.height > window.innerHeight - 8) y = evt.clientY - rect.height - pad;
        tooltipEl.style.left = Math.max(8, x) + 'px';
        tooltipEl.style.top = Math.max(8, y) + 'px';
    }

    function hideTooltip() {
        if (tooltipEl) tooltipEl.hidden = true;
    }

    function escapeHtml(s) {
        return String(s === null || s === undefined ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    /* ── 지수·환율 카드 ────────────────────────────────────────────────── */

    /** 스파크라인. 값이 2개 미만이면 선이 안 되므로 그리지 않는다. */
    function sparkSvg(values, cls) {
        if (!values || values.length < 2) return '';
        var w = 104, h = 30, pad = 2;
        var min = Math.min.apply(null, values);
        var max = Math.max.apply(null, values);
        var span = max - min;
        // 하루 종일 같은 값이면(FX 가 실제로 그렇다) 가운데 평평한 선으로 둔다.
        var pts = values.map(function (v, i) {
            var x = pad + (i / (values.length - 1)) * (w - pad * 2);
            var y = span > 0 ? h - pad - ((v - min) / span) * (h - pad * 2) : h / 2;
            return x.toFixed(1) + ',' + y.toFixed(1);
        });
        return '<svg class="quote-spark ' + cls + '" viewBox="0 0 ' + w + ' ' + h + '" '
            + 'preserveAspectRatio="none" aria-hidden="true">'
            + '<polyline points="' + pts.join(' ') + '" fill="none" stroke="currentColor" '
            + 'stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round" /></svg>';
    }

    /** 마지막 값의 시각. ⚠️ 해외지수는 **현지시각**이라 KST 로 적으면 거짓말이 된다. */
    function atText(item) {
        if (!item.at) return '';
        var t = item.at.replace('T', ' ').slice(5, 16);
        return t + (item.category === 'INDEX_EX' ? ' 현지' : '');
    }

    function cardHtml(item) {
        var cls = pctClass(item.change_pct);
        return '<div class="quote-card">'
            + '<div class="quote-card-head">'
            + '<span class="quote-card-name">' + escapeHtml(item.name) + '</span>'
            + '<span class="quote-card-at">' + escapeHtml(atText(item)) + '</span>'
            + '</div>'
            + '<div class="quote-card-body">'
            + '<div class="quote-card-figures">'
            + '<span class="quote-card-price">' + quoteValue(item.price) + '</span>'
            + '<span class="quote-card-pct ' + cls + '">' + pctText(item.change_pct) + '</span>'
            + '</div>'
            + sparkSvg(item.spark, cls)
            + '</div>'
            + '</div>';
    }

    function renderQuotes(rows) {
        var idx = rows.filter(function (r) { return r.category !== 'FX'; });
        var fx = rows.filter(function (r) { return r.category === 'FX'; });

        fill('quoteIndexCards', idx);
        fill('quoteFxCards', fx);

        // 등락률이 하나도 없으면 왜 비었는지 알려준다 — 빈 `-` 만 보면 고장으로 읽힌다.
        note('quoteIndexNote', idx);
        note('quoteFxNote', fx);
    }

    function fill(id, rows) {
        var el = document.getElementById(id);
        if (!el) return;
        el.innerHTML = rows.length
            ? rows.map(cardHtml).join('')
            : '<div class="quote-empty">수집 중인 항목이 없습니다.</div>';
    }

    function note(id, rows) {
        var el = document.getElementById(id);
        if (!el) return;
        var have = rows.filter(function (r) {
            return r.change_pct !== null && r.change_pct !== undefined;
        }).length;
        el.textContent = (rows.length && !have) ? '전일 데이터가 쌓이면 등락률이 표시됩니다' : '';
    }

    /* ── 로딩 ──────────────────────────────────────────────────────────── */

    function loadQuotes() {
        fetch('/api/v1/quotes', { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : []; })
            .then(renderQuotes)
            .catch(function () { renderQuotes([]); });
    }

    function loadHeatmap() {
        boxEl.innerHTML = '<div class="quote-empty">불러오는 중…</div>';
        fetch('/api/v1/stocks/heatmap?market=' + encodeURIComponent(market), { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : []; })
            .then(function (rows) {
                heatmapData = rows || [];
                renderHeatmap();
            })
            .catch(function () {
                heatmapData = [];
                boxEl.innerHTML = '<div class="quote-empty">불러오지 못했습니다.</div>';
            });
    }

    function setMarket(m) {
        if (GROUPS.indexOf(m) < 0 || m === market) return;
        market = m;
        syncTabs();
        loadHeatmap();
    }

    function syncTabs() {
        for (var i = 0; i < tabEls.length; i++) {
            tabEls[i].classList.toggle('active', tabEls[i].dataset.group === market);
        }
    }

    /* ── 시작 ──────────────────────────────────────────────────────────── */

    document.addEventListener('DOMContentLoaded', function () {
        rootEl = document.getElementById('quotesRoot');
        if (!rootEl) return;
        boxEl = document.getElementById('heatmapBox');
        tooltipEl = document.getElementById('heatmapTooltip');
        footEl = document.getElementById('heatmapFoot');
        legendEl = document.getElementById('heatmapLegend');
        tabEls = rootEl.querySelectorAll('.heatmap-tab');

        var d = (rootEl.dataset.market || '').toUpperCase();
        market = GROUPS.indexOf(d) >= 0 ? d : 'KR';
        syncTabs();
        renderLegend();

        for (var i = 0; i < tabEls.length; i++) {
            tabEls[i].addEventListener('click', function () {
                setMarket(this.dataset.group);
            });
        }

        // 타일마다 리스너를 달면 수백 개가 된다 — 상자 하나에서 위임한다.
        boxEl.addEventListener('mouseover', function (e) {
            var tile = e.target.closest ? e.target.closest('.heat-tile') : null;
            if (!tile) return;
            var d2 = heatmapData.filter(function (x) { return (x.market_cap || 0) > 0; })[+tile.dataset.idx];
            if (d2) showTooltip(e, d2);
        });
        boxEl.addEventListener('mousemove', moveTooltip);
        boxEl.addEventListener('mouseleave', hideTooltip);

        window.addEventListener('resize', function () {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(renderHeatmap, 150);
        });

        loadQuotes();
        loadHeatmap();
    });
})();
