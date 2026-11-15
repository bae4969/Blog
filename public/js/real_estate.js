/* 지도·차트·지역 목록은 하나의 조건과 집계 응답을 공유한다. */
(() => {
    'use strict';
    const $ = id => document.getElementById(id);
    const root = $('realEstate');
    if (!root) return;
    const fmt = new Intl.NumberFormat('ko-KR');
    const compactCount = new Intl.NumberFormat('ko-KR', {notation:'compact', maximumFractionDigits:1});
    const css = getComputedStyle(document.documentElement);
    const color = name => css.getPropertyValue(name).trim();
    const palette = {up: color('--chart-up-color'), down: color('--chart-down-color'),
        text: color('--bae-text-primary'), dim: color('--bae-text-dim'), neutral: color('--bae-surface-alt'),
        grid: color('--bae-border'), accent: color('--bae-accent')};
    let geo, meta, data, region = 'KR', selected = null, pinned = null, period = -1;
    let requestId = 0, renderId = 0, navigationId = 0, controller, pollTimer, priceChart, volumeChart;
    let zoomFrame, zoomResolve, lastHoverEvent, updatingCharts = false;
    const reducedMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
    const maps = new Map();
    let volumeMax = 1;
    const params = new URLSearchParams(location.search);
    let viewStart = 0, viewEnd = -1, mapData = null;
    const bundles = new Map();
    const quarterIndex = label => { const [year,q] = label.split(' Q'); return Number(year)*4+Number(q)-1; };
    const viewLabel = i => data.regions[region]?.[i]?.rolling ? '최근 3개월' : data.periods[i];
    const number = n => n == null ? '—' : fmt.format(n);
    const percent = n => n == null ? '—' : `${n > 0 ? '+' : ''}${n.toFixed(2)}%`;
    const node = id => geo.nodes[id];
    const mapPoint = id => mapData?.map_summary[id];
    const mapPeriod = () => data ? `${viewLabel(viewStart)} ~ ${viewLabel(viewEnd)}` : '';
    const point = id => data?.regions[id]?.[period];
    const reliable = p => p && p.reliable && p.complete && p.comparison_complete !== false;
    const shortName = id => node(id).name.replace('특별자치도', '').replace('특별자치시', '').replace('특별시', '').replace('광역시', '');
    function fail(message) { $('reError').textContent = message; $('reError').hidden = false; }
    function make(tag, cls, text) {
        const el = document.createElement(tag); if (cls) el.className = cls;
        if (text != null) el.textContent = text; return el;
    }
    function stateURL(id = region) {
        const q = new URLSearchParams({region: id});
        if (data) { q.set('first',quarterIndex(data.periods[viewStart])); q.set('last',quarterIndex(data.periods[viewEnd])); }
        return `/real-estate?${q}`;
    }
    function saveURL(replace = false) { history[replace ? 'replaceState' : 'pushState']({}, '', stateURL()); }
    async function json(url, signal) {
        const response = await fetch(url, {signal});
        let body;
        try { body = await response.json(); } catch { throw new Error('서버 응답을 읽지 못했습니다.'); }
        if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : '조회 조건을 확인해 주세요.');
        return body;
    }
    async function load(push = true, background = false) {
        if (push) saveURL();
        const id = ++requestId;
        if (!background) invalidateMap();
        controller?.abort(); clearTimeout(pollTimer); controller = new AbortController();
        $('reError').hidden = true; $('reLoading').hidden = background; root.setAttribute('aria-busy', 'true');
        cancelAnimationFrame(periodFrame);
        if (!background) {
            data = null; period = -1; selected = pinned = null; cancelZoom(); ++navigationId; ++renderId;
            priceChart?.destroy(); volumeChart?.destroy(); priceChart = volumeChart = null;
            $('reRegionRows').replaceChildren();
            await render();
        }
        const targetRegion = region;
        const q = new URLSearchParams({region:targetRegion});
        const signal = controller.signal;
        const poll = async () => {
            try {
                const body = await json(`/api/v1/real-estate/explorer?${q}`, signal);
                if (id !== requestId || region !== targetRegion) return;
                if (body.pending) { $('reLoading').textContent = body.total ? `부동산 통계 준비 중 · ${Math.min(100,Math.round(body.processed / body.total * 100))}%` : '부동산 통계 준비 중…'; pollTimer = setTimeout(poll, 3000); return; }
                const atEnd = data && viewEnd === data.periods.length-1;
                if (data?.matrix.version !== body.matrix.version) bundles.clear();
                bundles.set(targetRegion,body);
                data = body; meta = body.metadata;
                if (!background || viewEnd < 0) restoreWindow(new URLSearchParams(location.search));
                else if (atEnd) { const count=viewEnd-viewStart+1; viewEnd=data.periods.length-1; viewStart=Math.max(0,viewEnd-count+1); }
                period = viewEnd;
                updateMap();
                $('reLoading').hidden = true; root.setAttribute('aria-busy', 'false');
                if (data.metadata.unmapped.length) fail('일부 지역은 현재 지도 경계와 연결되지 않았습니다. 분석 기준에서 확인할 수 있습니다.');
                await render(); saveURL(true);
            } catch (e) {
                if (e.name === 'AbortError' || id !== requestId) return;
                $('reLoading').hidden = true; root.setAttribute('aria-busy', 'false'); fail(e.message);
            }
        };
        poll();
    }
    function mapColor(p, metric) {
        if (!p || !p.complete || (metric === 'change' && !reliable(p))) return palette.neutral;
        const value = p[metric];
        if (value == null || value === 0) return palette.neutral;
        const strength = metric === 'count' ? 8 + 92 * Math.sqrt(Math.min(1, value / volumeMax)) :
            Math.abs(value) >= 10 ? 90 : Math.abs(value) >= 5 ? 72 : Math.abs(value) >= 2 ? 52 : 30;
        const base = metric === 'count' ? palette.accent : value > 0 ? palette.up : palette.down;
        return `color-mix(in srgb, ${base} ${strength}%, ${palette.neutral})`;
    }
    function detail(id) {
        const p = mapPoint(id);
        const status = !p ? '불러오는 중…' : !p.complete || p.comparison_complete === false ? '비교 기간 수집 미완료' : !p.reliable ? `표본 부족 · ${p.samples}개` : `연환산 ${percent(p.change)}`;
        return `${node(id).name} · ${mapPeriod()}\n${status}${p?.provisional ? ' · 잠정' : ''}\n거래 ${number(p?.count)}건 · 비교 표본 ${number(p?.samples)}개`;
    }
    function highlight() {
        $('reMap').classList.toggle('has-preview', !!selected && selected !== region);
        document.querySelectorAll('.re-map-region, .re-region-row').forEach(el => {
            el.classList.toggle('is-selected', el.dataset.region === selected);
        });
    }
    function select(id) {
        if (!node(id) || selected === id || zoomResolve) return;
        selected = id;
        highlight(); renderDetail(); renderCharts();
    }
    function clearRegionPreview(reset = false) {
        if (zoomResolve) return;
        if (reset === true) pinned = null;
        if (selected === pinned && reset !== true) return;
        selected = pinned;
        cancelAnimationFrame(periodFrame);
        if (data) period = viewEnd;
        lastHoverEvent = null;
        highlight(); renderDetail(); renderCharts();
    }
    function activateRegion(id) {
        if (zoomResolve) return;
        if (pinned === id) navigate(id);
        else { pinned = id; select(id); }
    }
    const mapViewBox = () => maps.get(region)?.viewBox || [0, 0, 640, 540];
    function cancelZoom() {
        cancelAnimationFrame(zoomFrame);
        if (zoomResolve) { zoomResolve(false); zoomResolve = null; }
        $('reMap').setAttribute('viewBox', mapViewBox().join(' '));
    }
    function zoomInto(id, outward = false) {
        const svg = $('reMap'), path = svg.querySelector(`[data-region="${id}"]`);
        if (!path || reducedMotion()) return Promise.resolve(true);
        const box = path.getBBox(), base = mapViewBox();
        const width = Math.max(box.width * 1.18, box.height * 1.18 * base[2] / base[3]);
        const height = width * base[3] / base[2];
        const close = [box.x + box.width / 2 - width / 2, box.y + box.height / 2 - height / 2, width, height];
        const from = outward ? close : base;
        const target = outward ? base : close;
        svg.setAttribute('viewBox',from.join(' '));
        return new Promise(resolve => {
            zoomResolve = resolve;
            const start = performance.now();
            const frame = now => {
                const t = Math.max(0, Math.min(1, (now - start) / 260)), ease = 1 - Math.pow(1 - t, 3);
                svg.setAttribute('viewBox', from.map((v,i) => v + (target[i] - v) * ease).join(' '));
                if (t < 1) zoomFrame = requestAnimationFrame(frame);
                else { svg.setAttribute('viewBox', target.join(' ')); zoomResolve = null; resolve(true); }
            };
            zoomFrame = requestAnimationFrame(frame);
        });
    }
    async function navigate(id, push = true) {
        if (!node(id)) return;
        if (id === region) { clearRegionPreview(true); return; }
        const sequence = ++navigationId;
        ++requestId; controller?.abort(); clearTimeout(pollTimer);
        root.setAttribute('aria-busy','false');
        cancelZoom();
        const previousRegion = region;
        const child = node(region).children.includes(id);
        try {
            if (!maps.has(id)) maps.set(id, await json(`/maps/real-estate/${id}.json`));
            if (sequence !== navigationId) return;
            let bundle = bundles.get(id);
            if (!bundle) bundle = await json(`/api/v1/real-estate/explorer?region=${encodeURIComponent(id)}`);
            if (sequence !== navigationId) return;
            if (bundle.pending) throw new Error('부동산 통계를 준비하고 있습니다. 잠시 후 다시 시도해 주세요.');
            if (bundle.matrix.version !== data.matrix.version) bundles.clear();
            bundles.set(id,bundle);
            if (child) select(id);
            if (child && !(await zoomInto(id))) return;
            if (sequence !== navigationId) return;
            region = id; selected = pinned = null;
            data = bundle; meta = bundle.metadata;
            restoreWindow(new URLSearchParams(location.search)); period=viewEnd; updateMap();
            root.setAttribute('aria-busy','false');
            if (push) saveURL();
            await render();
            if (sequence !== navigationId) return;
            if (!child) {
                let anchor = previousRegion;
                while (node(anchor).parent && node(anchor).parent !== region) anchor = node(anchor).parent;
                await zoomInto(anchor, true);
            } else if (!reducedMotion()) $('reMap').animate([{opacity:.5},{opacity:1}], {duration:180});
        } catch(e) { if(sequence === navigationId) { cancelZoom(); fail(e.message); } }
    }
    async function renderMap(epoch) {
        const current = region;
        if (!maps.has(current)) maps.set(current, await json(`/maps/real-estate/${current}.json`));
        if (epoch !== renderId) return;
        const svg = $('reMap'), ns = 'http://www.w3.org/2000/svg';
        const viewBox = maps.get(current).viewBox || [0, 0, 640, 540];
        svg.setAttribute('viewBox', viewBox.join(' ')); svg.replaceChildren();
        const defs=document.createElementNS(ns,'defs'), hatch=document.createElementNS(ns,'pattern');
        hatch.id='reMissing'; hatch.setAttribute('width','6'); hatch.setAttribute('height','6'); hatch.setAttribute('patternUnits','userSpaceOnUse');
        const background=document.createElementNS(ns,'rect'); background.setAttribute('width','6');background.setAttribute('height','6');background.setAttribute('fill',palette.neutral);
        const stripe=document.createElementNS(ns,'path');stripe.setAttribute('d','M0,6L6,0');stripe.setAttribute('stroke',palette.dim);stripe.setAttribute('stroke-width','1');
        hatch.append(background,stripe);defs.append(hatch);svg.append(defs);
        const features = maps.get(current).features;
        volumeMax = Math.max(1, ...features.map(f => mapPoint(f.id)?.complete ? mapPoint(f.id).count || 0 : 0));
        svg.classList.toggle('is-volume', $('reMetric').value === 'count');
        for (const feature of features) {
            const id = feature.id, p = document.createElementNS(ns, 'path');
            p.setAttribute('d', feature.path); p.setAttribute('fill-rule', 'evenodd');
            p.setAttribute('fill', !mapData ? palette.neutral : !mapPoint(id) || !mapPoint(id).complete || ($('reMetric').value === 'change' && !reliable(mapPoint(id))) ? 'url(#reMissing)' : mapColor(mapPoint(id), $('reMetric').value));
            p.classList.add('re-map-region'); p.dataset.region = id;
            p.setAttribute('tabindex', '0'); p.setAttribute('role', 'button'); p.setAttribute('aria-label', detail(id));
            p.addEventListener('click', () => activateRegion(id));
            p.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activateRegion(id); } });
            svg.appendChild(p);
        }
        // 작은 지역은 목록으로도 동일하게 탐색할 수 있다. 전국 라벨 충돌을 줄인다.
        const placed = [];
        const scale = Math.min(svg.clientWidth / viewBox[2], svg.clientHeight / viewBox[3]) || 1;
        const labelSize = Math.max(12, 11 / scale);
        for (const feature of features) {
            const [x, y] = feature.label, name = current === 'KR' ? shortName(feature.id) : node(feature.id).name;
            const width = name.length * labelSize;
            if (placed.some(b => Math.abs(b.x - x) < (b.width + width) / 2 && Math.abs(b.y - y) < labelSize * 1.5)) continue;
            const t = document.createElementNS(ns, 'text'); t.setAttribute('x', x); t.setAttribute('y', y);
            t.classList.add('re-map-label'); t.style.fontSize = labelSize + 'px'; t.textContent = name; svg.appendChild(t); placed.push({x,y,width});
        }
        for (const inset of maps.get(current).insets || []) {
            const [x,y,w] = inset.box;
            const label = document.createElementNS(ns,'text'); label.textContent = inset.name; label.setAttribute('x',x+w/2); label.setAttribute('y',y+12); label.style.fontSize=Math.max(10,9/scale)+'px'; label.classList.add('re-map-inset-label'); svg.append(label);
        }
        highlight();
        const metric = $('reMetric').value;
        const labels = metric === 'count' ? [...new Set([0,.0625,.25,.5625,1].map(t => Math.round(volumeMax*t)))].map(v => [v,compactCount.format(v)]) :
            [[-10,'−10%'],[-5,'−5%'],[-2,'−2%'],[0,'0'],[2,'+2%'],[5,'+5%'],[10,'+10%']];
        const missing = make('span', '', '표본 부족');
        const swatch = document.createElementNS(ns, 'svg'), legendDefs = document.createElementNS(ns, 'defs');
        swatch.setAttribute('viewBox', '0 0 12 8'); swatch.setAttribute('aria-hidden', 'true');
        const legendHatch = hatch.cloneNode(true); legendHatch.id = 'reLegendMissing'; legendDefs.append(legendHatch);
        const fill = document.createElementNS(ns, 'rect');
        fill.setAttribute('width', '12'); fill.setAttribute('height', '8'); fill.setAttribute('rx', '2'); fill.setAttribute('fill', 'url(#reLegendMissing)');
        swatch.append(legendDefs, fill); missing.prepend(swatch);
        $('reLegend').replaceChildren(...labels.map(([v,label]) => {
            const e = make('span', '', label), swatch = make('i');
            if (metric === 'count') e.title = number(v)+'건';
            swatch.style.background = mapColor({[metric]:v,reliable:true,complete:true}, metric); e.prepend(swatch); return e;
        }), missing);
    }
    function renderRows() {
        const children = node(region).children.length ? [...node(region).children] : [region];
        const sort = $('reSort').value;
        const cityRank = id => region !== 'KR' ? 0 : id === '11' ? -2 : id === '41' ? -1 : /(?:특별시|광역시|특별자치시)$/.test(node(id).name) ? 0 : id === '50' ? 1 : 2;
        children.sort((a,b) => sort === 'region' ? cityRank(a)-cityRank(b) || node(a).name.localeCompare(node(b).name, 'ko') :
            sort === 'name' ? node(a).name.localeCompare(node(b).name, 'ko') :
            (sort === 'change' ? (reliable(mapPoint(b)) ? mapPoint(b).change : -Infinity) - (reliable(mapPoint(a)) ? mapPoint(a).change : -Infinity) : (mapPoint(b)?.count || 0) - (mapPoint(a)?.count || 0)));
        document.querySelector('.re-regions').hidden = !node(region).children.length;
        $('reRegionRows').replaceChildren(...children.map(id => {
            const p = mapPoint(id), row = make('a','re-region-row'); row.href = stateURL(id); row.dataset.region = id;
            row.addEventListener('click', e => { if (!e.ctrlKey && !e.metaKey && !e.shiftKey) { e.preventDefault(); activateRegion(id); } });
            row.setAttribute('aria-label',detail(id));
            const name = make('span','re-region-name'); const label=make('b','',node(id).name); label.title=node(id).name;
            name.append(label); if (node(id).children.length) name.append(make('small','','›'));
            const value = reliable(p) ? percent(p.change) : !p ? '집계 중' : !p.complete || p.comparison_complete === false ? '미수집' : '표본 부족';
            const volume = $('reMetric').value === 'count';
            row.append(name, make('span', 're-region-value ' + (!volume && reliable(p) ? (p.change > 0 ? 're-up' : p.change < 0 ? 're-down' : '') : 're-muted'), !p ? '집계 중' : volume ? number(p.count)+'건' : value));
            return row;
        }));
    }
    // 홈 차트와 같은 슬롯 폭·상승/하락색. 선 데이터는 축/호버에만 사용한다.
    const candlePlugin = {
        id: 'realEstateCandles',
        afterDatasetsDraw(chart) {
            const candles = chart.data.datasets[0].candles;
            if (!candles) return;
            const {ctx, chartArea: area, scales: {x, y}} = chart;
            const width = Math.max(1, Math.min(48, (area.right - area.left) / candles.length * .6));
            ctx.save();
            ctx.beginPath(); ctx.rect(area.left, area.top, area.right-area.left, area.bottom-area.top); ctx.clip();
            candles.forEach((c, i) => {
                if (!c) return;
                const px = x.getPixelForValue(i), open = y.getPixelForValue(c.o), close = y.getPixelForValue(c.c);
                ctx.strokeStyle = ctx.fillStyle = c.c > c.o ? palette.up : c.c < c.o ? palette.down : palette.dim;
                ctx.lineWidth = 1;
                ctx.beginPath(); ctx.moveTo(px, y.getPixelForValue(c.h)); ctx.lineTo(px, y.getPixelForValue(c.l)); ctx.stroke();
                ctx.fillRect(px-width/2, Math.min(open, close), width, Math.max(1, Math.abs(open-close)));
            });
            ctx.restore();
        }
    };
    function renderCharts() {
        if (!data) return;
        const detailRegion = selected || region;
        const series = (data.regions[detailRegion] || []).slice(viewStart,viewEnd+1), metric = $('rePriceMetric').value;
        const unitText = metric === 'median' ? '억원' : '만원/㎡';
        const divisor = metric === 'median' ? 10000 : 1;
        const candles = series.map(p => {
            const c = p.complete && p.candle?.[metric];
            return c ? Object.fromEntries(Object.entries(c).map(([key,v])=>[key,v/divisor])) : null;
        });
        const values = candles.map(c=>c?.c ?? null);
        const bounds = candles.filter(Boolean).flatMap(c=>[c.l,c.h]);
        const priceText = v => v.toLocaleString('ko-KR', {maximumFractionDigits:2}) + unitText;
        const labels = data.periods.slice(viewStart,viewEnd+1).map((p,i) => (series[i]?.rolling ? '최근 3개월' : p) + (series[i]?.provisional ? ' · 잠정' : ''));
        const options = (kind) => ({responsive:true, maintainAspectRatio:false, animation:false,
            layout:{autoPadding:false,padding:{right:8}},
            interaction:{mode:'index',intersect:false},
            events:['mousemove','mouseout','touchstart','touchmove'],
            onHover: (_e, els) => {
                if (updatingCharts || _e.native === lastHoverEvent) return;
                lastHoverEvent = _e.native;
                if (els.length && els[0].index + viewStart !== period) syncPeriod(els[0].index + viewStart);
                const other = kind === 'price' ? volumeChart : priceChart;
                if (!other) return;
                other.setActiveElements(els.map(e => ({datasetIndex:0,index:e.index}))); other.render();
            },
            plugins:{legend:{display:false}, tooltip:{callbacks:{
                label: item => {
                    if (kind === 'volume') return `거래량 ${number(series[item.dataIndex].count)}건`;
                    const c = candles[item.dataIndex];
                    return c ? [`첫 달 ${priceText(c.o)}`, `최고 ${priceText(c.h)}`, `최저 ${priceText(c.l)}`, `마지막 달 ${priceText(c.c)}`] : '표본 부족';
                },
                labelColor: item => {
                    const c = candles[item.dataIndex];
                    const color = kind === 'price' && c ? c.c > c.o ? palette.up : c.c < c.o ? palette.down : palette.dim : palette.accent;
                    return {borderColor:color,backgroundColor:color};
                },
                afterBody: items => {
                    const p=series[items[0]?.dataIndex];
                    return p ? `${kind === 'price' ? '월 중위값 기준 · ' : ''}거래 ${number(p.count)}건${p.complete ? '' : '\n수집 미완료'}` : '';
                }
            }}},
            scales:{x:{offset:true,grid:{display:false},ticks:{display:kind==='volume',color:palette.dim,maxRotation:0,autoSkip:true,maxTicksLimit:5}},
                y:{type:kind==='price'?'logarithmic':'linear',afterFit:axis=>{axis.width=64;},beginAtZero:kind==='volume',
                    ...(kind==='price' && bounds.length ? {min:Math.min(...bounds)/1.05,max:Math.max(...bounds)*1.05} : {}),grid:{color:palette.grid},ticks:{color:palette.dim},title:{display:kind==='price',text:unitText,color:palette.dim}}}});
        const priceConfig = {type:'line',data:{labels,datasets:[{data:values,candles,
            showLine:false,pointRadius:0,pointHoverRadius:0,pointHitRadius:15}]},options:options('price'),plugins:[candlePlugin]};
        if (priceChart) { priceChart.data = priceConfig.data; priceChart.options = priceConfig.options; updatingCharts = true; try { priceChart.update('none'); } finally { updatingCharts = false; } }
        else priceChart = new Chart($('rePriceChart'), priceConfig);
        const volumeConfig = {type:'bar',data:{labels,datasets:[{data:series.map(p=>p.complete?p.count:null),
            backgroundColor:palette.grid,hoverBackgroundColor:palette.accent,borderRadius:3,maxBarThickness:48}]},options:options('volume')};
        if (volumeChart) { volumeChart.data = volumeConfig.data; volumeChart.options = volumeConfig.options; updatingCharts = true; try { volumeChart.update('none'); } finally { updatingCharts = false; } }
        else volumeChart = new Chart($('reVolumeChart'), volumeConfig);
        $('reChartEmpty').hidden = values.some(v=>v!=null);
        $('rePriceChart').setAttribute('aria-label', `${node(detailRegion).name} ${$('rePriceMetric').selectedOptions[0].text} 분기봉, 월 중위값 기준: ${labels.map((l,i)=>{const c=candles[i];return `${l} ${c ? `첫 달 ${priceText(c.o)}, 최고 ${priceText(c.h)}, 최저 ${priceText(c.l)}, 마지막 달 ${priceText(c.c)}` : '표본 부족'}`;}).join('; ')}`);
        $('reVolumeChart').setAttribute('aria-label', `${node(detailRegion).name} 거래량: ${labels.map((l,i)=>`${l} ${number(series[i]?.count)}건`).join(', ')}`);
    }
    function renderDetail() {
        const id = selected || region, p = point(id), metric = $('rePriceMetric').value;
        $('reDetailName').textContent = node(id).name;
        $('reDetailPeriod').textContent = data ? (p?.rolling ? '최근 3개월' : data.periods[period]) + (p?.provisional ? ' · 잠정' : '') : '';
        $('reEnter').hidden = id === region;
        $('reEnter').setAttribute('aria-label', node(id).name + '로 이동');
        const headline = $('reHeadline');
        headline.className = '';
        headline.textContent = p?.complete && p[metric] != null ? (p[metric] / (metric === 'median' ? 10000 : 1)).toLocaleString('ko-KR',{maximumFractionDigits:2}) + (metric === 'median' ? '억' : '만원/㎡') : '—';
        const comparison = mapPoint(id), annual = $('reAnnualChange');
        const available = reliable(comparison) && comparison.change != null;
        annual.textContent = available ? `연 ${percent(comparison.change)}` : !comparison ? '—' :
            !comparison.complete || comparison.comparison_complete === false ? '미수집' : '표본 부족';
        annual.className = available ? (comparison.change > 0 ? 're-up' : comparison.change < 0 ? 're-down' : '') : 're-muted';
        annual.setAttribute('aria-label', `${node(id).name} ${mapPeriod()} 연환산 상승률 ${annual.textContent}`);
        $('reVolumeValue').textContent = number(p?.count) + '건';
        $('reTrendTitle').textContent = node(id).name + ' 분기별 가격 봉차트';
        $('reSampleInfo').textContent = data ? `${node(id).name}. 지도는 ${mapPeriod()} 비교 표본 ${number(mapPoint(id)?.samples)}개를 ${number(mapData ? Number(mapData.map_years.toFixed(3)) : null)}년 간격으로 연환산합니다.${p?.rolling ? ` 최근 구간: ${p.start} ~ ${new Date(Date.parse(p.stop+'T00:00:00Z')-86400000).toISOString().slice(0,10)}. 지도 누적 거래량은 겹치는 기간을 중복 집계하지 않습니다.` : ''}` : '';
    }
    let periodFrame;
    function syncPeriod(index) {
        if (!data) return;
        period = Math.max(viewStart, Math.min(index, viewEnd));
        cancelAnimationFrame(periodFrame);
        periodFrame = requestAnimationFrame(() => {
            if (!data) return;
            renderDetail();
        });
    }
    async function render() {
        const epoch = ++renderId;
        cancelZoom();
        const ancestors=[]; for(let id=region;id;id=node(id).parent) ancestors.unshift(id);
        $('reBreadcrumb').replaceChildren(...ancestors.flatMap((id,i) => {
            const a=make('a','',node(id).name); a.href=stateURL(id);
            if(id===region) {
                a.textContent = `${shortName(id)} 전체`;
                a.setAttribute('aria-current','page');
                a.setAttribute('aria-label',`${node(id).name} 전체 통계 보기`);
            }
            a.addEventListener('click',e=>{if(e.ctrlKey||e.metaKey||e.shiftKey)return;e.preventDefault();navigate(id);});
            return i?[make('span','re-muted','›'),a]:[a];
        }));
        const p=mapPoint(region);
        $('reMapTitle').textContent=`${node(region).name}${data ? ' · '+mapPeriod() : ''}${p?.provisional?' · 잠정':''}`;
        $('reTrendTitle').textContent=`${node(region).name} 가격 추이`;
        $('reSourceInfo').textContent=`최근 성공 수집: ${data?.metadata.updated_at || meta?.updated_at || '확인 중'} (KST). 지도 경계: ${geo.boundary_date}.${data?.metadata.unmapped.length ? ' 미연결 코드: '+data.metadata.unmapped.join(', ') : ''}`;
        document.querySelectorAll("[data-select]").forEach(b => b.setAttribute("aria-pressed", $(b.dataset.select).value === b.dataset.value));
        document.querySelectorAll('[data-years]').forEach(button => {
            const count=Number(button.dataset.years)*4;
            button.disabled=!data || data.periods.length<count;
            button.setAttribute('aria-pressed',!!data && viewEnd===data.periods.length-1 && viewEnd-viewStart+1===count);
        });
        renderRows(); renderDetail(); renderCharts();
        try { await renderMap(epoch); } catch(e) { if(epoch===renderId) fail(`지도를 불러오지 못했습니다. ${e.message}`); }
    }
    function restoreWindow(query) {
        const base=quarterIndex(data.periods[0]), total=data.periods.length;
        const first=Number(query.get('first')), last=Number(query.get('last'));
        if (query.has('first') && query.has('last') && Number.isInteger(first) && Number.isInteger(last) && first>=base && last>first && last<base+total) {
            viewStart=first-base; viewEnd=last-base;
        } else {
            const legacy=query.get('span'), count=legacy==='all'?total:['1','3','5','10'].includes(legacy)?Number(legacy)*4:40;
            viewEnd=total-1; viewStart=Math.max(0,total-count);
        }
    }
    function invalidateMap() {
        mapData=null;
        root.dataset.rangeBusy='true';
        document.querySelector('.re-map-panel').setAttribute('aria-busy','true');
    }
    function updateMap() {
        if (!data?.matrix) return;
        const index=viewEnd*(viewEnd-1)/2+viewStart, summaries={};
        for (const [code,series] of Object.entries(data.regions)) {
            const points=series.slice(viewStart,viewEnd+1), cell=data.matrix.regions[code];
            const count=points.reduce((n,p)=>n+p.calendar_count,0);
            const samples=viewStart<viewEnd?cell.samples[index]:0;
            summaries[code]={count,change:viewStart<viewEnd?cell.rates[index]:null,samples,
                reliable:samples>=data.metadata.min_samples,complete:points.every(p=>p.complete),
                comparison_complete:viewStart<viewEnd?cell.complete[index]:false,
                provisional:points.some(p=>p.provisional)};
        }
        mapData={map_summary:summaries,map_years:(data.matrix.centers[viewEnd]-data.matrix.centers[viewStart])/365.2425};
        root.dataset.rangeBusy='false';
        document.querySelector('.re-map-panel').setAttribute('aria-busy','false');
    }
    function setWindow(start, count) {
        if(!data)return;
        count=Math.min(data.periods.length,Math.max(2,Math.round(count)));
        start=Math.max(0,Math.min(data.periods.length-count,Math.round(start)));
        if(viewStart===start&&viewEnd===start+count-1)return;
        viewStart=start;viewEnd=start+count-1;period=viewEnd;
        updateMap();clearChartPreview();saveURL(true);
        render();
    }
    document.querySelectorAll('[data-years]').forEach(button => button.addEventListener('click',()=>{
        if (!data) return;
        const count=Number(button.dataset.years)*4;
        setWindow(data.periods.length-count,count);
    }));
    function clearChartPreview() {
        if (data) syncPeriod(viewEnd);
        lastHoverEvent = null;
        [priceChart, volumeChart].forEach(chart => {
            if (!chart) return;
            chart.setActiveElements([]);
            chart.tooltip.setActiveElements([], {x:0,y:0});
            chart.render();
        });
    }
    ['rePriceChart', 'reVolumeChart'].forEach(id => {
        $(id).addEventListener('mouseleave', clearChartPreview);
        // Chart.js가 같은 프레임에 처리하는 터치 미리보기까지 지운다.
        const endTouch = () => requestAnimationFrame(() => requestAnimationFrame(clearChartPreview));
        $(id).addEventListener('touchend', endTouch);
        $(id).addEventListener('touchcancel', endTouch);
    });
    document.querySelectorAll('[data-select]').forEach(button => button.addEventListener('click', () => {
        $(button.dataset.select).value = button.dataset.value;
        render();
    }));
    ['reMetric','rePriceMetric'].forEach(id=>$(id).addEventListener('change',()=>render()));
    $('reSort').addEventListener('change',() => {renderRows(); highlight();});
    $('reEnter').addEventListener('click',()=>{if(selected)navigate(selected);});
    root.addEventListener('keydown',e=>{if(e.key==='Escape')clearRegionPreview(true);});
    $('reMap').addEventListener('click',e=>{if(data && !e.target.closest('.re-map-region'))clearRegionPreview(true);});
    $('reInfoButton').addEventListener('click',()=>{$('reInfo').showModal(); document.documentElement.style.overflow='hidden';});
    $('reCloseInfo').addEventListener('click',()=>$('reInfo').close());
    $('reInfo').addEventListener('close',()=>{document.documentElement.style.overflow='';});
    let backdropDown=false;
    const outside=e=>{const r=$('reInfo').getBoundingClientRect();return e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom;};
    $('reInfo').addEventListener('pointerdown',e=>{backdropDown=outside(e);});
    $('reInfo').addEventListener('pointerup',e=>{if(backdropDown&&outside(e))$('reInfo').close();backdropDown=false;});
    window.addEventListener('popstate',()=>{
        ++navigationId; cancelZoom(); selected = pinned = null;
        const p=new URLSearchParams(location.search);
        region=node(p.get('region'))?p.get('region'):'KR';
        if(data && bundles.has(region)) { data=bundles.get(region);restoreWindow(p);period=viewEnd;updateMap();render(); }
        else load(false);
    });
    let refreshTimer, refreshChecking = false, pageActive = true;
    const dataVersion = metadata => [metadata.snapshot_id, metadata.updated_at, metadata.last_month, metadata.as_of_month, metadata.collection_revision].join('|');
    async function refreshIfChanged() {
        if (!pageActive || document.hidden || !data || refreshChecking || root.getAttribute('aria-busy') === 'true') return;
        refreshChecking = true;
        const previous = data;
        try {
            const latest = await json('/api/v1/real-estate/metadata');
            if (pageActive && data === previous && dataVersion(latest) !== dataVersion(data.metadata)) load(false, true);
        } catch { /* 일시적인 갱신 확인 실패에도 마지막 통계는 유지한다. */ }
        finally { refreshChecking = false; }
    }
    function scheduleRefresh() {
        clearTimeout(refreshTimer);
        if (pageActive) refreshTimer = setTimeout(async()=>{await refreshIfChanged();scheduleRefresh();}, 300000);
    }
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshIfChanged();});
    window.addEventListener('focus', refreshIfChanged);
    window.addEventListener('pagehide',()=>{pageActive=false;controller?.abort();clearTimeout(pollTimer);clearTimeout(refreshTimer);});
    window.addEventListener('pageshow',e=>{pageActive=true;if(e.persisted && geo && meta){load(false);scheduleRefresh();}});
    async function init() {
        try {
            geo=await json('/maps/real-estate/regions.json');
            meta=await json('/api/v1/real-estate/metadata');
            region=node(params.get('region'))?params.get('region'):'KR';
            document.querySelectorAll('.re-page select, [data-select]').forEach(e => { e.disabled = false; });
            load(false);
            scheduleRefresh();
        } catch(e) { fail(e.message); }
    }
    let mapWidth = 0, resizeFrame;
    new ResizeObserver(entries => {
        const width = entries[0].contentRect.width;
        if (Math.abs(width - mapWidth) < 1) return;
        mapWidth = width; cancelAnimationFrame(resizeFrame);
        resizeFrame = requestAnimationFrame(() => { if (geo && meta) { ++navigationId; cancelZoom(); renderMap(++renderId).catch(e => fail(e.message)); } });
    }).observe($('reMap'));
    init();
})();
