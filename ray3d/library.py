"""Modèles de HP par défaut. Profils latéraux en (f avant, u haut), origine = point d'accroche."""
from .model import SpeakerModel, Element


def default_models():
    return [
        SpeakerModel(
            "LA12 · line array",
            profile=[[0, 0], [0, -0.35], [-0.55, -0.30], [-0.55, -0.05]],
            width=1.0, top_hinge=[0.0, 0.0], bottom_hinge=[0.0, -0.35],
            elements=[Element("HF", 0.0, 0.0, -0.175, 0, 0, "Pavillon", 110, 10, 128)],
            id="la12"),
        SpeakerModel(
            "PS12 · point source",
            profile=[[0.19, 0], [0.19, -0.6], [-0.19, -0.55], [-0.19, -0.05]],
            width=0.4, top_hinge=[0.19, 0.0], bottom_hinge=[0.19, -0.6],
            elements=[Element("Coax", 0.19, 0.0, -0.3, 0, 0, "Pavillon", 90, 50, 122)],
            id="ps12"),
        SpeakerModel(
            "BH15 · bi-pavillon",
            profile=[[0.2, 0], [0.2, -0.3], [0.05, -0.62], [-0.25, -0.62], [-0.25, 0]],
            width=0.5, top_hinge=[0.2, 0.0], bottom_hinge=[0.05, -0.62],
            elements=[Element("Long", 0.2, 0.0, -0.15, 0, 0, "Pavillon", 60, 20, 124),
                      Element("Court", 0.13, 0.0, -0.46, 0, -30, "Pavillon", 90, 40, 118)],
            id="bh15"),
        SpeakerModel(
            "FF5 · front fill",
            profile=[[0.08, 0], [0.08, -0.16], [-0.08, -0.15], [-0.08, -0.01]],
            width=0.16, top_hinge=[0.08, 0.0], bottom_hinge=[0.08, -0.16],
            elements=[Element("Coax", 0.08, 0.0, -0.08, 0, 0, "Pavillon", 100, 60, 108)],
            id="ff5"),
        SpeakerModel(
            "SB18 · sub",
            profile=[[0.35, 0], [0.35, -0.55], [-0.35, -0.55], [-0.35, 0]],
            width=0.6, top_hinge=[0.35, 0.0], bottom_hinge=[0.35, -0.55],
            elements=[Element("LF", 0.35, 0.0, -0.275, 0, 0, "Omni", 360, 360, 130)],
            id="sb18"),
        # --- L-Acoustics (dimensions et niveaux des fiches techniques, géométrie interne approchée)
        SpeakerModel(
            "L-Acoustics X12",
            profile=[[0.19, 0], [0.19, -0.496], [0.0, -0.496], [-0.185, -0.25], [-0.185, 0]],
            width=0.43, top_hinge=[0.19, 0.0], bottom_hinge=[0.19, -0.496],
            elements=[Element("Coax 12\" + 3\"", 0.19, 0.0, -0.248, 0, 0, "Pavillon", 90, 60, 136)],
            id="lac_x12"),
        SpeakerModel(
            "L-Acoustics SB28",
            profile=[[0.35, 0], [0.35, -0.55], [-0.35, -0.55], [-0.35, 0]],
            width=1.35, top_hinge=[0.35, 0.0], bottom_hinge=[0.35, -0.55],
            elements=[Element("LF 18\" A", 0.33, 0.33, -0.275, 0, 0, "Omni", 360, 360, 137),
                      Element("LF 18\" B", 0.33, -0.33, -0.275, 0, 0, "Omni", 360, 360, 137)],
            id="lac_sb28"),
        SpeakerModel(
            "L-Acoustics A15 Focus",
            profile=[[0, 0], [0, -0.431], [-0.49, -0.389], [-0.49, -0.042]],
            width=0.762, top_hinge=[0.0, 0.0], bottom_hinge=[0.0, -0.431],
            elements=[Element("15\" + 3\" Panflex", 0.0, 0.0, -0.2155, 0, 0, "Pavillon", 110, 10, 144)],
            id="lac_a15f"),
        SpeakerModel(
            "L-Acoustics A15 Wide",
            profile=[[0, 0], [0, -0.424], [-0.494, -0.303], [-0.494, -0.121]],
            width=0.762, top_hinge=[0.0, 0.0], bottom_hinge=[0.0, -0.424],
            elements=[Element("15\" + 3\" Panflex", 0.0, 0.0, -0.212, 0, 0, "Pavillon", 110, 30, 141)],
            id="lac_a15w"),
        # --- Yamaha HS (fiche : 250 × 390 × 334 mm, 8" + dôme 1", filtre 2 kHz, 47 Hz–24 kHz à -3 dB).
        # Yamaha ne publie ni SPL max ni dispersion : niveaux, ouvertures et position des HP estimés.
        # Origine = coin haut avant (centre de la façade en largeur), comme les autres modèles.
        SpeakerModel(
            "Yamaha HS8",
            profile=[[0, 0], [0, -0.39], [-0.334, -0.39], [-0.334, 0]],
            width=0.25, top_hinge=[0.0, 0.0], bottom_hinge=[0.0, -0.39],
            elements=[Element("Tweeter 1\"", 0.0, 0.0, -0.085, 0, 0, "Pavillon", 90, 80, 101),
                      Element("Woofer 8\"", 0.0, 0.0, -0.255, 0, 0, "Pavillon", 150, 150, 104)],
            id="yam_hs8"),
        SpeakerModel(
            "Yamaha HS8S · sub",
            profile=[[0, 0], [0, -0.35], [-0.389, -0.35], [-0.389, 0]],
            width=0.30, top_hinge=[0.0, 0.0], bottom_hinge=[0.0, -0.35],
            elements=[Element("LF 8\"", 0.0, 0.0, -0.175, 0, 0, "Omni", 360, 360, 104)],
            id="yam_hs8s"),
    ]
