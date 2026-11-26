// Darts: Zahlentastatur fürs Zählen + Live-Aktualisierung für Zuschauer + Ansager.

// Ansager per Sprachausgabe des Handys. Muss direkt beim Antippen starten (sonst blocken Handys den Ton),
// deshalb wird erst nach der Ansage abgeschickt (spätestens nach 3 s).
// Klingt wie ein Caller: britische Stimme (die beste, die das Gerät hat), Zahlen auf Britisch
// ("one hundred and forty"), "you require 81", "Game shot, and the first leg!".
(function () {
  var ONES = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
              "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"];
  var TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"];
  var ORD = ["", "first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth",
             "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth", "sixteenth", "seventeenth", "eighteenth",
             "nineteenth", "twentieth", "twenty-first"];
  function words(n) {
    if (n === 0) return "no score";
    var out = "";
    if (n >= 100) { out = ONES[Math.floor(n / 100)] + " hundred"; n %= 100; if (n) out += " and "; }
    if (n >= 20) { out += TENS[Math.floor(n / 10)] + (n % 10 ? "-" + ONES[n % 10] : ""); }
    else if (n > 0) { out += ONES[n]; }
    return out;
  }
  // Bessere Stimmen zuerst: britisch, "Natural/Neural/Enhanced/Premium", bekannte Männerstimmen
  var GOOD = /natural|neural|online|enhanced|premium|siri|network/i;  // "network" = Android-Onlinestimmen (Google)
  var MALE = /daniel|arthur|george|ryan|oliver|thomas|harry|male|uk english male/i;
  function rank(v) {
    var r = 0;
    if (/^en[-_]GB/i.test(v.lang)) r += 40; else if (/^en[-_](IE|AU|NZ)/i.test(v.lang)) r += 25; else if (/^en/i.test(v.lang)) r += 10;
    if (GOOD.test(v.name)) r += 20;
    if (MALE.test(v.name)) r += 8;
    if (v.localService) r += 2;
    return r;
  }
  function cfg() {
    try { return Object.assign({ voice: "", every: true }, JSON.parse(localStorage.getItem("fd-caller-cfg") || "{}")); }
    catch (e) { return { voice: "", every: true }; }
  }
  function voices() { return "speechSynthesis" in window ? window.speechSynthesis.getVoices() : []; }

  window.fdCaller = {
    words: words,
    on: function () { try { return localStorage.getItem("fd-caller") !== "0"; } catch (e) { return true; } },
    toggle: function () {
      var next = !this.on();
      try { localStorage.setItem("fd-caller", next ? "1" : "0"); } catch (e) {}
      return next;
    },
    settings: cfg,
    save: function (c) { try { localStorage.setItem("fd-caller-cfg", JSON.stringify(c)); } catch (e) {} },
    voices: function () {
      return voices().filter(function (v) { return /^en/i.test(v.lang); }).sort(function (a, b) { return rank(b) - rank(a); });
    },
    // Lesbarer Name, z. B. Android "en-gb-x-gbd-network" -> "English (UK) · voice D · online"
    label: function (v) {
      var m = /^([a-z]{2})-([a-z]{2})-x-([a-z]{3})-(network|local)$/i.exec(v.name);
      var region = { GB: "UK", US: "US", AU: "Australia", IN: "India", IE: "Ireland", NZ: "New Zealand", ZA: "South Africa",
                     NG: "Nigeria", CA: "Canada" };
      if (m) {
        var r = m[2].toUpperCase();
        return "English (" + (region[r] || r) + ") · voice " + m[3].slice(-1).toUpperCase() + " · " +
               (m[4].toLowerCase() === "network" ? "online" : "offline");
      }
      return v.name + " (" + v.lang + ")";
    },
    // Manche Handys (Chrome auf Android) liefern die Stimmen erst später - bis zu 3 s darauf warten
    ready: function (cb) {
      if (!("speechSynthesis" in window)) { cb(); return; }
      if (voices().length) { cb(); return; }
      var done = false, finish = function () { if (!done && (voices().length || Date.now() - t0 > 3000)) { done = true; clearInterval(iv); cb(); } };
      var t0 = Date.now(), iv = setInterval(finish, 250);
      try { window.speechSynthesis.addEventListener("voiceschanged", finish); } catch (e) {}
      try {  // leere, stumme Ansage weckt die Sprachausgabe auf (sonst bleibt die Liste auf manchen Geräten leer)
        var u = new SpeechSynthesisUtterance(" "); u.volume = 0; window.speechSynthesis.speak(u);
      } catch (e) {}
    },
    voice: function () {
      var c = cfg(), all = voices();
      return all.find(function (v) { return v.name === c.voice; }) ||
             all.slice().sort(function (a, b) { return rank(b) - rank(a); })[0] || null;
    },
    // Ansage zu einer Aufnahme. info: { leg: 2, match: true } für den Checkout
    phrase: function (score, rest, finishable, info) {
      info = info || {};
      if (finishable && score === rest) {
        if (info.match) return "Game shot, and the match!";
        return "Game shot, and the " + (ORD[info.leg || 1] || "") + " leg!";
      }
      if (score > rest || rest - score === 1 || (score === rest && !finishable)) return "No score!";
      if (score === 180) return "One hundred and eighty!";
      if (score === 0) return "No score!";
      if (score >= 100 || cfg().every) return words(score) + (score >= 100 ? "!" : "");
      return null;
    },
    require: function (name, rest) { return name + ", you require " + words(rest) + "."; },
    say: function (text, done) {
      done = done || function () {};
      if (!text || !this.on() || !("speechSynthesis" in window)) { done(); return; }
      var finished = false;
      var finish = function () { if (!finished) { finished = true; done(); } };
      try {
        var u = new SpeechSynthesisUtterance(text), v = this.voice();
        if (v) { u.voice = v; u.lang = v.lang; } else { u.lang = "en-GB"; }
        var big = /eighty!|match!|leg!/.test(text);
        u.rate = big ? 0.82 : 0.9;   // Caller lassen sich Zeit - bei der 180 und beim Checkout besonders
        u.pitch = big ? 1.05 : 0.92;
        u.onend = finish; u.onerror = finish;
        window.speechSynthesis.cancel();
        window.speechSynthesis.speak(u);
        setTimeout(finish, 3000);
      } catch (e) { finish(); }
    },
  };
  // Manche Browser laden die Stimmen erst später (ready() wartet darauf)
  if ("speechSynthesis" in window) { try { window.speechSynthesis.getVoices(); } catch (e) {} }
})();

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
        window.fdCaller.say(window.fdCaller.phrase(score, rest, finishable, window.DARTS_LIVE), function () { form.submit(); });
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
        window.fdCaller.say(window.fdCaller.phrase(score, rest, this.state === "checkout", window.DARTS_LIVE),
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

// Link zum Spiel teilen (Handy: Teilen-Menü, sonst in die Zwischenablage)
window.fdShareGame = function () {
  var url = location.href.split("#")[0];
  if (navigator.share) { navigator.share({ title: document.title, url: url }).catch(function () {}); return; }
  if (navigator.clipboard) navigator.clipboard.writeText(url).then(function () { alert("Link copied – send it to the others."); });
  else prompt("Copy this link:", url);
};

// Nach einer neuen Aufnahme (Seite neu geladen): Aufnahme eines anderen (Gegner aus der Ferne, Bot) ansagen
// und dem, der jetzt dran ist und auschecken kann: "Dana, you require 81."
(function () {
  var cfg = window.DARTS_LIVE;
  if (!cfg) return;
  var key = "fd-heard-" + cfg.id, heard = -1;
  try { heard = parseInt(sessionStorage.getItem(key) || "-1", 10); sessionStorage.setItem(key, String(cfg.v)); } catch (e) {}
  if (heard < 0 || cfg.v <= heard) return;
  var parts = [];
  if (cfg.call) {
    var c = cfg.call, text;
    if (c.text) text = c.text;
    else if (c.checkout) text = c.match ? "Game shot, and the match!" : "Game shot, and the " + (c.ordinal || "") + " leg!";
    else if (c.bust || !c.score) text = "No score!";
    else if (c.score === 180) text = "One hundred and eighty!";
    else text = window.fdCaller.words(c.score);
    parts.push(c.name + ", " + text + (/[!.]$/.test(text) ? "" : "."));  // Punkt = kurze Pause vor "you require"
  }
  if (cfg.req) parts.push(window.fdCaller.require(cfg.req.name, cfg.req.rest));
  if (parts.length) document.addEventListener("DOMContentLoaded", function () { window.fdCaller.say(parts.join(" ")); });
})();

// Ansager-Einstellungen: Stimme wählen, jede Aufnahme oder nur 100+ ansagen
document.addEventListener("alpine:init", function () {
  Alpine.data("callerSettings", function () {
    return {
      open: false, list: [], voice: "", every: true,
      loading: false,
      load() {
        var c = window.fdCaller.settings();
        this.list = window.fdCaller.voices().map(function (v) { return { name: v.name, label: window.fdCaller.label(v) }; });
        var known = this.list.some(function (v) { return v.name === c.voice; });
        this.voice = known ? c.voice : "";  // "" = Handy-Standard bzw. automatisch die beste Stimme
        this.every = c.every;
      },
      show() {
        var self = this;
        this.load();
        this.open = true;
        if (!this.list.length) {
          this.loading = true;
          window.fdCaller.ready(function () { self.loading = false; self.load(); });
        }
      },
      store() { window.fdCaller.save({ voice: this.voice, every: this.every }); },
      test() { this.store(); window.fdCaller.say("One hundred and eighty! Chris, you require eighty-one."); },
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
