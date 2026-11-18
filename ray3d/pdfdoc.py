"""Petit moteur de mise en page PDF (QPdfWriter + QPainter), en millimètres.

Coordonnées papier : origine en haut à gauche, x vers la droite, y vers le bas.
Les dessins techniques passent par un `Frame` qui convertit des coordonnées monde (m, axe b vers le
haut) en millimètres à une échelle normalisée (1:5, 1:10, 1:20…).
"""
from __future__ import annotations

import datetime
import math

import numpy as np
from PySide6 import QtCore, QtGui
from PySide6.QtCore import QPointF, QRectF, Qt

INK = QtGui.QColor("#111111")
DIM_INK = QtGui.QColor("#555555")
LIGHT = QtGui.QColor("#9a9a9a")
ACCENT = QtGui.QColor("#e8650a")
ZONE = QtGui.QColor("#d4a000")
PANEL_FILL = QtGui.QColor(232, 101, 10, 55)
SCALES = [1, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10, 15, 20, 25, 30, 40, 50, 75, 100, 150, 200, 250, 500]
DPI = 300


def fmt_len(v, units="mm"):
    if units == "mm":
        return f"{v * 1000:.0f}"
    if units == "cm":
        return f"{v * 100:.1f}"
    return f"{v:.3f}"


class Doc:
    def __init__(self, path, title, subtitle="", landscape=True):
        self.w = QtGui.QPdfWriter(path)
        self.w.setResolution(DPI)
        lay = QtGui.QPageLayout(QtGui.QPageSize(QtGui.QPageSize.PageSizeId.A4),
                                QtGui.QPageLayout.Orientation.Landscape if landscape else
                                QtGui.QPageLayout.Orientation.Portrait, QtCore.QMarginsF(0, 0, 0, 0))
        self.w.setPageLayout(lay)
        self.w.setTitle(title)
        self.w.setCreator("Ray 3D")
        self.W, self.H = (297.0, 210.0) if landscape else (210.0, 297.0)
        self.k = DPI / 25.4
        self.p = QtGui.QPainter(self.w)
        self.p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        self.title, self.subtitle = title, subtitle
        self.page = 0
        self.M = 12.0
        self._start_page()

    # ------------------------------------------------------------------ pages
    def _start_page(self):
        self.page += 1
        self.text(self.M, self.M - 2, self.title, 11, True)
        if self.subtitle:
            self.text(self.W - self.M, self.M - 2, self.subtitle, 8, False, DIM_INK, align="right")
        self.line(self.M, self.M + 1.5, self.W - self.M, self.M + 1.5, 0.3)
        date = datetime.date.today().strftime("%d.%m.%Y")
        self.text(self.M, self.H - 6, f"Ray 3D · {date}", 6.5, False, LIGHT)
        self.text(self.W - self.M, self.H - 6, f"page {self.page}", 6.5, False, LIGHT, align="right")
        self.top = self.M + 6

    def new_page(self, section=None):
        self.w.newPage()
        self._start_page()
        if section:
            self.section(section)

    def finish(self):
        self.p.end()

    # ------------------------------------------------------------------ primitives (mm)
    def q(self, x, y):
        return QPointF(x * self.k, y * self.k)

    def pen(self, width=0.25, color=INK, style=Qt.PenStyle.SolidLine):
        p = QtGui.QPen(QtGui.QColor(color), width * self.k)
        p.setStyle(style)
        p.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        return p

    def line(self, x1, y1, x2, y2, width=0.25, color=INK, style=Qt.PenStyle.SolidLine):
        self.p.setPen(self.pen(width, color, style))
        self.p.drawLine(self.q(x1, y1), self.q(x2, y2))

    def polyline(self, pts, width=0.25, color=INK, closed=False, fill=None, style=Qt.PenStyle.SolidLine):
        poly = QtGui.QPolygonF([self.q(x, y) for x, y in pts])
        self.p.setPen(self.pen(width, color, style) if width > 0 else Qt.PenStyle.NoPen)
        if fill is not None:
            self.p.setBrush(QtGui.QBrush(QtGui.QColor(fill)))
            self.p.drawPolygon(poly)
        else:
            self.p.setBrush(Qt.BrushStyle.NoBrush)
            (self.p.drawPolygon if closed else self.p.drawPolyline)(poly)

    def rect(self, x, y, w, h, width=0.25, color=INK, fill=None):
        self.polyline([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], width, color, True, fill)

    def circle(self, x, y, r, width=0.25, color=INK, fill=None):
        self.p.setPen(self.pen(width, color))
        self.p.setBrush(QtGui.QBrush(QtGui.QColor(fill)) if fill is not None else Qt.BrushStyle.NoBrush)
        self.p.drawEllipse(self.q(x, y), r * self.k, r * self.k)

    def font(self, size=8, bold=False):
        f = QtGui.QFont("DejaVu Sans")
        f.setPointSizeF(size)
        f.setBold(bold)
        return f

    def text_w(self, s, size=8, bold=False):
        fm = QtGui.QFontMetricsF(self.font(size, bold), self.w)
        return fm.horizontalAdvance(s) / self.k

    def text(self, x, y, s, size=8, bold=False, color=INK, align="left", angle=0.0, valign="base"):
        """Texte ; (x, y) = ligne de base (valign 'base'), centre ('middle') ou haut ('top')."""
        f = self.font(size, bold)
        self.p.setFont(f)
        self.p.setPen(QtGui.QPen(QtGui.QColor(color)))
        fm = QtGui.QFontMetricsF(f, self.w)
        tw = fm.horizontalAdvance(s)
        dx = {"left": 0.0, "center": -tw / 2, "right": -tw}[align]
        dy = {"base": 0.0, "middle": (fm.ascent() - fm.descent()) / 2, "top": fm.ascent()}[valign]
        self.p.save()
        self.p.translate(self.q(x, y))
        if angle:
            self.p.rotate(angle)
        self.p.drawText(QPointF(dx, dy), s)
        self.p.restore()
        return tw / self.k

    def para(self, x, y, w, s, size=8, color=INK, bold=False):
        """Paragraphe avec retour à la ligne. Renvoie le y de fin."""
        f = self.font(size, bold)
        self.p.setFont(f)
        self.p.setPen(QtGui.QPen(QtGui.QColor(color)))
        r = QRectF(x * self.k, y * self.k, w * self.k, 1e6)
        br = self.p.boundingRect(r, int(Qt.TextFlag.TextWordWrap), s)
        self.p.drawText(r, int(Qt.TextFlag.TextWordWrap), s)
        return y + br.height() / self.k

    def arc(self, x, y, r, start, span, width=0.2, color=INK):
        """Arc de cercle (centre x, y en mm), angles en degrés, sens trigonométrique visuel."""
        self.p.setPen(self.pen(width, color))
        self.p.setBrush(Qt.BrushStyle.NoBrush)
        k = self.k
        self.p.drawArc(QRectF((x - r) * k, (y - r) * k, 2 * r * k, 2 * r * k), int(start * 16), int(span * 16))

    def image(self, x, y, w, h, img: QtGui.QImage):
        if img is None or img.isNull():
            return
        ar = img.width() / max(img.height(), 1)
        if w / h > ar:
            nw = h * ar; x += (w - nw) / 2; w = nw
        else:
            nh = w / ar; y += (h - nh) / 2; h = nh
        self.p.drawImage(QRectF(x * self.k, y * self.k, w * self.k, h * self.k), img)
        self.rect(x, y, w, h, 0.2, LIGHT)

    def section(self, s):
        self.text(self.M, self.top + 4, s.upper(), 8, True, ACCENT)
        self.top += 8

    def ensure(self, h, section=None):
        if self.top + h > self.H - 12:
            self.new_page(section)

    # ------------------------------------------------------------------ tableaux
    def table(self, headers, rows, widths, x=None, size=7.0, row_h=4.6, bold_cols=(), right_cols=(),
              title=None, max_y=None):
        """Tableau simple ; saute de page si besoin (en répétant l'en-tête)."""
        x = self.M if x is None else x
        max_y = max_y or (self.H - 12)

        def head():
            y = self.top
            self.p.fillRect(QRectF(x * self.k, y * self.k, sum(widths) * self.k, row_h * self.k),
                            QtGui.QColor("#eeeeee"))
            cx = x
            for j, (h, w) in enumerate(zip(headers, widths)):
                if j in right_cols:
                    self.text(cx + w - 1.2, y + row_h / 2, h, size, True, DIM_INK, "right", valign="middle")
                else:
                    self.text(cx + 1.2, y + row_h / 2, h, size, True, DIM_INK, valign="middle")
                cx += w
            self.top = y + row_h

        if title:
            self.ensure(row_h * 3 + 8)
            self.section(title)
        head()
        for i, r in enumerate(rows):
            if self.top + row_h > max_y:
                self.new_page()
                head()
            y = self.top
            cx = x
            for j, (v, w) in enumerate(zip(r, widths)):
                s = str(v)
                al = "right" if j in right_cols else "left"
                tx = cx + w - 1.2 if al == "right" else cx + 1.2
                # coupe le texte trop long
                while len(s) > 3 and self.text_w(s, size, j in bold_cols) > w - 2:
                    s = s[:-2] + "…"
                self.text(tx, y + row_h / 2, s, size, j in bold_cols, INK, align=al, valign="middle")
                cx += w
            self.line(x, y + row_h, x + sum(widths), y + row_h, 0.1, LIGHT)
            self.top = y + row_h
        self.top += 3


# --------------------------------------------------------------------------- dessin à l'échelle
class Frame:
    """Monde (a, b) en mètres → papier (mm), b vers le haut."""

    def __init__(self, doc: Doc, box, lo, hi, margin=14.0, scale=None):
        self.d = doc
        x, y, w, h = box
        lo, hi = np.asarray(lo, float), np.asarray(hi, float)
        span = np.maximum(hi - lo, 1e-6)
        fit = min((w - 2 * margin) / span[0], (h - 2 * margin) / span[1])   # mm par m
        if scale is None:
            need = 1000.0 / max(fit, 1e-9)
            scale = next((s for s in SCALES if s >= need - 1e-9), math.ceil(need / 100) * 100)
        self.scale = scale
        self.s = 1000.0 / scale
        c = (lo + hi) / 2
        self.cx, self.cy = x + w / 2, y + h / 2
        self.c = c
        self.box = box

    def place(self, cx, cy, c):
        """Centre papier (mm) et centre monde de la vue (pour aligner plusieurs vues)."""
        self.cx, self.cy, self.c = cx, cy, np.asarray(c, float)
        return self

    def pt(self, a, b):
        return (self.cx + (a - self.c[0]) * self.s, self.cy - (b - self.c[1]) * self.s)

    def pts(self, P):
        return [self.pt(float(a), float(b)) for a, b in np.asarray(P, float)[:, :2]]

    def label(self):
        sc = self.scale
        return f"Éch. 1:{sc:g}"

    # dessins
    def poly(self, P, width=0.25, color=INK, closed=True, fill=None, style=Qt.PenStyle.SolidLine):
        self.d.polyline(self.pts(P), width, color, closed, fill, style)

    def seg(self, A, B, width=0.25, color=INK, style=Qt.PenStyle.SolidLine):
        (x1, y1), (x2, y2) = self.pt(*A[:2]), self.pt(*B[:2])
        self.d.line(x1, y1, x2, y2, width, color, style)

    def text(self, a, b, s, size=7, bold=False, color=INK, align="center", valign="middle", angle=0.0):
        x, y = self.pt(a, b)
        self.d.text(x, y, s, size, bold, color, align, angle, valign)

    def dim(self, A, B, off, text, size=6.5, color=DIM_INK, bold=False, ext=True):
        """Cote de A à B (monde), décalée de `off` mm (positif = à gauche de A→B sur le papier)."""
        pa, pb = np.array(self.pt(*A[:2])), np.array(self.pt(*B[:2]))
        d = pb - pa
        L = float(np.linalg.norm(d))
        if L < 0.3:
            return
        u = d / L
        n = np.array([u[1], -u[0]])               # à gauche sur le papier (y vers le bas)
        qa, qb = pa + n * off, pb + n * off
        doc = self.d
        if ext and abs(off) > 0.5:
            sgn = 1 if off > 0 else -1
            for p0, p1 in ((pa, qa), (pb, qb)):
                s0 = p0 + n * sgn * 1.0
                s1 = p1 + n * sgn * 1.2
                doc.line(s0[0], s0[1], s1[0], s1[1], 0.12, color)
        doc.line(qa[0], qa[1], qb[0], qb[1], 0.15, color)
        t = (u + n) / math.sqrt(2) * 1.1
        for q in (qa, qb):
            doc.line(q[0] - t[0], q[1] - t[1], q[0] + t[0], q[1] + t[1], 0.3, color)
        ang = math.degrees(math.atan2(u[1], u[0]))
        if ang > 90.0001 or ang <= -90:
            ang += 180
        m = (qa + qb) / 2
        nn = np.array([math.sin(math.radians(ang)), -math.cos(math.radians(ang))])   # « au-dessus » du texte
        tw = doc.text_w(text, size, bold)
        if tw > L - 1.5:                         # cote courte : texte hors de la cote, alterné
            k = self.__dict__.get("_short", 0)
            self._short = k + 1
            ud = np.array([math.cos(math.radians(ang)), math.sin(math.radians(ang))])   # sens de lecture
            ends = sorted((qa, qb), key=lambda q: float(q @ ud))
            if k % 2 == 0:
                m = ends[1] + ud * (tw / 2 + 1.6)
            else:
                m = ends[0] - ud * (tw / 2 + 1.6)
            doc.line(ends[0][0], ends[0][1], (ends[0] - ud * 1.2)[0], (ends[0] - ud * 1.2)[1], 0.15, color)
            doc.line(ends[1][0], ends[1][1], (ends[1] + ud * 1.2)[0], (ends[1] + ud * 1.2)[1], 0.15, color)
        pos = m + nn * 0.8
        doc.text(pos[0], pos[1], text, size, bold, color, "center", ang, "base")
        # zone occupée par le texte (pour éviter les chevauchements d'autres étiquettes)
        th = size * 0.3528 * 1.1
        ud = np.array([math.cos(math.radians(ang)), math.sin(math.radians(ang))])
        c = pos + nn * th / 2
        hx = abs(ud[0]) * tw / 2 + abs(nn[0]) * th / 2 + 0.6
        hy = abs(ud[1]) * tw / 2 + abs(nn[1]) * th / 2 + 0.6
        self.__dict__.setdefault("_boxes", []).append((c[0] - hx, c[1] - hy, c[0] + hx, c[1] + hy))

    def leader(self, P, dx, dy, text, size=6.5, color=DIM_INK, bold=False):
        x, y = self.pt(*P[:2])
        doc = self.d
        doc.line(x, y, x + dx, y + dy, 0.15, color)
        doc.circle(x, y, 0.35, 0.1, color, color)
        al = "left" if dx >= 0 else "right"
        doc.line(x + dx, y + dy, x + dx + (3 if dx >= 0 else -3), y + dy, 0.15, color)
        doc.text(x + dx + (3.5 if dx >= 0 else -3.5), y + dy, text, size, bold, color, al, valign="middle")

    def scale_note(self, units):
        x, y, w, h = self.box
        self.d.text(x + w, y + h - 1, f"{self.label()} · cotes en {units}", 6.5, False, LIGHT, "right")
