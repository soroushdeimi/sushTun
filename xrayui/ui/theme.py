"""Dark theme palette and stylesheet."""

ACCENT = "#3d7eff"
OK = "#2dd4bf"
WARN = "#f5b74e"
ERR = "#ff6b6b"
MUTED = "#8b93a1"

STYLESHEET = f"""
* {{
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
    color: #e6e9ef;
}}
QWidget {{ background: #0f1216; }}
QMainWindow, QDialog {{ background: #0f1216; }}

QFrame#Card {{
    background: #171b21;
    border: 1px solid #232833;
    border-radius: 12px;
}}

QLabel#H1 {{ font-size: 18px; font-weight: 600; }}
QLabel#Muted {{ color: {MUTED}; }}
QLabel#Mono {{ font-family: "Cascadia Code", "Consolas", monospace; color: {MUTED}; }}

QLabel#PillOn {{
    background: rgba(45,212,191,0.15); color: {OK};
    border: 1px solid {OK}; border-radius: 10px; padding: 3px 12px; font-weight: 600;
}}
QLabel#PillOff {{
    background: rgba(139,147,161,0.12); color: {MUTED};
    border: 1px solid #3a414d; border-radius: 10px; padding: 3px 12px; font-weight: 600;
}}

QPushButton {{
    background: #222834; border: 1px solid #2c3341; border-radius: 8px;
    padding: 8px 14px;
}}
QPushButton:hover {{ background: #2a3140; }}
QPushButton:disabled {{ color: #5a616d; background: #1a1e25; }}

QPushButton#Primary {{
    background: {ACCENT}; border: none; color: white; font-weight: 600;
    padding: 11px 18px; border-radius: 10px;
}}
QPushButton#Primary:hover {{ background: #4f8bff; }}
QPushButton#Danger {{ background: {ERR}; border: none; color: white; font-weight: 600; }}
QPushButton#Danger:hover {{ background: #ff8080; }}

QListWidget {{
    background: #131720; border: 1px solid #232833; border-radius: 10px; padding: 4px;
}}
QListWidget::item {{ padding: 9px 10px; border-radius: 8px; }}
QListWidget::item:selected {{ background: {ACCENT}; color: white; }}
QListWidget::item:hover {{ background: #1d2430; }}

QTextEdit, QPlainTextEdit, QLineEdit, QComboBox, QSpinBox {{
    background: #0c0f14; border: 1px solid #232833; border-radius: 8px; padding: 6px;
    selection-background-color: {ACCENT};
}}
QPlainTextEdit#Log {{ font-family: "Cascadia Code", "Consolas", monospace; font-size: 12px; }}

QTabBar::tab {{
    background: transparent; padding: 8px 16px; color: {MUTED};
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{ color: #e6e9ef; border-bottom: 2px solid {ACCENT}; }}
QTabWidget::pane {{ border: none; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2c3341; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""
