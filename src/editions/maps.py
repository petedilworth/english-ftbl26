"""
The catchment map: each neighbourhood a dot, coloured by the club that
draws most of it.

No boundary files - the model has population-weighted MSOA centroids,
which is enough: a dot per neighbourhood, sized by population, draws the
shape of where people live without a coastline. Emphasis form: the clubs
the edition is about get the first three categorical slots, validated
all-pairs (docs/editions.md; the dataviz reference palette), and every
other club's ground is grey context. Identity is never colour alone - each
coloured club has a legend entry and a direct label at its ground.
"""

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]   # validated all-pairs, light surface
OTHER = "#d9d7d1"                             # every club not being discussed
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SOFT = "#52514e"

MIN_HALF_SPAN_MILES = 10.0
MAX_HALF_SPAN_MILES = 45.0
MILES_PER_DEG_LAT = 69.0
MIN_DOTS_TO_COLOUR = 3


def catchment_map(model, focus: list[str], names: dict[str, str], out_path: Path,
                  region_of: list[str] | None = None) -> Path | None:
    """
    focus: up to three club_ids, coloured in order. region_of: the clubs
    whose doorsteps set the frame (default: the first focus club).
    Returns the PNG path, or None if nothing can be drawn.
    """
    import numpy as np

    focus = [c for c in focus if c in model.index][:len(SERIES)]
    region_of = [c for c in (region_of or focus[:1]) if c in model.index]
    if not focus or not region_of:
        return None

    mask = np.zeros(len(model.pop), dtype=bool)
    for cid in region_of:
        mask |= model.turf(cid)
    if not mask.any():
        return None

    lat0 = float(np.average(model.msoa_lat[mask], weights=model.pop[mask]))
    lon0 = float(np.average(model.msoa_lon[mask], weights=model.pop[mask]))
    kx = math.cos(math.radians(lat0)) * MILES_PER_DEG_LAT       # miles per degree lon
    ky = MILES_PER_DEG_LAT

    def to_xy(lat, lon):
        return (np.asarray(lon) - lon0) * kx, (np.asarray(lat) - lat0) * ky

    rx, ry = to_xy(model.msoa_lat[mask], model.msoa_lon[mask])
    half = max(np.percentile(np.abs(rx), 95), np.percentile(np.abs(ry), 95)) * 1.25
    half = float(min(max(half, MIN_HALF_SPAN_MILES), MAX_HALF_SPAN_MILES))

    x, y = to_xy(model.msoa_lat, model.msoa_lon)
    view = (np.abs(x) <= half) & (np.abs(y) <= half * 0.72)
    # A club that wins nothing in frame gets no colour and no legend entry:
    # a key for a colour the reader cannot find is noise.
    from collections import Counter
    wins = Counter(int(w) for w in model.winner[view])
    # The first club is the subject and always keeps its colour; a rival
    # needs a few neighbourhoods in frame to earn one.
    focus = focus[:1] + [c for c in focus[1:] if wins[model.index[c]] >= MIN_DOTS_TO_COLOUR]
    focus = [c for c in focus if wins[model.index[c]] > 0]
    if not focus:
        return None
    colour_of = {model.index[c]: SERIES[i] for i, c in enumerate(focus)}
    colours = [colour_of.get(int(w), OTHER) for w in model.winner[view]]
    size = 4 + 14 * (model.pop[view] / max(model.pop[view].max(), 1.0))

    fig, ax = plt.subplots(figsize=(7.0, 5.0), dpi=100)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    # A thin surface ring on every dot, so overlapping dots stay separate.
    ax.scatter(x[view], y[view], s=size, c=colours, linewidths=0.4, edgecolors=SURFACE, zorder=2)

    # Grounds: every club in frame as a small grey ring; the focus clubs in
    # their colour, ringed in the surface, with a label in text ink.
    cx, cy = to_xy(model.club_lat, model.club_lon)
    in_frame = (np.abs(cx) <= half) & (np.abs(cy) <= half * 0.72)
    focus_idx = {model.index[c] for c in focus}
    others = [i for i in np.flatnonzero(in_frame) if i not in focus_idx]
    ax.scatter(cx[others], cy[others], s=22, facecolors=SURFACE, edgecolors="#8a8984",
               linewidths=1.0, zorder=3)
    for n, cid in enumerate(focus):
        i = model.index[cid]
        if not in_frame[i]:
            continue
        ax.scatter([cx[i]], [cy[i]], s=110, c=SERIES[n], edgecolors=SURFACE, linewidths=2.0, zorder=4)
        ax.annotate(names.get(cid, cid), (cx[i], cy[i]), xytext=(7, 6), textcoords="offset points",
                    fontsize=10, fontweight="bold", color=INK, zorder=5,
                    bbox={"boxstyle": "round,pad=0.2", "fc": SURFACE, "ec": "none", "alpha": 0.85})

    handles = [Line2D([0], [0], marker="o", linestyle="", markersize=8, markerfacecolor=SERIES[n],
                      markeredgecolor=SURFACE, label=f"Drawn most by {names.get(c, c)}")
               for n, c in enumerate(focus)]
    handles.append(Line2D([0], [0], marker="o", linestyle="", markersize=8, markerfacecolor=OTHER,
                          markeredgecolor=SURFACE, label="Drawn most by another club"))
    leg = ax.legend(handles=handles, loc="lower left", fontsize=8.5, frameon=True, framealpha=0.9,
                    facecolor=SURFACE, edgecolor="#e4e2dc", labelcolor=INK)
    leg.set_zorder(6)

    ax.text(0.99, 0.01, f"{2 * half:.0f} miles across · each dot a neighbourhood, sized by population",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=7.5, color=INK_SOFT)
    ax.set_xlim(-half, half)
    ax.set_ylim(-half * 0.72, half * 0.72)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.tight_layout(pad=0.3)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=SURFACE)
    plt.close(fig)
    return out_path
