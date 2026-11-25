// Service worker: ホーム画面から開けるようにし、一度読み込んだ日は電波がなくても読めるようにする。
//  - 画面の部品（HTML/CSS/JS/アイコン）: キャッシュを先に返し、裏で新しい版を取得（次回から反映）
//  - データ（data/*.json）: まずネットから取り、つながらなければキャッシュを返す
const VERSION = "v2";
const SHELL = `shell-${VERSION}`;
const DATA = "data-v1";
const SHELL_FILES = ["./", "index.html", "style.css", "app.js", "manifest.webmanifest", "site-config.json",
  "icons/icon-192.png", "icons/icon-512.png", "icons/apple-touch-icon.png"];
const MAX_DAYS = 70; // キャッシュしておく日数（サイトの保存期間 60 日より少し多め）

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(SHELL_FILES)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil((async () => {
    for (const k of await caches.keys()) if (k !== SHELL && k !== DATA) await caches.delete(k);
    await self.clients.claim();
  })());
});

async function networkFirst(req) {
  const cache = await caches.open(DATA);
  try {
    const res = await fetch(req, { cache: "no-cache" });
    if (res.ok) {
      await cache.put(req, res.clone());
      trimDays(cache);
    }
    return res;
  } catch (err) {
    const hit = await cache.match(req, { ignoreSearch: true });
    if (hit) return hit;
    throw err;
  }
}

async function trimDays(cache) {
  const days = (await cache.keys()).filter((r) => /\/data\/daily\//.test(r.url)).sort((a, b) => (a.url < b.url ? 1 : -1));
  for (const r of days.slice(MAX_DAYS)) await cache.delete(r);
}

async function staleWhileRevalidate(req) {
  const cache = await caches.open(SHELL);
  const hit = await cache.match(req, { ignoreSearch: true });
  const net = fetch(req).then((res) => { if (res.ok) cache.put(req, res.clone()); return res; }).catch(() => null);
  return hit || (await net) || new Response("offline", { status: 503 });
}

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return; // 外部（Claude など）は触らない
  if (url.pathname.includes("/data/")) e.respondWith(networkFirst(e.request));
  else e.respondWith(staleWhileRevalidate(e.request));
});
