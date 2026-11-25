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
  Alpine.data("scorer", function (rest, finishable, minDarts) {
    var IMPOSSIBLE = [163, 166, 169, 172, 173, 175, 176, 178, 179];
    return {
      entry: "", error: "", busy: false, needDarts: false,
      press(d) { this.error = ""; if (this.entry.length < 3) this.entry = (this.entry + d).replace(/^0+(?=\d)/, ""); },
      back() { this.error = ""; this.entry = this.entry.slice(0, -1); },
      quick(n) { this.entry = String(n); this.ok(); },
      ok() {
        var score = parseInt(this.entry || "0", 10);
        if (score > 180 || IMPOSSIBLE.indexOf(score) >= 0) { this.error = score + " isn't possible"; return; }
        if (finishable && score === rest) { this.needDarts = true; return; }
        this.send(score, "");
      },
      send(score, darts) {
        if (this.busy) return;
        this.busy = true;
        this.$refs.score.value = score;
        this.$refs.darts.value = darts;
        var form = this.$refs.form;
        window.fdCaller.say(window.fdCaller.phrase(score, rest, finishable), function () { form.submit(); });
      },
      typing() { return this.entry !== "" || this.needDarts; },
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
    var el = document.querySelector("[x-data^='scorer'], [x-data^='dartPad']");
    return el && el._x_dataStack && el._x_dataStack[0].typing();
  }
  setInterval(function () {
    if (document.hidden || busyTyping()) return;
    fetch("/darts/games/" + cfg.id + "/version", { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d && (d.v !== cfg.v || d.status !== "live")) location.reload(); })
      .catch(function () {});
  }, 3000);
})();
