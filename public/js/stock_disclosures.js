/**
 * 종목 상세의 공시 카드 — `/api/v1/stocks/{code}/disclosures` 로 채운다.
 *
 * 칩(주요·지분·전체)을 누르면 처음부터 다시 받고, "더 보기" 는 다음 쪽을 이어 붙인다.
 * ⚠️ 보고서명·제출인은 DART 원문 문자열이다 — `innerHTML` 로 넣지 않는다.
 * ⚠️ 칩을 빠르게 바꾸면 늦게 온 옛 응답이 새 목록을 덮는다 — 요청 번호로 거른다.
 */
(function () {
    'use strict';

    var card = document.querySelector('[data-disc-code]');
    if (!card) return;

    var code = card.getAttribute('data-disc-code');
    var list = document.getElementById('discList');
    var more = document.getElementById('discMore');
    var SIZE = 10;
    var kind = 'major';
    var page = 0;
    var seq = 0;

    function message(text) {
        var li = document.createElement('li');
        li.className = 'sd-exec__empty';
        li.textContent = text;
        return li;
    }

    function item(d) {
        var li = document.createElement('li');
        var a = document.createElement('a');
        a.href = d.url;
        a.target = '_blank';
        a.rel = 'noopener';

        var title = document.createElement('span');
        title.className = 'sd-disc__title';
        title.textContent = d.title;
        if (d.tag) {
            var tag = document.createElement('em');
            tag.className = 'sd-disc__tag';
            tag.textContent = d.tag;
            title.prepend(tag);
        }

        var meta = document.createElement('span');
        meta.className = 'sd-disc__meta';
        var time = document.createElement('time');
        time.dateTime = d.date;
        time.textContent = d.date.replace(/-/g, '.');
        meta.append(d.filer + ' · ', time);

        a.append(title, meta);
        li.append(a);
        return li;
    }

    function load(reset) {
        var my = ++seq;
        if (reset) {
            page = 0;
            list.replaceChildren(message('공시를 불러오는 중...'));
            more.hidden = true;
        }
        more.disabled = true;
        var url = '/api/v1/stocks/' + encodeURIComponent(code) + '/disclosures?kind=' + kind
                + '&page=' + (page + 1) + '&size=' + SIZE;
        fetch(url)
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (res) {
                if (my !== seq) return;
                page = res.page;
                if (reset) list.replaceChildren();
                res.items.forEach(function (d) { list.append(item(d)); });
                if (!res.total) list.append(message('공시가 없습니다.'));
                more.hidden = page >= res.pages;
                more.disabled = false;
            })
            .catch(function (e) {
                if (my !== seq) return;
                console.error('공시 로드 실패:', e);
                if (reset) list.replaceChildren(message('공시를 불러올 수 없습니다.'));
                else window.toast('공시를 더 불러오지 못했습니다', 'error');
                more.disabled = false;
            });
    }

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
    more.addEventListener('click', function () { load(false); });

    load(true);
})();
