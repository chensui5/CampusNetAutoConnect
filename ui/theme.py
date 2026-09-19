# -*- coding: utf-8 -*-
"""主题：Neumorphism（新拟物派）。

核心控件由 ui.neumorphism 自绘（双光源柔光），
这里只负责那些暂未自绘的部件（滚动条、菜单、下拉列表、对话框按钮）的 QSS，
保证整体仍是同一套同色系 + 同光源语言，不出现描边、渐变、直角。
"""

from __future__ import annotations

from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QApplication

from . import neumorphism as neu


def build_qss(p: dict) -> str:
    return f"""
    * {{
        font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
    }}
    QWidget {{
        color: {p['text']};
        font-size: 13px;
    }}
    QMainWindow, QDialog, QMessageBox, QFileDialog {{
        background-color: {p['bg']};
    }}
    QLabel, QCheckBox, QRadioButton, QSlider, QGroupBox {{
        background: transparent;
        border: none;
    }}
    QLabel[role="muted"] {{ color: {p['text2']}; }}
    QLabel[role="body"] {{ color: {p['text']}; }}
    QLabel[role="title"] {{ color: {p['accent']}; }}
    QLabel[role="plain"] {{ color: {p['text']}; }}
    QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {{
        background: transparent;
        border: none;
        color: {p['text']};
        selection-background-color: {p['accent']};
        selection-color: {p['accent_text']};
    }}
    QLineEdit {{
        padding: 5px 10px;
    }}
    /* 复合控件内部的编辑区必须彻底无边框，否则会露出默认的下边线 */
    QSpinBox QLineEdit, QComboBox QLineEdit, QAbstractSpinBox QLineEdit {{
        border: none;
        background: transparent;
        padding: 0px;
    }}
    QScrollArea {{
        background: transparent;
        border: none;
    }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollArea > QWidget > QScrollBar {{ background: transparent; }}
    QTextEdit, QPlainTextEdit {{
        padding: 8px 10px;
    }}
    /* 标准按钮（对话框等）；主界面按钮由 NeuButton 自绘 */
    QPushButton {{
        background-color: {p['surface2']};
        border: none;
        border-radius: 10px;
        padding: 7px 16px;
        color: {p['text']};
    }}
    QPushButton:hover {{ background-color: {p['hover']}; }}
    QPushButton:pressed {{ background-color: {p['accent']}; color: {p['accent_text']}; }}
    QPushButton:disabled {{ color: {p['text3']}; }}

    QTabWidget::pane {{ border: none; background: transparent; }}
    QTabBar {{ background: transparent; }}

    QScrollBar:vertical {{
        background: transparent; width: 12px; margin: 3px 2px 3px 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {p['shadow_dark']}; border-radius: 5px; min-height: 34px; margin: 0 2px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {p['accent']}; }}
    QScrollBar:horizontal {{
        background: transparent; height: 12px; margin: 2px 3px 2px 3px;
    }}
    QScrollBar::handle:horizontal {{
        background: {p['shadow_dark']}; border-radius: 5px; min-width: 34px; margin: 2px 0;
    }}
    QScrollBar::handle:horizontal:hover {{ background: {p['accent']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QMenu {{
        background-color: {p['surface2']};
        border: none;
        border-radius: 12px;
        padding: 7px;
    }}
    QMenu::item {{
        padding: 8px 22px 8px 16px;
        border-radius: 8px;
        color: {p['text']};
    }}
    QMenu::item:selected {{ background-color: {p['accent']}; color: {p['accent_text']}; }}
    QMenu::separator {{ height: 6px; background: transparent; }}

    QToolTip {{
        background-color: {p['surface2']};
        color: {p['text']};
        border: none;
        border-radius: 8px;
        padding: 6px 10px;
    }}

    QComboBox QAbstractItemView {{
        background-color: {p['surface2']};
        border: none;
        border-radius: 10px;
        padding: 5px;
        outline: none;
        color: {p['text']};
        selection-background-color: {p['accent']};
        selection-color: {p['accent_text']};
    }}
    QComboBox QAbstractItemView::item {{
        padding: 6px 10px;
        border-radius: 7px;
        min-height: 24px;
    }}
    QComboBox::drop-down {{ border: none; width: 0px; }}
    QComboBox::down-arrow {{ image: none; width: 0; height: 0; }}

    QSpinBox::up-button, QSpinBox::down-button {{ width: 0px; border: none; }}

    QSplitter::handle {{ background: transparent; }}
    QStatusBar {{ background: transparent; color: {p['text2']}; }}
    QStatusBar::item {{ border: none; }}
    """


def apply_theme(app: QApplication, mode: str) -> dict:
    """mode: light / dark / system。返回实际生效的调色板。"""
    if mode == "system":
        mode = detect_system_mode(app)
    p = neu.set_palette(mode)
    app.setStyleSheet(build_qss(p))

    pal = app.palette()
    pal.setColor(QPalette.Window, QColor(p["bg"]))
    pal.setColor(QPalette.WindowText, QColor(p["text"]))
    pal.setColor(QPalette.Base, QColor(p["surface"]))
    pal.setColor(QPalette.AlternateBase, QColor(p["surface2"]))
    pal.setColor(QPalette.Text, QColor(p["text"]))
    pal.setColor(QPalette.PlaceholderText, QColor(p["text3"]))
    pal.setColor(QPalette.Button, QColor(p["surface2"]))
    pal.setColor(QPalette.ButtonText, QColor(p["text"]))
    pal.setColor(QPalette.Highlight, QColor(p["accent"]))
    pal.setColor(QPalette.HighlightedText, QColor(p["accent_text"]))
    pal.setColor(QPalette.ToolTipBase, QColor(p["surface2"]))
    pal.setColor(QPalette.ToolTipText, QColor(p["text"]))
    app.setPalette(pal)

    out = dict(p)
    out["muted"] = p["text2"]
    return out


def detect_system_mode(app: QApplication) -> str:
    """读注册表判断系统是否深色模式。"""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return "light" if value else "dark"
    except Exception:
        try:
            return "dark" if app.palette().window().color().lightness() < 128 else "light"
        except Exception:
            return "dark"
