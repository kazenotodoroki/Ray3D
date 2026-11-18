"""Modèle de scène : formes extrudées, modèles de HP, objets (HP, line array, rangée),
groupes, écouteurs, réglages."""
from __future__ import annotations

import copy
import json
import math
import uuid
from dataclasses import dataclass, field, asdict, fields

import numpy as np

from . import geometry as G


def new_id() -> str:
    return uuid.uuid4().hex[:8]


SHAPE_KINDS = ["Pièce", "Objet", "Surface"]
PATTERNS = ["Pavillon", "Omni", "Cardioïde", "Supercardioïde", "Hypercardioïde", "Mesuré"]
ORIENTS = ["Verticale", "Couchée ←", "Couchée →", "Côte à côte →", "Côte à côte ←"]
MIRROR_ORIENT = {"Verticale": "Verticale", "Couchée ←": "Couchée →", "Couchée →": "Couchée ←",
                 "Côte à côte →": "Côte à côte ←", "Côte à côte ←": "Côte à côte →"}
GROUP_COLORS = ["#ff7a1a", "#3ec1ff", "#b6ff3a", "#ff3aa8", "#ffd23a",
                "#9b7bff", "#3affc8", "#ff5b5b"]


def speed_of_sound(temp_c: float) -> float:
    """Vitesse du son dans l'air sec (m/s)."""
    return 331.3 * math.sqrt(1.0 + temp_c / 273.15)


def frame(az_deg: float, el_deg: float, roll_deg: float = 0.0):
    """Repère local : f = axe, l = gauche, u = haut local (roulis autour de f)."""
    a, e = math.radians(az_deg), math.radians(el_deg)
    f = np.array([math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)])
    l = np.array([-math.sin(a), math.cos(a), 0.0])
    u = np.cross(f, l)
    if roll_deg:
        r = math.radians(roll_deg)
        l, u = math.cos(r) * l + math.sin(r) * u, -math.sin(r) * l + math.cos(r) * u
    return f, l, u


def base_matrix(az, el, roll=0.0):
    f, l, u = frame(az, el, roll)
    return np.column_stack([f, l, u])


def plane_rot(a, b, th_deg):
    """Rotation (3x3, coordonnées locales) dans le plan (a, b) : a tourne vers b."""
    t = math.radians(th_deg)
    A, B = np.outer(a, a) + np.outer(b, b), np.outer(b, a) - np.outer(a, b)
    return np.eye(3) + math.sin(t) * B + (math.cos(t) - 1) * A


def wrap180(a):
    return (a + 180.0) % 360.0 - 180.0


# --------------------------------------------------------------------------- formes
@dataclass
class Shape:
    name: str = "Forme"
    kind: str = "Pièce"            # Pièce (réfléchit à l'intérieur), Objet (plein), Surface (plane)
    profile: list = field(default_factory=lambda: [[0, 0], [10, 0], [10, 6.5], [0, 6.5]])
    plane: str = "XY"              # plan d'esquisse
    height: float = 3.0            # extrusion (0 = surface)
    symmetric: bool = False        # extrusion symétrique
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    rot: float = 0.0               # rotation autour de Z (°)
    tilt: float = 0.0              # inclinaison (°), monte vers +X
    absorption: float = 0.1
    audience: bool = False         # carte SPL
    assembly: str = ""             # ensemble (objet composé) auquel la forme appartient
    locked: bool = False
    arcs: list = field(default_factory=list)          # flèche par segment du profil (0 = droit)
    role: str = ""                 # "" ou "bass_trap" (traitement acoustique)
    id: str = field(default_factory=new_id)

    @property
    def is_bass_trap(self):
        return self.role == "bass_trap"

    @is_bass_trap.setter
    def is_bass_trap(self, v):
        self.role = "bass_trap" if v else ""

    def faces(self):
        a, b, e = G.PLANES.get(self.plane, G.PLANES["XY"])
        h = 0.0 if self.kind == "Surface" else max(self.height, 0.0)
        if self.kind == "Pièce" and self.plane == "XY":
            names = dict(cap0="sol", cap1="plafond", side="mur")
        elif self.plane == "XY":
            names = dict(cap0="dessous", cap1="dessus", side="face")
        else:
            names = dict(cap0="flanc A", cap1="flanc B", side="face")
        faces = G.extrude_faces(self.outline(), a, b, e, h, self.symmetric, names)
        M = G.rot_z(self.rot) @ G.rot_tilt(self.tilt)
        t = np.array([self.x, self.y, self.z])
        return [f.transformed(M, t) for f in faces]

    def outline(self):
        """Profil avec les arcs discrétisés."""
        return G.expand_profile(self.profile, self.arcs)

    def audience_faces(self):
        out = []
        for f in self.faces():
            nz = f.normal[2]
            if self.kind == "Pièce" and nz < -0.7:
                out.append(f)
            elif self.kind == "Objet" and nz > 0.7:
                out.append(f)
            elif self.kind == "Surface" and abs(nz) > 0.3:
                out.append(f)
        return out

    def corners(self):
        fs = self.faces()
        return np.vstack([f.verts for f in fs]) if fs else np.zeros((1, 3))

    def recenter(self, floor=True):
        """Centre la forme en XY sur l'origine, sol à z = 0."""
        c = self.corners()
        lo, hi = c.min(0), c.max(0)
        self.x -= (lo[0] + hi[0]) / 2
        self.y -= (lo[1] + hi[1]) / 2
        if floor:
            self.z -= lo[2]
        self.x, self.y, self.z = (round(v, 4) for v in (self.x, self.y, self.z))


# --------------------------------------------------------------------------- modèles de HP
@dataclass
class Element:
    """Transducteur / pavillon d'un HP, en coordonnées du modèle (f avant, l gauche, u haut)."""
    name: str = "HF"
    f: float = 0.0
    l: float = 0.0
    u: float = -0.17
    az: float = 0.0
    el: float = 0.0
    pattern: str = "Pavillon"
    cov_h: float = 110.0
    cov_v: float = 10.0
    level: float = 128.0
    delay: float = 0.0             # ms, interne au modèle
    balloon: dict | None = None    # directivité mesurée (freqs, az, el, db)


@dataclass
class SpeakerModel:
    """Enceinte : profil latéral (f, u) extrudé symétriquement sur la largeur.
    L'origine (0, 0) du profil est le point d'accroche."""
    name: str = "Modèle"
    profile: list = field(default_factory=lambda: [[0, 0], [0, -0.35], [-0.55, -0.3], [-0.55, -0.05]])
    width: float = 1.0
    top_hinge: list = field(default_factory=lambda: [0.0, 0.0])
    bottom_hinge: list = field(default_factory=lambda: [0.0, -0.35])
    elements: list = field(default_factory=lambda: [Element()])
    arcs: list = field(default_factory=list)         # flèche par segment du profil
    id: str = field(default_factory=new_id)

    def local_faces(self):
        """Faces en coordonnées (f, l, u)."""
        a = np.array([1.0, 0, 0]); b = np.array([0, 0, 1.0]); e = np.array([0, 1.0, 0])
        return G.extrude_faces(self.outline(), a, b, e, max(self.width, 0.01), True,
                               dict(cap0="flanc", cap1="flanc", side="face"))

    def hinge_span(self):
        return float(np.linalg.norm(np.subtract(self.top_hinge, self.bottom_hinge)))

    def aim_offset(self):
        if not self.elements:
            return 0.0
        return float(np.mean([e.el for e in self.elements]))

    def outline(self):
        return G.expand_profile(self.profile, self.arcs)

    def chain(self, orient="Verticale"):
        """Géométrie de chaînage : axe a, axe b (locaux), profil 2D (a, b), arêtes haute/basse."""
        a = np.array([1.0, 0.0, 0.0])
        if orient.startswith("Côte"):
            sb = 1.0 if "→" in orient else -1.0
            prof = G.ccw(self.outline())
            fmin, fmax = float(prof[:, 0].min()), float(prof[:, 0].max())
            w = max(self.width, 0.01) / 2
            return (a, np.array([0.0, sb, 0.0]), [[fmax, w], [fmin, w], [fmin, -w], [fmax, -w]],
                    [fmin, w], [fmin, -w])
        return a, np.array([0.0, 0.0, 1.0]), self.outline().tolist(), list(self.top_hinge), list(self.bottom_hinge)

    def splay_range(self, orient="Verticale"):
        """(min, max) des splays sans collision entre deux boîtes accrochées par leurs arêtes."""
        _, _, prof2, top, bot = self.chain(orient)
        key = (orient, json.dumps(prof2), tuple(top), tuple(bot))
        cache = self.__dict__.setdefault("_ms", {})
        if key in cache:
            return cache[key]
        prof = G.ccw(prof2)
        val = (-45.0, 45.0)
        if len(prof) >= 3 and np.linalg.norm(np.subtract(top, bot)) > 1e-6:
            area = abs(G.poly_area(prof))
            hull = G.hull2d(prof)

            def collides(s):
                q = box_profile_2d(prof, top, bot, 0.0, -s)
                return G.clip_area(q, hull) > 2e-4 * area
            if collides(0.0):
                val = (0.0, 0.0)
            else:
                hi = 0.0
                while hi < 90 and not collides(hi + 0.1):
                    hi += 0.1
                lo = 0.0
                while lo > -45 and not collides(lo - 0.1):
                    lo -= 0.1
                val = (round(lo, 1), round(hi, 1))
        cache[key] = val
        return val


def box_profile_2d(prof, top, bot, th0, th1):
    """Profil 2D de la boîte suivante (accrochée sous une boîte à l'angle th0) à l'angle th1,
    dans le repère de la première boîte (tests de collision)."""
    def R(th):
        t = math.radians(th)
        return np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])
    bh = R(th0) @ np.asarray(bot, float)
    P2 = bh - R(th1) @ np.asarray(top, float)
    prof = np.asarray(G.ccw(prof), float)
    return (prof @ R(th1).T) + P2


# --------------------------------------------------------------------------- objets
@dataclass
class Speaker:
    name: str = "HP"
    group: str = ""
    model: str = ""
    x: float = 0.0
    y: float = 0.0
    z: float = 3.0
    az: float = 0.0
    el: float = 0.0
    flip: bool = False             # symétrie gauche/droite du modèle
    gain: float = 0.0
    delay_offset: float = 0.0
    mute: bool = False
    locked: bool = False
    mirror_of: str = ""
    mirror_axis: str = ""
    id: str = field(default_factory=new_id)
    TYPE = "speaker"

    @property
    def pos(self):
        return np.array([self.x, self.y, self.z], float)


@dataclass
class LineArray:
    name: str = "Line array"
    group: str = ""
    model: str = ""
    x: float = 0.0
    y: float = 0.0
    z: float = 8.0
    az: float = 0.0
    top_angle: float = 0.0
    n: int = 8
    splays: list = field(default_factory=lambda: [2.0] * 7)
    orient: str = "Verticale"
    tilt: float = 0.0              # site d'ensemble (arrays horizontaux)
    flip: bool = False
    gain: float = 0.0
    delay_offset: float = 0.0
    mute: bool = False
    locked: bool = False
    mirror_of: str = ""
    mirror_axis: str = ""
    id: str = field(default_factory=new_id)
    TYPE = "array"

    @property
    def pos(self):
        return np.array([self.x, self.y, self.z], float)

    def norm_splays(self):
        n = max(1, int(self.n))
        s = [float(v) for v in self.splays][: n - 1]
        while len(s) < n - 1:
            s.append(s[-1] if s else 0.0)
        self.splays = s
        return s


@dataclass
class Row:
    name: str = "Rangée"
    group: str = ""
    model: str = ""
    x: float = 0.0
    y: float = 0.0
    z: float = 1.2
    az: float = 0.0
    el: float = 0.0
    n: int = 4
    spacing: float = 3.0
    row_angle: float = 90.0
    flip: bool = False
    gain: float = 0.0
    delay_offset: float = 0.0
    mute: bool = False
    locked: bool = False
    mirror_of: str = ""
    mirror_axis: str = ""
    id: str = field(default_factory=new_id)
    TYPE = "row"

    @property
    def pos(self):
        return np.array([self.x, self.y, self.z], float)


OBJ_TYPES = {"speaker": Speaker, "array": LineArray, "row": Row}
OBJ_LABEL = {"speaker": "HP", "array": "line array", "row": "rangée"}


@dataclass
class Group:
    name: str = "Groupe"
    color: str = "#ff7a1a"
    main: bool = False
    id: str = field(default_factory=new_id)


@dataclass
class Assembly:
    """Ensemble de formes (objet composé : bureau, régie, praticable…)."""
    name: str = "Ensemble"
    locked: bool = False
    parent: str = ""               # ensemble parent (sous-groupe)
    id: str = field(default_factory=new_id)


@dataclass
class Listener:
    name: str = "Écoute"
    x: float = 0.0
    y: float = 0.0
    z: float = 1.2
    locked: bool = False
    head: bool = False             # sphère de la taille d'une tête
    head_d: float = 0.18           # diamètre de la tête (m)
    id: str = field(default_factory=new_id)

    @property
    def pos(self):
        return np.array([self.x, self.y, self.z], float)


@dataclass
class Source:
    """Source sonore élémentaire (générée à partir des objets)."""
    name: str = "Source"
    group: str = ""
    owner: str = ""
    x: float = 0.0
    y: float = 0.0
    z: float = 2.0
    az: float = 0.0
    el: float = 0.0
    pattern: str = "Pavillon"
    cov_h: float = 90.0
    cov_v: float = 60.0
    level: float = 115.0
    delay_offset: float = 0.0
    mute: bool = False
    roll: float = 0.0
    balloon: dict | None = None
    baffle: float = 0.3            # largeur de la face avant (m) : transition omni / directif
    id: str = field(default_factory=new_id)

    @property
    def pos(self):
        return np.array([self.x, self.y, self.z], float)


@dataclass
class Settings:
    temperature: float = 20.0
    haas: float = 0.0
    ref_mode: str = "Axe"
    per_group_delay: bool = True
    apply_delays: bool = True
    show_cov: bool = True
    cov_range: float = 30.0
    cov_clip: bool = True
    cone_alpha: float = 0.18
    show_rays: bool = True
    rays_selection_only: bool = True
    rays_listener_only: bool = False
    rays_capture: float = 0.25
    nrays: int = 40
    max_order: int = 2
    ray_len: float = 80.0
    show_refl: bool = True
    refl_order: int = 1
    refl_listener: str = ""
    show_spl: bool = True
    spl_scope: str = "Sélection"
    show_section: bool = True
    freq: float = 1000.0
    band: str = "Octave"
    ear: float = 1.2
    section_y: float = 0.0
    dyn: float = 18.0
    resolution: float = 0.0        # 0 = automatique
    opt_near: float = 5.0
    opt_far: float = 26.0
    opt_znear: float = 1.2
    opt_zfar: float = 4.6
    opt_max: float = 10.0
    opt_step: float = 0.5
    opt_weight: float = 1.0
    target_freq: float = 1000.0
    # SBIR
    sbir_listener: str = ""
    sbir_scope: str = "Sélection"
    sbir_fmin: float = 20.0
    sbir_fmax: float = 1000.0
    sbir_order: int = 1
    sbir_smooth: str = "1/12 oct"
    sbir_rear_rad: bool = True
    sbir_rear_wall: bool = True
    sbir_front: bool = True
    sbir_side: bool = True
    sbir_floor: bool = True
    sbir_ceiling: bool = True
    sbir_show_paths: bool = True
    sbir_band_lo: float = 40.0
    sbir_band_hi: float = 300.0
    sbir_scan: str = "Distance enceinte ↔ mur"
    sbir_scan_min: float = 0.05
    sbir_scan_max: float = 1.5
    row_dist: float = 3.0
    row_overlap: str = "-6 dB"
    # traitement acoustique (premières réflexions, hors bass traps)
    treat_show: bool = False
    treat_scope: str = "Sélection"
    treat_head_w: float = 0.6
    treat_head_d: float = 0.3
    treat_head_h: float = 0.2
    treat_margin: float = 0.10
    treat_min_level: float = -30.0
    treat_size: str = "120 × 60 cm"
    treat_thick: float = 0.10
    treat_alpha: float = 0.9
    treat_gap: float = 0.0
    treat_panels: dict = field(default_factory=dict)
    treat_assembly: str = ""
    treat_zone_assy: dict = field(default_factory=dict)
    treat_hide_zones: bool = False
    treat_ceiling_drop: float = 0.0
    bt_size: float = 0.60
    bt_alpha: float = 0.95
    cam_orbit: bool = False
    # export PDF
    pdf_units: str = "mm"


# --------------------------------------------------------------------------- poses
def pose_points(P, M, pts):
    """Points (N,3) en coordonnées modèle (f, l, u) -> monde."""
    return P + np.atleast_2d(np.asarray(pts, float)) @ M.T


def object_poses(obj, model: SpeakerModel):
    """Liste de (point d'accroche monde, matrice 3x3 modèle -> monde) pour chaque boîte."""
    D = np.diag([1.0, -1.0 if obj.flip else 1.0, 1.0])
    if obj.TYPE == "speaker":
        return [(obj.pos, base_matrix(obj.az, obj.el) @ D)]
    if obj.TYPE == "row":
        r = math.radians(obj.row_angle)
        d = np.array([math.cos(r), math.sin(r), 0.0])
        M = base_matrix(obj.az, obj.el) @ D
        return [(obj.pos + d * obj.spacing * i, M) for i in range(max(1, int(obj.n)))]
    # line array : l'arête haute de la boîte i+1 vient sur l'arête basse de la boîte i,
    # le splay est une rotation autour de cette arête
    orient = obj.orient if obj.orient in ORIENTS else "Verticale"
    a, b, _, top, bot = model.chain(orient)
    roll = {"Couchée ←": 90.0, "Couchée →": -90.0}.get(orient, 0.0)
    Rb = base_matrix(obj.az, 0.0 if orient == "Verticale" else obj.tilt, roll)
    th3 = top[0] * a + top[1] * b
    bh3 = bot[0] * a + bot[1] * b
    out = []
    P, th = obj.pos, obj.top_angle
    splays = obj.norm_splays()
    for i in range(max(1, int(obj.n))):
        if i > 0:
            hb = P + Rb @ plane_rot(a, b, th) @ bh3
            th = th - splays[i - 1]
            P = hb - Rb @ plane_rot(a, b, th) @ th3
        out.append((P, Rb @ plane_rot(a, b, th) @ D))
    return out


def element_frame(M, e):
    """Position-indépendant : direction (az, el, roll) monde d'un élément."""
    fe, le, ue = frame(e.az, e.el)
    Fe, Ue = M @ fe, M @ ue
    az = math.degrees(math.atan2(Fe[1], Fe[0]))
    el = math.degrees(math.asin(max(-1.0, min(1.0, Fe[2]))))
    _, l0, u0 = frame(az, el)
    roll = math.degrees(math.atan2(-(Ue @ l0), Ue @ u0))
    return az, el, roll


# --------------------------------------------------------------------------- scène
class Scene:
    def __init__(self):
        self.shapes: list[Shape] = []
        self.models: list[SpeakerModel] = []
        self.groups: list[Group] = []
        self.objects: list = []
        self.listeners: list[Listener] = []
        self.assemblies: list[Assembly] = []
        self.settings = Settings()
        self.sources: list[Source] = []   # générées
        self.bodies: dict = {}            # obj.id -> liste de faces monde par boîte
        self.delays: dict[str, float] = {}

    # accès
    def group(self, gid):
        return next((g for g in self.groups if g.id == gid), None)

    def model(self, mid):
        return next((m for m in self.models if m.id == mid), None) or (self.models[0] if self.models else None)

    def obj(self, oid):
        return next((o for o in self.objects if o.id == oid), None)

    def listener(self, lid):
        return next((l for l in self.listeners if l.id == lid), None)

    def objects_in(self, gid):
        return [o for o in self.objects if o.group == gid]

    def sources_in(self, gid):
        return [s for s in self.sources if s.group == gid]

    def assembly(self, aid):
        return next((a for a in self.assemblies if a.id == aid), None)

    def shapes_in(self, aid):
        """Formes directement dans l'ensemble aid."""
        return [s for s in self.shapes if s.assembly == aid]

    def sub_assemblies(self, aid):
        return [a for a in self.assemblies if a.parent == aid]

    def descendant_assemblies(self, aid):
        out, todo = [], [aid]
        while todo:
            cur = todo.pop()
            for a in self.sub_assemblies(cur):
                if a not in out:
                    out.append(a)
                    todo.append(a.id)
        return out

    def all_shapes_in(self, aid):
        """Formes de l'ensemble et de tous ses sous-ensembles."""
        ids = {aid} | {a.id for a in self.descendant_assemblies(aid)}
        return [s for s in self.shapes if s.assembly in ids]

    def ancestors(self, aid):
        out, seen = [], set()
        a = self.assembly(aid)
        while a is not None and a.parent and a.parent not in seen:
            seen.add(a.parent)
            a = self.assembly(a.parent)
            if a is not None:
                out.append(a)
        return out

    def prune_assemblies(self):
        """Supprime les ensembles vides (sans forme ni sous-ensemble)."""
        changed = True
        while changed:
            changed = False
            for a in list(self.assemblies):
                if not self.shapes_in(a.id) and not self.sub_assemblies(a.id):
                    self.assemblies.remove(a)
                    changed = True

    def sources_of(self, oid):
        return [s for s in self.sources if s.owner == oid]

    def active_sources(self):
        return [s for s in self.sources if not s.mute]

    def find(self, oid):
        for kind, coll in (("shape", self.shapes), ("group", self.groups), ("object", self.objects),
                           ("listener", self.listeners), ("model", self.models), ("assembly", self.assemblies)):
            for o in coll:
                if o.id == oid:
                    return kind, o
        return None, None

    def color_of(self, s):
        g = self.group(s.group)
        return g.color if g else "#cccccc"

    def next_color(self):
        used = {g.color for g in self.groups}
        for c in GROUP_COLORS:
            if c not in used:
                return c
        return GROUP_COLORS[len(self.groups) % len(GROUP_COLORS)]

    # génération
    def sync(self):
        gids = {g.id for g in self.groups}
        if self.objects and not self.groups:
            self.groups.append(Group("Groupe 1", GROUP_COLORS[0]))
            gids = {self.groups[0].id}
        for o in self.objects:
            if o.group not in gids:
                o.group = self.groups[0].id
        srcs, bodies = [], {}
        for o in self.objects:
            m = self.model(o.model)
            if m is None:
                continue
            if o.TYPE == "array":
                o.norm_splays()
            lf = m.local_faces()
            boxes = []
            poses = object_poses(o, m)
            multi = len(m.elements) > 1
            for i, (P, M) in enumerate(poses):
                boxes.append([f.transformed(M, P) for f in lf])
                for k, e in enumerate(m.elements):
                    pos = pose_points(P, M, [e.f, e.l, e.u])[0]
                    az, el, roll = element_frame(M, e)
                    nm = o.name if len(poses) == 1 else f"{o.name} {i + 1}"
                    if multi:
                        nm += f" · {e.name}"
                    pat = e.pattern if (e.pattern != "Mesuré" or e.balloon) else "Omni"
                    srcs.append(Source(nm, o.group, o.id, float(pos[0]), float(pos[1]), float(pos[2]),
                                       az, el, pat, e.cov_h, e.cov_v, e.level + o.gain,
                                       o.delay_offset + e.delay, o.mute, roll, e.balloon,
                                       max(m.width, 0.05), id=f"{o.id}-{i}-{k}"))
            bodies[o.id] = boxes
        self.sources, self.bodies = srcs, bodies

    def bbox(self):
        if not self.shapes:
            return np.array([-10, -10, 0.0]), np.array([10, 10, 8.0])
        pts = np.vstack([s.corners() for s in self.shapes])
        return pts.min(0), pts.max(0)

    # miroir lié
    def partner(self, o):
        return self.obj(o.mirror_of) if getattr(o, "mirror_of", "") else None

    def propagate(self, o):
        """Recopie o sur son partenaire miroir."""
        p = self.partner(o)
        if p is None or p.TYPE != o.TYPE:
            return
        keep = {"id", "name", "group", "mirror_of", "mirror_axis", "mute"}
        for f in fields(o):
            if f.name not in keep:
                setattr(p, f.name, copy.deepcopy(getattr(o, f.name)))
        ax = o.mirror_axis or "Y"
        if ax == "Y":
            p.y = -o.y
            p.az = wrap180(-o.az)
            if o.TYPE == "row":
                p.row_angle = wrap180(-o.row_angle)
        else:
            p.x = -o.x
            p.az = wrap180(180 - o.az)
            if o.TYPE == "row":
                p.row_angle = wrap180(180 - o.row_angle)
        p.flip = not o.flip
        if o.TYPE == "array":
            p.orient = MIRROR_ORIENT.get(o.orient, o.orient)

    def make_mirror(self, o, axis):
        p = copy.deepcopy(o)
        p.id = new_id()
        p.name = mirror_name(o.name, axis)
        o.mirror_of, o.mirror_axis = p.id, axis
        p.mirror_of, p.mirror_axis = o.id, axis
        self.objects.append(p)
        self.propagate(o)
        return p

    def unlink(self, o):
        p = self.partner(o)
        o.mirror_of = o.mirror_axis = ""
        if p is not None:
            p.mirror_of = p.mirror_axis = ""

    # sérialisation
    def to_dict(self):
        objs = []
        for o in self.objects:
            d = asdict(o)
            d["type"] = o.TYPE
            objs.append(d)
        return dict(version=2,
                    shapes=[asdict(s) for s in self.shapes],
                    models=[asdict(m) for m in self.models],
                    groups=[asdict(g) for g in self.groups],
                    objects=objs,
                    listeners=[asdict(l) for l in self.listeners],
                    assemblies=[asdict(a) for a in self.assemblies],
                    settings=asdict(self.settings))

    @staticmethod
    def _make(cls, d):
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})

    @classmethod
    def from_dict(cls, d):
        sc = cls()
        sc.shapes = [cls._make(Shape, x) for x in d.get("shapes", [])]
        for x in d.get("models", []):
            m = cls._make(SpeakerModel, x)
            m.elements = [cls._make(Element, e) for e in x.get("elements", [])]
            sc.models.append(m)
        sc.groups = [cls._make(Group, x) for x in d.get("groups", [])]
        for x in d.get("objects", []):
            t = OBJ_TYPES.get(x.get("type"))
            if t:
                sc.objects.append(cls._make(t, x))
        sc.listeners = [cls._make(Listener, x) for x in d.get("listeners", [])]
        sc.assemblies = [cls._make(Assembly, x) for x in d.get("assemblies", [])]
        ids = {a.id for a in sc.assemblies}
        for a in sc.assemblies:
            if a.parent not in ids or a.parent == a.id:
                a.parent = ""
        for s in sc.shapes:
            if s.assembly and s.assembly not in ids:
                s.assembly = ""
        sc.settings = cls._make(Settings, d.get("settings", {}))
        from .library import default_models
        have = {m.id for m in sc.models}
        sc.models += [m for m in default_models() if m.id not in have]
        sc.sync()
        return sc

    def save(self, path):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))


def mirror_name(name, axis):
    for a, b in ((" L", " R"), (" R", " L"), (" G", " D"), (" D", " G"), ("Left", "Right"), ("Right", "Left")):
        if name.endswith(a):
            return name[: -len(a)] + b
    return f"{name} (miroir {axis})"
