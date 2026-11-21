// Tabellen sortieren durch Antippen der Spaltenköpfe.
// <table class="sortable" data-sort-key="players"> + <th data-sort="num|text">,
// Sortierwert pro Zelle in data-v (sonst der Text), leere Werte stehen immer unten.
// data-first="asc|desc" = Richtung beim ersten Antippen, data-default = so kommt die Liste vom Server.
// Die Wahl merkt sich der Browser.
(function () {
  function store(key, value) {
    try {
      if (value === undefined) return JSON.parse(localStorage.getItem(key) || "null");
      localStorage.setItem(key, JSON.stringify(value));
    } catch (e) { return null; }
  }

  document.querySelectorAll("table.sortable").forEach(function (table) {
    var key = "fd-sort:" + (table.dataset.sortKey || location.pathname);
    var body = table.tBodies[0];
    var heads = Array.prototype.slice.call(table.tHead.rows[0].cells);
    // Ursprüngliche Reihenfolge merken: bei Gleichstand bleibt sie erhalten
    Array.prototype.forEach.call(body.rows, function (row, i) { row.dataset.i = i; });
    var current = null;

    function value(row, col, numeric) {
      var cell = row.cells[col];
      var v = cell.dataset.v !== undefined ? cell.dataset.v : cell.textContent.trim();
      if (v === "") return null;
      if (!numeric) return v.toLowerCase();
      var n = parseFloat(v);
      return isNaN(n) ? null : n;
    }

    function sortBy(col, dir, save) {
      var numeric = heads[col].dataset.sort === "num";
      var rows = Array.prototype.slice.call(body.rows);
      rows.sort(function (a, b) {
        var x = value(a, col, numeric), y = value(b, col, numeric);
        if (x === null || y === null) {
          if (x !== y) return x === null ? 1 : -1;
          return a.dataset.i - b.dataset.i;
        }
        var c = numeric ? x - y : x.localeCompare(y);
        return c * dir || a.dataset.i - b.dataset.i;
      });
      rows.forEach(function (r) { body.appendChild(r); });
      heads.forEach(function (th) { th.removeAttribute("aria-sort"); });
      heads[col].setAttribute("aria-sort", dir > 0 ? "ascending" : "descending");
      current = { col: col, dir: dir };
      if (save) store(key, current);
    }

    heads.forEach(function (th, col) {
      if (!th.dataset.sort) return;
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "th-sort";
      btn.innerHTML = th.innerHTML;
      th.textContent = "";
      th.appendChild(btn);
      btn.addEventListener("click", function () {
        // Zahlen zuerst absteigend (höchste Punkte oben), Text zuerst A–Z
        var first = th.dataset.first ? (th.dataset.first === "asc" ? 1 : -1) : (th.dataset.sort === "num" ? -1 : 1);
        var dir = current && current.col === col ? -current.dir : first;
        sortBy(col, dir, true);
      });
    });

    // Server-Reihenfolge als Ausgangspunkt anzeigen, gespeicherte Wahl wiederherstellen
    var initial = heads.findIndex(function (th) { return th.dataset.default; });
    if (initial >= 0) {
      heads[initial].setAttribute("aria-sort", heads[initial].dataset.default === "asc" ? "ascending" : "descending");
      current = { col: initial, dir: heads[initial].dataset.default === "asc" ? 1 : -1 };
    }
    var saved = store(key);
    if (saved && heads[saved.col] && heads[saved.col].dataset.sort) sortBy(saved.col, saved.dir, false);
  });
})();
