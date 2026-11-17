"""Import / export de directivités et de modèles de HP.

Formats lus :
- Polaires H/V en texte (.txt, .csv) : sections « H » et « V », une ligne d'en-tête
  « angle, f1, f2, … » puis une ligne par angle (dB, relatifs ou absolus).
- SOFA / AES69 (.sofa, HDF5) : conventions FreeFieldDirectivityTF / GeneralTF (module h5py).
- Modèle Ray 3D (.r3dspk, JSON).

Les formats EASE GLL / XHN et CLF binaires (CF1/CF2) sont fermés ou non documentés publiquement :
il faut les exporter en polaires texte ou en SOFA depuis l'outil du fabricant.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import asdict

import numpy as np

from .model import SpeakerModel, Element, new_id

GRID_AZ = np.arange(-180.0, 180.01, 5.0)
GRID_EL = np.arange(-90.0, 90.01, 5.0)
OCTAVES = [63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]

UNSUPPORTED = {
    ".gll": "GLL (EASE / AFMG) est un format binaire protégé, lisible seulement avec la bibliothèque "
            "d'AFMG. Exportez les polaires H/V en texte ou un fichier SOFA depuis EASE GLL Viewer / "
            "le logiciel du fabricant.",
    ".xhn": "XHN (EASE SpeakerLab) n'est pas documenté publiquement. Exportez des polaires texte ou un SOFA.",
    ".cf1": "CLF binaire (CF1) : format propriétaire du CLF group. Utilisez le CLF Viewer pour exporter "
            "les polaires en texte, ou un fichier SOFA.",
    ".cf2": "CLF binaire (CF2) : format propriétaire du CLF group. Utilisez le CLF Viewer pour exporter "
            "les polaires en texte, ou un fichier SOFA.",
}


class ImportErrorMsg(Exception):
    pass


# --------------------------------------------------------------------------- outils
def _num(tok):
    try:
        return float(tok)
    except ValueError:
        return None


def _split(line):
    return [t for t in re.split(r"[;,\t ]+", line.strip()) if t]


def _normalize(db):
    """Normalise chaque bande pour que l'axe (az 0, el 0) soit à 0 dB."""
    ia = int(np.argmin(np.abs(GRID_AZ)))
    ie = int(np.argmin(np.abs(GRID_EL)))
    return db - db[:, ie:ie + 1, ia:ia + 1]


def balloon_from_polars(freqs, angles_h, H, angles_v, V):
    """Construit un ballon 5° à partir des polaires horizontale et verticale.
    Interpolation elliptique : dB(θ, ψ) = cos²ψ·H(±θ) + sin²ψ·V(±θ)."""
    A, E = np.meshgrid(np.radians(GRID_AZ), np.radians(GRID_EL))          # (nEl, nAz)
    x = np.cos(E) * np.cos(A); y = np.cos(E) * np.sin(A); z = np.sin(E)
    th = np.degrees(np.arccos(np.clip(x, -1, 1)))
    psi = np.arctan2(z, y)
    c2, s2 = np.cos(psi) ** 2, np.sin(psi) ** 2
    sh = np.where(np.cos(psi) >= 0, 1.0, -1.0)
    sv = np.where(np.sin(psi) >= 0, 1.0, -1.0)
    out = []
    for k in range(len(freqs)):
        h = np.interp(sh * th, angles_h, H[:, k], period=360)
        v = np.interp(sv * th, angles_v, V[:, k], period=360)
        out.append(c2 * h + s2 * v)
    db = _normalize(np.array(out))
    return dict(freqs=[float(f) for f in freqs], az=GRID_AZ.tolist(), el=GRID_EL.tolist(),
                db=np.round(db, 2).tolist(), source="polaires H/V")


# --------------------------------------------------------------------------- polaires texte
def read_polar_text(path):
    """Fichier texte de polaires. Sections repérées par une ligne contenant H / V
    (ex. « [H] », « # plan: V », « Horizontal »). Sans section : même polaire pour H et V."""
    sections, cur = {}, None
    header = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            low = line.lower().lstrip("#[ ").rstrip("] ")
            m = re.match(r"^(plan\s*[:=]?\s*)?(h|v|horizontal|vertical|horizontale|verticale)$", low)
            if m:
                cur = "V" if m.group(2).startswith("v") else "H"
                sections.setdefault(cur, [])
                continue
            if line.startswith("#"):
                continue
            toks = _split(line)
            nums = [_num(t) for t in toks]
            if nums and nums[0] is None:          # en-tête : angle, f1, f2…
                fr = [_num(t.lower().replace("hz", "").replace("k", "e3")) for t in toks[1:]]
                if fr and all(f is not None for f in fr):
                    header[cur or "H"] = fr
                continue
            if any(v is None for v in nums) or len(nums) < 2:
                continue
            sections.setdefault(cur or "H", []).append(nums)
    if not sections:
        raise ImportErrorMsg("Aucune donnée numérique trouvée.")

    def table(key):
        rows = np.array(sections[key], float)
        rows = rows[np.argsort(rows[:, 0])]
        return rows[:, 0], rows[:, 1:]
    keyH = "H" if "H" in sections else next(iter(sections))
    keyV = "V" if "V" in sections else keyH
    aH, H = table(keyH)
    aV, V = table(keyV)
    nb = min(H.shape[1], V.shape[1])
    freqs = header.get(keyH) or header.get(keyV) or OCTAVES[:nb]
    freqs = list(freqs)[:nb]
    if len(freqs) < nb:
        nb = len(freqs)
    return balloon_from_polars(freqs, aH, H[:, :nb], aV, V[:, :nb])


# --------------------------------------------------------------------------- SOFA (AES69)
def read_sofa(path):
    try:
        import h5py
    except ImportError as e:
        raise ImportErrorMsg("La lecture SOFA demande le module h5py (pip install h5py).") from e
    with h5py.File(path, "r") as f:
        conv = f.attrs.get("SOFAConventions", b"")
        conv = conv.decode() if isinstance(conv, bytes) else str(conv)
        if "Data.Real" in f:
            mag = np.hypot(np.asarray(f["Data.Real"]), np.asarray(f["Data.Imag"]))
        elif "Data.IR" in f:
            ir = np.asarray(f["Data.IR"])
            mag = np.abs(np.fft.rfft(ir, axis=-1))
            fs = float(np.asarray(f["Data.SamplingRate"]).ravel()[0])
            freqs = np.fft.rfftfreq(ir.shape[-1], 1 / fs)
        else:
            raise ImportErrorMsg("Fichier SOFA sans Data.Real/Imag ni Data.IR.")
        if "N" in f and "Data.Real" in f:
            freqs = np.asarray(f["N"]).ravel()
        mag = mag.reshape(-1, mag.shape[-1])               # (directions, fréquences)
        pos = None
        for key in ("ReceiverPosition", "SourcePosition", "EmitterPosition", "ListenerPosition"):
            if key in f:
                p = np.asarray(f[key])
                p = p.reshape(-1, p.shape[-1]) if p.ndim >= 2 else p.reshape(1, -1)
                if p.shape[0] == mag.shape[0]:
                    typ = f[key].attrs.get("Type", b"spherical")
                    typ = typ.decode() if isinstance(typ, bytes) else str(typ)
                    pos, ptype = p, typ.lower()
                    break
        if pos is None:
            raise ImportErrorMsg("Impossible d'associer les positions de mesure aux données.")
    if "cart" in ptype:
        x, y, z = pos[:, 0], pos[:, 1], pos[:, 2]
        r = np.maximum(np.sqrt(x * x + y * y + z * z), 1e-9)
        dirs = np.column_stack([x, y, z]) / r[:, None]
    else:
        az, el = np.radians(pos[:, 0]), np.radians(pos[:, 1])
        dirs = np.column_stack([np.cos(el) * np.cos(az), np.cos(el) * np.sin(az), np.sin(el)])
    bands, out = [], []
    p2 = mag ** 2
    for fc in OCTAVES:
        m = (freqs >= fc / math.sqrt(2)) & (freqs < fc * math.sqrt(2))
        if m.any():
            bands.append(fc)
            out.append(10 * np.log10(np.maximum(p2[:, m].mean(1), 1e-20)))
    if not bands:
        raise ImportErrorMsg("Aucune fréquence exploitable dans le fichier SOFA.")
    A, E = np.meshgrid(np.radians(GRID_AZ), np.radians(GRID_EL))
    g = np.column_stack([(np.cos(E) * np.cos(A)).ravel(), (np.cos(E) * np.sin(A)).ravel(), np.sin(E).ravel()])
    nearest = np.argmax(g @ dirs.T, axis=1)                # plus proche mesure pour chaque point de grille
    db = np.array([b[nearest].reshape(E.shape) for b in out])
    db = _normalize(db)
    return dict(freqs=[float(b) for b in bands], az=GRID_AZ.tolist(), el=GRID_EL.tolist(),
                db=np.round(db, 2).tolist(), source=f"SOFA {conv}".strip())


def read_directivity(path):
    low = path.lower()
    for ext, msg in UNSUPPORTED.items():
        if low.endswith(ext):
            raise ImportErrorMsg(msg)
    if low.endswith(".sofa"):
        return read_sofa(path)
    return read_polar_text(path)


def coverage_from_balloon(b, freq=1000.0):
    """Ouvertures -6 dB (H, V) dans la bande la plus proche."""
    f = np.asarray(b["freqs"], float)
    k = int(np.argmin(np.abs(np.log(f / freq))))
    db = np.asarray(b["db"], float)[k]
    az, el = np.asarray(b["az"]), np.asarray(b["el"])
    ie, ia = int(np.argmin(np.abs(el))), int(np.argmin(np.abs(az)))
    h = db[ie]; v = db[:, ia]

    def width(angles, vals):
        ok = vals >= -6
        c = int(np.argmin(np.abs(angles)))
        lo = c
        while lo > 0 and ok[lo - 1]:
            lo -= 1
        hi = c
        while hi < len(ok) - 1 and ok[hi + 1]:
            hi += 1
        return float(angles[hi] - angles[lo])
    return width(az, h), width(el, v)


# --------------------------------------------------------------------------- modèle Ray 3D
def export_model(model: SpeakerModel, path):
    d = asdict(model)
    d["format"] = "ray3d-speaker/1"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)


def import_model(path) -> SpeakerModel:
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    names = set(SpeakerModel.__dataclass_fields__)
    m = SpeakerModel(**{k: v for k, v in d.items() if k in names and k != "elements"})
    en = set(Element.__dataclass_fields__)
    m.elements = [Element(**{k: v for k, v in e.items() if k in en}) for e in d.get("elements", [])]
    m.id = new_id()
    return m
