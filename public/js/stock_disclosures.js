/**
 * 종목 상세의 공시 카드 — `/api/v1/stocks/{code}/disclosures` 로 채운다.
 *
 * 한 건 = 분류 배지 · 쉬운 제목 · 그날 등락률 / AI 요약 / 핵심 숫자(자사주 금액·지분 증감) / 날짜 · 제출인 · 원문 제목.
 * 법정 서식 이름은 맨 아래 줄로 내린다 — 그것만 보여 주면 아무도 안 읽는다(2026-09-29 사용자 지적).
 *
 * 읽기 쉬운 원문이 있는 건(`has_detail`)은 누르면 **그 자리에서 펼친다** — AI 가 뽑은 핵심 사실, 정정 전 → 후,
 * 원문의 항목·값 표(문서형은 본문), DART 원문 링크. 원문이 없는 건은 예전처럼 DART 로 바로 간다.
 * ⚠️ 요약은 서버가 숫자 대조를 통과한 것만 준다(`verified`). 요약이 없으면 원문 표만 보인다.
 *
 * 칩(주요·지분·전체)을 누르면 처음부터 다시 받고, 목록 끝이 보이면 다음 쪽을 이어 붙인다(무한 스크롤).
 * ⚠️ 끝 표시(`sentinel`)는 **목록 안**의 마지막 줄이다. PC 에서는 목록이 스크롤 상자라, 밖에 두면
 *    늘 보이는 자리에 있어 쪽을 끝까지 연달아 받는다.
 * ⚠️ 보고서명·제출인은 DART 원문 문자열이다 — `innerHTML` 로 넣지 않는다.
 * ⚠️ 칩을 빠르게 바꾸면 늦게 온 옛 응답이 새 목록을 덮는다 — 요청 번호로 거른다.
 */
(function () {
    'use strict';

    var card = document.querySelector('[data-disc-code]');
    if (!card) return;

    var code = card.getAttribute('data-disc-code');
    var list = document.getElementById('discList');
    var SIZE = 10;
    var kind = 'major';
    var page = 0;
    var pages = 1;
    var loading = false;
    var seq = 0;

    var sentinel = document.createElement('li');
    sentinel.className = 'sd-disc__sentinel';
    sentinel.setAttribute('aria-hidden', 'true');

    function message(text) {
        var li = document.createElement('li');
        li.className = 'sd-exec__empty';
        li.textContent = text;
        return li;
    }

    function span(cls, text) {
        var el = document.createElement('span');
        el.className = cls;
        el.textContent = text;
        return el;
    }

    function el(tag, cls, text) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        if (text != null) e.textContent = text;
        return e;
    }

    function link(url) {
        var a = el('a', 'sd-disc__origin', 'DART 원문 보기');
        a.href = url;
        a.target = '_blank';
        a.rel = 'noopener';
        return a;
    }

    /** 항목·값 목록 — `dl` 한 줄에 이름과 값. */
    function pairs(cls, rows, name, value) {
        var dl = el('dl', 'sd-disc__pairs ' + cls);
        rows.forEach(function (r) {
            dl.append(el('dt', '', name(r)), el('dd', '', value(r)));
        });
        return dl;
    }

    function detail(res) {
        var frag = document.createDocumentFragment();
        if (res.changes.length) {
            frag.append(el('h3', 'sd-disc__sub', '정정 내용 · AI 요약'));
            var dl = el('dl', 'sd-disc__pairs sd-disc__pairs--ai');
            res.changes.forEach(function (c) {
                var dd = el('dd', '');
                dd.append(el('del', '', c.before), ' → ', el('ins', '', c.after));
                dl.append(el('dt', '', c.item), dd);
            });
            frag.append(dl);
        }
        if (res.facts.length) {
            frag.append(el('h3', 'sd-disc__sub', '핵심 사실 · AI 요약'),
                        pairs('sd-disc__pairs--ai', res.facts,
                              function (f) { return f.label; }, function (f) { return f.value; }));
        }
        if (res.fields.length) {
            frag.append(el('h3', 'sd-disc__sub', '원문'),
                        pairs('', res.fields, function (f) { return f.name; }, function (f) { return f.value; }));
        }
        if (res.body) {
            frag.append(el('h3', 'sd-disc__sub', '원문'), el('p', 'sd-disc__body', res.body));
            if (res.body_truncated) frag.append(el('p', 'sd-disc__note', '본문이 길어 여기까지만 보입니다.'));
        }
        frag.append(link(res.url));
        return frag;
    }

    /** 펼침 — 처음 열 때 한 번 받는다. 실패하면 닫아 두고 다시 누를 수 있게 한다. */
    function toggle(row, panel, d) {
        var open = row.getAttribute('aria-expanded') !== 'true';
        row.setAttribute('aria-expanded', open ? 'true' : 'false');
        panel.hidden = !open;
        if (!open || panel.dataset.loaded) return;
        panel.dataset.loaded = '1';
        panel.replaceChildren(el('p', 'sd-disc__note', '원문을 불러오는 중...'));
        fetch('/api/v1/stocks/' + encodeURIComponent(code) + '/disclosures/' + d.rcept_no)
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (res) { panel.replaceChildren(detail(res)); })
            .catch(function (e) {
                console.error('공시 원문 로드 실패:', e);
                delete panel.dataset.loaded;
                row.setAttribute('aria-expanded', 'false');
                panel.hidden = true;
                window.toast('공시 원문을 불러오지 못했습니다', 'error', {
                    action: { label: 'DART 에서 보기', onClick: function () { window.open(d.url, '_blank', 'noopener'); } }
                });
            });
    }

    var CHEVRON = '<svg class="sd-disc__chev" viewBox="0 0 24 24" width="16" height="16" fill="none" '
                + 'stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" '
                + 'aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>';

    function item(d) {
        var li = document.createElement('li');
        if (d.category === 'admin') li.className = 'is-muted';
        var a;
        if (d.has_detail) {
            a = el('button', 'sd-disc__row');
            a.type = 'button';
            a.setAttribute('aria-expanded', 'false');
        } else {
            a = el('a', 'sd-disc__row');
            a.href = d.url;
            a.target = '_blank';
            a.rel = 'noopener';
        }

        var head = span('sd-disc__head', '');
        head.append(span('sd-disc__cat sd-disc__cat--' + d.category, d.category_label));
        var title = span('sd-disc__title', d.label);
        if (d.tag) title.prepend(span('sd-disc__tag', d.tag));
        head.append(title);
        if (d.reaction != null) {
            var r = Math.round(d.reaction * 100) / 100;
            head.append(span('sd-disc__react ' + (r > 0 ? 'q-up' : (r < 0 ? 'q-down' : 'q-flat')),
                             (r > 0 ? '+' : '') + r.toFixed(2) + '%'));
        }
        if (d.has_detail) head.insertAdjacentHTML('beforeend', CHEVRON);
        a.append(head);

        if (d.summary) {
            var sum = span('sd-disc__sum', d.summary);
            sum.prepend(span('sd-disc__ai', 'AI 요약'));
            a.append(sum);
        }
        if (d.detail) a.append(span('sd-disc__detail', d.detail));

        var meta = span('sd-disc__meta', '');
        var time = document.createElement('time');
        time.dateTime = d.date;
        time.textContent = d.date.replace(/-/g, '.');
        meta.append(time, ' · ' + d.filer);
        // 쉬운 제목과 다를 때만 원문을 덧붙인다 — 모르는 서식은 이미 원문이 제목이다.
        if (d.label !== d.title) meta.append(' · ' + d.title);
        a.append(meta);

        li.append(a);
        if (d.has_detail) {
            var panel = el('div', 'sd-disc__panel');
            panel.hidden = true;
            a.addEventListener('click', function () { toggle(a, panel, d); });
            li.append(panel);
        }
        return li;
    }

    function load(reset) {
        if (!reset && (loading || page >= pages)) return;
        var my = ++seq;
        loading = true;
        if (reset) {
            page = 0;
            pages = 1;
            list.scrollTop = 0;
            list.replaceChildren(message('공시를 불러오는 중...'));
        }
        var url = '/api/v1/stocks/' + encodeURIComponent(code) + '/disclosures?kind=' + kind
                + '&page=' + (page + 1) + '&size=' + SIZE;
        fetch(url)
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (res) {
                if (my !== seq) return;
                loading = false;
                page = res.page;
                pages = res.pages;
                if (reset) list.replaceChildren();
                res.items.forEach(function (d) { list.append(item(d)); });
                if (!res.total) return list.append(message('공시가 없습니다.'));
                if (page < pages) {
                    // 끝 표시를 맨 뒤로 옮기고 다시 관찰한다 — 옮긴 뒤에도 계속 보이면(목록이 짧으면)
                    // 교차 "변화" 가 없어 콜백이 안 오고 멈춘다. `observe` 는 처음 한 번 현재 상태를 알린다.
                    list.append(sentinel);
                    io.unobserve(sentinel);
                    io.observe(sentinel);
                } else {
                    sentinel.remove();
                }
            })
            .catch(function (e) {
                if (my !== seq) return;
                loading = false;
                console.error('공시 로드 실패:', e);
                if (reset) list.replaceChildren(message('공시를 불러올 수 없습니다.'));
                else window.toast('공시를 더 불러오지 못했습니다', 'error');
            });
    }

    // 스크롤 상자(PC)든 페이지(모바일)든 끝 표시가 **실제로 보이면** 다음 쪽 — 조상의 잘림까지 계산된다.
    var io = new IntersectionObserver(function (entries) {
        if (entries.some(function (e) { return e.isIntersecting; })) load(false);
    });

    card.querySelectorAll('[data-disc-kind]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            if (btn.getAttribute('aria-pressed') === 'true') return;
            card.querySelectorAll('[data-disc-kind]').forEach(function (b) {
                b.setAttribute('aria-pressed', b === btn ? 'true' : 'false');
            });
            kind = btn.getAttribute('data-disc-kind');
            load(true);
        });
    });

    load(true);
})();
