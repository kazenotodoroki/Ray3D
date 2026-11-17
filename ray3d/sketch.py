"""Éditeur d'esquisse 2D façon CAO : points cliqués (aimantés), segments droits ou en arc, cotes
éditables, sélection et suppression d'un point, annuler / rétablir, puis extrusion."""
from __future__ import annotations

import copy
import math

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from . import style as S
from . import geometry as G
from .model import SHAPE_KINDS
from .widgets import no_enter_dialog, NoWheelCombo, parse_number

PLANE_LABELS = {"XY": ("X", "Y", "Z"), "XZ": ("X", "Z", "Y"), "YZ": ("Y", "Z", "X")}
SEL = "#3ec1ff"          # couleur de la sélection


def fnum(text, default=None):
    v = parse_number(text)
    return default if v is None else v


# --------------------------------------------------------------------------- canevas
class SketchCanvas(pg.PlotWidget):
    """Points (pts) + flèche par segment (arcs, convention de geometry.py).
    - clic dans le vide : ajoute un point après le point sélectionné (ou à la fin) ;
    - clic sur un point : le sélectionne ; glisser : le déplace ;
    - poignée ronde au milieu de chaque segment : glisser pour le courber en arc ;
    - Suppr : supprime le point sélectionné ; clic droit : menu ;
    - Ctrl+Z / Ctrl+Y : annuler / rétablir."""
    changed = QtCore.Signal()
    selectionChanged = QtCore.Signal(int)

    def __init__(self):
        super().__init__()
        self.setBackground(S.BG)
        pi = self.getPlotItem()
        pi.hideButtons(); pi.setMenuEnabled(False)
        self.setAspectLocked(True)
        pi.showGrid(x=True, y=True, alpha=0.12)
        for a in ("left", "bottom"):
            ax = pi.getAxis(a)
            ax.setPen(pg.mkPen(S.BORDER)); ax.setTextPen(pg.mkPen(S.DIM)); ax.enableAutoSIPrefix(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.pts: list[list[float]] = []
        self.arcs: list[float] = []
        self.sel = -1
        self.snap = 0.1
        self.origin_marker = False
        self.extra = []           # [(pos, label, color)] marqueurs fixes (arêtes d'accroche…)
        self._items = []
        self.history, self.hpos = [], -1
        self.scene().sigMouseClicked.connect(self._click)
        self.getPlotItem().getViewBox().setRange(xRange=(-1, 11), yRange=(-1, 8))

    # ---------------------------------------------------------------- état / historique
    def set_profile(self, pts, arcs=None, reset_history=False):
        self.pts = [list(map(float, p)) for p in (pts or [])]
        self.arcs = G.norm_arcs(self.pts, arcs)
        self.sel = min(self.sel, len(self.pts) - 1)
        if reset_history:
            self.history, self.hpos = [], -1
        self.commit()

    def commit(self):
        """Enregistre l'état courant dans l'historique et prévient le dialogue."""
        self.arcs = G.norm_arcs(self.pts, self.arcs)
        snap = (copy.deepcopy(self.pts), list(self.arcs))
        if self.hpos >= 0 and self.history[self.hpos] == snap:
            self.redraw(); self.changed.emit()
            return
        del self.history[self.hpos + 1:]
        self.history.append(snap)
        if len(self.history) > 300:
            self.history.pop(0)
        self.hpos = len(self.history) - 1
        self.redraw()
        self.changed.emit()

    def _restore(self):
        pts, arcs = self.history[self.hpos]
        self.pts, self.arcs = copy.deepcopy(pts), list(arcs)
        self.sel = min(self.sel, len(self.pts) - 1)
        self.redraw()
        self.changed.emit()
        self.selectionChanged.emit(self.sel)

    def undo(self):
        if self.hpos > 0:
            self.hpos -= 1
            self._restore()

    def redo(self):
        if self.hpos < len(self.history) - 1:
            self.hpos += 1
            self._restore()

    # ---------------------------------------------------------------- édition
    def orient(self):
        """+1 si le profil (sans arcs) tourne dans le sens trigonométrique."""
        return 1.0 if len(self.pts) < 3 or G.poly_area(self.pts) >= 0 else -1.0

    def bulge_out(self, i):
        """Flèche du segment i, positive = bombé vers l'extérieur de la forme."""
        return -self.arcs[i] * self.orient()

    def set_bulge_out(self, i, v):
        self.arcs[i] = -v * self.orient()

    def select(self, i):
        self.sel = i if 0 <= i < len(self.pts) else -1
        self.redraw()
        self.selectionChanged.emit(self.sel)

    def delete_point(self, i=None):
        i = self.sel if i is None else i
        if not (0 <= i < len(self.pts)):
            return
        n = len(self.pts)
        del self.pts[i]
        # le segment (i-1 → i) disparaît, (i → i+1) devient (i-1 → i+1) : on garde l'arc précédent
        del self.arcs[i]
        if self.pts:
            self.arcs[(i - 1) % len(self.pts)] = 0.0     # le nouveau segment (i-1 → i+1) est droit
        self.sel = min(i, len(self.pts) - 1) if self.pts else -1
        self.commit()
        self.selectionChanged.emit(self.sel)

    def insert_mid(self, i=None):
        """Insère un point au milieu du segment i (i → i+1)."""
        i = self.sel if i is None else i
        n = len(self.pts)
        if n < 2 or not (0 <= i < n) or (i == n - 1 and n < 3):
            return
        A, B = np.asarray(self.pts[i]), np.asarray(self.pts[(i + 1) % n])
        s = self.arcs[i]
        if abs(s) > 1e-9:                    # sur un arc : point au sommet, deux demi-arcs
            g = G.arc_geometry(A, B, s)
            C, R, a0, sw = g
            am = a0 + sw / 2
            M = C + R * np.array([math.cos(am), math.sin(am)])
            c2 = float(np.linalg.norm(M - A))
            s2 = math.copysign(R - math.sqrt(max(R * R - c2 * c2 / 4, 0)), s) if abs(sw) <= math.pi * 2 else 0
            # pour un arc de plus d'un demi-cercle, la flèche des moitiés reste la petite
            self.arcs[i] = s2
            self.pts.insert(i + 1, [round(float(M[0]), 4), round(float(M[1]), 4)])
            self.arcs.insert(i + 1, s2)
        else:
            M = (A + B) / 2
            self.pts.insert(i + 1, [round(float(M[0]), 4), round(float(M[1]), 4)])
            self.arcs.insert(i + 1, 0.0)
        self.sel = i + 1
        self.commit()
        self.selectionChanged.emit(self.sel)

    def set_straight(self, i):
        if 0 <= i < len(self.arcs):
            self.arcs[i] = 0.0
            self.commit()

    def set_semicircle(self, i):
        n = len(self.pts)
        if 0 <= i < n and n >= 2:
            c = float(np.linalg.norm(np.subtract(self.pts[(i + 1) % n], self.pts[i])))
            self.set_bulge_out(i, c / 2)
            self.commit()

    # ---------------------------------------------------------------- souris / clavier
    def set_axes(self, xa, ya):
        pi = self.getPlotItem()
        pi.getAxis("bottom").setLabel(xa, color=S.DIM)
        pi.getAxis("left").setLabel(ya, color=S.DIM)

    def snapv(self, v):
        if self.snap <= 0:
            return round(v, 4)
        return round(round(v / self.snap) * self.snap, 4)

    def _hit(self, scene_pos, pts, tol=10):
        vb = self.getPlotItem().getViewBox()
        for i, q in enumerate(pts):
            sp = vb.mapViewToScene(QtCore.QPointF(float(q[0]), float(q[1])))
            if (sp - scene_pos).manhattanLength() < tol:
                return i
        return -1

    def _handles(self):
        """Poignées d'arc : milieu de chaque segment (sommet de l'arc s'il est courbé)."""
        n = len(self.pts)
        out = []
        for i in range(n if n >= 3 else n - 1):
            A, B = np.asarray(self.pts[i]), np.asarray(self.pts[(i + 1) % n])
            c = float(np.linalg.norm(B - A))
            if c < 1e-9:
                out.append(None); continue
            d = (B - A) / c
            nrm = np.array([-d[1], d[0]])
            out.append((A + B) / 2 + nrm * self.arcs[i])
        return out

    def _click(self, ev):
        if ev.double():
            return
        vb = self.getPlotItem().getViewBox()
        if not vb.sceneBoundingRect().contains(ev.scenePos()):
            return
        self.setFocus()
        p = vb.mapSceneToView(ev.scenePos())
        k = self._hit(ev.scenePos(), self.pts)
        if ev.button() == Qt.MouseButton.RightButton:
            self._menu(ev, k)
            ev.accept()
            return
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        if k >= 0:                           # clic sur un point : sélection
            self.select(k)
            ev.accept()
            return
        h = [x for x in self._handles()]
        if self._hit(ev.scenePos(), [q for q in h if q is not None]) >= 0:
            ev.accept()
            return
        x, y = p.x(), p.y()
        ref = self.pts[self.sel] if 0 <= self.sel < len(self.pts) else (self.pts[-1] if self.pts else None)
        if not (ev.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            x, y = self.snapv(x), self.snapv(y)
            if ref is not None:              # aimantation angulaire 15° depuis le point de référence
                px, py = ref
                L = math.hypot(x - px, y - py)
                if L > 1e-9:
                    a = math.degrees(math.atan2(y - py, x - px))
                    a15 = round(a / 15) * 15
                    if abs(a - a15) < 4:
                        L = self.snapv(L)
                        x = round(px + L * math.cos(math.radians(a15)), 4)
                        y = round(py + L * math.sin(math.radians(a15)), 4)
        at = self.sel + 1 if 0 <= self.sel < len(self.pts) else len(self.pts)
        self.pts.insert(at, [x, y])
        self.arcs.insert(at, 0.0)
        self.sel = at
        self.commit()
        self.selectionChanged.emit(self.sel)
        ev.accept()

    def _menu(self, ev, k):
        m = QtWidgets.QMenu(self)
        n = len(self.pts)
        if k >= 0:
            self.select(k)
            m.addAction(f"Supprimer le point {k + 1}", lambda: self.delete_point(k))
            if n >= 2:
                m.addAction(f"Insérer un point après le point {k + 1}", lambda: self.insert_mid(k))
            if n >= 2 and (k < n - 1 or n >= 3):
                m.addSeparator()
                m.addAction(f"Segment {k + 1} → {(k + 1) % n + 1} droit", lambda: self.set_straight(k))
                m.addAction(f"Segment {k + 1} → {(k + 1) % n + 1} en demi-cercle", lambda: self.set_semicircle(k))
        else:
            hs = self._handles()
            j = self._hit(ev.scenePos(), [q if q is not None else (1e18, 1e18) for q in hs])
            if j >= 0:
                m.addAction(f"Segment {j + 1} → {(j + 1) % n + 1} droit", lambda: self.set_straight(j))
                m.addAction(f"Segment {j + 1} → {(j + 1) % n + 1} en demi-cercle", lambda: self.set_semicircle(j))
                m.addAction("Insérer un point au milieu", lambda: self.insert_mid(j))
            else:
                m.addAction("Désélectionner", lambda: self.select(-1))
        m.addSeparator()
        a = m.addAction("Annuler (Ctrl+Z)", self.undo); a.setEnabled(self.hpos > 0)
        a = m.addAction("Rétablir (Ctrl+Y)", self.redo); a.setEnabled(self.hpos < len(self.history) - 1)
        m.exec(ev.screenPos().toPoint())

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_point(); e.accept(); return
        if e.matches(QtGui.QKeySequence.StandardKey.Undo):
            self.undo(); e.accept(); return
        if e.matches(QtGui.QKeySequence.StandardKey.Redo) or (
                e.key() == Qt.Key.Key_Y and e.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.redo(); e.accept(); return
        if e.key() == Qt.Key.Key_Escape and self.sel >= 0:
            self.select(-1); e.accept(); return
        super().keyPressEvent(e)

    # ---------------------------------------------------------------- dessin
    def redraw(self):
        pi = self.getPlotItem()
        for it in self._items:
            pi.removeItem(it)
        self._items = []

        def add(it, z=0):
            it.setZValue(z); pi.addItem(it); self._items.append(it)
        if self.origin_marker:
            add(pg.PlotDataItem([-0.1, 0.1, np.nan, 0, 0], [0, 0, np.nan, -0.1, 0.1], connect="finite",
                                pen=pg.mkPen("#ffffff", width=1.5)), 5)
            t = pg.TextItem("accroche", color=S.TEXT, anchor=(0, 1)); t.setPos(0.02, 0.02); add(t, 5)
        for pos, label, col in self.extra:
            add(pg.ScatterPlotItem([pos[0]], [pos[1]], size=9, symbol="d", pen=pg.mkPen(col),
                                   brush=pg.mkBrush(col)), 6)
            t = pg.TextItem(label, color=col, anchor=(1, 0)); t.setPos(*pos); add(t, 6)
        n = len(self.pts)
        self.arcs = G.norm_arcs(self.pts, self.arcs)
        if n >= 3:
            E = G.expand_profile(self.pts, self.arcs)
            poly = QtWidgets.QGraphicsPolygonItem(QtGui.QPolygonF([QtCore.QPointF(*q) for q in E]))
            c = QtGui.QColor(S.ACCENT); c.setAlpha(28)
            poly.setBrush(c); poly.setPen(pg.mkPen(None))
            add(poly, -1)
        hs = self._handles()
        for i in range(len(hs)):
            A, B = np.asarray(self.pts[i]), np.asarray(self.pts[(i + 1) % n])
            seg = np.vstack([A[None], np.array(G.arc_points(A, B, self.arcs[i])).reshape(-1, 2), B[None]])
            closing = i == n - 1
            style = Qt.PenStyle.DashLine if closing else Qt.PenStyle.SolidLine
            add(pg.PlotDataItem(seg[:, 0], seg[:, 1], pen=pg.mkPen(S.ACCENT, width=1 if closing else 2,
                                                                    style=style)), 1)
            if hs[i] is None:
                continue
            c = float(np.linalg.norm(B - A))
            if abs(self.arcs[i]) > 1e-9:
                g = G.arc_geometry(A, B, self.arcs[i])
                txt = f"R {g[1]:.2f} · {G.arc_length(A, B, self.arcs[i]):.2f}"
            else:
                txt = f"{c:.2f}"
            d = (B - A) / c
            nrm = np.array([-d[1], d[0]])
            t = pg.TextItem(txt, color="#ffffff", anchor=(0.5, 0.5), fill=pg.mkBrush(QtGui.QColor(12, 13, 15, 200)))
            off = nrm * (0.0 if abs(self.arcs[i]) < 1e-9 else 0.0)
            t.setPos(*((A + B) / 2 + off))
            add(t, 3)
            # poignée d'arc
            h = pg.TargetItem(pos=(float(hs[i][0]), float(hs[i][1])), size=8, symbol="o",
                              pen=pg.mkPen(S.DIM if abs(self.arcs[i]) < 1e-9 else "#ffd23a", width=1),
                              brush=pg.mkBrush(QtGui.QColor(0, 0, 0, 0)), hoverPen=pg.mkPen("#ffd23a", width=2),
                              movable=True)
            h.setToolTip("Glisser pour courber le segment en arc")
            h.sigPositionChangeFinished.connect(lambda it, k=i: self._arc_moved(k, it))
            add(h, 4)
        for i, q in enumerate(self.pts):
            on = i == self.sel
            tg = pg.TargetItem(pos=tuple(q), size=11 if on else 9, symbol="s",
                               pen=pg.mkPen("#ffffff", width=2 if on else 1),
                               brush=pg.mkBrush(SEL if on else S.ACCENT), hoverBrush=pg.mkBrush("#ffffff"),
                               movable=True, label=str(i + 1),
                               labelOpts=dict(color=SEL if on else S.DIM, offset=(7, -7), anchor=(0, 1)))
            tg.sigPositionChangeFinished.connect(lambda it, k=i: self._moved(k, it))
            add(tg, 5)

    def _moved(self, k, it):
        x, y = it.pos().x(), it.pos().y()
        nx, ny = self.snapv(x), self.snapv(y)
        if [nx, ny] == self.pts[k]:          # simple clic (pas de déplacement) : sélection
            QtCore.QTimer.singleShot(0, lambda: self.select(k))
            return
        self.pts[k] = [nx, ny]
        self.sel = k
        QtCore.QTimer.singleShot(0, self.commit)
        self.selectionChanged.emit(k)

    def _arc_moved(self, i, it):
        n = len(self.pts)
        A, B = np.asarray(self.pts[i]), np.asarray(self.pts[(i + 1) % n])
        c = float(np.linalg.norm(B - A))
        if c < 1e-9:
            return
        d = (B - A) / c
        nrm = np.array([-d[1], d[0]])
        Q = np.array([it.pos().x(), it.pos().y()])
        s = float((Q - (A + B) / 2) @ nrm)
        s = self.snapv(s) if self.snap > 0 else s
        if abs(s) < 1e-6 or abs(s) < 0.02 * c:
            s = 0.0
        self.arcs[i] = s
        QtCore.QTimer.singleShot(0, self.commit)

    def fit(self):
        if not self.pts:
            return
        P = G.expand_profile(self.pts, self.arcs)
        lo, hi = P.min(0), P.max(0)
        m = max(float((hi - lo).max()) * 0.15, 0.1)
        self.getPlotItem().getViewBox().setRange(xRange=(lo[0] - m, hi[0] + m), yRange=(lo[1] - m, hi[1] + m))


# --------------------------------------------------------------------------- dialogue
TCOLS = ["a", "b", "→ longueur", "→ angle °", "→ flèche", "→ rayon"]


class SketchDialog(QtWidgets.QDialog):
    """mode 'shape' : forme de scène ; mode 'speaker' : profil latéral d'enceinte."""

    def __init__(self, parent=None, profile=None, mode="shape", kind="Pièce", plane="XY", height=3.0,
                 symmetric=False, recenter=True, title="Esquisse", extra=None, arcs=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1250, 760)
        self.mode = mode
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        self.canvas = SketchCanvas()
        self.canvas.origin_marker = mode == "speaker"
        self.canvas.extra = extra or []
        self.canvas.changed.connect(self._sync_table)
        self.canvas.selectionChanged.connect(self._select_row)
        left = QtWidgets.QWidget(); ll = QtWidgets.QVBoxLayout(left); ll.setContentsMargins(0, 0, 0, 0); ll.setSpacing(0)
        hint = QtWidgets.QLabel("  Clic : ajouter un point après le point sélectionné (aimanté, Maj = libre) · "
                                "clic sur un point : le sélectionner · glisser : déplacer · ○ au milieu d'un "
                                "segment : glisser pour faire un arc · Suppr : supprimer · clic droit : menu · "
                                "Ctrl+Z / Ctrl+Y")
        hint.setObjectName("title"); hint.setWordWrap(True)
        ll.addWidget(hint); ll.addWidget(self.canvas, 1)
        lay.addWidget(left, 3)

        right = QtWidgets.QWidget(); right.setMinimumWidth(460)
        f = QtWidgets.QFormLayout(right); f.setContentsMargins(12, 10, 12, 12); f.setVerticalSpacing(6)
        lay.addWidget(right, 2)

        def section(t):
            l = QtWidgets.QLabel(t.upper()); l.setObjectName("section"); f.addRow(l)

        section("Esquisse")
        self.snap = NoWheelCombo()
        for s in ("0.001", "0.005", "0.01", "0.05", "0.1", "0.25", "0.5", "1"):
            self.snap.addItem(s, float(s))
        self.snap.setCurrentText("0.01" if mode == "speaker" else "0.1")
        self.snap.currentIndexChanged.connect(lambda _: setattr(self.canvas, "snap", self.snap.currentData()))
        self.canvas.snap = self.snap.currentData()
        f.addRow("Grille d'aimantation (m)", self.snap)

        pre = QtWidgets.QHBoxLayout()
        self.rw = QtWidgets.QLineEdit("10" if mode == "shape" else "0.55")
        self.rd = QtWidgets.QLineEdit("6.5" if mode == "shape" else "0.35")
        b = QtWidgets.QPushButton("Rectangle")
        b.clicked.connect(self._rect)
        pre.addWidget(self.rw); pre.addWidget(QtWidgets.QLabel("×")); pre.addWidget(self.rd); pre.addWidget(b)
        f.addRow("Préréglage", pre)
        if mode == "shape":
            st = QtWidgets.QHBoxLayout()
            self.sn = QtWidgets.QLineEdit("8"); self.sd = QtWidgets.QLineEdit("0.9"); self.sr = QtWidgets.QLineEdit("0.4")
            for w, tip in ((self.sn, "marches"), (self.sd, "profondeur"), (self.sr, "hauteur")):
                w.setToolTip(tip); st.addWidget(w)
            b2 = QtWidgets.QPushButton("Gradins")
            b2.setToolTip("Profil de gradins (à esquisser dans le plan XZ)")
            b2.clicked.connect(self._stairs)
            st.addWidget(b2)
            f.addRow("n · prof. · haut.", st)

        section("Points et cotes")
        eb = QtWidgets.QHBoxLayout()
        self.b_undo = QtWidgets.QPushButton("Annuler"); self.b_undo.clicked.connect(self.canvas.undo)
        self.b_redo = QtWidgets.QPushButton("Rétablir"); self.b_redo.clicked.connect(self.canvas.redo)
        self.b_ins = QtWidgets.QPushButton("Insérer un point"); self.b_ins.clicked.connect(lambda: self.canvas.insert_mid())
        self.b_ins.setToolTip("Insère un point au milieu du segment qui part du point sélectionné")
        self.b_del = QtWidgets.QPushButton("Supprimer le point"); self.b_del.clicked.connect(lambda: self.canvas.delete_point())
        for w in (self.b_undo, self.b_redo, self.b_ins, self.b_del):
            eb.addWidget(w)
        f.addRow(eb)
        self.table = QtWidgets.QTableWidget(0, len(TCOLS))
        self.table.setHorizontalHeaderLabels(TCOLS)
        self.table.verticalHeader().setDefaultSectionSize(22)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.table.itemChanged.connect(self._table_edit)
        self.table.itemSelectionChanged.connect(self._row_selected)
        self.table.setMinimumHeight(240)
        self.table.setToolTip("Ligne i : point i et segment i → i+1. Flèche > 0 = arc bombé vers l'extérieur, "
                              "< 0 = vers l'intérieur, 0 = droit. Suppr : supprime le point de la ligne.")
        f.addRow(self.table)
        for w in (self.table, self.canvas):
            for seq, fn in ((QtGui.QKeySequence.StandardKey.Undo, self.canvas.undo),
                            (QtGui.QKeySequence.StandardKey.Redo, self.canvas.redo),
                            (QtGui.QKeySequence("Ctrl+Y"), self.canvas.redo)):
                sc = QtGui.QShortcut(QtGui.QKeySequence(seq), w)
                sc.setContext(Qt.ShortcutContext.WidgetShortcut)
                sc.activated.connect(fn)
        dl = QtGui.QShortcut(QtGui.QKeySequence(Qt.Key.Key_Delete), self.table)
        dl.setContext(Qt.ShortcutContext.WidgetShortcut)
        dl.activated.connect(lambda: self.canvas.delete_point())
        self.info = QtWidgets.QLabel(); self.info.setObjectName("info"); self.info.setWordWrap(True)
        f.addRow(self.info)
        clr = QtWidgets.QPushButton("Effacer l'esquisse")
        clr.clicked.connect(self._clear)
        f.addRow(clr)

        if mode == "shape":
            section("Extrusion")
            self.kind = NoWheelCombo(); self.kind.addItems(SHAPE_KINDS); self.kind.setCurrentText(kind)
            f.addRow("Type", self.kind)
            self.plane = NoWheelCombo()
            for k, lab in (("XY", "XY · vue de dessus (extrusion en hauteur)"),
                           ("XZ", "XZ · profil de côté (extrusion en largeur)"),
                           ("YZ", "YZ · vue de face (extrusion en profondeur)")):
                self.plane.addItem(lab, k)
            self.plane.setCurrentIndex(max(0, self.plane.findData(plane)))
            self.plane.currentIndexChanged.connect(self._axes)
            f.addRow("Plan d'esquisse", self.plane)
            self.height = QtWidgets.QLineEdit(f"{height:g}")
            f.addRow("Extrusion (m)", self.height)
            self.sym = QtWidgets.QCheckBox("Extrusion symétrique"); self.sym.setChecked(symmetric)
            f.addRow(self.sym)
            self.recenter = QtWidgets.QCheckBox("Centrer sur l'origine, sol à z = 0"); self.recenter.setChecked(recenter)
            f.addRow(self.recenter)
            self.kind.currentTextChanged.connect(lambda k: self.height.setEnabled(k != "Surface"))
            self.height.setEnabled(kind != "Surface")
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
                                        QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        bb.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setObjectName("primary")
        bb.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setText("Valider")
        bb.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel).setText("Annuler")
        for bt in bb.buttons():
            bt.setIcon(QtGui.QIcon())
        bb.accepted.connect(self._accept); bb.rejected.connect(self.reject)
        f.addRow(bb)
        self._axes()
        self.canvas.set_profile(profile or [], arcs, reset_history=True)
        self.canvas.fit()
        no_enter_dialog(self)
        self.canvas.setFocus()

    def keyPressEvent(self, e):
        # Entrée valide la cote ou le champ en cours, sans fermer le dialogue
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            fw = self.focusWidget()
            if isinstance(fw, QtWidgets.QLineEdit):
                fw.editingFinished.emit()
            e.accept()
            return
        super().keyPressEvent(e)

    # ------------------------------------------------------------------
    def _axes(self):
        if self.mode == "speaker":
            self.canvas.set_axes("avant · f (m)", "haut · u (m)")
            self.table.setHorizontalHeaderLabels(["f", "u"] + TCOLS[2:])
            return
        a, b, e = PLANE_LABELS[self.plane.currentData()]
        self.canvas.set_axes(f"{a} (m)", f"{b} (m)")
        self.table.setHorizontalHeaderLabels([a, b] + TCOLS[2:])

    def _rect(self):
        w, d = fnum(self.rw.text(), 1), fnum(self.rd.text(), 1)
        if self.mode == "speaker":
            pts = [[0, 0], [0, -d], [-w, -d], [-w, 0]]
        else:
            pts = [[0, 0], [w, 0], [w, d], [0, d]]
        self.canvas.set_profile(pts, None)
        self.canvas.fit()

    def _stairs(self):
        from .demo import stairs_profile
        n = int(fnum(self.sn.text(), 8)); dp = fnum(self.sd.text(), 0.9); r = fnum(self.sr.text(), 0.4)
        if self.plane.currentData() == "XY":
            self.plane.setCurrentIndex(self.plane.findData("XZ"))
            self.sym.setChecked(True)
            self.kind.setCurrentText("Objet")
            self.height.setText("20")
        self.canvas.set_profile(stairs_profile(0, dp, r, max(1, n)), None)
        self.canvas.fit()

    def _clear(self):
        self.canvas.sel = -1
        self.canvas.set_profile([], None)

    def _cell(self, text, editable=True, color=None):
        it = QtWidgets.QTableWidgetItem(text)
        if not editable:
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            it.setForeground(QtGui.QColor(S.DIM))
        elif color:
            it.setForeground(QtGui.QColor(color))
        return it

    def _sync_table(self):
        cv = self.canvas
        P = cv.pts
        self.table.blockSignals(True)
        n = len(P)
        self.table.setRowCount(n)
        for i, (x, y) in enumerate(P):
            self.table.setItem(i, 0, self._cell(f"{x:.3f}"))
            self.table.setItem(i, 1, self._cell(f"{y:.3f}"))
            seg = n >= 2 and (i < n - 1 or n >= 3)
            if seg:
                j = (i + 1) % n
                L = math.hypot(P[j][0] - x, P[j][1] - y)
                a = math.degrees(math.atan2(P[j][1] - y, P[j][0] - x))
                closing = i == n - 1                       # segment de fermeture : longueur / angle calculés
                self.table.setItem(i, 2, self._cell(f"{L:.3f}", not closing))
                self.table.setItem(i, 3, self._cell(f"{a:.1f}", not closing))
                b = cv.bulge_out(i)
                arc = abs(b) > 1e-9
                self.table.setItem(i, 4, self._cell(f"{b:.3f}" if arc else "0", True, "#ffd23a" if arc else None))
                if arc:
                    g = G.arc_geometry(P[i], P[j], cv.arcs[i])
                    self.table.setItem(i, 5, self._cell(f"{g[1]:.3f}", True, "#ffd23a"))
                else:
                    self.table.setItem(i, 5, self._cell("—"))
            else:
                for c in range(2, 6):
                    self.table.setItem(i, c, self._cell("", False))
        self.table.blockSignals(False)
        self._select_row(cv.sel)
        if n >= 3:
            E = G.expand_profile(P, cv.arcs)
            A = abs(G.poly_area(E))
            ext = E.max(0) - E.min(0)
            narc = sum(abs(a) > 1e-9 for a in cv.arcs)
            self.info.setText(f"{n} points · {narc} arc(s) · aire {A:.3f} m² · encombrement "
                              f"{ext[0]:.3f} × {ext[1]:.3f} m")
        else:
            self.info.setText("Au moins 3 points sont nécessaires.")
        self.b_undo.setEnabled(cv.hpos > 0)
        self.b_redo.setEnabled(cv.hpos < len(cv.history) - 1)
        self.b_del.setEnabled(0 <= cv.sel < n)
        self.b_ins.setEnabled(0 <= cv.sel < n and n >= 2)

    def _select_row(self, i):
        self.table.blockSignals(True)
        self.table.clearSelection()
        if 0 <= i < self.table.rowCount():
            self.table.selectRow(i)
        self.table.blockSignals(False)
        n = len(self.canvas.pts)
        self.b_del.setEnabled(0 <= i < n)
        self.b_ins.setEnabled(0 <= i < n and n >= 2)

    def _row_selected(self):
        rows = {it.row() for it in self.table.selectedItems()}
        if rows:
            r = min(rows)
            if r != self.canvas.sel:
                self.canvas.sel = r
                self.canvas.redraw()
                self._select_row(r)

    def _table_edit(self, it):
        cv = self.canvas
        r, c = it.row(), it.column()
        P = cv.pts
        n = len(P)
        txt = it.text().strip()
        v = fnum(txt)
        if c == 5 and txt in ("", "—", "-"):
            v = 0.0
        if v is None or r >= n:
            QtCore.QTimer.singleShot(0, self._sync_table); return
        if c in (0, 1):
            P[r][c] = round(v, 4)
        elif c in (2, 3):
            j = r + 1
            if j >= n:
                QtCore.QTimer.singleShot(0, self._sync_table); return
            x, y = P[r]
            L = math.hypot(P[j][0] - x, P[j][1] - y)
            a = math.degrees(math.atan2(P[j][1] - y, P[j][0] - x))
            if c == 2:
                L = max(v, 0.0)
            else:
                a = v
            nx, ny = x + L * math.cos(math.radians(a)), y + L * math.sin(math.radians(a))
            dx, dy = nx - P[j][0], ny - P[j][1]
            for k in range(j, n):            # cotes chaînées : la suite se décale
                P[k] = [round(P[k][0] + dx, 4), round(P[k][1] + dy, 4)]
        elif c == 4:                          # flèche (positive = vers l'extérieur)
            cv.set_bulge_out(r, v)
        elif c == 5:                          # rayon : petit arc, même côté qu'avant (extérieur par défaut)
            j = (r + 1) % n
            chord = math.hypot(P[j][0] - P[r][0], P[j][1] - P[r][1])
            if v <= 0 or chord < 1e-9:
                cv.arcs[r] = 0.0
            else:
                side = 1.0 if cv.bulge_out(r) >= 0 else -1.0
                cv.set_bulge_out(r, G.sagitta_from_radius(chord, v, side))
        cv.sel = r
        QtCore.QTimer.singleShot(0, cv.commit)

    def _accept(self):
        if len(self.canvas.pts) < 3:
            QtWidgets.QMessageBox.warning(self, "Esquisse", "Il faut au moins 3 points.")
            return
        self.accept()

    # résultats
    def _oriented(self):
        return G.ccw_with_arcs(self.canvas.pts, self.canvas.arcs)

    @property
    def profile(self):
        return [list(map(float, p)) for p in self._oriented()[0]]

    @property
    def arcs(self):
        return [round(float(a), 6) for a in self._oriented()[1]]

    def values(self):
        return dict(profile=self.profile, arcs=self.arcs, kind=self.kind.currentText(),
                    plane=self.plane.currentData(), height=fnum(self.height.text(), 3.0),
                    symmetric=self.sym.isChecked(), recenter=self.recenter.isChecked())
