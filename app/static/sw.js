// Minimaler Service Worker: macht die Seite als App installierbar und cached
// statische Dateien. Seiten selbst kommen immer frisch vom Server.
const CACHE = "fd-static-v11";

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== location.origin) return;

  if (url.pathname.startsWith("/static/")) {
    // Statisches: erst Cache, im Hintergrund aktualisieren
    event.respondWith(
      caches.open(CACHE).then(async (cache) => {
        const cached = await cache.match(event.request);
        const fresh = fetch(event.request).then((res) => {
          if (res.ok) cache.put(event.request, res.clone());
          return res;
        });
        return cached || fresh;
      })
    );
    return;
  }

  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request).catch(
        () => new Response(
          "<!doctype html><meta name=viewport content='width=device-width'><body style='font-family:sans-serif;padding:2rem;text-align:center'><h2>Offline</h2><p>No connection – try again in a moment.</p><button onclick='location.reload()'>Retry</button>",
          { headers: { "Content-Type": "text/html; charset=utf-8" } }
        )
      )
    );
  }
});
