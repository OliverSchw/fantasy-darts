"""Kleine Liniendiagramme als SVG (ohne Bibliothek): Geometrie hier, Zeichnen im Template (_chart.html)."""

import math
from dataclasses import dataclass

W, H = 320, 150  # viewBox
LEFT, RIGHT, TOP, BOTTOM = 34, 8, 10, 20


@dataclass
class Point:
    x: float
    y: float
    value: float
    label: str  # Tooltip
    hollow: bool = False  # z. B. verlorenes Spiel


def _nice_step(span: float, ticks: int = 3) -> float:
    raw = span / ticks
    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    return next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)


def line_chart(values: list[tuple[float, str, bool]], baseline: float | None = None, fmt: str = "{:.0f}") -> dict | None:
    """values = [(Wert, Tooltip, hohl?)] in zeitlicher Reihenfolge. baseline = gestrichelte Hilfslinie (z. B. 1000 Elo).
    Gibt None zurück, wenn es weniger als 2 Punkte gibt (dann lohnt kein Diagramm)."""
    if len(values) < 2:
        return None
    vs = [v for v, _, _ in values] + ([baseline] if baseline is not None else [])
    lo, hi = min(vs), max(vs)
    if hi - lo < 1e-9:
        lo, hi = lo - 1, hi + 1
    step = _nice_step(hi - lo)
    lo, hi = math.floor(lo / step) * step, math.ceil(hi / step) * step
    pw, ph = W - LEFT - RIGHT, H - TOP - BOTTOM
    n = len(values)

    def y_of(v):
        return TOP + ph - (v - lo) / (hi - lo) * ph

    pts = [Point(LEFT + (i / (n - 1)) * pw, y_of(v), v, label, hollow) for i, (v, label, hollow) in enumerate(values)]
    ticks = []
    t = lo
    while t <= hi + step / 2:
        ticks.append({"y": y_of(t), "label": fmt.format(t)})
        t += step
    return {
        "w": W, "h": H, "left": LEFT, "right": W - RIGHT, "top": TOP, "bottom": TOP + ph,
        "points": pts, "path": "M" + " L".join(f"{p.x:.1f},{p.y:.1f}" for p in pts), "ticks": ticks,
        "baseline": y_of(baseline) if baseline is not None else None,
        "first": values[0][1].split(" · ")[0], "last": values[-1][1].split(" · ")[0],
        "markers": n <= 40,
    }
