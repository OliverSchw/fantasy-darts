// Darts: Zahlentastatur fürs Zählen + Live-Aktualisierung für Zuschauer + Ansager.

// Ansager per Sprachausgabe des Browsers. Muss direkt beim Antippen starten (sonst blocken Handys den Ton),
// deshalb wird erst nach der Ansage abgeschickt (spätestens nach 2,5 s).
window.fdCaller = {
  on: function () { try { return localStorage.getItem("fd-caller") !== "0"; } catch (e) { return true; } },
  toggle: function () {
    var next = !this.on();
    try { localStorage.setItem("fd-caller", next ? "1" : "0"); } catch (e) {}
    return next;
  },
  phrase: function (score, rest, finishable) {
    if (finishable && score === rest) return "Game shot!";
    if (score > rest || rest - score === 1 || (score === rest && !finishable)) return "No score";
    if (score === 180) return "One hundred and eighty!";
    if (score >= 100) return String(score);
    return null;
  },
  say: function (text, done) {
    if (!text || !this.on() || !("speechSynthesis" in window)) { done(); return; }
    var finished = false;
    var finish = function () { if (!finished) { finished = true; done(); } };
    try {
      var u = new SpeechSynthesisUtterance(text);
      u.lang = "en-GB"; u.rate = 0.95; u.pitch = 0.9;
      u.onend = finish; u.onerror = finish;
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(u);
      setTimeout(finish, 2500);
    } catch (e) { finish(); }
  },
};

document.addEventListener("alpine:init", function () {
  Alpine.data("scorer", function (rest, finishable, minDarts, maxDbl) {
    var IMPOSSIBLE = [163, 166, 169, 172, 173, 175, 176, 178, 179];
    function range(a, b) { var r = []; for (var i = a; i <= b; i++) r.push(i); return r; }
    return {
      entry: "", error: "", busy: false, needDarts: false, dbl: null,
      press(d) { this.error = ""; if (this.entry.length < 3) this.entry = (this.entry + d).replace(/^0+(?=\d)/, ""); },
      back() { this.error = ""; this.entry = this.entry.slice(0, -1); },
      quick(n) { this.entry = String(n); this.ok(); },
      ok() {
        var score = parseInt(this.entry || "0", 10);
        if (score > 180 || IMPOSSIBLE.indexOf(score) >= 0) { this.error = score + " isn't possible"; return; }
        if (finishable && score === rest) { this.needDarts = true; return; }
        var left = rest - score, bust = score > rest || left === 1 || score === rest;
        // Doppelversuch möglich? Nur wenn die Aufnahme bei höchstens 50 Rest endet (oder überworfen wurde)
        if (maxDbl > 0 && (bust || left <= 50)) {
          this.dbl = { score: score, darts: "", options: range(0, maxDbl),
                       note: bust ? "Bust – how many of your darts went at a double?" : "For your double rate – " + left + " left." };
          return;
        }
        this.send(score, "", "");
      },
      pickDarts(d) {  // Checkout: mit d Darts - davon mindestens einer aufs Doppel
        this.needDarts = false;
        var most = Math.min(d, maxDbl);
        if (most <= 1) { this.send(rest, d, 1); return; }
        this.dbl = { score: rest, darts: d, options: range(1, most), note: "Including the one that hit." };
      },
      sendDbl(k) { var x = this.dbl; this.dbl = null; this.send(x.score, x.darts, k); },
      send(score, darts, dbl) {
        if (this.busy) return;
        this.busy = true;
        this.$refs.score.value = score;
        this.$refs.darts.value = darts;
        this.$refs.dbl.value = dbl === undefined ? "" : dbl;
        var form = this.$refs.form;
        window.fdCaller.say(window.fdCaller.phrase(score, rest, finishable), function () { form.submit(); });
      },
      typing() { return this.entry !== "" || this.needDarts || !!this.dbl; },
    };
  });

  // X01: Eingabe als Gesamtpunktzahl oder Dart für Dart - die Wahl merkt sich das Gerät
  Alpine.data("x01Input", function () {
    var saved = false;
    try { saved = localStorage.getItem("fd-x01-input") === "darts"; } catch (e) {}
    return {
      perDart: saved,
      init() {
        this.$watch("perDart", function (v) { try { localStorage.setItem("fd-x01-input", v ? "darts" : "total"); } catch (e) {} });
      },
    };
  });

  // X01 Dart für Dart: Rest mitrechnen, Bust/Checkout erkennen (Double-out), dann abschicken
  Alpine.data("x01Pad", function (rest) {
    function value(code) {
      if (code === "M") return [0, 0];
      if (code === "SB") return [1, 25];
      if (code === "DB") return [2, 25];
      return ["SDT".indexOf(code[0]) + 1, parseInt(code.slice(1), 10)];
    }
    return {
      darts: [], mult: "S", busy: false, state: "",
      push(code) { if (!this.over()) this.darts.push(code); this.mult = "S"; this.update(); },
      add(n) { this.push(this.mult + n); },
      addBull(inner) { this.push(inner ? "DB" : "SB"); },
      label(code) {
        if (code === "M") return "Miss";
        if (code === "SB") return "25";
        if (code === "DB") return "Bull";
        return (code[0] === "S" ? "" : code[0]) + code.slice(1);
      },
      total() { return this.darts.reduce(function (t, c) { var v = value(c); return t + v[0] * v[1]; }, 0); },
      update() {
        var left = rest - this.total(), last = this.darts.length ? value(this.darts[this.darts.length - 1]) : null;
        this.state = left === 0 && last && last[0] === 2 ? "checkout" : (left < 2 && this.darts.length ? "bust" : "");
      },
      over() { this.update(); return this.state !== "" || this.darts.length >= 3; },
      status() {
        this.update();
        if (this.state === "checkout") return "🎯 Game shot!";
        if (this.state === "bust") return "Bust – no score";
        return (rest - this.total()) + " left" + (this.darts.length ? " · " + this.total() + " scored" : "");
      },
      sendLabel() {
        if (this.state === "checkout") return "✓ Game shot";
        if (this.state === "bust") return "✓ Save bust";
        return this.darts.length === 3 ? "✓ Save " + this.total() : "Enter " + (3 - this.darts.length) + " more dart" + (this.darts.length === 2 ? "" : "s");
      },
      send() {
        if (!this.over() || this.busy) return;
        this.busy = true;
        this.$refs.throws.value = this.darts.join(",");
        var form = this.$refs.dform, score = this.state === "bust" ? rest + 1 : this.total();
        window.fdCaller.say(window.fdCaller.phrase(score, rest, this.state === "checkout"),
                            function () { form.submit(); });
      },
      typing() { return this.darts.length > 0; },
    };
  });

  // Partyspiele: Darts einzeln eingeben (Faktor + Zahl), max. 3, dann abschicken
  Alpine.data("dartPad", function () {
    return {
      darts: [], mult: "S", busy: false,
      push(code) { if (this.darts.length < 3) this.darts.push(code); this.mult = "S"; },
      add(n) { this.push(this.mult + n); },
      addBull(inner) { this.push(inner ? "DB" : "SB"); },
      label(code) {
        if (code === "M") return "Miss";
        if (code === "SB") return "25";
        if (code === "DB") return "Bull";
        return (code[0] === "S" ? "" : code[0]) + code.slice(1);
      },
      send() {
        if (!this.darts.length || this.busy) return;
        this.busy = true;
        this.$refs.throws.value = this.darts.join(",");
        this.$refs.form.submit();
      },
      typing() { return this.darts.length > 0; },
    };
  });
});

// Live: alle 3 Sekunden fragen, ob es eine neue Aufnahme gibt - dann neu laden (nicht während man tippt).
(function () {
  var cfg = window.DARTS_LIVE;
  if (!cfg || !cfg.live) return;
  function busyTyping() {
    var els = document.querySelectorAll("[x-data^='scorer'], [x-data^='dartPad'], [x-data^='x01Pad']");
    return Array.prototype.some.call(els, function (el) { return el._x_dataStack && el._x_dataStack[0].typing(); });
  }
  setInterval(function () {
    if (document.hidden || busyTyping()) return;
    fetch("/darts/games/" + cfg.id + "/version", { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d && (d.v !== cfg.v || d.status !== "live")) location.reload(); })
      .catch(function () {});
  }, 3000);
})();
