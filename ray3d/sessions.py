"""Sauvegarde automatique, versions horodatées, scènes récentes et fenêtre de démarrage.

- Scène enregistrée dans un fichier : sauvegarde automatique à côté, « <nom>.autosave.json »
  (sinon dans ~/.ray3d/autosave/ si le dossier n'est pas accessible en écriture).
- Scène sans fichier : ~/.ray3d/autosave.json.
- Chaque sauvegarde automatique garde le chemin du fichier d'origine : après une restauration,
  Ctrl+S réécrit au bon endroit.
- Versions horodatées : au plus une toutes les 5 minutes, dans ~/.ray3d/versions/<nom>/ ; on garde
  les 40 dernières par scène.
"""
from __future__ import annotations

import datetime
import glob
import hashlib
import json
import os
import shutil
import time

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

USER_DIR = os.path.join(os.path.expanduser("~"), ".ray3d")
GLOBAL_AUTOSAVE = os.path.join(USER_DIR, "autosave.json")
VERSIONS_DIR = os.path.join(USER_DIR, "versions")
RECENT_FILE = os.path.join(USER_DIR, "recent.json")
VERSION_EVERY = 300.0        # s
KEEP_VERSIONS = 40
SUFFIX = ".autosave.json"


def _stem(path):
    return os.path.splitext(os.path.basename(path))[0] if path else "sans-nom"


def autosave_path(path):
    """Fichier de sauvegarde automatique pour une scène (chemin d'origine ou None)."""
    if not path:
        return GLOBAL_AUTOSAVE
    d = os.path.dirname(os.path.abspath(path))
    if os.access(d, os.W_OK):
        return os.path.join(d, _stem(path) + SUFFIX)
    h = hashlib.sha1(os.path.abspath(path).encode()).hexdigest()[:8]
    return os.path.join(USER_DIR, "autosave", f"{_stem(path)}-{h}.json")


def _write_json(target, data):
    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, target)


def scene_data(scene, path):
    d = scene.to_dict()
    d["meta"] = dict(path=os.path.abspath(path) if path else "", saved=datetime.datetime.now().isoformat(timespec="seconds"))
    return d


def write_autosave(scene, path):
    target = autosave_path(path)
    _write_json(target, scene_data(scene, path))
    return target


def write_version(scene, path):
    d = os.path.join(VERSIONS_DIR, _stem(path))
    name = f"{_stem(path)}_{datetime.datetime.now():%Y%m%d-%H%M%S}.json"
    target = os.path.join(d, name)
    _write_json(target, scene_data(scene, path))
    files = sorted(glob.glob(os.path.join(d, "*.json")))
    for old in files[:-KEEP_VERSIONS]:
        try:
            os.remove(old)
        except OSError:
            pass
    return target


def archive_file(src, label="session"):
    """Copie un fichier de sauvegarde dans les versions (avant de le remplacer)."""
    if not os.path.isfile(src):
        return None
    meta = read_meta(src)
    stem = _stem(meta.get("path")) if meta.get("path") else label
    d = os.path.join(VERSIONS_DIR, stem)
    os.makedirs(d, exist_ok=True)
    t = datetime.datetime.fromtimestamp(os.path.getmtime(src))
    target = os.path.join(d, f"{stem}_{t:%Y%m%d-%H%M%S}.json")
    if not os.path.exists(target):
        shutil.copyfile(src, target)
    return target


def read_meta(path):
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        return d.get("meta") or {}
    except (OSError, ValueError):
        return {}


def versions(path=None):
    """Versions d'une scène (ou toutes si path est None), de la plus récente à la plus ancienne."""
    pat = os.path.join(VERSIONS_DIR, _stem(path) if path else "*", "*.json")
    files = glob.glob(pat)
    return sorted(files, key=os.path.getmtime, reverse=True)


def recent():
    try:
        with open(RECENT_FILE, encoding="utf-8") as fh:
            return [p for p in json.load(fh) if isinstance(p, str)]
    except (OSError, ValueError):
        return []


def add_recent(path):
    if not path:
        return
    p = os.path.abspath(path)
    lst = [x for x in recent() if os.path.abspath(x) != p]
    try:
        _write_json(RECENT_FILE, [p] + lst[:14])
    except OSError:
        pass


def newer_autosave(path):
    """Sauvegarde automatique plus récente que le fichier, ou None."""
    a = autosave_path(path)
    if os.path.isfile(a) and os.path.isfile(path) and os.path.getmtime(a) > os.path.getmtime(path) + 1:
        return a
    return None


def when(path):
    return time.strftime("%d.%m.%Y %H:%M", time.localtime(os.path.getmtime(path)))


# =========================================================================== fenêtre de démarrage
class StartDialog(QtWidgets.QDialog):
    """Que faire au lancement : restaurer une session, ouvrir une scène, ou nouvelle session."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ray 3D")
        self.resize(720, 460)
        self.choice = None          # ("restore", fichier) / ("open", fichier) / ("browse",) / ("new",)
        lay = QtWidgets.QVBoxLayout(self)
        t = QtWidgets.QLabel("Reprendre le travail")
        f = t.font(); f.setPointSizeF(f.pointSizeF() * 1.3); f.setBold(True); t.setFont(f)
        lay.addWidget(t)
        self.list = QtWidgets.QListWidget()
        self.list.itemDoubleClicked.connect(lambda *_: self._open_item())
        lay.addWidget(self.list, 1)
        self._fill()
        hb = QtWidgets.QHBoxLayout()
        bn = QtWidgets.QPushButton("Nouvelle session"); bn.clicked.connect(self._new)
        bb = QtWidgets.QPushButton("Ouvrir un fichier…"); bb.clicked.connect(lambda: self._done(("browse",)))
        self.bo = QtWidgets.QPushButton("Ouvrir"); self.bo.setObjectName("primary"); self.bo.clicked.connect(self._open_item)
        self.bo.setDefault(False); self.bo.setAutoDefault(False)
        hb.addWidget(bn); hb.addStretch(1); hb.addWidget(bb); hb.addWidget(self.bo)
        lay.addLayout(hb)
        self.list.currentRowChanged.connect(lambda r: self.bo.setEnabled(r >= 0))
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            self.bo.setEnabled(False)

    def _add(self, text, data, sub=""):
        it = QtWidgets.QListWidgetItem(text + (f"\n    {sub}" if sub else ""))
        it.setData(Qt.ItemDataRole.UserRole, data)
        self.list.addItem(it)

    def _fill(self):
        seen = set()
        if os.path.isfile(GLOBAL_AUTOSAVE):
            m = read_meta(GLOBAL_AUTOSAVE)
            orig = m.get("path") or ""
            self._add(f"Session sauvegardée automatiquement · {when(GLOBAL_AUTOSAVE)}",
                      ("restore", GLOBAL_AUTOSAVE), f"scène : {orig}" if orig else "scène sans fichier")
        for p in recent():
            if not os.path.isfile(p) or p in seen:
                continue
            seen.add(p)
            a = newer_autosave(p)
            if a:
                self._add(f"{os.path.basename(p)} · modifications non enregistrées du {when(a)}",
                          ("restore", a), p)
            self._add(f"{os.path.basename(p)} · enregistré le {when(p)}", ("open", p), p)

    def _open_item(self):
        it = self.list.currentItem()
        if it is not None:
            self._done(it.data(Qt.ItemDataRole.UserRole))

    def _new(self):
        if os.path.isfile(GLOBAL_AUTOSAVE):
            r = QtWidgets.QMessageBox.question(
                self, "Nouvelle session",
                f"Ouvrir une nouvelle session ?\n\nLa session sauvegardée automatiquement le {when(GLOBAL_AUTOSAVE)} "
                "est rangée dans les versions (Fichier › Versions…), elle n'est pas perdue.")
            if r != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        self._done(("new",))

    def _done(self, choice):
        self.choice = choice
        self.accept()


class VersionsDialog(QtWidgets.QDialog):
    """Versions horodatées : de la scène courante, ou de toutes."""

    def __init__(self, parent, path):
        super().__init__(parent)
        self.setWindowTitle("Versions")
        self.resize(680, 480)
        self.path = path
        self.choice = None
        lay = QtWidgets.QVBoxLayout(self)
        self.all = QtWidgets.QCheckBox("Toutes les scènes")
        self.all.setChecked(not path)
        self.all.toggled.connect(self._fill)
        lay.addWidget(self.all)
        self.list = QtWidgets.QListWidget()
        self.list.itemDoubleClicked.connect(lambda *_: self._ok())
        lay.addWidget(self.list, 1)
        info = QtWidgets.QLabel("Une version est gardée toutes les 5 minutes de travail (40 par scène), et avant de "
                                "commencer une nouvelle session. Ouvrir une version garde le chemin du fichier "
                                "d'origine : Ctrl+S l'y réenregistre.")
        info.setObjectName("info"); info.setWordWrap(True)
        lay.addWidget(info)
        hb = QtWidgets.QHBoxLayout()
        bd = QtWidgets.QPushButton("Dossier des versions")
        bd.clicked.connect(lambda: (os.makedirs(VERSIONS_DIR, exist_ok=True),
                                    QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(VERSIONS_DIR))))
        bc = QtWidgets.QPushButton("Annuler"); bc.clicked.connect(self.reject)
        bo = QtWidgets.QPushButton("Ouvrir cette version"); bo.setObjectName("primary"); bo.clicked.connect(self._ok)
        hb.addWidget(bd); hb.addStretch(1); hb.addWidget(bc); hb.addWidget(bo)
        lay.addLayout(hb)
        self._fill()

    def _fill(self, *_):
        self.list.clear()
        for f in versions(None if self.all.isChecked() else self.path):
            m = read_meta(f)
            it = QtWidgets.QListWidgetItem(f"{when(f)} · {os.path.basename(os.path.dirname(f))}"
                                           + (f"\n    {m.get('path')}" if m.get("path") else ""))
            it.setData(Qt.ItemDataRole.UserRole, f)
            self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _ok(self):
        it = self.list.currentItem()
        if it is not None:
            self.choice = it.data(Qt.ItemDataRole.UserRole)
            self.accept()
