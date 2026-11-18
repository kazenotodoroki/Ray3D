"""SBIR (Speaker Boundary Interference Response) : réponse en fréquence au point d'écoute,
somme complexe du son direct et des réflexions sur les parois proches (sources images).

- Les réflexions sont classées par paroi : mur derrière l'enceinte, murs latéraux, sol, plafond,
  mur derrière l'écoute.
- « Rayonnement arrière » : dans le grave, une enceinte rayonne presque en omni, y compris vers
  l'arrière. La directivité passe d'omni à celle du modèle autour de f_t = c / (π · largeur de face).
- Balayage : écart-type de la réponse lissée dans une bande, en fonction de la distance de
  l'enceinte au mur derrière elle (ou de la position d'écoute).
"""
from __future__ import annotations

import dataclasses
import math

import numpy as np

from . import acoustics as A

CATS = {
    "front": "Mur derrière l'enceinte",
    "side": "Mur latéral",
    "floor": "Sol",
    "ceiling": "Plafond",
    "rear": "Mur derrière l'écoute",
}
SHORT = {"front": "Mur avant", "side": "Latéral", "floor": "Sol", "ceiling": "Plafond", "rear": "Mur arrière"}
CAT_COLORS = {"direct": "#ffffff", "front": "#ff7a1a", "side": "#3ec1ff", "floor": "#b6ff3a",
              "ceiling": "#9b7bff", "rear": "#ff3aa8", "multi": "#ffd23a"}
SMOOTH = {"Aucun": 0.0, "1/48 oct": 1 / 48, "1/24 oct": 1 / 24, "1/12 oct": 1 / 12,
          "1/6 oct": 1 / 6, "1/3 oct": 1 / 3}


# --------------------------------------------------------------------------- classement des parois
def classify(geo, q, R, S, L):
    """Catégorie de la face q (point de réflexion R) pour une source S et une écoute L."""
    n = geo.fN[q]
    if abs(n[2]) > 0.7:
        return "floor" if R[2] < 0.5 * (S[2] + L[2]) else "ceiling"
    u = np.array([S[0] - L[0], S[1] - L[1], 0.0])
    nu = np.linalg.norm(u)
    if nu < 1e-6:
        return "side"
    u /= nu
    if abs(n @ u) > 0.6:
        if (R - S) @ u > 0:
            return "front"
        if (R - L) @ u < 0:
            return "rear"
    return "side"


# --------------------------------------------------------------------------- directivité en fréquence
def pattern_gain_f(s, d0, freqs):
    """Gain (amplitude) du modèle dans la direction d0, pour chaque fréquence."""
    if s.pattern == "Mesuré" and getattr(s, "balloon", None):
        bf = np.asarray(s.balloon["freqs"], float)
        idx = np.argmin(np.abs(np.log(freqs[:, None] / bf[None, :])), axis=1)
        out = np.empty(len(freqs))
        keep = A.CURRENT_FREQ[0]
        try:
            for k in np.unique(idx):
                A.CURRENT_FREQ[0] = float(bf[k])
                out[idx == k] = float(A.gain(s, d0[None])[0])
        finally:
            A.CURRENT_FREQ[0] = keep
        return out
    return np.full(len(freqs), float(A.gain(s, d0[None])[0]))


def gain_f(s, d0, freqs, c, rear_radiation):
    g = pattern_gain_f(s, d0, freqs)
    if not rear_radiation or s.pattern == "Mesuré":
        return g
    ft = c / (math.pi * max(getattr(s, "baffle", 0.3), 0.05))
    w = 1.0 / (1.0 + (freqs / ft) ** 2)            # 1 dans le grave (omni), 0 dans l'aigu
    return w + (1.0 - w) * g


# --------------------------------------------------------------------------- calcul
def smooth_db(freqs, p2, frac):
    """Lissage en fraction d'octave d'une puissance |H|² (grille logarithmique)."""
    if frac <= 0 or len(freqs) < 3:
        return 10 * np.log10(np.maximum(p2, 1e-20))
    ppo = (len(freqs) - 1) / math.log2(freqs[-1] / freqs[0])
    h = max(int(round(ppo * frac / 2)), 0)
    if h == 0:
        return 10 * np.log10(np.maximum(p2, 1e-20))
    cs = np.concatenate([[0.0], np.cumsum(p2)])
    i = np.arange(len(p2))
    lo, hi = np.maximum(i - h, 0), np.minimum(i + h + 1, len(p2))
    return 10 * np.log10(np.maximum((cs[hi] - cs[lo]) / (hi - lo), 1e-20))


def paths_for(geo, sources, L, order, c):
    paths = A.reflection_paths(geo, sources, L, order, c)
    for p in paths:
        if p["order"] == 0:
            p["cat"] = "direct"
        else:
            S = p["src"].pos
            cats = [classify(geo, q, np.asarray(R), S, L) for q, R in zip(p["faces"], p["pts"][1:-1])]
            p["cats"] = cats
            p["cat"] = cats[0]                  # couleur : première paroi touchée
            p["color"] = CAT_COLORS[p["cat"]]
    return paths


def response(scene, geo, sources, L, opts, c, freqs=None, paths=None):
    """Réponse complexe au point L. opts : dict (order, rear_radiation, cats{}, apply_delays)."""
    if freqs is None:
        freqs = np.geomspace(opts.get("fmin", 20.0), opts.get("fmax", 1000.0), opts.get("nf", 700))
    if paths is None:
        paths = paths_for(geo, sources, L, opts.get("order", 1), c)
    enabled = opts.get("cats", {})
    H = np.zeros(len(freqs), complex)
    Hd = np.zeros(len(freqs), complex)
    used = []
    for p in paths:
        if p["order"] > 0 and not all(enabled.get(k, True) for k in p["cats"]):
            continue
        s = p["src"]
        tau = scene.delays.get(s.id, 0.0) / 1000 if opts.get("apply_delays", True) else 0.0
        g = gain_f(s, np.asarray(p["d0"], float), freqs, c, opts.get("rear_radiation", True))
        absf = 1.0
        for q in p["faces"]:
            absf *= math.sqrt(max(1 - geo.fA[q], 0.0))
        amp = 10 ** (s.level / 20) * g * absf / max(p["length"], 0.05)
        p["amp_f"] = amp
        p["freqs"] = freqs
        h = amp * np.exp(-2j * np.pi * freqs * (p["length"] / c + tau))
        H += h
        if p["order"] == 0:
            Hd += h
        used.append(p)
    return freqs, H, Hd, used


def reflection_table(used, c):
    """Lignes du tableau : une par réflexion, avec écart de trajet et premier creux."""
    direct = {p["src"].id: p for p in used if p["order"] == 0}
    rows = []
    for p in used:
        if p["order"] == 0:
            continue
        d = direct.get(p["src"].id)
        if d is None:
            continue
        delta = p["length"] - d["length"]
        notch = c / (2 * delta) if delta > 1e-6 else float("inf")
        rel = p["rel"]
        if "amp_f" in p and "amp_f" in d:          # niveau relatif à la fréquence du premier creux
            fr = p["freqs"]
            k = int(np.argmin(np.abs(np.log(fr / min(max(notch, fr[0]), fr[-1])))))
            rel = 20 * math.log10(max(p["amp_f"][k], 1e-12) / max(d["amp_f"][k], 1e-12))
        chain = " → ".join(SHORT.get(k, k) for k in p.get("cats", [p["cat"]]))
        rows.append(dict(src=p["src"], cat=p["cat"], surf=p["surf"], order=p["order"], delta=delta,
                         dt=delta / c * 1000, notch=notch, rel=rel, chain=chain))
    rows.sort(key=lambda r: r["delta"])
    return rows


def flatness(freqs, H, lo, hi, frac=1 / 6):
    """Écart-type (dB) de la réponse lissée dans la bande [lo, hi]."""
    db = smooth_db(freqs, np.abs(H) ** 2, frac)
    m = (freqs >= lo) & (freqs <= hi)
    if m.sum() < 3:
        return float("nan")
    return float(np.std(db[m] - db[m].mean()))


# --------------------------------------------------------------------------- balayage
def wall_distance(geo, sources, direction):
    """Distance (le long de -direction) entre le centre acoustique et la paroi derrière."""
    C = np.mean([s.pos for s in sources], 0)
    t, i = geo.first_hit(C[None], (-direction)[None])
    return float(t[0]) if i[0] >= 0 else float("inf"), C


def scan_speaker(scene, geo, sources, L, opts, c, depth, dmin, dmax, n=60):
    """Déplace les sources le long de leur axe horizontal ; distance = face avant → mur derrière."""
    az = math.radians(float(np.mean([s.az for s in sources])))
    fh = np.array([math.cos(az), math.sin(az), 0.0])
    cur, _ = wall_distance(geo, sources, fh)
    if not math.isfinite(cur):
        return None
    freqs = np.geomspace(max(opts.get("fmin", 20.0), 15.0), opts.get("fmax", 1000.0), 500)
    ds = np.linspace(max(dmin, depth + 0.01), dmax, n)
    out = []
    for d in ds:
        off = d - cur
        moved = [dataclasses.replace(s, x=s.x + fh[0] * off, y=s.y + fh[1] * off) for s in sources]
        f, H, _, _ = response(scene, geo, moved, L, opts, c, freqs)
        out.append(flatness(f, H, opts["band_lo"], opts["band_hi"]))
    out = np.array(out)
    k = int(np.nanargmin(out)) if np.isfinite(out).any() else 0
    return dict(dist=ds, dev=out, best=float(ds[k]), best_dev=float(out[k]), current=cur,
                direction=fh)


def scan_listener(scene, geo, sources, L, opts, c, axis, xmin, xmax, n=60):
    """Déplace le point d'écoute le long d'un axe (X ou Y)."""
    freqs = np.geomspace(max(opts.get("fmin", 20.0), 15.0), opts.get("fmax", 1000.0), 500)
    k_ax = 0 if axis == "X" else 1
    xs = np.linspace(xmin, xmax, n)
    out = []
    for x in xs:
        P = L.copy(); P[k_ax] = x
        f, H, _, _ = response(scene, geo, sources, P, opts, c, freqs)
        out.append(flatness(f, H, opts["band_lo"], opts["band_hi"]))
    out = np.array(out)
    k = int(np.nanargmin(out)) if np.isfinite(out).any() else 0
    return dict(dist=xs, dev=out, best=float(xs[k]), best_dev=float(out[k]), current=float(L[k_ax]))
