// Diagramme: Punkt antippen / mit der Tastatur anwählen -> Wert unter dem Diagramm anzeigen.
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("figure.chart").forEach((fig) => {
    const tip = fig.querySelector(".ch-tip");
    const show = (g) => {
      fig.querySelectorAll(".ch-pt.on").forEach((x) => x.classList.remove("on"));
      g.classList.add("on");
      tip.textContent = g.querySelector("title").textContent;
    };
    fig.querySelectorAll(".ch-pt").forEach((g) => {
      g.addEventListener("click", () => show(g));
      g.addEventListener("focus", () => show(g));
      g.addEventListener("mouseenter", () => show(g));
    });
    const pts = fig.querySelectorAll(".ch-pt");
    if (pts.length) show(pts[pts.length - 1]);  // zuletzt: neuester Wert
  });
});
