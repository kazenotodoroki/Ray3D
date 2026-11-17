"""Champs de saisie : nombres tapés librement au clavier, validés à Entrée / en sortie de champ."""
from __future__ import annotations

import math
import re

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt


def parse_number(text):
    """Nombre depuis un texte : accepte la virgule, les espaces et un suffixe d'unité."""
    t = str(text).strip().replace(" ", "").replace(" ", "").replace(",", ".")
    m = re.match(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?", t)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


class NumField(QtWidgets.QLineEdit):
    """Champ numérique.
    - saisie libre (n'importe quelle valeur intermédiaire), validée à Entrée ou en quittant le champ ;
    - la valeur est ramenée dans [min, max] ;
    - flèches haut / bas et molette (champ actif seulement) changent la valeur d'un pas
      (Maj = ×10, Ctrl = ÷10) ;
    - Échap annule la saisie en cours."""
    valueChanged = QtCore.Signal(float)

    def __init__(self, value=0.0, lo=-1e9, hi=1e9, step=1.0, decimals=2, suffix="", integer=False, parent=None):
        super().__init__(parent)
        self._lo, self._hi, self._step = lo, hi, step
        self._dec = 0 if integer else decimals
        self._suffix = suffix
        self._int = integer
        self._v = self._clamp(value)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.editingFinished.connect(self._commit)
        self._show()

    # ---------------------------------------------------------------- API façon QSpinBox
    def setRange(self, lo, hi):
        self._lo, self._hi = lo, hi
        self.setValue(self._v)

    def setDecimals(self, d):
        self._dec = 0 if self._int else d
        self._show()

    def setSingleStep(self, s):
        self._step = s

    def setSuffix(self, s):
        self._suffix = s
        self._show()

    def value(self):
        return int(round(self._v)) if self._int else self._v

    def setValue(self, v):
        v = self._clamp(v)
        changed = v != self._v
        self._v = v
        self._show()
        if changed and not self.signalsBlocked():
            self.valueChanged.emit(self.value())

    # ---------------------------------------------------------------- interne
    def _clamp(self, v):
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = 0.0
        if not math.isfinite(v):
            v = 0.0
        v = min(max(v, self._lo), self._hi)
        if self._int:
            v = float(int(round(v)))
        else:
            v = round(v, max(self._dec, 0) + 3)
        return v

    def _fmt(self, v):
        return f"{int(round(v))}" if self._int else f"{v:.{self._dec}f}"

    def _show(self):
        if self.hasFocus():
            self.setText(self._fmt(self._v))
        else:
            self.setText(self._fmt(self._v) + (self._suffix if self._suffix else ""))
        self.setCursorPosition(0)

    def _commit(self):
        v = parse_number(self.text())
        if v is None:
            self._show()
            return
        self.setValue(v)

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.setText(self._fmt(self._v))
        self.selectAll()
        self._select_on_release = e.reason() == Qt.FocusReason.MouseFocusReason

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if getattr(self, "_select_on_release", False) and not self.hasSelectedText():
            self.selectAll()          # premier clic : tout sélectionner pour retaper
        self._select_on_release = False

    def focusOutEvent(self, e):
        self._commit()
        super().focusOutEvent(e)
        self._show()

    def _bump(self, n):
        mods = QtWidgets.QApplication.keyboardModifiers()
        k = 10.0 if mods & Qt.KeyboardModifier.ShiftModifier else (0.1 if mods & Qt.KeyboardModifier.ControlModifier else 1.0)
        cur = parse_number(self.text())
        base = self._v if cur is None else cur
        self.setValue(base + n * self._step * k)
        if self.hasFocus():
            self.setText(self._fmt(self._v))
            self.selectAll()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Up:
            self._bump(1); return
        if e.key() == Qt.Key.Key_Down:
            self._bump(-1); return
        if e.key() == Qt.Key.Key_Escape:
            self.setText(self._fmt(self._v)); self.selectAll(); return
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._commit()
            self.setText(self._fmt(self._v)); self.selectAll()
            e.accept()
            return            # Entrée ne doit pas remonter au dialogue
        super().keyPressEvent(e)

    def wheelEvent(self, e):
        if not self.hasFocus():
            e.ignore()        # laisse défiler le panneau
            return
        d = e.angleDelta().y()
        if d:
            self._bump(1 if d > 0 else -1)
        e.accept()


class NoWheelCombo(QtWidgets.QComboBox):
    """Liste déroulante qui ne change pas de valeur à la molette tant qu'elle n'est pas active."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, e):
        if not self.hasFocus():
            e.ignore()
            return
        super().wheelEvent(e)


def no_enter_dialog(dlg: QtWidgets.QDialog):
    """Désactive « Entrée = bouton par défaut » dans un dialogue."""
    for b in dlg.findChildren(QtWidgets.QPushButton):
        b.setAutoDefault(False)
        b.setDefault(False)
