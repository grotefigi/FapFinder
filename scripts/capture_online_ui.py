"""Render only neutral public smoke-test images; never opens the user's library."""
import json
import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
os.chdir(root)

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from fapfinder.config import Paths
from fapfinder.window import MainWindow
from fapfinder.online_ui import PhotoViewer

report = json.loads((root / "verification/online-source-report.json").read_text("utf-8"))
session = json.loads(Path(report["session_path"]).read_text("utf-8"))
app = QApplication([])
for name in ("segoeui.ttf", "seguisb.ttf", "segoeuib.ttf", "seguisym.ttf"):
    QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name))
app.setStyle("Fusion")
window = MainWindow(Paths(root / "verification/ui-online"))
window.resize(1480, 940)
page = window.online_page
page.model.replace(session["items"])
page.terms.setText(session["terms"])
page.stack.setCurrentWidget(page.gallery)
page.summary.setText(f"{len(session['items'])} photos · Compared locally · Dimensions reported by search")
page.more_button.setEnabled(True)
window.show_online()
window.show()

def dark():
    window.set_theme("dark")
    window.grab().save(str(root / "verification/online-dark.png"))
    window.set_theme("light")
    QTimer.singleShot(350, light)

def light():
    window.grab().save(str(root / "verification/online-light.png"))
    window.resize(1060, 680)
    QTimer.singleShot(350, compact)

def compact():
    window.grab().save(str(root / "verification/online-compact.png"))
    window.set_theme("dark")
    class Cache:
        def image(self, url, original, stop):
            return report["original_path"], *report["original_dimensions"]
        def prune(self): pass
    viewer = PhotoViewer(session["items"], 0, Cache(), window)
    viewer.resize(1480, 940)
    viewer.show()
    def capture():
        viewer.grab().save(str(root / "verification/online-viewer.png"))
        viewer.close()
        window.close()
        app.quit()
    QTimer.singleShot(700, capture)
QTimer.singleShot(700, dark)
app.exec()
