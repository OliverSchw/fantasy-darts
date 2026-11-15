// Team-Builder (Alpine.js). Die Regeln kommen vom Server; geprüft wird dort nochmal alles.
document.addEventListener("alpine:init", () => {
  const cfg = JSON.parse(document.getElementById("builder-data").textContent);
  const EPS = 0.001;

  Alpine.data("teamBuilder", () => ({
    players: cfg.players,
    byId: Object.fromEntries(cfg.players.map((p) => [p.id, p])),
    budget: cfg.budget,
    squadSize: cfg.squadSize,
    selected: [...cfg.initial.selected],
    playmaker: cfg.initial.playmaker,
    underdog: cfg.initial.underdog,
    champion: cfg.initial.champion,
    name: cfg.initial.name,
    q: "",
    sort: "price_desc",
    onlySelected: false,
    submitting: false,

    init() {
      // Rollen zurücksetzen, wenn der Spieler abgewählt wird
      this.$watch("selected", () => {
        if (!this.selected.includes(this.playmaker)) this.playmaker = null;
        if (!this.selected.includes(this.underdog)) this.underdog = null;
      });
    },

    get byPrice() {
      return [...this.players].sort((a, b) => b.price - a.price || a.name.localeCompare(b.name));
    },
    get visible() {
      const q = this.q.trim().toLowerCase();
      let list = this.players.filter(
        (p) =>
          (!this.onlySelected || this.isSel(p.id)) &&
          (!q || p.name.toLowerCase().includes(q) || (p.nation || "").toLowerCase().includes(q))
      );
      const cmp = {
        price_desc: (a, b) => b.price - a.price || a.name.localeCompare(b.name),
        price_asc: (a, b) => a.price - b.price || a.name.localeCompare(b.name),
        name: (a, b) => a.name.localeCompare(b.name),
      }[this.sort];
      return list.sort(cmp);
    },
    get spent() {
      return this.selected.reduce((sum, id) => sum + this.byId[id].price, 0);
    },
    get remaining() {
      return this.budget - this.spent;
    },
    isSel(id) {
      return this.selected.includes(id);
    },
    canAdd(p) {
      return this.selected.length < this.squadSize && p.price <= this.remaining + EPS;
    },
    toggle(id) {
      if (this.isSel(id)) this.selected = this.selected.filter((x) => x !== id);
      else if (this.canAdd(this.byId[id])) this.selected = [...this.selected, id];
    },
    eligible(maxPrice) {
      return this.selected
        .map((id) => this.byId[id])
        .filter((p) => p.price <= maxPrice + EPS)
        .sort((a, b) => b.price - a.price);
    },
    get playmakerOk() {
      return this.playmaker && this.eligible(cfg.pmMax).some((p) => p.id === this.playmaker);
    },
    get underdogOk() {
      return this.underdog && this.eligible(cfg.udMax).some((p) => p.id === this.underdog);
    },
    get valid() {
      return (
        this.selected.length === this.squadSize &&
        this.remaining >= -EPS &&
        this.playmakerOk &&
        this.underdogOk &&
        !!this.champion &&
        this.name.trim().length > 0
      );
    },
  }));
});
