/**
 * 종목 상세의 공시 카드 — `/api/v1/stocks/{code}/disclosures` 로 채운다.
 *
 * 한 건 = 분류 배지 · 쉬운 제목 · 그날 등락률 / 핵심 숫자(자사주 금액·지분 증감) / 날짜 · 제출인 · 원문 제목.
 * 법정 서식 이름은 맨 아래 줄로 내린다 — 그것만 보여 주면 아무도 안 읽는다(2026-09-29 사용자 지적).
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

    function item(d) {
        var li = document.createElement('li');
        if (d.category === 'admin') li.className = 'is-muted';
        var a = document.createElement('a');
        a.href = d.url;
        a.target = '_blank';
        a.rel = 'noopener';

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
        a.append(head);

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
