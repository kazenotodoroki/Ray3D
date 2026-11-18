"""Onglet TÉLÉMÈTRE : serveur pour smartphone, repère, points mesurés, construction de la scène."""
from __future__ import annotations

import math
import os
import shutil
import webbrowser

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from . import style as S
from . import telemetry as TM
from . import teleserver as TS
from .panels import scroll_form, make_table, cell
from .widgets import NoWheelCombo, NumField


def _nf(v=0.0, lo=0.0, hi=1000.0, step=0.01, dec=3, suf=" m"):
    return NumField(v, lo, hi, step, dec, suf)


class TeleAPI:
    """Fonctions appelées par le serveur (toujours dans le fil Qt)."""

    def __init__(self, app):
        self.app = app

    def name(self):
        p = getattr(self.app, "path", None)
        return os.path.basename(p) if p else "scène sans nom"

    def state(self):
        from .model import speed_of_sound
        return TM.state_json(self.app.scene, dict(scene=self.name(),
                                                  c=speed_of_sound(self.app.scene.settings.temperature)))

    def set_ref(self, d):
        TM.update_ref(self.app.scene.telemetry, d)
        self.app.tele_changed()
        return self.state()

    def save_point(self, d):
        p = TM.upsert_point(self.app.scene.telemetry, d)
        self.app.tele_changed()
        return dict(point=p, state=self.state())

    def delete_point(self, d):
        TM.delete_point(self.app.scene.telemetry, d.get("id"))
        self.app.tele_changed()
        return self.state()

    def preview(self, d):
        tel = dict(self.app.scene.telemetry)
        q = dict(d, id="__preview__")
        tel = dict(ref=tel["ref"], points=[q], ver=0)
        _, pts = TM.solve(tel)
        p = pts[0]
        return dict(ok=p["ok"], P=None if p["P"] is None else [float(x) for x in p["P"]], warn=p["warn"],
                    prec=TM.precision_text(p["sig"]) if p["ok"] else "")

    def build(self, d):
        msg = self.app.tele_build(d)
        return dict(message=msg, state=self.state())


class TeleTab(QtWidgets.QWidget):
    changed = QtCore.Signal()
    build = QtCore.Signal(dict)

    def __init__(self, scene_getter, app):
        super().__init__()
        self.scene = scene_getter
        self.app = app
        self.server = TS.TeleServer(TeleAPI(app))
        self._edit = None
        self._loading = False
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        sa, form = scroll_form(); lay.addWidget(sa)
        self.form = form

        # --- serveur
        self._section(form, "Serveur pour smartphone")
        hb = QtWidgets.QHBoxLayout()
        self.port = NumField(8765, 1024, 65535, 1, 0, "", integer=True)
        self.srv_btn = QtWidgets.QPushButton("Démarrer le serveur"); self.srv_btn.setObjectName("primary")
        self.srv_btn.clicked.connect(self.toggle_server)
        hb.addWidget(QtWidgets.QLabel("Port")); hb.addWidget(self.port); hb.addWidget(self.srv_btn, 1)
        form.addRow(hb)
        self.srv_lab = QtWidgets.QLabel("Arrêté.")
        f = self.srv_lab.font(); f.setPointSizeF(f.pointSizeF() * 1.25); f.setBold(True); self.srv_lab.setFont(f)
        self.srv_lab.setWordWrap(True)
        self.srv_lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow(self.srv_lab)
        hb = QtWidgets.QHBoxLayout()
        b1 = QtWidgets.QPushButton("Ouvrir la page"); b1.clicked.connect(self.open_page)
        b2 = QtWidgets.QPushButton("Choisir l'APK Android…"); b2.clicked.connect(self.pick_apk)
        hb.addWidget(b1); hb.addWidget(b2)
        form.addRow(hb)
        self.apk_lab = self._info(form, "")
        self._info(form, "Sur le téléphone (même Wi-Fi) : ouvrez l'adresse ci-dessus dans le navigateur, puis "
                         "« Télécharger l'application Android » ou « Ouvrir dans le navigateur ». L'application "
                         "trouve le serveur toute seule. Windows peut demander d'autoriser Python sur le réseau privé.")

        # --- repère
        self._section(form, "Repère A, B, C")
        self.mode = NoWheelCombo(); self.mode.addItem("Libre (comme Régie)", "libre")
        self.mode.addItem("Sur des points de la scène", "scene")
        self.mode.currentIndexChanged.connect(self._ref_edited)
        form.addRow("Mode", self.mode)
        self.libre = QtWidgets.QWidget(); fl = QtWidgets.QFormLayout(self.libre); fl.setContentsMargins(0, 0, 0, 0)
        self.rAB, self.rAC, self.rBC = _nf(), _nf(), _nf()
        self.rH0 = _nf(0.0, 0, 5)
        self.rFlip = QtWidgets.QCheckBox("C est à droite quand on regarde de A vers B")
        for lab, w in (("A–B", self.rAB), ("A–C", self.rAC), ("B–C", self.rBC), ("Hauteur de mesure", self.rH0)):
            fl.addRow(lab, w)
        fl.addRow(self.rFlip)
        self.rAx, self.rAy, self.rAz = _nf(0, -1e4, 1e4), _nf(0, -1e4, 1e4), _nf(0, -1e4, 1e4)
        hb = QtWidgets.QHBoxLayout()
        for w in (self.rAx, self.rAy, self.rAz):
            hb.addWidget(w)
        fl.addRow("A dans la scène (X, Y, sol Z)", hb)
        self.rRot = NumField(0, -360, 360, 1, 1, " °")
        fl.addRow("Direction A→B (azimut)", self.rRot)
        form.addRow(self.libre)
        self.scn = QtWidgets.QWidget(); fs = QtWidgets.QFormLayout(self.scn); fs.setContentsMargins(0, 0, 0, 0)
        self.pick, self.xyz = {}, {}
        for k in "ABC":
            cb = NoWheelCombo(); cb.activated.connect(lambda i, k=k: self._take_point(k, i))
            self.pick[k] = cb
            fs.addRow(f"{k} : prendre", cb)
            hb = QtWidgets.QHBoxLayout()
            self.xyz[k] = [_nf(0, -1e4, 1e4) for _ in range(3)]
            for w in self.xyz[k]:
                hb.addWidget(w)
            fs.addRow(f"{k} (X, Y, Z)", hb)
        form.addRow(self.scn)
        for w in (self.rAB, self.rAC, self.rBC, self.rH0, self.rAx, self.rAy, self.rAz, self.rRot,
                  *[w for k in "ABC" for w in self.xyz[k]]):
            w.valueChanged.connect(self._ref_edited)
        self.rFlip.toggled.connect(self._ref_edited)
        self.ref_lab = QtWidgets.QLabel(); self.ref_lab.setObjectName("value"); self.ref_lab.setWordWrap(True)
        form.addRow(self.ref_lab)
        self._info(form, "Libre : marquez trois points au sol, mesurez les trois côtés, puis placez A et la "
                         "direction A→B dans la scène. Sur des points de la scène : A, B, C sont des points connus "
                         "(angles de la pièce…) ; les sources et objets mesurés depuis ces points tombent "
                         "directement au bon endroit par triangulation.")

        # --- points
        self._section(form, "Points mesurés")
        self.table = make_table(["Nom", "Type", "Groupe", "A", "B", "C", "X", "Y", "Z", "±"], stretch=0)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setMinimumHeight(200)
        self.table.itemSelectionChanged.connect(self._row_changed)
        form.addRow(self.table)
        self.rel_lab = QtWidgets.QLabel("Depuis le point sélectionné : distances et angles vers les enceintes "
                                        "et les écoutes")
        self.rel_lab.setObjectName("info"); self.rel_lab.setWordWrap(True)
        form.addRow(self.rel_lab)
        self.rel = make_table(["Vers", "Distance", "Délai", "Site", "Azimut", "Hors axe (ce point)",
                               "Incidence (sur l'autre)"], stretch=0)
        self.rel.setMinimumHeight(120)
        form.addRow(self.rel)
        self.pName = QtWidgets.QLineEdit()
        self.pType = NoWheelCombo()
        for k, v in TM.TYPES.items():
            self.pType.addItem(v, k)
        self.pGroup = QtWidgets.QComboBox(); self.pGroup.setEditable(True)
        form.addRow("Nom", self.pName)
        form.addRow("Type", self.pType)
        form.addRow("Groupe / objet", self.pGroup)
        self.pA, self.pB, self.pC = _nf(), _nf(), _nf()
        hb = QtWidgets.QHBoxLayout()
        for w in (self.pA, self.pB, self.pC):
            hb.addWidget(w)
        form.addRow("Distances A, B, C", hb)
        self.pAim = NoWheelCombo()
        form.addRow("Orienté vers", self.pAim)
        hb = QtWidgets.QHBoxLayout()
        self.pHkOn = QtWidgets.QCheckBox("Hauteur connue"); self.pHk = _nf(0, -100, 100)
        hb.addWidget(self.pHkOn); hb.addWidget(self.pHk)
        form.addRow(hb)
        self.pBelow = QtWidgets.QCheckBox("Point sous le plan de mesure")
        form.addRow(self.pBelow)
        self.pv_lab = QtWidgets.QLabel(); self.pv_lab.setObjectName("value"); self.pv_lab.setWordWrap(True)
        form.addRow(self.pv_lab)
        for w in (self.pA, self.pB, self.pC, self.pHk):
            w.valueChanged.connect(self._preview)
        self.pHkOn.toggled.connect(self._preview); self.pBelow.toggled.connect(self._preview)
        hb = QtWidgets.QHBoxLayout()
        self.bSave = QtWidgets.QPushButton("Ajouter"); self.bSave.setObjectName("primary"); self.bSave.clicked.connect(self._save)
        bNew = QtWidgets.QPushButton("Nouveau"); bNew.clicked.connect(self._new)
        self.bDel = QtWidgets.QPushButton("Supprimer"); self.bDel.clicked.connect(self._delete)
        hb.addWidget(self.bSave); hb.addWidget(bNew); hb.addStretch(1); hb.addWidget(self.bDel)
        form.addRow(hb)

        # --- construction
        self._section(form, "Construire dans la scène")
        self.roomH = _nf(0, 0, 100)
        hb = QtWidgets.QHBoxLayout()
        bR = QtWidgets.QPushButton("Créer la pièce"); bR.setObjectName("primary")
        bR.clicked.connect(lambda: self.build.emit(dict(what="room", height=self.roomH.value(),
                                                        ids=self.selected_ids())))
        hb.addWidget(QtWidgets.QLabel("Hauteur (0 = auto)")); hb.addWidget(self.roomH); hb.addWidget(bR, 1)
        form.addRow(hb)
        self.objGroup = NoWheelCombo()
        self.objH = _nf(0, 0, 100)
        self.objTop = QtWidgets.QCheckBox("Les points sont le dessus de l'objet"); self.objTop.setChecked(True)
        form.addRow("Objet (groupe)", self.objGroup)
        hb = QtWidgets.QHBoxLayout()
        bO = QtWidgets.QPushButton("Créer l'objet"); bO.setObjectName("primary")
        bO.clicked.connect(lambda: self.build.emit(dict(what="object", group=self.objGroup.currentData() or "",
                                                        height=self.objH.value(), top=self.objTop.isChecked(),
                                                        ids=self.selected_ids())))
        hb.addWidget(QtWidgets.QLabel("Épaisseur (0 = auto)")); hb.addWidget(self.objH); hb.addWidget(bO, 1)
        form.addRow(hb)
        form.addRow(self.objTop)
        self.spkModel = NoWheelCombo()
        form.addRow("Modèle d'enceinte", self.spkModel)
        hb = QtWidgets.QHBoxLayout()
        for text, what in (("Enceinte au point", "speaker"), ("Écoute au point", "listener"),
                           ("Déplacer la sélection", "move")):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(lambda _=False, w=what: self.build.emit(dict(what=w, point=self.current_id() or "",
                                                                           model=self.spkModel.currentData())))
            hb.addWidget(b)
        form.addRow(hb)
        self._info(form, "Pièce : angles au sol (et au plafond pour la hauteur), ou les points sélectionnés dans "
                         "le tableau. Objet : contour des points du groupe choisi (ou de la sélection) ; auto = du "
                         "sol jusqu'aux points s'ils sont à la même hauteur, sinon de la hauteur basse à la haute. "
                         "Enceinte / écoute : au point sélectionné, orientée vers son point « Orienté vers ». "
                         "« Déplacer la sélection » amène l'enceinte ou l'écouteur sélectionné dans la scène sur ce "
                         "point.")
        self.refresh_server()

    # ------------------------------------------------------------------ outils
    def _section(self, form, text):
        lab = QtWidgets.QLabel(text.upper()); lab.setObjectName("section")
        form.addRow(lab)

    def _info(self, form, text):
        lab = QtWidgets.QLabel(text); lab.setObjectName("info"); lab.setWordWrap(True)
        form.addRow(lab)
        return lab

    def tel(self):
        return self.scene().telemetry

    def selected_ids(self):
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()}) if self.table.selectionModel() else []
        pts = self.tel()["points"]
        return [pts[r]["id"] for r in rows if r < len(pts)]

    def current_id(self):
        ids = self.selected_ids()
        return ids[0] if ids else None

    # ------------------------------------------------------------------ serveur
    def toggle_server(self):
        if self.server.running:
            self.server.stop()
        else:
            self.server.port = int(self.port.value())
            try:
                self.server.start()
            except OSError as e:
                QtWidgets.QMessageBox.warning(self, "Serveur", f"Impossible de démarrer le serveur :\n{e}")
        self.refresh_server()

    def refresh_server(self):
        on = self.server.running
        self.srv_btn.setText("Arrêter le serveur" if on else "Démarrer le serveur")
        self.port.setEnabled(not on)
        self.srv_lab.setText("\n".join(self.server.urls()) if on else "Arrêté.")
        self.srv_lab.setStyleSheet(f"color:{S.ACCENT}" if on else "")
        p = TS.apk_path()
        self.apk_lab.setText(f"Application Android servie : {p}" if p else
                             "Pas encore d'APK : compilez-le (voir README, dossier android/) puis « Choisir l'APK "
                             "Android… ». La version navigateur fonctionne sans.")

    def open_page(self):
        if not self.server.running:
            self.toggle_server()
        if self.server.running:
            webbrowser.open(f"http://127.0.0.1:{self.server.port}/")

    def pick_apk(self):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Application Android (APK)", "", "APK (*.apk)")
        if not p:
            return
        os.makedirs(TS.USER_DIR, exist_ok=True)
        shutil.copyfile(p, os.path.join(TS.USER_DIR, TS.APK_NAME))
        self.refresh_server()

    # ------------------------------------------------------------------ chargement
    def load(self):
        self._loading = True
        try:
            r = self.tel()["ref"]
            self.mode.setCurrentIndex(1 if r.get("mode") == "scene" else 0)
            for w, k in ((self.rAB, "AB"), (self.rAC, "AC"), (self.rBC, "BC"), (self.rH0, "h0"), (self.rAx, "ax"),
                         (self.rAy, "ay"), (self.rAz, "az"), (self.rRot, "rot")):
                w.blockSignals(True); w.setValue(TM.num(r.get(k)) or 0.0); w.blockSignals(False)
            self.rFlip.blockSignals(True); self.rFlip.setChecked(bool(r.get("flip"))); self.rFlip.blockSignals(False)
            for k in "ABC":
                for i, w in enumerate(self.xyz[k]):
                    w.blockSignals(True); w.setValue(float((r.get(k) or [0, 0, 0])[i])); w.blockSignals(False)
            self._refresh_picks()
            sc = self.scene()
            cur = self.spkModel.currentData()
            self.spkModel.clear()
            for m in sc.models:
                self.spkModel.addItem(m.name, m.id)
            i = self.spkModel.findData(cur)
            self.spkModel.setCurrentIndex(max(i, 0))
        finally:
            self._loading = False
        self.refresh()

    def _refresh_picks(self):
        self._scene_pts = TM.scene_points(self.scene())
        for k in "ABC":
            cb = self.pick[k]
            cb.blockSignals(True)
            cb.clear()
            cb.addItem("— choisir un point —")
            for lab, P in self._scene_pts:
                cb.addItem(f"{lab} ({P[0]:.2f}, {P[1]:.2f}, {P[2]:.2f})")
            cb.blockSignals(False)

    def _take_point(self, k, i):
        if i <= 0 or i - 1 >= len(self._scene_pts):
            return
        P = self._scene_pts[i - 1][1]
        for j, w in enumerate(self.xyz[k]):
            w.blockSignals(True); w.setValue(round(float(P[j]), 4)); w.blockSignals(False)
        self.pick[k].setCurrentIndex(0)
        self._ref_edited()

    def _ref_edited(self, *_):
        if self._loading:
            return
        d = dict(mode=self.mode.currentData(), AB=self.rAB.value() or None, AC=self.rAC.value() or None,
                 BC=self.rBC.value() or None, h0=self.rH0.value(), flip=self.rFlip.isChecked(),
                 ax=self.rAx.value(), ay=self.rAy.value(), az=self.rAz.value(), rot=self.rRot.value())
        for k in "ABC":
            d[k] = [w.value() for w in self.xyz[k]]
        TM.update_ref(self.tel(), d)
        self.refresh()
        self.app.schedule(False)

    # ------------------------------------------------------------------ affichage
    def refresh(self):
        tel = self.tel()
        scene_mode = tel["ref"].get("mode") == "scene"
        self.libre.setVisible(not scene_mode)
        self.scn.setVisible(scene_mode)
        fr, pts = TM.solve(tel)
        sides = getattr(fr, "sides", (None, None, None))
        txt = "A–B {} · A–C {} · B–C {}".format(*[f"{s:.3f} m" if s else "—" for s in sides])
        if fr.warn:
            txt += f"\n⚠ {fr.warn}"
        self.ref_lab.setText(txt)
        keep = set(self.selected_ids())
        self.table.blockSignals(True)
        self.table.setRowCount(len(tel["points"]))
        by = {p["id"]: p for p in pts}
        for r, q in enumerate(tel["points"]):
            s = by.get(q["id"], {})
            P = s.get("P")
            vals = [q.get("name", ""), TM.TYPES.get(q.get("type"), "").split(" (")[0], q.get("group", ""),
                    *(f"{TM.num(q.get(k)):.3f}" if TM.num(q.get(k)) else "—" for k in ("dA", "dB", "dC")),
                    *(f"{P[i]:.3f}" if P is not None else "—" for i in range(3)),
                    (("⚠ " + s["warn"]) if s.get("warn") else TM.precision_text(s["sig"])) if s.get("ok") else s.get("warn", "")]
            for c, v in enumerate(vals):
                col = TM.TYPE_COLORS.get(q.get("type")) if c == 1 else (S.ACCENT if c in (6, 7, 8) else None)
                if c == 9 and s.get("warn"):
                    col = "#e2584f"
                self.table.setItem(r, c, cell(v, col, c >= 3 and c < 9))
        self.table.clearSelection()
        for r, q in enumerate(tel["points"]):
            if q["id"] in keep:
                self.table.selectRow(r)
        self.table.blockSignals(False)
        groups = sorted({q.get("group", "") for q in tel["points"] if q.get("group")})
        cur = self.objGroup.currentData()
        self.objGroup.clear()
        self.objGroup.addItem("(points sélectionnés)", "")
        for g in groups:
            self.objGroup.addItem(g, g)
        i = self.objGroup.findData(cur)
        self.objGroup.setCurrentIndex(i if i >= 0 else (1 if groups else 0))
        gtxt = self.pGroup.currentText()
        self.pGroup.clear(); self.pGroup.addItems([""] + groups); self.pGroup.setEditText(gtxt)
        self._fill_aim()
        self._preview()
        self._relations()

    def _relations(self):
        from .model import speed_of_sound
        ids = self.selected_ids()
        sc = self.scene()
        _, pts = TM.solve(self.tel())
        p = next((x for x in pts if ids and x["id"] == ids[0]), None)
        rows = TM.relations(pts, p["id"], speed_of_sound(sc.settings.temperature)) if p else []
        if p is None:
            self.rel_lab.setText("Sélectionnez un point : distances et angles vers les enceintes et les écoutes.")
        else:
            aim = next((x for x in pts if x["id"] == p.get("aim")), None)
            self.rel_lab.setText(f"Depuis « {p['name']} »" + (f", orienté vers « {aim['name']} »" if aim else
                                 " (sans orientation : pas d'angle hors axe)") +
                                 " · incidence : angle entre l'axe de l'autre élément et la ligne vers ce point.")
        self.rel.setRowCount(len(rows))
        sg = lambda v: f"{v:+.1f}°"
        ang = lambda o: "—" if o is None else f"{o[0]:.1f}°  (H {sg(o[1])} · V {sg(o[2])})"
        for i, r in enumerate(rows):
            vals = [r["name"], f"{r['L']:.2f} m", f"{r['t']:.2f} ms", sg(r["site"]), f"{r['az']:.1f}°",
                    ang(r["off"]), ang(r["inc"])]
            for c_, v in enumerate(vals):
                col = TM.TYPE_COLORS.get(r["type"]) if c_ == 0 else (S.ACCENT if c_ in (1, 5, 6) else None)
                self.rel.setItem(i, c_, cell(v, col, c_ > 0))

    def _fill_aim(self):
        cur = self.pAim.currentData()
        self.pAim.clear()
        self.pAim.addItem("Aucune", "")
        for q in self.tel()["points"]:
            if q["id"] != self._edit:
                self.pAim.addItem(q.get("name", ""), q["id"])
        i = self.pAim.findData(cur)
        self.pAim.setCurrentIndex(max(i, 0))

    def _row_changed(self):
        ids = self.selected_ids()
        q = next((p for p in self.tel()["points"] if p["id"] == ids[0]), None) if len(ids) == 1 else None
        self._fill(q)
        self._relations()
        self.app.recompute()           # repère le point sélectionné dans les vues

    def _fill(self, q):
        self._edit = q["id"] if q else None
        self.pName.setText(q.get("name", "") if q else "")
        if q:
            self.pType.setCurrentIndex(max(self.pType.findData(q.get("type")), 0))
            self.pGroup.setEditText(q.get("group", ""))
        for w, k in ((self.pA, "dA"), (self.pB, "dB"), (self.pC, "dC")):
            w.blockSignals(True); w.setValue((TM.num(q.get(k)) or 0.0) if q else 0.0); w.blockSignals(False)
        hk = TM.num(q.get("hk")) if q else None
        self.pHkOn.blockSignals(True); self.pHkOn.setChecked(hk is not None); self.pHkOn.blockSignals(False)
        self.pHk.blockSignals(True); self.pHk.setValue(hk or 0.0); self.pHk.blockSignals(False)
        self.pBelow.blockSignals(True); self.pBelow.setChecked(bool(q.get("below")) if q else False); self.pBelow.blockSignals(False)
        self._fill_aim()
        self.pAim.setCurrentIndex(max(self.pAim.findData((q.get("aim") or "") if q else ""), 0))
        self.bSave.setText("Enregistrer" if q else "Ajouter")
        self.bDel.setEnabled(q is not None)
        self._preview()

    def _data(self):
        return dict(id=self._edit, name=self.pName.text(), type=self.pType.currentData(), group=self.pGroup.currentText(),
                    dA=self.pA.value() or None, dB=self.pB.value() or None, dC=self.pC.value() or None,
                    aim=self.pAim.currentData() or None, below=self.pBelow.isChecked(),
                    hk=self.pHk.value() if self.pHkOn.isChecked() else None)

    def _preview(self, *_):
        d = self._data()
        if not (d["dA"] and d["dB"] and d["dC"]):
            self.pv_lab.setText("Saisissez les distances depuis A, B et C.")
            return
        p = TeleAPI(self.app).preview(d)
        if not p["ok"]:
            self.pv_lab.setText(p["warn"])
            return
        P = p["P"]
        self.pv_lab.setText(f"X {P[0]:.3f} · Y {P[1]:.3f} · Z {P[2]:.3f} m · {p['prec']}" +
                            (f"\n⚠ {p['warn']}" if p["warn"] else ""))

    def _save(self):
        d = self._data()
        if not (d["dA"] and d["dB"] and d["dC"]):
            QtWidgets.QMessageBox.information(self, "Télémètre", "Saisissez les trois distances depuis A, B et C.")
            return
        TM.upsert_point(self.tel(), d)
        self._edit = None
        self.changed.emit()
        self._new(keep_type=True)

    def _new(self, keep_type=False):
        t, g = self.pType.currentIndex(), self.pGroup.currentText()
        self.table.clearSelection()
        self._fill(None)
        if keep_type:
            self.pType.setCurrentIndex(t); self.pGroup.setEditText(g)
        self.pName.setFocus()

    def _delete(self):
        for pid in self.selected_ids() or ([self._edit] if self._edit else []):
            TM.delete_point(self.tel(), pid)
        self._fill(None)
        self.changed.emit()
