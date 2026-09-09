"""Explicit, neutral, end-to-end smoke test for source and packaged builds."""
from pathlib import Path
import json
import time
import traceback

from .online import ImageCache, discover_task, save_to_library
from .vision import VisionEngine
from .config import Paths
from .database import Database


def verify(paths, report_path):
    started = time.monotonic()
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    cache = ImageCache(report_path.parent / "online-smoke")
    class Progress:
        def emit(self, done, total, message):
            pass
    class Work:
        progress = Progress()
        def isInterruptionRequested(self): return False
    try:
        engine = VisionEngine(paths)
        # Never searches with user photos, metadata or filenames.
        terms = "mountain landscape photography"
        result = discover_task(cache, engine, terms, 1, 1280)(Work())
        rows = result["items"]
        if not rows:
            raise RuntimeError("The public image search did not return usable high-resolution previews.")
        cache.save_session(terms, rows)
        path = None
        for row in rows[:6]:
            try:
                path, width, height = cache.image(row["image_url"], original=True)
                break
            except Exception:
                continue
        if path is None:
            raise RuntimeError("None of the first six originals could be downloaded.")
        # Save to a disposable verification library, never the user's library.
        scratch = Paths(report_path.parent / "online-smoke" / "saved-library")
        scratch.initialize()
        db = Database(scratch.database)
        saved = save_to_library(path, row, scratch, db)
        scores, vector = engine.analyze([path])[0]
        db.save_analysis(saved["image_id"], scores, vector, engine.version)
        reference = db.get_image(saved["image_id"])
        class CachedProvider:
            def search(self, *_): return rows
        reranked = discover_task(cache, engine, terms, 1, 1280, reference=reference, provider=CachedProvider())(Work())
        report = {"ok": True, "query": terms, "candidates": result["candidates"], "matches": len(rows),
            "device": engine.device_name, "score_range": [round(rows[-1]["match_score"], 2), round(rows[0]["match_score"], 2)],
            "original_dimensions": [width, height], "original_path": path,
            "saved_with_source": bool(db.get_image(saved["image_id"])["web_sources"]),
            "reference_matches": len(reranked["items"]), "reference_top_score": round(reranked["items"][0]["match_score"], 2),
            "session_path": str(cache.root / "last-search.json"), "seconds": round(time.monotonic() - started, 2)}
    except Exception:
        report = {"ok": False, "error": traceback.format_exc()}
    report_path.write_text(json.dumps(report, indent=2), "utf-8")
    return 0 if report["ok"] else 1
