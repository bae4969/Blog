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
 * ⚠️ (2026-09-22) 2열 배치 스크립트는 사라졌다. 배치는 `.post-grid` 가 CSS 로 한다 —
 *    여기서는 `#left` 에 카드를 붙이기만 하면 된다.
 *
 * 빌드 도구는 쓰지 않는다(사용자 결정 2026-08-19). 그래서 프레임워크 없이 DOM API 로만
 * 짠다 — 배포가 `git reset --hard` + 재시작 하나로 끝나는 성질을 유지하려는 것이다.
 */
(function () {
    'use strict';

    // 한 쪽에 12개.
    // ⚠️ 그리드 열 수(1·2·3)의 **공배수**여야 마지막 줄이 비지 않는다 — 10 이면
    //    3열에서 3+3+3+1 이라 끝에 카드 한 장만 남아 배치가 어긋나 보인다.
    //    열 수는 `.post-grid` 의 `auto-fill` 이 정하고 실측으로 1·2·3 뿐이다.
    var PER_PAGE = 12;
    //: 뒤로 왔을 때 되살릴 상한. API 가 `size` 를 100 까지만 받는다(`_MAX_SIZE`).
    var MAX_RESTORE = 96;

    var root, listEl, rightEl, moreEl, statusEl;
    //: 지금까지 붙인 쪽 수 · 불러오는 중인지 · 더 없는지 · 이미 붙인 글 id
    var loaded = 0, loading = false, done = false, seen = null, io = null;

    /** URL 에서 현재 **필터**를 읽는다. 딥링크·새로고침이 그대로 동작해야 한다.
     *  ⚠️ 무한 스크롤로 바뀌면서 `page` 는 상태가 아니다 — 아래 `restoreDepth()` 참조. */
    function readState() {
        var p = new URLSearchParams(location.search);
        return {
            category: p.get('category_index') || '',
            search: p.get('search_string') || ''
        };
    }

    /**
     * 처음에 몇 쪽치를 한 번에 받을지.
     *
     * 글을 읽고 **뒤로** 왔는데 목록이 첫 쪽으로 돌아가 있으면 무한 스크롤은 금방 짜증이
     * 난다. 대개는 브라우저 bfcache 가 DOM 째로 되살려 주지만(이 화면은 `no-store` 도
     * `unload` 핸들러도 없어 자격이 된다) 캐시에서 밀려나면 그냥 새로 그린다. 그래서
     * 스크롤할 때마다 `history.replaceState` 에 쪽 수를 적어 두고, 되살아나면 그만큼
     * 한 번에 받는다. 옛 `?page=N` 북마크도 같은 뜻으로 받아 준다.
     */
    function restoreDepth() {
        var fromState = history.state && history.state.blogLoaded;
        var fromUrl = parseInt(new URLSearchParams(location.search).get('page') || '0', 10);
        var n = Math.max(fromState || 0, fromUrl || 0, 1);
        return Math.min(n, Math.floor(MAX_RESTORE / PER_PAGE));
    }

    /** 상태 → 쿼리스트링. ⚠️ 값이 있을 때만 붙인다(`?` 만 남은 주소를 만들지 않는다). */
    function toQuery(s) {
        var parts = [];
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

    /** 버튼 아이콘 — 템플릿의 `_icons.html` 과 같은 선 두께·모서리를 쓴다.
     *  프로젝트 디자인 규칙: 버튼은 SVG 아이콘만 보이고 이름은 마우스를 올리면 뜬다. */
    var ICON = {
        more:  '<path d="m6 9 6 6 6-6"/>',
        retry: '<path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/>'
    };

    function iconEl(name) {
        var wrap = document.createElement('span');
        wrap.innerHTML = '<svg class="c-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
            + ' stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            + ICON[name] + '</svg>';
        return wrap.firstChild;
    }

    /** 아이콘 버튼 하나. 이름 span 은 ui.css 가 눈에만 숨기고 `tooltip.js` 가 풍선으로 띄운다. */
    function iconButton(cls, name, label) {
        var b = el('button', cls);
        b.type = 'button';
        b.appendChild(iconEl(name));
        b.appendChild(el('span', null, label));
        return b;
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
        // ⚠️ (2026-09-22) `div` + click 리스너였다. 진짜 `<a>` 로 바꾸면 **탭 순서·새 탭·
        //    가운데 클릭·크롤러**가 전부 따라온다 — 실측으로 /blog 의 탭 스톱이 10개뿐이고
        //    글 카드 10장이 통째로 포커스 불가였다.
        var box = el('a', 'posting' + (post.is_hidden ? ' posting-disabled' : ''));
        box.href = '/reader.php?posting_index=' + post.id;
        // ⚠️ 제목·요약 텍스트는 **안쪽 요소로 한 겹 감싼다.** `.posting` 이 그리드라
        //    그 직계 자식은 display 가 블록화되고, 그러면 `-webkit-box` 가
        //    `flow-root` 로 바뀌어 `-webkit-line-clamp` 가 말줄임표만 그리고
        //    **넘치는 줄을 안 자른다**(실측: 제목 3번째 줄이 요약과 겹쳐 보였다).
        //    한 겹 안쪽은 그리드 아이템이 아니라 클램프가 제대로 먹는다.
        var titleBox = el('h2', 'posting_title');
        titleBox.appendChild(el('span', 'posting_title_text', post.title));
        box.appendChild(titleBox);

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
            // 카드 전체가 링크라 썸네일은 장식이다 — 빈 alt 로 두면 스크린리더가
            // 제목을 두 번 읽지 않는다.
            img.alt = '';
            img.loading = 'lazy';
            img.decoding = 'async';
            tc.appendChild(img);
            wrap.appendChild(tc);
        }
        var s = (post.summary || '').trim();
        var sumBox = el('div', 'posting_summary');
        sumBox.appendChild(el('span', 'posting_summary_text',
            s ? (s.length > 200 ? s.slice(0, 200) + ' ...' : s) : '내용이 없습니다.'));
        wrap.appendChild(sumBox);
        box.appendChild(wrap);
        return box;
    }

    /**
     * 뉴스처럼 한 줄 — 인사이트(금융) 목록(`data-view="feed"`, 2026-09-23).
     * 제목 · 요약 두 줄 · 날짜·조회, 썸네일이 있으면 오른쪽에 작게. 긴 분석 글이라 카드보다
     * **제목을 훑기** 좋은 모양을 골랐다(토스증권 뉴스 목록과 같은 배치).
     */
    function feedRow(post) {
        var a = el('a', 'feed-item' + (post.is_hidden ? ' posting-disabled' : ''));
        a.href = '/reader.php?posting_index=' + post.id;
        var body = el('div', 'feed-item__body');
        var h = el('h2', 'feed-item__title');
        h.appendChild(el('span', null, post.title));
        body.appendChild(h);
        var s = (post.summary || '').trim();
        if (s) {
            var p = el('p', 'feed-item__summary');
            p.appendChild(el('span', null, s));
            body.appendChild(p);
        }
        var meta = el('p', 'feed-item__meta');
        meta.appendChild(el('span', null, fmt(post.created_at)));
        meta.appendChild(el('span', null, '조회 ' + (post.read_count || 0).toLocaleString()));
        body.appendChild(meta);
        a.appendChild(body);
        if (post.thumbnail_url) {
            var img = el('img', 'feed-item__thumb');
            img.src = post.thumbnail_url;
            img.alt = '';           // 행 전체가 링크라 장식이다(카드와 같은 이유)
            img.loading = 'lazy';
            img.decoding = 'async';
            a.appendChild(img);
        }
        return a;
    }

    /**
     * 목록 끝의 한 칸 — "더 보기" 버튼 · "불러오는 중…" · "마지막 글입니다" 중 하나.
     *
     * ⚠️ 스크롤만으로 더 불러오면 **키보드·스크린리더 사용자는 다음 글에 닿을 방법이
     *    없다**(발밑이 계속 늘어나 푸터에도 못 간다). 그래서 진짜 버튼을 두고,
     *    IntersectionObserver 는 그 버튼을 대신 눌러 주는 역할만 한다 — 경로가 하나라
     *    동작이 갈리지 않는다.
     */
    function renderMore() {
        moreEl.innerHTML = '';
        if (loading) {
            moreEl.appendChild(el('div', 'post-more__msg', '불러오는 중…'));
            return;
        }
        if (done) {
            // 한 쪽으로 끝나는 목록에 "마지막" 을 붙이면 군더더기다.
            if (loaded > 1) moreEl.appendChild(el('div', 'post-more__msg', '마지막 글입니다'));
            return;
        }
        var btn = iconButton('c-btn post-more__btn', 'more', '더 보기');
        btn.addEventListener('click', function () { loadMore(); });
        moreEl.appendChild(btn);
    }

    /** 끝 칸이 화면에 들어오면 다음 쪽을 미리 받는다. 600px 앞서 시작해 끊김을 줄인다. */
    function watchMore() {
        if (io) io.disconnect();
        if (!('IntersectionObserver' in window)) return;   // 없으면 버튼만으로 동작한다
        io = new IntersectionObserver(function (entries) {
            if (entries.some(function (e) { return e.isIntersecting; })) loadMore();
        }, { rootMargin: '600px 0px' });
        io.observe(moreEl);
    }

    /** 목록 자리에 남는 **상태 설명**(불러오는 중 · 글 없음 · 로드 실패).
     *  ⚠️ 이건 토스트가 아니다 — 토스트는 "일어난 일" 을 알리고 사라지지만, 여기는
     *     비어 있는 이유를 그 자리에서 설명해야 한다(프로젝트 디자인 규칙 참조). */
    function setStatus(msg) {
        statusEl.innerHTML = '';
        if (msg) statusEl.appendChild(el('div', 'alert alert-info', msg));
    }

    /** 필터를 갈아끼우고 목록을 처음부터 다시 그린다(칩·검색·뒤로가기). */
    function reset(state, depth) {
        if (io) io.disconnect();
        listEl.innerHTML = '';
        // ⚠️ `#right` 는 2열 배치와 함께 사라졌다(2026-09-22). 가드가 없으면 매 로드마다
        //    TypeError 로 목록이 **조용히** 안 뜬다 — init 의 가드에 rightEl 만 빠져 있었다.
        if (rightEl) rightEl.innerHTML = '';
        loaded = 0; loading = false; done = false;
        seen = Object.create(null);
        markActiveCategory(state.category);
        return fetchPage(state, 1, PER_PAGE * (depth || 1));
    }

    /** 다음 쪽을 이어 붙인다. */
    function loadMore() {
        if (loading || done) return;
        return fetchPage(readState(), loaded + 1, PER_PAGE);
    }

    /**
     * 한 번 받아서 **이어 붙인다**(지우지 않는다).
     *
     * ⚠️ `/api/v1/posts` 는 `posting_index DESC` 의 **offset 페이징**이다(커서가 아니다).
     *    내가 스크롤하는 사이에 글이 새로 올라오면 경계가 한 칸 밀려 같은 글이 두 번
     *    올 수 있다 — 그래서 붙인 id 를 기억해 두고 거른다. 반대로 한 글을 건너뛰는
     *    경우는 남지만, 그건 스크롤 도중에 글이 올라올 때뿐이라 실제로는 거의 없다.
     */
    function fetchPage(state, page, size) {
        loading = true;
        renderMore();
        if (loaded === 0) setStatus('불러오는 중…');

        var q = ['size=' + size, 'page=' + page];
        if (state.category) q.push('category=' + encodeURIComponent(state.category));
        if (state.search) q.push('q=' + encodeURIComponent(state.search));
        // 목록이 둘이다(2026-09-23) — 인사이트(finance) · 블로그(general).
        if (root.dataset.group) q.push('group=' + encodeURIComponent(root.dataset.group));

        return fetch('/api/v1/posts?' + q.join('&'), { headers: { 'Accept': 'application/json' } })
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (data) {
                loading = false;
                root.classList.remove('is-loading');   // 자리 잡기를 푼다(blog_index.html)
                var added = 0;
                data.items.forEach(function (p) {
                    if (seen[p.id]) return;          // offset 페이징 경계 중복 거르기
                    seen[p.id] = 1;
                    listEl.appendChild(root.dataset.view === 'feed' ? feedRow(p) : card(p));
                    added++;
                });
                // 받은 것이 size 만큼이면 그만큼 쪽을 앞당긴 것이다(되살릴 때 size 가 크다).
                loaded += Math.max(1, Math.ceil(data.items.length / PER_PAGE));
                if (data.page >= data.pages || data.items.length === 0) done = true;

                setStatus(loaded > 0 && Object.keys(seen).length === 0 ? '게시글이 없습니다.' : '');
                // 지금 깊이를 주소 기록에 남긴다 — 뒤로 왔을 때 그만큼 되살린다.
                try { history.replaceState({ blogLoaded: loaded }, '', location.href); } catch (e) {}
                renderMore();
                if (!done) watchMore(); else if (io) io.disconnect();

                // 화면이 아직 안 찼으면(가로 모드·큰 화면) 한 번 더 받는다 — 스크롤할
                // 것이 없어 관찰자가 영영 안 깨어나는 상태를 막는다.
                if (!done && added > 0 &&
                    document.documentElement.scrollHeight <= window.innerHeight + 100) {
                    return loadMore();
                }
            })
            .catch(function (e) {
                loading = false;
                root.classList.remove('is-loading');
                // ⚠️ 조용히 빈 화면을 두지 않는다. 서버 렌더 때는 실패가 곧 500 이라
                //    눈에 보였는데, 클라이언트 렌더는 아무 일도 없던 것처럼 보인다.
                //    프로젝트 디자인 규칙대로 **안내는 화면 아래 가운데 토스트**로 띄우고,
                //    다시 할 수 있는 일은 토스트 안에 버튼으로 붙인다.
                if (window.toast) {
                    window.toast('목록을 불러오지 못했습니다.', 'error',
                                 { action: { label: '다시 시도', onClick: function () {
                                     if (loaded === 0) reset(readState(), 1); else loadMore();
                                 } } });
                }
                if (loaded === 0) {
                    // 첫 로드가 실패하면 자리 설명이 필요하다(토스트는 사라진다).
                    setStatus('목록을 불러오지 못했습니다.');
                    listEl.innerHTML = '';
                } else {
                    moreEl.innerHTML = '';
                    var retry = iconButton('c-btn post-more__btn', 'retry', '다시 시도');
                    retry.addEventListener('click', function () { loadMore(); });
                    moreEl.appendChild(retry);
                }
                if (window.console) console.error('목록 로드 실패', e);
            });
    }

    /** 칩에서 지금 카테고리를 표시한다(서버가 하던 일). */
    function markActiveCategory(category) {
        var want = String(category || '');
        document.querySelectorAll('.c-cats .c-chip').forEach(function (a) {
            var raw = a.getAttribute('data-category-index') || '-1';
            var v = raw === '-1' ? '' : raw;
            if (v === want) a.setAttribute('aria-current', 'true');
            else a.removeAttribute('aria-current');
        });
    }

    /** 필터를 바꾸고 주소·목록을 함께 갱신한다. */
    function go(patch) {
        var state = Object.assign(readState(), patch);
        // 검색 폼의 hidden 카테고리를 지금 상태에 맞춘다 — 안 맞추면 다음 검색이
        // 옛 카테고리로 나간다(칩으로 바꾼 뒤 검색하는 흔한 순서에서 드러난다).
        var hidden = document.querySelector('.c-search input[name="category_index"]');
        if (hidden) hidden.value = state.category || '-1';
        // 필터가 바뀌면 깊이는 1 로 되돌린다 — 주소에 `page` 를 남기지 않는다.
        history.pushState({ blogLoaded: 1 }, '', (root.dataset.path || '/blog') + toQuery(state));
        window.scrollTo({ top: 0, behavior: 'smooth' });
        reset(state, 1);
    }

    function init() {
        root = document.getElementById('postings');
        if (!root) return;
        listEl = document.getElementById('left');
        rightEl = document.getElementById('right');
        moreEl = document.getElementById('blogMore');
        statusEl = document.getElementById('blogStatus');
        if (!listEl || !moreEl || !statusEl) return;

        // 카테고리 칩 — 서버가 진짜 `<a href>` 로 그린다(JS 가 꺼져도 동작한다).
        // 여기서는 **가로채서** 새로고침 없이 거른다. 위임이라 칩이 늘어도 그대로 돈다.
        // ⚠️ 새 탭·가운데 클릭·보조키 조합은 가로채지 않는다 — 브라우저에 맡긴다.
        var cats = document.querySelector('.c-cats');
        if (cats) {
            cats.addEventListener('click', function (e) {
                var a = e.target.closest('.c-chip');
                if (!a || !cats.contains(a)) return;
                if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
                e.preventDefault();
                var raw = a.getAttribute('data-category-index') || '-1';
                go({ category: raw === '-1' ? '' : raw });
            });
        }

        // 검색 폼도 같은 방식 — 폼 자체는 GET 이라 JS 없이도 동작한다.
        var form = document.querySelector('.c-search');
        if (form) {
            form.addEventListener('submit', function (e) {
                e.preventDefault();
                var textEl = form.querySelector('input[name="search_string"]');
                var catEl = form.querySelector('input[name="category_index"]');
                var cat = catEl ? catEl.value : '-1';
                go({ category: cat === '-1' ? '' : cat,
                     search: textEl ? textEl.value.trim() : '' });
            });
        }

        // 뒤로/앞으로 — 주소만 바뀌므로 목록을 다시 그린다. bfcache 로 되살아나면
        // 여기까지 오지 않는다(DOM 이 그대로다).
        window.addEventListener('popstate', function () { reset(readState(), restoreDepth()); });

        reset(readState(), restoreDepth());
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
