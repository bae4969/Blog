/* 블로그 서비스워커 — 설치형 앱(PWA)으로 뜨게 하고, 서버에 못 닿을 때 안내 화면을 낸다.
 *
 * ## 캐시하는 것은 정적 파일뿐이다
 *
 * `/css/` `/js/` `/vendor/` `/res/` 만 담는다. 누구에게나 같은 값이라 새어 나가도 문제가 없다.
 *
 * ⚠️ **화면(HTML)·API 는 담지 않는다.** 화면은 로그인 등급에 따라 보이는 글이 달라서, 담아 두면
 *    로그아웃 뒤나 다른 계정에서 옛 화면이 나온다. 시세는 지금 값이 아니면 틀린 값이다.
 * ⚠️ **200 만 담는다.** 로그인으로 보내는 303 이나 오류를 담으면 그 상태가 굳는다(auth·home_iot 이
 *    같은 이유로 그렇게 한다).
 * ⚠️ `/uploads/` 는 사용자가 올린 이미지라 개수가 끝이 없다 — 담지 않는다.
 *
 * ## `?v=` 가 바뀌면 옛 항목을 지운다
 *
 * 화면이 붙이는 `?v=`(`static_v`)는 **서버가 재시작할 때마다 바뀐다.** 그대로 두면 재시작마다 같은
 * 파일이 한 벌씩 쌓이므로, 새로 담을 때 같은 경로의 다른 쿼리 항목을 지운다.
 *
 * ⚠️ 이 파일을 고쳐 캐시 방식이 바뀌면 `VERSION` 을 올린다 — activate 때 옛 캐시가 통째로 버려진다.
 */

const VERSION = 'v1';
const CACHE = `blog-static-${VERSION}`;
const STATIC = ['/css/', '/js/', '/vendor/', '/res/'];
const PASS = ['/api/', '/uploads/', '/admin'];

const OFFLINE_HTML = `<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="theme-color" content="#1C1C1C">
<title>오프라인 — Developer Notes</title>
<style>
  html, body { height: 100%; margin: 0; }
  body { display: flex; align-items: center; justify-content: center; background: #1C1C1C;
         color: #E0E0E0; font-family: system-ui, -apple-system, sans-serif; text-align: center; }
  h1 { font-size: 1.25rem; margin: 0 0 .5rem; }
  p { margin: 0 0 1.5rem; color: #A0A0A0; }
  button { padding: .6rem 1.4rem; border: 1px solid #555; border-radius: 6px; background: #2A2A2A;
           color: #E0E0E0; font-size: 1rem; cursor: pointer; }
</style>
</head>
<body>
<main>
  <h1>서버에 연결할 수 없습니다</h1>
  <p>네트워크 연결을 확인한 뒤 다시 시도해 주세요.</p>
  <button type="button" onclick="location.reload()">다시 시도</button>
</main>
</body>
</html>`;

self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter((n) => n !== CACHE).map((n) => caches.delete(n)));
    await self.clients.claim();
  })());
});

/** 새 응답을 담고, 같은 경로의 다른 쿼리(옛 `?v=`) 항목을 지운다. */
async function keep(request, response) {
  const cache = await caches.open(CACHE);
  await cache.put(request, response);
  const path = new URL(request.url).pathname;
  for (const old of await cache.keys()) {
    if (old.url !== request.url && new URL(old.url).pathname === path) await cache.delete(old);
  }
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // respondWith 를 부르지 않으면 브라우저가 평소대로 처리한다 — 쓰기·남의 도메인(auth 로그인)·
  // API·업로드·관리자는 손대지 않는다.
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (PASS.some((p) => url.pathname.startsWith(p))) return;

  // 화면 이동은 네트워크만 쓴다. 못 닿았을 때만 안내 화면을 낸다.
  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(() => new Response(OFFLINE_HTML, {
      status: 503,
      headers: { 'Content-Type': 'text/html; charset=utf-8' },
    })));
    return;
  }

  if (!STATIC.some((p) => url.pathname.startsWith(p))) return;

  // stale-while-revalidate — 캐시에 있으면 바로 주고, 뒤에서 새로 받아 바꿔 둔다.
  // ⚠️ clone 은 응답 본문이 읽히기 전에 해야 한다. 아래 then 이 respondWith 쪽보다 먼저 걸리므로
  //    화면이 본문을 읽기 전에 돈다.
  const fresh = fetch(request);
  event.waitUntil(fresh.then((res) => {
    if (res.status === 200 && res.type === 'basic') return keep(request, res.clone());
  }).catch(() => {}));
  event.respondWith(caches.match(request).then((hit) => hit || fresh));
});
