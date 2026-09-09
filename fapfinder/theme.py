from PySide6.QtGui import QColor, QFont, QPalette

THEMES = {
    "dark": dict(bg="#111315", panel="#181b1e", surface="#202428", hover="#292e33", border="#30363b", text="#edf0ed", muted="#9ba59f", accent="#b5e3bf", accent_text="#152c1b", selection="#324b3a"),
    "light": dict(bg="#f6f7f4", panel="#ffffff", surface="#eef1eb", hover="#e3e9df", border="#d9dfd5", text="#202920", muted="#657160", accent="#315f3b", accent_text="#ffffff", selection="#deebdd"),
}


def apply_theme(app, name):
    c = THEMES.get(name, THEMES["dark"])
    palette = QPalette()
    for role, key in ((QPalette.Window, "bg"), (QPalette.WindowText, "text"), (QPalette.Base, "panel"),
                      (QPalette.AlternateBase, "surface"), (QPalette.Text, "text"), (QPalette.Button, "surface"),
                      (QPalette.ButtonText, "text"), (QPalette.Highlight, "selection"), (QPalette.HighlightedText, "text"),
                      (QPalette.ToolTipBase, "surface"), (QPalette.ToolTipText, "text"), (QPalette.PlaceholderText, "muted")):
        palette.setColor(role, QColor(c[key]))
    app.setPalette(palette)
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet("""
        QWidget { color: %(text)s; font-family: 'Segoe UI'; font-size: 13px; }
        QMainWindow, QDialog, QWidget#page { background: %(bg)s; }
        QFrame#sidebar, QFrame#filters, QFrame#settingsCard { background: %(panel)s; border: 1px solid %(border)s; border-radius: 12px; }
        QFrame#sidebar { border: 0; border-right: 1px solid %(border)s; border-radius: 0; }
        QLabel { background: transparent; }
        QLabel#title { font-size: 30px; font-weight: 650; letter-spacing: -1px; }
        QLabel#sectionTitle { font-size: 19px; font-weight: 600; }
        QLabel#brand { font-size: 22px; font-weight: 700; letter-spacing: -0.6px; }
        QLabel#eyebrow { font-size: 10px; font-weight: 700; letter-spacing: 1.5px; color: %(muted)s; }
        QLabel#muted { color: %(muted)s; }
        QLabel#badge { color: %(accent)s; background: %(selection)s; border-radius: 10px; padding: 5px 10px; font-size: 11px; }
        QLabel#error { color: #e69587; }
        QPushButton { background: %(surface)s; border: 1px solid %(border)s; border-radius: 8px; padding: 9px 13px; font-weight: 500; }
        QPushButton:hover { background: %(hover)s; }
        QPushButton:pressed { background: %(selection)s; }
        QPushButton:disabled { color: %(muted)s; background: %(panel)s; }
        QPushButton:focus { border: 1px solid %(accent)s; }
        QPushButton#primary { background: %(accent)s; color: %(accent_text)s; border: 1px solid %(accent)s; font-weight: 650; }
        QPushButton#primary:hover { border: 1px solid %(text)s; }
        QPushButton#nav { border: 0; background: transparent; text-align: left; padding: 12px 15px; }
        QPushButton#nav:checked { background: %(selection)s; color: %(accent)s; }
        QPushButton#nav:hover { background: %(hover)s; }
        QPushButton#quiet { border: 0; background: transparent; color: %(muted)s; padding: 6px; }
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit { background: %(surface)s; border: 1px solid %(border)s; border-radius: 7px; padding: 8px 10px; selection-background-color: %(selection)s; }
        QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus { border: 1px solid %(accent)s; }
        QComboBox::drop-down { border: 0; width: 23px; }
        QComboBox QAbstractItemView { background: %(surface)s; border: 1px solid %(border)s; selection-background-color: %(selection)s; padding: 4px; }
        QSlider { background: transparent; min-height: 20px; max-height: 20px; }
        QSlider::groove:horizontal { background: %(border)s; height: 4px; border: 0; border-radius: 2px; }
        QSlider::add-page:horizontal { background: %(border)s; border: 0; border-radius: 2px; }
        QSlider::sub-page:horizontal { background: %(accent)s; height: 4px; border-radius: 2px; }
        QSlider::handle:horizontal { background: %(accent)s; border: 2px solid %(panel)s; width: 13px; height: 13px; margin: -6px 0; border-radius: 8px; }
        QSlider::sub-page:horizontal:disabled { background: %(border)s; }
        QSlider::handle:horizontal:disabled { background: %(muted)s; }
        QCheckBox { spacing: 8px; padding: 5px 0; }
        QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid %(border)s; border-radius: 4px; background: %(surface)s; }
        QCheckBox::indicator:checked { background: %(accent)s; border-color: %(accent)s; image: none; }
        QProgressBar { border: 0; background: %(surface)s; border-radius: 3px; min-height: 5px; max-height: 5px; }
        QProgressBar::chunk { background: %(accent)s; border-radius: 3px; }
        QScrollArea, QScrollArea > QWidget > QWidget { border: 0; background: transparent; }
        QListView { background: transparent; border: 0; outline: 0; }
        QScrollBar:vertical { background: transparent; width: 9px; margin: 2px; }
        QScrollBar::handle:vertical { background: %(border)s; min-height: 32px; border-radius: 3px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
        QMenu { background: %(panel)s; border: 1px solid %(border)s; padding: 5px; }
        QMenu::item { padding: 8px 24px; border-radius: 5px; }
        QMenu::item:selected { background: %(selection)s; }
        QToolTip { background: %(surface)s; color: %(text)s; border: 1px solid %(border)s; padding: 6px; }
        QSplitter::handle { background: %(bg)s; }
    """ % c)
    return c
