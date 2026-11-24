// Live-Ansicht: alle 3 Sekunden fragen, ob sich etwas geändert hat - dann neu laden.
// Erwartet window.LIVE = { url: "/.../version", v: <aktuelle Version>, live: true }.
(function () {
  var cfg = window.LIVE;
  if (!cfg || !cfg.live) return;
  setInterval(function () {
    if (document.hidden || document.querySelector("form[data-busy]")) return;
    fetch(cfg.url, { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d && (d.v !== cfg.v || d.status !== "live")) location.reload(); })
      .catch(function () {});
  }, 3000);
})();
