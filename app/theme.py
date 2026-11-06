"""Uygulama görünümü: kurumsal renk paleti ve Qt stil sayfası."""
from PySide6.QtGui import QColor, QFont, QIcon, QPalette
from PySide6.QtWidgets import QApplication

from .paths import resource_dir

# Palet
SIDEBAR, SIDEBAR_HOVER, SIDEBAR_TEXT, SIDEBAR_MUTED = "#0F2744", "#1A3A5F", "#C3CFDE", "#6E85A3"
PRIMARY, PRIMARY_HOVER, PRIMARY_LIGHT = "#1B6FD8", "#155DB8", "#E7F0FC"
SUCCESS, SUCCESS_HOVER, SUCCESS_LIGHT = "#12A150", "#0E8743", "#E3F6EB"
WARNING, WARNING_TEXT, WARNING_LIGHT = "#E8A317", "#A16F00", "#FDF3DC"
DANGER, DANGER_HOVER, DANGER_LIGHT = "#D92D52", "#B8234A", "#FCE8ED"
INFO, INFO_HOVER, INFO_LIGHT = "#0E9AA7", "#0B7F8A", "#E0F4F6"
BG, SURFACE, BORDER, TEXT, MUTED = "#F4F6FA", "#FFFFFF", "#E4E8EF", "#1C2434", "#6B7686"

# Metin ve skor renkleri (uyarı rengi metinde okunabilir koyu tonuyla)
ACCENT, GOOD, WARN, BAD = PRIMARY, SUCCESS, WARNING_TEXT, DANGER

_ICONS = (resource_dir() / "icons").as_posix()

QSS = f"""
QWidget {{ font-family: 'Segoe UI'; font-size: 10pt; color: {TEXT}; }}
QMainWindow, QDialog, QStackedWidget#pages, QWidget#page {{ background: {BG}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

QFrame#sidebar {{ background: {SIDEBAR}; border: none; }}
QLabel#brand {{ color: white; font-size: 13pt; font-weight: 600; }}
QLabel#navGroup {{ color: {SIDEBAR_MUTED}; font-size: 8pt; font-weight: 600; }}
QLabel#sidebarNote {{ color: {SIDEBAR_MUTED}; font-size: 8.5pt; }}
QPushButton[nav="true"] {{ background: transparent; color: {SIDEBAR_TEXT}; border: none; border-radius: 6px;
    padding: 9px 12px; text-align: left; font-weight: 500; }}
QPushButton[nav="true"]:hover {{ background: {SIDEBAR_HOVER}; color: white; }}
QPushButton[nav="true"]:checked {{ background: {PRIMARY}; color: white; font-weight: 600; }}
QPushButton[nav="true"]:disabled {{ color: #51657F; background: transparent; }}

QFrame#topbar {{ background: {SURFACE}; border: none; border-bottom: 1px solid {BORDER}; }}
QLabel#pageTitle {{ font-size: 14pt; font-weight: 600; }}

QFrame#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
QLabel#cardHeading {{ font-size: 11pt; font-weight: 600; }}
QFrame#cardRule {{ background: {BORDER}; border: none; max-height: 1px; min-height: 1px; }}
QFrame#statTile {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
QLabel#statTitle {{ color: {MUTED}; font-size: 9pt; font-weight: 500; }}
QLabel#statValue {{ font-size: 20pt; font-weight: 600; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#fieldLabel {{ font-weight: 500; }}

QLabel[badge="success"] {{ background: {SUCCESS_LIGHT}; color: {SUCCESS}; }}
QLabel[badge="warning"] {{ background: {WARNING_LIGHT}; color: {WARNING_TEXT}; }}
QLabel[badge="danger"] {{ background: {DANGER_LIGHT}; color: {DANGER}; }}
QLabel[badge="info"] {{ background: {INFO_LIGHT}; color: {INFO_HOVER}; }}
QLabel[badge="muted"] {{ background: {BG}; color: {MUTED}; }}
QLabel[badge] {{ border-radius: 4px; padding: 3px 9px; font-size: 9pt; font-weight: 600; }}

QPushButton {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 6px; padding: 7px 14px; font-weight: 500; }}
QPushButton:hover {{ border-color: {PRIMARY}; color: {PRIMARY}; }}
QPushButton:disabled {{ color: #A0A8B6; background: #F0F2F6; border-color: #E5E9F0; }}
QPushButton[variant="primary"] {{ background: {PRIMARY}; border-color: {PRIMARY}; color: white; font-weight: 600; }}
QPushButton[variant="primary"]:hover {{ background: {PRIMARY_HOVER}; border-color: {PRIMARY_HOVER}; color: white; }}
QPushButton[variant="success"] {{ background: {SUCCESS}; border-color: {SUCCESS}; color: white; font-weight: 600; }}
QPushButton[variant="success"]:hover {{ background: {SUCCESS_HOVER}; border-color: {SUCCESS_HOVER}; color: white; }}
QPushButton[variant="danger"] {{ background: {DANGER}; border-color: {DANGER}; color: white; font-weight: 600; }}
QPushButton[variant="danger"]:hover {{ background: {DANGER_HOVER}; border-color: {DANGER_HOVER}; color: white; }}
QPushButton[variant="info"] {{ background: {INFO}; border-color: {INFO}; color: white; font-weight: 600; }}
QPushButton[variant="info"]:hover {{ background: {INFO_HOVER}; border-color: {INFO_HOVER}; color: white; }}
QPushButton[variant="light"] {{ background: {PRIMARY_LIGHT}; border-color: {PRIMARY_LIGHT}; color: {PRIMARY}; }}
QPushButton[variant="light"]:hover {{ background: #D5E5FA; border-color: #D5E5FA; color: {PRIMARY_HOVER}; }}
QPushButton[variant="primary"]:disabled, QPushButton[variant="success"]:disabled,
QPushButton[variant="danger"]:disabled, QPushButton[variant="info"]:disabled,
QPushButton[variant="light"]:disabled {{ background: #E6E9EF; border-color: #E6E9EF; color: #A0A8B6; }}
QPushButton[variant="ghost"], QPushButton[variant="ghost-danger"] {{ background: transparent; border: none; padding: 5px; }}
QPushButton[variant="ghost"]:hover {{ background: {PRIMARY_LIGHT}; }}
QPushButton[variant="ghost-danger"]:hover {{ background: {DANGER_LIGHT}; }}
QPushButton[variant="link"] {{ background: transparent; border: none; padding: 2px; text-align: left; font-weight: 600; }}
QPushButton[variant="link"]:hover {{ color: {PRIMARY}; }}
QPushButton[pager="true"] {{ background: {SURFACE}; border: 1px solid {BORDER}; padding: 4px 9px; min-width: 14px; font-weight: 500; }}
QPushButton[pager="true"]:hover {{ border-color: {PRIMARY}; color: {PRIMARY}; }}
QPushButton[pager="true"]:checked {{ background: {PRIMARY}; border-color: {PRIMARY}; color: white; font-weight: 600; }}
QPushButton[pager="true"]:disabled {{ background: {BG}; }}

QLineEdit, QPlainTextEdit, QTextBrowser, QComboBox, QSpinBox, QKeySequenceEdit {{
    background: {SURFACE}; border: 1px solid #D5DCE7; border-radius: 6px; padding: 6px 9px;
    selection-background-color: {PRIMARY}; selection-color: white; }}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {PRIMARY}; }}
QLineEdit:disabled, QComboBox:disabled {{ background: #F0F2F6; color: #A0A8B6; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url("{_ICONS}/chevron-down.svg"); width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{ background: {SURFACE}; border: 1px solid {BORDER}; outline: none;
    selection-background-color: {PRIMARY_LIGHT}; selection-color: {TEXT}; }}
QSpinBox::up-button, QSpinBox::down-button {{ border: none; width: 20px; }}
QSpinBox::up-arrow {{ image: url("{_ICONS}/chevron-up.svg"); width: 12px; height: 12px; }}
QSpinBox::down-arrow {{ image: url("{_ICONS}/chevron-down.svg"); width: 12px; height: 12px; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator, QTableView::indicator {{ width: 15px; height: 15px; border: 1px solid #C5CDD9; border-radius: 4px; background: white; }}
QCheckBox::indicator:checked, QTableView::indicator:checked {{ background: {PRIMARY}; border-color: {PRIMARY};
    image: url("{_ICONS}/check-white.svg"); }}

QTableWidget, QTableView {{ background: {SURFACE}; alternate-background-color: #F1F5FB; color: {TEXT}; font-size: 10.5pt;
    border: 1px solid #CBD3DF; border-radius: 6px; gridline-color: #D5DCE7;
    selection-background-color: #D5E5FA; selection-color: {TEXT}; outline: none; }}
QTableWidget::item, QTableView::item {{ padding-left: 10px; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: #E6ECF4; color: {TEXT}; font-size: 9.5pt; font-weight: 600; padding: 9px 12px;
    border: none; border-right: 1px solid #CBD3DF; border-bottom: 1px solid #CBD3DF; }}
QHeaderView::section:hover {{ background: #DCE4EE; }}
QHeaderView::up-arrow {{ image: url("{_ICONS}/chevron-up.svg"); width: 12px; height: 12px; }}
QHeaderView::down-arrow {{ image: url("{_ICONS}/chevron-down.svg"); width: 12px; height: 12px; }}
QTableCornerButton::section {{ background: #E6ECF4; border: none; }}

QTabWidget::pane {{ border: none; background: transparent; top: 0; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{ padding: 8px 16px; margin-right: 4px; border: none; color: {MUTED}; background: transparent; font-weight: 500; }}
QTabBar::tab:hover {{ color: {PRIMARY}; }}
QTabBar::tab:selected {{ color: {PRIMARY}; border-bottom: 2px solid {PRIMARY}; font-weight: 600; }}

QProgressBar {{ border: none; background: #E8EDF5; border-radius: 3px; max-height: 6px; }}
QProgressBar::chunk {{ background: {PRIMARY}; border-radius: 3px; }}
QSplitter::handle {{ background: transparent; height: 10px; width: 10px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #CBD3DF; border-radius: 3px; min-height: 28px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #CBD3DF; border-radius: 3px; min-width: 28px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; border: none; width: 0; height: 0; }}
QMenu {{ background: {SURFACE}; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 7px 26px 7px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background: {PRIMARY_LIGHT}; color: {PRIMARY}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}
QToolTip {{ background: {SIDEBAR}; color: white; border: none; padding: 6px 8px; }}
"""


def app_icon() -> QIcon:
    from .ui.icons import icon
    return icon("logo", PRIMARY)


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = app.palette()
    pal.setColor(QPalette.Window, QColor(BG))
    pal.setColor(QPalette.Highlight, QColor(PRIMARY))
    app.setPalette(pal)
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(QSS)
    app.setWindowIcon(app_icon())


def grade_color(value: float, good: float = 0.9, warn: float = 0.75) -> str:
    return GOOD if value >= good else WARN if value >= warn else BAD
