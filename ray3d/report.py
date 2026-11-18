"""Exports PDF : analyse acoustique (SBIR, plan, élévations, panneaux) et plans de découpe d'un ensemble."""
from __future__ import annotations

import math
import os

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from . import geometry as G
from . import sbir as SB
from . import treatment as T
from .pdfdoc import Doc, Frame, fmt_len, INK, DIM_INK, LIGHT, ACCENT, ZONE, PANEL_FILL
from .widgets import NoWheelCombo, no_enter_dialog

SPK_FILL = QtGui.QColor("#bdbdbd")
OBJ_INK = QtGui.QColor("#444444")


# =========================================================================== utilitaires
def _seg_pairs(faces, ax=(0, 1)):
    E = G.faces_edges(faces)
    return [(E[i][list(ax)], E[i + 1][list(ax)]) for i in range(0, len(E), 2)]


def _hull(P2):
    P2 = np.asarray(P2, float)
    if len(P2) < 3:
        return P2
    return np.asarray(G.hull2d(P2))


def _scene_name(app):
    p = getattr(app, "path", None)
    return os.path.splitext(os.path.basename(p))[0] if p else "scène"


def _rooms(scene):
    return [s for s in scene.shapes if s.kind == "Pièce"]


# =========================================================================== vue 3D positionnée
class SnapshotDialog(QtWidgets.QDialog):
    """Vue 3D à cadrer avant l'export : l'image est prise à la validation."""

    def __init__(self, parent, scene, res, cam):
        super().__init__(parent)
        from .views import View3D
        self.setWindowTitle("Vue 3D du rapport · cadrez puis exportez")
        no_enter_dialog(self)
        self.resize(1100, 760)
        lay = QtWidgets.QVBoxLayout(self)
        info = QtWidgets.QLabel("Tournez (clic gauche), déplacez (clic milieu / Maj), zoomez (molette). "
                                "L'image est prise telle qu'elle est affichée.")
        info.setObjectName("info")
        lay.addWidget(info)
        self.view = View3D()
        self.view.setMinimumSize(900, 560)
        lay.addWidget(self.view, 1)
        self.view.render(scene, res, set())
        self.view._fitted = True
        if cam:
            self.view.setCameraPosition(pos=cam["center"], distance=cam["distance"],
                                        elevation=cam["elevation"], azimuth=cam["azimuth"])
        hb = QtWidgets.QHBoxLayout()
        self.paths = QtWidgets.QCheckBox("Inclure les chemins de réflexion")
        self.paths.setChecked(True)
        self._scene, self._res = scene, res
        self.paths.toggled.connect(self._toggle_paths)
        hb.addWidget(self.paths)
        hb.addStretch(1)
        bc = QtWidgets.QPushButton("Annuler"); bc.clicked.connect(self.reject)
        bo = QtWidgets.QPushButton("Exporter le PDF…"); bo.setObjectName("primary"); bo.clicked.connect(self._ok)
        hb.addWidget(bc); hb.addWidget(bo)
        lay.addLayout(hb)
        self.image = None

    def _toggle_paths(self, on):
        res = dict(self._res)
        if not on:
            res["refl"] = []
            res["rays"] = None
        self.view.render(self._scene, res, set())

    def _ok(self):
        self.image = self.view.grabFramebuffer()
        self.accept()


def camera_of(view):
    o = view.opts
    return dict(center=o["center"], distance=o["distance"], elevation=o["elevation"], azimuth=o["azimuth"])


# =========================================================================== analyse acoustique
def export_analysis(app, path=None, image=None):
    """Depuis la fenêtre principale : cadrage 3D, choix du fichier, écriture."""
    res = getattr(app, "_last_res", None)
    if res is None:
        app.recompute()
        res = app._last_res
    data = gather_analysis(app)
    vis = data["zone_vis"]
    res = dict(res, zones=[z for z in res.get("zones", []) if vis.get(z.key, False)],
               zone_plan={k: v for k, v in res.get("zone_plan", {}).items() if vis.get(k, False)})
    if image is None:
        dlg = SnapshotDialog(app, app.scene, res, camera_of(app.v3d))
        if not dlg.exec():
            return None
        image = dlg.image
    if path is None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(app, "Exporter l'analyse acoustique",
                                                        f"analyse_{_scene_name(app)}.pdf", "PDF (*.pdf)")
        if not path:
            return None
    data["image"] = image
    write_analysis(path, data)
    if hasattr(app, "status"):
        app.status.setText(f"PDF exporté : {path}")
    return path


def gather_analysis(app):
    sc = app.scene
    zones, tctx = app.compute_treatment()
    placed = T.panel_rects(sc, zones)
    st = sc.settings
    plans = {}
    for z in zones:
        cfg = T.zone_cfg(z, st)
        if placed.get(z.key):
            plans[z.key] = dict(rects=placed[z.key], placed=True, cfg=cfg)
        elif cfg["on"]:
            lay = T.layout(z, cfg, st.treat_gap)
            plans[z.key] = dict(rects=[r + (f"{z.abbr}-{i + 1}",) for i, r in enumerate(lay["rects"])],
                                placed=False, cfg=cfg)
    ctx = app.sbir_context()
    sb = app.compute_sbir() if ctx is not None else None
    # zones minimales : pas affichées quand les panneaux sont posés (ou si masquées)
    zone_vis = {z.key: not st.treat_hide_zones and not z.empty and T.zone_cfg(z, st)["on"]
                and not (z.key in plans and plans[z.key]["placed"]) for z in zones}
    return dict(scene=sc, name=_scene_name(app), units=st.pdf_units, zones=zones, plans=plans, sbir=sb,
                ctx=ctx, tctx=tctx, zone_vis=zone_vis, traps=T.bass_traps(sc))


def write_analysis(path, data):
    sc = data["scene"]
    units = data["units"]
    doc = Doc(path, "Analyse acoustique", data["name"])
    _page_summary(doc, data)
    if data["sbir"] is not None:
        doc.new_page("SBIR · réponse au point d'écoute")
        _page_sbir(doc, data)
    doc.new_page("Plan de la pièce (vue de dessus)")
    _page_plan(doc, data)
    zones = [z for z in data["zones"] if data["zone_vis"].get(z.key) or z.key in data["plans"]]
    for z in zones:                              # une paroi par page (échelle 1:20 à 1:50)
        what = "zone minimale et panneaux" if data["zone_vis"].get(z.key) else "panneaux"
        doc.new_page(("Élévation" if z.kind == "wall" else "Plan") + f" · {z.label} · {what}")
        _elevation(doc, data, z, (doc.M, doc.top, doc.W - 2 * doc.M, doc.H - 13 - doc.top))
    if data["plans"] or data["traps"]:
        doc.new_page("Liste des panneaux et bass traps")
        _panel_list(doc, data)
    doc.finish()
    return path


# --------------------------------------------------------------------------- page 1
def _page_summary(doc, data):
    sc, units = data["scene"], data["units"]
    doc.section("Synthèse")
    y0 = doc.top
    doc.image(doc.M, y0, 160, 104, data.get("image"))
    x = doc.M + 166
    w = doc.W - doc.M - x
    y = y0 + 3
    rooms = _rooms(sc)
    for r in rooms[:2]:
        P = np.vstack([f.verts for f in r.faces()])
        e = P.max(0) - P.min(0)
        y = doc.para(x, y, w, f"Pièce « {r.name} » : {e[0]:.2f} × {e[1]:.2f} m, hauteur {e[2]:.2f} m, "
                              f"absorption {r.absorption:.2f}", 8) + 1.5
    ctx = data["ctx"] or data["tctx"]
    if ctx is not None:
        L = ctx["listener"]
        y = doc.para(x, y, w, f"Écoute « {ctx['listener_obj'].name} » : X {L[0]:.3f} · Y {L[1]:.3f} · "
                              f"Z {L[2]:.3f} m", 8) + 1.5
    sb = data["sbir"]
    if sb is not None:
        st = sc.settings
        dev = SB.flatness(sb["freqs"], sb["H"], st.sbir_band_lo, st.sbir_band_hi)
        devd = SB.flatness(sb["freqs"], sb["Hd"], st.sbir_band_lo, st.sbir_band_hi)
        y = doc.para(x, y, w, f"SBIR {st.sbir_band_lo:.0f}–{st.sbir_band_hi:.0f} Hz : écart-type {dev:.1f} dB "
                              f"(direct seul {devd:.1f} dB) · {len(sb['rows'])} réflexion(s), ordre ≤ "
                              f"{st.sbir_order}", 8) + 1.5
    zones = data["zones"]
    shown = [z for z in zones if data["zone_vis"].get(z.key)]
    if zones:
        npan = sum(len(p["rects"]) for p in data["plans"].values())
        placed = any(p["placed"] for p in data["plans"].values())
        txt = f"Traitement : {npan} panneau(x) {'posé(s)' if placed else 'prévu(s)'}"
        if shown:
            txt += f" · {len(shown)} zone(s) minimale(s), {sum(z.w * z.h for z in shown):.2f} m²"
        if data["traps"]:
            txt += f" · {len(data['traps'])} bass trap(s)"
        y = doc.para(x, y, w, txt, 8, bold=True) + 1.5
    doc.top = max(doc.top, y0 + 106)
    # enceintes
    objs = _speakers(data)
    if objs:
        rows = []
        for o in objs:
            m = sc.model(getattr(o, "model", ""))
            rows.append([o.name, m.name if m else "", fmt_len(o.x, units), fmt_len(o.y, units), fmt_len(o.z, units),
                         f"{getattr(o, 'az', 0):.1f}°", f"{getattr(o, 'el', 0):.1f}°"])
        doc.table(["Enceinte", "Modèle", f"X ({units})", f"Y ({units})", f"Z ({units})", "Azimut", "Site"], rows,
                  [40, 55, 24, 24, 24, 20, 20], right_cols=(2, 3, 4, 5, 6), title="Enceintes analysées")
    if shown:
        rows = [[f"{z.abbr}", z.label, f"{fmt_len(z.w, units)} × {fmt_len(z.h, units)}", _zone_pos(z, units),
                 f"{z.level:+.1f} dB"] for z in shown]
        doc.table(["Repère", "Paroi", f"Zone minimale ({units})", "Position", "Niveau"], rows, [16, 34, 40, 120, 20],
                  bold_cols=(2, 3), right_cols=(4,), title="Zones minimales à traiter")
    rows = []
    for z in zones:
        p = data["plans"].get(z.key)
        if not p or not p["placed"] or not p["rects"]:
            continue
        R = np.array([r[:4] for r in p["rects"]], float)
        extra = f" · suspendus à {fmt_len(p['cfg'].get('drop', 0.0), units)}" if z.kind == "ceiling" else ""
        rows.append([z.abbr, z.label, str(len(R)), f"{fmt_len(R[0, 2], units)} × {fmt_len(R[0, 3], units)} × "
                     f"{fmt_len(p['cfg']['t'], units)}", _block_pos(z, R, units) + extra])
    if rows:
        doc.table(["Repère", "Paroi", "Qté", f"Panneau ({units})", "Bloc"], rows, [16, 34, 12, 42, 126],
                  bold_cols=(3,), right_cols=(2,), title="Panneaux posés")


def _block_pos(z, R, units):
    bu, bv = R[:, 0].min(), R[:, 1].min()
    bw, bh = (R[:, 0] + R[:, 2]).max() - bu, (R[:, 1] + R[:, 3]).max() - bv
    if z.kind == "wall":
        return (f"{fmt_len(bw, units)} × {fmt_len(bh, units)} · à {fmt_len(bu, units)} du coin gauche, "
                f"{fmt_len(bv, units)} du sol")
    return f"{fmt_len(bw, units)} × {fmt_len(bh, units)} · X {fmt_len(bu, units)} · Y {fmt_len(bv, units)}"


def _speakers(data):
    ctx = data["ctx"] or data["tctx"]
    sc = data["scene"]
    if ctx is None:
        return []
    ids = []
    for s in ctx["sources"]:
        if s.owner not in ids:
            ids.append(s.owner)
    return [o for o in (sc.obj(i) for i in ids) if o is not None]


def _zone_pos(z, units):
    """Position de la zone : depuis le coin gauche et le sol (mur), ou depuis le coin X min / Y min."""
    u0, v0, u1, v1 = z.rect
    if z.kind == "wall":
        return (f"à {fmt_len(u0, units)} du coin gauche · de {fmt_len(v0, units)} à {fmt_len(v1, units)} du sol")
    return (f"X {fmt_len(u0, units)} → {fmt_len(u1, units)} · Y {fmt_len(v0, units)} → {fmt_len(v1, units)}"
            f" (depuis le coin)")


# --------------------------------------------------------------------------- SBIR
def _page_sbir(doc, data):
    sc = data["scene"]
    st = sc.settings
    sb = data["sbir"]
    f, H, Hd = sb["freqs"], sb["H"], sb["Hd"]
    frac = SB.SMOOTH.get(st.sbir_smooth, 0)
    tot = SB.smooth_db(f, np.abs(H) ** 2, frac)
    dr = SB.smooth_db(f, np.abs(Hd) ** 2, frac)
    ref = float(np.median(dr))
    tot, dr = tot - ref, dr - ref
    x0, y0, w, h = doc.M + 12, doc.top + 2, doc.W - 2 * doc.M - 14, 92
    fmin, fmax = float(f[0]), float(f[-1])
    ymin, ymax = -24.0, 12.0

    def X(fr):
        return x0 + (math.log10(fr) - math.log10(fmin)) / (math.log10(fmax) - math.log10(fmin)) * w

    def Y(db):
        return y0 + (ymax - min(max(db, ymin), ymax)) / (ymax - ymin) * h

    lo, hi = max(st.sbir_band_lo, fmin), min(st.sbir_band_hi, fmax)
    if hi > lo:
        doc.p.fillRect(QtCore.QRectF(X(lo) * doc.k, y0 * doc.k, (X(hi) - X(lo)) * doc.k, h * doc.k),
                       QtGui.QColor(0, 0, 0, 12))
    for dec in (1, 10, 100, 1000, 10000):
        for m in range(1, 10):
            fr = dec * m
            if fmin <= fr <= fmax:
                doc.line(X(fr), y0, X(fr), y0 + h, 0.12 if m == 1 else 0.06, LIGHT)
                if m in (1, 2, 5):
                    doc.text(X(fr), y0 + h + 3.5, f"{fr // 1000}k" if fr >= 1000 else str(fr), 6.5, False,
                             DIM_INK, "center")
    for db in range(int(ymin), int(ymax) + 1, 6):
        doc.line(x0, Y(db), x0 + w, Y(db), 0.12 if db == 0 else 0.06, LIGHT)
        doc.text(x0 - 1.5, Y(db), f"{db:+d}" if db else "0", 6.5, False, DIM_INK, "right", valign="middle")
    doc.text(x0 + w, y0 + h + 8, "fréquence (Hz)", 6.5, False, DIM_INK, "right")
    doc.text(x0 - 9, y0 + h / 2, "niveau (dB)", 6.5, False, DIM_INK, "center", -90)
    seen = set()
    for r in sb["rows"]:
        key = (r["cat"], r["src"].owner)
        if r["order"] != 1 or key in seen or not (fmin <= r["notch"] <= fmax) or r["rel"] < -20:
            continue
        seen.add(key)
        doc.line(X(r["notch"]), y0, X(r["notch"]), y0 + h, 0.2, QtGui.QColor(SB.CAT_COLORS.get(r["cat"], "#888")),
                 Qt.PenStyle.DotLine)
    doc.polyline([(X(a), Y(b)) for a, b in zip(f, dr)], 0.25, DIM_INK, style=Qt.PenStyle.DashLine)
    doc.polyline([(X(a), Y(b)) for a, b in zip(f, tot)], 0.45, ACCENT)
    doc.rect(x0, y0, w, h, 0.2, DIM_INK)
    ly = y0 + 4
    doc.line(x0 + 3, ly, x0 + 9, ly, 0.45, ACCENT); doc.text(x0 + 10.5, ly, "total", 6.5, valign="middle")
    doc.line(x0 + 24, ly, x0 + 30, ly, 0.25, DIM_INK, Qt.PenStyle.DashLine)
    doc.text(x0 + 31.5, ly, "direct seul", 6.5, valign="middle")
    xx = x0 + 52
    for k in ("front", "side", "floor", "ceiling", "rear"):
        doc.line(xx, ly - 1.5, xx, ly + 1.5, 0.4, QtGui.QColor(SB.CAT_COLORS[k]))
        xx += doc.text(xx + 1.5, ly, SB.CATS[k].lower(), 6.5, valign="middle") + 6
    doc.top = y0 + h + 11
    dev = SB.flatness(f, H, st.sbir_band_lo, st.sbir_band_hi)
    devd = SB.flatness(f, Hd, st.sbir_band_lo, st.sbir_band_hi)
    doc.text(doc.M, doc.top, f"{sb['nsrc']} source(s) · lissage {st.sbir_smooth} · ordre ≤ {st.sbir_order} · "
                             f"écart-type {st.sbir_band_lo:.0f}–{st.sbir_band_hi:.0f} Hz : {dev:.1f} dB "
                             f"(direct seul {devd:.1f} dB)", 7.5, True)
    doc.top += 4
    rows = []
    for r in sb["rows"][:40]:
        lab = SB.CATS.get(r["cat"], r["cat"]) if r["order"] == 1 else f"{r['order']}× · {r['chain']}"
        rows.append([r["src"].name, lab, f"{r['delta']:.2f} m", f"{r['dt']:.2f} ms", f"{r['notch']:.0f} Hz",
                     f"{r['rel']:+.1f} dB"])
    doc.table(["Source", "Paroi(s)", "Δ trajet", "Δt", "1er creux", "rel."], rows, [55, 110, 24, 24, 26, 22],
              right_cols=(2, 3, 4, 5), title="Réflexions (par écart de trajet)")


# --------------------------------------------------------------------------- plan
def _plan_items(data):
    """Éléments à dessiner en plan : pièces, objets (hors panneaux), panneaux, enceintes, écouteur."""
    sc = data["scene"]
    _, tids = T.treatment_ids(sc)
    rooms = _rooms(sc)
    objs = [s for s in sc.shapes if s.kind != "Pièce" and s.id not in tids]
    panels = [s for s in sc.shapes if s.id in tids and getattr(s, "role", "") != "bass_trap"]
    return rooms, objs, panels


def _page_plan(doc, data):
    sc, units = data["scene"], data["units"]
    rooms, objs, panels = _plan_items(data)
    if rooms:
        P = np.vstack([f.verts for r in rooms for f in r.faces()])
    else:
        P = np.vstack([s.corners() for s in sc.shapes]) if sc.shapes else np.array([[-5, -5, 0], [5, 5, 3]])
    lo, hi = P.min(0), P.max(0)
    box = (doc.M, doc.top, 192, doc.H - doc.top - 14)
    fr = Frame(doc, box, lo[:2], hi[:2], margin=18)
    for r in rooms:
        for a, b in _seg_pairs(r.faces()):
            fr.seg(a, b, 0.6, INK)
    for s in objs:
        for a, b in _seg_pairs(s.faces()):
            fr.seg(a, b, 0.2, OBJ_INK)
    zmid = (lo[2] + hi[2]) / 2
    for s in panels:
        V = np.vstack([f.verts for f in s.faces()])
        Hh = _hull(V[:, :2])
        if V[:, 2].min() > zmid:                 # plafond : contour en tirets
            fr.poly(Hh, 0.25, ACCENT, style=Qt.PenStyle.DashLine)
        else:
            fr.poly(Hh, 0.2, ACCENT, fill=PANEL_FILL)
            fr.poly(Hh, 0.25, ACCENT)
    for s in data["traps"]:                       # bass traps : hachurés
        V = np.vstack([f.verts for f in s.faces()])
        Hh = _hull(V[:, :2])
        doc.p.setBrush(QtGui.QBrush(QtGui.QColor("#6b4f9e"), Qt.BrushStyle.BDiagPattern))
        doc.p.setPen(doc.pen(0.3, QtGui.QColor("#6b4f9e")))
        doc.p.drawPolygon(QtGui.QPolygonF([doc.q(*fr.pt(a, b)) for a, b in Hh]))
        c = V.mean(0)
        fr.text(c[0], c[1], s.name, 6, True, QtGui.QColor("#6b4f9e"))
    for z in data["zones"]:
        if not data["zone_vis"].get(z.key):
            continue
        u0, v0, u1, v1 = z.rect
        C = z.to3([[u0, v0], [u1, v0], [u1, v1], [u0, v1]])
        if z.kind == "wall":
            A, B = C[0], C[1]
            fr.seg(A, B, 1.2, ZONE)
            m = (A + B) / 2 + z.n_in * 0.0
            off = z.n_in[:2] * (7.0 / fr.s)
            fr.text(m[0] + off[0], m[1] + off[1], f"{z.abbr} {fmt_len(z.w, units)}", 6.5, True, ZONE)
        else:
            fr.poly(C[:, :2], 0.5 if z.kind == "ceiling" else 0.7, ZONE,
                    style=Qt.PenStyle.DashLine if z.kind == "ceiling" else Qt.PenStyle.SolidLine)
    # enceintes
    for o in _speakers(data) or [o for o in sc.objects]:
        V = [f.verts for box_ in sc.bodies.get(o.id, []) for f in box_]
        if V:
            H2 = _hull(np.vstack(V)[:, :2])
            fr.poly(H2, 0.25, INK, fill=SPK_FILL)
            fr.poly(H2, 0.25, INK)
        q = fr.pt(o.x, o.y)
        doc.text(q[0] + 3, q[1] - 3, o.name, 6.5, True)
    ctx = data["ctx"] or data["tctx"]
    L = ctx["listener"] if ctx is not None else (sc.listeners[0].pos if sc.listeners else None)
    if L is not None:
        q = fr.pt(L[0], L[1])
        doc.circle(q[0], q[1], 2.2, 0.3, INK, "#ffffff")
        doc.line(q[0] - 3, q[1], q[0] + 3, q[1], 0.15); doc.line(q[0], q[1] - 3, q[0], q[1] + 3, 0.15)
        name = ctx["listener_obj"].name if ctx is not None else sc.listeners[0].name
        doc.text(q[0] + 3, q[1] + 5, name, 6.5, True)
    # cotes
    x0, y0, x1, y1 = lo[0], lo[1], hi[0], hi[1]
    fr.dim((x0, y0), (x1, y0), -9, fmt_len(x1 - x0, units), 7, INK, True)
    fr.dim((x0, y1), (x0, y0), -9, fmt_len(y1 - y0, units), 7, INK, True)
    if L is not None:
        fr.dim((x0, L[1]), (L[0], L[1]), 2.5, fmt_len(L[0] - x0, units), 6.5, DIM_INK)
        fr.dim((L[0], y0), (L[0], L[1]), 2.5, fmt_len(L[1] - y0, units), 6.5, DIM_INK)
    for o in _speakers(data):
        yy = o.y
        fr.dim((x0, yy), (o.x, yy), -2.5, fmt_len(o.x - x0, units), 6.0, DIM_INK)
        if yy - y0 < y1 - yy:
            fr.dim((o.x, y0), (o.x, yy), -2.5, fmt_len(yy - y0, units), 6.0, DIM_INK)
        else:
            fr.dim((o.x, yy), (o.x, y1), -2.5, fmt_len(y1 - yy, units), 6.0, DIM_INK)
    fr.scale_note(units)
    # tableau des positions
    doc.top = box[1] + 2
    X0 = doc.M + 196
    rows = []
    if L is not None:
        rows.append(["Écoute", fmt_len(L[0] - x0, units), fmt_len(L[1] - y0, units), fmt_len(L[2] - lo[2], units)])
    for o in _speakers(data):
        rows.append([o.name, fmt_len(o.x - x0, units), fmt_len(o.y - y0, units), fmt_len(o.z - lo[2], units)])
    for s in data["traps"]:
        q = s.corners().min(0)
        rows.append([s.name + " (bass trap)", fmt_len(q[0] - x0, units), fmt_len(q[1] - y0, units),
                     fmt_len(q[2] - lo[2], units)])
    for a in sc.assemblies:
        if a.parent or a.id == sc.settings.treat_assembly:
            continue
        shs = sc.all_shapes_in(a.id)
        if shs:
            Q = np.vstack([s.corners() for s in shs])
            rows.append([a.name + " (coin min)", fmt_len(Q[:, 0].min() - x0, units), fmt_len(Q[:, 1].min() - y0, units),
                         fmt_len(Q[:, 2].min() - lo[2], units)])
    doc.table(["Élément", "X", "Y", "Z"], rows, [35, 14, 14, 14], x=X0, size=6.5, right_cols=(1, 2, 3))
    doc.para(X0, doc.top, 77, f"Cotes en {units}, depuis le coin X min / Y min de la pièce "
                              f"({x0:.3f}, {y0:.3f}) et depuis le sol. Trait jaune épais : zone minimale à traiter "
                              f"(tirets : plafond). Orange : panneaux (tirets : plafond). Violet hachuré : bass traps.",
             6.5, DIM_INK)


# --------------------------------------------------------------------------- élévations
def _elevation(doc, data, z, box):
    sc, units = data["scene"], data["units"]
    x, y, w, h = box
    plan = data["plans"].get(z.key)
    vis = data["zone_vis"].get(z.key, False)
    view = "vue de l'intérieur" if z.kind == "wall" else "vue en plan (depuis le dessus)"
    doc.text(x, y + 4, f"{z.abbr} · {z.label} — {view}", 8.5, True)
    if vis:
        doc.text(x + w, y + 4, f"zone minimale {fmt_len(z.w, units)} × {fmt_len(z.h, units)} {units} · "
                               f"{_zone_pos(z, units)}", 7.5, True, ZONE, "right")
    elif plan and plan["rects"]:
        R = np.array([r[:4] for r in plan["rects"]], float)
        doc.text(x + w, y + 4, f"bloc de panneaux {_block_pos(z, R, units)} {units}", 7.5, True, ACCENT, "right")
    fr = Frame(doc, (x, y + 6, w, h - 8), (0, 0), (z.W, z.H), margin=16)
    fr.poly(z.poly, 0.5, INK)
    if z.kind != "wall":                     # repères au sol / plafond
        rooms, objs, _ = _plan_items(data)
        for s in objs:
            for a, b in _seg_pairs(s.faces()):
                fr.seg(a[:2] - z.O[:2], b[:2] - z.O[:2], 0.12, LIGHT)
        for o in _speakers(data):
            V = [f.verts for box_ in sc.bodies.get(o.id, []) for f in box_]
            if V:
                fr.poly(_hull(np.vstack(V)[:, :2] - z.O[:2]), 0.15, LIGHT)
        ctx = data["ctx"] or data["tctx"]
        if ctx is not None:
            L = ctx["listener"] - z.O
            q = fr.pt(L[0], L[1]); doc.circle(q[0], q[1], 1.5, 0.2, LIGHT)
    else:
        doc.text(fr.pt(0, 0)[0] + 1, fr.pt(0, 0)[1] - 1.2, "sol", 6, False, LIGHT)
    if vis and z.pts is not None and len(z.pts):
        dot = QtGui.QColor(ZONE); dot.setAlpha(90)
        for p in z.pts[:: max(1, len(z.pts) // 200)]:
            q = fr.pt(*p)
            doc.circle(q[0], q[1], 0.18, 0, dot, dot)
    u0, v0, u1, v1 = z.rect
    if plan:
        for r in plan["rects"]:
            pu, pv, pw, ph = r[:4]
            fr.poly([(pu, pv), (pu + pw, pv), (pu + pw, pv + ph), (pu, pv + ph)], 0.3, ACCENT, fill=PANEL_FILL)
            fr.poly([(pu, pv), (pu + pw, pv), (pu + pw, pv + ph), (pu, pv + ph)], 0.3, ACCENT)
            if pw * fr.s > 14 and ph * fr.s > 5:
                fr.text(pu + pw / 2, pv + ph / 2, r[4] if len(r) > 4 else "", 5.5, False, ACCENT)
    # cotes de la paroi
    fr.dim((0, 0), (z.W, 0), -9, fmt_len(z.W, units), 7, INK, True)
    fr.dim((0, z.H), (0, 0), -9, fmt_len(z.H, units), 7, INK, True)
    if vis:                                  # zone minimale (en haut / à droite), en gras
        fr.poly([(u0, v0), (u1, v0), (u1, v1), (u0, v1)], 0.9, ZONE)
        if u0 > 1e-4:
            fr.dim((0, v1), (u0, v1), 4, fmt_len(u0, units), 6.5, ZONE, True)
        fr.dim((u0, v1), (u1, v1), 4, fmt_len(u1 - u0, units), 6.5, ZONE, True)
        if v0 > 1e-4:
            fr.dim((u1, 0), (u1, v0), -4, fmt_len(v0, units), 6.5, ZONE, True)
        fr.dim((u1, v0), (u1, v1), -4, fmt_len(v1 - v0, units), 6.5, ZONE, True)
    # panneaux : bloc (en bas / à gauche)
    if plan and plan["rects"]:
        R = np.array([r[:4] for r in plan["rects"]], float)
        bu, bv = R[:, 0].min(), R[:, 1].min()
        bu1, bv1 = (R[:, 0] + R[:, 2]).max(), (R[:, 1] + R[:, 3]).max()
        if bu > 1e-4:
            fr.dim((0, bv), (bu, bv), -4, fmt_len(bu, units), 6.0, ACCENT)
        xs = sorted(set(np.round(np.concatenate([R[:, 0], R[:, 0] + R[:, 2]]), 6)))
        for a, b in zip(xs[:-1], xs[1:]):
            fr.dim((a, bv), (b, bv), -4, fmt_len(b - a, units), 6.0, ACCENT)
        if bv > 1e-4:
            fr.dim((bu, bv), (bu, 0), -4, fmt_len(bv, units), 6.0, ACCENT)
        ys = sorted(set(np.round(np.concatenate([R[:, 1], R[:, 1] + R[:, 3]]), 6)))
        for a, b in zip(ys[:-1], ys[1:]):
            fr.dim((bu, b), (bu, a), -4, fmt_len(b - a, units), 6.0, ACCENT)
        n = len(R)
        t = plan["cfg"]["t"]
        hang = ""
        if z.kind == "ceiling":
            hang = f" · suspendus : dessus à {fmt_len(plan['cfg'].get('drop', 0.0), units)} sous le plafond"
        doc.text(x, y + h - 1, f"{n} panneau(x) {fmt_len(R[0, 2], units)} × {fmt_len(R[0, 3], units)} × "
                               f"{fmt_len(t, units)} {units} · bloc {fmt_len(bu1 - bu, units)} × "
                               f"{fmt_len(bv1 - bv, units)} · {'posés' if plan['placed'] else 'prévus'}{hang}",
                 7, True, ACCENT)
    elif plan is None:
        doc.text(x, y + h - 1, "Zone non traitée", 7, False, DIM_INK)
    fr.scale_note(units)


def _panel_list(doc, data):
    units = data["units"]
    rows = []
    total, area = 0, 0.0
    for z in data["zones"]:
        plan = data["plans"].get(z.key)
        if not plan:
            continue
        t = plan["cfg"]["t"]
        for i, r in enumerate(plan["rects"]):
            pu, pv, pw, ph = r[:4]
            name = r[4] if len(r) > 4 else f"{z.abbr}-{i + 1}"
            if z.kind == "wall":
                p1, p2 = f"u {fmt_len(pu, units)}", f"v {fmt_len(pv, units)}"
            else:
                p1, p2 = f"X {fmt_len(pu, units)}", f"Y {fmt_len(pv, units)}"
            hang = fmt_len(plan["cfg"].get("drop", 0.0), units) if z.kind == "ceiling" else ""
            rows.append([name, z.label, f"{fmt_len(pw, units)} × {fmt_len(ph, units)} × {fmt_len(t, units)}", p1, p2,
                         hang, "posé" if plan["placed"] else "prévu"])
            total += 1
            area += pw * ph
    if rows:
        doc.table(["Repère", "Paroi", f"Dimensions L × H × ép. ({units})", "Position (gauche / X)",
                   "Position (bas / Y)", "Suspension", "État"], rows, [24, 40, 58, 42, 42, 24, 20], bold_cols=(2,))
        doc.para(doc.M, doc.top, doc.W - 2 * doc.M,
                 f"{total} panneau(x) · {area:.2f} m² · absorption {data['scene'].settings.treat_alpha:.2f} · positions du "
                 "coin bas gauche de chaque panneau (mur vu de l'intérieur), ou depuis le coin X min / Y min de la "
                 "pièce au sol / plafond. Suspension : distance entre le plafond et le dessus du panneau.", 7.5,
                 bold=True)
        doc.top += 10
    traps = data["traps"]
    if traps:
        sc = data["scene"]
        rooms = _rooms(sc)
        P = np.vstack([f.verts for r in rooms for f in r.faces()]) if rooms else np.zeros((1, 3))
        o = P.min(0)
        trows = []
        for s in traps:
            Q = s.outline()
            e = Q.max(0) - Q.min(0)
            q = s.corners().min(0) - o
            trows.append([s.name, f"{len(s.profile)} pts" + (" · arc" if any(abs(a) > 1e-9 for a in s.arcs) else ""),
                          f"{fmt_len(e[0], units)} × {fmt_len(e[1], units)}", fmt_len(s.height, units),
                          f"X {fmt_len(q[0], units)} · Y {fmt_len(q[1], units)} · Z {fmt_len(q[2], units)}",
                          f"{s.absorption:.2f}"])
        doc.table(["Bass trap", "Profil", f"Encombrement ({units})", "Hauteur", "Coin min (depuis l'origine)", "α"],
                  trows, [30, 30, 40, 22, 90, 14], bold_cols=(2,), right_cols=(3, 5), title="Bass traps")


# =========================================================================== plans de découpe
class CutlistDialog(QtWidgets.QDialog):
    def __init__(self, parent, scene, default_id, units):
        super().__init__(parent)
        self.setWindowTitle("Plans de découpe")
        no_enter_dialog(self)
        lay = QtWidgets.QFormLayout(self)
        self.asm = NoWheelCombo()
        for a in scene.assemblies:
            if a.id == scene.settings.treat_assembly:
                continue
            depth = len(scene.ancestors(a.id))
            self.asm.addItem("    " * depth + a.name, a.id)
        i = self.asm.findData(default_id)
        if i < 0:
            i = next((k for k in range(self.asm.count()) if self.asm.itemText(k).strip().lower() == "bureau"), 0)
        self.asm.setCurrentIndex(max(i, 0))
        lay.addRow("Ensemble", self.asm)
        self.units = NoWheelCombo(); self.units.addItems(["mm", "cm", "m"]); self.units.setCurrentText(units)
        lay.addRow("Unités", self.units)
        hb = QtWidgets.QHBoxLayout()
        bc = QtWidgets.QPushButton("Annuler"); bc.clicked.connect(self.reject)
        bo = QtWidgets.QPushButton("Exporter le PDF…"); bo.setObjectName("primary"); bo.clicked.connect(self.accept)
        hb.addWidget(bc); hb.addWidget(bo)
        lay.addRow(hb)


def export_cutlist(app, path=None, aid=None, units=None):
    sc = app.scene
    cands = [a for a in sc.assemblies if a.id != sc.settings.treat_assembly]
    if not cands:
        QtWidgets.QMessageBox.information(app, "Plans de découpe",
                                          "Aucun ensemble : regroupez d'abord les pièces du bureau (Ctrl+G).")
        return None
    if aid is None:
        kind, obj = sc.find(app.sel) if app.sel else (None, None)
        default = obj.id if kind == "assembly" else (obj.assembly if kind == "shape" else "")
        dlg = CutlistDialog(app, sc, default, sc.settings.pdf_units)
        if not dlg.exec():
            return None
        aid = dlg.asm.currentData()
        units = dlg.units.currentText()
        sc.settings.pdf_units = units

    a = sc.assembly(aid)
    if path is None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(app, "Exporter les plans de découpe",
                                                        f"decoupe_{a.name}.pdf", "PDF (*.pdf)")
        if not path:
            return None
    write_cutlist(path, sc, a, units or sc.settings.pdf_units)
    if hasattr(app, "status"):
        app.status.setText(f"PDF exporté : {path}")
    return path


def write_cutlist(path, scene, asm, units="mm", sheet=None, kerf=None, rotate=None):
    from .cutlist import write_cutlist as wc
    st = scene.settings
    return wc(path, scene, asm, units, sheet or st.cut_sheet, st.cut_kerf if kerf is None else kerf,
              st.cut_rotate if rotate is None else rotate)
