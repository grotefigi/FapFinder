from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="FapFinder local image library")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--screenshot", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--download-model", action="store_true")
    parser.add_argument("--verify-engine", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--verify-report", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--verify-online", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    from fapfinder.config import Paths, offline_environment
    paths = Paths(args.data_dir.resolve()) if args.data_dir else Paths.default()
    paths.initialize()
    if args.download_model:
        from fapfinder.vision import download_model
        download_model(paths, lambda done, total, name: print(f"{done / max(total, 1):.0%} {name}", flush=True))
        return 0
    offline_environment()
    if args.verify_online:
        from fapfinder.online_verification import verify
        return verify(paths, args.verify_report or paths.root / "online-verification.json")
    if args.verify_engine:
        import json
        import socket
        import traceback
        import numpy as np
        report_path = args.verify_report or paths.root / "engine-verification.json"
        try:
            def deny(*_args, **_kwargs):
                raise AssertionError("Offline inference attempted network access")
            socket.socket.connect = deny
            socket.socket.connect_ex = deny
            socket.create_connection = deny
            from fapfinder.vision import VisionEngine
            engine = VisionEngine(paths)
            tags, vector = engine.analyze([args.verify_engine])[0]
            text = engine.encode_text("a portrait")
            report = {"ok": True, "device": engine.device_name, "dimensions": len(vector),
                "traits": len(tags), "finite": bool(np.isfinite(vector).all()), "text_dimensions": len(text),
                "version": engine.version, "network_blocked": True}
        except Exception:
            report = {"ok": False, "error": traceback.format_exc()}
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), "utf-8")
        return 0 if report["ok"] else 1
    from logging.handlers import RotatingFileHandler
    log = RotatingFileHandler(paths.root / "app.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    logging.basicConfig(handlers=[log], level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
    from PySide6.QtCore import QLockFile, QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    app.setApplicationName("FapFinder")
    app.setOrganizationName("FapFinder")
    app.setApplicationVersion("1.2.0")
    icon_path = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "assets" / "app.ico"
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    lock = QLockFile(str(paths.root / "app.lock"))
    if not lock.tryLock(0):
        QMessageBox.information(None, "FapFinder is already open", "This library is already open in another FapFinder window.")
        return 0
    def handle_error(kind, error, trace):
        logging.error("Unhandled application error", exc_info=(kind, error, trace))
        QMessageBox.warning(None, "FapFinder", f"Something went wrong: {error}\nDetails were saved in the local app.log file.")
    sys.excepthook = handle_error
    from fapfinder.window import MainWindow
    window = MainWindow(paths)
    window.show()
    if args.screenshot:
        def capture():
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            window.grab().save(str(args.screenshot))
            window.close()
        QTimer.singleShot(1000, capture)
    result = app.exec()
    lock.unlock()
    return result


if __name__ == "__main__":
    from multiprocessing import freeze_support
    freeze_support()
    raise SystemExit(main())
