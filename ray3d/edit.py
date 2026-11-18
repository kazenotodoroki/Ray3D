"""Édition de scène : coins et arêtes des éléments, déplacements, verrous, ensembles
(objets composés) et leur sauvegarde."""
from __future__ import annotations

import copy
import json
from dataclasses import asdict, fields

import numpy as np

from .model import (Scene, Shape, Group, Listener, Assembly, SpeakerModel, Element, OBJ_TYPES, new_id,
                    GROUP_COLORS)

ENSEMBLE_FORMAT = "ray3d-ensemble/1"


# --------------------------------------------------------------------------- coins et arêtes
def _faces_points(faces):
    """Sommets uniques (N,3) et arêtes uniques [(i, j)] d'une liste de faces."""
    keys, pts, edges = {}, [], set()

    def idx(v):
        k = tuple(np.round(v, 5))
        if k not in keys:
            keys[k] = len(pts)
            pts.append(np.asarray(v, float))
        return keys[k]
    for f in faces:
        ids = [idx(v) for v in f.verts]
        for a in range(len(ids)):
            i, j = ids[a], ids[(a + 1) % len(ids)]
            if i != j:
                edges.add((min(i, j), max(i, j)))
    return (np.array(pts) if pts else np.zeros((0, 3))), sorted(edges)


def item_faces(scene: Scene, kind, obj):
    if kind == "shape":
        return obj.faces()
    if kind == "assembly":
        return [f for s in scene.all_shapes_in(obj.id) for f in s.faces()]
    if kind == "object":
        return [f for box in scene.bodies.get(obj.id, []) for f in box]
    if kind == "group":
        return [f for o in scene.objects_in(obj.id) for box in scene.bodies.get(o.id, []) for f in box]
    return []


def item_points(scene: Scene, kind, obj):
    """Coins (N,3) et arêtes d'un élément. Écouteur : un seul point."""
    if kind == "listener":
        return obj.pos[None].copy(), []
    return _faces_points(item_faces(scene, kind, obj))


def corner_order(P):
    """Ordre lisible des coins : par z, puis y, puis x."""
    if len(P) == 0:
        return np.zeros(0, int)
    return np.lexsort((np.round(P[:, 0], 4), np.round(P[:, 1], 4), np.round(P[:, 2], 4)))


def sorted_points(scene, kind, obj):
    """Coins triés (numérotation stable 1..N) et arêtes renumérotées."""
    P, E = item_points(scene, kind, obj)
    P = np.round(P, 6) + 0.0                     # pas de « -0.000 »
    order = corner_order(P)
    inv = np.empty(len(order), int)
    inv[order] = np.arange(len(order))
    return P[order], sorted({(min(inv[i], inv[j]), max(inv[i], inv[j])) for i, j in E})


def neighbours(edges, k):
    return sorted({int(j if i == k else i) for i, j in edges if k in (i, j)})


# --------------------------------------------------------------------------- verrous et déplacements
def is_locked(scene: Scene, kind, obj):
    if obj is None:
        return True
    if getattr(obj, "locked", False):
        return True
    aid = obj.assembly if kind == "shape" else (obj.id if kind == "assembly" else "")
    if aid:
        chain = ([scene.assembly(aid)] if kind == "shape" else []) + scene.ancestors(aid)
        return any(a is not None and a.locked for a in chain)
    return False


def expand(scene: Scene, items):
    """(kind, obj) -> éléments déplaçables élémentaires, sans doublon, en ne gardant qu'un
    élément par paire miroir (son partenaire suit)."""
    out, seen = [], set()

    def add(k, o):
        if o is None or o.id in seen:
            return
        seen.add(o.id)
        out.append((k, o))
    for kind, obj in items:
        if kind == "assembly":
            for s in scene.all_shapes_in(obj.id):
                add("shape", s)
        elif kind == "group":
            for o in scene.objects_in(obj.id):
                add("object", o)
        elif kind in ("shape", "object", "listener"):
            add(kind, obj)
    res, taken = [], set()
    for k, o in out:
        if k == "object" and getattr(o, "mirror_of", "") and o.mirror_of in taken:
            continue
        taken.add(o.id)
        res.append((k, o))
    return res


def translate(scene: Scene, items, d):
    """Déplace les éléments de d = (dx, dy, dz). Renvoie (déplacés, verrouillés)."""
    d = np.asarray(d, float)
    moved, locked = [], []
    for kind, obj in expand(scene, items):
        if is_locked(scene, kind, obj):
            locked.append(obj)
            continue
        obj.x = round(obj.x + float(d[0]), 4)
        obj.y = round(obj.y + float(d[1]), 4)
        obj.z = round(obj.z + float(d[2]), 4)
        if kind == "object" and getattr(obj, "mirror_of", ""):
            scene.propagate(obj)
        moved.append(obj)
    return moved, locked


def snap_vector(P_src, k_src, P_dst, k_dst, edge_to=None, along=0.0, extra=(0, 0, 0)):
    """Vecteur qui amène le coin k_src sur le coin k_dst, puis le fait glisser de « along » mètres
    sur l'arête k_dst → edge_to, plus un décalage libre."""
    target = P_dst[k_dst].copy()
    if edge_to is not None:
        e = P_dst[edge_to] - P_dst[k_dst]
        L = float(np.linalg.norm(e))
        if L > 1e-9:
            target = target + e / L * along
    return target - P_src[k_src] + np.asarray(extra, float)


# --------------------------------------------------------------------------- ensembles (objets composés)
def make_assembly(scene: Scene, shapes, name=None, subs=()):
    """Nouvel ensemble contenant des formes et des sous-ensembles. Il prend la place des éléments
    dans leur ensemble parent commun (s'il y en a un)."""
    parents = {s.assembly for s in shapes} | {a.parent for a in subs}
    sub_ids = {a.id for a in subs}
    parent = parents.pop() if len(parents) == 1 else ""
    if parent in sub_ids:
        parent = ""
    a = Assembly(name or f"Ensemble {len(scene.assemblies) + 1}", parent=parent)
    scene.assemblies.append(a)
    for s in shapes:
        s.assembly = a.id
    for b in subs:
        if b.id != a.id:
            b.parent = a.id
    return a


def dissolve(scene: Scene, a):
    """Supprime l'ensemble ; son contenu remonte dans l'ensemble parent."""
    for s in scene.shapes_in(a.id):
        s.assembly = a.parent
    for b in scene.sub_assemblies(a.id):
        b.parent = a.parent
    scene.assemblies.remove(a)


def can_nest(scene: Scene, child_id, parent_id):
    """Vrai si l'ensemble child peut être placé dans parent (pas de boucle)."""
    if not parent_id:
        return True
    if child_id == parent_id:
        return False
    return parent_id not in {b.id for b in scene.descendant_assemblies(child_id)}


def ensemble_dict(scene: Scene, items, name):
    """Contenu d'un fichier d'ensemble à partir d'une sélection (formes, ensembles, HP, groupes,
    écouteurs)."""
    shapes, objects, listeners, asm = [], [], [], {}
    for kind, obj in items:
        if kind == "assembly":
            asm[obj.id] = obj
            for b in scene.descendant_assemblies(obj.id):
                asm[b.id] = b
            shapes += scene.all_shapes_in(obj.id)
        elif kind == "shape":
            shapes.append(obj)
            if obj.assembly:
                asm.setdefault(obj.assembly, scene.assembly(obj.assembly))
        elif kind == "object":
            objects.append(obj)
        elif kind == "group":
            objects += scene.objects_in(obj.id)
        elif kind == "listener":
            listeners.append(obj)
    uniq = lambda xs: list({x.id: x for x in xs}.values())
    shapes, objects, listeners = uniq(shapes), uniq(objects), uniq(listeners)
    groups = uniq([scene.group(o.group) for o in objects if scene.group(o.group)])
    models = uniq([scene.model(o.model) for o in objects if scene.model(o.model)])
    objs = []
    for o in objects:
        dd = asdict(o); dd["type"] = o.TYPE
        objs.append(dd)
    return dict(format=ENSEMBLE_FORMAT, name=name,
                assemblies=[asdict(a) for a in asm.values() if a is not None],
                shapes=[asdict(s) for s in shapes], objects=objs,
                listeners=[asdict(l) for l in listeners],
                groups=[asdict(g) for g in groups], models=[asdict(m) for m in models])


def save_ensemble(scene, items, path, name):
    d = ensemble_dict(scene, items, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)
    return d


def _make(cls, d):
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in d.items() if k in names})


def insert_ensemble(scene: Scene, d, offset=(0.0, 0.0, 0.0)):
    """Insère un ensemble (dict) dans la scène avec de nouveaux identifiants. Renvoie les éléments
    créés [(kind, obj)]."""
    if d.get("format") != ENSEMBLE_FORMAT:
        raise ValueError("Ce fichier n'est pas un ensemble Ray 3D.")
    off = np.asarray(offset, float)
    created = []
    # modèles : on réutilise ceux déjà présents (même id), sinon on les ajoute
    have = {m.id for m in scene.models}
    for md in d.get("models", []):
        if md.get("id") in have:
            continue
        m = _make(SpeakerModel, {k: v for k, v in md.items() if k != "elements"})
        m.elements = [_make(Element, e) for e in md.get("elements", [])]
        scene.models.append(m)
    # ensembles : nouvel id ; le nom de fichier sert de nom s'il n'y a qu'un ensemble
    amap = {}
    for ad in d.get("assemblies", []):
        a = _make(Assembly, ad)
        a.id = new_id()
        a.locked = False
        if len(d.get("assemblies", [])) == 1 and d.get("name"):
            a.name = d["name"]
        amap[ad["id"]] = a.id
        scene.assemblies.append(a)
        if not ad.get("parent") or ad.get("parent") not in {x["id"] for x in d.get("assemblies", [])}:
            created.append(("assembly", a))          # ensembles de premier niveau seulement
    for ad in d.get("assemblies", []):              # sous-ensembles : parents renumérotés
        a = scene.assembly(amap[ad["id"]])
        a.parent = amap.get(ad.get("parent", ""), "")
    loose = [sd for sd in d.get("shapes", []) if not sd.get("assembly") or sd["assembly"] not in amap]
    if len(loose) > 1 and not amap:          # plusieurs formes libres : on les regroupe
        a = Assembly(d.get("name") or "Ensemble")
        scene.assemblies.append(a)
        created.append(("assembly", a))
        for sd in loose:
            amap.setdefault(sd.get("assembly") or "_loose", a.id)
    for sd in d.get("shapes", []):
        s = _make(Shape, sd)
        s.id = new_id()
        s.assembly = amap.get(sd.get("assembly") or "_loose", "")
        s.x += off[0]; s.y += off[1]; s.z += off[2]
        scene.shapes.append(s)
        if not s.assembly:
            created.append(("shape", s))
    # groupes : même nom = même groupe
    gmap = {}
    for gd in d.get("groups", []):
        g = next((x for x in scene.groups if x.name == gd.get("name")), None)
        if g is None:
            g = _make(Group, gd)
            g.id = new_id()
            g.main = False
            if any(x.color == g.color for x in scene.groups):
                g.color = scene.next_color()
            scene.groups.append(g)
        gmap[gd["id"]] = g.id
    omap, new_objs = {}, []
    for od in d.get("objects", []):
        t = OBJ_TYPES.get(od.get("type"))
        if t is None:
            continue
        o = _make(t, od)
        omap[od["id"]] = o.id = new_id()
        o.group = gmap.get(od.get("group"), scene.groups[0].id if scene.groups else "")
        o.x += off[0]; o.y += off[1]; o.z += off[2]
        new_objs.append(o)
    for o in new_objs:                          # miroirs internes à l'ensemble conservés
        o.mirror_of = omap.get(o.mirror_of, "")
        if not o.mirror_of:
            o.mirror_axis = ""
        scene.objects.append(o)
        created.append(("object", o))
    for ld in d.get("listeners", []):
        l = _make(Listener, ld)
        l.id = new_id()
        l.x += off[0]; l.y += off[1]; l.z += off[2]
        scene.listeners.append(l)
        created.append(("listener", l))
    if new_objs and not scene.groups:
        scene.groups.append(Group("Groupe 1", GROUP_COLORS[0]))
    scene.sync()
    return created


def load_ensemble(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
