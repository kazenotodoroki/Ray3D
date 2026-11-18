"""Chemins spéculaires exacts source → écouteur jusqu'à l'ordre 4 (méthode des sources images).

Les séquences de parois candidates viennent :
- d'une énumération exhaustive tant que leur nombre reste raisonnable ;
- sinon d'un lancer de rayons depuis la source (les séquences de faces réellement visitées),
  puis chaque séquence est validée exactement par sources images.

Côté réfléchissant des faces : intérieur pour une pièce, extérieur pour un objet, les deux pour une
surface. Une source image n'est retenue que si la source (ou l'image précédente) est de ce côté.
"""
from __future__ import annotations

import math

import numpy as np

EPS = 1e-6
EXHAUSTIVE_LIMIT = 40000
CHUNK = 1500


def face_sides(geo):
    """-1 : réfléchit vers l'intérieur (pièce), +1 : vers l'extérieur (objet), 0 : deux faces."""
    m = {"Pièce": -1.0, "Objet": 1.0, "Surface": 0.0}
    return np.array([m.get(k, 0.0) for k in geo.fkind])


def _side_ok(d, side):
    """d = distance signée au plan (le long de la normale)."""
    return np.where(side < 0, d < -EPS, np.where(side > 0, d > EPS, np.abs(d) > EPS))


def _mirror(P, O, N):
    return P - 2 * ((P - O) * N).sum(-1)[..., None] * N


# --------------------------------------------------------------------------- séquences candidates
def _exhaustive(geo, S, sides, k_max):
    """Toutes les séquences valides (côté réfléchissant) jusqu'à l'ordre k_max, si le nombre le permet.
    Renvoie {k: (seq (n,k), images (n,k,3))} et l'ordre max atteint."""
    F = geo.F
    out = {}
    d = ((S[None] - geo.fO) * geo.fN).sum(1)
    ok = _side_ok(d, sides)
    seq = np.nonzero(ok)[0][:, None]
    img = _mirror(S[None], geo.fO[seq[:, 0]], geo.fN[seq[:, 0]])[:, None, :]
    out[1] = (seq, img)
    for k in range(2, k_max + 1):
        n = len(seq)
        if n == 0 or n * (F - 1) > EXHAUSTIVE_LIMIT:
            return out, k - 1
        last = img[:, -1, :]                                           # (n,3)
        dd = np.einsum("nfj,fj->nf", last[:, None, :] - geo.fO[None], geo.fN)
        okm = _side_ok(dd, sides[None, :]) & (np.arange(F)[None, :] != seq[:, -1][:, None])
        ii, ff = np.nonzero(okm)
        newimg = _mirror(last[ii], geo.fO[ff], geo.fN[ff])
        seq = np.concatenate([seq[ii], ff[:, None]], 1)
        img = np.concatenate([img[ii], newimg[:, None, :]], 1)
        out[k] = (seq, img)
    return out, k_max


def _ray_sequences(geo, S, k_min, k_max, n_rays):
    """Séquences de faces (longueur k_min..k_max) visitées par des rayons partant de S."""
    k = np.arange(n_rays) + 0.5
    z = 1 - 2 * k / n_rays
    r = np.sqrt(np.maximum(0, 1 - z * z))
    phi = k * math.pi * (3 - math.sqrt(5))
    D = np.column_stack([r * np.cos(phi), r * np.sin(phi), z])
    O = np.repeat(S[None], n_rays, 0)
    hist = np.full((n_rays, k_max), -1, int)
    alive = np.ones(n_rays, bool)
    for order in range(k_max):
        idx = np.nonzero(alive)[0]
        if len(idx) == 0:
            break
        for c0 in range(0, len(idx), CHUNK):
            sl = idx[c0:c0 + CHUNK]
            t, tri = geo.first_hit(O[sl], D[sl])
            hit = tri >= 0
            dead = sl[~hit]
            alive[dead] = False
            hs = sl[hit]
            f = geo.tf[tri[hit]]
            hist[hs, order] = f
            n = geo.N[tri[hit]]
            P = O[hs] + D[hs] * t[hit][:, None]
            d = D[hs]
            D[hs] = d - 2 * (d * n).sum(1)[:, None] * n
            O[hs] = P + D[hs] * 1e-5
    seqs = {}
    for kk in range(k_min, k_max + 1):
        h = hist[:, :kk]
        h = h[(h >= 0).all(1)]
        if len(h):
            seqs[kk] = np.unique(h, axis=0)
    return seqs


def _images_for(geo, S, seq, sides):
    """Images successives pour des séquences (n,k), avec contrôle du côté réfléchissant."""
    n, k = seq.shape
    img = np.empty((n, k, 3))
    ok = np.ones(n, bool)
    cur = np.repeat(S[None], n, 0)
    for j in range(k):
        f = seq[:, j]
        d = ((cur - geo.fO[f]) * geo.fN[f]).sum(1)
        ok &= _side_ok(d, sides[f])
        if j > 0:
            ok &= f != seq[:, j - 1]
        cur = _mirror(cur, geo.fO[f], geo.fN[f])
        img[:, j] = cur
    return seq[ok], img[ok]


# --------------------------------------------------------------------------- validation
def _in_faces(geo, P, faces):
    res = np.zeros(len(P), bool)
    for f in np.unique(faces):
        m = faces == f
        res[m] = geo.in_face(P[m], int(f))
    return res


def _segments_clear(geo, A, B, fa, fb):
    """Vrai si les segments A→B ne traversent aucune face (hors faces fa / fb, -1 = aucune)."""
    n = len(A)
    out = np.ones(n, bool)
    if geo.M == 0 or n == 0:
        return out
    V = B - A
    L = np.linalg.norm(V, axis=1)
    Dn = V / np.maximum(L, 1e-12)[:, None]
    for c0 in range(0, n, CHUNK):
        sl = slice(c0, c0 + CHUNK)
        T = geo.hit_matrix(A[sl], Dn[sl])
        excl = (geo.tf[None, :] == fa[sl][:, None]) | (geo.tf[None, :] == fb[sl][:, None])
        T = np.where(excl, np.inf, T)
        out[sl] = ~(T < (L[sl] - 1e-4)[:, None]).any(1)
    return out


@np.errstate(invalid="ignore", divide="ignore")
def _validate(geo, S, L, seq, img):
    """Chemins valides pour des séquences d'ordre k : points (n, k+2, 3)."""
    n, k = seq.shape
    if n == 0:
        return seq, np.zeros((0, k + 2, 3))
    pts = np.empty((n, k + 2, 3))
    pts[:, 0] = S
    pts[:, -1] = L
    ok = np.ones(n, bool)
    P = np.repeat(L[None], n, 0)
    for j in range(k - 1, -1, -1):
        f = seq[:, j]
        I = img[:, j]
        O, N = geo.fO[f], geo.fN[f]
        t = ((O - P) * N).sum(1) / ((I - P) * N).sum(1)
        ok &= (t > EPS) & (t < 1 - EPS)
        R = P + t[:, None] * (I - P)
        pts[:, j + 1] = R
        P = R
    idx = np.nonzero(ok)[0]
    for j in range(k):
        if len(idx) == 0:
            break
        inside = _in_faces(geo, pts[idx, j + 1], seq[idx, j])
        idx = idx[inside]
    for j in range(k + 1):                       # segments S→R1, R1→R2, …, Rk→L
        if len(idx) == 0:
            break
        fa = seq[idx, j - 1] if j > 0 else np.full(len(idx), -1)
        fb = seq[idx, j] if j < k else np.full(len(idx), -1)
        clear = _segments_clear(geo, pts[idx, j], pts[idx, j + 1], fa, fb)
        idx = idx[clear]
    return seq[idx], pts[idx]


def specular_paths(geo, S, L, max_order, n_rays=16000):
    """Liste de (faces, points) des chemins S → L d'ordre 1..max_order."""
    if geo.F == 0 or max_order < 1:
        return []
    S = np.asarray(S, float); L = np.asarray(L, float)
    sides = face_sides(geo)
    ex, k_ex = _exhaustive(geo, S, sides, max_order)
    cand = {k: ex[k] for k in ex}
    if k_ex < max_order:
        seqs = _ray_sequences(geo, S, k_ex + 1, max_order, n_rays)
        for k, sq in seqs.items():
            cand[k] = _images_for(geo, S, sq, sides)
    out = []
    for k in sorted(cand):
        seq, img = cand[k]
        vs, vp = _validate(geo, S, L, seq, img)
        for a, b in zip(vs, vp):
            out.append((list(map(int, a)), b))
    return out
