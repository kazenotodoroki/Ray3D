"""Outils géométriques : polygones 2D, triangulation, esquisses extrudées."""
from __future__ import annotations

import math

import numpy as np

EX = np.array([1.0, 0.0, 0.0])
EY = np.array([0.0, 1.0, 0.0])
EZ = np.array([0.0, 0.0, 1.0])

# plan d'esquisse -> (axe a, axe b, direction d'extrusion)
PLANES = {
    "XY": (EX, EY, EZ),    # vue de dessus, extrusion vers le haut
    "XZ": (EX, EZ, EY),    # profil de côté, extrusion en largeur
    "YZ": (EY, EZ, EX),    # vue de face, extrusion en profondeur
}


# --------------------------------------------------------------------------- polygones 2D
def clean_poly(p, eps=1e-6):
    p = [np.asarray(q, float) for q in p]
    out = []
    for q in p:
        if not out or np.linalg.norm(q - out[-1]) > eps:
            out.append(q)
    if len(out) > 1 and np.linalg.norm(out[0] - out[-1]) < eps:
        out.pop()
    return np.array(out) if out else np.zeros((0, 2))


def poly_area(p):
    p = np.asarray(p, float)
    if len(p) < 3:
        return 0.0
    x, y = p[:, 0], p[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def ccw(p):
    p = clean_poly(p)
    return p if poly_area(p) >= 0 else p[::-1].copy()


def _cross2(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _in_tri(p, a, b, c):
    d1 = _cross2(b - a, p - a)
    d2 = _cross2(c - b, p - b)
    d3 = _cross2(a - c, p - c)
    return d1 > 1e-12 and d2 > 1e-12 and d3 > 1e-12


def triangulate(p):
    """Triangulation par oreilles d'un polygone simple (CCW)."""
    p = np.asarray(p, float)
    n = len(p)
    if n < 3:
        return []
    idx = list(range(n))
    tris = []
    guard = 0
    while len(idx) > 3 and guard < 10000:
        guard += 1
        found = False
        m = len(idx)
        for k in range(m):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % m]
            a, b, c = p[i0], p[i1], p[i2]
            if _cross2(b - a, c - b) <= 1e-12:
                continue
            if any(_in_tri(p[j], a, b, c) for j in idx if j not in (i0, i1, i2)):
                continue
            tris.append((i0, i1, i2))
            idx.pop(k)
            found = True
            break
        if not found:   # polygone dégénéré : éventail
            for k in range(1, len(idx) - 1):
                tris.append((idx[0], idx[k], idx[k + 1]))
            return tris
    tris.append(tuple(idx))
    return tris


def points_in_poly(pts, poly):
    """Test pair/impair vectorisé. pts (N,2), poly (M,2)."""
    pts = np.asarray(pts, float)
    poly = np.asarray(poly, float)
    x, y = pts[:, 0][:, None], pts[:, 1][:, None]
    x1, y1 = poly[:, 0][None], poly[:, 1][None]
    x2, y2 = np.roll(poly[:, 0], -1)[None], np.roll(poly[:, 1], -1)[None]
    with np.errstate(divide="ignore", invalid="ignore"):
        cond = ((y1 > y) != (y2 > y)) & (x < (x2 - x1) * (y - y1) / (y2 - y1) + x1)
    return (np.sum(cond, axis=1) % 2) == 1


def hull2d(pts):
    pts = sorted(set(map(tuple, np.round(np.asarray(pts, float), 6))))
    if len(pts) < 3:
        return np.array(pts)

    def cr(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, up = [], []
    for q in pts:
        while len(lo) >= 2 and cr(lo[-2], lo[-1], q) <= 0:
            lo.pop()
        lo.append(q)
    for q in reversed(pts):
        while len(up) >= 2 and cr(up[-2], up[-1], q) <= 0:
            up.pop()
        up.append(q)
    return np.array(lo[:-1] + up[:-1])


def clip_area(subject, clip):
    """Aire de l'intersection subject ∩ clip (clip convexe CCW) — Sutherland-Hodgman."""
    out = [np.asarray(q, float) for q in subject]
    clip = np.asarray(clip, float)
    for i in range(len(clip)):
        a, b = clip[i], clip[(i + 1) % len(clip)]
        inp, out = out, []
        if not inp:
            break

        def inside(q):
            return _cross2(b - a, q - a) >= -1e-12

        def inter(p1, p2):
            d1, d2 = _cross2(b - a, p1 - a), _cross2(b - a, p2 - a)
            t = d1 / (d1 - d2)
            return p1 + t * (p2 - p1)
        s = inp[-1]
        for e in inp:
            if inside(e):
                if not inside(s):
                    out.append(inter(s, e))
                out.append(e)
            elif inside(s):
                out.append(inter(s, e))
            s = e
    return abs(poly_area(np.array(out))) if len(out) >= 3 else 0.0


# --------------------------------------------------------------------------- 3D
def rot_z(deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])


def rot_tilt(deg):
    """Rotation autour de Y qui fait monter l'extrémité +X."""
    a = math.radians(-deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


class Face:
    """Face plane : polygone 3D, normale extérieure, triangles (indices locaux)."""
    __slots__ = ("name", "verts", "normal", "tris")

    def __init__(self, name, verts, normal, tris):
        self.name = name
        self.verts = np.asarray(verts, float)
        self.normal = np.asarray(normal, float)
        self.tris = tris

    def transformed(self, M, t):
        return Face(self.name, self.verts @ M.T + t, M @ self.normal, self.tris)


def extrude_faces(profile, a_axis, b_axis, e_axis, height, symmetric, names=None):
    """Prisme : esquisse 2D (CCW) dans le plan (a, b) extrudée selon e.
    Si height == 0 : une seule face plane."""
    p = ccw(profile)
    if len(p) < 3:
        return []
    names = names or {}
    tris = triangulate(p)
    base = p[:, 0:1] * a_axis + p[:, 1:2] * b_axis
    n0 = np.cross(a_axis, b_axis)
    if height <= 1e-9:
        return [Face(names.get("cap", "surface"), base, n0, tris)]
    off = -0.5 * height if symmetric else 0.0
    e = e_axis * height
    b0 = base + e_axis * off
    b1 = b0 + e
    s = 1.0 if n0 @ e_axis > 0 else -1.0
    faces = [Face(names.get("cap0", "base"), b0[::-1], -s * n0, [(len(p) - 1 - i, len(p) - 1 - j, len(p) - 1 - k) for i, j, k in tris]),
             Face(names.get("cap1", "dessus"), b1, s * n0, tris)]
    side = names.get("side", "face")
    for i in range(len(p)):
        j = (i + 1) % len(p)
        d = base[j] - base[i]
        nrm = np.cross(d, n0)
        ln = np.linalg.norm(nrm)
        if ln < 1e-12:
            continue
        faces.append(Face(f"{side} {i + 1}", np.array([b0[i], b0[j], b1[j], b1[i]]), nrm / ln,
                          [(0, 1, 2), (0, 2, 3)]))
    return faces


def faces_edges(faces):
    """Segments (2N,3) des contours de faces."""
    segs = []
    for f in faces:
        v = f.verts
        for i in range(len(v)):
            segs.append(v[i]); segs.append(v[(i + 1) % len(v)])
    return np.array(segs) if segs else np.zeros((0, 3))


def faces_mesh(faces):
    V, F = [], []
    for f in faces:
        k = sum(len(x) for x in V)
        V.append(f.verts)
        F += [(k + a, k + b, k + c) for a, b, c in f.tris]
    if not V:
        return np.zeros((0, 3)), np.zeros((0, 3), int)
    return np.vstack(V), np.array(F, int)


def face_basis(f: Face):
    e1 = f.verts[1] - f.verts[0]
    e1 /= max(np.linalg.norm(e1), 1e-12)
    e2 = np.cross(f.normal, e1)
    e2 /= max(np.linalg.norm(e2), 1e-12)
    return f.verts[0], e1, e2
