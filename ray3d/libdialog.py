"""Bibliothèque de HP : profil extrudé, éléments sonores, arêtes d'accroche, aperçus 2D et 3D,
import / export de directivités et de modèles."""
from __future__ import annotations

import copy
import math
import os

import numpy as np
import pyqtgraph as pg
import pyqtgraph.opengl as gl
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from . import style as S
from . import geometry as G
from . import importers as IMP
from .model import Scene, SpeakerModel, Element, PATTERNS, new_id, frame
from .sketch import SketchDialog, fnum
from .widgets import no_enter_dialog

ECOLS = [("name", "Nom"), ("f", "f"), ("l", "l"), ("u", "u"), ("az", "Az °"), ("el", "Site °"),
         ("pattern", "Directivité"), ("cov_h", "Ouv. H"), ("cov_v", "Ouv. V"), ("level", "dB@1m"),
         ("delay", "Délai ms"), ("balloon", "Mesure")]
ELEM_COLORS = ["#ffffff", "#3ec1ff", "#b6ff3a", "#ff3aa8", "#ffd23a", "#9b7bff"]


class ComboDelegate(QtWidgets.QStyledItemDelegate):
    """Liste déroulante éditée dans la cellule (pas de widget permanent)."""

    def __init__(self, items, parent=None):
        super().__init__(parent)
        self.items = items

    def createEditor(self, parent, option, index):
        cb = QtWidgets.QComboBox(parent)
        cb.addItems(self.items)
        cb.activated.connect(lambda _: self.commitData.emit(cb))
        return cb

    def setEditorData(self, editor, index):
        editor.setCurrentText(index.data() or self.items[0])

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText())


class SpeakerPreview3D(gl.GLViewWidget):
    """Petite vue 3D de l'enceinte : volume, éléments (position + axe + cône -6 dB), arêtes, accroche."""

    def __init__(self):
        super().__init__()
        self.setBackgroundColor(S.BG)
        self.setMinimumHeight(260)
        self._items = []
        self.setCameraPosition(distance=2.2, elevation=18, azimuth=-140)

    def _add(self, it):
        self.addItem(it)
        self._items.append(it)

    def show_model(self, m: SpeakerModel):
        for it in self._items:
            self.removeItem(it)
        self._items = []
        if m is None:
            return
        faces = m.local_faces()
        V, F = G.faces_mesh(faces)
        if len(F):
            mesh = gl.GLMeshItem(vertexes=V, faces=F, color=S.hex_rgba("#5a6170", 0.35), smooth=False,
                                 shader="shaded", glOptions="translucent")
            self._add(mesh)
            self._add(gl.GLLinePlotItem(pos=G.faces_edges(faces), mode="lines", color=(0.85, 0.85, 0.9, 0.7),
                                        width=1, antialias=True))
        size = float(np.ptp(V, axis=0).max()) if len(V) else 0.5
        L = max(size * 0.8, 0.3)
        # repère d'accroche
        ax = np.array([[0, 0, 0], [L * 0.3, 0, 0], [0, 0, 0], [0, L * 0.3, 0], [0, 0, 0], [0, 0, L * 0.3]])
        cols = np.array([(1, .4, .1, 1)] * 2 + [(.3, .8, 1, 1)] * 2 + [(.7, 1, .3, 1)] * 2)
        self._add(gl.GLLinePlotItem(pos=ax, mode="lines", color=cols, width=2))
        self._add(gl.GLTextItem(pos=np.array([0, 0, L * 0.35]), text="accroche", color=QtGui.QColor("#ffffff"),
                                font=QtGui.QFont("DejaVu Sans", 8)))
        # arêtes d'accroche (sur toute la largeur)
        w = m.width / 2
        for h, col in ((m.top_hinge, "#3ec1ff"), (m.bottom_hinge, "#b6ff3a")):
            seg = np.array([[h[0], -w, h[1]], [h[0], w, h[1]]])
            self._add(gl.GLLinePlotItem(pos=seg, mode="lines", color=S.hex_rgba(col), width=3))
        # éléments
        for k, e in enumerate(m.elements):
            col = ELEM_COLORS[k % len(ELEM_COLORS)]
            p = np.array([e.f, e.l, e.u])
            self._add(gl.GLScatterPlotItem(pos=p[None], size=11, color=S.hex_rgba(col), pxMode=True))
            f, l, u = frame(e.az, e.el)
            self._add(gl.GLLinePlotItem(pos=np.array([p, p + f * L]), mode="lines", color=S.hex_rgba(col),
                                        width=2))
            if e.pattern in ("Pavillon",):
                hh, hv = math.radians(min(e.cov_h, 170) / 2), math.radians(min(e.cov_v, 170) / 2)
                psi = np.linspace(0, 2 * np.pi, 40, endpoint=False)
                th = 1 / np.sqrt(np.cos(psi) ** 2 / hh ** 2 + np.sin(psi) ** 2 / hv ** 2)
                d = (np.cos(th)[:, None] * f + np.sin(th)[:, None] * (np.cos(psi)[:, None] * l + np.sin(psi)[:, None] * u))
                ring = p + d * L * 0.7
                Vc = np.vstack([p[None], ring])
                Fc = np.array([[0, i + 1, (i + 1) % 40 + 1] for i in range(40)])
                self._add(gl.GLMeshItem(vertexes=Vc, faces=Fc, color=S.hex_rgba(col, 0.18), smooth=False,
                                        glOptions="translucent"))
            self._add(gl.GLTextItem(pos=p + u * 0.04, text=e.name, color=QtGui.QColor(col),
                                    font=QtGui.QFont("DejaVu Sans", 8)))
        c = V.mean(0) if len(V) else np.zeros(3)
        self.setCameraPosition(pos=pg.Vector(*c), distance=max(size * 2.6, 1.0))


class LibraryDialog(QtWidgets.QDialog):
    def __init__(self, scene: Scene, parent=None, select=None):
        super().__init__(parent)
        self.setWindowTitle("Bibliothèque de haut-parleurs")
        self.resize(1450, 860)
        self.scene = scene
        lay = QtWidgets.QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)

        # liste
        left = QtWidgets.QWidget(); left.setFixedWidth(250)
        ll = QtWidgets.QVBoxLayout(left); ll.setContentsMargins(10, 10, 10, 10)
        t = QtWidgets.QLabel("MODÈLES"); t.setObjectName("section"); ll.addWidget(t)
        self.list = QtWidgets.QListWidget()
        self.list.currentRowChanged.connect(self._select)
        ll.addWidget(self.list, 1)
        for text, fn in (("Nouveau", self._new), ("Dupliquer", self._dup), ("Supprimer", self._del),
                         ("Importer un modèle…", self._import_model), ("Exporter le modèle…", self._export_model)):
            b = QtWidgets.QPushButton(text); b.clicked.connect(fn); ll.addWidget(b)
        lay.addWidget(left)

        # édition
        mid = QtWidgets.QWidget()
        f = QtWidgets.QFormLayout(mid); f.setContentsMargins(12, 10, 12, 10); f.setVerticalSpacing(6)

        def section(t):
            l = QtWidgets.QLabel(t.upper()); l.setObjectName("section"); f.addRow(l)
        section("Enceinte")
        self.name = QtWidgets.QLineEdit(); self.name.editingFinished.connect(self._apply_name)
        f.addRow("Nom", self.name)
        self.width = QtWidgets.QLineEdit(); self.width.editingFinished.connect(self._apply_fields)
        f.addRow("Largeur (extrusion, m)", self.width)
        bp = QtWidgets.QPushButton("Éditer le profil latéral…"); bp.clicked.connect(self._edit_profile)
        f.addRow("Profil", bp)
        section("Accroche (line array)")
        h1 = QtWidgets.QHBoxLayout(); self.thf = QtWidgets.QLineEdit(); self.thu = QtWidgets.QLineEdit()
        h1.addWidget(self.thf); h1.addWidget(self.thu)
        f.addRow("Arête haute f · u", h1)
        h2 = QtWidgets.QHBoxLayout(); self.bhf = QtWidgets.QLineEdit(); self.bhu = QtWidgets.QLineEdit()
        h2.addWidget(self.bhf); h2.addWidget(self.bhu)
        f.addRow("Arête basse f · u", h2)
        for w in (self.thf, self.thu, self.bhf, self.bhu):
            w.editingFinished.connect(self._apply_fields)
        self.rng = QtWidgets.QLabel(); self.rng.setObjectName("value"); self.rng.setWordWrap(True)
        f.addRow(self.rng)
        note = QtWidgets.QLabel("L'origine (0, 0) du profil est le point d'accroche. Dans un line array vertical "
                                "ou couché, l'arête haute d'une boîte vient sur l'arête basse de la précédente ; "
                                "côte à côte, les boîtes s'articulent sur leurs arêtes verticales arrière.")
        note.setObjectName("info"); note.setWordWrap(True)
        f.addRow(note)
        section("Éléments sonores (f avant · l gauche · u haut, en m)")
        self.etable = QtWidgets.QTableWidget(0, len(ECOLS))
        self.etable.setHorizontalHeaderLabels([c[1] for c in ECOLS])
        self.etable.verticalHeader().setVisible(False)
        self.etable.verticalHeader().setDefaultSectionSize(24)
        self.etable.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.etable.horizontalHeader().setStretchLastSection(True)
        self.etable.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked |
                                    QtWidgets.QAbstractItemView.EditTrigger.SelectedClicked |
                                    QtWidgets.QAbstractItemView.EditTrigger.EditKeyPressed |
                                    QtWidgets.QAbstractItemView.EditTrigger.AnyKeyPressed)
        self.etable.setItemDelegateForColumn(6, ComboDelegate(PATTERNS, self.etable))
        self.etable.itemChanged.connect(self._elem_edit)
        self.etable.setMinimumHeight(170)
        f.addRow(self.etable)
        eb = QtWidgets.QHBoxLayout()
        for text, fn in (("+ élément", self._add_elem), ("− élément", self._del_elem),
                         ("Importer une directivité…", self._import_dir), ("Effacer la mesure", self._clear_dir)):
            b = QtWidgets.QPushButton(text); b.clicked.connect(fn); eb.addWidget(b)
        eb.addStretch(1)
        f.addRow(eb)
        self.dir_info = QtWidgets.QLabel(); self.dir_info.setObjectName("info"); self.dir_info.setWordWrap(True)
        f.addRow(self.dir_info)
        bb = QtWidgets.QPushButton("Fermer"); bb.setObjectName("primary"); bb.clicked.connect(self.accept)
        f.addRow(bb)
        mid.setMinimumWidth(600)
        lay.addWidget(mid)

        # aperçus
        right = QtWidgets.QSplitter(Qt.Orientation.Vertical)
        self.p3d = SpeakerPreview3D()
        w3 = QtWidgets.QWidget(); l3 = QtWidgets.QVBoxLayout(w3); l3.setContentsMargins(0, 0, 0, 0); l3.setSpacing(0)
        t3 = QtWidgets.QLabel("APERÇU 3D · ÉLÉMENTS, AXES, CÔNES -6 dB, ARÊTES D'ACCROCHE"); t3.setObjectName("title")
        l3.addWidget(t3); l3.addWidget(self.p3d, 1)
        right.addWidget(w3)
        self.prev = pg.PlotWidget()
        self.prev.setBackground(S.BG)
        pi = self.prev.getPlotItem(); pi.hideButtons(); pi.setMenuEnabled(False)
        self.prev.setAspectLocked(True); pi.showGrid(x=True, y=True, alpha=0.1)
        for a in ("bottom", "left"):
            pi.getAxis(a).enableAutoSIPrefix(False)
        pi.getAxis("bottom").setLabel("avant · f (m)", color=S.DIM)
        pi.getAxis("left").setLabel("haut · u (m)", color=S.DIM)
        self.splay_prev = QtWidgets.QLineEdit("6")
        self.splay_prev.editingFinished.connect(self._preview)
        pw = QtWidgets.QWidget(); pl = QtWidgets.QVBoxLayout(pw); pl.setContentsMargins(0, 0, 0, 0); pl.setSpacing(0)
        bar = QtWidgets.QHBoxLayout()
        tl = QtWidgets.QLabel("PROFIL · 3 BOÎTES ACCROCHÉES, SPLAY (°)"); tl.setObjectName("title")
        bar.addWidget(tl); bar.addStretch(1); self.splay_prev.setFixedWidth(60); bar.addWidget(self.splay_prev)
        pl.addLayout(bar); pl.addWidget(self.prev, 1)
        right.addWidget(pw)
        right.setSizes([430, 400])
        lay.addWidget(right, 1)

        self._fill_list(select)
        no_enter_dialog(self)

    def keyPressEvent(self, e):
        # Entrée valide le champ en cours sans déclencher de bouton (ni fermer le dialogue)
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            fw = self.focusWidget()
            if isinstance(fw, QtWidgets.QLineEdit):
                fw.editingFinished.emit()
            e.accept()
            return
        super().keyPressEvent(e)

    # ------------------------------------------------------------------
    @property
    def m(self) -> SpeakerModel | None:
        r = self.list.currentRow()
        return self.scene.models[r] if 0 <= r < len(self.scene.models) else None

    def _fill_list(self, select=None):
        self.list.blockSignals(True)
        self.list.clear()
        for m in self.scene.models:
            used = sum(o.model == m.id for o in self.scene.objects)
            self.list.addItem(f"{m.name}" + (f"   ·{used}" if used else ""))
        self.list.blockSignals(False)
        idx = next((i for i, m in enumerate(self.scene.models) if m.id == select), 0)
        self.list.setCurrentRow(idx if self.scene.models else -1)
        self._select(self.list.currentRow())

    def _select(self, r):
        m = self.m
        if m is None:
            return
        self.name.setText(m.name)
        self.width.setText(f"{m.width:g}")
        self.thf.setText(f"{m.top_hinge[0]:g}"); self.thu.setText(f"{m.top_hinge[1]:g}")
        self.bhf.setText(f"{m.bottom_hinge[0]:g}"); self.bhu.setText(f"{m.bottom_hinge[1]:g}")
        self._fill_elems()
        self._preview()

    def _fill_elems(self):
        m = self.m
        self.etable.blockSignals(True)
        self.etable.clearContents()
        self.etable.setRowCount(len(m.elements) if m else 0)
        for r, e in enumerate(m.elements if m else []):
            for c, (attr, _) in enumerate(ECOLS):
                v = getattr(e, attr)
                if attr == "balloon":
                    it = QtWidgets.QTableWidgetItem(f"{len(v['freqs'])} bandes" if v else "—")
                    it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    it.setForeground(QtGui.QColor(S.ACCENT if v else S.DIM))
                elif attr == "name":
                    it = QtWidgets.QTableWidgetItem(v)
                    it.setForeground(QtGui.QColor(ELEM_COLORS[r % len(ELEM_COLORS)]))
                else:
                    it = QtWidgets.QTableWidgetItem(v if isinstance(v, str) else f"{v:g}")
                self.etable.setItem(r, c, it)
        self.etable.blockSignals(False)
        self._dir_info()

    def _dir_info(self):
        m = self.m
        txt = []
        for e in (m.elements if m else []):
            if e.balloon:
                h, v = IMP.coverage_from_balloon(e.balloon, 1000)
                txt.append(f"{e.name} : mesure {e.balloon.get('source', '')}, "
                           f"{e.balloon['freqs'][0]:g}–{e.balloon['freqs'][-1]:g} Hz, ≈ {h:.0f}° × {v:.0f}° à 1 kHz")
        self.dir_info.setText("\n".join(txt) if txt else
                              "Importer une directivité : polaires H/V texte (.txt, .csv) ou SOFA AES69 (.sofa). "
                              "La mesure s'applique à l'élément sélectionné et passe sa directivité en « Mesuré ».")

    def _elem_edit(self, it):
        m = self.m
        if m is None or it.row() >= len(m.elements):
            return
        e = m.elements[it.row()]
        attr = ECOLS[it.column()][0]
        if attr == "balloon":
            return
        if attr == "name":
            e.name = it.text()
        elif attr == "pattern":
            if it.text() in PATTERNS:
                e.pattern = it.text()
        else:
            v = fnum(it.text())
            if v is not None:
                setattr(e, attr, v)
            self.etable.blockSignals(True)
            it.setText(f"{getattr(e, attr):g}")
            self.etable.blockSignals(False)
        self._preview()

    def _cur_elem(self):
        m = self.m
        if m is None or not m.elements:
            return None
        r = self.etable.currentRow()
        return m.elements[r if 0 <= r < len(m.elements) else 0]

    def _add_elem(self):
        m = self.m
        if m is None:
            return
        base = copy.deepcopy(m.elements[-1]) if m.elements else Element()
        base.name = f"E{len(m.elements) + 1}"
        base.balloon = None if base.pattern != "Mesuré" else base.balloon
        m.elements.append(base)
        self._fill_elems(); self._preview()

    def _del_elem(self):
        m = self.m
        r = self.etable.currentRow()
        if m is None or not m.elements:
            return
        m.elements.pop(r if 0 <= r < len(m.elements) else -1)
        self._fill_elems(); self._preview()

    def _import_dir(self):
        e = self._cur_elem()
        if e is None:
            QtWidgets.QMessageBox.information(self, "Directivité", "Ajoutez d'abord un élément.")
            return
        p, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, f"Directivité pour « {e.name} »", "",
            "Directivités (*.txt *.csv *.tab *.sofa *.gll *.xhn *.cf1 *.cf2);;Tous (*)")
        if not p:
            return
        try:
            b = IMP.read_directivity(p)
        except IMP.ImportErrorMsg as ex:
            QtWidgets.QMessageBox.warning(self, "Import", str(ex)); return
        except Exception as ex:
            QtWidgets.QMessageBox.warning(self, "Import", f"Lecture impossible :\n{ex}"); return
        b["file"] = os.path.basename(p)
        e.balloon = b
        e.pattern = "Mesuré"
        e.cov_h, e.cov_v = IMP.coverage_from_balloon(b, 1000)
        self._fill_elems(); self._preview()

    def _clear_dir(self):
        e = self._cur_elem()
        if e is not None and e.balloon:
            e.balloon = None
            if e.pattern == "Mesuré":
                e.pattern = "Pavillon"
            self._fill_elems(); self._preview()

    def _apply_name(self):
        if self.m:
            self.m.name = self.name.text()
            self._fill_list(self.m.id)

    def _apply_fields(self):
        m = self.m
        if m is None:
            return
        m.width = max(fnum(self.width.text(), m.width), 0.01)
        m.top_hinge = [fnum(self.thf.text(), m.top_hinge[0]), fnum(self.thu.text(), m.top_hinge[1])]
        m.bottom_hinge = [fnum(self.bhf.text(), m.bottom_hinge[0]), fnum(self.bhu.text(), m.bottom_hinge[1])]
        self._preview()

    def _edit_profile(self):
        m = self.m
        if m is None:
            return
        extra = [(m.top_hinge, "arête haute", "#3ec1ff"), (m.bottom_hinge, "arête basse", "#b6ff3a")]
        extra += [((e.f, e.u), e.name, ELEM_COLORS[k % len(ELEM_COLORS)]) for k, e in enumerate(m.elements)]
        dlg = SketchDialog(self, m.profile, mode="speaker", title=f"Profil latéral · {m.name}", extra=extra)
        if dlg.exec():
            m.profile = dlg.profile
            self._preview()

    def _new(self):
        m = SpeakerModel(f"Modèle {len(self.scene.models) + 1}")
        self.scene.models.append(m)
        self._fill_list(m.id)

    def _dup(self):
        if self.m is None:
            return
        m = copy.deepcopy(self.m)
        m.id = new_id(); m.name += " copie"
        self.scene.models.append(m)
        self._fill_list(m.id)

    def _del(self):
        m = self.m
        if m is None:
            return
        if any(o.model == m.id for o in self.scene.objects):
            QtWidgets.QMessageBox.information(self, "Supprimer", "Ce modèle est utilisé dans la scène.")
            return
        if len(self.scene.models) <= 1:
            return
        self.scene.models.remove(m)
        self._fill_list()

    def _import_model(self):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Importer un modèle", "", "Modèle Ray 3D (*.r3dspk *.json)")
        if not p:
            return
        try:
            m = IMP.import_model(p)
        except Exception as ex:
            QtWidgets.QMessageBox.warning(self, "Import", f"Lecture impossible :\n{ex}"); return
        self.scene.models.append(m)
        self._fill_list(m.id)

    def _export_model(self):
        m = self.m
        if m is None:
            return
        p, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Exporter le modèle", f"{m.name}.r3dspk",
                                                     "Modèle Ray 3D (*.r3dspk)")
        if p:
            IMP.export_model(m, p)

    # ------------------------------------------------------------------
    def _preview(self):
        m = self.m
        self.p3d.show_model(m)
        pi = self.prev.getPlotItem()
        pi.clear()
        if m is None:
            return
        lo, hi = m.splay_range()
        lo2, hi2 = m.splay_range("Côte à côte →")
        self.rng.setText(f"Écart entre arêtes {np.linalg.norm(np.subtract(m.top_hinge, m.bottom_hinge)):.3f} m\n"
                         f"Splay sans collision · vertical / couché : {max(lo, -45):.1f}° … {hi:.1f}°"
                         f" · côte à côte : {lo2:.1f}° … {hi2:.1f}°")
        s = fnum(self.splay_prev.text(), 6.0)
        prof = np.asarray(G.ccw(m.profile), float)
        if len(prof) < 3:
            return

        def R(a):
            t = math.radians(a)
            return np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])
        polys, th, P = [prof], 0.0, np.zeros(2)
        for i in range(2):
            bh = P + R(th) @ np.asarray(m.bottom_hinge, float)
            th -= s
            P = bh - R(th) @ np.asarray(m.top_hinge, float)
            polys.append(prof @ R(th).T + P)
        collide = s > hi + 1e-6 or s < lo - 1e-6
        for k, q in enumerate(polys):
            col = QtGui.QColor("#ff5b5b" if (collide and k > 0) else S.ACCENT)
            col.setAlpha(60 if k == 0 else (110 if collide else 30))
            poly = QtWidgets.QGraphicsPolygonItem(QtGui.QPolygonF([QtCore.QPointF(*p) for p in q]))
            poly.setBrush(col)
            poly.setPen(pg.mkPen(S.ACCENT if k == 0 else S.DIM, width=1.5 if k == 0 else 1))
            pi.addItem(poly)
        pi.addItem(pg.PlotDataItem([-0.05, 0.05, np.nan, 0, 0], [0, 0, np.nan, -0.05, 0.05],
                                   connect="finite", pen=pg.mkPen("#ffffff", width=1.5)))
        for pt, lab, col in ((m.top_hinge, "arête haute", "#3ec1ff"), (m.bottom_hinge, "arête basse", "#b6ff3a")):
            pi.addItem(pg.ScatterPlotItem([pt[0]], [pt[1]], size=10, symbol="d", pen=pg.mkPen(col),
                                          brush=pg.mkBrush(col)))
            t = pg.TextItem(lab, color=col, anchor=(1.05, 0.5)); t.setPos(*pt); pi.addItem(t)
        t = pg.TextItem("accroche", color="#ffffff", anchor=(-0.1, 1.1)); t.setPos(0, 0); pi.addItem(t)
        for k, e in enumerate(m.elements):
            a = math.radians(e.el)
            L = 0.25
            col = ELEM_COLORS[k % len(ELEM_COLORS)]
            pi.addItem(pg.PlotDataItem([e.f, e.f + L * math.cos(a)], [e.u, e.u + L * math.sin(a)],
                                       pen=pg.mkPen(col, width=1.5)))
            if e.pattern == "Pavillon":
                hv = math.radians(min(e.cov_v, 179) / 2)
                for sg in (-1, 1):
                    pi.addItem(pg.PlotDataItem([e.f, e.f + L * 1.6 * math.cos(a + sg * hv)],
                                               [e.u, e.u + L * 1.6 * math.sin(a + sg * hv)],
                                               pen=pg.mkPen(col, width=1, style=Qt.PenStyle.DashLine)))
            pi.addItem(pg.ScatterPlotItem([e.f], [e.u], size=8, pen=None, brush=pg.mkBrush(col)))
            t = pg.TextItem(e.name, color=col, anchor=(0, 0)); t.setPos(e.f + 0.02, e.u - 0.02); pi.addItem(t)
        allp = np.vstack(polys)
        a0, a1 = allp.min(0), allp.max(0)
        mrg = 0.2
        pi.getViewBox().setRange(xRange=(a0[0] - mrg, a1[0] + mrg + 0.3), yRange=(a0[1] - mrg, a1[1] + mrg))
