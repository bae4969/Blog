/**
 * AI 상담 시트(2026-10-19) — 모든 화면 아래(root 전용, `_assistant.html`). 투자 계획 화면의 상담을 떼어 냈다.
 *
 * - 손잡이를 위로 쓸면 올라오고 아래로 내리면 접힌다(삼성페이 카드 꺼내듯). 누르기·키보드(Enter·Space)·Esc 로도 열고 닫는다.
 * - 보내는 말마다 **지금 화면의 맥락**을 함께 보낸다: 템플릿의 `assistant_ctx`(#aiCtx) + 화면 스크립트의
 *   `window.assistantContext()`(지금 고른 노드·설정 같은 바뀌는 상태) + 제목·주소.
 * - 상담은 화면을 모른다. AI 가 무언가 고치면 서버가 준 `changes` 를 토스트(+[되돌리기])로 띄우고
 *   `assistant:changed` 이벤트({source, data})로 알린다 — 그 화면(예: plan.js)이 듣고 다시 그린다.
 *   source 가 null 이면 "무엇이 바뀌었는지 모른다"(연결이 끊긴 뒤 등) — 화면이 알아서 다시 읽는다.
 * - 화면이 쓰는 것: `window.assistant.away(on)`(화면의 다른 시트가 떠 있는 동안 비킨다), `assistant:open` 이벤트.
 *
 * ⚠️ 휴대폰은 기다리는 사이 요청이 끊긴다(화면 꺼짐·앱 전환). 서버는 답을 끝까지 만들어 저장하므로, 끊기면
 *    `/chat/busy` 로 끝나길 기다렸다 기록을 다시 읽는다 — 다시 보내면 AI 가 같은 일을 두 번 했다(2026-10-14~16 운영 로그).
 *    다른 화면으로 옮겨도 이어 받게 보낸 때의 마지막 기록 번호를 sessionStorage(`ai-pending`)에 둔다.
 * ⚠️ 개인 데이터라 읽기도 Bearer 다 — 쿠키 세션에서 `/api/v1/auth/token` 으로 받는다(watchlist.js 와 같은 길).
 */
(function () {
    'use strict';

    var sheetEl = document.getElementById('aiSheet');
    if (!sheetEl) return;
    var grip = document.getElementById('aiGrip');
    var dim = document.getElementById('aiDim');
    var logEl = document.getElementById('aiLog');
    var form = document.getElementById('aiForm');
    var input = document.getElementById('aiInput');
    var fileInput = document.getElementById('aiFile');
    var thumbsEl = document.getElementById('aiThumbs');
    var sendBtn = document.getElementById('aiSend');

    var MAX_IMAGES = 4;
    var IMAGE_SIDE = 1600;
    var images = [];          // 보낼 이미지 data URL
    var busy = false;
    var loaded = null;        // 대화 기록을 읽었나(Promise) — 처음 열 때 읽는다
    var lastChatId = 0;       // 화면에 있는 마지막 기록 — 끊긴 뒤 다시 읽을 때 새 답이 왔는지 가른다
    //: 손가락이 주 입력인 기기 — Enter 는 줄바꿈, 보내기는 버튼(휴대폰 메신저처럼. 긴 글을 쓰다 Enter 로 잘못 보냈다)
    var coarse = window.matchMedia('(pointer: coarse)');
    var store = window.sessionStorage;

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
                    // 상담 실패(502)는 {message, changes} — 실패 전에 AI 가 고친 것이 있으면 changes 에 온다
                    var d = j.detail, msg = typeof d === 'string' ? d : d && d.message;
                    var err = new Error(msg || '요청 실패(' + r.status + ')');
                    err.status = r.status;   // 없으면 서버에 닿지 못한 것(연결 끊김) — send() 가 가른다
                    err.changes = d && d.changes;
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

    function changed(source, data) {
        document.dispatchEvent(new CustomEvent('assistant:changed', { detail: { source: source, data: data } }));
    }

    /** 지금 화면 — 템플릿이 알린 대상 + 화면 스크립트의 지금 상태 + 제목·주소. */
    function context() {
        var c = {};
        try { c = JSON.parse(document.getElementById('aiCtx').textContent || '{}') || {}; } catch (e) { c = {}; }
        if (typeof window.assistantContext === 'function') {
            try { Object.assign(c, window.assistantContext() || {}); } catch (e) { /* 화면 스크립트 오류로 상담을 막지 않는다 */ }
        }
        c.title = c.title || document.title.replace(/ · Developer Notes$/, '');
        c.path = location.pathname + location.search;
        return c;
    }

    // ── 대화 — 생김새는 30.ai_center 대화 화면을 따른다 ─────────
    //    내 말 = 오른쪽 연보라 말풍선(원문 그대로), AI = 전폭 카드("ASSISTANT"·시각), 아래에 떠 있는 입력 상자.

    /**
     * AI 답을 마크다운으로 그린다 — 30.ai_center 와 같은 marked(gfm·줄바꿈 살림) + DOMPurify 정화.
     * ⚠️ innerHTML 은 **정화한 결과에만** 쓴다 — AI 답엔 웹 검색 결과가 섞이므로 이 정화가 유일한 방어선이다.
     *    링크는 새 창, 표는 좁은 화면에서 가로로 밀리게 감싼다.
     */
    function richText(target, text) {
        if (!window.marked || !window.DOMPurify) { target.textContent = text; target.classList.add('is-plain'); return; }
        target.innerHTML = window.DOMPurify.sanitize(window.marked.parse(text, { gfm: true, breaks: true }));
        target.querySelectorAll('a').forEach(function (a) { a.target = '_blank'; a.rel = 'noopener noreferrer'; });
        target.querySelectorAll('table').forEach(function (t) {
            var wrap = el('div', 'ai-md-table');
            t.parentNode.insertBefore(wrap, t);
            wrap.appendChild(t);
        });
    }

    function clock(iso) {
        var d = iso ? new Date(iso.length === 19 ? iso + '+09:00' : iso) : new Date();
        var k = new Date(d.getTime() + 9 * 3600 * 1000), now = new Date(Date.now() + 9 * 3600 * 1000);
        var two = function (v) { return (v < 10 ? '0' : '') + v; };
        var hm = two(k.getUTCHours()) + ':' + two(k.getUTCMinutes());
        return k.toISOString().slice(0, 10) === now.toISOString().slice(0, 10) ? hm : (k.getUTCMonth() + 1) + '/' + k.getUTCDate() + ' ' + hm;
    }

    //: 대화 끝의 "요청중..." 줄(점은 CSS 가 움직인다) — 30.ai_center 와 같은 대기 표시.
    var waitEl = el('div', 'ai-wait', '요청중');
    var timer = null;

    function addMessage(m) {
        var empty = logEl.querySelector('.ai-empty');
        if (empty) empty.remove();
        var div;
        if (m.role === 'user') {
            // 서버가 맨 앞에 붙여 남긴 `[화면: …]` 은 말풍선 밖 작은 글자로
            var hit = /^\[화면: ([^\]\n]*)\]\n?/.exec(m.content), box = el('div');
            div = el('div', 'ai-msg ai-msg--user');
            // 서버는 "제목 · 주소" 로 남긴다 — 화면엔 제목만
            if (hit) box.appendChild(el('span', 'ai-msg__where', hit[1].replace(/ · \/\S*$/, '')));
            box.appendChild(el('div', 'ai-bubble', hit ? m.content.slice(hit[0].length) : m.content));
            div.appendChild(box);
        } else {
            div = el('article', 'ai-msg ai-msg--ai');
            var head = el('header', 'ai-msg__head', 'assistant');
            head.appendChild(el('time', 'ai-msg__time', clock(m.created_at)));
            div.appendChild(head);
            var body = el('div', 'ai-msg__body');
            richText(body, m.content);
            div.appendChild(body);
            if (m.meta && m.meta.badge) div.appendChild(el('span', 'ai-msg__badge', m.meta.badge));
        }
        logEl.insertBefore(div, waitEl.parentNode ? waitEl : null);
        logEl.scrollTop = logEl.scrollHeight;
        return div;
    }

    function emptyChat() {
        var box = el('div', 'ai-empty');
        box.appendChild(el('div', 'ai-empty__mark', '∅'));
        box.appendChild(el('p', null, '지금 보는 화면에 대해 묻거나, 투자 계획·보유 자산 화면을 첨부해 상담을 시작하세요.'));
        logEl.appendChild(box);
    }

    function showChats(chats) {
        logEl.textContent = '';
        if (!chats.length) emptyChat();
        chats.forEach(addMessage);
        lastChatId = chats.length ? chats[chats.length - 1].chat_id : 0;
        if (busy) logEl.appendChild(waitEl);
    }

    function load() {
        if (!loaded) {
            logEl.appendChild(el('p', 'ai-empty', '불러오는 중…'));
            loaded = api('GET', '/api/v1/assistant/chat').then(showChats, function (e) {
                loaded = null;
                logEl.textContent = '';
                window.toast('상담 기록을 불러오지 못했습니다: ' + e.message, 'error');
                throw e;
            });
        }
        return loaded;
    }

    function renderChips() {
        thumbsEl.textContent = '';
        thumbsEl.hidden = !images.length;
        images.forEach(function (src, i) {
            var chip = el('span', 'ai-chip');
            var img = el('img'); img.src = src; img.alt = '';
            chip.appendChild(img);
            chip.appendChild(el('span', 'ai-chip__name', '이미지 ' + (i + 1)));
            chip.appendChild(el('span', 'ai-chip__size', '(' + Math.round(src.length * 0.75 / 1024) + ' KB)'));
            var x = el('button', 'ai-chip__x');
            x.type = 'button';
            x.setAttribute('aria-label', '이미지 ' + (i + 1) + ' 빼기');
            x.innerHTML = '<svg class="c-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"'
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

    function setBusy(on) {
        busy = on;
        sendBtn.disabled = on;
        clearInterval(timer);
        if (on) {
            var t0 = Date.now();
            waitEl.textContent = '요청중';
            logEl.appendChild(waitEl);
            timer = setInterval(function () { waitEl.textContent = '요청중 · ' + Math.round((Date.now() - t0) / 1000) + '초'; }, 1000);
        } else {
            if (waitEl.parentNode) waitEl.remove();
            store.removeItem('ai-pending');
        }
        logEl.scrollTop = logEl.scrollHeight;
    }

    /** 모듈이 낸 바뀐 것 — 토스트(+[되돌리기])와 화면에 알리기. */
    function applyChanges(list) {
        (list || []).forEach(function (c) {
            changed(c.source);
            if (c.toast) {
                var u = c.undo;
                window.toast(c.toast, 'success', u ? { action: { label: u.label, onClick: function () {
                    api(u.method, u.url).then(function (res) {
                        changed(c.source, res);
                        window.toast(u.done, 'success');
                    }).catch(function (e) { window.toast('되돌리지 못했습니다: ' + e.message, 'error'); });
                } }, duration: 8000 } : {});
            }
            if (c.note) window.toast(c.note, 'error');
        });
    }

    function send() {
        if (busy) return;
        var text = input.value.trim();
        if (!text && !images.length) return;
        var ctx = context();
        var sent = { message: text, images: images.slice(), context: ctx };
        var shown = ['[화면: ' + ctx.title + ']', text, sent.images.length ? '[이미지 ' + sent.images.length + '장]' : '']
            .filter(Boolean).join('\n');
        var mine = addMessage({ role: 'user', content: shown });
        input.value = '';
        store.removeItem('ai-draft');
        images = [];
        renderChips();
        setBusy(true);
        store.setItem('ai-pending', String(lastChatId));

        api('POST', '/api/v1/assistant/chat', sent).then(function (r) {
            setBusy(false);
            lastChatId = r.chat_id;
            addMessage({ role: 'assistant', content: r.reply, meta: r.meta });
            arrived();
            applyChanges(r.changes);
        }).catch(function (e) {
            // 서버에 못 닿은 실패면 서버는 답을 끝까지 만들어 저장한다 — 끝나길 기다렸다 기록을 다시 읽는다.
            if (!e.status) {
                follow(lastChatId).then(function (got) {
                    if (got) { window.toast('연결이 끊긴 동안 온 답을 불러왔습니다', 'info'); arrived(); }
                    else failed(e);
                }, function () { failed(e); });
                return;
            }
            failed(e);
        });

        function failed(e) {
            setBusy(false);
            // 보낸 것을 되살려 다시 보낼 수 있게 한다.
            mine.remove();
            input.value = sent.message;
            images = sent.images;
            renderChips();
            if (!logEl.querySelector('.ai-msg')) emptyChat();
            // 실패해도 AI 가 그 전에 무언가 고쳤을 수 있다(쓰기는 그때그때 저장된다) — 알리고, 같은 요청을 되풀이하지
            // 않게 그때는 [다시 시도]를 뺀다(2026-10-14 검토).
            if (e.changes && e.changes.length) {
                e.changes.forEach(function (c) { changed(c.source); });
                window.toast('상담은 실패했지만 일부가 바뀌었습니다 — ' + e.changes.map(function (c) { return c.toast; }).join(' / ')
                             + ' · ' + e.message, 'error');
            } else if (!e.status) {
                changed(null);
                window.toast('상담 실패: ' + e.message + ' — 바뀐 것이 있는지 확인하세요', 'error');
            } else {
                window.toast('상담 실패: ' + e.message, 'error', { action: { label: '다시 시도', onClick: send } });
            }
        }
    }

    // 서버의 상담이 끝날 때까지 기다렸다(최대 12분 — codex 는 10분이면 끊긴다) 대화를 다시 그린다.
    // `since` 뒤에 새 답이 저장됐으면 true. 기다리는 동안의 연결 실패는 다시 묻는다(화면이 꺼져 있었을 수 있다).
    function follow(since) {
        var until = Date.now() + 12 * 60 * 1000;
        var later = function () { return new Promise(function (ok) { setTimeout(ok, 5000); }); };
        var poll = function () {
            return api('GET', '/api/v1/assistant/chat/busy').then(function (r) { return r.busy; }, function (e) {
                if (e.status || Date.now() > until) throw e;
                return true;
            }).then(function (still) {
                if (still) return later().then(poll);
                return api('GET', '/api/v1/assistant/chat');
            });
        };
        if (!busy) setBusy(true);
        return poll().then(function (chats) {
            var newest = chats.length ? chats[chats.length - 1].chat_id : 0;
            changed(null);   // 그 사이 무엇이 바뀌었는지 모른다 — 화면이 다시 읽는다
            setBusy(false);
            loaded = Promise.resolve();
            showChats(chats);
            return newest > since;
        });
    }

    // 대화 기록 아래 여백 = 떠 있는 입력 상자의 실제 높이 + 4px. 첨부 칩이 붙어 상자가 높아지면 따라간다.
    function fitLogPadding() {
        var bottom = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 4;
        logEl.style.paddingBottom = (form.offsetHeight + 4) + 'px';
        if (bottom) logEl.scrollTop = logEl.scrollHeight;
    }
    if (window.ResizeObserver) new ResizeObserver(fitLogPadding).observe(form);

    form.addEventListener('submit', function (e) { e.preventDefault(); send(); });
    input.addEventListener('keydown', function (e) {
        // 한글 조합 중 Enter 는 글자 확정이다 — 보내지 않는다.
        if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && !coarse.matches) { e.preventDefault(); send(); }
    });
    // 쓰던 글은 화면을 옮겨도 남는다(이미지는 남지 않는다)
    input.addEventListener('input', function () { store.setItem('ai-draft', input.value); });
    input.value = store.getItem('ai-draft') || '';
    input.addEventListener('paste', function (e) {
        var files = Array.prototype.map.call((e.clipboardData && e.clipboardData.items) || [], function (it) {
            return it.kind === 'file' ? it.getAsFile() : null;
        }).filter(Boolean);
        if (files.length) { e.preventDefault(); addFiles(files); }
    });
    document.getElementById('aiAttach').addEventListener('click', function () { fileInput.click(); });
    fileInput.addEventListener('change', function () { addFiles(fileInput.files); fileInput.value = ''; });
    if (coarse.matches) input.placeholder = '메시지 입력';

    // 시트 위의 휠은 페이지를 움직이지 않고 대화 기록만(넘치는 입력칸 위에서는 입력칸 먼저) 움직인다.
    // ⚠️ preventDefault 를 쓰려면 passive: false 여야 한다. 확대·축소(ctrl+휠)는 브라우저에 맡긴다.
    sheetEl.addEventListener('wheel', function (e) {
        if (e.ctrlKey) return;
        e.preventDefault();
        var t = e.target.closest('textarea'), box = t && t.scrollHeight > t.clientHeight ? t : logEl;
        box.scrollTop += e.deltaY * (e.deltaMode === 1 ? 16 : 1);
    }, { passive: false });

    // ── 시트 ───────────────────────────────────────────────
    //    끄는 동안은 손가락(마우스)을 따라 움직이고, 40px 넘게 움직였으면 그 방향으로 열고 닫는다.

    var drag = null, closedY = 0, swallowClick = false;

    function isOpen() { return sheetEl.classList.contains('is-open'); }
    function translateY() { return new DOMMatrix(getComputedStyle(sheetEl).transform).m42; }

    function set(open) {
        if (open === isOpen()) return;
        sheetEl.classList.toggle('is-open', open);
        dim.hidden = !open;
        grip.setAttribute('aria-expanded', String(open));
        grip.setAttribute('aria-label', open ? 'AI 상담 닫기' : 'AI 상담 열기');
        if (open) {
            grip.classList.remove('has-new');
            document.dispatchEvent(new CustomEvent('assistant:open'));
            load().catch(function () {});
            fitLogPadding();
            logEl.scrollTop = logEl.scrollHeight;
            if (!coarse.matches) input.focus({ preventScroll: true });
        }
    }

    /** 접혀 있는 동안 답이 오면 손잡이에 점을 찍는다. */
    function arrived() { if (!isOpen()) grip.classList.add('has-new'); }

    grip.addEventListener('pointerdown', function (e) {
        if (e.pointerType === 'mouse' && e.button !== 0) return;
        swallowClick = false;
        if (!isOpen()) closedY = translateY();   // 접힌 자리 — 열린 채 끌기 시작하면 앞서 잰 값을 쓴다
        drag = { y: e.clientY, base: translateY(), open: isOpen(), moved: false };
        grip.setPointerCapture(e.pointerId);
        sheetEl.classList.add('is-dragging');
    });
    grip.addEventListener('pointermove', function (e) {
        if (!drag) return;
        var dy = e.clientY - drag.y;
        if (Math.abs(dy) > 6) drag.moved = true;
        var max = closedY || sheetEl.offsetHeight;
        sheetEl.style.transform = 'translateY(' + Math.min(max, Math.max(0, drag.base + dy)) + 'px)';
    });
    function end(e) {
        if (!drag) return;
        var dy = e.clientY - drag.y, was = drag.open, moved = drag.moved;
        drag = null;
        sheetEl.classList.remove('is-dragging');
        sheetEl.style.transform = '';
        // 누르기는 여기서 연다/닫는다 — 손잡이에 포인터를 잡아 둔 터치에서는 click 이 오지 않는다(browserless 실측).
        // 오는 기기도 있어 뒤따르는 click 한 번은 삼킨다(다음 pointerdown 이 표시를 지운다). click 은 키보드 몫이다.
        swallowClick = true;
        set(!moved ? !was : dy < -40 ? true : dy > 40 ? false : was);
    }
    grip.addEventListener('pointerup', end);
    grip.addEventListener('pointercancel', end);
    grip.addEventListener('click', function () {
        if (swallowClick) { swallowClick = false; return; }
        set(!isOpen());
    });
    dim.addEventListener('click', function () { set(false); });
    document.addEventListener('keydown', function (e) {
        // 열린 모달(버전 기록 등)이 있으면 Esc 는 그 창 몫이다
        if (e.key === 'Escape' && isOpen() && !document.querySelector('dialog[open]')) set(false);
    });

    window.assistant = {
        /** 화면의 다른 아래 시트가 떠 있는 동안은 손잡이까지 내린다. */
        away: function (on) { sheetEl.classList.toggle('is-away', on); if (on) set(false); },
        open: function () { set(true); },
    };

    // 다른 화면에서 보낸 상담이 아직 돌고 있으면(보내고 화면을 옮긴 경우) 끝날 때까지 기다렸다 답을 띄운다.
    var pending = store.getItem('ai-pending');
    if (pending !== null) {
        follow(+pending || 0).then(function (got) { if (got) arrived(); }, function () { setBusy(false); });
    }
})();
