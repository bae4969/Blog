/**
 * 블로그 목록 — 서버가 아니라 `/api/v1/posts` 를 읽어 그린다.
 *
 * 껍데기(레이아웃·헤더·사이드바)는 그대로 서버가 그린다. 여기서 맡는 것은 **글 카드와
 * 페이저**뿐이다. 그래야 한 화면씩 옮기면서 문제가 생겨도 그 화면만 되돌릴 수 있다.
 *
 * ⚠️ **마크업이 서버 렌더와 한 글자도 달라지면 안 된다.** `public/css/blog.css` 가
 *    `.posting > .posting_content_wrapper > .posting_thumbnail_container` 같은 중첩에
 *    의존한다(래퍼를 빼고 그렸다가 카드 레이아웃이 통째로 깨진 적이 있다).
 *
 * ⚠️ 2열 배치는 건드리지 않는다. `blog_index.html` 의 MutationObserver 가 `#postings`
 *    변화를 보고 알아서 다시 배치한다 — 여기서는 DOM 만 갈아끼우면 된다.
 *
 * 빌드 도구는 쓰지 않는다(사용자 결정 2026-08-19). 그래서 프레임워크 없이 DOM API 로만
 * 짠다 — 배포가 `git reset --hard` + 재시작 하나로 끝나는 성질을 유지하려는 것이다.
 */
(function () {
    'use strict';

    var PER_PAGE = 10;
    var root, listEl, rightEl, pagerEl, statusEl;

    /** URL 에서 현재 상태를 읽는다. 딥링크·새로고침이 그대로 동작해야 한다. */
    function readState() {
        var p = new URLSearchParams(location.search);
        return {
            page: Math.max(1, parseInt(p.get('page') || '1', 10) || 1),
            category: p.get('category_index') || '',
            search: p.get('search_string') || ''
        };
    }

    /** 상태 → 쿼리스트링. ⚠️ 값이 있을 때만 붙인다 — 1쪽이 `?page=1` 이 되면 옛 URL 과 달라진다. */
    function toQuery(s) {
        var parts = [];
        if (s.page > 1) parts.push('page=' + s.page);
        if (s.category) parts.push('category_index=' + encodeURIComponent(s.category));
        if (s.search) parts.push('search_string=' + encodeURIComponent(s.search));
        return parts.length ? '?' + parts.join('&') : '';
    }

    /**
     * ⚠️ `new Date(iso)` 를 쓰지 않는다. API 가 주는 값은 시간대 표기가 없는데 **실제로는
     *    KST** 다(DB 가 KST 로 들고 있다). Date 로 파싱하면 브라우저 시간대에 따라 9시간씩
     *    밀린다 — 문자열을 그대로 자른다. 서버가 찍던 `%Y-%m-%d %H:%M` 과 같은 모양이다.
     */
    function fmt(iso) {
        return iso ? String(iso).slice(0, 16).replace('T', ' ') : '';
    }

    function el(tag, cls, text) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        // ⚠️ 항상 textContent 다. 제목·요약·글쓴이는 사용자 입력이라 innerHTML 로 넣으면
        //    그대로 XSS 가 된다(서버는 Jinja 가 자동 이스케이프해 준다).
        if (text != null) e.textContent = text;
        return e;
    }

    /** 글 카드 하나. 서버 렌더(`blog_index.html`)와 같은 구조·클래스여야 한다. */
    function card(post) {
        var box = el('div', 'posting' + (post.is_hidden ? ' posting-disabled' : ''));
        box.addEventListener('click', function () {
            location.href = '/reader.php?posting_index=' + post.id;
        });
        box.appendChild(el('div', 'posting_title', post.title));

        var meta = el('div', 'post-meta');
        meta.appendChild(el('span', 'post-category', (post.category && post.category.name) || '미분류'));
        meta.appendChild(el('span', 'post-author', post.author || '익명'));
        meta.appendChild(el('span', 'post-date', fmt(post.created_at)));
        // 수정된 글에만 붙는다 — 작성 시각과 다를 때만(서버와 같은 조건).
        if (post.updated_at && post.updated_at !== post.created_at) {
            meta.appendChild(el('span', 'post-updated', '(수정: ' + fmt(post.updated_at) + ')'));
        }
        meta.appendChild(el('span', 'post-read-count', '조회: ' + (post.read_count || 0).toLocaleString()));
        box.appendChild(meta);
        box.appendChild(document.createElement('hr'));

        var wrap = el('div', 'posting_content_wrapper' + (post.thumbnail_url ? '' : ' no-thumbnail'));
        if (post.thumbnail_url) {
            var tc = el('div', 'posting_thumbnail_container');
            var img = el('img', 'posting_thumbnail');
            img.src = post.thumbnail_url;
            img.alt = '썸네일';
            img.loading = 'lazy';
            tc.appendChild(img);
            wrap.appendChild(tc);
        }
        var s = (post.summary || '').trim();
        wrap.appendChild(el('div', 'posting_summary',
            s ? (s.length > 200 ? s.slice(0, 200) + ' ...' : s) : '내용이 없습니다.'));
        box.appendChild(wrap);
        return box;
    }

    /** 페이저 — 현재 쪽 좌우 4개 + 첫·마지막, 끊기면 …. 서버 규칙과 같다. */
    function renderPager(state, pages) {
        pagerEl.innerHTML = '';
        // ⚠️ 비워 두는 것만으로는 부족하다. `.pagination` 은 `margin-top: 20px` 이라
        //    빈 채로 남으면 한 쪽짜리 목록 밑에 여백만 생긴다(서버 렌더는 아예 안 그렸다).
        pagerEl.style.display = pages > 1 ? '' : 'none';
        if (pages <= 1) return;

        var start = Math.max(1, state.page - 4);
        var end = Math.min(pages, state.page + 4);

        function link(p, label) {
            var a = el('a', 'page-link', label == null ? String(p) : label);
            a.href = toQuery({ page: p, category: state.category, search: state.search }) || '/blog';
            a.addEventListener('click', function (ev) { ev.preventDefault(); go({ page: p }); });
            return a;
        }
        function dots() { return el('span', 'page-ellipsis', '…'); }

        if (state.page > 1) pagerEl.appendChild(link(state.page - 1, '←'));
        if (start > 1) {
            pagerEl.appendChild(link(1));
            if (start > 2) pagerEl.appendChild(dots());
        }
        for (var p = start; p <= end; p++) {
            if (p === state.page) pagerEl.appendChild(el('span', 'page-link page-current', String(p)));
            else pagerEl.appendChild(link(p));
        }
        if (end < pages) {
            if (end < pages - 1) pagerEl.appendChild(dots());
            pagerEl.appendChild(link(pages));
        }
        if (state.page < pages) pagerEl.appendChild(link(state.page + 1, '→'));
    }

    function setStatus(msg) {
        statusEl.innerHTML = '';
        if (msg) statusEl.appendChild(el('div', 'alert alert-info', msg));
    }

    function load(state) {
        var q = ['size=' + PER_PAGE, 'page=' + state.page];
        if (state.category) q.push('category=' + encodeURIComponent(state.category));
        if (state.search) q.push('q=' + encodeURIComponent(state.search));

        setStatus('불러오는 중…');
        return fetch('/api/v1/posts?' + q.join('&'), { headers: { 'Accept': 'application/json' } })
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (data) {
                setStatus(data.items.length ? '' : '게시글이 없습니다.');
                listEl.innerHTML = '';
                rightEl.innerHTML = '';
                data.items.forEach(function (p) { listEl.appendChild(card(p)); });
                renderPager(state, data.pages);
                markActiveCategory(state.category);
            })
            .catch(function (e) {
                // ⚠️ 조용히 빈 화면을 두지 않는다. 서버 렌더 때는 실패가 곧 500 이라
                //    눈에 보였는데, 클라이언트 렌더는 아무 일도 없던 것처럼 보인다.
                setStatus('목록을 불러오지 못했습니다. 새로고침 해주세요.');
                listEl.innerHTML = '';
                if (window.console) console.error('목록 로드 실패', e);
            });
    }

    /** 사이드바에서 지금 카테고리를 표시한다(서버가 하던 일). */
    function markActiveCategory(category) {
        var want = String(category || '');
        document.querySelectorAll('#category li.category').forEach(function (li) {
            // 서버가 그린 `onclick="selectCategory(4)"` 에서 번호를 읽는다. 마크업에
            // data 속성을 새로 붙이지 않으려는 것이다(사이드바는 공용이다).
            var m = /selectCategory\((-?\d+)\)/.exec(li.getAttribute('onclick') || '');
            var v = m ? (m[1] === '-1' ? '' : m[1]) : '';
            li.classList.toggle('category-selected', v === want);
        });
    }

    /** 상태를 바꾸고 주소·목록을 함께 갱신한다. */
    function go(patch, replace) {
        var state = Object.assign(readState(), patch);
        if (patch.page === undefined) state.page = 1;   // 필터가 바뀌면 1쪽으로
        var url = '/blog' + toQuery(state);
        history[replace ? 'replaceState' : 'pushState'](null, '', url);
        load(state);
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    function init() {
        root = document.getElementById('postings');
        if (!root) return;
        listEl = document.getElementById('left');
        rightEl = document.getElementById('right');
        pagerEl = document.getElementById('blogPager');
        statusEl = document.getElementById('blogStatus');
        if (!listEl || !pagerEl || !statusEl) return;

        // 사이드바는 `layout.html` 이 `onclick="selectCategory(n)"` 로 그린다. 마크업을
        // 건드리는 대신 **그 전역 함수를 갈아끼운다** — 사이드바는 관리자·주식 화면도
        // 함께 쓰므로 손대면 그쪽까지 검증해야 한다.
        window.selectCategory = function (idx) {
            go({ category: idx === -1 ? '' : String(idx) });
        };
        window.searchPostingClick = function () {
            var catEl = document.getElementById('search_category_list');
            var textEl = document.getElementById('search_posting_text');
            var cat = catEl ? catEl.value : '-1';
            go({ category: cat === '-1' ? '' : cat,
                 search: textEl ? textEl.value.trim() : '' });
        };

        // 뒤로/앞으로 — 주소만 바뀌므로 목록을 다시 읽는다.
        window.addEventListener('popstate', function () { load(readState()); });

        load(readState());
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
