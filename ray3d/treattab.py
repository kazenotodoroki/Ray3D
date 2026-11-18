"""Onglet TRAITEMENT : zones minimales de premières réflexions et pose de panneaux (hors bass traps)."""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from . import style as S
from . import treatment as T
from .panels import Binder, scroll_form, make_table, cell
from .widgets import NoWheelCombo, NumField


class TreatTab(QtWidgets.QWidget):
    changed = QtCore.Signal(bool)
    place = QtCore.Signal()
    remove = QtCore.Signal()
    export_pdf = QtCore.Signal()
    export_desk = QtCore.Signal()
    add_bass_trap = QtCore.Signal(dict)

    def __init__(self, scene_getter):
        super().__init__()
        self.scene = scene_getter
        self.zones = []
        self.placed = {}
        self._cur = None
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        sa, form = scroll_form(); lay.addWidget(sa)
        b = self.b = Binder(form, lambda: self.scene().settings)
        b.changed.connect(lambda a: self.changed.emit(False))

        b.section("Zone d'écoute")
        self.ctx_lab = b.info("")
        b.add("treat_scope", "Sources", "choice", choices=["Sélection", "Toutes les sources"],
              tip="Sélection : l'enceinte ou le groupe sélectionné (toutes si rien n'est sélectionné).")
        b.add("treat_head_w", "Largeur (gauche ↔ droite)", lo=0, hi=5, step=0.05, dec=2, suffix=" m",
              tip="Déplacements de la tête pris en compte autour du point d'écoute.")
        b.add("treat_head_d", "Profondeur (avant ↔ arrière)", lo=0, hi=5, step=0.05, dec=2, suffix=" m")
        b.add("treat_head_h", "Hauteur", lo=0, hi=2, step=0.05, dec=2, suffix=" m")
        b.add("treat_margin", "Marge autour des points", lo=0, hi=1, step=0.05, dec=2, suffix=" m")
        b.add("treat_min_level", "Ignorer sous", lo=-80, hi=0, step=1, dec=0, suffix=" dB",
              tip="Niveau de la réflexion par rapport au son direct (directivité comprise).")
        b.add("treat_show", "Toujours afficher les zones dans les vues", "bool",
              tip="Sinon, les zones ne s'affichent que lorsque cet onglet est ouvert.")
        b.add("treat_hide_zones", "Masquer les zones minimales (jaunes)", "bool",
              tip="Par exemple une fois les panneaux posés.")

        b.section("Zones minimales (premières réflexions)")
        self.table = make_table(["Paroi", "Dimensions", "Position", "Niveau", "Panneaux"], stretch=2)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setMinimumHeight(170)
        self.table.itemSelectionChanged.connect(self._row_changed)
        form.addRow(self.table)
        self.summary = QtWidgets.QLabel(); self.summary.setObjectName("value"); self.summary.setWordWrap(True)
        form.addRow(self.summary)

        b.section("Panneaux de la zone sélectionnée")
        self.z_lab = QtWidgets.QLabel("—")
        f = self.z_lab.font(); f.setBold(True); self.z_lab.setFont(f); self.z_lab.setWordWrap(True)
        form.addRow(self.z_lab)
        self.on = QtWidgets.QCheckBox("Traiter cette zone")
        self.on.toggled.connect(lambda v: self._set("on", bool(v)))
        form.addRow(self.on)
        self.size = NoWheelCombo(); self.size.addItems(list(T.PANEL_SIZES.keys()))
        self.size.currentTextChanged.connect(lambda v: self._set("size", v))
        form.addRow("Taille de panneau", self.size)
        self.pw = NumField(1.2, 0.05, 10, 0.05, 2, " m"); self.pw.valueChanged.connect(lambda v: self._set("w", float(v)))
        self.ph = NumField(0.6, 0.05, 10, 0.05, 2, " m"); self.ph.valueChanged.connect(lambda v: self._set("h", float(v)))
        hb = QtWidgets.QHBoxLayout(); hb.addWidget(self.pw); hb.addWidget(QtWidgets.QLabel("×")); hb.addWidget(self.ph)
        form.addRow("Sur mesure", hb)
        self.orient = NoWheelCombo(); self.orient.addItems(T.ORIENTS)
        self.orient.currentTextChanged.connect(lambda v: self._set("orient", v))
        form.addRow("Orientation", self.orient)
        self.thick = NumField(0.1, 0.005, 1, 0.01, 3, " m"); self.thick.valueChanged.connect(lambda v: self._set("t", float(v)))
        form.addRow("Épaisseur", self.thick)
        self.drop = NumField(0.0, 0, 2, 0.05, 3, " m"); self.drop.valueChanged.connect(lambda v: self._set("drop", float(v)))
        self.drop.setToolTip("Distance entre le plafond et le dessus du panneau (nuage suspendu).")
        form.addRow("Suspension sous plafond", self.drop)
        self.nu = NumField(0, 0, 50, 1, 0, "", integer=True); self.nu.valueChanged.connect(lambda v: self._set("nu", int(v)))
        self.nv = NumField(0, 0, 50, 1, 0, "", integer=True); self.nv.valueChanged.connect(lambda v: self._set("nv", int(v)))
        hb = QtWidgets.QHBoxLayout(); hb.addWidget(self.nu); hb.addWidget(QtWidgets.QLabel("×")); hb.addWidget(self.nv)
        form.addRow("Nombre (larg. × haut., 0 = auto)", hb)
        self.manual = QtWidgets.QCheckBox("Position manuelle du bloc (centre)")
        self.manual.toggled.connect(self._manual_toggled)
        form.addRow(self.manual)
        self.cu = NumField(0, 0, 100, 0.05, 3, " m"); self.cu.valueChanged.connect(lambda v: self._set("cu", float(v)))
        self.cv = NumField(0, 0, 100, 0.05, 3, " m"); self.cv.valueChanged.connect(lambda v: self._set("cv", float(v)))
        hb = QtWidgets.QHBoxLayout(); hb.addWidget(self.cu); hb.addWidget(self.cv)
        self.cu_lab = QtWidgets.QLabel("Centre (gauche, sol)")
        form.addRow(self.cu_lab, hb)
        self.lay_lab = QtWidgets.QLabel(); self.lay_lab.setObjectName("value"); self.lay_lab.setWordWrap(True)
        form.addRow(self.lay_lab)
        self._editors = (self.on, self.size, self.pw, self.ph, self.orient, self.thick, self.drop,
                         self.nu, self.nv, self.manual, self.cu, self.cv)

        b.section("Pose")
        b.add("treat_size", "Taille par défaut", "choice", choices=[k for k in T.PANEL_SIZES if k != "Sur mesure"])
        b.add("treat_thick", "Épaisseur par défaut", lo=0.005, hi=1, step=0.01, dec=3, suffix=" m")
        b.add("treat_gap", "Espace entre panneaux", lo=0, hi=1, step=0.01, dec=2, suffix=" m")
        b.add("treat_ceiling_drop", "Suspension par défaut (plafond)", lo=0, hi=2, step=0.05, dec=3, suffix=" m",
              tip="Distance entre le plafond et le dessus des panneaux de plafond.")
        b.add("treat_alpha", "Absorption des panneaux", lo=0, hi=1, step=0.05, dec=2)
        hb = QtWidgets.QHBoxLayout()
        bt = QtWidgets.QPushButton("Poser les panneaux"); bt.setObjectName("primary"); bt.clicked.connect(self.place)
        bt2 = QtWidgets.QPushButton("Retirer les panneaux"); bt2.clicked.connect(self.remove)
        hb.addWidget(bt); hb.addWidget(bt2)
        form.addRow(hb)
        self.placed_lab = QtWidgets.QLabel(); self.placed_lab.setObjectName("info"); self.placed_lab.setWordWrap(True)
        form.addRow(self.placed_lab)

        b.section("Bass traps")
        self.bt_corner = NoWheelCombo()
        form.addRow("Angle", self.bt_corner)
        self.bt_kind = NoWheelCombo(); self.bt_kind.addItems(T.BT_KINDS)
        form.addRow("Forme", self.bt_kind)
        b.add("bt_size", "Côté le long des murs", lo=0.05, hi=3, step=0.05, dec=2, suffix=" m")
        self.bt_h = NumField(0.0, 0, 10, 0.1, 2, " m")
        self.bt_h.setToolTip("0 = toute la hauteur de la pièce")
        form.addRow("Hauteur (0 = sol → plafond)", self.bt_h)
        b.add("bt_alpha", "Absorption", lo=0, hi=1, step=0.05, dec=2)
        bb = QtWidgets.QPushButton("Ajouter le bass trap")
        bb.clicked.connect(lambda: self.add_bass_trap.emit(dict(
            corner=self.bt_corner.currentIndex(), kind=self.bt_kind.currentText(), height=self.bt_h.value())))
        form.addRow(bb)
        self.bt_lab = QtWidgets.QLabel(); self.bt_lab.setObjectName("info"); self.bt_lab.setWordWrap(True)
        form.addRow(self.bt_lab)
        b.info("Les bass traps sont des formes comme les autres : modifiez leur esquisse (Éditer le profil) "
               "pour les dessiner à la main. Toute forme peut devenir un bass trap : cochez « Bass trap » "
               "dans ses propriétés. Ils sont conservés quand on repose ou retire les panneaux, et figurent "
               "dans le PDF d'analyse.")

        b.section("Exports PDF")
        b.add("pdf_units", "Unités des plans", "choice", choices=["mm", "cm", "m"])
        hb = QtWidgets.QHBoxLayout()
        e1 = QtWidgets.QPushButton("Analyse acoustique…"); e1.setObjectName("primary"); e1.clicked.connect(self.export_pdf)
        e2 = QtWidgets.QPushButton("Plans de découpe d'un ensemble…"); e2.clicked.connect(self.export_desk)
        hb.addWidget(e1); hb.addWidget(e2)
        form.addRow(hb)
        b.info("Les zones sont les surfaces minimales qui couvrent les points de réflexion du premier ordre "
               "entre les enceintes et la zone d'écoute (hors bass traps : les angles et le grave ne sont "
               "pas traités ici). Les panneaux sont posés en grille, centrés sur chaque zone, dans "
               "l'orientation qui en demande le moins ; ils sont rangés dans l'ensemble « Traitement "
               "acoustique » et absorbent dans les calculs (SBIR, réflexions). Le sol n'est pas traité par "
               "défaut (cochez « Traiter cette zone »). L'écouteur est celui de l'onglet SBIR.")

    # ------------------------------------------------------------------
    def load(self):
        self.b.load()

    def set_context(self, text):
        self.ctx_lab.setText(text)

    def set_corners(self, corners, traps):
        cur = self.bt_corner.currentText()
        self.bt_corner.blockSignals(True)
        self.bt_corner.clear()
        for c in corners:
            self.bt_corner.addItem(f"{c['label']} · ({c['C'][0]:.2f}, {c['C'][1]:.2f})")
        i = self.bt_corner.findText(cur)
        self.bt_corner.setCurrentIndex(max(i, 0))
        self.bt_corner.blockSignals(False)
        self.bt_lab.setText(f"{len(traps)} bass trap(s) : " + ", ".join(s.name for s in traps[:8])
                            if traps else "Aucun bass trap.")

    def show_result(self, zones, placed):
        st = self.scene().settings
        keep = self._cur
        self.zones, self.placed = zones, placed
        self.table.blockSignals(True)
        self.table.setRowCount(len(zones))
        bold = QtGui.QFont(); bold.setBold(True)
        total = 0
        for i, z in enumerate(zones):
            cfg = T.zone_cfg(z, st)
            lay = T.layout(z, cfg, st.treat_gap)
            n = len(lay["rects"]) if cfg["on"] else 0
            total += n
            u0, v0, u1, v1 = z.rect
            pos = (f"u {u0:.2f} · v {v0:.2f}→{v1:.2f}" if z.kind == "wall"
                   else f"X {z.O[0] + u0:.2f} · Y {z.O[1] + v0:.2f}")
            self.table.setItem(i, 0, cell(f"{z.abbr}  {z.label}", None if not z.empty else S.DIM, False))
            if z.empty:
                self.table.setItem(i, 1, cell("vide", S.DIM))
                self.table.setItem(i, 2, cell("réflexions sous le seuil" if z.level > -98 else "aucune réflexion",
                                              S.DIM, False))
                self.table.setItem(i, 3, cell(f"{z.level:+.1f} dB" if z.level > -98 else "—", S.DIM))
            else:
                it = cell(f"{z.w:.2f} × {z.h:.2f} m"); it.setFont(bold); self.table.setItem(i, 1, it)
                it = cell(pos, None, False); it.setFont(bold); self.table.setItem(i, 2, it)
                self.table.setItem(i, 3, cell(f"{z.level:+.1f} dB", S.DIM))
            self.table.setItem(i, 4, cell(f"{n}" if cfg["on"] else "—", S.ACCENT))
        self.table.blockSignals(False)
        if not zones:
            self.summary.setText("Aucune zone : ajoutez une pièce, un écouteur et des enceintes.")
        else:
            full = [z for z in zones if not z.empty]
            area = sum(z.w * z.h for z in full)
            self.summary.setText(f"{len(full)} zone(s) · {area:.2f} m² à traiter au minimum · "
                                 f"{total} panneau(x) prévus")
        npl = sum(len(v) for v in placed.values())
        self.placed_lab.setText(f"{npl} panneau(x) posé(s) dans la scène." if npl else "Aucun panneau posé.")
        row = next((i for i, z in enumerate(zones) if z.key == keep), 0 if zones else -1)
        if row >= 0:
            self.table.selectRow(row)
        self._row_changed()

    def _zone(self):
        r = self.table.currentRow()
        sel = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if sel:
            r = sel[0].row()
        return self.zones[r] if 0 <= r < len(self.zones) else None

    def _row_changed(self):
        z = self._zone()
        for w in self._editors:
            w.setEnabled(z is not None)
        if z is None:
            self._cur = None
            self.z_lab.setText("—"); self.lay_lab.setText("")
            return
        self._cur = z.key
        st = self.scene().settings
        cfg = T.zone_cfg(z, st)
        for w in self._editors:
            w.blockSignals(True)
        self.on.setChecked(cfg["on"])
        self.size.setCurrentText(cfg["size"])
        self.pw.setValue(cfg["w"]); self.ph.setValue(cfg["h"])
        self.orient.setCurrentText(cfg["orient"])
        self.thick.setValue(cfg["t"])
        self.drop.setValue(cfg.get("drop", 0.0))
        self.nu.setValue(int(cfg.get("nu", 0) or 0)); self.nv.setValue(int(cfg.get("nv", 0) or 0))
        man = bool(cfg.get("manual"))
        self.manual.setChecked(man)
        c0 = ((z.rect[0] + z.rect[2]) / 2, (z.rect[1] + z.rect[3]) / 2)
        self.cu.setRange(0, z.W); self.cv.setRange(0, z.H)
        self.cu.setValue(float(cfg.get("cu", c0[0])) if man else c0[0])
        self.cv.setValue(float(cfg.get("cv", c0[1])) if man else c0[1])
        self.cu_lab.setText("Centre (gauche, sol)" if z.kind == "wall" else "Centre (X, Y depuis le coin)")
        for w in self._editors:
            w.blockSignals(False)
        custom = cfg["size"] == "Sur mesure"
        self.pw.setEnabled(custom); self.ph.setEnabled(custom)
        self.orient.setEnabled(T.PANEL_SIZES.get(cfg["size"]) != "zone")
        self.drop.setEnabled(z.kind == "ceiling")
        self.cu.setEnabled(man); self.cv.setEnabled(man)
        self.z_lab.setText(f"{z.abbr} · {z.label} : {z.describe()}")
        lay = T.layout(z, cfg, st.treat_gap)
        bu, bv, bw, bh = lay["block"]
        where = (f"à {bu:.2f} m du coin gauche, de {bv:.2f} à {bv + bh:.2f} m du sol" if z.kind == "wall"
                 else f"X {z.O[0] + bu:.2f} → {z.O[0] + bu + bw:.2f}, Y {z.O[1] + bv:.2f} → {z.O[1] + bv + bh:.2f}")
        hang = f" · suspendu(s) à {cfg.get('drop', 0.0):.2f} m sous le plafond" if z.kind == "ceiling" else ""
        self.lay_lab.setText(f"{lay['nu']} × {lay['nv']} panneau(x) de {lay['pw'] * 100:.0f} × {lay['ph'] * 100:.0f} cm"
                             f" · bloc {bw:.2f} × {bh:.2f} m {where}{hang}" if cfg["on"] else "Zone non traitée.")

    def _manual_toggled(self, on):
        z = self._zone()
        if z is None:
            return
        if on:                                    # part du centre actuel
            self._set("cu", float(self.cu.value()), emit=False)
            self._set("cv", float(self.cv.value()), emit=False)
        self._set("manual", bool(on))

    def _set(self, key, val, emit=True):
        z = self._zone()
        if z is None:
            return
        st = self.scene().settings
        d = dict(st.treat_panels or {})
        cfg = dict(d.get(z.key, {}))
        cfg[key] = val
        d[z.key] = cfg
        st.treat_panels = d
        if emit:
            self.changed.emit(False)
