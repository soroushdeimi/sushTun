"""Dark theme palette and stylesheet, modelled on macOS dark mode."""

ACCENT = "#0a84ff"
OK = "#30d158"
WARN = "#ffb340"
ERR = "#ff453a"
MUTED = "#98989d"

TEXT = "#f5f5f7"
BG = "#1e1e20"
SURFACE = "#2a2a2d"
SUNKEN = "#18181a"
LINE = "#38383c"

_FONT = '"-apple-system", "SF Pro Text", "Inter", "Segoe UI", "Ubuntu", "Cantarell", sans-serif'
_MONO = '"SF Mono", "JetBrains Mono", "Cascadia Code", "Ubuntu Mono", "Consolas", monospace'

STYLESHEET = f"""
* {{
    font-family: {_FONT};
    font-size: 13px;
    color: {TEXT};
}}
QWidget {{ background: {BG}; }}
QMainWindow, QDialog {{ background: {BG}; }}

/* Frameless window: the frame paints the rounded body, the window stays clear. */
QMainWindow#Frameless {{ background: transparent; }}
QWidget#WindowFrame {{
    background: {BG}; border: 1px solid #45454a; border-radius: 12px;
}}
QWidget#WindowFrame[maximized="true"] {{ border: none; border-radius: 0; }}
/* Anything square that paints edge to edge would cover the rounded corners. */
QWidget#WindowBody, QWidget#TitleBar, #TitleBar QWidget {{ background: transparent; }}
QLabel#WindowTitle {{ background: transparent; font-weight: 600; color: {TEXT}; }}
QLabel#WindowTitle[inactive="true"] {{ color: #6e6e73; }}

QFrame#Card {{
    background: {SURFACE};
    border: 1px solid {LINE};
    border-radius: 12px;
}}
QFrame#Card QLabel {{ background: transparent; }}

QLabel#H1 {{ font-size: 17px; font-weight: 600; }}
QLabel#Muted {{ color: {MUTED}; }}
QLabel#Mono {{ font-family: {_MONO}; color: {MUTED}; }}

QLabel#PillOn {{
    background: rgba(48,209,88,0.16); color: {OK};
    border: 1px solid rgba(48,209,88,0.55); border-radius: 10px;
    padding: 3px 12px; font-weight: 600; font-size: 11px;
}}
QLabel#PillOff {{
    background: rgba(152,152,157,0.12); color: {MUTED};
    border: 1px solid {LINE}; border-radius: 10px;
    padding: 3px 12px; font-weight: 600; font-size: 11px;
}}

QPushButton {{
    background: #3a3a3d; border: 1px solid #48484c; border-radius: 7px;
    padding: 6px 14px;
}}
QPushButton:hover {{ background: #444448; }}
QPushButton:pressed {{ background: #303033; }}
QPushButton:checked {{
    background: rgba(10,132,255,0.22); border: 1px solid {ACCENT}; color: #d4e7ff;
}}
QPushButton:disabled {{ color: #5c5c61; background: #28282b; border-color: #313134; }}

QPushButton#Primary {{
    background: {ACCENT}; border: none; color: white; font-weight: 600;
    padding: 9px 18px; border-radius: 8px;
}}
QPushButton#Primary:hover {{ background: #2b95ff; }}
QPushButton#Primary:pressed {{ background: #0070e0; }}
QPushButton#Primary:disabled {{ background: #1f3d66; color: #7d8ea8; }}
QPushButton#Danger {{
    background: {ERR}; border: none; color: white; font-weight: 600;
    padding: 9px 18px; border-radius: 8px;
}}
QPushButton#Danger:hover {{ background: #ff5e55; }}
QPushButton#Danger:pressed {{ background: #e0352b; }}
QPushButton#Danger:disabled {{ background: #4a2624; color: #a07a77; }}

/* Same look as QPushButton, so a QToolButton (e.g. a split button with a
   dropdown menu) doesn't stand out from the QPushButtons next to it. */
QToolButton {{
    background: #3a3a3d; border: 1px solid #48484c; border-radius: 7px;
    padding: 6px 14px;
}}
QToolButton:hover {{ background: #444448; }}
QToolButton:pressed {{ background: #303033; }}
QToolButton:disabled {{ color: #5c5c61; background: #28282b; border-color: #313134; }}
QToolButton::menu-button {{ border: none; width: 18px; }}

QListWidget {{
    background: {SURFACE}; border: 1px solid {LINE}; border-radius: 10px; padding: 5px;
    outline: none;
}}
QListWidget::item {{ padding: 8px 10px; border-radius: 6px; }}
QListWidget::item:selected {{ background: {ACCENT}; color: white; }}
QListWidget::item:hover:!selected {{ background: #343437; }}

QTextEdit, QPlainTextEdit, QLineEdit, QComboBox, QSpinBox {{
    background: {SUNKEN}; border: 1px solid {LINE}; border-radius: 7px; padding: 6px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus {{
    border: 1px solid {ACCENT};
}}
QTextEdit#Log, QPlainTextEdit#Log {{ font-family: {_MONO}; font-size: 12px; }}

/* Tabs as a macOS segmented control. */
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{
    background: transparent; color: {MUTED}; padding: 5px 16px; margin: 0 4px 6px 0;
    border: 1px solid transparent; border-radius: 6px;
}}
QTabBar::tab:hover:!selected {{ color: {TEXT}; }}
QTabBar::tab:selected {{ background: #3a3a3d; border: 1px solid #48484c; color: {TEXT}; }}
QTabWidget::pane {{ border: none; }}

QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ width: 10px; }}
QSplitter::handle:vertical {{ height: 10px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: rgba(255,255,255,0.18); border-radius: 3px; min-height: 30px; margin: 0 2px;
}}
QScrollBar::handle:vertical:hover {{ background: rgba(255,255,255,0.32); }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{
    background: rgba(255,255,255,0.18); border-radius: 3px; min-width: 30px; margin: 2px 0;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QToolTip {{
    background: #2c2c2e; color: {TEXT}; border: 1px solid #45454a;
    border-radius: 6px; padding: 4px 8px;
}}

QMenu {{
    background: #2c2c2e; border: 1px solid #45454a; border-radius: 8px; padding: 5px;
}}
QMenu::item {{ padding: 5px 22px 5px 12px; border-radius: 5px; background: transparent; }}
QMenu::item:selected {{ background: {ACCENT}; color: white; }}
QMenu::separator {{ height: 1px; background: #45454a; margin: 4px 8px; }}
"""
