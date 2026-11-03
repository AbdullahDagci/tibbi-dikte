"""Uygulama genel görünümü: Fusion + açık, sade, yuvarlak köşeli tema."""
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

ACCENT = "#2F6FED"
GOOD, WARN, BAD = "#16A34A", "#D97706", "#DC2626"

QSS = f"""
QWidget {{ font-family: 'Segoe UI'; font-size: 10pt; color: #1F2430; }}
QDialog, QMainWindow {{ background: #F5F7FB; }}
QTabWidget::pane {{ border: 1px solid #E3E8F0; border-radius: 10px; background: white; top: -1px; }}
QTabBar::tab {{ padding: 8px 18px; margin-right: 4px; border: none; color: #5B6577; background: transparent; }}
QTabBar::tab:selected {{ color: {ACCENT}; border-bottom: 2px solid {ACCENT}; font-weight: 600; }}
QPushButton {{ background: white; border: 1px solid #D5DCE7; border-radius: 8px; padding: 7px 16px; }}
QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
QPushButton:disabled {{ color: #A0A8B6; border-color: #E5E9F0; }}
QPushButton#primary {{ background: {ACCENT}; color: white; border: none; font-weight: 600; }}
QPushButton#primary:hover {{ background: #255FD6; color: white; }}
QPushButton#primary:disabled {{ background: #A9C0F5; }}
QPushButton#danger {{ background: #FF5A5F; color: white; border: none; font-weight: 600; }}
QLineEdit, QPlainTextEdit, QTextBrowser, QComboBox, QSpinBox, QKeySequenceEdit {{
    background: white; border: 1px solid #D5DCE7; border-radius: 8px; padding: 6px; selection-background-color: {ACCENT}; }}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QFrame#card {{ background: white; border: 1px solid #E3E8F0; border-radius: 12px; }}
QLabel#cardValue {{ font-size: 20pt; font-weight: 600; }}
QLabel#cardTitle {{ color: #6B7486; font-size: 8.5pt; letter-spacing: 0.5px; }}
QLabel#h1 {{ font-size: 15pt; font-weight: 600; }}
QLabel#muted {{ color: #6B7486; }}
QProgressBar {{ border: none; background: #E8EDF5; border-radius: 3px; max-height: 6px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
QCheckBox {{ spacing: 8px; }}
"""


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = app.palette()
    pal.setColor(QPalette.Window, QColor("#F5F7FB"))
    pal.setColor(QPalette.Highlight, QColor(ACCENT))
    app.setPalette(pal)
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(QSS)


def grade_color(value: float, good: float = 0.9, warn: float = 0.75) -> str:
    return GOOD if value >= good else WARN if value >= warn else BAD
