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
    var expandBtn = document.getElementById('aiExpand');
    var newChatBtn = document.getElementById('aiNewChat');

    var MAX_IMAGES = 4;
    var IMAGE_SIDE = 1600;
    var images = [];          // 보낼 이미지 data URL
    var busy = false;
    var sending = false;      // 이 탭이 직접 POST /chat 을 기다리는 중
    var hasLoaded = false;    // 대화 기록을 최소 1회 읽었나
    var chatSig = '';         // 마지막으로 그린 대화 시그니처(바뀔 때만 다시 그린다)
    var syncPromise = null;   // 진행 중인 동기화 요청(중복 호출 방지)
    var followPromise = null; // 진행 중인 busy 폴링(중복 폴링 방지)
    var pendingText = null;   // 다른 기기·이전 탭에서 진행 중인 사용자 질문
    var lastChatId = 0;       // 화면에 있는 마지막 기록 — 끊긴 뒤 다시 읽을 때 새 답이 왔는지 가른다
    var sseAbort = null;      // 열린 시트의 실시간 SSE 연결 중단기
    var sseRetryTimer = null;
    var sseBackoff = 2000;
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

    function chatsSig(chats) {
        if (!chats.length) return '0';
        return chats.length + ':' + chats[0].chat_id + ':' + chats[chats.length - 1].chat_id;
    }

    function clearPendingBubbles() {
        logEl.querySelectorAll('[data-pending="1"]').forEach(function (n) { n.remove(); });
    }

    function showPendingBubble(content) {
        clearPendingBubbles();
        if (!content) return;
        var node = addMessage({ role: 'user', content: content });
        node.setAttribute('data-pending', '1');
    }

    function showChats(chats) {
        logEl.textContent = '';
        chatSig = chatsSig(chats);
        if (!chats.length && !pendingText) emptyChat();
        chats.forEach(addMessage);
        lastChatId = chats.length ? chats[chats.length - 1].chat_id : 0;
        if (busy) {
            if (pendingText) showPendingBubble(pendingText);
            logEl.appendChild(waitEl);
            logEl.scrollTop = logEl.scrollHeight;
        }
    }

    function load() {
        return sync(false);
    }

    /** 서버의 최신 대화와 진행 중(busy) 상태를 동기화한다 — PC·폰 다중 기기·새 탭 모두 같은 상태를 본다. */
    function sync(silent) {
        if (sending) return Promise.resolve();
        if (syncPromise) return syncPromise;
        if (!hasLoaded && !silent) {
            logEl.textContent = '';
            logEl.appendChild(el('p', 'ai-empty', '불러오는 중…'));
        }
        syncPromise = Promise.all([
            api('GET', '/api/v1/assistant/chat'),
            api('GET', '/api/v1/assistant/chat/busy')
        ]).then(function (res) {
            syncPromise = null;
            var chats = res[0], b = res[1];
            var nextSig = chatsSig(chats);
            var first = !hasLoaded;
            hasLoaded = true;
            if (b && b.busy) {
                pendingText = b.message || pendingText;
                if (first || nextSig !== chatSig) showChats(chats);
                else if (pendingText && !logEl.querySelector('[data-pending="1"]')) showPendingBubble(pendingText);
                follow(lastChatId, b).then(function (got) { if (got) arrived(); }, function () { setBusy(false); });
            } else {
                pendingText = null;
                if (busy && !followPromise) setBusy(false);
                if (first || nextSig !== chatSig) showChats(chats);
            }
        }, function (e) {
            syncPromise = null;
            if (!hasLoaded) {
                logEl.textContent = '';
                if (!silent) window.toast('상담 기록을 불러오지 못했습니다: ' + e.message, 'error');
            }
            if (!silent) throw e;
        });
        return syncPromise;
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

    function setBusy(on, startedAt) {
        busy = on;
        sendBtn.disabled = on;
        newChatBtn.disabled = on;
        clearInterval(timer);
        if (on) {
            var parsed = startedAt ? Date.parse(startedAt) : NaN;
            var t0 = isFinite(parsed) ? Math.min(parsed, Date.now()) : Date.now();
            var tick = function () {
                var sec = Math.max(0, Math.round((Date.now() - t0) / 1000));
                waitEl.textContent = sec > 0 ? '요청중 · ' + sec + '초' : '요청중';
            };
            tick();
            logEl.appendChild(waitEl);
            timer = setInterval(tick, 1000);
        } else {
            pendingText = null;
            clearPendingBubbles();
            if (waitEl.parentNode) waitEl.remove();
            store.removeItem('ai-pending');
        }
        logEl.scrollTop = logEl.scrollHeight;
    }

    newChatBtn.addEventListener('click', function () {
        if (busy) return;
        sending = true;
        setBusy(true);
        api('POST', '/api/v1/assistant/chat/new').then(function () {
            sending = false;
            hasLoaded = true;
            input.value = '';
            store.removeItem('ai-draft');
            images = [];
            renderChips();
            setBusy(false);
            showChats([]);
            window.toast('새 상담을 시작했습니다. 자산·원칙·기억은 유지됩니다', 'success');
            input.focus();
        }).catch(function (e) {
            sending = false;
            setBusy(false);
            if (e.status === 409) {
                window.toast('다른 기기에서 상담이 진행 중입니다. 끝난 뒤 다시 시도해 주세요', 'info');
                sync(true);
                return;
            }
            window.toast('새 상담을 시작하지 못했습니다: ' + e.message, 'error');
        });
    });

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
        expand(false);   // 크게 편 채 보내면 큰 입력창이 대화를 가린다 — 접는다(30.ai_center 와 같다)
        images = [];
        renderChips();
        sending = true;
        setBusy(true);
        store.setItem('ai-pending', String(lastChatId));

        api('POST', '/api/v1/assistant/chat', sent).then(function (r) {
            sending = false;
            setBusy(false);
            lastChatId = r.chat_id;
            chatSig = '';
            addMessage({ role: 'assistant', content: r.reply, meta: r.meta });
            arrived();
            applyChanges(r.changes);
        }).catch(function (e) {
            sending = false;
            // 다른 기기(PC·폰)에서 이미 상담이 돌고 있으면 작성한 입력은 되살리고 진행 중 대기로 합류한다.
            if (e.status === 409) {
                setBusy(false);
                mine.remove();
                input.value = sent.message;
                images = sent.images;
                renderChips();
                if (!logEl.querySelector('.ai-msg')) emptyChat();
                window.toast('다른 기기에서 상담이 진행 중입니다. 끝나면 자동으로 불러옵니다', 'info');
                sync(true);
                return;
            }
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

    // 서버의 상담이 끝날 때까지 기다렸다(최대 12분 — codex/agy 는 10분이면 끊긴다) 대화를 다시 그린다.
    // `since` 뒤에 새 답이 저장됐으면 true. 기다리는 동안의 연결 실패는 다시 묻는다(화면이 꺼져 있었을 수 있다).
    function follow(since, initial) {
        if (followPromise) return followPromise;
        var until = Date.now() + 12 * 60 * 1000;
        var later = function () { return new Promise(function (ok) { setTimeout(ok, 5000); }); };
        var poll = function () {
            return api('GET', '/api/v1/assistant/chat/busy').then(function (r) {
                if (r.busy && r.message && r.message !== pendingText) {
                    pendingText = r.message;
                    if (hasLoaded) showPendingBubble(pendingText);
                }
                return r.busy;
            }, function (e) {
                if (e.status || Date.now() > until) throw e;
                return true;
            }).then(function (still) {
                if (still) return later().then(poll);
                return api('GET', '/api/v1/assistant/chat');
            });
        };
        if (initial && initial.message) {
            pendingText = initial.message;
            if (hasLoaded) showPendingBubble(pendingText);
        }
        if (!busy) setBusy(true, initial && initial.started_at);
        followPromise = (initial && initial.busy ? later().then(poll) : poll()).then(function (chats) {
            followPromise = null;
            var newest = chats.length ? chats[chats.length - 1].chat_id : 0;
            changed(null);   // 그 사이 무엇이 바뀌었는지 모른다 — 화면이 다시 읽는다
            hasLoaded = true;
            setBusy(false);
            showChats(chats);
            return newest > since;
        }, function (e) {
            followPromise = null;
            throw e;
        });
        return followPromise;
    }

    // 대화 기록 아래 여백 = 떠 있는 입력 상자의 실제 높이 + 4px. 첨부 칩이 붙어 상자가 높아지면 따라간다.
    function fitLogPadding() {
        var bottom = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 4;
        logEl.style.paddingBottom = (form.offsetHeight + 4) + 'px';
        if (bottom) logEl.scrollTop = logEl.scrollHeight;
        liftToast();
    }

    // 열린 동안 토스트는 입력 상자 위 8px 에 뜬다(정본 toast.md — 접힌 손잡이만큼만 올리면 쓰는 칸을 가렸다).
    // 여닫는 중엔 transform 이 움직이므로 화면 좌표 대신 시트 바닥에서 상자 위까지의 거리 + 키보드 높이로 잰다.
    function liftToast() {
        var root = document.documentElement.style;
        if (!isOpen()) { root.removeProperty('--ai-toast-lift'); return; }
        var kb = parseFloat(sheetEl.style.getPropertyValue('--ai-kb')) || 0;
        var lift = kb + sheetEl.getBoundingClientRect().bottom - form.getBoundingClientRect().top + 8;
        root.setProperty('--ai-toast-lift', Math.round(lift) + 'px');
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

    /** 입력창 확장/축소 — 30.ai_center 처럼 행 수만 3 ↔ 12. */
    function expand(on) {
        input.rows = on ? 12 : 3;
        expandBtn.setAttribute('aria-pressed', String(on));
        expandBtn.setAttribute('aria-label', on ? '입력창 축소' : '입력창 확장');
    }
    expandBtn.addEventListener('click', function () {
        expand(expandBtn.getAttribute('aria-pressed') !== 'true');
        input.focus();
    });

    // 시트 위의 휠은 페이지를 움직이지 않고 대화 기록만(넘치는 입력칸 위에서는 입력칸 먼저) 움직인다.
    // ⚠️ preventDefault 를 쓰려면 passive: false 여야 한다. 확대·축소(ctrl+휠)와 가로 휠(shift+휠·트랙패드 옆으로)은
    //    브라우저에 맡긴다 — 대화 안 코드 블록·표를 옆으로 밀 수 없었다.
    sheetEl.addEventListener('wheel', function (e) {
        if (e.ctrlKey || e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) return;
        e.preventDefault();
        var t = e.target.closest('textarea'), box = t && t.scrollHeight > t.clientHeight ? t : logEl;
        box.scrollTop += e.deltaY * (e.deltaMode === 1 ? 16 : 1);
    }, { passive: false });

    // ── 시트 ───────────────────────────────────────────────
    //    위아래로 끄는 동안은 손가락(마우스)을 따라 움직이고, 40px 넘게 움직였으면 그 방향으로 열고 닫는다.
    //    누르기로 여닫기: 손가락은 한 번, 넓은 화면의 마우스는 더블클릭, 키보드는 Enter·Space.
    //    넓은 화면에서는 좌우로 끌면 시트가 옆으로 옮겨진다(2026-10-19 사용자) — 처음 움직인 방향이 더 큰 쪽으로 가른다.
    //    옮긴 자리는 기억하고(localStorage `ai-x`, 화면을 옮겨도 그대로), 가운데 근처(32px)에 놓으면 가운데에 붙는다.
    //    (두 번 누르기로 가운데를 주려 했으나, 첫 누르기에 시트가 열고 닫히며 손잡이가 움직여 두 번째가 빗나갔다.)

    var drag = null, closedY = 0, swallowClick = false;
    var wide = window.matchMedia('(min-width: 64rem)');
    var sheetX = 0;   // 가운데에서 옆으로 옮긴 거리(px)

    /** 화면 안(좌우 1rem 여백)으로 맞춰 옮긴다. 좁은 화면은 CSS 가 무시한다(폭 전체). */
    function placeX(x, save) {
        if (!wide.matches) return;
        var r = sheetEl.getBoundingClientRect(), left0 = r.left - sheetX;   // 옮기기 전 자리
        sheetX = Math.round(Math.min(window.innerWidth - 16 - r.width - left0, Math.max(16 - left0, x)));
        sheetEl.style.setProperty('--ai-x', sheetX + 'px');
        if (save) localStorage.setItem('ai-x', String(sheetX));
    }
    placeX(+localStorage.getItem('ai-x') || 0);
    // 창이 좁아졌다 다시 넓어지면 기억한 자리로 — 좁을 때 맞춘 자리에 머물지 않게
    window.addEventListener('resize', function () { placeX(+localStorage.getItem('ai-x') || 0); });
    wide.addEventListener('change', function () { if (wide.matches) placeX(+localStorage.getItem('ai-x') || 0); });

    function isOpen() { return sheetEl.classList.contains('is-open'); }
    function translateY() { return new DOMMatrix(getComputedStyle(sheetEl).transform).m42; }

    function set(open) {
        if (open === isOpen()) return;
        sheetEl.classList.toggle('is-open', open);
        fitKeyboard();
        dim.hidden = !open;
        grip.setAttribute('aria-expanded', String(open));
        grip.setAttribute('aria-label', open ? 'AI 상담 닫기' : 'AI 상담 열기');
        liftToast();
        if (open) {
            grip.classList.remove('has-new');
            document.dispatchEvent(new CustomEvent('assistant:open'));
            load().catch(function () {});
            startStream();
            fitLogPadding();
            logEl.scrollTop = logEl.scrollHeight;
            if (!coarse.matches) input.focus({ preventScroll: true });
        } else {
            stopStream();
        }
    }

    /** 접혀 있는 동안 답이 오면 손잡이에 점을 찍는다. */
    function arrived() { if (!isOpen()) grip.classList.add('has-new'); }

    grip.addEventListener('pointerdown', function (e) {
        if (e.pointerType === 'mouse' && e.button !== 0) return;
        swallowClick = false;
        if (!isOpen()) closedY = translateY();   // 접힌 자리 — 열린 채 끌기 시작하면 앞서 잰 값을 쓴다
        drag = { x: e.clientX, y: e.clientY, base: translateY(), baseX: sheetX, open: isOpen(), axis: null, mouse: e.pointerType === 'mouse' };
        grip.setPointerCapture(e.pointerId);
        sheetEl.classList.add('is-dragging');
    });
    grip.addEventListener('pointermove', function (e) {
        if (!drag) return;
        var dx = e.clientX - drag.x, dy = e.clientY - drag.y;
        if (!drag.axis && (Math.abs(dx) > 6 || Math.abs(dy) > 6)) {
            drag.axis = wide.matches && Math.abs(dx) > Math.abs(dy) ? 'x' : 'y';
        }
        if (drag.axis === 'x') {
            placeX(drag.baseX + dx);
        } else if (drag.axis === 'y') {
            var max = closedY || sheetEl.offsetHeight;
            sheetEl.style.transform = 'translateY(' + Math.min(max, Math.max(0, drag.base + dy)) + 'px)';
        }
    });
    function end(e) {
        if (!drag) return;
        var dy = e.clientY - drag.y, was = drag.open, axis = drag.axis, mouse = drag.mouse;
        drag = null;
        sheetEl.classList.remove('is-dragging');
        sheetEl.style.transform = '';
        // 누르기는 여기서 연다/닫는다 — 손잡이에 포인터를 잡아 둔 터치에서는 click 이 오지 않는다(browserless 실측).
        // 오는 기기도 있어 뒤따르는 click 한 번은 삼킨다(다음 pointerdown 이 표시를 지운다). click 은 키보드 몫이다.
        swallowClick = true;
        if (axis === 'x') { placeX(Math.abs(sheetX) < 32 ? 0 : sheetX, true); return; }
        if (axis === 'y') { set(dy < -40 ? true : dy > 40 ? false : was); return; }
        // 넓은 화면의 마우스는 한 번 누르기로 여닫지 않는다 — 더블클릭으로(2026-10-19 사용자). 좌우로 옮기려 잡았다 놓을 때
        // 열리고 닫히지 않게도 된다. 손가락(휴대폰·터치 노트북)은 한 번 누르기 그대로다.
        if (!(mouse && wide.matches)) set(!was);
    }
    grip.addEventListener('pointerup', end);
    grip.addEventListener('pointercancel', end);
    grip.addEventListener('click', function () {
        if (swallowClick) { swallowClick = false; return; }
        set(!isOpen());   // 키보드(Enter·Space)
    });
    grip.addEventListener('dblclick', function () { if (wide.matches) set(!isOpen()); });
    dim.addEventListener('click', function () { set(false); });
    document.addEventListener('keydown', function (e) {
        // 열린 모달(버전 기록 등)·떠 있는 창(popover=auto — 넓은 화면은 덮개가 없어 같이 열린다)이 있으면 Esc 는 그 창 몫이다(한 겹씩)
        if (e.key === 'Escape' && isOpen() && !document.querySelector('dialog[open], [popover="auto"]:popover-open')) set(false);
    });

    // ── 휴대폰 키보드 ──────────────────────────────────────
    //    키보드는 보이는 영역(visual viewport)만 줄인다 — fixed 시트의 바닥(입력칸)은 키보드 뒤에 남아, 브라우저가
    //    스크롤해 주지 않으면 가렸다(드물게, 사용자 "매우 중요"). 열린 동안 키보드 높이만큼 바닥을 올리고 높이를 보이는
    //    영역 안으로 줄인다(assistant.css --ai-kb·--ai-vh). 접혀 있을 땐 손대지 않는다(상단 검색칸 키보드에 손잡이가 따라 올라온다).
    var vv = window.visualViewport;

    function fitKeyboard() {
        if (!vv) return;
        var kb = isOpen() ? Math.max(0, Math.round(window.innerHeight - vv.height - vv.offsetTop)) : 0;
        var atEnd = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 4;
        if (kb > 0) {
            sheetEl.style.setProperty('--ai-kb', kb + 'px');
            sheetEl.style.setProperty('--ai-vh', Math.round(vv.height) + 'px');
        } else {
            sheetEl.style.removeProperty('--ai-kb');
            sheetEl.style.removeProperty('--ai-vh');
        }
        if (atEnd) logEl.scrollTop = logEl.scrollHeight;   // 보던 마지막 말이 키보드에 밀려 올라가지 않게
        liftToast();
    }
    if (vv) {
        vv.addEventListener('resize', fitKeyboard);
        vv.addEventListener('scroll', fitKeyboard);
    }
    // 키보드가 다 올라온 뒤 한 번 더 잰다 — resize 가 늦게 오거나 올라오는 도중 값만 오는 기기가 있다
    input.addEventListener('focus', function () { setTimeout(fitKeyboard, 50); setTimeout(fitKeyboard, 350); });

    window.assistant = {
        /** 화면의 다른 아래 시트가 떠 있는 동안은 손잡이까지 내린다. */
        away: function (on) { sheetEl.classList.toggle('is-away', on); if (on) set(false); },
        open: function () { set(true); },
    };

    // ── 실시간 다중 기기 동기화 (SSE) ──────────────────────
    //    시트가 열려 있고 탭이 보이는 동안 `/api/v1/assistant/chat/events` 에 Bearer 로 연결한다.
    //    PC·폰 양쪽 시트를 열어둔 상태에서도 질문 시작(`started`)·완료(`done`)·새 상담(`reset`)이 즉시 반영된다.
    function handleStreamEvent(ev, data) {
        if (ev === 'started') {
            if (sending) return;
            pendingText = (data && data.message) || pendingText;
            if (hasLoaded && pendingText) showPendingBubble(pendingText);
            if (!busy) setBusy(true, data && data.started_at);
            return;
        }
        if (ev === 'state') {
            if (sending) return;
            if (data && data.busy) {
                pendingText = data.message || pendingText;
                if (hasLoaded && pendingText && !logEl.querySelector('[data-pending="1"]')) showPendingBubble(pendingText);
                if (!busy) setBusy(true, data.started_at);
            } else if (busy && !followPromise) {
                setBusy(false);
                sync(true);
            }
            return;
        }
        if (ev === 'done') {
            if (sending) return;
            pendingText = null;
            setBusy(false);
            changed(null);
            sync(true).then(function () {
                if (data && data.chat_id && data.chat_id > lastChatId) arrived();
            });
            return;
        }
        if (ev === 'reset') {
            if (sending) return;
            pendingText = null;
            setBusy(false);
            hasLoaded = true;
            showChats([]);
        }
    }

    function stopStream() {
        clearTimeout(sseRetryTimer);
        sseRetryTimer = null;
        if (sseAbort) {
            try { sseAbort.abort(); } catch (e) {}
            sseAbort = null;
        }
    }

    function scheduleStreamRetry() {
        if (!isOpen() || document.visibilityState !== 'visible') return;
        clearTimeout(sseRetryTimer);
        var delay = sseBackoff;
        sseBackoff = Math.min(15000, sseBackoff * 2);
        sseRetryTimer = setTimeout(function () {
            sseRetryTimer = null;
            if (isOpen() && document.visibilityState === 'visible') {
                sync(true);
                startStream();
            }
        }, delay);
    }

    function startStream() {
        if (sseAbort || !isOpen() || document.visibilityState !== 'visible') return;
        if (typeof AbortController === 'undefined' || !window.TextDecoder) return;
        var ac = new AbortController();
        sseAbort = ac;
        authToken().then(function (t) {
            if (sseAbort !== ac) return null;
            return fetch('/api/v1/assistant/chat/events', {
                headers: { Authorization: 'Bearer ' + t, Accept: 'text/event-stream' },
                signal: ac.signal
            });
        }).then(function (r) {
            if (!r || sseAbort !== ac) return;
            if (!r.ok || !r.body) throw new Error('SSE ' + r.status);
            sseBackoff = 2000;
            var reader = r.body.getReader();
            var decoder = new TextDecoder();
            var buf = '';
            function pump() {
                return reader.read().then(function (chunk) {
                    if (sseAbort !== ac) return;
                    if (chunk.done) throw new Error('EOF');
                    buf += decoder.decode(chunk.value, { stream: true }).replace(/\r\n/g, '\n');
                    var sep;
                    while ((sep = buf.indexOf('\n\n')) >= 0) {
                        var block = buf.slice(0, sep);
                        buf = buf.slice(sep + 2);
                        var ev = 'message', lines = [];
                        block.split('\n').forEach(function (line) {
                            if (line.indexOf('event:') === 0) ev = line.slice(6).trim();
                            else if (line.indexOf('data:') === 0) lines.push(line.slice(5).trim());
                        });
                        if (lines.length) {
                            try { handleStreamEvent(ev, JSON.parse(lines.join('\n'))); } catch (e) {}
                        }
                    }
                    return pump();
                });
            }
            return pump();
        }).catch(function () {
            if (sseAbort === ac) {
                sseAbort = null;
                scheduleStreamRetry();
            }
        });
    }

    // 다른 탭·기기에서 진행 중인 상담이 있으면 바로 대기 상태로 합류한다.
    var pending = store.getItem('ai-pending');
    if (pending !== null) {
        follow(+pending || 0).then(function (got) { if (got) arrived(); }, function () { setBusy(false); });
    } else {
        api('GET', '/api/v1/assistant/chat/busy').then(function (b) {
            if (b && b.busy) {
                follow(lastChatId, b).then(function (got) { if (got) arrived(); }, function () { setBusy(false); });
            }
        }).catch(function () {});
    }

    // 다른 기기(PC↔폰)에서 상담을 마치고 돌아온 탭에서도 최신 대화를 바로 반영하고 SSE 를 다시 잇는다.
    document.addEventListener('visibilitychange', function () {
        if (document.visibilityState === 'visible') {
            if (isOpen()) {
                sync(true);
                startStream();
            }
        } else {
            stopStream();
        }
    });
    window.addEventListener('pagehide', stopStream);
})();
