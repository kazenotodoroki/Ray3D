"""Fenêtre principale."""
from __future__ import annotations

import copy
import json
import os
import sys
import time

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from . import style as S
from . import acoustics as A
from .demo import default_scene, studio_scene
from . import sbir as SB
from .sbirtab import SbirTab
from .treattab import TreatTab
from . import treatment as T
from .library import default_models
from .libdialog import LibraryDialog
from .model import (Scene, Shape, Group, Speaker, LineArray, Row, Listener, new_id, speed_of_sound,
                    OBJ_LABEL, mirror_name)
from .panels import PropertyEditor, DisplayTab, ArrayTab, DelayTab, ReflTab
from .sketch import SketchDialog
from .views import View2D, View3D, ColorLegend, ViewPane
from . import edit as E
from .tools import OffsetDialog, SnapDialog

ROLE = Qt.ItemDataRole.UserRole
AUTOSAVE = os.path.join(os.path.expanduser("~"), ".ray3d", "autosave.json")
ENSEMBLE_DIR = os.path.join(os.path.expanduser("~"), ".ray3d", "ensembles")
SPL_KEYS = {"spl_scope", "temperature", "haas", "ref_mode", "per_group_delay", "apply_delays", "show_spl", "show_section",
            "freq", "band", "ear", "section_y", "resolution"}


# --------------------------------------------------------------------------- arbre avec glisser-déposer
class SceneTree(QtWidgets.QTreeWidget):
    dropped = QtCore.Signal(list, str, str)          # [(kind, id)], type cible, id cible

    def __init__(self):
        super().__init__()
        self.setHeaderHidden(True)
        self.setColumnCount(2)
        self.setIndentation(14)
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.header().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.InternalMove)

    def dropEvent(self, ev):
        target = self.itemAt(ev.position().toPoint())
        ev.setDropAction(Qt.DropAction.IgnoreAction)
        ev.ignore()
        if target is None:
            return
        dragged = [it.data(0, ROLE) for it in self.selectedItems() if it.data(0, ROLE)]
        t = target.data(0, ROLE)
        if t is None:                      # en-tête de section : « FORMES » = sortir de l'ensemble
            if target.text(0) == "FORMES":
                t = ("shapes_root", "")
            else:
                return
        if t[0] in ("object", "shape") and target.parent() is not None and target.parent().data(0, ROLE):
            t = target.parent().data(0, ROLE)
        QtCore.QTimer.singleShot(0, lambda: self.dropped.emit(dragged, t[0], t[1]))


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, scene: Scene | None = None):
        super().__init__()
        self.setWindowTitle("Ray 3D — projection de haut-parleurs")
        self.resize(1600, 960)
        self.scene = scene or default_scene()
        self.sel = None
        self.multi = set()
        self.markers = []
        self.path = None
        self.maxed = None
        self._cache = {}
        self.history, self.hpos, self._restoring = [], -1, False
        self._previewing = False
        self.dirty = False
        self.timer = QtCore.QTimer(self, singleShot=True, interval=40)
        self.timer.timeout.connect(self.recompute)
        self.autosave_timer = QtCore.QTimer(self, interval=20000)
        self.autosave_timer.timeout.connect(self.autosave)
        self.autosave_timer.start()
        self._build_ui()
        self.refresh_tree()
        self.refresh_lists()
        self.recompute()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        get = lambda: self.scene

        self.v3d = View3D()
        self.vtop = View2D("xy")
        self.vside = View2D("xz")
        self.legend = ColorLegend()
        for v in (self.vtop, self.vside):
            v.sigMoved.connect(self.on_moved)
        self.vtop.sigSection.connect(self.on_section)

        self.walk_btn = QtWidgets.QToolButton(); self.walk_btn.setText("Balade")
        self.walk_btn.setCheckable(True)
        self.walk_btn.setToolTip("Se déplacer dans la scène : ZQSD/WASD, E/C, Maj, glisser pour regarder")
        self.walk_btn.toggled.connect(lambda on: self.v3d.set_walk(on))
        self.v3d.sigWalk.connect(lambda on: (self.walk_btn.blockSignals(True), self.walk_btn.setChecked(on),
                                             self.walk_btn.blockSignals(False)))
        eye_btn = QtWidgets.QToolButton(); eye_btn.setText("À l'écouteur")
        eye_btn.setToolTip("Se placer à l'écouteur sélectionné (ou au premier)")
        eye_btn.clicked.connect(self.go_listener)
        self.orbit_btn = QtWidgets.QToolButton(); self.orbit_btn.setText("Orbite écouteur")
        self.orbit_btn.setCheckable(True)
        self.orbit_btn.setToolTip("Ancre la rotation de la caméra sur l'écouteur sélectionné (ou le premier)")
        self.orbit_btn.toggled.connect(lambda on: self.update_anchor())
        fit_btn = QtWidgets.QToolButton(); fit_btn.setText("Recadrer")
        fit_btn.clicked.connect(lambda: self.v3d.fit(self.scene))

        self.p3d = ViewPane(self.v3d, "3D", [self.walk_btn, eye_btn, self.orbit_btn, fit_btn])
        self.ptop = ViewPane(self.vtop, "DESSUS · XY", [self.legend])
        self.pside = ViewPane(self.vside, "CÔTÉ · XZ (coupe)")
        for p in (self.p3d, self.ptop, self.pside):
            p.sigMaximize.connect(self.toggle_max)
        self.right_split = QtWidgets.QSplitter(Qt.Orientation.Vertical)
        self.right_split.addWidget(self.ptop)
        self.right_split.addWidget(self.pside)
        self.center = QtWidgets.QSplitter(Qt.Orientation.Horizontal)
        self.center.addWidget(self.p3d)
        self.center.addWidget(self.right_split)
        self.center.setSizes([900, 700])
        self.setCentralWidget(self.center)

        # gauche
        self.tree = SceneTree()
        self.tree.itemSelectionChanged.connect(self.on_tree_select)
        self.tree.itemDoubleClicked.connect(self.on_tree_double)
        self.tree.dropped.connect(self.on_drop)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.tree_menu)
        self.props = PropertyEditor(get)
        self.props.changed.connect(self.on_props_changed)
        self.props.editSketch.connect(self.edit_sketch)
        self.props.recenter.connect(self.recenter_shape)
        self.props.unlink.connect(self.unlink)
        self.props.openLibrary.connect(self.open_library)
        self.props.action.connect(lambda a: {"snap": self.snap_selection, "offset": self.offset_selection,
                                             "save_ensemble": self.save_ensemble,
                                             "ungroup": self.ungroup_shapes}[a]())
        left = QtWidgets.QSplitter(Qt.Orientation.Vertical)
        left.addWidget(ViewPane(self.tree, "SCÈNE"))
        left.addWidget(ViewPane(self.props, "PROPRIÉTÉS"))
        for i in range(2):
            left.widget(i).maxbtn.hide()
        left.setSizes([360, 600])
        self.dock_l = QtWidgets.QDockWidget("", self)
        self.dock_l.setTitleBarWidget(QtWidgets.QWidget())
        self.dock_l.setWidget(left)
        self.dock_l.setFeatures(QtWidgets.QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.dock_l.setMinimumWidth(310)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.dock_l)

        # droite
        self.tab_disp = DisplayTab(get)
        self.tab_arr = ArrayTab(get)
        self.tab_del = DelayTab(get)
        self.tab_ref = ReflTab(get)
        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self.tab_disp, "AFFICHAGE")
        tabs.addTab(self.tab_arr, "LINE ARRAY")
        tabs.addTab(self.tab_del, "DÉLAIS")
        tabs.addTab(self.tab_ref, "RÉFLEXIONS")
        self.tab_sbir = SbirTab(get, self.sbir_context)
        tabs.addTab(self.tab_sbir, "SBIR")
        self.tab_sbir.changed.connect(self.on_tab_changed)
        self.tab_sbir.applied.connect(self.after_edit)
        self.tab_sbir.export_pdf.connect(self.export_analysis_pdf)
        self.tab_treat = TreatTab(get)
        tabs.addTab(self.tab_treat, "TRAITEMENT")
        self.tab_treat.place.connect(self.place_treatment)
        self.tab_treat.remove.connect(self.remove_treatment)
        self.tab_treat.export_pdf.connect(self.export_analysis_pdf)
        self.tab_treat.export_desk.connect(self.export_cutlist_pdf)
        self.tab_treat.add_bass_trap.connect(self.add_bass_trap)
        self._corners = []
        tabs.currentChanged.connect(lambda _: self.schedule())
        self.tabs = tabs
        for t in (self.tab_disp, self.tab_arr, self.tab_del, self.tab_ref, self.tab_sbir, self.tab_treat):
            t.changed.connect(self.on_tab_changed)
        self.tab_arr.applied.connect(self.after_edit)
        self.dock_r = QtWidgets.QDockWidget("", self)
        self.dock_r.setTitleBarWidget(QtWidgets.QWidget())
        self.dock_r.setWidget(tabs)
        self.dock_r.setFeatures(QtWidgets.QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.dock_r.setMinimumWidth(370)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock_r)

        # barres d'outils : ligne 1 fichier / édition, ligne 2 ajout
        tb = QtWidgets.QToolBar()
        tb.setMovable(False)
        self.addToolBar(tb)
        self.addToolBarBreak()
        tb2 = QtWidgets.QToolBar()
        tb2.setMovable(False)
        self.addToolBar(tb2)

        def act(text, fn, sc=None, tip=None, bar=tb):
            a = QtGui.QAction(text, self)
            a.triggered.connect(fn)
            if sc:
                a.setShortcut(QtGui.QKeySequence(sc))
            if tip:
                a.setToolTip(tip + (f" ({sc})" if sc else ""))
            bar.addAction(a)
            return a
        act("Nouveau", self.new_scene, "Ctrl+N")
        act("Exemple studio", lambda: self.set_scene(studio_scene()),
            tip="Petit studio avec une paire de Yamaha HS8, pour l'étude du SBIR")
        act("Ouvrir", self.open_scene, "Ctrl+O")
        act("Enregistrer", self.save_scene, "Ctrl+S")
        tb.addSeparator()
        act("Annuler", self.undo, "Ctrl+Z", tip="Annuler")
        act("Rétablir", self.redo, "Ctrl+Y", tip="Rétablir (ou Ctrl+Maj+Z)")
        a = QtGui.QAction(self); a.setShortcut(QtGui.QKeySequence("Ctrl+Shift+Z")); a.triggered.connect(self.redo)
        self.addAction(a)
        tb.addSeparator()
        act("Dupliquer", self.duplicate, "Ctrl+D")
        act("Supprimer", self.delete, "Del")
        tb.addSeparator()
        act("Décaler…", self.offset_selection, "Ctrl+M", tip="Déplacer la sélection d'un décalage dX, dY, dZ")
        act("Accrocher…", self.snap_selection, "Ctrl+K",
            tip="Poser un coin de l'élément sélectionné sur un coin d'un autre, puis glisser le long d'une arête")
        act("🔒 Verrou", self.toggle_lock, "Ctrl+L", tip="Verrouiller / déverrouiller les éléments sélectionnés")
        ens = QtWidgets.QToolButton()
        ens.setText("Ensembles ▾")
        ens.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QtWidgets.QMenu(ens)
        for text, fn, sc_ in (("Créer un ensemble avec la sélection", self.group_shapes, "Ctrl+G"),
                              ("Dissocier l'ensemble", self.ungroup_shapes, "Ctrl+Shift+G"),
                              ("Enregistrer la sélection comme ensemble…", self.save_ensemble, None),
                              ("Insérer un ensemble…", self.insert_ensemble, None)):
            a = menu.addAction(text, fn)
            if sc_:
                a.setShortcut(QtGui.QKeySequence(sc_))
                self.addAction(a)
        ens.setMenu(menu)
        tb.addWidget(ens)
        tb.addSeparator()
        act("Miroir X", lambda: self.mirror("X"), tip="Copie liée en symétrie par rapport au plan X = 0")
        act("Miroir Y", lambda: self.mirror("Y"), tip="Copie liée en symétrie par rapport au plan Y = 0")
        tb.addSeparator()
        act("Bibliothèque HP", lambda: self.open_library(None))
        act("Recadrer", self.fit_views, "F")

        act("+ Pièce", lambda: self.add_shape("Pièce"), tip="Esquisser puis extruder une salle", bar=tb2)
        act("+ Objet", lambda: self.add_shape("Objet"), tip="Esquisser puis extruder un objet (bureau, scène…)",
            bar=tb2)
        act("+ Surface", lambda: self.add_shape("Surface"), tip="Surface plane esquissée", bar=tb2)
        tb2.addSeparator()
        act("+ Groupe", self.add_group, bar=tb2)
        act("+ HP", self.add_speaker, bar=tb2)
        act("+ Line array", self.add_array, bar=tb2)
        act("+ Rangée", self.add_row, tip="Rangée d'enceintes régulièrement espacées (front fill…)", bar=tb2)
        act("+ Écouteur", self.add_listener, bar=tb2)
        a = QtGui.QAction(self); a.setShortcut(QtGui.QKeySequence("F11")); a.triggered.connect(self.toggle_fullscreen)
        self.addAction(a)
        a = QtGui.QAction(self); a.setShortcut(QtGui.QKeySequence("Escape")); a.triggered.connect(self.escape)
        a.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.addAction(a)
        spacer = QtWidgets.QWidget()
        spacer.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)
        tb2.addWidget(spacer)
        self.status = QtWidgets.QLabel()
        self.status.setObjectName("info")
        tb2.addWidget(self.status)

    # ------------------------------------------------------------------ plein écran
    def toggle_max(self, pane):
        panes = (self.p3d, self.ptop, self.pside)
        if self.maxed is pane:
            for p in panes:
                p.show()
            self.right_split.show()
            self.dock_l.show(); self.dock_r.show()
            self.maxed = None
            pane.maxbtn.setText("⤢")
            return
        for p in panes:
            p.setVisible(p is pane)
        self.right_split.setVisible(pane is not self.p3d)
        self.dock_l.hide(); self.dock_r.hide()
        if self.maxed is not None:
            self.maxed.maxbtn.setText("⤢")
        self.maxed = pane
        pane.maxbtn.setText("⤡")

    def toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def escape(self):
        if self.v3d.walk:
            self.v3d.set_walk(False)
        elif self.maxed is not None:
            self.toggle_max(self.maxed)
        elif self.isFullScreen():
            self.showNormal()

    def anchor_listener(self):
        sc = self.scene
        l = sc.listener(self.sel)
        if l is None:
            l = next((x for x in sc.listeners if x.id == getattr(self, "_anchor_id", None)), None)
        if l is None and sc.listeners:
            l = sc.listeners[0]
        return l

    def update_anchor(self):
        l = self.anchor_listener() if self.orbit_btn.isChecked() else None
        self._anchor_id = l.id if l else None
        self.v3d.set_anchor(l.pos if l else None)

    def go_listener(self):
        sc = self.scene
        l = sc.listener(self.sel) or (sc.listeners[0] if sc.listeners else None)
        if l is None:
            return
        mains = [s.pos for s in sc.active_sources() if (sc.group(s.group) and sc.group(s.group).main)]
        tgt = np.mean(mains, 0) if mains else l.pos + np.array([-1.0, 0, 0])
        d = tgt - l.pos
        self.v3d.opts["azimuth"] = float(np.degrees(np.arctan2(-d[1], -d[0])))
        self.v3d.opts["elevation"] = -float(np.degrees(np.arctan2(d[2], np.hypot(d[0], d[1])))) * 0.5
        self.v3d.set_walk(True, eye=l.pos)

    # ------------------------------------------------------------------ arbre
    def refresh_tree(self):
        sc = self.scene
        self.tree.blockSignals(True)
        self.tree.clear()
        items = {}
        drag = Qt.ItemFlag.ItemIsDragEnabled
        drop = Qt.ItemFlag.ItemIsDropEnabled

        def node(parent, text, sub="", kind=None, oid=None, color=None, flags_on=(), flags_off=()):
            it = QtWidgets.QTreeWidgetItem(parent, [text, sub])
            fl = it.flags() & ~drag & ~drop
            for f in flags_on:
                fl |= f
            if oid:
                it.setData(0, ROLE, (kind, oid))
                items[oid] = it
            else:
                fl &= ~Qt.ItemFlag.ItemIsSelectable
                it.setForeground(0, QtGui.QColor(S.DIM))
                f = it.font(0); f.setPointSize(8); f.setLetterSpacing(QtGui.QFont.SpacingType.AbsoluteSpacing, 1.5)
                it.setFont(0, f)
            it.setFlags(fl)
            if color:
                it.setForeground(0, QtGui.QColor(color))
            it.setForeground(1, QtGui.QColor(S.DIM))
            return it

        lk = lambda o: "🔒 " if getattr(o, "locked", False) else ""
        r = node(self.tree, "FORMES", flags_on=(drop,))
        r.setFlags(r.flags() | drop)
        def add_assembly(parent_item, a, depth=0):
            n = len(sc.all_shapes_in(a.id))
            nsub = len(sc.sub_assemblies(a.id))
            sub = f"{lk(a)}{'sous-ensemble' if depth else 'ensemble'} · {n}" + (f" · {nsub} sous-ens." if nsub else "")
            ai = node(parent_item, a.name, sub, "assembly", a.id, "#e8e8e8", flags_on=(drop, drag))
            if depth > 30:
                return
            for b in sc.sub_assemblies(a.id):
                add_assembly(ai, b, depth + 1)
            for sh in sc.shapes_in(a.id):
                node(ai, sh.name, lk(sh) + sh.kind.lower(), "shape", sh.id, flags_on=(drag,))
            ai.setExpanded(True)
        for a in sc.assemblies:
            if not a.parent:
                add_assembly(r, a)
        for sh in sc.shapes:
            if not sh.assembly:
                node(r, sh.name, lk(sh) + sh.kind.lower(), "shape", sh.id, flags_on=(drag,))
        r2 = node(self.tree, "GROUPES")
        for g in sc.groups:
            gi = node(r2, g.name, "main" if g.main else "", "group", g.id, g.color, flags_on=(drop,))
            for o in sc.objects_in(g.id):
                m = sc.model(o.model)
                sub = OBJ_LABEL[o.TYPE] + (f" ×{o.n}" if o.TYPE != "speaker" else "")
                if o.mirror_of:
                    sub = f"⇋{o.mirror_axis} · " + sub
                if o.TYPE == "array" and o.orient != "Verticale":
                    sub += " · " + o.orient.lower()
                if o.locked:
                    sub = "🔒 " + sub
                if o.mute:
                    sub += " · mute"
                it = node(gi, o.name, sub, "object", o.id, flags_on=(drag,))
                it.setToolTip(0, m.name if m else "")
            gi.setExpanded(True)
        r3 = node(self.tree, "ÉCOUTEURS")
        for l in sc.listeners:
            node(r3, l.name, lk(l).strip(), "listener", l.id)
        r4 = node(self.tree, "MODÈLES DE HP")
        for m in sc.models:
            used = sum(o.model == m.id for o in sc.objects)
            node(r4, m.name, f"{len(m.elements)} él." + (f" · ×{used}" if used else ""), "model", m.id)
        for t in (r, r2, r3):
            t.setExpanded(True)
        r4.setExpanded(False)
        for oid in self.multi:
            if oid in items:
                items[oid].setSelected(True)
        if self.sel in items:
            items[self.sel].setSelected(True)
            self.tree.setCurrentItem(items[self.sel], 0, QtCore.QItemSelectionModel.SelectionFlag.NoUpdate)
        self.tree.blockSignals(False)

    def on_tree_select(self):
        its = [it for it in self.tree.selectedItems() if it.data(0, ROLE)]
        self.multi = {it.data(0, ROLE)[1] for it in its}
        cur = self.tree.currentItem()
        d = cur.data(0, ROLE) if (cur is not None and cur.isSelected()) else None
        if d is None and its:
            d = its[-1].data(0, ROLE)
        self.select(d[1] if d else None, from_tree=True)

    def on_tree_double(self, it, col):
        d = it.data(0, ROLE)
        if not d:
            return
        if d[0] == "model":
            self.open_library(d[1])
        elif d[0] == "shape":
            self.edit_sketch(self.scene.find(d[1])[1])

    def select(self, oid, from_tree=False):
        self.sel = oid
        if not from_tree:
            self.multi = {oid} if oid else set()
        kind, obj = self.scene.find(oid) if oid else (None, None)
        if kind == "model":
            kind, obj = None, None
        self.props.set_object(kind, obj)
        self.props.update_info(self.scene)
        if kind == "object":
            self.tab_arr.select_object(oid)
        if not from_tree:
            self.refresh_tree()
        self.schedule()

    def tree_menu(self, pos):
        m = QtWidgets.QMenu(self)
        kind, obj = self.scene.find(self.sel) if self.sel else (None, None)
        if kind == "object":
            sub = m.addMenu("Déplacer vers le groupe")
            for g in self.scene.groups:
                sub.addAction(g.name, lambda gid=g.id, oid=obj.id: self.move_to_group(oid, gid))
            sub.addAction("Nouveau groupe…", lambda oid=obj.id: self.move_to_group(oid, self.add_group(select=False).id))
            m.addAction("Miroir X", lambda: self.mirror("X"))
            m.addAction("Miroir Y", lambda: self.mirror("Y"))
            if obj.mirror_of:
                m.addAction("Délier le miroir", lambda: self.unlink(obj))
        if kind == "shape":
            m.addAction("Éditer l'esquisse…", lambda: self.edit_sketch(obj))
            if obj.assembly:
                m.addAction("Retirer de l'ensemble", lambda: self.remove_from_assembly())
        if kind in ("shape", "assembly"):
            m.addAction("Créer un ensemble avec la sélection", self.group_shapes)
        if kind == "assembly":
            m.addAction("Dissocier l'ensemble", self.ungroup_shapes)
            if obj.parent:
                m.addAction("Sortir du sous-groupe (remonter d'un niveau)", self.remove_from_assembly)
        m.addSeparator()
        m.addAction("Décaler…", self.offset_selection)
        m.addAction("Accrocher…", self.snap_selection)
        m.addAction("Verrouiller / déverrouiller", self.toggle_lock)
        m.addAction("Enregistrer comme ensemble…", self.save_ensemble)
        m.addSeparator()
        m.addAction("Dupliquer", self.duplicate)
        m.addAction("Supprimer", self.delete)
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def move_to_group(self, oid, gid):
        o = self.scene.obj(oid)
        if o is None or self.scene.group(gid) is None:
            return
        o.group = gid
        self.sel = oid
        self.schedule(True)
        self.select(oid)

    # ------------------------------------------------------------------ changements
    def schedule(self, structural=False):
        if structural:
            self.scene.sync()
            self.refresh_tree()
            self.refresh_lists()
        self.timer.start()

    def refresh_lists(self):
        self.tab_arr.refresh_lists()
        self.tab_del.refresh_lists()
        self.tab_ref.refresh_lists()
        self.tab_sbir.refresh_lists()

    def after_edit(self, obj):
        """Après modification d'un objet : recopie sur le miroir lié."""
        if obj is not None and getattr(obj, "mirror_of", ""):
            self.scene.propagate(obj)

    def on_props_changed(self, structural):
        kind, obj = self.props.kind, self.props.obj
        if kind == "object":
            self.after_edit(obj)
        self.schedule(structural)

    def on_tab_changed(self, structural):
        if structural:
            self.props.reload()
        self.schedule(structural)

    def on_moved(self, kind, oid, a, b):
        view = self.sender()
        _, obj = self.scene.find(oid)
        if obj is None:
            return
        if E.is_locked(self.scene, kind, obj):
            self.schedule(False)
            return
        obj.x = round(a, 3)
        if view.plane == "xy":
            obj.y = round(b, 3)
        else:
            obj.z = round(b, 3)
        if kind == "object":
            self.after_edit(obj)
        if self.sel != oid:
            self.select(oid)
        self.props.reload()
        self.schedule(False)

    def on_section(self, y):
        self.scene.settings.section_y = round(y, 2)
        self.tab_disp.load()
        self.schedule()

    # ------------------------------------------------------------------ calcul
    def selected_items(self):
        """Éléments sélectionnés [(kind, obj)], l'élément courant en premier."""
        sc = self.scene
        ids = ([self.sel] if self.sel else []) + [i for i in self.multi if i != self.sel]
        out = []
        for i in ids:
            k, o = sc.find(i)
            if o is not None and k != "model":
                out.append((k, o))
        return out

    def selected_sources(self):
        """Sources des HP / groupes sélectionnés, ou None si la sélection n'en contient pas."""
        sc = self.scene
        srcs, any_src = {}, False
        for kind, obj in self.selected_items():
            if kind == "object":
                ss = sc.sources_of(obj.id)
            elif kind == "group":
                ss = sc.sources_in(obj.id)
            else:
                continue
            any_src = True
            for s in ss:
                srcs[s.id] = s
        return list(srcs.values()) if any_src else None

    def selection_ids(self):
        """Identifiants à surligner (ensembles : leurs formes aussi)."""
        ids = set(self.multi) | ({self.sel} if self.sel else set())
        for kind, obj in self.selected_items():
            if kind == "assembly":
                ids |= {s.id for s in self.scene.all_shapes_in(obj.id)}
        return ids

    def sbir_context(self):
        """Contexte du calcul SBIR : sources, écouteur, géométrie, options."""
        sc = self.scene
        st = sc.settings
        lst = sc.listener(st.sbir_listener) or (sc.listeners[0] if sc.listeners else None)
        geo = getattr(self, "_geo", None) or A.Geometry(sc)
        kind, obj = sc.find(self.sel) if self.sel else (None, None)
        sel = self.selected_sources()
        srcs = sc.active_sources() if (st.sbir_scope != "Sélection" or sel is None) else [s for s in sel if not s.mute]
        if lst is None or not srcs:
            return None
        cats = dict(front=st.sbir_front, side=st.sbir_side, floor=st.sbir_floor, ceiling=st.sbir_ceiling,
                    rear=st.sbir_rear_wall)
        opts = dict(order=st.sbir_order, rear_radiation=st.sbir_rear_rad, cats=cats,
                    apply_delays=st.apply_delays, fmin=st.sbir_fmin, fmax=max(st.sbir_fmax, st.sbir_fmin * 2),
                    nf=900)
        return dict(scene=sc, geo=geo, sources=srcs, obj=obj if kind == "object" else None,
                    listener=lst.pos, listener_obj=lst, c=speed_of_sound(st.temperature), opts=opts)

    def compute_sbir(self):
        ctx = self.sbir_context()
        if ctx is None:
            return None
        st = self.scene.settings
        key = self._key(("sbir", self.sel, {k: v for k, v in vars(st).items() if k.startswith("sbir_")},
                         st.apply_delays))
        if self._cache.get("sbir_key") != key:
            f, H, Hd, used = SB.response(ctx["scene"], ctx["geo"], ctx["sources"], ctx["listener"],
                                         ctx["opts"], ctx["c"])
            self._cache["sbir"] = dict(freqs=f, H=H, Hd=Hd, used=used, rows=SB.reflection_table(used, ctx["c"]),
                                       nsrc=len(ctx["sources"]))
            self._cache["sbir_key"] = key
        return self._cache["sbir"]

    def treat_opts(self):
        st = self.scene.settings
        return dict(head_w=st.treat_head_w, head_d=st.treat_head_d, head_h=st.treat_head_h,
                    margin=st.treat_margin, min_level=st.treat_min_level)

    def compute_treatment(self):
        """Zones minimales de traitement (écouteur et sources de l'onglet SBIR)."""
        ctx = self.sbir_context()
        if ctx is None:
            return [], None
        if self.scene.settings.treat_scope != "Sélection":
            ctx = dict(ctx, sources=[s for s in self.scene.active_sources()])
        else:
            sel = self.selected_sources()
            ctx = dict(ctx, sources=self.scene.active_sources() if sel is None else [s for s in sel if not s.mute])
        if not ctx["sources"]:
            return [], None
        key = self._key(("treat", self.sel, sorted(s.id for s in ctx["sources"]), ctx["listener_obj"].id,
                         self.treat_opts()))
        if self._cache.get("treat_key") != key:
            self._cache["treat"] = T.compute_zones(self.scene, ctx["sources"], ctx["listener"], self.treat_opts())
            self._cache["treat_key"] = key
        return self._cache["treat"], ctx

    def place_treatment(self):
        zones, _ = self.compute_treatment()
        if not zones:
            QtWidgets.QMessageBox.information(self, "Traitement", "Aucune zone à traiter.")
            return
        created = T.place_panels(self.scene, zones, self.scene.settings.treat_gap)
        self.status.setText(f"{len(created)} panneau(x) posé(s)")
        self.schedule(True)

    def remove_treatment(self):
        n = T.remove_treatment(self.scene)
        if self.sel and self.scene.find(self.sel)[1] is None:
            self.sel = None
            self.props.set_object(None, None)
        self.multi = {i for i in self.multi if self.scene.find(i)[1] is not None}
        self.status.setText(f"{n} panneau(x) retiré(s)")
        self.schedule(True)

    def add_bass_trap(self, opts):
        cs = self._corners or T.room_corners(self.scene)
        i = opts.get("corner", 0)
        if not cs or not (0 <= i < len(cs)):
            QtWidgets.QMessageBox.information(self, "Bass trap", "Aucun angle de pièce trouvé.")
            return
        st = self.scene.settings
        sh = T.make_bass_trap(self.scene, cs[i], opts["kind"], st.bt_size, opts.get("height", 0.0), st.bt_alpha)
        self.sel = sh.id
        self.multi = {sh.id}
        self.status.setText(f"{sh.name} ajouté ({cs[i]['label']})")
        self.schedule(True)
        self.select(sh.id)

    def export_analysis_pdf(self):
        from .report import export_analysis
        export_analysis(self)

    def export_cutlist_pdf(self):
        from .report import export_cutlist
        export_cutlist(self)

    def _key(self, extra=None):
        d = self.scene.to_dict()
        d["settings"] = {k: v for k, v in d["settings"].items() if k in SPL_KEYS}
        d["extra"] = extra
        return json.dumps(d, sort_keys=True, default=str)

    def recompute(self):
        t0 = time.perf_counter()
        sc = self.scene
        st = sc.settings
        A.CURRENT_FREQ[0] = st.freq
        sc.sync()
        c = speed_of_sound(st.temperature)
        geo = A.Geometry(sc)
        self._geo = geo
        delay_rows = A.compute_delays(sc, geo)
        active = sc.active_sources()
        selected = self.selected_sources()
        sel_active = [s for s in (selected or []) if not s.mute]

        rays = None
        if st.show_rays:
            rs = sel_active if st.rays_selection_only else active
            rays = A.trace_rays(geo, rs, st.nrays, st.max_order, st.ray_len) if rs else None
            if rays is not None and st.rays_listener_only:
                tg = [(l.pos, l.head_d / 2 if l.head else st.rays_capture) for l in sc.listeners]
                rays = A.rays_reaching(rays, tg) if tg else None

        cones = {}
        if st.show_cov:
            for s in active:
                cones[s.id] = A.cone(s, geo, st.cov_range, st.cov_clip)

        refl = []
        lst = sc.listener(st.refl_listener) or (sc.listeners[0] if sc.listeners else None)
        if lst is not None:
            rsrc = sel_active if selected is not None else active
            key = self._key(("refl", lst.id, st.refl_order, [s.id for s in rsrc]))
            if self._cache.get("refl_key") != key:
                self._cache["refl"] = A.reflection_paths(geo, rsrc, lst.pos, st.refl_order, c)
                self._cache["refl_key"] = key
            refl = self._cache["refl"]

        maps, section = [], None
        spl_src = sel_active if (st.spl_scope == "Sélection" and sel_active) else active
        if st.show_spl and spl_src:
            key = self._key(("spl", sorted(s.id for s in spl_src)))
            if self._cache.get("spl_key") != key:
                self._cache["maps"] = A.spl_maps(sc, spl_src, c)
                self._cache["section"] = A.spl_section(sc, spl_src, c, geo) if st.show_section else None
                self._cache["spl_key"] = key
            maps, section = self._cache["maps"], self._cache["section"]
        allv = [m["db"][np.isfinite(m["db"])] for m in maps]
        if section is not None:
            allv.append(section["db"][np.isfinite(section["db"])])
        allv = np.concatenate(allv) if allv else np.zeros(0)
        vals = allv.size > 0
        # percentile : ignore le champ proche d'une enceinte posée dans la coupe
        vmax = float(np.ceil(np.percentile(allv, 99.5))) if vals else 110.0
        vmin = vmax - st.dyn
        lab = f"{st.freq:g} Hz · {st.band}" if st.band != "Énergie" else "énergie"
        if spl_src is not active:
            lab += " · sélection"
        self.legend.set_range(vmin, vmax, lab if vals else "")

        shown = refl if (st.show_refl and selected is not None) else []
        sbir_res = None
        if self.tabs.currentWidget() is self.tab_sbir and not self._previewing:
            sbir_res = self.compute_sbir()
            self.tab_sbir.show_result(sbir_res)
            if sbir_res is not None and st.sbir_show_paths:
                shown = [p for p in sbir_res["used"] if p["order"] > 0]
        zones, zone_plan = [], {}
        treat_tab = self.tabs.currentWidget() is self.tab_treat
        if (treat_tab or st.treat_show) and not self._previewing:
            zones, tctx = self.compute_treatment()
            placed = T.panel_rects(sc, zones)
            for z in zones:
                cfg = T.zone_cfg(z, st)
                if cfg["on"] and not placed.get(z.key):
                    zone_plan[z.key] = T.layout(z, cfg, st.treat_gap)["rects"]
            if treat_tab:
                self.tab_treat.show_result(zones, placed)
                fwd = T.forward_dir(tctx["sources"], tctx["listener"]) if tctx is not None else None
                self._corners = T.room_corners(sc, tctx["listener"] if tctx is not None else None, fwd)
                self.tab_treat.set_corners(self._corners, T.bass_traps(sc))
                if tctx is not None:
                    names = sorted({s.name.split(" · ")[0] for s in tctx["sources"]})
                    self.tab_treat.set_context(f"Écoute « {tctx['listener_obj'].name} » · "
                                               f"{', '.join(names[:6])}")
                else:
                    self.tab_treat.set_context("Ajoutez un écouteur et des enceintes.")
            if st.treat_hide_zones:
                zones, zone_plan = [], {}
        corners = None
        k0, o0 = sc.find(self.sel) if self.sel else (None, None)
        if k0 in ("shape", "assembly", "object") and o0 is not None:
            P, _ = E.sorted_points(sc, k0, o0)
            if 0 < len(P) <= 200:
                corners = P
        res = dict(rays=rays, cones=cones, refl=shown, maps=maps, section=section,
                   range=(vmin, vmax), src_by_id={s.id: s for s in sc.sources},
                   corners=corners, markers=self.markers, zones=zones, zone_plan=zone_plan)
        self._last_res = res
        if self.orbit_btn.isChecked():
            l = self.anchor_listener()
            self._anchor_id = l.id if l else None
            self.v3d.anchor = l.pos if l else None
        selset = self.selection_ids()
        self.v3d.render(sc, res, selset)
        self.vtop.render(sc, res, selset)
        self.vside.render(sc, res, selset)

        self.tab_del.update_rows(delay_rows, c)
        self.tab_ref.update_rows(refl, c)
        self.tab_arr.refresh_report()
        self.tab_disp.update_info(sc)
        self.props.update_info(sc)
        if not self._previewing:
            self._push_history()
        dt = (time.perf_counter() - t0) * 1000
        self.status.setText(f"c = {c:.1f} m/s   ·   {len(sc.objects)} objets · {len(sc.sources)} sources   ·   "
                            f"{geo.F} faces   ·   {dt:.0f} ms  ")

    # ------------------------------------------------------------------ formes
    def add_shape(self, kind):
        defaults = {"Pièce": ([[0, 0], [10, 0], [10, 6.5], [0, 6.5]], "XY", 3.0, False, True),
                    "Objet": ([[0, 0], [2, 0], [2, 2], [0, 2]], "XY", 1.0, False, False),
                    "Surface": ([[0, 0], [5, 0], [5, 5], [0, 5]], "XY", 0.0, False, False)}
        prof, plane, h, sym, rec = defaults[kind]
        dlg = SketchDialog(self, prof, "shape", kind, plane, h, sym, rec, title=f"Nouvelle forme · {kind}")
        if not dlg.exec():
            return
        v = dlg.values()
        n = sum(s.kind == v["kind"] for s in self.scene.shapes) + 1
        sh = Shape(f"{v['kind']} {n}", v["kind"], v["profile"], v["plane"], v["height"], v["symmetric"],
                   absorption=0.15 if v["kind"] == "Pièce" else 0.2, audience=v["kind"] != "Objet",
                   arcs=v["arcs"])
        if v["recenter"]:
            sh.recenter()
        self.scene.shapes.append(sh)
        self._cache.clear()
        self.sel = sh.id
        self.schedule(True)
        self.select(sh.id)
        if sh.kind == "Pièce" and len([s for s in self.scene.shapes if s.kind == "Pièce"]) == 1:
            self.fit_views()

    def edit_sketch(self, sh):
        if sh is None:
            return
        dlg = SketchDialog(self, sh.profile, "shape", sh.kind, sh.plane, sh.height, sh.symmetric,
                           sh.kind == "Pièce", title=f"Esquisse · {sh.name}", arcs=sh.arcs)
        if not dlg.exec():
            return
        v = dlg.values()
        sh.arcs = v["arcs"]
        sh.profile, sh.kind, sh.plane, sh.height, sh.symmetric = (v["profile"], v["kind"], v["plane"],
                                                                  v["height"], v["symmetric"])
        if v["recenter"]:
            sh.x = sh.y = sh.z = 0.0
            sh.recenter()
        self.props.set_object("shape", sh)
        self.schedule(True)

    def recenter_shape(self, sh):
        sh.recenter()
        self.props.reload()
        self.schedule(True)

    # ------------------------------------------------------------------ objets
    def _target_group(self):
        sc = self.scene
        kind, obj = sc.find(self.sel) if self.sel else (None, None)
        if kind == "group":
            return obj
        if kind == "object":
            return sc.group(obj.group)
        if sc.groups:
            return sc.groups[0]
        return self.add_group(select=False)

    def add_group(self, select=True):
        sc = self.scene
        g = Group(f"Groupe {len(sc.groups) + 1}", sc.next_color(), main=not sc.groups)
        sc.groups.append(g)
        if select:
            self.schedule(True)
            self.select(g.id)
        return g

    def _model_for(self, prefer):
        sc = self.scene
        return next((m.id for m in sc.models if m.id == prefer), sc.models[0].id if sc.models else "")

    def _place(self, o):
        lo, hi = self.scene.bbox()
        o.x = round(float(lo[0] + min(2.0, (hi[0] - lo[0]) * 0.15)), 2)
        if o.TYPE != "row":
            o.y = round(float(lo[1] + (hi[1] - lo[1]) * 0.3), 2)
        o.z = round(min(o.z, float(hi[2]) - 0.3), 2)
        return o

    def add_speaker(self):
        g = self._target_group()
        o = Speaker(f"HP {sum(x.TYPE == 'speaker' for x in self.scene.objects) + 1}", g.id,
                    self._model_for("ps12"), x=0.0, y=0.0, z=3.0, el=-10)
        self._place(o)
        self._add_obj(o)

    def add_array(self):
        g = self._target_group()
        sc = self.scene
        o = LineArray(f"Line array {sum(x.TYPE == 'array' for x in sc.objects) + 1}", g.id,
                      self._model_for("la12"), z=min(8.0, float(sc.bbox()[1][2]) - 0.5), n=8)
        self._place(o)
        st = sc.settings
        A.optimize_array(o, sc.model(o.model), st.opt_near, st.opt_far, st.opt_znear, st.opt_zfar,
                         st.opt_max, st.opt_step, st.opt_weight)
        self._add_obj(o)
        self.tabs.setCurrentWidget(self.tab_arr)

    def add_row(self):
        g = self._target_group()
        o = Row(f"Rangée {sum(x.TYPE == 'row' for x in self.scene.objects) + 1}", g.id,
                self._model_for("ff5"), y=-4.5, z=1.2, n=4, spacing=3, el=-5)
        self._place(o)
        self._add_obj(o)

    def _add_obj(self, o):
        self.scene.objects.append(o)
        self.sel = o.id
        self.schedule(True)
        self.select(o.id)

    def add_listener(self):
        l = Listener(f"Écoute {len(self.scene.listeners) + 1}", 0.0, 0.0, 1.2)
        self.scene.listeners.append(l)
        if not self.scene.settings.refl_listener:
            self.scene.settings.refl_listener = l.id
        self.schedule(True)
        self.select(l.id)

    def mirror(self, axis):
        sc = self.scene
        kind, obj = sc.find(self.sel) if self.sel else (None, None)
        if kind == "group":
            objs = [o for o in sc.objects_in(obj.id) if not o.mirror_of]
        elif kind == "object":
            objs = [obj]
        else:
            QtWidgets.QMessageBox.information(self, "Miroir", "Sélectionnez un HP, un line array, une rangée ou un groupe.")
            return
        made = None
        for o in objs:
            if o.mirror_of:
                if o.mirror_axis != axis:
                    QtWidgets.QMessageBox.information(self, "Miroir", f"« {o.name} » est déjà lié en miroir "
                                                                      f"{o.mirror_axis}. Déliez-le d'abord.")
                continue
            made = sc.make_mirror(o, axis)
        self.schedule(True)
        if made is not None and kind == "object":
            self.select(made.id)

    def toggle_lock(self):
        sc = self.scene
        targets = []
        for kind, obj in self.selected_items():
            if kind == "group":
                targets += sc.objects_in(obj.id)
            elif kind in ("object", "shape", "listener", "assembly"):
                targets.append(obj)
        if not targets:
            return
        state = not all(getattr(o, "locked", False) for o in targets)
        for o in targets:
            o.locked = state
            p = sc.partner(o) if hasattr(o, "mirror_of") else None
            if p is not None:
                p.locked = state
        self.props.rebuild()
        self.schedule(True)

    # ------------------------------------------------------------------ décaler / accrocher / ensembles
    def offset_selection(self):
        items = self.selected_items()
        if not items:
            QtWidgets.QMessageBox.information(self, "Décaler", "Sélectionnez un ou plusieurs éléments "
                                                              "(Ctrl+clic ou Maj+clic dans l'arbre).")
            return
        dlg = OffsetDialog(self.scene, items, self)
        if not dlg.exec():
            return
        v = dlg.vector()
        if dlg.copy.isChecked():
            d = E.ensemble_dict(self.scene, items, "copie")
            created = E.insert_ensemble(self.scene, d, v)
            if created:
                self.multi = {o.id for _, o in created}
                self.sel = created[0][1].id
            self.status.setText(f"{len(created)} élément(s) copié(s)")
        else:
            moved, locked = E.translate(self.scene, items, v)
            self.status.setText(f"{len(moved)} élément(s) décalé(s)" +
                                (f" · {len(locked)} verrouillé(s) ignoré(s)" if locked else ""))
        self.props.reload()
        self.schedule(True)
        kind, obj = self.scene.find(self.sel) if self.sel else (None, None)
        self.props.set_object(kind if kind != "model" else None, obj if kind != "model" else None)

    def snap_selection(self):
        items = self.selected_items()
        if not items or items[0][0] not in ("shape", "assembly", "object", "listener"):
            QtWidgets.QMessageBox.information(self, "Accrocher", "Sélectionnez une forme, un ensemble, un HP ou un "
                                                                 "écouteur à déplacer.")
            return
        dlg = SnapDialog(self.scene, items, items[0], self)
        dlg.preview.connect(self._snap_preview)
        self._previewing = True
        try:
            dlg.update_preview()
            ok = dlg.exec()
        finally:
            self._previewing = False
            self.markers = []
        self.props.reload()
        self.schedule(True)
        if ok:
            self.status.setText("Élément accroché")

    def _snap_preview(self, markers):
        self.markers = markers
        self.scene.sync()
        self.recompute()

    def group_shapes(self):
        """Crée un ensemble avec les formes et ensembles sélectionnés. Un ensemble sélectionné devient un
        sous-ensemble du nouvel ensemble (sous-groupe)."""
        sc = self.scene
        items = self.selected_items()
        subs = [o for k, o in items if k == "assembly"]
        sub_ids = set()
        for a in subs:
            sub_ids |= {b.id for b in sc.descendant_assemblies(a.id)}
        subs = [a for a in subs if a.id not in sub_ids]          # garde les plus hauts sélectionnés
        inside = {a.id for a in subs} | sub_ids
        shapes = [o for k, o in items if k == "shape" and o.kind != "Pièce" and o.assembly not in inside]
        shapes = list({s.id: s for s in shapes}.values())
        if not shapes and not subs:
            QtWidgets.QMessageBox.information(self, "Ensemble", "Sélectionnez des formes (objets ou surfaces) ou des "
                                                                "ensembles avec Ctrl+clic dans l'arbre.")
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "Ensemble", "Nom de l'ensemble :",
                                                  text=f"Ensemble {len(sc.assemblies) + 1}")
        if not ok:
            return
        a = E.make_assembly(sc, shapes, name.strip() or None, subs)
        sc.prune_assemblies()
        self.schedule(True)
        self.select(a.id)

    def ungroup_shapes(self):
        sc = self.scene
        for kind, obj in self.selected_items():
            if kind == "assembly":
                E.dissolve(sc, obj)
        self.sel = None
        self.multi = set()
        self.props.set_object(None, None)
        self.schedule(True)

    def remove_from_assembly(self):
        sc = self.scene
        for kind, obj in self.selected_items():
            if kind == "shape" and obj.assembly:
                a = sc.assembly(obj.assembly)
                obj.assembly = a.parent if a is not None else ""     # remonte d'un niveau
            elif kind == "assembly" and obj.parent:
                p = sc.assembly(obj.parent)
                obj.parent = p.parent if p is not None else ""
        sc.prune_assemblies()
        self.schedule(True)

    def on_drop(self, dragged, tkind, tid):
        sc = self.scene
        changed = False
        for kind, oid in dragged:
            k, o = sc.find(oid)
            if k == "object" and tkind == "group":
                o.group = tid; changed = True
            elif k == "shape" and tkind == "assembly" and o.kind != "Pièce":
                o.assembly = tid; changed = True
            elif k == "shape" and tkind == "shapes_root":
                o.assembly = ""; changed = True
            elif k == "assembly" and tkind == "assembly" and E.can_nest(sc, o.id, tid):
                o.parent = tid; changed = True            # sous-ensemble
            elif k == "assembly" and tkind == "shapes_root":
                o.parent = ""; changed = True
        sc.prune_assemblies()
        if changed:
            self.schedule(True)

    def save_ensemble(self):
        items = self.selected_items()
        if not items:
            QtWidgets.QMessageBox.information(self, "Ensemble", "Sélectionnez ce qu'il faut enregistrer "
                                                                "(ensembles, formes, HP, écouteurs).")
            return
        name = items[0][1].name if items[0][0] == "assembly" else "ensemble"
        os.makedirs(ENSEMBLE_DIR, exist_ok=True)
        p, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Enregistrer l'ensemble",
                                                     os.path.join(ENSEMBLE_DIR, f"{name}.r3dset"),
                                                     "Ensemble Ray 3D (*.r3dset)")
        if not p:
            return
        if not p.lower().endswith(".r3dset"):
            p += ".r3dset"
        d = E.save_ensemble(self.scene, items, p, os.path.splitext(os.path.basename(p))[0])
        self.status.setText(f"Ensemble enregistré : {len(d['shapes'])} forme(s), {len(d['objects'])} HP")

    def insert_ensemble(self):
        os.makedirs(ENSEMBLE_DIR, exist_ok=True)
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Insérer un ensemble", ENSEMBLE_DIR,
                                                     "Ensemble Ray 3D (*.r3dset *.json)")
        if not p:
            return
        try:
            created = E.insert_ensemble(self.scene, E.load_ensemble(p))
        except Exception as ex:
            QtWidgets.QMessageBox.warning(self, "Ensemble", f"Lecture impossible :\n{ex}")
            return
        if created:
            self.multi = {o.id for _, o in created}
            self.sel = created[0][1].id
        self.schedule(True)
        kind, obj = self.scene.find(self.sel) if self.sel else (None, None)
        self.props.set_object(kind, obj)
        self.status.setText(f"Ensemble inséré ({len(created)} élément(s)) — utilisez Accrocher ou Décaler pour le placer")

    # ------------------------------------------------------------------ annuler / sauvegarde auto
    def _snapshot(self):
        return json.dumps(self.scene.to_dict(), sort_keys=True, default=str)

    def _push_history(self):
        if self._restoring:
            return
        snap = self._snapshot()
        if self.hpos >= 0 and self.history[self.hpos] == snap:
            return
        del self.history[self.hpos + 1:]
        self.history.append(snap)
        if len(self.history) > 200:
            self.history.pop(0)
        self.hpos = len(self.history) - 1
        if self.hpos > 0:
            self.dirty = True

    def _restore(self, snap):
        sel = self.sel
        self._restoring = True
        try:
            sc = Scene.from_dict(json.loads(snap))
            self.scene = sc
            self._cache.clear()
            for t in (self.tab_disp, self.tab_arr, self.tab_del, self.tab_ref, self.tab_sbir, self.tab_treat):
                t.load()
            self.sel = sel if sc.find(sel)[1] is not None else None
            self.multi = {i for i in self.multi if sc.find(i)[1] is not None}
            kind, obj = sc.find(self.sel) if self.sel else (None, None)
            self.props.set_object(kind if kind != "model" else None, obj if kind != "model" else None)
            self.refresh_tree()
            self.refresh_lists()
            self.recompute()
        finally:
            self._restoring = False
        self.dirty = True

    def undo(self):
        if self.hpos > 0:
            self.hpos -= 1
            self._restore(self.history[self.hpos])
            self.status.setText(f"Annulé · {self.hpos} étape(s) restante(s)")

    def redo(self):
        if self.hpos < len(self.history) - 1:
            self.hpos += 1
            self._restore(self.history[self.hpos])
            self.status.setText("Rétabli")

    def autosave(self, force=False):
        if not (self.dirty or force):
            return
        try:
            os.makedirs(os.path.dirname(AUTOSAVE), exist_ok=True)
            tmp = AUTOSAVE + ".tmp"
            self.scene.save(tmp)
            os.replace(tmp, AUTOSAVE)
            self.dirty = False
            self.status.setText(f"Sauvegarde automatique {time.strftime('%H:%M:%S')}")
        except OSError as e:
            self.status.setText(f"Sauvegarde automatique impossible : {e}")

    def closeEvent(self, ev):
        self.autosave(force=True)
        super().closeEvent(ev)

    def unlink(self, o):
        self.scene.unlink(o)
        self.props.rebuild()
        self.schedule(True)

    def duplicate(self):
        sc = self.scene
        items = self.selected_items()
        if not items:
            return
        if len(items) == 1 and items[0][0] == "group":
            obj = items[0][1]
            new = copy.deepcopy(obj); new.id = new_id(); new.name = obj.name + " copie"
            new.color = sc.next_color(); new.main = False
            sc.groups.append(new)
            for o in sc.objects_in(obj.id):
                o2 = copy.deepcopy(o); o2.id = new_id(); o2.group = new.id; o2.mirror_of = o2.mirror_axis = ""
                o2.locked = False
                sc.objects.append(o2)
            self.schedule(True)
            self.select(new.id)
            return
        d = E.ensemble_dict(sc, items, "copie")
        created = E.insert_ensemble(sc, d, (0.0, 1.0, 0.0))
        for k, o in created:
            if hasattr(o, "name") and k != "assembly":
                o.name = o.name + " copie"
            if hasattr(o, "locked"):
                o.locked = False
        if created:
            self.multi = {o.id for _, o in created}
            self.sel = created[0][1].id
        self.schedule(True)
        kind, obj = sc.find(self.sel) if self.sel else (None, None)
        self.props.set_object(kind, obj)

    def delete(self):
        sc = self.scene
        items = self.selected_items()
        if not items:
            return
        groups = [o for k, o in items if k == "group" and sc.objects_in(o.id)]
        asms = [o for k, o in items if k == "assembly" and sc.all_shapes_in(o.id)]
        if groups or asms:
            n = sum(len(sc.objects_in(g.id)) for g in groups) + sum(len(sc.all_shapes_in(a.id)) for a in asms)
            r = QtWidgets.QMessageBox.question(self, "Supprimer", f"Supprimer aussi les {n} élément(s) contenus "
                                                                   f"dans les groupes / ensembles sélectionnés ?")
            if r != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        for kind, obj in items:
            if kind == "shape" and obj in sc.shapes:
                sc.shapes.remove(obj)
            elif kind == "assembly" and obj in sc.assemblies:
                ids = {obj.id} | {b.id for b in sc.descendant_assemblies(obj.id)}
                sc.shapes = [s for s in sc.shapes if s.assembly not in ids]
                sc.assemblies = [a for a in sc.assemblies if a.id not in ids]
            elif kind == "object" and obj in sc.objects:
                sc.unlink(obj)
                sc.objects.remove(obj)
            elif kind == "group" and obj in sc.groups:
                for o in sc.objects_in(obj.id):
                    sc.unlink(o)
                sc.objects = [o for o in sc.objects if o.group != obj.id]
                sc.groups.remove(obj)
            elif kind == "listener" and obj in sc.listeners:
                sc.listeners.remove(obj)
        sc.prune_assemblies()
        self.sel = None
        self.multi = set()
        self.props.set_object(None, None)
        self.schedule(True)

    def open_library(self, mid=None):
        dlg = LibraryDialog(self.scene, self, select=mid)
        dlg.exec()
        self._cache.clear()
        self.props.rebuild()
        self.schedule(True)

    # ------------------------------------------------------------------ fichiers
    def set_scene(self, sc):
        self.history, self.hpos = [], -1
        self.scene = sc
        self.sel = None
        self.multi = set()
        self._cache.clear()
        self.props.set_object(None, None)
        for t in (self.tab_disp, self.tab_arr, self.tab_del, self.tab_ref, self.tab_sbir, self.tab_treat):
            t.load()
        self.refresh_tree()
        self.refresh_lists()
        self.fit_views()
        self.recompute()

    def new_scene(self):
        sc = Scene()
        sc.models = default_models()
        room = Shape("Salle", "Pièce", [[0, 0], [10, 0], [10, 6.5], [0, 6.5]], "XY", 3.0,
                     absorption=0.15, audience=True)
        room.recenter()
        sc.shapes = [room]
        sc.groups = [Group("Main", S.ACCENT, main=True)]
        sc.settings.opt_near, sc.settings.opt_far, sc.settings.opt_zfar = 1.5, 8.0, 1.2
        sc.sync()
        self.set_scene(sc)

    def open_scene(self):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Ouvrir", "", "Scène Ray 3D (*.json)")
        if p:
            try:
                self.set_scene(Scene.load(p))
                self.path = p
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Ouvrir", f"Impossible de lire le fichier :\n{e}")

    def save_scene(self):
        p = self.path
        if not p:
            p, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Enregistrer", "scene.json", "Scène Ray 3D (*.json)")
        if p:
            self.scene.save(p)
            self.path = p
            self.status.setText(f"Enregistré : {p}")

    def fit_views(self):
        for v in (self.v3d, self.vtop, self.vside):
            v.fit(self.scene)


def setup_app(argv):
    QtWidgets.QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    loc = QtCore.QLocale.c()
    loc.setNumberOptions(QtCore.QLocale.NumberOption.OmitGroupSeparator |
                         QtCore.QLocale.NumberOption.RejectGroupSeparator)
    QtCore.QLocale.setDefault(loc)
    app = QtWidgets.QApplication(argv)
    app.setStyle("Fusion")
    pal = app.palette()
    for role, col in ((QtGui.QPalette.ColorRole.Window, S.BG), (QtGui.QPalette.ColorRole.Base, S.PANEL),
                      (QtGui.QPalette.ColorRole.Text, S.TEXT), (QtGui.QPalette.ColorRole.WindowText, S.TEXT),
                      (QtGui.QPalette.ColorRole.Button, S.PANEL), (QtGui.QPalette.ColorRole.ButtonText, S.TEXT),
                      (QtGui.QPalette.ColorRole.Highlight, S.ACCENT)):
        pal.setColor(role, QtGui.QColor(col))
    app.setPalette(pal)
    app.setStyleSheet(S.QSS)
    pg.setConfigOptions(antialias=True, background=S.BG, foreground=S.DIM)
    return app


def main():
    app = setup_app(sys.argv)
    sc = Scene.load(sys.argv[1]) if len(sys.argv) > 1 else None
    if sc is None and os.path.exists(AUTOSAVE):
        when = time.strftime("%d/%m %H:%M", time.localtime(os.path.getmtime(AUTOSAVE)))
        r = QtWidgets.QMessageBox.question(None, "Ray 3D", f"Restaurer la session sauvegardée automatiquement "
                                                           f"({when}) ?")
        if r == QtWidgets.QMessageBox.StandardButton.Yes:
            try:
                sc = Scene.load(AUTOSAVE)
            except Exception:
                sc = None
    w = MainWindow(sc)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
