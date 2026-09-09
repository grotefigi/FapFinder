import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from fapfinder.config import Paths
from fapfinder.window import MainWindow
from fapfinder.editor import TagEditor

root = Path(__file__).resolve().parent.parent
app = QApplication([])
app.setStyle("Fusion")
window = MainWindow(Paths(root / "verification" / "scale-library"))
window.resize(1480, 940)
window.show()
steps = []

def gallery():
    window.set_theme("dark")
    window.subtitle.setText("QA preview · 1,500 synthetic test fixtures · not your personal library")

def matches():
    combo, slider = window.trait_controls["hair_color"]
    combo.setCurrentIndex(combo.findData("blonde"))
    window.run_search()

def settings():
    window.show_settings()

def light():
    window.change_view("all")
    window.clear_search()
    window.set_theme("light")

steps = [(gallery, "gallery-dark"), (matches, "matches-dark"), (settings, "settings-dark"), (light, "gallery-light")]

def next_step():
    if not steps:
        window.close()
        app.quit()
        return
    action, name = steps.pop(0)
    action()
    def capture():
        window.grab().save(str(root / "verification" / f"{name}.png"))
        QTimer.singleShot(50, next_step)
    QTimer.singleShot(400, capture)

QTimer.singleShot(400, next_step)
app.exec()
