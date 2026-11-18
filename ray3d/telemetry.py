"""Télémètre : positions 3D par trilatération (distances depuis trois repères A, B, C).

Même méthode que l'app Régie :
- repère au sol A, B, C (bien écartés, non alignés) dont on mesure les trois côtés ;
- chaque point se calcule à partir de sa distance à A, B et C ; la hauteur sort de la trilatération,
  ou d'une hauteur connue saisie (mètre ruban) pour les points bas et loin des repères.

Deux façons de placer le repère dans la scène :
- « libre » : A est posé à une position donnée et A→B suit une direction donnée (azimut) ;
- « scène » : A, B, C sont des points connus de la scène (angles de la pièce…). Les côtés sont alors
  calculés, et les points mesurés tombent directement au bon endroit (triangulation dans la salle).

Les points servent ensuite à créer une pièce (angles au sol / au plafond), un objet (contour d'un
groupe de points) ou à placer une enceinte / un écouteur (orientation vers un autre point).
"""
from __future__ import annotations

import math
import uuid

import numpy as np

from .model import Shape, Speaker, Listener

SIG_D = 0.01            # incertitude supposée par distance mesurée (m)
TYPES = {
    "sol": "Angle de pièce (sol)",
    "plafond": "Angle de pièce (plafond)",
    "objet": "Point d'objet",
    "hp": "Enceinte",
    "ecoute": "Écoute / micro",
    "autre": "Autre",
}
TYPE_COLORS = {"sol": "#7fd1ff", "plafond": "#b49cff", "objet": "#cfd6df", "hp": "#e9a23b",
               "ecoute": "#6aa6e6", "autre": "#9aa3ad"}


def new_id():
    return uuid.uuid4().hex[:10]


def default_telemetry():
    return dict(ref=dict(mode="libre", AB=None, AC=None, BC=None, h0=0.0, flip=False,
                         ax=0.0, ay=0.0, az=0.0, rot=0.0,
                         A=[0.0, 0.0, 0.0], B=[1.0, 0.0, 0.0], C=[0.0, 1.0, 0.0]),
                points=[], ver=0)


def sanitize(t):
    d = default_telemetry()
    if isinstance(t, dict):
        r = t.get("ref") or {}
        d["ref"].update({k: v for k, v in r.items() if k in d["ref"]})
        d["points"] = [p for p in (t.get("points") or []) if isinstance(p, dict) and p.get("id")]
        d["ver"] = int(t.get("ver", 0) or 0)
    return d


def num(v):
    try:
        v = float(str(v).replace(",", "."))
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- géométrie (comme Régie)
def ref_frame(AB, AC, BC, flip):
    """A à l'origine, B sur +x, C dans le plan z = 0 (côté +y, ou −y si flip)."""
    if not (AB and AC and BC and AB > 0 and AC > 0 and BC > 0):
        return None
    i = (AC * AC - BC * BC + AB * AB) / (2 * AB)
    j2 = AC * AC - i * i
    if not j2 > 1e-6:
        return None
    j = math.sqrt(j2) * (-1 if flip else 1)
    return dict(d=AB, i=i, j=j)


def trilat(R, r1, r2, r3, below=False):
    x = (r1 * r1 - r2 * r2 + R["d"] ** 2) / (2 * R["d"])
    y = (r1 * r1 - r3 * r3 + R["i"] ** 2 + R["j"] ** 2 - 2 * R["i"] * x) / (2 * R["j"])
    z2 = r1 * r1 - x * x - y * y
    return np.array([x, y, math.sqrt(max(0.0, z2)) * (-1 if below else 1)]), z2


def z_sigma(R, r, below, s=SIG_D):
    """Incertitude sur la hauteur pour une erreur s sur chaque distance."""
    b, z2 = trilat(R, *r, below)
    if z2 <= 1e-6:
        return math.inf
    acc = 0.0
    for k in range(3):
        q = list(r)
        q[k] += 1e-4
        t, _ = trilat(R, *q, below)
        acc += ((t[2] - b[2]) / 1e-4) ** 2
    return math.sqrt(acc) * s


def tri_angles(a, b, c):
    """Angles (°) opposés aux côtés a, b, c et surface, ou None."""
    if not (a and b and c) or a + b <= c or a + c <= b or b + c <= a:
        return None
    al = math.acos(max(-1, min(1, (b * b + c * c - a * a) / (2 * b * c))))
    be = math.acos(max(-1, min(1, (a * a + c * c - b * b) / (2 * a * c))))
    s = (a + b + c) / 2
    S = math.sqrt(max(0.0, s * (s - a) * (s - b) * (s - c)))
    return dict(al=math.degrees(al), be=math.degrees(be), ga=180 - math.degrees(al) - math.degrees(be), S=S)


class Frame:
    """Repère de mesure → monde : P = O + ex·x + ey·y + ez·z."""

    def __init__(self, tel):
        r = tel["ref"]
        self.mode = r.get("mode", "libre")
        self.ok = False
        self.warn = ""
        if self.mode == "scene":
            A, B, C = (np.asarray(r.get(k) or [0, 0, 0], float) for k in "ABC")
            AB = float(np.linalg.norm(B - A))
            n = np.cross(B - A, C - A)
            if AB < 1e-6 or np.linalg.norm(n) < 1e-9:
                self.warn = "A, B et C ne doivent pas être alignés."
                self.R = None
                return
            ex = (B - A) / AB
            n = n / np.linalg.norm(n)
            if n[2] < 0:
                n = -n
            ey = np.cross(n, ex)
            self.O, self.ex, self.ey, self.ez = A, ex, ey, n
            self.h0 = 0.0
            self.ground = 0.0
            self.sides = (AB, float(np.linalg.norm(C - A)), float(np.linalg.norm(C - B)))
            self.R = dict(d=AB, i=float((C - A) @ ex), j=float((C - A) @ ey))
            if abs(self.R["j"]) < 1e-3:
                self.R = None
                self.warn = "A, B et C sont presque alignés."
                return
        else:
            AB, AC, BC = num(r.get("AB")), num(r.get("AC")), num(r.get("BC"))
            self.sides = (AB, AC, BC)
            self.R = ref_frame(AB, AC, BC, bool(r.get("flip")))
            if self.R is None:
                if AB and AC and BC:
                    self.warn = "Ces trois longueurs ne forment pas un triangle : vérifiez les mesures."
                return
            a = math.radians(num(r.get("rot")) or 0.0)
            self.h0 = num(r.get("h0")) or 0.0
            self.ground = num(r.get("az")) or 0.0
            self.ex = np.array([math.cos(a), math.sin(a), 0.0])
            self.ez = np.array([0.0, 0.0, 1.0])
            self.ey = np.cross(self.ez, self.ex)
            self.O = np.array([num(r.get("ax")) or 0.0, num(r.get("ay")) or 0.0, self.ground + self.h0])
        t = tri_angles(self.sides[2], self.sides[1], self.sides[0])
        if t and min(t["al"], t["be"], t["ga"]) < 20:
            self.warn = "Triangle très aplati : les positions seront imprécises. Écartez davantage les repères."
        self.ok = True

    def world(self, p):
        p = np.asarray(p, float)
        return self.O + self.ex * p[0] + self.ey * p[1] + self.ez * p[2]

    def refs(self):
        """Positions monde de A, B, C."""
        if not self.ok:
            return {}
        R = self.R
        return dict(A=self.world([0, 0, 0]), B=self.world([R["d"], 0, 0]), C=self.world([R["i"], R["j"], 0]))


def solve(tel):
    """Points calculés : liste de dict (id, name, type, group, aim, ok, P, sig, z2, warn)."""
    fr = Frame(tel)
    out = []
    for q in tel["points"]:
        d = [num(q.get(k)) for k in ("dA", "dB", "dC")]
        item = dict(id=q["id"], name=q.get("name", ""), type=q.get("type", "autre"), group=q.get("group", ""),
                    aim=q.get("aim") or "", ok=False, P=None, sig=math.inf, z2=0.0, warn="")
        if not fr.ok:
            item["warn"] = "repère manquant"
        elif not all(x and x > 0 for x in d):
            item["warn"] = "distances incomplètes"
        else:
            p, z2 = trilat(fr.R, *d, bool(q.get("below")))
            hk = num(q.get("hk"))
            P = fr.world(p)
            if hk is not None:
                P[2] = (fr.ground + hk) if fr.mode == "libre" else hk
                sig = 0.0
            else:
                sig = z_sigma(fr.R, d, bool(q.get("below")))
            item.update(ok=True, P=P, sig=sig, z2=z2)
            if hk is None and z2 < -0.09:
                item["warn"] = f"distances incohérentes (écart ≈ {math.sqrt(-z2):.2f} m)"
            elif hk is None and z2 <= 1e-4:
                item["warn"] = "au niveau des repères : hauteur imprécise"
        out.append(item)
    return fr, out


def precision_text(sig):
    if sig == 0:
        return "hauteur saisie"
    if not math.isfinite(sig):
        return "imprécis"
    return f"± {max(1, round(sig * 100))} cm" if sig < 0.995 else f"± {sig:.1f} m"


# --------------------------------------------------------------------------- points de la scène (repère « scène »)
def scene_points(scene):
    """Points remarquables : angles des pièces (sol et plafond), écouteurs, enceintes."""
    out = []
    for sh in scene.shapes:
        if sh.kind != "Pièce":
            continue
        faces = {f.name: f for f in sh.faces()}
        for key, lab in (("sol", "sol"), ("plafond", "plafond")):
            f = faces.get(key)
            if f is None:
                continue
            for i, v in enumerate(f.verts):
                out.append((f"{sh.name} · angle {i + 1} ({lab})", np.asarray(v, float)))
    for l in scene.listeners:
        out.append((f"Écoute « {l.name} »", l.pos))
    for o in scene.objects:
        if hasattr(o, "pos"):
            out.append((f"HP « {o.name} »", o.pos))
    return out


# --------------------------------------------------------------------------- construction
def _ordered(P2):
    """Ordre des points autour de leur centre (contour sans croisement pour un polygone convexe ou étoilé)."""
    c = P2.mean(0)
    ang = np.arctan2(P2[:, 1] - c[1], P2[:, 0] - c[0])
    return np.argsort(ang)


def _profile(P):
    P2 = np.asarray(P, float)[:, :2]
    idx = _ordered(P2)
    P2 = P2[idx]
    o = P2.min(0)
    prof = [[round(float(x - o[0]), 4) + 0.0, round(float(y - o[1]), 4) + 0.0] for x, y in P2]
    return prof, o


def build_room(sol, plafond=(), height=0.0, name="Pièce (télémètre)", absorption=0.15):
    """Pièce à partir des angles au sol (≥ 3) ; hauteur = plafond mesuré, ou saisie, ou 2.50 m."""
    if len(sol) < 3:
        raise ValueError("Il faut au moins 3 angles au sol.")
    P = np.array(sol, float)
    z0 = float(P[:, 2].mean())
    if height and height > 0:
        H = float(height)
    elif len(plafond):
        H = float(np.mean(np.asarray(plafond, float)[:, 2])) - z0
    else:
        H = 2.5
    if H <= 0.1:
        raise ValueError("Hauteur de pièce invalide : vérifiez les angles au plafond ou saisissez une hauteur.")
    prof, o = _profile(P)
    return Shape(name, "Pièce", prof, "XY", round(H, 4), x=round(float(o[0]), 4) + 0.0, y=round(float(o[1]), 4) + 0.0, z=round(z0, 4),
                 absorption=absorption)


def build_object(pts, height=0.0, top=True, ground=0.0, name="Objet (télémètre)", absorption=0.1):
    """Objet extrudé à partir du contour d'un groupe de points (≥ 3).

    height > 0 : épaisseur donnée, vers le bas depuis les points (top=True) ou vers le haut.
    height = 0 : automatique — de la hauteur basse à la hauteur haute des points s'ils sont
                 à des hauteurs différentes, sinon du sol (ground) jusqu'aux points.
    """
    if len(pts) < 3:
        raise ValueError("Il faut au moins 3 points pour un objet.")
    P = np.array(pts, float)
    zmin, zmax = float(P[:, 2].min()), float(P[:, 2].max())
    if height and height > 0:
        H = float(height)
        base = (zmax - H) if top else zmin
    elif zmax - zmin > 0.05:
        base, H = zmin, zmax - zmin
    else:
        base, H = float(ground), max(zmax - float(ground), 0.02)
    prof, o = _profile(P)
    return Shape(name, "Objet", prof, "XY", round(H, 4), x=round(float(o[0]), 4) + 0.0, y=round(float(o[1]), 4) + 0.0, z=round(base, 4),
                 absorption=absorption)


def aim_angles(P, Q):
    d = np.asarray(Q, float) - np.asarray(P, float)
    h = math.hypot(d[0], d[1])
    if h < 1e-9 and abs(d[2]) < 1e-9:
        return None
    return math.degrees(math.atan2(d[1], d[0])), math.degrees(math.atan2(d[2], h))


def relation(P, Q, c=343.0):
    d = np.asarray(Q, float) - np.asarray(P, float)
    L = float(np.linalg.norm(d))
    Lh = math.hypot(d[0], d[1])
    return dict(L=L, Lh=Lh, dz=float(d[2]), site=math.degrees(math.atan2(d[2], Lh)),
                az=math.degrees(math.atan2(d[1], d[0])) % 360, t=L / c * 1000)


def off_axis(P, X, Q):
    """Angle entre l'axe P→X et la ligne P→Q : (total, horizontal, vertical) en degrés, ou None."""
    a = np.asarray(X, float) - np.asarray(P, float)
    b = np.asarray(Q, float) - np.asarray(P, float)
    la, lb = np.linalg.norm(a), np.linalg.norm(b)
    if la < 1e-9 or lb < 1e-9:
        return None
    tot = math.degrees(math.acos(max(-1.0, min(1.0, float(a @ b) / (la * lb)))))
    h = math.degrees(math.atan2(b[1], b[0]) - math.atan2(a[1], a[0]))
    h = (h + 540) % 360 - 180
    v = math.degrees(math.atan2(b[2], math.hypot(b[0], b[1])) - math.atan2(a[2], math.hypot(a[0], a[1])))
    return tot, h, v


def relations(pts, pid, c=343.0, types=("hp", "ecoute")):
    """Depuis le point pid : distance, délai, site, azimut, hors axe du point et incidence sur chaque
    autre enceinte / écoute (selon leurs orientations « orienté vers »)."""
    by = {p["id"]: p for p in pts if p["ok"]}
    X = by.get(pid)
    if X is None:
        return []
    aimX = by.get(X.get("aim") or "")
    out = []
    for Y in pts:
        if Y["id"] == pid or not Y["ok"] or Y["type"] not in types:
            continue
        r = relation(X["P"], Y["P"], c)
        aimY = by.get(Y.get("aim") or "")
        r.update(id=Y["id"], name=Y["name"], type=Y["type"],
                 off=off_axis(X["P"], aimX["P"], Y["P"]) if aimX else None,
                 inc=off_axis(Y["P"], aimY["P"], X["P"]) if aimY else None)
        out.append(r)
    out.sort(key=lambda r: r["L"])
    return out


def ground_of(scene):
    """Altitude du sol : plus bas sol de pièce, sinon 0."""
    zs = []
    for sh in scene.shapes:
        if sh.kind == "Pièce":
            for f in sh.faces():
                if f.name == "sol":
                    zs.append(float(f.verts[:, 2].min()))
    return min(zs) if zs else 0.0


def state_json(scene, extra=None):
    """État complet pour le téléphone (valeurs saisies + positions calculées)."""
    tel = scene.telemetry
    fr, pts = solve(tel)
    refs = {k: [round(float(x), 4) for x in v] for k, v in fr.refs().items()}
    out = dict(ver=tel.get("ver", 0), ref=tel["ref"], points=tel["points"], refs=refs,
               frame=dict(ok=fr.ok, warn=fr.warn, sides=[None if s is None else round(s, 4) for s in fr.sides]
                          if hasattr(fr, "sides") else [None] * 3),
               solved=[dict(id=p["id"], ok=p["ok"], warn=p["warn"], prec=precision_text(p["sig"]) if p["ok"] else "",
                            P=None if p["P"] is None else [round(float(x), 4) for x in p["P"]]) for p in pts],
               types=TYPES, groups=sorted({q.get("group", "") for q in tel["points"] if q.get("group")}))
    if extra:
        out.update(extra)
    return out


def update_ref(tel, data):
    r = tel["ref"]
    for k in ("mode", "AB", "AC", "BC", "h0", "flip", "ax", "ay", "az", "rot", "A", "B", "C"):
        if k in data:
            v = data[k]
            if k == "mode":
                r[k] = "scene" if v == "scene" else "libre"
            elif k == "flip":
                r[k] = bool(v)
            elif k in ("A", "B", "C"):
                if isinstance(v, (list, tuple)) and len(v) == 3:
                    r[k] = [num(x) or 0.0 for x in v]
            else:
                r[k] = num(v)
    tel["ver"] = tel.get("ver", 0) + 1


def upsert_point(tel, data):
    q = dict(name=str(data.get("name") or "").strip()[:60], type=data.get("type") if data.get("type") in TYPES else "autre",
             group=str(data.get("group") or "").strip()[:40], dA=num(data.get("dA")), dB=num(data.get("dB")),
             dC=num(data.get("dC")), below=bool(data.get("below")), hk=num(data.get("hk")),
             aim=str(data.get("aim") or "") or None)
    pid = data.get("id")
    old = next((p for p in tel["points"] if p["id"] == pid), None) if pid else None
    if not q["name"]:
        q["name"] = old["name"] if old else f"Point {len(tel['points']) + 1}"
    if old is not None:
        old.update(q)
        if old.get("aim") == old["id"]:
            old["aim"] = None
        p = old
    else:
        q["id"] = new_id()
        tel["points"].append(q)
        p = q
    tel["ver"] = tel.get("ver", 0) + 1
    return p


def delete_point(tel, pid):
    n = len(tel["points"])
    tel["points"] = [p for p in tel["points"] if p["id"] != pid]
    for p in tel["points"]:
        if p.get("aim") == pid:
            p["aim"] = None
    tel["ver"] = tel.get("ver", 0) + 1
    return n != len(tel["points"])


def make_speaker(name, group, model, P, aim=None):
    az, el = 0.0, 0.0
    if aim is not None:
        a = aim_angles(P, aim)
        if a:
            az, el = a
    return Speaker(name, group, model, x=round(float(P[0]), 4), y=round(float(P[1]), 4), z=round(float(P[2]), 4),
                   az=round(az, 2), el=round(el, 2))


def make_listener(name, P):
    return Listener(name, round(float(P[0]), 4), round(float(P[1]), 4), round(float(P[2]), 4))
