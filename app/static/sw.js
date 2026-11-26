// Minimaler Service Worker: macht die Seite als App installierbar und cached
// statische Dateien. Seiten selbst kommen immer frisch vom Server.
const CACHE = "fd-static-v32";

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

// Push-Benachrichtigung ("Du bist dran") anzeigen ...
self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = { body: event.data && event.data.text() }; }
  event.waitUntil(self.registration.showNotification(data.title || "Mönninghausen Games", {
    body: data.body || "",
    icon: "/static/icons/icon-192.png?v=4",
    badge: "/static/icons/badge-96.png",
    tag: data.tag || undefined,
    renotify: !!data.tag,
    vibrate: [200, 100, 200],
    data: { url: data.url || "/" },
  }));
});

// ... und beim Antippen die passende Seite öffnen (oder ein offenes Fenster dorthin holen).
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL(event.notification.data && event.notification.data.url || "/", self.location.origin).href;
  event.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const w of wins) {
      if ("navigate" in w) { await w.focus(); return w.navigate(url); }
    }
    return self.clients.openWindow(url);
  })());
});
