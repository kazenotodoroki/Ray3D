"""Vues : 3D (orbite ou balade), dessus (XY) et côté (XZ)."""
from __future__ import annotations

import math
import time

import numpy as np
import pyqtgraph as pg
import pyqtgraph.opengl as gl
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from . import style as S
from . import geometry as G
from .model import Scene


def qcolor(h, a=255):
    c = QtGui.QColor(h)
    c.setAlpha(int(max(0, min(255, a))))
    return c


def nan_join(segs):
    if not segs:
        return np.array([]), np.array([])
    parts = []
    for s in segs:
        parts.append(np.asarray(s, float))
        parts.append(np.full((1, 2), np.nan))
    a = np.vstack(parts)
    return a[:, 0], a[:, 1]


from OpenGL import GL as _GL

# cônes : toujours visibles, même sous la carte SPL ou derrière une surface
OVERLAY = {_GL.GL_DEPTH_TEST: False, _GL.GL_BLEND: True, _GL.GL_CULL_FACE: False,
           "glBlendFunc": (_GL.GL_SRC_ALPHA, _GL.GL_ONE_MINUS_SRC_ALPHA)}


class SeeThroughMesh(gl.GLMeshItem):
    """Maillage translucide qui n'écrit pas dans le tampon de profondeur : il ne masque pas ce qui est
    derrière lui (enceintes dans la pièce vues de l'extérieur, etc.)."""

    def paint(self):
        _GL.glDepthMask(_GL.GL_FALSE)
        try:
            super().paint()
        finally:
            _GL.glDepthMask(_GL.GL_TRUE)


# murs de pièce : on n'affiche que les faces vues de l'intérieur → vue de l'extérieur, les murs
# proches de la caméra disparaissent (vue « maison de poupée »)
ROOM_OPTS = {_GL.GL_DEPTH_TEST: True, _GL.GL_BLEND: True, _GL.GL_CULL_FACE: True,
             "glCullFace": (_GL.GL_FRONT,), "glBlendFunc": (_GL.GL_SRC_ALPHA, _GL.GL_ONE_MINUS_SRC_ALPHA)}


def oriented_mesh(faces):
    """Maillage dont chaque triangle est tourné dans le sens de la normale extérieure de sa face."""
    V, F = [], []
    k = 0
    for f in faces:
        v = f.verts
        V.append(v)
        for a, b, c in f.tris:
            if np.cross(v[b] - v[a], v[c] - v[a]) @ f.normal < 0:
                b, c = c, b
            F.append((k + a, k + b, k + c))
        k += len(v)
    if not V:
        return np.zeros((0, 3)), np.zeros((0, 3), int)
    return np.vstack(V), np.array(F, int)


def is_on(s, sel):
    return s.owner in sel or s.group in sel or s.id in sel


# --------------------------------------------------------------------------- vue 2D
class View2D(pg.PlotWidget):
    sigMoved = QtCore.Signal(str, str, float, float)   # type, id, a, b
    sigSection = QtCore.Signal(float)

    def __init__(self, plane: str):
        super().__init__()
        self.plane = plane
        self.ax = (0, 1) if plane == "xy" else (0, 2)
        self.vdir = np.array([0, 0, 1.0]) if plane == "xy" else np.array([0, 1.0, 0])
        self.setBackground(S.BG)
        pi = self.getPlotItem()
        pi.hideButtons(); pi.setMenuEnabled(False)
        self.setAspectLocked(True)
        pi.showGrid(x=True, y=True, alpha=0.08)
        for name in ("left", "bottom"):
            a = pi.getAxis(name)
            a.setPen(pg.mkPen(S.BORDER)); a.setTextPen(pg.mkPen(S.DIM)); a.setStyle(tickLength=-4)
            a.enableAutoSIPrefix(False)
        pi.getAxis("bottom").setLabel("X (m)", color=S.DIM)
        pi.getAxis("left").setLabel("Y (m)" if plane == "xy" else "Z (m)", color=S.DIM)
        self._items = []
        self._fitted = False

    def P(self, pts):
        return np.asarray(pts, float)[..., list(self.ax)]

    def _add(self, it, z=0):
        it.setZValue(z)
        self.getPlotItem().addItem(it)
        self._items.append(it)
        return it

    def _lines(self, segs, color, alpha=255, width=1.0, z=0, style=Qt.PenStyle.SolidLine):
        if not segs:
            return
        x, y = nan_join(segs)
        self._add(pg.PlotDataItem(x, y, connect="finite", antialias=True,
                                  pen=pg.mkPen(qcolor(color, alpha), width=width, style=style)), z)

    def _polygon(self, pts2, color, alpha, z=0, edge=None, edge_alpha=200):
        if len(pts2) < 3:
            return
        poly = QtWidgets.QGraphicsPolygonItem(QtGui.QPolygonF([QtCore.QPointF(float(p[0]), float(p[1])) for p in pts2]))
        poly.setBrush(pg.mkBrush(qcolor(color, alpha)))
        poly.setPen(pg.mkPen(qcolor(edge, edge_alpha), width=1) if edge else pg.mkPen(None))
        self._add(poly, z)

    def _target(self, xy, color, kind, oid, label, symbol="s", size=10, sel=False, movable=True):
        t = pg.TargetItem(pos=(float(xy[0]), float(xy[1])), size=size + (3 if sel else 0), symbol=symbol,
                          pen=pg.mkPen("#ffffff" if sel else color, width=1.5),
                          brush=pg.mkBrush(qcolor(color, 140)),
                          hoverPen=pg.mkPen("#ffffff", width=2), hoverBrush=pg.mkBrush(qcolor(color, 230)),
                          movable=movable, label=label,
                          labelOpts=dict(color=qcolor(S.TEXT if sel else S.DIM), offset=(8, -8), anchor=(0, 1)))
        t.sigPositionChangeFinished.connect(
            lambda it, k=kind, i=oid: self.sigMoved.emit(k, i, float(it.pos().x()), float(it.pos().y())))
        self._add(t, 50)

    def _faces(self, faces, fill, alpha, edge, edge_alpha, z, width=1.0):
        segs = []
        for f in faces:
            v = self.P(f.verts)
            segs.append(np.vstack([v, v[:1]]))
            if fill and abs(f.normal @ self.vdir) > 0.3:
                self._polygon(v, fill, alpha, z - 1)
        self._lines(segs, edge, edge_alpha, width, z)

    def fit(self, scene: Scene):
        lo, hi = scene.bbox()
        a, b = self.ax
        self.getPlotItem().getViewBox().setRange(xRange=(lo[a] - 1, hi[a] + 1), yRange=(lo[b] - 1, hi[b] + 1),
                                                 padding=0.02)

    def render(self, scene: Scene, res: dict, sel: set):
        pi = self.getPlotItem()
        for it in self._items:
            pi.removeItem(it)
        self._items = []
        st = scene.settings
        vmin, vmax = res["range"]

        # --- cartes SPL
        if self.plane == "xy":
            for m in res["maps"]:
                if abs(np.cross(m["U"], m["V"])[2]) < 1e-6:
                    continue
                rgba = S.colorize((m["db"] - vmin) / max(vmax - vmin, 1e-6), 235)
                img = pg.ImageItem(rgba)
                O, U, V = self.P(m["O"]), self.P(m["U"]), self.P(m["V"])
                img.setTransform(QtGui.QTransform(U[0] / m["nu"], U[1] / m["nu"], V[0] / m["nv"], V[1] / m["nv"],
                                                  O[0], O[1]))
                self._add(img, -20 + 0.01 * float(m["O"][2]))
        elif res["section"] is not None:
            sec = res["section"]
            img = pg.ImageItem(S.colorize((sec["db"] - vmin) / max(vmax - vmin, 1e-6), 215))
            img.setRect(QtCore.QRectF(sec["x0"], sec["z0"], sec["w"], sec["h"]))
            self._add(img, -20)

        # --- formes
        for sh in scene.shapes:
            on = sh.id in sel
            fill = None if sh.kind == "Pièce" else S.SHAPE
            self._faces(sh.faces(), fill, 22, "#ffffff" if on else S.SHAPE,
                        230 if on else (150 if sh.kind == "Pièce" else 110), -5, 1.6 if on else 1.0)

        # --- coupe
        if self.plane == "xy" and st.show_section and st.show_spl:
            line = pg.InfiniteLine(pos=st.section_y, angle=0, movable=True,
                                   pen=pg.mkPen(qcolor(S.ACCENT, 160), width=1, style=Qt.PenStyle.DashLine),
                                   hoverPen=pg.mkPen(S.ACCENT, width=2),
                                   label="coupe", labelOpts=dict(color=S.ACCENT, position=0.06))
            line.sigPositionChangeFinished.connect(lambda it: self.sigSection.emit(float(it.value())))
            self._add(line, 40)

        # --- rayons
        R = res.get("rays")
        if R is not None and len(R["p0"]):
            for order in range(int(R["order"].max()) + 1):
                m = R["order"] == order
                if m.any():
                    segs = np.stack([self.P(R["p0"][m]), self.P(R["p1"][m])], 1)
                    col = S.ORDER_COLORS[min(order, len(S.ORDER_COLORS) - 1)]
                    self._lines(list(segs), col, 55 if order == 0 else max(14, 45 - 12 * order), 1.0, z=5)

        # --- cônes de couverture
        e_idx = (0, 24) if self.plane == "xy" else (12, 36)
        for sid, cn in res["cones"].items():
            s = res["src_by_id"][sid]
            col = scene.color_of(s)
            on = is_on(s, sel)
            self._lines([self.P(np.array([s.pos, cn["axis"]]))], col, 200 if on else 90, 1.0, z=8,
                        style=Qt.PenStyle.DashLine)
            ring = cn["ring"]
            if ring is None:
                continue
            pts = self.P(np.vstack([s.pos[None], ring]))
            ca = st.cone_alpha
            self._polygon(G.hull2d(pts), col, int(255 * min(0.6, ca * (1.6 if on else 0.6))), z=7)
            self._lines([self.P(np.array([s.pos, ring[i]])) for i in e_idx], col, 220 if on else 110,
                        1.4 if on else 1.0, z=8)

        # --- réflexions vers l'écouteur
        by_order = {}
        for p in res.get("refl", []):
            if p["order"] > 0:
                by_order.setdefault((p["order"], p.get("color")), []).append(p)
        for (order, pcol), paths in by_order.items():
            col = pcol or S.ORDER_COLORS[min(order, len(S.ORDER_COLORS) - 1)]
            self._lines([self.P(np.array(p["pts"])) for p in paths], col, 160 if order == 1 else 100, 1.0, z=12)
            pts = self.P(np.vstack([np.array(p["pts"][1:-1]) for p in paths]))
            self._add(pg.ScatterPlotItem(pts[:, 0], pts[:, 1], size=5, pen=None, brush=pg.mkBrush(qcolor(col, 220))), 13)

        # --- enceintes
        for o in scene.objects:
            g = scene.group(o.group)
            col = g.color if g else "#cccccc"
            on = o.id in sel or o.group in sel
            for box in scene.bodies.get(o.id, []):
                self._faces(box, col, 150 if on else 95, "#ffffff" if on else "#000000", 200, 20)
            sym = {"speaker": "s", "array": "t1", "row": "t1"}[o.TYPE]
            lab = o.name + ("  ⇋" if o.mirror_of else "") + ("  🔒" if o.locked else "") + ("  (mute)" if o.mute else "")
            self._target(self.P(o.pos), col, "object", o.id, lab, symbol=sym, size=10, sel=on, movable=not o.locked)

        # --- coins de l'élément sélectionné et repères d'accrochage
        C = res.get("corners")
        if C is not None and len(C):
            pc = self.P(C)
            self._add(pg.ScatterPlotItem(pc[:, 0], pc[:, 1], size=6, symbol="s", pen=pg.mkPen("#ffffff"),
                                         brush=pg.mkBrush(qcolor("#000000", 200))), 45)
            if len(C) <= 40:
                seen = {}
                for i, q in enumerate(pc):       # coins superposés dans cette vue : un seul texte
                    key = (round(float(q[0]), 3), round(float(q[1]), 3))
                    seen.setdefault(key, []).append(str(i + 1))
                for (x, y), labs in seen.items():
                    t = pg.TextItem(",".join(labs), color=qcolor("#ffffff", 200), anchor=(-0.15, 1.1))
                    f = t.textItem.font(); f.setPointSize(7); t.setFont(f)
                    t.setPos(x, y)
                    self._add(t, 46)
        for pos, col, lab in res.get("markers", []):
            q = self.P(np.asarray(pos)[None])[0]
            self._add(pg.ScatterPlotItem([q[0]], [q[1]], size=13, symbol="d", pen=pg.mkPen("#ffffff"),
                                         brush=pg.mkBrush(col)), 60)
            t = pg.TextItem(lab, color=col, anchor=(-0.2, -0.1)); t.setPos(float(q[0]), float(q[1]))
            self._add(t, 60)

        # --- écouteurs
        for l in scene.listeners:
            self._target(self.P(l.pos), "#e8e8e8", "listener", l.id, l.name, symbol="o", size=9,
                         sel=l.id in sel, movable=not getattr(l, "locked", False))

        if not self._fitted:
            self.fit(scene)
            self._fitted = True


# --------------------------------------------------------------------------- vue 3D
class View3D(gl.GLViewWidget):
    sigWalk = QtCore.Signal(bool)

    MOVE_KEYS = {Qt.Key.Key_W: (1, 0, 0), Qt.Key.Key_Z: (1, 0, 0), Qt.Key.Key_Up: (1, 0, 0),
                 Qt.Key.Key_S: (-1, 0, 0), Qt.Key.Key_Down: (-1, 0, 0),
                 Qt.Key.Key_A: (0, 1, 0), Qt.Key.Key_Q: (0, 1, 0), Qt.Key.Key_Left: (0, 1, 0),
                 Qt.Key.Key_D: (0, -1, 0), Qt.Key.Key_Right: (0, -1, 0),
                 Qt.Key.Key_E: (0, 0, 1), Qt.Key.Key_Space: (0, 0, 1), Qt.Key.Key_PageUp: (0, 0, 1),
                 Qt.Key.Key_C: (0, 0, -1), Qt.Key.Key_PageDown: (0, 0, -1)}

    def __init__(self):
        super().__init__()
        self.setBackgroundColor(S.BG)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._items = []
        self.grid = gl.GLGridItem(color=(255, 255, 255, 14))
        self.grid.setSize(120, 120)
        self.grid.setSpacing(1, 1)
        self.addItem(self.grid)
        self._fitted = False
        self.walk = False
        self.keys = set()
        self._t = time.perf_counter()
        self.wtimer = QtCore.QTimer(self, interval=16)
        self.wtimer.timeout.connect(self._step)
        self._last = None
        self._scene_size = 30.0

    # ------------------------------------------------------------------ navigation
    def set_walk(self, on: bool, eye=None):
        self.walk = on
        if on:
            if eye is None:      # départ au centre de l'orbite, à hauteur d'yeux
                cam = np.array(self.opts["center"], float)
                cam[:2] = np.clip(cam[:2], self._lo[:2] + 0.5, self._hi[:2] - 0.5)
                cam[2] = self._lo[2] + 1.7
            else:
                cam = np.asarray(eye, float)
            self.opts["center"] = pg.Vector(*cam)
            self.opts["distance"] = 0.05
            self.opts["fov"] = 75
            self.opts["elevation"] = max(min(self.opts["elevation"], 30), -30)
        else:
            self.opts["fov"] = 60
            self.keys.clear()
            self.wtimer.stop()
            f = self._forward()
            c = np.array(self.opts["center"])
            d = self._scene_size * 0.6
            self.opts["distance"] = d
            self.opts["center"] = pg.Vector(*(c + f * d))
        self.update()
        self.setFocus()
        self.sigWalk.emit(on)

    def _forward(self):
        az, el = math.radians(self.opts["azimuth"]), math.radians(self.opts["elevation"])
        return -np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])

    def _step(self):
        now = time.perf_counter()
        dt = min(now - self._t, 0.05)
        self._t = now
        if not self.keys:
            self.wtimer.stop()
            return
        az = math.radians(self.opts["azimuth"])
        fwd = -np.array([math.cos(az), math.sin(az), 0.0])
        left = np.array([-fwd[1], fwd[0], 0.0])
        v = np.zeros(3)
        for k in self.keys:
            a, b, c = self.MOVE_KEYS[k]
            v += a * fwd + b * left + c * np.array([0, 0, 1.0])
        speed = 4.0 * (3.0 if QtWidgets.QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier else 1.0)
        c = np.array(self.opts["center"]) + v * speed * dt
        self.opts["center"] = pg.Vector(*c)
        self.update()

    def keyPressEvent(self, ev):
        if self.walk and ev.key() in self.MOVE_KEYS and not ev.isAutoRepeat():
            self.keys.add(ev.key())
            self._t = time.perf_counter()
            if not self.wtimer.isActive():
                self.wtimer.start()
            ev.accept()
            return
        if ev.key() == Qt.Key.Key_Escape and self.walk:
            self.set_walk(False)
            return
        if not self.walk:
            super().keyPressEvent(ev)

    def keyReleaseEvent(self, ev):
        if self.walk and ev.key() in self.MOVE_KEYS and not ev.isAutoRepeat():
            self.keys.discard(ev.key())
            ev.accept()
            return
        super().keyReleaseEvent(ev)

    def mousePressEvent(self, ev):
        self.setFocus()
        self._last = ev.position()
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if not self.walk:
            return super().mouseMoveEvent(ev)
        if self._last is None:
            self._last = ev.position()
        d = ev.position() - self._last
        self._last = ev.position()
        if ev.buttons() & (Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton):
            self.opts["azimuth"] = (self.opts["azimuth"] - d.x() * 0.25) % 360
            self.opts["elevation"] = float(np.clip(self.opts["elevation"] + d.y() * 0.25, -89, 89))
            self.update()

    def wheelEvent(self, ev):
        if not self.walk:
            return super().wheelEvent(ev)
        step = ev.angleDelta().y() / 120 * 0.5
        c = np.array(self.opts["center"]) + self._forward() * step
        self.opts["center"] = pg.Vector(*c)
        self.update()

    # ------------------------------------------------------------------ rendu
    def _add(self, it):
        self.addItem(it)
        self._items.append(it)

    def _lines(self, pts, rgba, width=1.0, colors=None, opts="translucent"):
        if pts is None or len(pts) == 0:
            return
        it = gl.GLLinePlotItem(pos=np.asarray(pts, float), mode="lines", width=width, antialias=True,
                               color=colors if colors is not None else rgba)
        it.setGLOptions(opts)
        self._add(it)

    def _mesh(self, V, F, rgba=None, vcolors=None, opts="translucent", shader=None, see_through=None):
        if len(F) == 0:
            return
        kw = dict(vertexes=np.asarray(V, float), faces=np.asarray(F), smooth=False, drawEdges=False)
        if vcolors is not None:
            kw["vertexColors"] = vcolors
        else:
            kw["color"] = rgba
        if shader:
            kw["shader"] = shader
        if see_through is None:
            see_through = opts != "opaque"
        m = (SeeThroughMesh if see_through else gl.GLMeshItem)(**kw)
        m.setGLOptions(opts)
        if see_through:
            m.setDepthValue(10)       # translucides dessinés après les éléments opaques
        self._add(m)

    def fit(self, scene: Scene):
        lo, hi = scene.bbox()
        self._lo, self._hi = lo, hi
        c = (lo + hi) / 2
        size = float(np.linalg.norm(hi - lo))
        self._scene_size = size
        if self.walk:
            self.set_walk(False)
        self.setCameraPosition(pos=pg.Vector(*c), distance=size * 1.15, elevation=28, azimuth=-125)

    def _grid_mesh(self, P, db, vmin, vmax, alpha):
        nu, nv = db.shape
        col = S.colorize((db - vmin) / max(vmax - vmin, 1e-6)).reshape(-1, 4) / 255.0
        col[:, 3] = alpha
        ii, jj = np.meshgrid(np.arange(nu - 1), np.arange(nv - 1), indexing="ij")
        a = (ii * nv + jj).ravel()
        F = np.vstack([np.stack([a, a + nv, a + nv + 1], 1), np.stack([a, a + nv + 1, a + 1], 1)])
        ok = np.isfinite(db.ravel())
        F = F[ok[F].all(1)]
        return P.reshape(-1, 3), F, col

    def render(self, scene: Scene, res: dict, sel: set):
        for it in self._items:
            self.removeItem(it)
        self._items = []
        st = scene.settings
        vmin, vmax = res["range"]
        lo, hi = scene.bbox()
        self._lo, self._hi = lo, hi
        self.grid.resetTransform()
        self.grid.translate(0, 0, lo[2] - 0.08)

        # --- SPL
        for m in res["maps"]:
            V, F, col = self._grid_mesh(m["P"] + np.array([0, 0, 0.03]), m["db"], vmin, vmax, 0.95)
            self._mesh(V, F, vcolors=col, opts="opaque")
        if res["section"] is not None and st.show_section:
            sec = res["section"]
            nx, nz = sec["db"].shape
            xs = sec["x0"] + (np.arange(nx) + 0.5) / nx * sec["w"]
            zs = sec["z0"] + (np.arange(nz) + 0.5) / nz * sec["h"]
            X, Z = np.meshgrid(xs, zs, indexing="ij")
            P = np.stack([X, np.full_like(X, st.section_y), Z], -1)
            V, F, col = self._grid_mesh(P, sec["db"], vmin, vmax, 0.55)
            self._mesh(V, F, vcolors=col)

        # --- formes
        for sh in scene.shapes:
            on = sh.id in sel
            faces = sh.faces()
            if sh.kind == "Pièce":
                # arêtes et murs : seules les faces vues de l'intérieur sont pleines
                self._lines(G.faces_edges(faces), (1, 1, 1, 0.9) if on else S.hex_rgba(S.SHAPE, 0.35), 1.5 if on else 1.0)
                V, F = oriented_mesh(faces)
                self._mesh(V, F, S.hex_rgba(S.SHAPE, 0.07), opts=ROOM_OPTS, see_through=True)
            else:
                self._lines(G.faces_edges(faces), (1, 1, 1, 0.9) if on else S.hex_rgba(S.SHAPE, 0.6),
                            1.5 if on else 1.0)
                V, F = G.faces_mesh(faces)
                a = {"Objet": 0.45, "Surface": 0.14}[sh.kind]
                col = S.hex_rgba("#d8dce4" if on else S.SHAPE, a)
                self._mesh(V, F, col, shader="shaded" if sh.kind == "Objet" else None)

        # --- rayons
        R = res.get("rays")
        if R is not None and len(R["p0"]):
            n = len(R["p0"])
            pts = np.empty((2 * n, 3)); pts[0::2] = R["p0"]; pts[1::2] = R["p1"]
            cols = np.array([S.hex_rgba(S.ORDER_COLORS[min(o, 5)]) for o in range(6)])
            c = cols[np.minimum(R["order"], 5)].copy()
            c[:, 3] = np.where(R["order"] == 0, 0.30, np.clip(0.35 * R["energy"], 0.08, 0.35))
            self._lines(pts, None, 1.0, colors=np.repeat(c, 2, 0))

        # --- cônes d'émission (-6 dB), translucides
        ca = st.cone_alpha
        # sélection : cônes dessinés par-dessus tout (sans test de profondeur), après le reste
        items = sorted(res["cones"].items(), key=lambda kv: is_on(res["src_by_id"][kv[0]], sel))
        for sid, cn in items:
            s = res["src_by_id"][sid]
            on = is_on(s, sel)
            col = scene.color_of(s)
            self._lines(np.array([s.pos, cn["axis"]]), S.hex_rgba(col, 1.0 if on else 0.6), 1.5, opts=OVERLAY if on else "translucent")
            ring = cn["ring"]
            if ring is None:
                continue
            k = len(ring)
            V = np.vstack([s.pos[None], ring])
            F = np.array([[0, i + 1, (i + 1) % k + 1] for i in range(k)])
            self._mesh(V, F, S.hex_rgba(col, min(0.85, ca * (2.0 if on else 1.0))), opts=OVERLAY if on else "translucent")
            edges = []
            for i in range(0, k, k // 8):
                edges += [s.pos, ring[i]]
            self._lines(np.array(edges), S.hex_rgba(col, 1.0 if on else 0.65), 1.6 if on else 1.2, opts=OVERLAY if on else "translucent")
            if not st.cov_clip:      # cône de longueur fixe : bord d'émission
                loop = np.empty((2 * k, 3)); loop[0::2] = ring; loop[1::2] = np.roll(ring, -1, 0)
                self._lines(loop, S.hex_rgba(col, 0.9 if on else 0.5), 1.4, opts=OVERLAY if on else "translucent")

        # --- réflexions
        by_order = {}
        for p in res.get("refl", []):
            if p["order"] > 0:
                pts = np.array(p["pts"])
                seg = np.empty((2 * (len(pts) - 1), 3)); seg[0::2] = pts[:-1]; seg[1::2] = pts[1:]
                by_order.setdefault((p["order"], p.get("color")), []).append(seg)
        for (order, pcol), segs in by_order.items():
            col = pcol or S.ORDER_COLORS[min(order, 5)]
            self._lines(np.vstack(segs), S.hex_rgba(col, 0.75 if order == 1 else 0.45), 1.3)

        # --- enceintes (volumes extrudés)
        font = QtGui.QFont("DejaVu Sans", 8)
        for o in scene.objects:
            g = scene.group(o.group)
            col = g.color if g else "#cccccc"
            on = o.id in sel or o.group in sel
            faces = [f for box in scene.bodies.get(o.id, []) for f in box]
            V, F = G.faces_mesh(faces)
            self._mesh(V, F, S.hex_rgba(col, 0.35 if o.mute else 1.0), opts="opaque" if not o.mute else "translucent",
                       shader="shaded")
            self._lines(G.faces_edges(faces), (1, 1, 1, 0.9) if on else (0, 0, 0, 0.7), 1.0)
            self._add(gl.GLTextItem(pos=o.pos + np.array([0, 0, 0.5]), text=o.name, color=qcolor(col), font=font))

        # --- coins et repères d'accrochage
        C = res.get("corners")
        if C is not None and len(C):
            sp = gl.GLScatterPlotItem(pos=np.asarray(C), size=7, color=(1, 1, 1, 0.95), pxMode=True)
            sp.setGLOptions(OVERLAY); sp.setDepthValue(20)
            self._add(sp)
            if len(C) <= 40:
                small = QtGui.QFont("DejaVu Sans", 7)
                for i, q in enumerate(C):
                    self._add(gl.GLTextItem(pos=np.asarray(q), text=str(i + 1), color=qcolor("#ffffff", 210),
                                            font=small))
        for pos, col, lab in res.get("markers", []):
            sp = gl.GLScatterPlotItem(pos=np.asarray(pos)[None], size=14, color=S.hex_rgba(col), pxMode=True)
            sp.setGLOptions(OVERLAY); sp.setDepthValue(21)
            self._add(sp)
            self._add(gl.GLTextItem(pos=np.asarray(pos), text="  " + lab, color=qcolor(col), font=font))

        # --- écouteurs
        if scene.listeners:
            pos = np.array([l.pos for l in scene.listeners])
            cols = np.array([(1, 1, 1, 1) if l.id in sel else (0.85, 0.85, 0.85, 0.9) for l in scene.listeners])
            sp = gl.GLScatterPlotItem(pos=pos, size=9, color=cols, pxMode=True)
            sp.setGLOptions("translucent")
            self._add(sp)
            for l in scene.listeners:
                self._add(gl.GLTextItem(pos=l.pos + np.array([0, 0, 0.4]), text=l.name, color=qcolor(S.TEXT), font=font))

        if not self._fitted:
            self.fit(scene)
            self._fitted = True


# --------------------------------------------------------------------------- légende
class ColorLegend(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.vmin, self.vmax, self.label = 90.0, 114.0, ""
        self.setFixedHeight(22)
        self.setMinimumWidth(340)

    def set_range(self, vmin, vmax, label):
        self.vmin, self.vmax, self.label = vmin, vmax, label
        self.update()

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        w = 120
        x0 = self.width() - w - 56
        y0 = 7
        grad = S.colorize(np.linspace(0, 1, w))
        for i in range(w):
            r, g, b, _ = grad[i]
            p.setPen(QtGui.QColor(int(r), int(g), int(b)))
            p.drawLine(x0 + i, y0, x0 + i, y0 + 8)
        f = p.font(); f.setPointSize(8); p.setFont(f)
        fm = p.fontMetrics()
        t0, t1 = f"{self.vmin:.0f}", f"{self.vmax:.0f} dB"
        x = x0 - 6
        p.setPen(QtGui.QColor(S.DIM))
        x -= fm.horizontalAdvance(t0); p.drawText(x, y0 + 9, t0)
        if self.label:
            p.setPen(QtGui.QColor(S.TEXT))
            x -= fm.horizontalAdvance(self.label) + 12; p.drawText(x, y0 + 9, self.label)
        p.setPen(QtGui.QColor(S.DIM))
        p.drawText(x0 + w + 4, y0 + 9, t1)
        p.end()


class ViewPane(QtWidgets.QWidget):
    """Vue avec barre de titre et bouton plein écran."""
    sigMaximize = QtCore.Signal(object)

    def __init__(self, widget, title, extras=()):
        super().__init__()
        self.view = widget
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        bar = QtWidgets.QHBoxLayout(); bar.setContentsMargins(0, 0, 4, 0); bar.setSpacing(2)
        lab = QtWidgets.QLabel(title); lab.setObjectName("title")
        bar.addWidget(lab)
        bar.addStretch(1)
        for w in extras:
            bar.addWidget(w)
        self.maxbtn = QtWidgets.QToolButton()
        self.maxbtn.setText("⤢")
        self.maxbtn.setToolTip("Plein écran (double-clic sur le titre) · Échap pour revenir")
        self.maxbtn.clicked.connect(lambda: self.sigMaximize.emit(self))
        bar.addWidget(self.maxbtn)
        lay.addLayout(bar)
        lay.addWidget(widget, 1)
        lab.mouseDoubleClickEvent = lambda e: self.sigMaximize.emit(self)
