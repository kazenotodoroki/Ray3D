"""Plans de découpe d'un ensemble (bureau, meuble…), en PDF : une page par pièce.

Chaque forme est un prisme : un profil (esquisse) extrudé. On la ramène à une pièce de panneau dont
l'épaisseur est la plus petite des trois dimensions :
- cas A — l'épaisseur est l'extrusion (plateau, pied) : le contour de la pièce, coté sur chaque côté
  (rayon pour les arcs) et à l'encombrement, avec la vue de l'épaisseur en dessous ;
- cas B — l'épaisseur est dans le profil (tasseau, planche chanfreinée) : la face longueur × largeur
  avec les lignes de chanfrein, et la section cotée à côté.
Les pièces identiques sont regroupées (quantité). Le dessin est à la plus grande échelle possible.
"""
from __future__ import annotations

import math

import numpy as np
from PySide6 import QtGui
from PySide6.QtCore import Qt

from . import geometry as G
from .pdfdoc import Doc, Frame, fmt_len, INK, DIM_INK, LIGHT, ACCENT, SCALES

FILL = QtGui.QColor(0, 0, 0, 12)


# =========================================================================== pièces
def norm_profile(pts, arcs):
    """Profil en sens trigonométrique, coin bas-gauche à l'origine."""
    pts, arcs = G.ccw_with_arcs([list(map(float, p)) for p in pts], arcs)
    P = np.array(pts, float)
    out = G.expand_profile(list(P), arcs)
    lo = out.min(0) if len(out) else P.min(0)
    return [p - lo for p in P], list(arcs)


def rot90(pts, arcs):
    """Rotation de 90° (sens trigonométrique) ; les flèches d'arc ne changent pas."""
    return norm_profile([np.array([-p[1], p[0]]) for p in pts], arcs)


def extent(pts, arcs):
    out = G.expand_profile(list(pts), arcs)
    return out.max(0) - out.min(0)


class Piece:
    def __init__(self, ref, shapes):
        self.ref = ref
        self.shapes = shapes
        s = shapes[0]
        self.qty = len(shapes)
        self.names = ", ".join(dict.fromkeys(x.name for x in shapes))
        pts, arcs = norm_profile(s.profile, s.arcs)
        da, db = extent(pts, arcs)
        h = 0.0 if s.kind == "Surface" else max(float(s.height), 0.0)
        self.h = h
        if h <= min(da, db) + 1e-9:                               # cas A : épaisseur = extrusion
            self.case = "A"
            if db > da + 1e-9:
                pts, arcs = rot90(pts, arcs)
            self.pts, self.arcs = pts, arcs
            self.L, self.W = extent(pts, arcs)
            self.T = h
        else:                                                     # cas B : épaisseur dans le profil
            self.case = "B"
            if da < db:                       # épaisseur selon a : la section garde (a, b)
                sec_pts, sec_arcs = pts, arcs
            else:                             # épaisseur selon b : la section tourne (b → horizontal)
                sec_pts, sec_arcs = rot90(pts, arcs)
            self.pts, self.arcs = sec_pts, sec_arcs              # profil coté = section (w, v)
            T, W = extent(sec_pts, sec_arcs)
            self.L, self.W, self.T = h, W, T
        self.outline = G.expand_profile(list(self.pts), self.arcs)

    @property
    def face_outline(self):
        """Contour de la face principale (pour le plan de débit), coin bas-gauche à l'origine."""
        if self.case == "A":
            return self.outline
        return np.array([[0, 0], [self.L, 0], [self.L, self.W], [0, self.W]], float)

    def lines_v(self):
        """Cas B : lignes de chanfrein le long de la pièce (positions sur la largeur)."""
        vs = sorted({round(float(p[1]), 6) for p in self.outline})
        return [v for v in vs if 1e-6 < v < self.W - 1e-6]

    def lines_u(self):
        """Cas A : arêtes vues sur le chant (positions sur la longueur)."""
        us = sorted({round(float(p[0]), 6) for p in self.pts})
        return [u for u in us if 1e-6 < u < self.L - 1e-6]


def piece_key(s):
    pts, arcs = norm_profile(s.profile, s.arcs)
    P = tuple((round(float(a), 4), round(float(b), 4)) for a, b in pts)
    return (P, tuple(round(x, 4) for x in arcs), round(float(s.height), 4), s.kind == "Surface")


def make_pieces(shapes):
    groups = {}
    for s in shapes:
        groups.setdefault(piece_key(s), []).append(s)
    lst = sorted(groups.values(), key=lambda ss: -abs(G.poly_area(ss[0].outline())) * max(ss[0].height, 1e-3))
    return [Piece(f"P{i + 1}", ss) for i, ss in enumerate(lst)]


def vertex_info(pts, arcs):
    """Angles intérieurs (°) aux sommets (tangentes pour les arcs) et segments sortants."""
    n = len(pts)
    out = []
    for i in range(n):
        P, Q = pts[i], pts[(i + 1) % n]
        prv = pts[i - 1]
        s_in, s_out = arcs[i - 1], arcs[i]
        din = _tangent(prv, P, s_in, end=True)
        dout = _tangent(P, Q, s_out, end=False)
        turn = math.degrees(math.atan2(din[0] * dout[1] - din[1] * dout[0], din @ dout))
        inner = 180.0 - turn
        L = float(np.linalg.norm(Q - P))
        seg = dict(kind="arc" if abs(s_out) > 1e-9 else "line", chord=L,
                   length=G.arc_length(P, Q, s_out) if abs(s_out) > 1e-9 else L)
        if abs(s_out) > 1e-9:
            seg["R"] = G.arc_geometry(P, Q, s_out)[1]
        out.append(dict(P=P, inner=inner, din=din, dout=dout, straight=abs(s_in) < 1e-9 and abs(s_out) < 1e-9,
                        seg=seg))
    return out


def _tangent(A, B, s, end):
    d = np.asarray(B, float) - np.asarray(A, float)
    L = np.linalg.norm(d)
    if L < 1e-12:
        return np.array([1.0, 0.0])
    d = d / L
    if abs(s) < 1e-9:
        return d
    g = G.arc_geometry(A, B, s)
    C, R, a0, sweep = g
    a = a0 + (sweep if end else 0.0)
    t = np.array([-math.sin(a), math.cos(a)]) * (1 if sweep > 0 else -1)
    return t


# =========================================================================== dessin d'un profil coté
def _std_scale(fit_mm_per_m):
    need = 1000.0 / max(fit_mm_per_m, 1e-9)
    return next((s for s in SCALES if s >= need - 1e-9), math.ceil(need / 100) * 100)


def draw_profile(fr, pts, arcs, units, numbers=True, dims=True, overall=True, big=True, angles=True):
    """Profil fermé coté : longueur de chaque côté, rayons, angles ≠ 90°, encombrement."""
    doc = fr.d
    out = G.expand_profile(list(pts), arcs)
    fr.poly(out, 0, INK, fill=FILL)
    fr.poly(out, 0.5, INK)
    n = len(pts)
    info = vertex_info(pts, arcs)
    lo, hi = out.min(0), out.max(0)
    e = hi - lo
    C = out.mean(0)
    size = 8 if big else 7
    # côtés
    full_w = full_h = False
    for i in range(n):
        A, B = pts[i], pts[(i + 1) % n]
        sg = info[i]["seg"]
        L = sg["chord"]
        if L < 1e-9:
            continue
        d = (B - A) / L
        right = np.array([d[1], -d[0]])           # extérieur pour un profil trigonométrique
        if sg["kind"] == "arc":
            g = G.arc_geometry(A, B, arcs[i])
            Cc, R, a0, sweep = g
            am = a0 + sweep / 2
            Pm = Cc + R * np.array([math.cos(am), math.sin(am)])
            M = (A + B) / 2
            f = float(np.linalg.norm(Pm - M))                 # flèche
            # corde (tirets) cotée, flèche cotée du milieu de la corde au sommet de l'arc
            fr.seg(A, B, 0.15, DIM_INK, Qt.PenStyle.DashLine)
            fr.dim(A, B, 0.0, f"corde {fmt_len(L, units)}", size - 0.8, DIM_INK, False, ext=False)
            fr.seg(M, Pm, 0.15, ACCENT)
            for q_ in (fr.pt(*M), fr.pt(*Pm)):
                doc.circle(q_[0], q_[1], 0.45, 0.1, ACCENT, ACCENT)
            qm, qp = np.array(fr.pt(*M)), np.array(fr.pt(*Pm))
            t = (qm + qp) / 2
            dv = qp - qm
            nv = np.array([-dv[1], dv[0]]) / max(np.linalg.norm(dv), 1e-9)
            doc.text(t[0] + nv[0] * 2.5, t[1] + nv[1] * 2.5, f"f {fmt_len(f, units)}", size - 0.5, True, ACCENT,
                     "left" if nv[0] >= 0 else "right", valign="middle")
            # rayon : repère sur l'arc, au quart
            aq = a0 + sweep * 0.25
            Pq = Cc + R * np.array([math.cos(aq), math.sin(aq)])
            v = Pq - C
            v = v / max(np.linalg.norm(v), 1e-9)
            fr.leader(Pq, 8 * (1 if v[0] >= 0 else -1), -8 * (1 if v[1] >= 0 else -1),
                      f"R {fmt_len(R, units)}", size - 0.5, ACCENT, True)
            continue
        if not dims:
            continue
        if abs(d[1]) < 1e-6 and abs(L - e[0]) < 1e-6:
            full_w = True
        if abs(d[0]) < 1e-6 and abs(L - e[1]) < 1e-6:
            full_h = True
        # cote à l'extérieur du côté (dim : décalage positif = à gauche sur le papier → on prend -)
        fr.dim(A, B, -6.0, fmt_len(L, units), size, INK, True)
    # encombrement
    if overall:
        if not full_w:
            fr.dim((lo[0], lo[1]), (hi[0], lo[1]), -16, fmt_len(e[0], units), size, DIM_INK)
        if not full_h:
            fr.dim((lo[0], hi[1]), (lo[0], lo[1]), -16, fmt_len(e[1], units), size, DIM_INK)
    # angles non droits (entre deux côtés droits), placés après les cotes pour les éviter
    fr._segs = [(fr.pt(*out[k]), fr.pt(*out[(k + 1) % len(out)])) for k in range(len(out))]
    for k, it in enumerate(info if angles else []):
        if it["straight"] and min(abs(it["inner"] - 90), abs(it["inner"] - 180), abs(it["inner"] - 270)) > 0.05:
            lens = (info[k - 1]["seg"]["chord"], it["seg"]["chord"])
            _angle_mark(fr, it["P"], -it["din"], it["dout"], it["inner"], lens)
    if numbers:
        for i, p in enumerate(pts):
            q = fr.pt(*p)
            doc.circle(q[0], q[1], 0.55, 0.2, INK, "#ffffff")
            v = p - C
            v = v / max(np.linalg.norm(v), 1e-9)
            doc.text(q[0] + v[0] * 3.0, q[1] - v[1] * 3.0, str(i + 1), 6, True, ACCENT, "center", valign="middle")
    return info


def _hit_box(b, boxes):
    return any(b[0] < o[2] and b[2] > o[0] and b[1] < o[3] and b[3] > o[1] for o in boxes)


def _box_cuts(b, segs):
    """Le rectangle b (x0, y0, x1, y1) touche-t-il un des segments (papier) ?"""
    x0, y0, x1, y1 = b
    for (ax, ay), (bx, by) in segs:
        if max(ax, bx) < x0 or min(ax, bx) > x1 or max(ay, by) < y0 or min(ay, by) > y1:
            continue
        # échantillonne le segment
        for t in np.linspace(0, 1, 24):
            x, y = ax + (bx - ax) * t, ay + (by - ay) * t
            if x0 <= x <= x1 and y0 <= y <= y1:
                return True
    return False


def _angle_mark(fr, P, d1, d2, inner, lens):
    """Arc d'angle au sommet P entre les directions d1 et d2 (monde) et sa valeur, placée sans chevaucher
    les cotes, les autres angles ni le contour (à l'intérieur si possible, sinon à l'extérieur avec un
    trait de rappel)."""
    doc = fr.d
    q = np.array(fr.pt(*P))
    r = max(2.0, min(5.5, 0.38 * min(lens) * fr.s))
    a1 = math.degrees(math.atan2(d1[1], d1[0]))
    a2 = math.degrees(math.atan2(d2[1], d2[0]))
    span = (a1 - a2) % 360                     # de d2 vers d1, sens trigonométrique
    start = a2
    if abs(span - inner) > 1.0:
        start, span = a1, (a2 - a1) % 360
    boxes = fr.__dict__.setdefault("_boxes", [])
    segs = fr.__dict__.get("_segs", [])
    text = f"{inner:.1f}°"
    size = 6.5
    tw = doc.text_w(text, size, True)
    th = size * 0.3528 * 1.1
    mid = math.radians(start + span / 2)
    u = np.array([math.cos(mid), -math.sin(mid)])           # bissectrice, vers l'intérieur (papier)
    best = None
    for sgn in (1, -1):                                     # intérieur, puis extérieur
        for rr in np.arange(r + 3.0, r + 34.0, 1.5):
            c = q + u * sgn * (rr + (abs(u[0]) * tw / 2))
            b = (c[0] - tw / 2 - 0.5, c[1] - th / 2 - 0.4, c[0] + tw / 2 + 0.5, c[1] + th / 2 + 0.4)
            if not _hit_box(b, boxes) and not _box_cuts(b, segs):
                best = (c, b, rr, sgn)
                break
        if best:
            break
    if best is None:
        c = q + u * (r + 4)
        best = (c, (c[0] - tw / 2, c[1] - th / 2, c[0] + tw / 2, c[1] + th / 2), r + 4, 1)
    c, b, rr, sgn = best
    doc.arc(q[0], q[1], r, start, span, 0.2, ACCENT)
    # trait de rappel de l'arc à l'étiquette (lève toute ambiguïté entre sommets voisins)
    p0 = q + u * r if sgn > 0 else q
    d = c - p0
    L = float(np.linalg.norm(d))
    if L > 1e-6:
        dn = d / L
        # point d'entrée dans le cadre de l'étiquette
        k = min((tw / 2 + 0.6) / max(abs(dn[0]), 1e-6), (th / 2 + 0.5) / max(abs(dn[1]), 1e-6))
        p1 = c - dn * k
        if float(np.linalg.norm(p1 - p0)) > 0.6:
            doc.line(p0[0], p0[1], p1[0], p1[1], 0.15, ACCENT)
            doc.circle(p0[0], p0[1], 0.35, 0.1, ACCENT, ACCENT)
    boxes.append(b)
    doc.text(c[0], c[1], text, size, True, ACCENT, "center", valign="middle")


# =========================================================================== fiche pièce
def _fit_scale(fit_mm_per_m):
    """La plus grande échelle possible, arrondie au demi (1:6.5…) ; jamais plus grand que 1:1."""
    need = 1000.0 / max(fit_mm_per_m, 1e-9)
    return max(1.0, math.ceil(need * 2 - 1e-9) / 2)


MX, MY = 24.0, 14.0     # place des cotes autour d'une vue
DET_W = 72.0            # largeur de la section (cas B)


def piece_scale(p, w, h):
    if p.case == "A":
        gap = 26.0 if p.T > 0 else 0.0
        fit = min((w - 2 * MX) / max(p.L, 1e-6), (h - 2 * MY - gap) / max(p.W + p.T, 1e-6))
    else:
        fit = min((w - DET_W - 2 * MX - 6) / max(p.L, 1e-6), (h - 2 * MY) / max(p.W, 1e-6))
    return _fit_scale(fit)


def draw_card(doc, p, box, units):
    """Une pièce : vue(s) au plus grand, cotes sur les côtés."""
    x, y, w, h = box
    doc.text(x, y + 5, p.ref, 13, True, ACCENT)
    doc.text(x + 14, y + 5, p.names, 10, True)
    doc.text(x + w, y + 5, f"Qté {p.qty}  ·  {fmt_len(p.L, units)} × {fmt_len(p.W, units)} × "
                           f"{fmt_len(p.T, units)} {units}", 11, True, INK, "right")
    dx, dy, dw, dh = x, y + 9, w, h - 12
    scale = piece_scale(p, dw, dh)
    s = 1000.0 / scale
    if p.case == "A":
        gap = 26.0 if p.T > 0 else 0.0
        tot_h = (p.W + p.T) * s + gap
        cx = dx + dw / 2
        top = dy + (dh - tot_h) / 2
        fr = Frame(doc, (dx, dy, dw, dh), (0, 0), (p.L, p.W), scale=scale).place(cx, top + p.W * s / 2, (p.L / 2, p.W / 2))
        draw_profile(fr, p.pts, p.arcs, units, numbers=False)
        if p.T > 0:
            fe = Frame(doc, (dx, dy, dw, dh), (0, 0), (p.L, p.T), scale=scale).place(
                cx, top + p.W * s + gap + p.T * s / 2, (p.L / 2, p.T / 2))
            fe.poly([(0, 0), (p.L, 0), (p.L, p.T), (0, p.T)], 0, INK, fill=FILL)
            fe.poly([(0, 0), (p.L, 0), (p.L, p.T), (0, p.T)], 0.45, INK)
            fe.dim((p.L, 0), (p.L, p.T), -6, fmt_len(p.T, units), 8, INK, True)
            q = fe.pt(0, p.T / 2)
            doc.text(q[0] - 2, q[1], "épaisseur", 6.5, False, DIM_INK, "right", valign="middle")
    else:
        mw = dw - DET_W - 6
        cy = dy + dh / 2
        fm = Frame(doc, (dx, dy, mw, dh), (0, 0), (p.L, p.W), scale=scale).place(dx + mw / 2, cy, (p.L / 2, p.W / 2))
        R = [(0, 0), (p.L, 0), (p.L, p.W), (0, p.W)]
        fm.poly(R, 0, INK, fill=FILL)
        fm.poly(R, 0.5, INK)
        for v in p.lines_v():
            fm.seg((0, v), (p.L, v), 0.25, INK)
        fm.dim((0, 0), (p.L, 0), -7, fmt_len(p.L, units), 8, INK, True)
        fm.dim((0, p.W), (0, 0), -7, fmt_len(p.W, units), 8, INK, True)
        prev = 0.0
        if p.lines_v():
            for v in p.lines_v() + [p.W]:
                fm.dim((p.L, prev), (p.L, v), -6, fmt_len(v - prev, units), 7, INK, True)
                prev = v
        # section à sa propre échelle
        bx = (dx + dw - DET_W, dy, DET_W, dh)
        fit = min((DET_W - 2 * MX + 10) / max(p.T, 1e-6), (dh - 2 * MY - 8) / max(p.W, 1e-6))
        sd = _fit_scale(fit)
        fs = Frame(doc, bx, (0, 0), (p.T, p.W), scale=sd).place(bx[0] + DET_W / 2 + 4, cy + 3, (p.T / 2, p.W / 2))
        draw_profile(fs, p.pts, p.arcs, units, numbers=False)
        doc.text(bx[0] + DET_W / 2, dy + 4, f"Section (éch. 1:{sd:g})", 8, True, ACCENT, "center")
    doc.text(dx, y + h - 1, f"Éch. 1:{scale:g} · cotes en {units}", 7, False, LIGHT)


# =========================================================================== document
def write_cutlist(path, scene, asm, units="mm", *_, **__):
    """Une page par pièce (pièces identiques regroupées), dessin au plus grand, cotes sur les côtés."""
    shapes = scene.all_shapes_in(asm.id)
    pieces = make_pieces(shapes)
    doc = Doc(path, f"Plans de découpe · {asm.name}", f"cotes en {units}")
    M = doc.M
    for k, p in enumerate(pieces):
        if k:
            doc.new_page()
        draw_card(doc, p, (M, M + 5, doc.W - 2 * M, doc.H - M - 5 - 10), units)
    if not pieces:
        doc.text(M, 40, "Aucune pièce dans cet ensemble.", 10)
    doc.finish()
    return path
