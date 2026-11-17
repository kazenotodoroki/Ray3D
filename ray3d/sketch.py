"""Éditeur d'esquisse 2D façon CAO : points cliqués (aimantés), cotes éditables,
puis extrusion."""
from __future__ import annotations

import math

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from . import style as S
from . import geometry as G
from .model import SHAPE_KINDS

PLANE_LABELS = {"XY": ("X", "Y", "Z"), "XZ": ("X", "Z", "Y"), "YZ": ("Y", "Z", "X")}


def fnum(text, default=None):
    try:
        return float(str(text).strip().replace(",", "."))
    except ValueError:
        return default


class SketchCanvas(pg.PlotWidget):
    changed = QtCore.Signal()

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
        self.pts: list[list[float]] = []
        self.snap = 0.1
        self.origin_marker = False
        self.extra = []           # [(pos, label, color)] marqueurs fixes (arêtes d'accroche…)
        self._items = []
        self.scene().sigMouseClicked.connect(self._click)
        self.getPlotItem().getViewBox().setRange(xRange=(-1, 11), yRange=(-1, 8))

    def set_axes(self, xa, ya):
        pi = self.getPlotItem()
        pi.getAxis("bottom").setLabel(xa, color=S.DIM)
        pi.getAxis("left").setLabel(ya, color=S.DIM)

    def snapv(self, v):
        if self.snap <= 0:
            return round(v, 4)
        return round(round(v / self.snap) * self.snap, 4)

    def _click(self, ev):
        if ev.double():
            return
        vb = self.getPlotItem().getViewBox()
        if not vb.sceneBoundingRect().contains(ev.scenePos()):
            return
        p = vb.mapSceneToView(ev.scenePos())
        if ev.button() == Qt.MouseButton.RightButton:
            if self.pts:
                self.pts.pop()
                self.redraw(); self.changed.emit()
            ev.accept()
            return
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        # clic près d'un sommet existant : pas d'ajout (déplacement par glisser)
        for q in self.pts:
            sp = vb.mapViewToScene(QtCore.QPointF(*q))
            if (sp - ev.scenePos()).manhattanLength() < 10:
                return
        x, y = p.x(), p.y()
        if not (ev.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            x, y = self.snapv(x), self.snapv(y)
            # aimantation angulaire 15° depuis le point précédent si proche
            if self.pts:
                px, py = self.pts[-1]
                L = math.hypot(x - px, y - py)
                if L > 1e-9:
                    a = math.degrees(math.atan2(y - py, x - px))
                    a15 = round(a / 15) * 15
                    if abs(a - a15) < 4:
                        L = self.snapv(L)
                        x = round(px + L * math.cos(math.radians(a15)), 4)
                        y = round(py + L * math.sin(math.radians(a15)), 4)
        self.pts.append([x, y])
        self.redraw(); self.changed.emit()
        ev.accept()

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
        P = np.array(self.pts, float) if self.pts else np.zeros((0, 2))
        if len(P) >= 3:
            poly = QtWidgets.QGraphicsPolygonItem(QtGui.QPolygonF([QtCore.QPointF(*q) for q in P]))
            c = QtGui.QColor(S.ACCENT); c.setAlpha(28)
            poly.setBrush(c); poly.setPen(pg.mkPen(None))
            add(poly, -1)
        if len(P) >= 2:
            add(pg.PlotDataItem(P[:, 0], P[:, 1], pen=pg.mkPen(S.ACCENT, width=2)), 1)
        if len(P) >= 3:
            add(pg.PlotDataItem([P[-1, 0], P[0, 0]], [P[-1, 1], P[0, 1]],
                                pen=pg.mkPen(S.ACCENT, width=1, style=Qt.PenStyle.DashLine)), 1)
        n = len(P)
        for i in range(n if n >= 3 else n - 1):
            a, b = P[i], P[(i + 1) % n]
            L = float(np.linalg.norm(b - a))
            if L < 1e-9:
                continue
            m = (a + b) / 2
            d = (b - a) / L
            nrm = np.array([-d[1], d[0]])
            t = pg.TextItem(f"{L:.2f}", color="#ffffff", anchor=(0.5, 0.5),
                            fill=pg.mkBrush(QtGui.QColor(12, 13, 15, 200)))
            t.setPos(*(m - nrm * 0.0))
            add(t, 3)
        for i, q in enumerate(self.pts):
            tg = pg.TargetItem(pos=tuple(q), size=9, symbol="s", pen=pg.mkPen("#ffffff", width=1),
                               brush=pg.mkBrush(S.ACCENT), hoverBrush=pg.mkBrush("#ffffff"), movable=True,
                               label=str(i + 1), labelOpts=dict(color=S.DIM, offset=(7, -7), anchor=(0, 1)))
            tg.sigPositionChangeFinished.connect(lambda it, k=i: self._moved(k, it))
            add(tg, 4)

    def _moved(self, k, it):
        x, y = it.pos().x(), it.pos().y()
        self.pts[k] = [self.snapv(x), self.snapv(y)]
        QtCore.QTimer.singleShot(0, self.redraw)
        self.changed.emit()

    def fit(self):
        if not self.pts:
            return
        P = np.array(self.pts)
        lo, hi = P.min(0), P.max(0)
        m = max(float((hi - lo).max()) * 0.15, 0.1)
        self.getPlotItem().getViewBox().setRange(xRange=(lo[0] - m, hi[0] + m), yRange=(lo[1] - m, hi[1] + m))


class SketchDialog(QtWidgets.QDialog):
    """mode 'shape' : forme de scène ; mode 'speaker' : profil latéral d'enceinte."""

    def __init__(self, parent=None, profile=None, mode="shape", kind="Pièce", plane="XY", height=3.0,
                 symmetric=False, recenter=True, title="Esquisse", extra=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1150, 720)
        self.mode = mode
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        self.canvas = SketchCanvas()
        self.canvas.pts = [list(map(float, p)) for p in (profile or [])]
        self.canvas.origin_marker = mode == "speaker"
        self.canvas.extra = extra or []
        self.canvas.changed.connect(self._sync_table)
        left = QtWidgets.QWidget(); ll = QtWidgets.QVBoxLayout(left); ll.setContentsMargins(0, 0, 0, 0); ll.setSpacing(0)
        hint = QtWidgets.QLabel("  Clic : ajouter un point (aimanté, Maj = libre) · glisser : déplacer · "
                                "clic droit : retirer le dernier · cotes éditables à droite")
        hint.setObjectName("title")
        ll.addWidget(hint); ll.addWidget(self.canvas, 1)
        lay.addWidget(left, 3)

        right = QtWidgets.QWidget(); right.setMinimumWidth(380)
        f = QtWidgets.QFormLayout(right); f.setContentsMargins(12, 10, 12, 12); f.setVerticalSpacing(6)
        lay.addWidget(right, 2)

        def section(t):
            l = QtWidgets.QLabel(t.upper()); l.setObjectName("section"); f.addRow(l)

        section("Esquisse")
        self.snap = QtWidgets.QComboBox()
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
        clr = QtWidgets.QPushButton("Effacer l'esquisse")
        clr.clicked.connect(self._clear)
        f.addRow(clr)

        section("Points et cotes")
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["a", "b", "→ longueur", "→ angle °"])
        self.table.verticalHeader().setDefaultSectionSize(22)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(self._table_edit)
        f.addRow(self.table)
        self.info = QtWidgets.QLabel(); self.info.setObjectName("info"); self.info.setWordWrap(True)
        f.addRow(self.info)

        if mode == "shape":
            section("Extrusion")
            self.kind = QtWidgets.QComboBox(); self.kind.addItems(SHAPE_KINDS); self.kind.setCurrentText(kind)
            f.addRow("Type", self.kind)
            self.plane = QtWidgets.QComboBox()
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
        self.canvas.redraw(); self.canvas.fit()
        self._sync_table()

    # ------------------------------------------------------------------
    def _axes(self):
        if self.mode == "speaker":
            self.canvas.set_axes("avant · f (m)", "haut · u (m)")
            self.table.setHorizontalHeaderLabels(["f", "u", "→ longueur", "→ angle °"])
            return
        a, b, e = PLANE_LABELS[self.plane.currentData()]
        self.canvas.set_axes(f"{a} (m)", f"{b} (m)")
        self.table.setHorizontalHeaderLabels([a, b, "→ longueur", "→ angle °"])

    def _rect(self):
        w, d = fnum(self.rw.text(), 1), fnum(self.rd.text(), 1)
        if self.mode == "speaker":
            self.canvas.pts = [[0, 0], [0, -d], [-w, -d], [-w, 0]]
        else:
            self.canvas.pts = [[0, 0], [w, 0], [w, d], [0, d]]
        self.canvas.redraw(); self.canvas.fit(); self._sync_table()

    def _stairs(self):
        from .demo import stairs_profile
        n = int(fnum(self.sn.text(), 8)); dp = fnum(self.sd.text(), 0.9); r = fnum(self.sr.text(), 0.4)
        self.canvas.pts = stairs_profile(0, dp, r, max(1, n))
        if self.plane.currentData() == "XY":
            self.plane.setCurrentIndex(self.plane.findData("XZ"))
            self.sym.setChecked(True)
            self.kind.setCurrentText("Objet")
            self.height.setText("20")
        self.canvas.redraw(); self.canvas.fit(); self._sync_table()

    def _clear(self):
        self.canvas.pts = []
        self.canvas.redraw(); self._sync_table()

    def _sync_table(self):
        P = self.canvas.pts
        self.table.blockSignals(True)
        n = len(P)
        self.table.setRowCount(n)
        for i, (x, y) in enumerate(P):
            self.table.setItem(i, 0, QtWidgets.QTableWidgetItem(f"{x:.3f}"))
            self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(f"{y:.3f}"))
            if n >= 2:
                j = (i + 1) % n
                L = math.hypot(P[j][0] - x, P[j][1] - y)
                a = math.degrees(math.atan2(P[j][1] - y, P[j][0] - x))
                itL = QtWidgets.QTableWidgetItem(f"{L:.3f}")
                itA = QtWidgets.QTableWidgetItem(f"{a:.1f}")
                if i == n - 1:      # segment de fermeture : calculé
                    for it in (itL, itA):
                        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        it.setForeground(QtGui.QColor(S.DIM))
                self.table.setItem(i, 2, itL); self.table.setItem(i, 3, itA)
            else:
                self.table.setItem(i, 2, QtWidgets.QTableWidgetItem(""))
                self.table.setItem(i, 3, QtWidgets.QTableWidgetItem(""))
        self.table.blockSignals(False)
        if n >= 3:
            A = abs(G.poly_area(P))
            arr = np.array(P)
            ext = arr.max(0) - arr.min(0)
            self.info.setText(f"{n} points · aire {A:.2f} m² · encombrement {ext[0]:.2f} × {ext[1]:.2f} m")
        else:
            self.info.setText("Au moins 3 points sont nécessaires.")

    def _table_edit(self, it):
        r, c = it.row(), it.column()
        v = fnum(it.text())
        P = self.canvas.pts
        if v is None or r >= len(P):
            self._sync_table(); return
        if c in (0, 1):
            P[r][c] = round(v, 4)
        else:
            j = r + 1
            if j >= len(P):
                self._sync_table(); return
            x, y = P[r]
            L = math.hypot(P[j][0] - x, P[j][1] - y)
            a = math.degrees(math.atan2(P[j][1] - y, P[j][0] - x))
            if c == 2:
                L = max(v, 0.0)
            else:
                a = v
            nx, ny = x + L * math.cos(math.radians(a)), y + L * math.sin(math.radians(a))
            dx, dy = nx - P[j][0], ny - P[j][1]
            for k in range(j, len(P)):      # cotes chaînées : la suite se décale
                P[k] = [round(P[k][0] + dx, 4), round(P[k][1] + dy, 4)]
        self.canvas.redraw()
        QtCore.QTimer.singleShot(0, self._sync_table)

    def _accept(self):
        if len(self.canvas.pts) < 3:
            QtWidgets.QMessageBox.warning(self, "Esquisse", "Il faut au moins 3 points.")
            return
        self.accept()

    # résultats
    @property
    def profile(self):
        return [list(map(float, p)) for p in G.ccw(self.canvas.pts)]

    def values(self):
        return dict(profile=self.profile, kind=self.kind.currentText(), plane=self.plane.currentData(),
                    height=fnum(self.height.text(), 3.0), symmetric=self.sym.isChecked(),
                    recenter=self.recenter.isChecked())
