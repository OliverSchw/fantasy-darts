// Push-Benachrichtigungen ("Du bist dran"): an-/abmelden dieses Geräts.
// window.fdPush wird überall genutzt; das Alpine-Bauteil "pushToggle" steht im Account und im Turnier.
(() => {
  const supported = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  const ios = /iphone|ipad|ipod/i.test(navigator.userAgent);
  const standalone = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;

  const b64 = (s) => {
    const raw = atob((s + "=".repeat((4 - (s.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(raw, (c) => c.charCodeAt(0));
  };
  const post = (url, body) => fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}),
  }).then((r) => { if (!r.ok) throw new Error("server " + r.status); return r.json(); });

  async function current() {
    if (!supported) return null;
    const reg = await navigator.serviceWorker.ready;
    return reg.pushManager.getSubscription();
  }

  async function enable() {
    const perm = await Notification.requestPermission();
    if (perm !== "granted") throw new Error("denied");
    const reg = await navigator.serviceWorker.ready;
    const { key } = await fetch("/push/key").then((r) => r.json());
    let sub = await reg.pushManager.getSubscription();
    const opts = { userVisibleOnly: true, applicationServerKey: b64(key) };
    try {
      sub = sub || await reg.pushManager.subscribe(opts);
    } catch (e) {  // altes Abo mit anderem Schlüssel -> neu anmelden
      if (sub) await sub.unsubscribe();
      sub = await reg.pushManager.subscribe(opts);
    }
    await post("/push/subscribe", sub.toJSON());
    return sub;
  }

  async function disable() {
    const sub = await current();
    if (!sub) return;
    await post("/push/unsubscribe", { endpoint: sub.endpoint }).catch(() => {});
    await sub.unsubscribe();
  }

  // Ein angemeldetes Gerät gehört immer dem, der gerade eingeloggt ist (einmal pro Sitzung abgleichen).
  async function sync(username) {
    if (!supported || Notification.permission !== "granted") return;
    const flag = "fd-push-sync";
    try { if (sessionStorage.getItem(flag) === username) return; } catch (e) {}
    const sub = await current();
    if (!sub) return;
    await post("/push/subscribe", sub.toJSON());
    try { sessionStorage.setItem(flag, username); } catch (e) {}
  }

  window.fdPush = { supported, ios, standalone, enable, disable, current, sync };

  document.addEventListener("alpine:init", () => {
    Alpine.data("pushToggle", (compact = false) => ({
      supported, needsInstall: !supported && ios && !standalone, on: false, busy: false, msg: "",
      hidden: compact,
      async init() {
        if (!supported) return;
        this.on = !!(await current()) && Notification.permission === "granted";
        let dismissed = false;
        try { dismissed = localStorage.getItem("fd-push-dismiss") === "1"; } catch (e) {}
        this.hidden = compact && (this.on || dismissed || Notification.permission === "denied");
      },
      async toggle() {
        this.busy = true; this.msg = "";
        try {
          if (this.on) { await disable(); this.on = false; this.msg = "Notifications are off on this device."; }
          else { await enable(); this.on = true; this.msg = "Done – you'll get a message when it's your turn."; }
        } catch (e) {
          console.warn("push:", e);
          this.msg = e.message === "denied"
            ? "Notifications are blocked – allow them for this site in your browser / phone settings."
            : "That didn't work – please try again.";
        }
        this.busy = false;
      },
      async test() {
        this.busy = true;
        try {
          const { sent } = await post("/push/test");
          this.msg = sent ? "Test sent – it should pop up in a few seconds." : "No device reached – turn notifications off and on again.";
        } catch (e) { this.msg = "That didn't work – please try again."; }
        this.busy = false;
      },
      dismiss() {
        this.hidden = true;
        try { localStorage.setItem("fd-push-dismiss", "1"); } catch (e) {}
      },
    }));
  });
})();
