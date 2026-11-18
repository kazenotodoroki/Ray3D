"""Onglet SBIR : réponse au point d'écoute, réflexions par paroi, optimisation des positions."""
from __future__ import annotations

import math

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from . import style as S
from . import sbir as SB
from .panels import Binder, scroll_form, make_table, cell
from .widgets import NoWheelCombo

SCANS = ["Distance enceinte ↔ mur", "Écoute le long de X", "Écoute le long de Y"]


def _plot(height, xlabel, ylabel, logx):
    w = pg.PlotWidget()
    w.setBackground(S.BG)
    w.setMinimumHeight(height)
    pi = w.getPlotItem()
    pi.hideButtons(); pi.setMenuEnabled(False)
    pi.showGrid(x=True, y=True, alpha=0.12)
    for name, lab in (("bottom", xlabel), ("left", ylabel)):
        a = pi.getAxis(name)
        a.setPen(pg.mkPen(S.BORDER)); a.setTextPen(pg.mkPen(S.DIM)); a.enableAutoSIPrefix(False)
        a.setLabel(lab, color=S.DIM)
    if logx:
        pi.setLogMode(x=True, y=False)
        major, minor = [], []
        for dec in (1, 10, 100, 1000, 10000):
            for m in range(1, 10):
                f = dec * m
                if f < 10 or f > 20000:
                    continue
                lab = f"{f // 1000}k" if f >= 1000 else str(f)
                (major if m in (1, 2, 5) else minor).append((math.log10(f), lab if m in (1, 2, 5) else ""))
        pi.getAxis("bottom").setTicks([major, minor])
    return w


class SbirTab(QtWidgets.QWidget):
    changed = QtCore.Signal(bool)
    applied = QtCore.Signal(object)
    export_pdf = QtCore.Signal()

    def __init__(self, scene_getter, ctx_getter):
        super().__init__()
        self.scene = scene_getter
        self.ctx = ctx_getter          # -> dict(scene, geo, sources, obj, listener, c, opts)
        self.result = None
        self.scan = None
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        sa, form = scroll_form(); lay.addWidget(sa)
        b = self.b = Binder(form, lambda: self.scene().settings)
        b.changed.connect(lambda a: self.changed.emit(False))

        b.section("Point d'écoute et sources")
        self.lst = NoWheelCombo()
        self.lst.currentIndexChanged.connect(self._lst_changed)
        form.addRow("Écouteur", self.lst)
        b.add("sbir_scope", "Sources", "choice", choices=["Sélection", "Toutes les sources"],
              tip="Sélection : l'enceinte ou le groupe sélectionné (toutes les sources si rien n'est sélectionné)")

        b.section("Parois prises en compte")
        b.add("sbir_front", "Mur derrière l'enceinte", "bool")
        b.add("sbir_side", "Murs latéraux", "bool")
        b.add("sbir_floor", "Sol", "bool")
        b.add("sbir_ceiling", "Plafond", "bool")
        b.section("Réflexions arrières")
        b.add("sbir_rear_rad", "Rayonnement arrière des enceintes (grave omni)", "bool",
              tip="Dans le grave, l'enceinte rayonne aussi vers l'arrière : le mur derrière elle renvoie "
                  "ce son vers l'écoute. Transition vers la directivité du modèle autour de c / (π · largeur).")
        b.add("sbir_rear_wall", "Mur derrière la position d'écoute", "bool")
        b.add("sbir_order", "Ordre des réflexions", "int", lo=1, hi=4,
              tip="1 à 4 rebonds. Les ordres 3 et 4 prennent un peu plus de temps de calcul.")
        b.add("sbir_show_paths", "Afficher les chemins dans les vues", "bool")

        b.section("Réponse au point d'écoute")
        b.add("sbir_fmin", "Fréquence min", lo=10, hi=5000, step=5, dec=0, suffix=" Hz")
        b.add("sbir_fmax", "Fréquence max", lo=50, hi=20000, step=100, dec=0, suffix=" Hz")
        b.add("sbir_smooth", "Lissage", "choice", choices=list(SB.SMOOTH.keys()))
        self.plot = _plot(270, "fréquence (Hz)", "niveau (dB)", True)
        form.addRow(self.plot)
        leg = QtWidgets.QLabel(" ".join([
            f'<span style="color:{S.ACCENT}">■</span> total',
            f'<span style="color:{S.DIM}">■</span> direct seul'] +
            [f'<span style="color:{SB.CAT_COLORS[k]}">|</span> {SB.CATS[k].lower()}' for k in
             ("front", "side", "floor", "ceiling", "rear")]))
        leg.setObjectName("info"); leg.setWordWrap(True)
        form.addRow(leg)
        self.summary = QtWidgets.QLabel(); self.summary.setObjectName("value"); self.summary.setWordWrap(True)
        form.addRow(self.summary)
        self.table = make_table(["Source", "Paroi", "Δ trajet", "Δt", "1er creux", "rel."], stretch=1)
        self.table.setMinimumHeight(200)
        form.addRow(self.table)
        bx = QtWidgets.QPushButton("Exporter l'analyse en PDF (vue 3D, SBIR, plans)…")
        bx.clicked.connect(self.export_pdf)
        form.addRow(bx)

        b.section("Optimisation (écart-type de la réponse dans la bande)")
        b.add("sbir_band_lo", "Bande de", lo=10, hi=5000, step=5, dec=0, suffix=" Hz")
        b.add("sbir_band_hi", "à", lo=20, hi=20000, step=10, dec=0, suffix=" Hz")
        b.add("sbir_scan", "Balayer", "choice", choices=SCANS)
        b.add("sbir_scan_min", "De", lo=-100, hi=100, step=0.05, dec=2, suffix=" m",
              tip="Distance au mur : mesurée depuis la face avant (centre acoustique) de l'enceinte. "
                  "Écoute : coordonnée X ou Y.")
        b.add("sbir_scan_max", "À", lo=-100, hi=100, step=0.05, dec=2, suffix=" m")
        hb = QtWidgets.QHBoxLayout()
        bt = QtWidgets.QPushButton("Balayer"); bt.setObjectName("primary"); bt.clicked.connect(self.run_scan)
        self.apply_btn = QtWidgets.QPushButton("Appliquer la meilleure position")
        self.apply_btn.clicked.connect(self.apply_scan); self.apply_btn.setEnabled(False)
        hb.addWidget(bt); hb.addWidget(self.apply_btn)
        form.addRow(hb)
        self.scan_plot = _plot(200, "position (m)", "écart-type (dB)", False)
        form.addRow(self.scan_plot)
        self.scan_lab = QtWidgets.QLabel(); self.scan_lab.setObjectName("value"); self.scan_lab.setWordWrap(True)
        form.addRow(self.scan_lab)
        b.info("Le SBIR vient des réflexions sur les parois proches : chaque réflexion retardée de Δt "
               "crée des creux à c / (2·Δ trajet) et ses multiples impairs. Repères : enceinte collée au "
               "mur (ou encastrée) pour repousser le creux au-dessus de la bande, ou assez loin pour le "
               "faire descendre sous le caisson. La réponse est calculée pour la sélection seule ; les "
               "délais de l'onglet DÉLAIS sont appliqués si l'option y est cochée.")

    # ------------------------------------------------------------------
    def load(self):
        self.b.load()

    def refresh_lists(self):
        sc = self.scene()
        self.lst.blockSignals(True)
        self.lst.clear()
        for l in sc.listeners:
            self.lst.addItem(l.name, l.id)
        i = self.lst.findData(sc.settings.sbir_listener)
        if i < 0 and sc.listeners:
            i = 0
            sc.settings.sbir_listener = sc.listeners[0].id
        self.lst.setCurrentIndex(max(i, 0))
        self.lst.blockSignals(False)

    def _lst_changed(self, i):
        self.scene().settings.sbir_listener = self.lst.itemData(i) or ""
        self.scan = None
        self.changed.emit(False)

    # ------------------------------------------------------------------ affichage du résultat
    def show_result(self, res):
        self.result = res
        pi = self.plot.getPlotItem()
        pi.clear()
        self.table.setRowCount(0)
        if res is None:
            self.summary.setText("Ajoutez un écouteur et une enceinte (exemple : « Exemple studio »).")
            return
        st = self.scene().settings
        f, H, Hd = res["freqs"], res["H"], res["Hd"]
        frac = SB.SMOOTH.get(st.sbir_smooth, 0)
        tot = SB.smooth_db(f, np.abs(H) ** 2, frac)
        dir_ = SB.smooth_db(f, np.abs(Hd) ** 2, frac)
        ref = float(np.median(dir_))
        pi.addItem(pg.PlotDataItem(f, dir_ - ref, pen=pg.mkPen(S.DIM, width=1, style=Qt.PenStyle.DashLine)))
        pi.addItem(pg.PlotDataItem(f, tot - ref, pen=pg.mkPen(S.ACCENT, width=2)))
        rows = res["rows"]
        seen = set()
        for r in rows:                         # premier creux de chaque paroi (réflexion la plus proche)
            key = (r["cat"], r["src"].owner)
            if r["order"] != 1 or key in seen or not (f[0] <= r["notch"] <= f[-1]) or r["rel"] < -20:
                continue
            seen.add(key)
            col = QtGui.QColor(SB.CAT_COLORS.get(r["cat"], "#ffffff")); col.setAlpha(170)
            pi.addItem(pg.InfiniteLine(pos=math.log10(r["notch"]), angle=90,
                                       pen=pg.mkPen(col, width=1, style=Qt.PenStyle.DotLine)))
        lo, hi = st.sbir_band_lo, st.sbir_band_hi
        band = pg.LinearRegionItem(values=(math.log10(max(lo, 1)), math.log10(max(hi, 2))), movable=False,
                                   brush=pg.mkBrush(QtGui.QColor(255, 255, 255, 10)), pen=pg.mkPen(None))
        pi.addItem(band)
        pi.setYRange(-24, 12)
        dev = SB.flatness(f, H, lo, hi)
        devd = SB.flatness(f, Hd, lo, hi)
        m = (f >= lo) & (f <= hi)
        worst = ""
        if m.any():
            k = int(np.argmin((tot - dir_)[m]))
            worst = f" · creux max {float((tot - dir_)[m][k]):+.1f} dB à {f[m][k]:.0f} Hz"
        self.summary.setText(f"{res['nsrc']} source(s) · {len(rows)} réflexion(s)\n"
                             f"Écart-type {lo:.0f}–{hi:.0f} Hz : {dev:.1f} dB (direct seul {devd:.1f} dB){worst}")
        show = rows[:200]
        self.table.setRowCount(len(show))
        for i, r in enumerate(show):
            col = SB.CAT_COLORS.get(r["cat"], S.TEXT)
            lab = SB.CATS.get(r["cat"], r["cat"]) if r["order"] == 1 else f"{r['order']}× · {r['chain']}"
            self.table.setItem(i, 0, cell(r["src"].name, None, False))
            it = cell(lab, col, False); it.setToolTip(" → ".join(r["surf"]))
            self.table.setItem(i, 1, it)
            self.table.setItem(i, 2, cell(f"{r['delta']:.2f} m"))
            self.table.setItem(i, 3, cell(f"{r['dt']:.2f} ms"))
            self.table.setItem(i, 4, cell(f"{r['notch']:.0f} Hz", S.ACCENT))
            self.table.setItem(i, 5, cell(f"{r['rel']:+.1f} dB", S.DIM))

    # ------------------------------------------------------------------ balayage
    def run_scan(self):
        ctx = self.ctx()
        st = self.scene().settings
        self.apply_btn.setEnabled(False)
        if ctx is None:
            self.scan_lab.setText("Ajoutez un écouteur et des sources.")
            return
        # le balayage recalcule tous les chemins à chaque position : ordre limité à 2
        opts = dict(ctx["opts"], band_lo=st.sbir_band_lo, band_hi=st.sbir_band_hi,
                    order=min(ctx["opts"].get("order", 1), 2))
        QtWidgets.QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if st.sbir_scan == SCANS[0]:
                o = ctx["obj"]
                if o is None or o.TYPE != "speaker":
                    self.scan_lab.setText("Sélectionnez une enceinte (HP) pour balayer sa distance au mur.")
                    return
                m = ctx["scene"].model(o.model)
                pf = np.asarray(m.outline(), float)[:, 0]
                depth = float(pf.max() - pf.min())
                r = SB.scan_speaker(ctx["scene"], ctx["geo"], ctx["sources"], ctx["listener"], opts, ctx["c"],
                                    depth, st.sbir_scan_min, st.sbir_scan_max)
                if r is None:
                    self.scan_lab.setText("Aucune paroi derrière l'enceinte.")
                    return
                r.update(kind="speaker", obj=o, depth=depth)
            else:
                axis = "X" if st.sbir_scan == SCANS[1] else "Y"
                r = SB.scan_listener(ctx["scene"], ctx["geo"], ctx["sources"], ctx["listener"], opts, ctx["c"],
                                     axis, st.sbir_scan_min, st.sbir_scan_max)
                r.update(kind="listener", axis=axis, lst=ctx["listener_obj"])
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.scan = r
        pi = self.scan_plot.getPlotItem(); pi.clear()
        pi.addItem(pg.PlotDataItem(r["dist"], r["dev"], pen=pg.mkPen(S.ACCENT, width=2)))
        pi.addItem(pg.InfiniteLine(pos=r["current"], angle=90, pen=pg.mkPen(S.DIM, style=Qt.PenStyle.DashLine),
                                   label="actuel", labelOpts=dict(color=S.DIM, position=0.9)))
        pi.addItem(pg.InfiniteLine(pos=r["best"], angle=90, pen=pg.mkPen("#b6ff3a"),
                                   label="meilleur", labelOpts=dict(color="#b6ff3a", position=0.75)))
        if r["kind"] == "speaker":
            gap = r["best"] - r["depth"]
            self.scan_lab.setText(f"Distance face avant → mur : actuelle {r['current']:.2f} m · meilleure "
                                  f"{r['best']:.2f} m ({r['best_dev']:.1f} dB)\nEspace derrière la caisse : "
                                  f"{gap:.2f} m. Le miroir lié suit.")
        else:
            self.scan_lab.setText(f"Écoute en {r['axis']} : actuelle {r['current']:.2f} m · meilleure "
                                  f"{r['best']:.2f} m ({r['best_dev']:.1f} dB)")
        self.apply_btn.setEnabled(True)

    def apply_scan(self):
        r = self.scan
        if r is None:
            return
        if r["kind"] == "speaker":
            o = r["obj"]
            if o.locked:
                self.scan_lab.setText("Enceinte verrouillée : déverrouillez-la pour appliquer.")
                return
            off = r["best"] - r["current"]
            o.x = round(o.x + r["direction"][0] * off, 3)
            o.y = round(o.y + r["direction"][1] * off, 3)
            self.applied.emit(o)
        else:
            l = r["lst"]
            if r["axis"] == "X":
                l.x = round(r["best"], 3)
            else:
                l.y = round(r["best"], 3)
            self.applied.emit(None)
        self.scan = None
        self.apply_btn.setEnabled(False)
        self.changed.emit(True)
