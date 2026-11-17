"""Thème sombre, minimaliste, sans arrondis."""
import numpy as np

BG = "#0c0d0f"
PANEL = "#131417"
FIELD = "#17191c"
BORDER = "#25282d"
TEXT = "#c8cbd0"
DIM = "#6a6f77"
ACCENT = "#ff7a1a"
SHAPE = "#8a9099"

ORDER_COLORS = ["#ffffff", "#3ec1ff", "#b06cff", "#ff3aa8", "#ffd23a", "#3affc8"]

QSS = f"""
* {{ border-radius: 0px; color: {TEXT}; font-size: 12px; outline: 0; }}
QMainWindow, QWidget {{ background: {BG}; }}
QToolTip {{ background: {PANEL}; border: 1px solid {BORDER}; color: {TEXT}; padding: 4px; }}
QDockWidget {{ titlebar-close-icon: none; }}
QDockWidget::title {{ background: {BG}; padding: 6px 8px; border-bottom: 1px solid {BORDER}; }}
QLabel#title {{ color: {DIM}; font-size: 10px; letter-spacing: 2px; padding: 4px 8px; background: {BG}; }}
QLabel#section {{ color: {DIM}; font-size: 10px; letter-spacing: 2px; padding-top: 10px; }}
QLabel#value {{ color: {ACCENT}; font-family: "JetBrains Mono", "DejaVu Sans Mono", monospace; }}
QLabel#info {{ color: {DIM}; }}
QLineEdit, QAbstractSpinBox, QComboBox {{
    background: {FIELD}; border: 1px solid {BORDER}; padding: 3px 6px; min-height: 18px;
    selection-background-color: {ACCENT}; selection-color: #000;
    font-family: "JetBrains Mono", "DejaVu Sans Mono", monospace;
}}
QLineEdit:focus, QAbstractSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QLineEdit:disabled, QAbstractSpinBox:disabled, QComboBox:disabled {{ color: {DIM}; background: {BG}; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 0px; border: none; }}
QComboBox::drop-down {{ border: none; width: 14px; }}
QComboBox::down-arrow {{ image: none; border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 5px solid {DIM}; width: 0; height: 0; margin-right: 6px; }}
QComboBox QAbstractItemView {{ background: {PANEL}; border: 1px solid {BORDER};
    selection-background-color: {ACCENT}; selection-color: #000; }}
QPushButton {{ background: {PANEL}; border: 1px solid {BORDER}; padding: 5px 10px; }}
QPushButton:hover {{ border-color: {ACCENT}; color: #fff; }}
QPushButton:pressed {{ background: {ACCENT}; color: #000; }}
QPushButton#primary {{ background: {ACCENT}; color: #000; border-color: {ACCENT}; }}
QPushButton#primary:hover {{ background: #ff9446; }}
QToolBar {{ background: {BG}; border: none; border-bottom: 1px solid {BORDER}; spacing: 0px; padding: 2px; }}
QToolBar::separator {{ background: {BORDER}; width: 1px; margin: 4px 6px; }}
QToolButton {{ background: transparent; border: 1px solid transparent; padding: 4px 9px; }}
QToolButton:hover {{ border-color: {BORDER}; color: #fff; }}
QToolButton:pressed {{ background: {ACCENT}; color: #000; }}
QTreeWidget, QTableWidget, QListWidget {{ background: {PANEL}; border: 1px solid {BORDER};
    gridline-color: {BORDER}; alternate-background-color: {FIELD}; }}
QTreeWidget::item, QListWidget::item {{ padding: 3px 2px; }}
QTreeWidget::item:selected, QTableWidget::item:selected, QListWidget::item:selected {{
    background: {ACCENT}; color: #000; }}
QTreeWidget::branch {{ background: {PANEL}; }}
QHeaderView::section {{ background: {BG}; color: {DIM}; border: none; border-bottom: 1px solid {BORDER};
    border-right: 1px solid {BORDER}; padding: 4px 6px; font-size: 10px; }}
QTableCornerButton::section {{ background: {BG}; border: none; }}
QTabWidget::pane {{ border: none; border-top: 1px solid {BORDER}; }}
QTabBar::tab {{ background: {BG}; color: {DIM}; border: none; border-bottom: 2px solid transparent;
    padding: 7px 12px; font-size: 11px; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom-color: {ACCENT}; }}
QTabBar::tab:hover {{ color: #fff; }}
QCheckBox {{ spacing: 7px; }}
QCheckBox::indicator {{ width: 11px; height: 11px; border: 1px solid {DIM}; background: {BG}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QScrollArea {{ border: none; }}
QScrollBar:vertical {{ background: {BG}; width: 8px; margin: 0; }}
QScrollBar:horizontal {{ background: {BG}; height: 8px; margin: 0; }}
QScrollBar::handle {{ background: {BORDER}; min-height: 24px; min-width: 24px; }}
QScrollBar::handle:hover {{ background: {DIM}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QSplitter::handle {{ background: {BORDER}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QStatusBar {{ background: {BG}; color: {DIM}; border-top: 1px solid {BORDER}; }}
QMenu {{ background: {PANEL}; border: 1px solid {BORDER}; }}
QMenu::item:selected {{ background: {ACCENT}; color: #000; }}
"""

# palette SPL : bleu nuit -> cyan -> vert -> jaune -> orange -> rouge
_POS = np.array([0.0, 0.2, 0.4, 0.6, 0.8, 1.0])
_COL = np.array([(25, 35, 110), (30, 110, 210), (40, 200, 170),
                 (190, 230, 60), (255, 160, 30), (240, 50, 40)], float)


def colorize(norm, alpha=235):
    norm = np.asarray(norm, float)
    bad = ~np.isfinite(norm)
    n = np.clip(np.where(bad, 0.0, norm), 0, 1)
    out = np.empty(n.shape + (4,), np.uint8)
    for c in range(3):
        out[..., c] = np.interp(n, _POS, _COL[:, c]).astype(np.uint8)
    out[..., 3] = np.where(bad, 0, alpha)
    return out


def hex_rgba(h, a=1.0):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)) + (a,)
