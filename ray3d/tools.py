"""Dialogues d'édition : décaler une sélection, accrocher un élément coin sur coin."""
from __future__ import annotations

import numpy as np
from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import Qt

from . import edit as E
from .widgets import NumField, NoWheelCombo, no_enter_dialog

KIND_LABEL = {"shape": "forme", "assembly": "ensemble", "object": "HP", "group": "groupe", "listener": "écouteur"}


def _fmt(p):
    return f"({p[0]:.3f}, {p[1]:.3f}, {p[2]:.3f})"


def _section(form, text):
    lab = QtWidgets.QLabel(text.upper())
    lab.setObjectName("section")
    form.addRow(lab)


class _Base(QtWidgets.QDialog):
    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            e.accept()
            return
        super().keyPressEvent(e)

    def _buttons(self, form, ok_text):
        bb = QtWidgets.QHBoxLayout()
        ok = QtWidgets.QPushButton(ok_text); ok.setObjectName("primary"); ok.clicked.connect(self.accept)
        ca = QtWidgets.QPushButton("Annuler"); ca.clicked.connect(self.reject)
        bb.addStretch(1); bb.addWidget(ca); bb.addWidget(ok)
        form.addRow(bb)


# --------------------------------------------------------------------------- décaler
class OffsetDialog(_Base):
    """Décalage relatif (dX, dY, dZ) de tous les éléments sélectionnés."""

    def __init__(self, scene, items, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Décaler la sélection")
        self.resize(420, 300)
        f = QtWidgets.QFormLayout(self)
        f.setContentsMargins(14, 12, 14, 12)
        flat = E.expand(scene, items)
        locked = [o for k, o in flat if E.is_locked(scene, k, o)]
        names = ", ".join(getattr(o, "name", "?") for _, o in items[:6]) + (" …" if len(items) > 6 else "")
        info = QtWidgets.QLabel(f"{len(flat)} élément(s) : {names}" +
                                (f"\n🔒 {len(locked)} verrouillé(s), ils ne bougeront pas." if locked else "") +
                                "\nUn HP lié en miroir entraîne son partenaire.")
        info.setObjectName("info"); info.setWordWrap(True)
        f.addRow(info)
        _section(f, "Décalage")
        self.dx = NumField(0.0, -1e4, 1e4, 0.1, 3, " m")
        self.dy = NumField(0.0, -1e4, 1e4, 0.1, 3, " m")
        self.dz = NumField(0.0, -1e4, 1e4, 0.1, 3, " m")
        f.addRow("dX", self.dx); f.addRow("dY", self.dy); f.addRow("dZ", self.dz)
        self.copy = QtWidgets.QCheckBox("Déplacer une copie (l'original reste en place)")
        f.addRow(self.copy)
        self._buttons(f, "Décaler")
        no_enter_dialog(self)
        self.dx.setFocus()

    def vector(self):
        return np.array([self.dx.value(), self.dy.value(), self.dz.value()], float)


# --------------------------------------------------------------------------- accrocher
class SnapDialog(_Base):
    """Amène un coin de l'élément sélectionné sur un coin d'un autre élément, puis le fait
    glisser le long d'une arête. Aperçu en direct ; Annuler remet tout en place."""
    preview = QtCore.Signal(object)     # liste de marqueurs [(pos, couleur, texte)]

    def __init__(self, scene, items, primary, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Accrocher")
        self.resize(560, 560)
        self.setModal(False)
        self.scene = scene
        self.items = items
        self.kind, self.obj = primary
        self.flat = E.expand(scene, items)
        moving = {o.id for _, o in self.flat} | {o.id for _, o in items}
        # positions d'origine (et partenaires miroir) pour annuler
        self.orig = {}
        for k, o in self.flat:
            self.orig[o.id] = (o, o.x, o.y, o.z)
            p = scene.partner(o) if k == "object" else None
            if p is not None:
                self.orig[p.id] = (p, p.x, p.y, p.z)
        self.P_src, self.E_src = E.sorted_points(scene, self.kind, self.obj)

        f = QtWidgets.QFormLayout(self)
        f.setContentsMargins(14, 12, 14, 12)
        f.setVerticalSpacing(6)
        locked = [o for k, o in self.flat if E.is_locked(scene, k, o)]
        lab = QtWidgets.QLabel(f"Élément déplacé : {getattr(self.obj, 'name', '?')} "
                               f"({KIND_LABEL.get(self.kind, self.kind)})"
                               + (f" + {len(self.flat) - 1} autre(s)" if len(self.flat) > 1 else "")
                               + (f"\n🔒 {len(locked)} élément(s) verrouillé(s) ne bougeront pas." if locked else ""))
        lab.setObjectName("info"); lab.setWordWrap(True)
        f.addRow(lab)

        _section(f, "Coin de l'élément déplacé")
        self.c_src = NoWheelCombo()
        for i, p in enumerate(self.P_src):
            self.c_src.addItem(f"{i + 1} · {_fmt(p)}", i)
        f.addRow("Coin", self.c_src)

        _section(f, "Cible")
        self.target = NoWheelCombo()
        self.targets = []
        for kind, coll in (("assembly", scene.assemblies), ("shape", scene.shapes), ("object", scene.objects),
                           ("listener", scene.listeners)):
            for o in coll:
                if o.id in moving or (kind == "shape" and o.assembly and o.assembly in moving):
                    continue
                self.targets.append((kind, o))
                self.target.addItem(f"{o.name}  ·  {KIND_LABEL[kind]}")
        self.target.addItem("Point libre (coordonnées)")
        f.addRow("Élément", self.target)
        self.c_dst = NoWheelCombo()
        f.addRow("Coin cible", self.c_dst)
        self.fx = NumField(0.0, -1e4, 1e4, 0.1, 3, " m")
        self.fy = NumField(0.0, -1e4, 1e4, 0.1, 3, " m")
        self.fz = NumField(0.0, -1e4, 1e4, 0.1, 3, " m")
        free = QtWidgets.QHBoxLayout()
        for w in (self.fx, self.fy, self.fz):
            free.addWidget(w)
        self.free_row = QtWidgets.QWidget(); self.free_row.setLayout(free)
        free.setContentsMargins(0, 0, 0, 0)
        f.addRow("Point libre X · Y · Z", self.free_row)

        _section(f, "Glisser le long d'une arête de la cible")
        self.edge = NoWheelCombo()
        f.addRow("Arête", self.edge)
        self.along = NumField(0.0, -1e4, 1e4, 0.05, 3, " m")
        f.addRow("Distance depuis le coin", self.along)
        hb = QtWidgets.QHBoxLayout()
        for txt, frac in (("Début", 0.0), ("Milieu", 0.5), ("Fin", 1.0)):
            b = QtWidgets.QPushButton(txt)
            b.clicked.connect(lambda _=False, fr=frac: self._set_frac(fr))
            hb.addWidget(b)
        hb.addStretch(1)
        f.addRow(hb)
        self.edge_info = QtWidgets.QLabel(); self.edge_info.setObjectName("info")
        f.addRow(self.edge_info)

        _section(f, "Décalage supplémentaire")
        self.ox = NumField(0.0, -1e4, 1e4, 0.01, 3, " m")
        self.oy = NumField(0.0, -1e4, 1e4, 0.01, 3, " m")
        self.oz = NumField(0.0, -1e4, 1e4, 0.01, 3, " m")
        off = QtWidgets.QHBoxLayout(); off.setContentsMargins(0, 0, 0, 0)
        for w in (self.ox, self.oy, self.oz):
            off.addWidget(w)
        ow = QtWidgets.QWidget(); ow.setLayout(off)
        f.addRow("dX · dY · dZ", ow)
        self.result = QtWidgets.QLabel(); self.result.setObjectName("value"); self.result.setWordWrap(True)
        f.addRow(self.result)
        self._buttons(f, "Accrocher")
        no_enter_dialog(self)

        self.c_src.currentIndexChanged.connect(self.update_preview)
        self.target.currentIndexChanged.connect(self._target_changed)
        self.c_dst.currentIndexChanged.connect(self._dst_changed)
        self.edge.currentIndexChanged.connect(self._edge_changed)
        for w in (self.along, self.ox, self.oy, self.oz, self.fx, self.fy, self.fz):
            w.valueChanged.connect(self.update_preview)
        self.c_src.setCurrentIndex(0)
        self._target_changed()

    # ------------------------------------------------------------------
    def _free(self):
        return self.target.currentIndex() >= len(self.targets)

    def _target_changed(self):
        free = self._free()
        self.free_row.setEnabled(free)
        self.c_dst.setEnabled(not free)
        self.c_dst.blockSignals(True)
        self.c_dst.clear()
        if free:
            self.P_dst, self.E_dst = np.zeros((0, 3)), []
        else:
            k, o = self.targets[self.target.currentIndex()]
            self.P_dst, self.E_dst = E.sorted_points(self.scene, k, o)
            for i, p in enumerate(self.P_dst):
                self.c_dst.addItem(f"{i + 1} · {_fmt(p)}", i)
        self.c_dst.blockSignals(False)
        self._dst_changed()

    def _dst_changed(self):
        self.edge.blockSignals(True)
        self.edge.clear()
        self.edge.addItem("— aucune (coin sur coin)", None)
        if not self._free() and self.c_dst.count():
            k = self.c_dst.currentData()
            for j in E.neighbours(self.E_dst, k):
                L = float(np.linalg.norm(self.P_dst[j] - self.P_dst[k]))
                self.edge.addItem(f"vers le coin {j + 1} · {L:.3f} m", j)
        self.edge.blockSignals(False)
        self._edge_changed()

    def _edge_len(self):
        j = self.edge.currentData()
        if j is None or self._free() or not self.c_dst.count():
            return 0.0
        return float(np.linalg.norm(self.P_dst[j] - self.P_dst[self.c_dst.currentData()]))

    def _edge_changed(self):
        L = self._edge_len()
        self.along.setEnabled(L > 0)
        self.edge_info.setText(f"Longueur de l'arête : {L:.3f} m" if L > 0 else "")
        self.update_preview()

    def _set_frac(self, fr):
        L = self._edge_len()
        if L > 0:
            self.along.setValue(round(L * fr, 4))

    def vector(self):
        if len(self.P_src) == 0:
            return np.zeros(3)
        ks = self.c_src.currentData() or 0
        extra = (self.ox.value(), self.oy.value(), self.oz.value())
        if self._free():
            tgt = np.array([self.fx.value(), self.fy.value(), self.fz.value()])
            return tgt - self.P_src[ks] + np.asarray(extra)
        if not self.c_dst.count():
            return np.zeros(3)
        return E.snap_vector(self.P_src, ks, self.P_dst, self.c_dst.currentData(), self.edge.currentData(),
                             self.along.value(), extra)

    # ------------------------------------------------------------------ aperçu
    def restore(self):
        for oid, (o, x, y, z) in self.orig.items():
            o.x, o.y, o.z = x, y, z

    def update_preview(self, *_):
        self.restore()
        v = self.vector()
        E.translate(self.scene, self.items, v)
        self.scene.sync()
        ks = self.c_src.currentData() or 0
        markers = []
        if len(self.P_src):
            markers.append((self.P_src[ks] + v, "#b6ff3a", f"coin {ks + 1}"))
        if not self._free() and self.c_dst.count():
            kd = self.c_dst.currentData()
            markers.append((self.P_dst[kd], "#ff3aa8", f"cible {kd + 1}"))
            j = self.edge.currentData()
            if j is not None:
                markers.append((self.P_dst[j], "#ff3aa8", f"{j + 1}"))
        self.result.setText(f"Déplacement : dX {v[0]:+.3f} · dY {v[1]:+.3f} · dZ {v[2]:+.3f} m")
        self.preview.emit(markers)

    def reject(self):
        self.restore()
        self.scene.sync()
        self.preview.emit([])
        super().reject()

    def accept(self):
        self.update_preview()
        self.preview.emit([])
        super().accept()
