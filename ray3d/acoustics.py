"""Moteur : directivité, lancer de rayons, réflexions (sources images), carte SPL,
délais et optimisation de line array."""
from __future__ import annotations

import math

import numpy as np

from . import geometry as G
from .model import Scene, Source, frame, speed_of_sound, object_poses, pose_points

A0 = {"Omni": 1.0, "Cardioïde": 0.5, "Supercardioïde": 0.37, "Hypercardioïde": 0.25}
CURRENT_FREQ = [1000.0]          # fréquence utilisée pour les directivités mesurées
_BCACHE: dict = {}


def sframe(s):
    return frame(s.az, s.el, getattr(s, "roll", 0.0))


# --------------------------------------------------------------------------- directivité mesurée
def balloon_arrays(b):
    """Tableaux numpy d'un ballon (mis en cache)."""
    key = id(b)
    c = _BCACHE.get(key)
    if c is None or c[0] is not b:
        f = np.asarray(b["freqs"], float)
        az = np.asarray(b["az"], float)
        el = np.asarray(b["el"], float)
        db = np.asarray(b["db"], float)
        c = (b, f, az, el, db)
        _BCACHE[key] = c
    return c[1:]


def balloon_db(b, az_deg, el_deg, freq):
    """Atténuation (dB) interpolée (bilinéaire) dans la bande la plus proche de freq."""
    f, az, el, db = balloon_arrays(b)
    k = int(np.argmin(np.abs(np.log(f / max(freq, 1.0)))))
    D = db[k]                                    # (nEl, nAz)
    a = ((np.asarray(az_deg) - az[0]) % 360.0) + az[0]
    ia = np.clip(np.searchsorted(az, a) - 1, 0, len(az) - 2)
    ie = np.clip(np.searchsorted(el, el_deg) - 1, 0, len(el) - 2)
    ta = np.clip((a - az[ia]) / (az[ia + 1] - az[ia]), 0, 1)
    te = np.clip((el_deg - el[ie]) / (el[ie + 1] - el[ie]), 0, 1)
    v00, v01 = D[ie, ia], D[ie, ia + 1]
    v10, v11 = D[ie + 1, ia], D[ie + 1, ia + 1]
    return (1 - te) * ((1 - ta) * v00 + ta * v01) + te * ((1 - ta) * v10 + ta * v11)


def _local_angles(s, d):
    f, l, u = sframe(s)
    x, y, z = d @ f, d @ l, d @ u
    return np.degrees(np.arctan2(y, x)), np.degrees(np.arcsin(np.clip(z, -1, 1)))


def _measured_edge(s, psi):
    key = (id(s.balloon), round(CURRENT_FREQ[0], 1), len(psi), float(psi[0]), float(psi[-1]))
    c = _BCACHE.get(("edge", key))
    if c is not None:
        return c
    th = np.radians(np.arange(0, 181, 1.0))
    T, P = np.meshgrid(th, psi, indexing="ij")              # (181, n)
    x, y, z = np.cos(T), np.sin(T) * np.cos(P), np.sin(T) * np.sin(P)
    az = np.degrees(np.arctan2(y, x)); el = np.degrees(np.arcsin(np.clip(z, -1, 1)))
    db = balloon_db(s.balloon, az, el, CURRENT_FREQ[0])
    below = db < -6.0
    idx = np.where(below.any(0), below.argmax(0), 180)
    res = np.radians(np.maximum(idx, 1).astype(float))
    _BCACHE[("edge", key)] = res
    return res
GOLD = math.pi * (3 - math.sqrt(5))
EPS = 1e-6


# --------------------------------------------------------------------------- directivité
def edge_angle(s, psi):
    """Demi-angle (rad) du contour -6 dB dans la direction azimutale psi
    (psi = 0 : bord gauche horizontal, pi/2 : bord haut)."""
    psi = np.asarray(psi, float)
    if s.pattern == "Mesuré" and getattr(s, "balloon", None):
        flat = np.atleast_1d(psi).ravel()
        return _measured_edge(s, flat).reshape(np.shape(psi))
    if s.pattern == "Pavillon":
        hh = math.radians(max(s.cov_h, 0.5) / 2)
        hv = math.radians(max(s.cov_v, 0.5) / 2)
        return np.minimum(1.0 / np.sqrt(np.cos(psi) ** 2 / hh ** 2 + np.sin(psi) ** 2 / hv ** 2), math.pi)
    a = A0.get(s.pattern, 1.0)
    th = math.pi if a >= 1 else math.acos((0.5 - a) / (1 - a))
    return np.full_like(psi, th)


def coverage_deg(s):
    h = math.degrees(float(edge_angle(s, 0.0))) * 2
    v = math.degrees(float(edge_angle(s, math.pi / 2))) * 2
    return min(h, 360), min(v, 360)


def directions(s, th, psi):
    f, l, u = sframe(s)
    th = np.asarray(th, float)[..., None]
    psi = np.asarray(psi, float)[..., None]
    return np.cos(th) * f + np.sin(th) * (np.cos(psi) * l + np.sin(psi) * u)


def gain(s, d):
    """Gain linéaire (amplitude) dans les directions unitaires d (N,3)."""
    if s.pattern == "Mesuré" and getattr(s, "balloon", None):
        az, el = _local_angles(s, d)
        return 10 ** (np.maximum(balloon_db(s.balloon, az, el, CURRENT_FREQ[0]), -40.0) / 20)
    f, l, u = sframe(s)
    ca = np.clip(d @ f, -1, 1)
    if s.pattern == "Pavillon":
        th = np.arccos(ca)
        psi = np.arctan2(d @ u, d @ l)
        db = -6.0 * (th / edge_angle(s, psi)) ** 2
        return 10 ** (np.maximum(db, -30.0) / 20)
    a = A0.get(s.pattern, 1.0)
    return np.maximum(np.abs(a + (1 - a) * ca), 0.01)


def sample_dirs(s, n: int):
    if n <= 1:
        return sframe(s)[0][None]
    k = np.arange(n) + 0.5
    r = np.sqrt(k / n)
    psi = k * GOLD
    th = np.minimum(r * edge_angle(s, psi) * 1.15, math.pi)
    return directions(s, th, psi)


# --------------------------------------------------------------------------- géométrie (triangles)
class Geometry:
    """Toutes les faces de la scène, triangulées. Les réflexions se font par face plane."""

    def __init__(self, scene: Scene, kinds=("Pièce", "Objet", "Surface")):
        T0, E1, E2, tri_face = [], [], [], []
        self.fO, self.fN, self.fA, self.fname, self.ftris, self.fkind, self.fshape = [], [], [], [], [], [], []
        for sh in scene.shapes:
            if sh.kind not in kinds:
                continue
            for f in sh.faces():
                fi = len(self.fO)
                ids = []
                for a, b, c in f.tris:
                    va, vb, vc = f.verts[a], f.verts[b], f.verts[c]
                    if np.linalg.norm(np.cross(vb - va, vc - va)) < 1e-10:
                        continue
                    ids.append(len(T0))
                    T0.append(va); E1.append(vb - va); E2.append(vc - va); tri_face.append(fi)
                if not ids:
                    continue
                self.fO.append(f.verts[0]); self.fN.append(f.normal)
                self.fA.append(min(max(sh.absorption, 0.0), 1.0))
                self.fname.append(f"{sh.name}·{f.name}")
                self.ftris.append(np.array(ids)); self.fkind.append(sh.kind); self.fshape.append(sh.id)
        self.M = len(T0)
        self.F = len(self.fO)
        if self.M:
            self.T0, self.E1, self.E2 = np.array(T0), np.array(E1), np.array(E2)
            self.tf = np.array(tri_face)
            self.fO, self.fN, self.fA = np.array(self.fO), np.array(self.fN), np.array(self.fA)
            self.A = self.fA[self.tf]
            self.N = self.fN[self.tf]

    # --- intersections rayon / triangles (Möller–Trumbore), (K, M)
    def hit_matrix(self, o, d, tmin=1e-4):
        o = np.atleast_2d(o); d = np.atleast_2d(d)
        if self.M == 0:
            return np.full((len(o), 0), np.inf)
        p = np.cross(d[:, None, :], self.E2[None])                      # K,M,3
        det = np.einsum("kmj,mj->km", p, self.E1)
        with np.errstate(divide="ignore", invalid="ignore"):
            inv = 1.0 / det
            tv = o[:, None, :] - self.T0[None]
            u = np.einsum("kmj,kmj->km", tv, p) * inv
            q = np.cross(tv, self.E1[None])
            v = np.einsum("kmj,kj->km", q, d) * inv
            t = np.einsum("kmj,mj->km", q, self.E2) * inv
            ok = (np.abs(det) > 1e-12) & (u >= -EPS) & (v >= -EPS) & (u + v <= 1 + EPS) & (t > tmin)
        return np.where(ok, t, np.inf)

    def first_hit(self, o, d):
        T = self.hit_matrix(o, d)
        k = T.shape[0]
        if self.M == 0:
            return np.full(k, np.inf), np.full(k, -1)
        idx = np.argmin(T, 1)
        t = T[np.arange(k), idx]
        idx = np.where(np.isfinite(t), idx, -1)
        return t, idx

    def blocked(self, a, b, exclude_faces=()):
        if self.M == 0:
            return False
        dv = b - a
        L = np.linalg.norm(dv)
        if L < 1e-6:
            return False
        T = self.hit_matrix(a[None], (dv / L)[None])[0]
        if exclude_faces:
            T[np.isin(self.tf, list(exclude_faces))] = np.inf
        return bool(np.any(T < L - 1e-4))

    def in_face(self, P, fi):
        """Le point P (…,3), supposé dans le plan de la face fi, est-il dans la face ?"""
        P = np.asarray(P, float)
        res = np.zeros(P.shape[:-1], bool)
        for t in self.ftris[fi]:
            e1, e2 = self.E1[t], self.E2[t]
            w = P - self.T0[t]
            d00, d01, d11 = e1 @ e1, e1 @ e2, e2 @ e2
            d20, d21 = w @ e1, w @ e2
            den = d00 * d11 - d01 * d01
            if abs(den) < 1e-14:
                continue
            v = (d11 * d20 - d01 * d21) / den
            ww = (d00 * d21 - d01 * d20) / den
            res |= (v >= -EPS) & (ww >= -EPS) & (v + ww <= 1 + EPS)
        return res

    def inside_parity(self, P, kind):
        """Points à l'intérieur des solides d'un type (test de parité, rayon vertical)."""
        sel = np.array([self.fkind[f] == kind for f in self.tf]) if self.M else np.zeros(0, bool)
        if not sel.any():
            return None
        d = np.array([0.0137, 0.0091, 1.0]); d /= np.linalg.norm(d)
        out = np.zeros(len(P), bool)
        sub = Geometry.__new__(Geometry)
        sub.M = int(sel.sum()); sub.T0, sub.E1, sub.E2 = self.T0[sel], self.E1[sel], self.E2[sel]
        for i in range(0, len(P), 4000):
            T = sub.hit_matrix(P[i:i + 4000], np.repeat(d[None], len(P[i:i + 4000]), 0), tmin=0.0)
            out[i:i + 4000] = (np.isfinite(T).sum(1) % 2) == 1
        return out


# --------------------------------------------------------------------------- rayons
def trace_rays(geo: Geometry, sources, nrays, max_order, max_len):
    if not sources:
        return None
    o, d, sid = [], [], []
    for k, s in enumerate(sources):
        dd = sample_dirs(s, nrays)
        o.append(np.repeat(s.pos[None], len(dd), 0)); d.append(dd); sid.append(np.full(len(dd), k))
    o, d, sid = np.vstack(o), np.vstack(d), np.concatenate(sid)
    rid = np.arange(len(o))
    E = np.ones(len(o)); rem = np.full(len(o), float(max_len))
    out = dict(p0=[], p1=[], order=[], energy=[], sid=[], rid=[])
    for order in range(max_order + 1):
        if len(o) == 0:
            break
        t, idx = geo.first_hit(o, d)
        hit = (idx >= 0) & (t < rem)
        tt = np.where(hit, t, rem)
        p1 = o + d * tt[:, None]
        out["p0"].append(o); out["p1"].append(p1); out["order"].append(np.full(len(o), order))
        out["energy"].append(E); out["sid"].append(sid); out["rid"].append(rid)
        if order == max_order or geo.M == 0:
            break
        n = geo.N[idx[hit]]
        dd = d[hit]
        d = dd - 2 * (dd * n).sum(1)[:, None] * n
        o = p1[hit]; E = E[hit] * (1 - geo.A[idx[hit]])
        rem = rem[hit] - tt[hit]; sid = sid[hit]; rid = rid[hit]
    res = {k: np.concatenate(v) for k, v in out.items()}
    res["sources"] = sources
    return res


def rays_reaching(R, targets):
    """Garde les rayons qui passent à moins de r d'une cible (écouteur), coupés au point le plus proche.
    targets : liste de (position, rayon). Renvoie un dict de même forme que trace_rays (+ 'hits')."""
    if R is None or not len(R["p0"]) or not targets:
        return R
    p0, p1 = R["p0"], R["p1"]
    d = p1 - p0
    dd = np.maximum((d * d).sum(1), 1e-12)
    best_t = np.full(len(p0), np.nan)
    best_q = np.zeros_like(p0)
    best_dist = np.full(len(p0), np.inf)
    for L, r in targets:
        L = np.asarray(L, float)
        t = np.clip(((L - p0) * d).sum(1) / dd, 0.0, 1.0)
        q = p0 + d * t[:, None]
        dist = np.linalg.norm(q - L, axis=1)
        m = (dist <= r) & (dist < best_dist)
        best_dist[m], best_t[m], best_q[m] = dist[m], t[m], q[m]
    hit = np.isfinite(best_dist)
    if not hit.any():
        out = {k: (v[:0] if isinstance(v, np.ndarray) else v) for k, v in R.items()}
        out["hits"] = 0
        return out
    rid, order = R["rid"], R["order"]
    first = {}
    for i in np.nonzero(hit)[0]:                    # premier passage de chaque rayon
        k = int(rid[i])
        if k not in first or order[i] < order[first[k]]:
            first[k] = i
    lim = np.full(int(rid.max()) + 1, -1)
    for k, i in first.items():
        lim[k] = order[i]
    keep = (lim[rid] >= 0) & (order <= lim[rid])
    out = {k: (v[keep] if isinstance(v, np.ndarray) and len(v) == len(p0) else v) for k, v in R.items()}
    out["p1"] = out["p1"].copy()
    idx = np.array(sorted(first.values()))
    pos = np.searchsorted(np.nonzero(keep)[0], idx)
    out["p1"][pos] = best_q[idx]
    out["hits"] = len(first)
    return out


def cone(s, geo: Geometry, rng: float, clip=True, npts=48):
    """Cône d'émission -6 dB : axe et anneau de bord (coupé aux surfaces si clip)."""
    pos = s.pos
    f, _, _ = sframe(s)
    ta, ia = geo.first_hit(pos[None], f[None])
    axis_t = min(float(ta[0]), rng) if clip else rng
    res = dict(axis=pos + f * axis_t, ring=None)
    psi = np.linspace(0, 2 * math.pi, npts, endpoint=False)
    th = edge_angle(s, psi)
    if th[0] >= math.pi - 1e-6:
        return res
    d = directions(s, th, psi)
    if clip:
        t, _ = geo.first_hit(np.repeat(pos[None], npts, 0), d)
        t = np.minimum(t, rng)
    else:
        t = np.full(npts, rng)
    res["ring"] = pos + d * t[:, None]
    return res


# --------------------------------------------------------------------------- réflexions (sources images)
def _mirror(P, O, N):
    return P - 2 * ((P - O) * N).sum(-1)[..., None] * N


def _line_plane(A, B, O, N):
    return ((O - A) * N).sum(-1) / ((B - A) * N).sum(-1)


@np.errstate(invalid="ignore", divide="ignore")
def reflection_paths(geo: Geometry, sources, L, max_order, c):
    """Son direct + chemins réfléchis (ordre 1..max_order, jusqu'à 4) pour chaque source."""
    from .paths import specular_paths
    out = []
    L = np.asarray(L, float)
    for s in sources:
        S = s.pos
        dv = L - S
        dlen = max(float(np.linalg.norm(dv)), 0.05)
        damp = float(gain(s, (dv / dlen)[None])[0]) / dlen
        out.append(dict(src=s, order=0, pts=[S, L], length=dlen, dt=0.0, rel=0.0,
                        level=s.level + 20 * math.log10(damp), blocked=geo.blocked(S, L), surf=[],
                        faces=[], d0=dv / dlen))
        if geo.F == 0 or max_order < 1:
            continue
        for surf, P in specular_paths(geo, S, L, min(int(max_order), 4)):
            seg = np.diff(P, axis=0)
            lens = np.linalg.norm(seg, axis=1)
            length = float(lens.sum())
            d0 = seg[0] / max(lens[0], 1e-12)
            amp = float(gain(s, d0[None])[0]) / length
            for q in surf:
                amp *= math.sqrt(max(1 - geo.fA[q], 0.0))
            out.append(dict(src=s, order=len(surf), pts=list(P), length=length,
                            dt=(length - dlen) / c * 1000, rel=20 * math.log10(max(amp, 1e-12) / damp),
                            level=s.level + 20 * math.log10(max(amp, 1e-12)), blocked=False,
                            surf=[geo.fname[q] for q in surf], faces=list(surf), d0=d0))
    return out


# --------------------------------------------------------------------------- SPL
BANDS = {"Cohérent": [0.0], "1/3 oct": list(np.linspace(-1 / 6, 1 / 6, 5)),
         "Octave": list(np.linspace(-0.5, 0.5, 9)), "Énergie": None}


def spl(scene: Scene, sources, pts, c):
    st = scene.settings
    if not sources or len(pts) == 0:
        return np.full(len(pts), -np.inf)
    pre = []
    for s in sources:
        v = pts - s.pos
        r = np.maximum(np.linalg.norm(v, axis=1), 0.1)
        A = 10 ** (s.level / 20) * gain(s, v / r[:, None]) / r
        tau = scene.delays.get(s.id, 0.0) / 1000 if st.apply_delays else 0.0
        pre.append((r, A.astype(np.float32), tau))
    offs = BANDS.get(st.band, [0.0])
    if offs is None:
        p2 = sum(A.astype(float) ** 2 for _, A, _ in pre)
    else:
        p2 = np.zeros(len(pts))
        for o in offs:
            f = st.freq * 2 ** o
            k = 2 * math.pi * f / c
            p = np.zeros(len(pts), np.complex64)
            for r, A, tau in pre:
                ph = (k * r + 2 * math.pi * f * tau).astype(np.float32)
                p += A * (np.cos(ph) - np.complex64(1j) * np.sin(ph))
            p2 += np.abs(p).astype(float) ** 2
        p2 /= len(offs)
    return 10 * np.log10(np.maximum(p2, 1e-12))


def auto_resolution(scene: Scene):
    st = scene.settings
    if st.resolution > 0:
        return st.resolution
    lo, hi = scene.bbox()
    span = float(max(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2], 1.0))
    return float(np.clip(span / 200.0, 0.025, 0.25))


def spl_maps(scene: Scene, sources, c):
    st = scene.settings
    res = auto_resolution(scene)
    maps = []
    for sh in scene.shapes:
        if not sh.audience:
            continue
        for f in sh.audience_faces():
            O, e1, e2 = G.face_basis(f)
            rel = f.verts - O
            a, b = rel @ e1, rel @ e2
            a0, a1, b0, b1 = a.min(), a.max(), b.min(), b.max()
            nu = int(np.clip((a1 - a0) / res, 2, 400))
            nv = int(np.clip((b1 - b0) / res, 2, 400))
            ga = a0 + (np.arange(nu) + 0.5) / nu * (a1 - a0)
            gb = b0 + (np.arange(nv) + 0.5) / nv * (b1 - b0)
            A_, B_ = np.meshgrid(ga, gb, indexing="ij")
            inside = G.points_in_poly(np.column_stack([A_.ravel(), B_.ravel()]), np.column_stack([a, b])).reshape(nu, nv)
            P = O + A_[..., None] * e1 + B_[..., None] * e2 + np.array([0, 0, st.ear])
            db = np.full((nu, nv), np.nan)
            if inside.any():
                db[inside] = spl(scene, sources, P[inside], c)
            Og = O + a0 * e1 + b0 * e2
            maps.append(dict(shape=sh, O=Og + np.array([0, 0, 0.01]), U=e1 * (a1 - a0), V=e2 * (b1 - b0),
                             nu=nu, nv=nv, db=db, P=P - np.array([0, 0, st.ear - 0.01])))
    return maps


def spl_section(scene: Scene, sources, c, geo: Geometry | None = None):
    st = scene.settings
    lo, hi = scene.bbox()
    res = auto_resolution(scene)
    nx = int(np.clip((hi[0] - lo[0]) / res, 2, 500))
    nz = int(np.clip((hi[2] - lo[2]) / res, 2, 300))
    xs = lo[0] + (np.arange(nx) + 0.5) / nx * (hi[0] - lo[0])
    zs = lo[2] + (np.arange(nz) + 0.5) / nz * (hi[2] - lo[2])
    X, Z = np.meshgrid(xs, zs, indexing="ij")
    P = np.stack([X, np.full_like(X, st.section_y), Z], -1).reshape(-1, 3)
    mask = np.ones(len(P), bool)
    if geo is not None:
        inroom = geo.inside_parity(P, "Pièce")
        if inroom is not None:
            mask &= inroom
        inobj = geo.inside_parity(P, "Objet")
        if inobj is not None:
            mask &= ~inobj
    db = np.full(len(P), np.nan)
    if mask.any():
        db[mask] = spl(scene, sources, P[mask], c)
    return dict(x0=lo[0], z0=lo[2], w=hi[0] - lo[0], h=hi[2] - lo[2], db=db.reshape(nx, nz))


# --------------------------------------------------------------------------- délais
def axis_point(s, geo: Geometry, default=15.0):
    f, _, _ = sframe(s)
    t, i = geo.first_hit(s.pos[None], f[None])
    t = float(t[0]) if i[0] >= 0 else default
    return s.pos + f * min(t, 300.0)


def compute_delays(scene: Scene, geo: Geometry):
    st = scene.settings
    c = speed_of_sound(st.temperature)
    centers = []
    for g in scene.groups:
        if g.main:
            ss = [s for s in scene.sources_in(g.id) if not s.mute]
            if ss:
                centers.append(np.mean([s.pos for s in ss], 0))
    lst = scene.listener(st.ref_mode)
    rows, delays = [], {}

    def ref(s):
        return lst.pos if lst else axis_point(s, geo)

    for g in scene.groups:
        srcs = scene.sources_in(g.id)
        if not srcs:
            continue
        if g.main or not centers:
            for s in srcs:
                delays[s.id] = s.delay_offset
                rows.append(dict(src=s, group=g, main=g.main, dm=None, ds=None,
                                 raw=0.0, delay=s.delay_offset, warn=False))
            continue
        if st.per_group_delay:
            act = [s for s in srcs if not s.mute] or srcs
            C = np.mean([s.pos for s in act], 0)
            P = lst.pos if lst else np.mean([ref(s) for s in act], 0)
            dm = min(float(np.linalg.norm(P - m)) for m in centers)
            ds = float(np.linalg.norm(P - C))
            raw = (dm - ds) / c * 1000 + st.haas
            for s in srcs:
                d = max(raw, 0.0) + s.delay_offset
                delays[s.id] = d
                rows.append(dict(src=s, group=g, main=False, dm=dm, ds=ds, raw=raw, delay=d, warn=raw < 0))
        else:
            for s in srcs:
                P = ref(s)
                dm = min(float(np.linalg.norm(P - m)) for m in centers)
                ds = float(np.linalg.norm(P - s.pos))
                raw = (dm - ds) / c * 1000 + st.haas
                d = max(raw, 0.0) + s.delay_offset
                delays[s.id] = d
                rows.append(dict(src=s, group=g, main=False, dm=dm, ds=ds, raw=raw, delay=d, warn=raw < 0))
    scene.delays = delays
    return rows


# --------------------------------------------------------------------------- line array
def optimize_array(arr, model, near, far, z_near, z_far, max_splay=10.0, step=0.5, weight=1.0):
    """Répartit les angles du fond (boîte haute) au premier rang (boîte basse).
    Densité de boîtes par degré ∝ distance**weight. Les splays sont bornés par la
    plage sans collision du modèle (arêtes d'accroche)."""
    n = max(1, int(arr.n))
    span = model.hinge_span() or 0.35
    zc = arr.z - n * span / 2
    ts = np.linspace(0, 1, 600)
    dist = near + ts * (far - near)
    zq = z_near + ts * (z_far - z_near)
    alpha = np.degrees(np.arctan2(zq - zc, dist))[::-1]
    r = np.hypot(zq - zc, dist)[::-1]
    dA = np.abs(np.diff(alpha))
    W = np.concatenate([[0], np.cumsum(0.5 * (r[1:] ** weight + r[:-1] ** weight) * dA)])
    targets = np.full(n, alpha[0]) if W[-1] <= 0 else np.interp(np.linspace(0, W[-1], n), W, alpha)
    targets = targets - model.aim_offset()
    lo, hi = model.splay_range(arr.orient)
    hi = min(hi, max_splay)
    lo = max(lo, 0.0) if hi >= 0 else lo
    top = round(float(targets[0]), 1)
    splays, cum = [], top
    stp = max(step, 0.01)
    for i in range(1, n):
        s = round((cum - targets[i]) / stp) * stp
        s = float(min(max(s, lo), hi))
        splays.append(round(s, 2))
        cum -= s
    arr.top_angle, arr.splays = top, splays
    return array_report(arr, model, near, far, z_near, z_far)


def array_report(arr, model, near, far, z_near, z_far):
    fh = np.array([math.cos(math.radians(arr.az)), math.sin(math.radians(arr.az)), 0.0])
    k = (z_far - z_near) / (far - near) if far != near else 0.0
    lo, hi = model.splay_range(arr.orient)
    rows = []
    splays = arr.norm_splays()
    els = model.elements or []
    for i, (P, M) in enumerate(object_poses(arr, model)):
        if els:
            c = pose_points(P, M, [[e.f, e.l, e.u] for e in els]).mean(0)
            d = np.mean([M @ frame(e.az, e.el)[0] for e in els], 0)
        else:
            c, d = P, M[:, 0]
        d = d / max(np.linalg.norm(d), 1e-9)
        aim = math.degrees(math.asin(max(-1.0, min(1.0, d[2]))))
        pan = math.degrees(math.atan2(d[1], d[0]))
        h0 = float((c - arr.pos) @ fh)
        pz = float(c[2])
        t_ = math.radians(aim)
        den = math.sin(t_) - k * math.cos(t_)
        hit = None
        if arr.orient == "Verticale" and abs(den) > 1e-9:
            t = (z_near + k * (h0 - near) - pz) / den
            if t > 0:
                hit = h0 + math.cos(t_) * t
        sp = splays[i - 1] if i else None
        rows.append(dict(i=i + 1, el=aim, pan=pan, splay=sp, hit=hit,
                         collision=sp is not None and (sp < lo - 1e-6 or sp > hi + 1e-6)))
    return rows


def coupling_freq(spacing, c):
    return c / (2 * spacing) if spacing > 0 else float("inf")


def row_spacing(element, dist, overlap="-6 dB"):
    """Espacement idéal d'une rangée : les contours se rejoignent à la distance D."""
    hh = math.radians(element.cov_h / 2)
    if element.pattern != "Pavillon":
        a = A0.get(element.pattern, 1.0)
        hh = math.pi / 2 if a >= 1 else math.acos((0.5 - a) / (1 - a))
    if overlap == "-3 dB":
        hh *= math.sqrt(0.5)
    hh = min(hh, math.radians(89))
    return 2 * dist * math.tan(hh)
