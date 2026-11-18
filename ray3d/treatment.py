"""Traitement acoustique des premières réflexions (hors bass traps).

Pour chaque paroi de la pièce (murs, sol, plafond), on cherche les points de réflexion du premier
ordre entre chaque source et une petite « zone d'écoute » autour de la tête (boîte largeur ×
profondeur × hauteur). Le rectangle qui englobe ces points, plus une marge, est la surface minimale
à traiter sur cette paroi.

Chaque zone a un repère 2D (u, v) en mètres :
- mur : u horizontal de gauche à droite vu depuis l'intérieur de la pièce, v vers le haut depuis le
  bas du mur ;
- sol / plafond : u = X, v = Y (vue en plan), depuis le coin minimal de la face.

Les panneaux se posent ensuite en grille, centrés sur la zone, dans l'orientation qui demande le
moins de panneaux.
"""
from __future__ import annotations

import math
import types
from dataclasses import dataclass, field

import numpy as np

from . import acoustics as A
from . import geometry as G
from .model import Assembly, Shape
from .paths import _segments_clear

TREAT_NAME = "Traitement acoustique"
PANEL_SIZES = {
    "120 × 60 cm": (1.2, 0.6),
    "60 × 60 cm": (0.6, 0.6),
    "120 × 30 cm": (1.2, 0.3),
    "100 × 50 cm": (1.0, 0.5),
    "60 × 30 cm": (0.6, 0.3),
    "Sur mesure": None,
    "Zone entière (1 panneau)": "zone",
}
ORIENTS = ["Auto", "Portrait", "Paysage"]
KIND_ABBR = {"Mur avant": "MAV", "Mur arrière": "MAR", "Mur gauche": "MG", "Mur droit": "MD",
             "Sol": "SOL", "Plafond": "PLA"}
EZ = np.array([0.0, 0.0, 1.0])


@dataclass
class Zone:
    key: str                     # identifiant stable (forme·face)
    label: str                   # « Mur gauche »…
    kind: str                    # wall / floor / ceiling
    face_name: str
    shape_id: str
    fi: int                      # index de face dans Geometry
    O: np.ndarray                # origine du repère (u, v) = (0, 0)
    eu: np.ndarray
    ev: np.ndarray
    n_in: np.ndarray             # normale vers l'intérieur de la pièce
    poly: np.ndarray             # contour de la face en (u, v)
    W: float                     # étendue de la face
    H: float
    rect: tuple = None           # (u0, v0, u1, v1) zone minimale
    level: float = -99.0         # niveau max réfléchi / direct (dB)
    pts: np.ndarray = None       # points de réflexion (u, v)
    center: np.ndarray = None    # point de réflexion pour la tête au centre (u, v) ou None
    sources: list = field(default_factory=list)

    @property
    def w(self):
        return self.rect[2] - self.rect[0]

    @property
    def h(self):
        return self.rect[3] - self.rect[1]

    def to3(self, uv):
        uv = np.atleast_2d(np.asarray(uv, float))
        return self.O + uv[:, 0:1] * self.eu + uv[:, 1:2] * self.ev

    def to_uv(self, P):
        D = np.atleast_2d(P) - self.O
        return np.stack([D @ self.eu, D @ self.ev], 1)

    @property
    def abbr(self):
        parts = self.label.rsplit(" ", 1)
        if len(parts) == 2 and parts[1].isdigit():
            return KIND_ABBR.get(parts[0], "Z") + parts[1]
        return KIND_ABBR.get(self.label, "Z")

    def describe(self):
        u0, v0, u1, v1 = self.rect
        if self.kind == "wall":
            return (f"{self.w:.2f} × {self.h:.2f} m · à {u0:.2f} m du coin gauche, "
                    f"de {v0:.2f} à {v1:.2f} m du sol")
        X0, Y0 = self.O[0] + u0, self.O[1] + v0
        return f"{self.w:.2f} × {self.h:.2f} m · X {X0:.2f} → {X0 + self.w:.2f}, Y {Y0:.2f} → {Y0 + self.h:.2f}"


# --------------------------------------------------------------------------- géométrie
def treatment_ids(scene):
    """Ensembles et formes du traitement posé (exclus du calcul des zones)."""
    aid = getattr(scene.settings, "treat_assembly", "")
    a = scene.assembly(aid) if aid else None
    if a is None:
        return set(), set()
    subs = {x.id for x in scene.descendant_assemblies(a.id)} | {a.id}
    return subs, {s.id for s in scene.all_shapes_in(a.id)}


def bare_geometry(scene):
    """Géométrie de la scène sans les panneaux de traitement."""
    _, sids = treatment_ids(scene)
    return A.Geometry(types.SimpleNamespace(shapes=[s for s in scene.shapes if s.id not in sids]))


def forward_dir(sources, L):
    C = np.mean([s.pos for s in sources], 0)
    f = np.array([C[0] - L[0], C[1] - L[1], 0.0])
    n = np.linalg.norm(f)
    return f / n if n > 1e-6 else np.array([1.0, 0, 0])


def _frame(face, kind):
    n_out = np.asarray(face.normal, float)
    if kind == "wall":
        eu = np.cross(n_out, EZ)
        eu /= max(np.linalg.norm(eu), 1e-12)
        ev = np.cross(eu, n_out)
        ev /= max(np.linalg.norm(ev), 1e-12)
    else:
        eu, ev = np.array([1.0, 0, 0]), np.array([0, 1.0, 0])
    V = face.verts
    uv = np.stack([V @ eu, V @ ev], 1)
    lo = uv.min(0)
    O = lo[0] * eu + lo[1] * ev
    # O sur le plan de la face
    O = O + ((V[0] - O) @ n_out) * n_out
    poly = uv - lo
    return O, eu, ev, -n_out, poly


def room_faces(scene, geo, fwd):
    """Faces des pièces : (shape, face, kind, label, fi)."""
    out = []
    names = {(geo.fshape[i], geo.fname[i]): i for i in range(geo.F)}
    left = np.cross(EZ, fwd)
    count = {}
    for sh in scene.shapes:
        if sh.kind != "Pièce":
            continue
        for f in sh.faces():
            fi = names.get((sh.id, f"{sh.name}·{f.name}"))
            if fi is None:
                continue
            n_in = -np.asarray(f.normal)
            if abs(n_in[2]) > 0.7:
                kind = "floor" if n_in[2] > 0 else "ceiling"
                label = "Sol" if kind == "floor" else "Plafond"
            else:
                kind = "wall"
                c = n_in @ fwd
                if c < -0.7:
                    label = "Mur avant"
                elif c > 0.7:
                    label = "Mur arrière"
                else:
                    label = "Mur gauche" if n_in @ left < 0 else "Mur droit"
            count[label] = count.get(label, 0) + 1
            out.append([sh, f, kind, label, fi])
    seen = {}
    for item in out:                       # doublons : Mur gauche 1, Mur gauche 2…
        lab = item[3]
        if count[lab] > 1:
            seen[lab] = seen.get(lab, 0) + 1
            item[3] = f"{lab} {seen[lab]}"
    return out


def listener_box(L, fwd, w, d, h, n=(3, 5, 3)):
    left = np.cross(EZ, fwd)
    xs = np.linspace(-d / 2, d / 2, n[0]) if d > 0 else [0.0]
    ys = np.linspace(-w / 2, w / 2, n[1]) if w > 0 else [0.0]
    zs = np.linspace(-h / 2, h / 2, n[2]) if h > 0 else [0.0]
    P = [L + a * fwd + b * left + c * EZ for a in xs for b in ys for c in zs]
    return np.array(P)


@np.errstate(invalid="ignore", divide="ignore")
def _reflections(geo, s, P, fi):
    """Points de réflexion valides de la source s vers les points P sur la face fi."""
    S = np.asarray(s.pos, float)
    O, N = geo.fO[fi], geo.fN[fi]
    if (S - O) @ N >= -1e-6:                # source hors de la pièce (côté réfléchissant)
        return np.zeros((0, 3)), np.zeros(0)
    I = S - 2 * ((S - O) @ N) * N
    D = I - P
    t = ((O - P) @ N) / (D @ N)
    ok = (t > 1e-6) & (t < 1 - 1e-6)
    R = P + t[:, None] * D
    idx = np.nonzero(ok)[0]
    if len(idx):
        idx = idx[geo.in_face(R[idx], fi)]
    if len(idx):
        fa = np.full(len(idx), -1); fb = np.full(len(idx), fi)
        idx = idx[_segments_clear(geo, np.repeat(S[None], len(idx), 0), R[idx], fa, fb)]
    if len(idx):
        idx = idx[_segments_clear(geo, R[idx], P[idx], np.full(len(idx), fi), np.full(len(idx), -1))]
    R, Pv = R[idx], P[idx]
    if not len(R):
        return R, np.zeros(0)
    d1 = R - S
    l1 = np.linalg.norm(d1, axis=1)
    l2 = np.linalg.norm(Pv - R, axis=1)
    dd = Pv - S
    ld = np.linalg.norm(dd, axis=1)
    g1 = A.gain(s, d1 / l1[:, None])
    g0 = A.gain(s, dd / ld[:, None])
    rel = 20 * np.log10(np.maximum(ld / (l1 + l2) * g1 / np.maximum(g0, 1e-6), 1e-9))
    return R, rel


def compute_zones(scene, sources, L, opts):
    """opts : head_w, head_d, head_h, margin, min_level (dB), surfaces {wall, floor, ceiling, front, rear}."""
    if not sources or L is None:
        return []
    geo = bare_geometry(scene)
    if geo.F == 0:
        return []
    L = np.asarray(L, float)
    fwd = forward_dir(sources, L)
    P = listener_box(L, fwd, opts.get("head_w", 0.6), opts.get("head_d", 0.3), opts.get("head_h", 0.2))
    zones = []
    for sh, f, kind, label, fi in room_faces(scene, geo, fwd):
        allR, allrel, cen, names = [], [], [], []
        for s in sources:
            R, rel = _reflections(geo, s, P, fi)
            if len(R):
                allR.append(R); allrel.append(rel); names.append(s.name)
            Rc, _ = _reflections(geo, s, L[None], fi)
            cen += list(Rc)
        if not allR:
            continue
        R = np.vstack(allR)
        rel = np.concatenate(allrel)
        level = float(rel.max())
        if level < opts.get("min_level", -30.0):
            continue
        O, eu, ev, n_in, poly = _frame(f, kind)
        W, H = poly.max(0)
        z = Zone(key=f"{sh.id}:{f.name}", label=label, kind=kind, face_name=f"{sh.name} · {f.name}",
                 shape_id=sh.id, fi=fi, O=O, eu=eu, ev=ev, n_in=n_in, poly=poly, W=float(W), H=float(H),
                 level=level, sources=sorted(set(names)))
        uv = z.to_uv(R)
        m = opts.get("margin", 0.1)
        lo = np.maximum(uv.min(0) - m, 0.0)
        hi = np.minimum(uv.max(0) + m, [W, H])
        z.rect = (float(lo[0]), float(lo[1]), float(hi[0]), float(hi[1]))
        z.pts = uv
        z.center = z.to_uv(np.array(cen)) if cen else None
        zones.append(z)
    order = {"Mur avant": 0, "Mur gauche": 1, "Mur droit": 2, "Mur arrière": 3, "Plafond": 4, "Sol": 5}
    zones.sort(key=lambda z: (order.get(" ".join(z.label.split(" ")[:2]) if z.kind == "wall" else z.label, 9),
                              z.label))
    return zones


# --------------------------------------------------------------------------- panneaux
def default_cfg(zone, st):
    return dict(on=True, size=("Zone entière (1 panneau)" if zone.kind == "floor" else st.treat_size),
                w=1.2, h=0.6, orient="Auto", t=(0.01 if zone.kind == "floor" else st.treat_thick))


def zone_cfg(zone, st):
    cfg = default_cfg(zone, st)
    cfg.update((st.treat_panels or {}).get(zone.key, {}))
    return cfg


def layout(zone, cfg, gap=0.0):
    """Grille de panneaux couvrant la zone. Renvoie dict(rects=[(u, v, w, h)], nu, nv, pw, ph, block)."""
    zw, zh = zone.w, zone.h
    size = PANEL_SIZES.get(cfg.get("size"), None)
    if size == "zone":
        return dict(rects=[(zone.rect[0], zone.rect[1], zw, zh)], nu=1, nv=1, pw=zw, ph=zh,
                    block=(zone.rect[0], zone.rect[1], zw, zh))
    if size is None:
        size = (max(cfg.get("w", 1.2), 0.05), max(cfg.get("h", 0.6), 0.05))
    a, b = max(size), min(size)
    # portrait = le grand côté vertical (v) ; au sol/plafond : grand côté selon Y
    cands = {"Portrait": [(b, a)], "Paysage": [(a, b)]}.get(cfg.get("orient", "Auto"), [(a, b), (b, a)])
    best = None
    cu, cv = (zone.rect[0] + zone.rect[2]) / 2, (zone.rect[1] + zone.rect[3]) / 2
    for pw, ph in cands:
        nu = max(1, math.ceil((zw + gap - 1e-6) / (pw + gap)))
        nv = max(1, math.ceil((zh + gap - 1e-6) / (ph + gap)))
        while nu > 1 and nu * pw + (nu - 1) * gap > zone.W + 1e-6:
            nu -= 1
        while nv > 1 and nv * ph + (nv - 1) * gap > zone.H + 1e-6:
            nv -= 1
        bw, bh = nu * pw + (nu - 1) * gap, nv * ph + (nv - 1) * gap
        u0 = min(max(cu - bw / 2, 0.0), max(zone.W - bw, 0.0))
        v0 = min(max(cv - bh / 2, 0.0), max(zone.H - bh, 0.0))
        cover = _overlap((u0, v0, u0 + bw, v0 + bh), zone.rect) / max(zw * zh, 1e-9)
        score = (-round(cover, 3), nu * nv, bw * bh)
        if best is None or score < best[0]:
            rects = [(u0 + i * (pw + gap), v0 + j * (ph + gap), pw, ph) for j in range(nv) for i in range(nu)]
            best = (score, dict(rects=rects, nu=nu, nv=nv, pw=pw, ph=ph, block=(u0, v0, bw, bh), cover=cover))
    return best[1]


def _overlap(r1, r2):
    w = min(r1[2], r2[2]) - max(r1[0], r2[0])
    h = min(r1[3], r2[3]) - max(r1[1], r2[1])
    return max(w, 0) * max(h, 0)


def remove_treatment(scene):
    aids, sids = treatment_ids(scene)
    scene.shapes = [s for s in scene.shapes if s.id not in sids]
    scene.assemblies = [a for a in scene.assemblies if a.id not in aids]
    scene.settings.treat_assembly = ""
    return len(sids)


def place_panels(scene, zones, gap=0.0):
    """Crée les panneaux (formes « Objet ») dans un ensemble « Traitement acoustique »."""
    st = scene.settings
    remove_treatment(scene)
    root = Assembly(name=TREAT_NAME)
    created = []
    for z in zones:
        cfg = zone_cfg(z, st)
        if not cfg["on"]:
            continue
        lay = layout(z, cfg, gap)
        if z.kind == "wall" and abs(z.ev[2]) < 0.99:       # mur incliné : non géré
            continue
        sub = Assembly(name=f"Panneaux · {z.label}", parent=root.id)
        t = max(float(cfg["t"]), 0.005)
        for k, (u, v, w, h) in enumerate(lay["rects"]):
            P0 = z.to3([u, v])[0]
            name = f"{z.abbr}-{k + 1}"
            if z.kind == "wall":
                rot = math.degrees(math.atan2(z.eu[1], z.eu[0]))
                pos = P0 + z.n_in * t
                sh = Shape(name=name, kind="Objet", plane="XZ", profile=[[0, 0], [w, 0], [w, h], [0, h]],
                           height=t, x=pos[0], y=pos[1], z=pos[2], rot=rot, absorption=st.treat_alpha,
                           assembly=sub.id)
            else:
                zz = P0[2] if z.kind == "floor" else P0[2] - t
                sh = Shape(name=name, kind="Objet", plane="XY", profile=[[0, 0], [w, 0], [w, h], [0, h]],
                           height=t, x=P0[0], y=P0[1], z=zz, absorption=st.treat_alpha, assembly=sub.id)
            for k2 in ("x", "y", "z", "rot"):
                setattr(sh, k2, round(float(getattr(sh, k2)), 6) + 0.0)
            created.append(sh)
        if lay["rects"]:
            scene.assemblies.append(sub)
    if created:
        scene.assemblies.insert(0, root)
        scene.shapes += created
        st.treat_assembly = root.id
    return created


def panel_rects(scene, zones):
    """Panneaux posés, en coordonnées (u, v) de chaque zone : {zone.key: [(u, v, w, h, name)]}."""
    aid = scene.settings.treat_assembly
    out = {z.key: [] for z in zones}
    if not aid or scene.assembly(aid) is None:
        return out
    for s in scene.all_shapes_in(aid):
        V = np.vstack([f.verts for f in s.faces()])
        best = None
        for z in zones:
            d = np.abs((V - z.O) @ z.n_in)
            if d.min() > 0.02:
                continue
            uv = z.to_uv(V)
            lo, hi = uv.min(0), uv.max(0)
            if hi[0] < -0.01 or lo[0] > z.W + 0.01 or hi[1] < -0.01 or lo[1] > z.H + 0.01:
                continue
            if best is None or d.min() < best[0]:
                best = (d.min(), z, lo, hi)
        if best:
            _, z, lo, hi = best
            out[z.key].append((float(lo[0]), float(lo[1]), float(hi[0] - lo[0]), float(hi[1] - lo[1]), s.name))
    return out
