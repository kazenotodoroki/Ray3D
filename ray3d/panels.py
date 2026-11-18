"""Panneaux : propriétés, affichage, line array, délais, réflexions."""
from __future__ import annotations

import math

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from . import style as S
from .model import Scene, SHAPE_KINDS, PATTERNS, ORIENTS, speed_of_sound
from . import acoustics as A
from .widgets import NumField, NoWheelCombo

FREQS = ["63", "125", "250", "500", "1000", "2000", "4000", "8000", "16000"]


# --------------------------------------------------------------------------- liaison widgets <-> objet
class Binder(QtCore.QObject):
    """Construit un formulaire lié aux attributs d'un objet."""
    changed = QtCore.Signal(str)

    def __init__(self, form: QtWidgets.QFormLayout, getter):
        super().__init__()
        self.form = form
        self.get = getter
        self.w = {}
        self.conds = {}

    def section(self, text):
        lab = QtWidgets.QLabel(text.upper())
        lab.setObjectName("section")
        self.form.addRow(lab)

    def info(self, text=""):
        lab = QtWidgets.QLabel(text)
        lab.setObjectName("info")
        lab.setWordWrap(True)
        self.form.addRow(lab)
        return lab

    def add(self, attr, label, kind="float", lo=-1e4, hi=1e4, step=0.1, dec=2, suffix="",
            choices=None, enabled=True, tip=None):
        obj = self.get()
        v = getattr(obj, attr)
        if kind == "float":
            w = NumField(float(v), lo, hi, step, dec, suffix)
            w.valueChanged.connect(lambda val, a=attr: self._set(a, float(val)))
        elif kind == "int":
            w = NumField(int(v), int(lo), int(hi), 1, 0, suffix, integer=True)
            w.valueChanged.connect(lambda val, a=attr: self._set(a, int(val)))
        elif kind == "str":
            w = QtWidgets.QLineEdit(str(v))
            w.editingFinished.connect(lambda a=attr, ww=w: self._set(a, ww.text()))
        elif kind == "choice":
            w = NoWheelCombo()
            for c in choices:
                if isinstance(c, tuple):
                    w.addItem(c[0], c[1])
                else:
                    w.addItem(str(c), c)
            i = w.findData(v)
            w.setCurrentIndex(max(i, 0))
            w.currentIndexChanged.connect(lambda i, a=attr, ww=w: self._set(a, ww.itemData(i)))
        elif kind == "freq":
            w = NoWheelCombo()
            w.setEditable(True)
            w.addItems(FREQS)
            w.setCurrentText(f"{v:g}")
            w.lineEdit().editingFinished.connect(lambda a=attr, ww=w: self._set_freq(a, ww))
            w.activated.connect(lambda i, a=attr, ww=w: self._set_freq(a, ww))
        elif kind == "bool":
            w = QtWidgets.QCheckBox(label)
            w.setChecked(bool(v))
            w.toggled.connect(lambda val, a=attr: self._set(a, bool(val)))
        elif kind == "color":
            w = QtWidgets.QPushButton()
            self._paint_color(w, v)
            w.clicked.connect(lambda _=False, a=attr, ww=w: self._pick_color(a, ww))
        elif kind == "list":
            w = QtWidgets.QLineEdit(", ".join(f"{x:g}" for x in v))
            w.editingFinished.connect(lambda a=attr, ww=w: self._set_list(a, ww))
        else:
            raise ValueError(kind)
        w.setEnabled(enabled)
        if tip:
            w.setToolTip(tip)
        if kind == "bool":
            self.form.addRow(w)
        else:
            self.form.addRow(label, w)
        self.w[attr] = (w, kind)
        return w

    def _set(self, attr, val):
        obj = self.get()
        if getattr(obj, attr) == val:
            return
        setattr(obj, attr, val)
        self.changed.emit(attr)

    def _set_freq(self, attr, w):
        try:
            v = float(w.currentText().replace(",", "."))
        except ValueError:
            return
        self._set(attr, min(max(v, 20.0), 20000.0))

    def _set_list(self, attr, w):
        try:
            vals = [float(x) for x in w.text().replace(";", ",").split(",") if x.strip()]
        except ValueError:
            return
        self._set(attr, vals)

    def _paint_color(self, w, c):
        w.setText(c)
        w.setStyleSheet(f"QPushButton {{ background: {c}; color: #000; border: 1px solid {S.BORDER}; }}")

    def _pick_color(self, attr, w):
        c = QtWidgets.QColorDialog.getColor(QtGui.QColor(getattr(self.get(), attr)), None, "Couleur")
        if c.isValid():
            self._paint_color(w, c.name())
            self._set(attr, c.name())

    def load(self):
        obj = self.get()
        for attr, (w, kind) in self.w.items():
            v = getattr(obj, attr)
            w.blockSignals(True)
            if kind == "float":
                w.setValue(float(v))
            elif kind == "int":
                w.setValue(int(v))
            elif kind == "str":
                w.setText(str(v))
            elif kind == "choice":
                w.setCurrentIndex(max(w.findData(v), 0))
            elif kind == "freq":
                w.setCurrentText(f"{v:g}")
            elif kind == "bool":
                w.setChecked(bool(v))
            elif kind == "color":
                self._paint_color(w, v)
            elif kind == "list":
                w.setText(", ".join(f"{x:g}" for x in v))
            w.blockSignals(False)


def scroll_form():
    host = QtWidgets.QWidget()
    form = QtWidgets.QFormLayout(host)
    form.setContentsMargins(10, 6, 10, 10)
    form.setHorizontalSpacing(10)
    form.setVerticalSpacing(5)
    form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    sa = QtWidgets.QScrollArea()
    sa.setWidgetResizable(True)
    sa.setWidget(host)
    return sa, form


def make_table(headers, stretch=None):
    t = CopyTable(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
    t.setAlternatingRowColors(True)
    t.horizontalHeader().setStretchLastSection(True)
    t.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
    if stretch is not None:
        t.horizontalHeader().setStretchLastSection(False)
        t.horizontalHeader().setSectionResizeMode(stretch, QtWidgets.QHeaderView.ResizeMode.Stretch)
        t.setWordWrap(False)
        t.setTextElideMode(Qt.TextElideMode.ElideMiddle)
    t.verticalHeader().setDefaultSectionSize(22)
    t.setShowGrid(False)
    return t


class CopyTable(QtWidgets.QTableWidget):
    """Tableau dont Ctrl+C copie les cellules sélectionnées (tabulations / lignes)."""

    def keyPressEvent(self, e):
        if e.matches(QtGui.QKeySequence.StandardKey.Copy):
            rows = {}
            for it in self.selectedItems():
                rows.setdefault(it.row(), {})[it.column()] = it.text()
            txt = "\n".join("\t".join(r[c] for c in sorted(r)) for _, r in sorted(rows.items()))
            QtWidgets.QApplication.clipboard().setText(txt)
            return
        super().keyPressEvent(e)


def cell(text, color=None, align_right=True):
    it = QtWidgets.QTableWidgetItem(text)
    if align_right:
        it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    if color:
        it.setForeground(QtGui.QColor(color))
    return it


# --------------------------------------------------------------------------- propriétés
class PropertyEditor(QtWidgets.QWidget):
    changed = QtCore.Signal(bool)          # structural
    editSketch = QtCore.Signal(object)
    recenter = QtCore.Signal(object)
    unlink = QtCore.Signal(object)
    openLibrary = QtCore.Signal(str)
    action = QtCore.Signal(str)            # "snap", "offset", "save_ensemble", "ungroup"

    STRUCT = {"name", "kind", "group", "color", "n", "main", "model", "mute", "locked", "orient"}

    def __init__(self, scene_getter):
        super().__init__()
        self.scene = scene_getter
        self.lay = QtWidgets.QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(0)
        self.kind, self.obj = None, None
        self.body = None
        self.info_lab = None
        self.binder = None
        self.corner_table = None
        self.set_object(None, None)

    def set_object(self, kind, obj):
        self.kind, self.obj = kind, obj
        self.rebuild()

    def _button(self, form, text, fn, primary=False):
        b = QtWidgets.QPushButton(text)
        if primary:
            b.setObjectName("primary")
        b.clicked.connect(fn)
        form.addRow(b)
        return b

    def rebuild(self):
        if self.body is not None:
            self.lay.removeWidget(self.body)
            self.body.deleteLater()
        sa, form = scroll_form()
        self.body = sa
        self.lay.addWidget(sa)
        self.info_lab = None
        self.binder = None
        self.corner_table = None
        sc, o, k = self.scene(), self.obj, self.kind
        if o is None:
            lab = QtWidgets.QLabel("Sélectionnez un élément de la scène.\n\nGlissez un HP, un line array ou "
                                   "une rangée sur un groupe dans l'arbre pour l'y déplacer.")
            lab.setObjectName("info"); lab.setWordWrap(True)
            form.addRow(lab)
            return
        b = Binder(form, lambda: o)
        b.changed.connect(self._on_change)
        self.binder = b
        pos = dict(suffix=" m", step=0.05, dec=3)
        ang = dict(lo=-360, hi=360, step=0.5, dec=1, suffix=" °")
        if k == "shape":
            asm = sc.assembly(o.assembly) if o.assembly else None
            lk = o.locked or bool(asm and asm.locked)
            b.section("Forme")
            b.add("name", "Nom", "str")
            b.add("kind", "Type", "choice", choices=SHAPE_KINDS)
            if asm is not None:
                b.info(f"Fait partie de l'ensemble « {asm.name} »" + (" (verrouillé)" if asm.locked else ""))
            b.add("locked", "🔒 Position verrouillée", "bool")
            self._button(form, "Éditer l'esquisse et l'extrusion…", lambda: self.editSketch.emit(o), True)
            b.section("Placement")
            for a in ("x", "y", "z"):
                b.add(a, f"Décalage {a.upper()}", enabled=not lk, **pos)
            b.add("rot", "Rotation Z", enabled=not lk, **ang)
            b.add("tilt", "Inclinaison", lo=-80, hi=80, step=1, dec=1, suffix=" °", enabled=not lk,
                  tip="Rotation qui fait monter le côté +X (surfaces, rampes)")
            self._place_buttons(form, lk)
            self._button(form, "Centrer sur l'origine · sol à z = 0", lambda: self.recenter.emit(o)).setEnabled(not lk)
            if o.kind != "Surface":
                b.add("height", "Extrusion", lo=0.01, hi=500, step=0.1, suffix=" m")
                b.add("symmetric", "Extrusion symétrique", "bool")
            b.section("Acoustique")
            b.add("absorption", "Absorption α", lo=0, hi=1, step=0.05)
            b.add("audience", "Zone public (carte SPL)", "bool")
            self.info_lab = b.info()
            self._corners(form)
        elif k == "assembly":
            b.section("Sous-ensemble" if o.parent else "Ensemble")
            if o.parent and sc.assembly(o.parent):
                b.info("Dans : " + " › ".join(a.name for a in reversed([sc.assembly(o.parent)] + sc.ancestors(o.parent))))
            b.add("name", "Nom", "str")
            b.add("locked", "🔒 Position verrouillée", "bool")
            self._place_buttons(form, o.locked)
            self._button(form, "Enregistrer l'ensemble…", lambda: self.action.emit("save_ensemble"))
            self._button(form, "Dissocier", lambda: self.action.emit("ungroup"))
            self.info_lab = b.info()
            b.info("Glissez une forme ou un ensemble sur cet ensemble dans l'arbre pour l'y ranger (sous-groupe), "
                   "ou sur « FORMES » pour l'en sortir. Ctrl+G sur des ensembles sélectionnés les regroupe dans "
                   "un nouvel ensemble.")
            self._corners(form)
        elif k == "object":
            lab = {"speaker": "Haut-parleur", "array": "Line array", "row": "Rangée"}[o.TYPE]
            b.section(lab)
            b.add("name", "Nom", "str")
            b.add("group", "Groupe", "choice", choices=[(g.name, g.id) for g in sc.groups])
            b.add("model", "Modèle", "choice", choices=[(m.name, m.id) for m in sc.models])
            self._button(form, "Ouvrir le modèle dans la bibliothèque…", lambda: self.openLibrary.emit(o.model))
            if o.mirror_of:
                p = sc.partner(o)
                b.section(f"Miroir {o.mirror_axis} lié")
                b.info(f"Lié à « {p.name if p else '?'} » : toute modification est recopiée en symétrie "
                       f"(plan {'Y = 0' if o.mirror_axis == 'Y' else 'X = 0'}).")
                self._button(form, "Délier le miroir", lambda: self.unlink.emit(o))
            lk = o.locked
            b.add("locked", "🔒 Position verrouillée", "bool",
                  tip="Empêche de déplacer ou de réorienter l'objet (vues et propriétés)")
            b.section("Point d'accroche" if o.TYPE != "row" else "Première enceinte (accroche)")
            for a in ("x", "y", "z"):
                b.add(a, a.upper(), enabled=not lk, **pos)
            b.section("Orientation")
            b.add("az", "Azimut", tip="0° = +X, 90° = +Y", enabled=not lk, **ang)
            if o.TYPE == "array":
                b.add("orient", "Disposition", "choice", choices=ORIENTS, enabled=not lk,
                      tip="Verticale : accroche haut/bas · Couchée : boîtes tournées de 90°, chaînées "
                          "horizontalement · Côte à côte : boîtes debout, articulées sur leurs arêtes arrière")
                vert = o.orient == "Verticale"
                if not vert:
                    b.add("tilt", "Site d'ensemble", lo=-90, hi=90, step=0.5, dec=1, suffix=" °", enabled=not lk)
                b.add("top_angle", "Site boîte haute" if vert else "Angle boîte 1", lo=-180, hi=180, step=0.5,
                      dec=1, suffix=" °", enabled=not lk)
                b.section("Boîtes")
                b.add("n", "Nombre", "int", lo=1, hi=48, enabled=not lk)
                b.add("splays", "Splays (°)", "list", tip="n-1 valeurs séparées par des virgules", enabled=not lk)
            else:
                b.add("el", "Site", lo=-90, hi=90, step=0.5, dec=1, suffix=" °", tip="Négatif = vers le bas",
                      enabled=not lk)
            if o.TYPE == "row":
                b.section("Rangée")
                b.add("n", "Nombre", "int", lo=1, hi=64, enabled=not lk)
                b.add("spacing", "Espacement", lo=0.05, hi=100, step=0.1, suffix=" m", enabled=not lk)
                b.add("row_angle", "Direction ligne", enabled=not lk, **ang)
            b.add("flip", "Modèle inversé gauche/droite", "bool", enabled=not lk)
            self._place_buttons(form, lk)
            b.section("Réglages")
            b.add("gain", "Gain", lo=-60, hi=20, step=0.5, dec=1, suffix=" dB")
            b.add("delay_offset", "Offset délai", lo=-500, hi=500, step=0.1, suffix=" ms")
            b.add("mute", "Mute", "bool")
            self.info_lab = b.info()
        elif k == "group":
            b.section("Groupe")
            b.add("name", "Nom", "str")
            b.add("color", "Couleur", "color")
            b.add("main", "Groupe main (référence des délais)", "bool")
            self.info_lab = b.info()
        elif k == "listener":
            b.section("Point d'écoute")
            b.add("name", "Nom", "str")
            b.add("locked", "🔒 Position verrouillée", "bool")
            for a in ("x", "y", "z"):
                b.add(a, a.upper(), enabled=not o.locked, **pos)
            self._place_buttons(form, o.locked)
        if k == "object":
            self._corners(form)

    def _place_buttons(self, form, locked):
        hb = QtWidgets.QHBoxLayout()
        for text, act in (("Accrocher…", "snap"), ("Décaler…", "offset")):
            bt = QtWidgets.QPushButton(text)
            bt.clicked.connect(lambda _=False, a=act: self.action.emit(a))
            bt.setEnabled(not locked)
            hb.addWidget(bt)
        form.addRow(hb)

    def _corners(self, form):
        lab = QtWidgets.QLabel("COINS")
        lab.setObjectName("section")
        form.addRow(lab)
        t = make_table(["#", "X", "Y", "Z"])
        t.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        t.setMinimumHeight(150)
        t.setMaximumHeight(240)
        t.setToolTip("Coordonnées des coins (numéros affichés dans les vues). Ctrl+C pour copier.")
        form.addRow(t)
        self.corner_table = t

    def _fill_corners(self, scene):
        t = self.corner_table
        if t is None or self.obj is None:
            return
        from . import edit as E
        P, _ = E.sorted_points(scene, self.kind, self.obj)
        t.setRowCount(len(P))
        for i, p in enumerate(P):
            t.setItem(i, 0, cell(str(i + 1), S.DIM))
            for j in range(3):
                t.setItem(i, j + 1, cell(f"{p[j]:.3f}"))

    def _on_change(self, attr):
        o = self.obj
        if attr in ("kind", "locked", "orient"):
            QtCore.QTimer.singleShot(0, self.rebuild)
        if attr == "n" and self.kind == "object" and o.TYPE == "array":
            o.norm_splays()
            QtCore.QTimer.singleShot(0, self.binder.load)
        self.changed.emit(attr in self.STRUCT)

    def reload(self):
        if self.obj is not None and self.binder is not None:
            self.binder.load()

    def update_info(self, scene: Scene):
        if self.obj is None:
            return
        o, c = self.obj, speed_of_sound(scene.settings.temperature)
        try:
            self._fill_corners(scene)
        except RuntimeError:
            pass
        if self.info_lab is None:
            return
        try:
            if self.kind == "shape":
                fs = o.faces()
                lo, hi = o.corners().min(0), o.corners().max(0)
                ext = hi - lo
                narc = sum(abs(a) > 1e-9 for a in (o.arcs or []))
                self.info_lab.setText(f"Plan {o.plane} · {len(o.profile)} points · {narc} arc(s) · {len(fs)} faces\n"
                                      f"Encombrement {ext[0]:.2f} × {ext[1]:.2f} × {ext[2]:.2f} m\n"
                                      f"z de {lo[2]:.2f} à {hi[2]:.2f} m")
            elif self.kind == "assembly":
                shapes = scene.all_shapes_in(o.id)
                subs = scene.sub_assemblies(o.id)
                if shapes:
                    P = np.vstack([s.corners() for s in shapes])
                    lo, hi = P.min(0), P.max(0)
                    ext = hi - lo
                    self.info_lab.setText(f"{len(shapes)} forme(s)" +
                                          (f", {len(subs)} sous-ensemble(s) : " + ", ".join(a.name for a in subs[:4])
                                           if subs else " : " + ", ".join(s.name for s in shapes[:6])) +
                                          f"\nEncombrement {ext[0]:.2f} × {ext[1]:.2f} × {ext[2]:.2f} m\n"
                                          f"Coin bas : ({lo[0]:.3f}, {lo[1]:.3f}, {lo[2]:.3f})")
            elif self.kind == "object":
                m = scene.model(o.model)
                ss = scene.sources_of(o.id)
                ds = sorted({round(scene.delays.get(s.id, 0.0), 2) for s in ss})
                txt = f"{len(ss)} source(s) · délai(s) : " + (", ".join(f"{d:.2f}" for d in ds[:6]) or "—") + " ms"
                if o.TYPE == "array" and m is not None:
                    lo, hi = m.splay_range(o.orient)
                    span = m.hinge_span()
                    sp = o.norm_splays()
                    bad = [i + 2 for i, s in enumerate(sp) if s > hi + 1e-6 or s < lo - 1e-6]
                    txt += (f"\nPas {span:.3f} m · hauteur {o.n * span:.2f} m · courbure {sum(sp):.1f}°"
                            f"\nSplay sans collision {max(lo, -45):.1f}…{hi:.1f}° · couplage ≤ "
                            f"{A.coupling_freq(span, c):.0f} Hz")
                    if bad:
                        txt += f"\n⚠ collision entre boîtes : {', '.join(map(str, bad))}"
                self.info_lab.setText(txt)
            elif self.kind == "group":
                objs = scene.objects_in(o.id)
                ss = scene.sources_in(o.id)
                ds = sorted({round(scene.delays.get(s.id, 0.0), 2) for s in ss})
                self.info_lab.setText(f"{len(objs)} objet(s) · {len(ss)} source(s)\nDélai(s) : " +
                                      (", ".join(f"{d:.2f}" for d in ds[:6]) or "—") + " ms")
        except Exception as e:  # pragma: no cover
            self.info_lab.setText(str(e))


# --------------------------------------------------------------------------- onglet affichage
class DisplayTab(QtWidgets.QWidget):
    changed = QtCore.Signal(bool)

    def __init__(self, scene_getter):
        super().__init__()
        self.scene = scene_getter
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        sa, form = scroll_form(); lay.addWidget(sa)
        b = self.b = Binder(form, lambda: self.scene().settings)
        b.changed.connect(lambda a: self.changed.emit(False))
        b.section("Émission (-6 dB)")
        b.add("show_cov", "Cônes d'émission translucides", "bool")
        b.add("cov_clip", "Arrêter les cônes aux surfaces", "bool")
        b.add("cov_range", "Longueur max des cônes", lo=0.5, hi=500, step=1, dec=1, suffix=" m")
        b.add("cone_alpha", "Opacité des cônes", lo=0.02, hi=0.9, step=0.02, dec=2)
        b.section("Rayons")
        b.add("show_rays", "Lancer de rayons", "bool")
        b.add("rays_selection_only", "Seulement la sélection", "bool")
        b.add("nrays", "Rayons / source", "int", lo=1, hi=3000)
        b.add("max_order", "Réflexions max", "int", lo=0, hi=10)
        b.add("ray_len", "Longueur max", lo=1, hi=1000, step=5, dec=0, suffix=" m")
        leg = QtWidgets.QLabel(" ".join(
            f'<span style="color:{c}">■</span> {n}' for c, n in
            zip(S.ORDER_COLORS, ["direct", "1re", "2e", "3e", "4e", "5e+"])))
        leg.setObjectName("info")
        b.form.addRow(leg)
        b.section("Carte SPL")
        b.add("show_spl", "Zones public", "bool")
        b.add("spl_scope", "Sources de la carte", "choice", choices=["Sélection", "Toutes les sources"],
              tip="Sélection : seulement le HP / groupe sélectionné (toutes les sources si la sélection n'en "
                  "contient pas)")
        b.add("show_section", "Coupe verticale XZ", "bool")
        b.add("section_y", "Position coupe Y", lo=-1000, hi=1000, step=0.25, suffix=" m")
        b.add("freq", "Fréquence (Hz)", "freq")
        b.add("band", "Calcul", "choice", choices=list(A.BANDS.keys()),
              tip="Cohérent : une fréquence · 1/3 oct / Octave : moyenne de bande · Énergie : somme incohérente")
        b.add("ear", "Hauteur d'oreille", lo=0, hi=3, step=0.1, suffix=" m")
        b.add("dyn", "Dynamique", lo=3, hi=60, step=3, dec=0, suffix=" dB")
        b.add("resolution", "Résolution (0 = auto)", lo=0, hi=2, step=0.01, dec=3, suffix=" m")
        self.res_info = b.info()
        b.section("Vue 3D")
        b.info("Bouton « Balade » de la vue 3D : ZQSD / WASD ou flèches pour marcher, E / C pour "
               "monter / descendre, Maj pour courir, glisser pour regarder, molette pour avancer, "
               "Échap pour revenir en orbite.")

    def load(self):
        self.b.load()

    def update_info(self, scene):
        r = A.auto_resolution(scene)
        self.res_info.setText(f"Résolution utilisée : {r * 100:.1f} cm")


# --------------------------------------------------------------------------- onglet line array
class ArrayTab(QtWidgets.QWidget):
    changed = QtCore.Signal(bool)
    applied = QtCore.Signal(object)     # objet modifié (pour le miroir)

    def __init__(self, scene_getter):
        super().__init__()
        self.scene = scene_getter
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        sa, form = scroll_form(); lay.addWidget(sa)
        self.form = form
        b = self.b = Binder(form, lambda: self.scene().settings)
        b.changed.connect(lambda a: self.changed.emit(False))

        b.section("Line array")
        self.combo = NoWheelCombo()
        self.combo.currentIndexChanged.connect(lambda _: self.refresh_report())
        form.addRow("Line array", self.combo)
        b.section("Public à couvrir (distances depuis l'accroche)")
        b.add("opt_near", "Premier rang", lo=0, hi=500, step=0.5, suffix=" m")
        b.add("opt_far", "Dernier rang", lo=0.5, hi=1000, step=1, suffix=" m")
        b.add("opt_znear", "Oreille premier rang Z", lo=-50, hi=100, step=0.1, suffix=" m")
        b.add("opt_zfar", "Oreille dernier rang Z", lo=-50, hi=100, step=0.1, suffix=" m")
        b.section("Contraintes")
        b.add("opt_max", "Splay max", lo=0, hi=30, step=0.5, dec=1, suffix=" °")
        b.add("opt_step", "Pas des angles", lo=0.1, hi=5, step=0.25, suffix=" °")
        b.add("opt_weight", "Pondération distance", lo=0, hi=3, step=0.1,
              tip="0 = angles réguliers · 1 = densité de boîtes ∝ distance (≈ SPL constant)")
        self.limits = QtWidgets.QLabel(); self.limits.setObjectName("info"); self.limits.setWordWrap(True)
        form.addRow(self.limits)
        btn = QtWidgets.QPushButton("Optimiser les angles")
        btn.setObjectName("primary")
        btn.clicked.connect(self.optimize)
        form.addRow(btn)
        self.table = make_table(["Boîte", "Site", "Splay", "Impact"])
        self.table.setMinimumHeight(220)
        form.addRow(self.table)

        b.section("Espacement / couplage")
        b.add("target_freq", "Fréquence cible", lo=20, hi=20000, step=100, dec=0, suffix=" Hz")
        self.coupling = QtWidgets.QLabel(); self.coupling.setObjectName("value"); self.coupling.setWordWrap(True)
        form.addRow(self.coupling)

        b.section("Rangée (front fill, distribué)")
        self.row_combo = NoWheelCombo()
        self.row_combo.currentIndexChanged.connect(lambda _: self.refresh_report())
        form.addRow("Rangée", self.row_combo)
        b.add("row_dist", "Distance d'écoute D", lo=0.1, hi=200, step=0.5, suffix=" m",
              tip="Distance (selon l'axe) où les couvertures de deux enceintes voisines se rejoignent")
        auto = QtWidgets.QPushButton("D = impact de l'axe")
        auto.clicked.connect(self.auto_dist)
        form.addRow(auto)
        b.add("row_overlap", "Recouvrement", "choice", choices=["-6 dB", "-3 dB"])
        btn2 = QtWidgets.QPushButton("Calculer et appliquer l'espacement")
        btn2.setObjectName("primary")
        btn2.clicked.connect(self.apply_spacing)
        form.addRow(btn2)
        self.row_res = QtWidgets.QLabel(); self.row_res.setObjectName("value"); self.row_res.setWordWrap(True)
        form.addRow(self.row_res)

    def load(self):
        self.b.load()

    def refresh_lists(self):
        sc = self.scene()
        for combo, kind in ((self.combo, "array"), (self.row_combo, "row")):
            cur = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            for o in sc.objects:
                if o.TYPE == kind:
                    combo.addItem(o.name + ("  ⇋" if o.mirror_of else ""), o.id)
            i = combo.findData(cur)
            combo.setCurrentIndex(i if i >= 0 else 0)
            combo.blockSignals(False)

    def select_object(self, oid):
        for combo in (self.combo, self.row_combo):
            i = combo.findData(oid)
            if i >= 0:
                combo.setCurrentIndex(i)

    def obj(self, combo):
        return self.scene().obj(combo.currentData())

    def optimize(self):
        o = self.obj(self.combo)
        if o is None or o.locked:
            return
        if o.orient != "Verticale":
            QtWidgets.QMessageBox.information(self, "Optimiser", "L'optimisation concerne les arrays verticaux.")
            return
        sc = self.scene(); st = sc.settings
        A.optimize_array(o, sc.model(o.model), st.opt_near, st.opt_far, st.opt_znear, st.opt_zfar,
                         st.opt_max, st.opt_step, st.opt_weight)
        self.applied.emit(o)
        self.changed.emit(True)

    def refresh_report(self):
        sc = self.scene(); st = sc.settings
        c = speed_of_sound(st.temperature)
        o = self.obj(self.combo)
        self.table.setRowCount(0)
        d = c / (2 * st.target_freq)
        if o is not None:
            m = sc.model(o.model)
            lo, hi = m.splay_range(o.orient)
            self.limits.setText(f"Modèle « {m.name} », disposition {o.orient.lower()} : splay sans collision "
                                f"{max(lo, -45):.1f}…{hi:.1f}° (profil et arêtes d'accroche)."
                                + ("" if o.orient == "Verticale" else
                                   "\nL'optimisation des angles ne concerne que les arrays verticaux ; "
                                   "la colonne Site donne ici l'azimut de chaque boîte."))
            rows = A.array_report(o, m, st.opt_near, st.opt_far, st.opt_znear, st.opt_zfar)
            self.table.setRowCount(len(rows))
            for r, row in enumerate(rows):
                hit = row["hit"]
                out = hit is None or hit < st.opt_near - 0.5 or hit > st.opt_far + 0.5
                self.table.setItem(r, 0, cell(f"{row['i']}", S.DIM))
                ang_ = row["el"] if o.orient == "Verticale" else row["pan"]
                self.table.setItem(r, 1, cell(f"{ang_:+.1f}°"))
                sp = "—" if row["splay"] is None else f"{row['splay']:.1f}°" + (" ⚠" if row["collision"] else "")
                self.table.setItem(r, 2, cell(sp, "#ff5b5b" if row["collision"] else S.ACCENT))
                self.table.setItem(r, 3, cell("hors public" if hit is None else f"{hit:.1f} m",
                                              S.DIM if out else None))
            span = m.hinge_span()
            f = A.coupling_freq(span, c)
            self.coupling.setText(f"c = {c:.1f} m/s\nPas entre boîtes {span:.3f} m → couplage cohérent ≤ {f:.0f} Hz\n"
                                  f"Pour {st.target_freq:.0f} Hz : pas max λ/2 = {d:.3f} m")
        else:
            self.limits.setText("Ajoutez un line array (+ Line array).")
            self.coupling.setText(f"c = {c:.1f} m/s · pour {st.target_freq:.0f} Hz : pas max λ/2 = {d:.3f} m")
        rg = self.obj(self.row_combo)
        if rg is not None:
            m = sc.model(rg.model)
            e = m.elements[0] if m and m.elements else None
            if e is not None:
                s = A.row_spacing(e, st.row_dist, st.row_overlap)
                self.row_res.setText(f"Espacement idéal = 2·D·tan(θ) = {s:.2f} m\n(actuel {rg.spacing:.2f} m)\n"
                                     f"Largeur couverte à D ≈ {s * rg.n:.1f} m pour {rg.n} enceintes")
        else:
            self.row_res.setText("Ajoutez une rangée (+ Rangée).")

    def auto_dist(self):
        rg = self.obj(self.row_combo)
        sc = self.scene()
        if rg is None:
            return
        ss = sc.sources_of(rg.id)
        if not ss:
            return
        geo = A.Geometry(sc)
        P = A.axis_point(ss[0], geo)
        sc.settings.row_dist = round(float(np.linalg.norm(P - ss[0].pos)), 2)
        self.b.load()
        self.changed.emit(False)

    def apply_spacing(self):
        rg = self.obj(self.row_combo)
        sc = self.scene()
        if rg is None or rg.locked:
            return
        m = sc.model(rg.model)
        if not m or not m.elements:
            return
        st = sc.settings
        rg.spacing = round(A.row_spacing(m.elements[0], st.row_dist, st.row_overlap), 2)
        self.applied.emit(rg)
        self.changed.emit(True)


# --------------------------------------------------------------------------- onglet délais
class DelayTab(QtWidgets.QWidget):
    changed = QtCore.Signal(bool)

    def __init__(self, scene_getter):
        super().__init__()
        self.scene = scene_getter
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        sa, form = scroll_form(); lay.addWidget(sa)
        b = self.b = Binder(form, lambda: self.scene().settings)
        b.changed.connect(lambda a: self.changed.emit(False))
        b.section("Air")
        b.add("temperature", "Température", lo=-30, hi=60, step=0.5, dec=1, suffix=" °C")
        self.c_lab = QtWidgets.QLabel(); self.c_lab.setObjectName("value")
        form.addRow("Vitesse du son", self.c_lab)
        b.section("Alignement")
        self.ref = NoWheelCombo()
        self.ref.currentIndexChanged.connect(self._ref_changed)
        form.addRow("Point de référence", self.ref)
        b.add("haas", "Décalage Haas", lo=-50, hi=100, step=0.5, dec=1, suffix=" ms",
              tip="Ajouté aux délais : quelques ms font localiser l'image sur le main")
        b.add("per_group_delay", "Un délai par groupe", "bool")
        b.add("apply_delays", "Appliquer les délais à la carte SPL", "bool")
        b.section("Groupe(s) main")
        self.mains = QtWidgets.QListWidget()
        self.mains.setMaximumHeight(110)
        self.mains.itemChanged.connect(self._main_changed)
        form.addRow(self.mains)
        b.section("Délais calculés")
        self.table = make_table(["Source", "Groupe", "d main", "d src", "Délai"], stretch=0)
        self.table.setMinimumHeight(260)
        form.addRow(self.table)
        b.info("Délai = (d main − d source) / c + Haas, mesuré au point de référence "
               "(impact de l'axe de la source, ou écouteur choisi). d main = distance au "
               "centre acoustique du groupe main le plus proche.")

    def load(self):
        self.b.load()

    def refresh_lists(self):
        sc = self.scene()
        self.ref.blockSignals(True)
        self.ref.clear()
        self.ref.addItem("Axe de chaque source", "Axe")
        for l in sc.listeners:
            self.ref.addItem(f"Écouteur : {l.name}", l.id)
        i = self.ref.findData(sc.settings.ref_mode)
        self.ref.setCurrentIndex(i if i >= 0 else 0)
        self.ref.blockSignals(False)
        self.mains.blockSignals(True)
        self.mains.clear()
        for g in sc.groups:
            it = QtWidgets.QListWidgetItem(g.name)
            it.setData(Qt.ItemDataRole.UserRole, g.id)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if g.main else Qt.CheckState.Unchecked)
            it.setForeground(QtGui.QColor(g.color))
            self.mains.addItem(it)
        self.mains.blockSignals(False)

    def _ref_changed(self, i):
        self.scene().settings.ref_mode = self.ref.itemData(i) or "Axe"
        self.changed.emit(False)

    def _main_changed(self, it):
        g = self.scene().group(it.data(Qt.ItemDataRole.UserRole))
        if g is not None:
            g.main = it.checkState() == Qt.CheckState.Checked
            self.changed.emit(True)

    def update_rows(self, rows, c):
        self.c_lab.setText(f"{c:.2f} m/s")
        # regroupe les sources d'un même groupe qui partagent le même délai
        agg = []
        for row in rows:
            key = (row["group"].id, round(row["delay"], 2), row["main"])
            if agg and agg[-1]["key"] == key:
                agg[-1]["n"] += 1
                continue
            agg.append(dict(row, key=key, n=1))
        agg.sort(key=lambda r: (r["main"], r["group"].name))
        self.table.setRowCount(len(agg))
        for r, row in enumerate(agg):
            s, g = row["src"], row["group"]
            name = s.name if row["n"] == 1 else f"{g.name} ×{row['n']}"
            self.table.setItem(r, 0, cell(name, None, False))
            self.table.setItem(r, 1, cell("MAIN" if row["main"] else g.name, g.color, False))
            self.table.setItem(r, 2, cell("—" if row["dm"] is None else f"{row['dm']:.2f} m"))
            self.table.setItem(r, 3, cell("—" if row["ds"] is None else f"{row['ds']:.2f} m"))
            txt = f"{row['delay']:.2f} ms" + (" ⚠" if row["warn"] else "")
            it = cell(txt, "#ff5b5b" if row["warn"] else (S.DIM if row["main"] else S.ACCENT))
            if row["warn"]:
                it.setToolTip(f"La source est plus loin que le main ({row['raw']:.2f} ms) : "
                              f"c'est le main qu'il faudrait retarder.")
            self.table.setItem(r, 4, it)


# --------------------------------------------------------------------------- onglet réflexions
class ReflTab(QtWidgets.QWidget):
    changed = QtCore.Signal(bool)

    def __init__(self, scene_getter):
        super().__init__()
        self.scene = scene_getter
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        sa, form = scroll_form(); lay.addWidget(sa)
        b = self.b = Binder(form, lambda: self.scene().settings)
        b.changed.connect(lambda a: self.changed.emit(False))
        b.section("Réflexions vers un écouteur")
        b.add("show_refl", "Afficher les chemins", "bool")
        self.lst = NoWheelCombo()
        self.lst.currentIndexChanged.connect(self._lst_changed)
        form.addRow("Écouteur", self.lst)
        b.add("refl_order", "Ordre max", "int", lo=1, hi=4)
        self.summary = QtWidgets.QLabel(); self.summary.setObjectName("info"); self.summary.setWordWrap(True)
        form.addRow(self.summary)
        self.table = make_table(["Source", "Ord.", "Surfaces", "Δt", "Niveau", "rel."], stretch=2)
        self.table.setMinimumHeight(380)
        form.addRow(self.table)
        b.info("Méthode des sources images (réflexions spéculaires). Les chemins sont dessinés "
               "pour la source ou le groupe sélectionné ; sans sélection, le tableau liste "
               "toutes les sources. "
               "Δt et niveau "
               "relatifs au son direct de la même source.")

    def load(self):
        self.b.load()

    def refresh_lists(self):
        sc = self.scene()
        self.lst.blockSignals(True)
        self.lst.clear()
        for l in sc.listeners:
            self.lst.addItem(l.name, l.id)
        i = self.lst.findData(sc.settings.refl_listener)
        self.lst.setCurrentIndex(i if i >= 0 else 0)
        if sc.listeners and i < 0:
            sc.settings.refl_listener = sc.listeners[0].id
        self.lst.blockSignals(False)

    def _lst_changed(self, i):
        self.scene().settings.refl_listener = self.lst.itemData(i) or ""
        self.changed.emit(False)

    def update_rows(self, paths, c):
        refl = sorted([p for p in paths if p["order"] > 0], key=lambda p: p["dt"])
        direct = [p for p in paths if p["order"] == 0]
        if not self.scene().listeners:
            self.summary.setText("Ajoutez un écouteur (+ Écouteur).")
        else:
            early = [p for p in refl if p["dt"] < 50 and p["rel"] > -10]
            self.summary.setText(f"{len(direct)} trajet(s) direct(s) · {len(refl)} réflexion(s) · "
                                 f"{len(early)} réflexion(s) précoce(s) gênante(s) (< 50 ms, > -10 dB).")
        rows = refl[:300]
        self.table.setRowCount(len(rows))
        for r, p in enumerate(rows):
            col = S.ORDER_COLORS[min(p["order"], 5)]
            self.table.setItem(r, 0, cell(p["src"].name, None, False))
            self.table.setItem(r, 1, cell(str(p["order"]), col))
            self.table.setItem(r, 2, cell(" → ".join(p["surf"]), S.DIM, False))
            self.table.setItem(r, 3, cell(f"{p['dt']:.1f} ms"))
            self.table.setItem(r, 4, cell(f"{p['level']:.0f} dB"))
            warn = p["dt"] < 50 and p["rel"] > -10
            self.table.setItem(r, 5, cell(f"{p['rel']:+.1f} dB", "#ff5b5b" if warn else S.DIM))
