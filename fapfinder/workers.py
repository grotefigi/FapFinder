from __future__ import annotations

import time
import traceback

from PySide6.QtCore import QThread, Signal

from .importer import discover_images, import_one
from .vision import Cancelled, download_model


class Task(QThread):
    progress = Signal(int, int, str)
    result = Signal(object)
    failed = Signal(str)

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function

    def run(self):
        try:
            self.result.emit(self.function(self))
        except Cancelled as error:
            self.result.emit({"message": str(error), "cancelled": True})
        except Exception as error:
            traceback.print_exc()
            self.failed.emit(str(error))

    def stop(self):
        self.requestInterruption()


def import_task(selected_paths, paths, db, copy):
    def run(task):
        task.progress.emit(0, 0, "Finding images…")
        files = list(discover_images(selected_paths, task.isInterruptionRequested))
        summary = {"imported": 0, "duplicate": 0, "errors": [], "cancelled": False}
        last_emit = 0
        for index, path in enumerate(files):
            if task.isInterruptionRequested():
                summary["cancelled"] = True
                break
            try:
                summary[import_one(path, paths, db, copy)] += 1
            except Exception as error:
                summary["errors"].append(f"{path.name}: {error}")
            now = time.monotonic()
            if now - last_emit > .1 or index == len(files) - 1:
                task.progress.emit(index + 1, len(files), f"Importing {index + 1:,} of {len(files):,} · {path.name}")
                last_emit = now
        return summary
    return run


def analyze_task(db, engine, batch_size):
    def run(task):
        engine.load(lambda message: task.progress.emit(0, 0, message))
        rows = db.pending(include_errors=True)
        total = len(rows)
        completed, errors, batch = 0, [], max(1, min(int(batch_size), 32))
        started = time.monotonic()
        while completed < total:
            if task.isInterruptionRequested():
                break
            chunk = rows[completed:completed + batch]
            try:
                results = engine.analyze([r["path"] for r in chunk])
                for row, (scores, vector) in zip(chunk, results):
                    db.save_analysis(row["id"], scores, vector, engine.version)
                completed += len(chunk)
            except Exception as error:
                if "out of memory" in str(error).lower() and batch > 1:
                    engine.recover_memory()
                    batch = max(1, batch // 2)
                    continue
                # Isolate corrupt / missing files so a single failure does not lose the batch.
                for row in chunk:
                    if task.isInterruptionRequested():
                        break
                    try:
                        scores, vector = engine.analyze([row["path"]])[0]
                        db.save_analysis(row["id"], scores, vector, engine.version)
                    except Exception as individual:
                        db.mark_error(row["id"], individual)
                        errors.append(f"Image {row['id']}: {individual}")
                    completed += 1
            elapsed = max(time.monotonic() - started, .01)
            rate = completed / elapsed
            eta = max(0, round((total - completed) / max(rate, .01)))
            task.progress.emit(completed, total, f"Analyzed {completed:,} / {total:,} · {rate:.1f} images/s · about {eta}s left")
        return {"analyzed": completed - len(errors), "errors": errors, "cancelled": task.isInterruptionRequested(), "device": engine.device_name}
    return run


def download_task(paths):
    def run(task):
        last_emit = 0
        def progress(done, total, name):
            nonlocal last_emit
            now = time.monotonic()
            if now - last_emit > .15 or done == total:
                task.progress.emit(int(done / 1024), int(total / 1024), f"Downloading model · {done / 1e9:.2f} / {total / 1e9:.2f} GB")
                last_emit = now
        download_model(paths, progress, task.isInterruptionRequested)
        return {"message": "Model installed. Analysis is ready to run offline."}
    return run
