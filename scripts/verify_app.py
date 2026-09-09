"""Offline integration and scale verification on explicitly synthetic fixtures."""
from __future__ import annotations

import json
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from PIL import Image, ImageDraw

from fapfinder.config import Paths
from fapfinder.database import Database
from fapfinder.importer import import_one
from fapfinder.search import SearchQuery, search
from fapfinder.vision import VisionEngine
from fapfinder.workers import analyze_task


def main():
    workspace = Path(__file__).resolve().parent.parent
    root = workspace / "verification"
    root.mkdir(exist_ok=True)
    paths = Paths(root / "scale-library")
    paths.initialize()
    db = Database(paths.database)
    sources = root / "synthetic-fixtures"
    sources.mkdir(exist_ok=True)
    count = 1500
    for i in range(count):
        target = sources / f"synthetic-{i:04}.png"
        if not target.exists():
            colors = [(40, 58, 76), (62, 81, 61), (139, 98, 70), (82, 74, 112), (61, 101, 106), (162, 139, 106)]
            image = Image.new("RGB", (160, 200), colors[i % len(colors)])
            draw = ImageDraw.Draw(image)
            draw.ellipse((40 + i % 11, 25, 113, 105), fill=(202, 182, 145))
            draw.polygon([(10, 200), (50, 90), (100, 90), (150, 200)], fill=(30 + i % 100, 60 + i % 70, 90 + i % 80))
            draw.text((12, 180), f"TEST {i:04}", fill="white")
            image.save(target)
    started = time.perf_counter()
    imported = sum(import_one(file, paths, db, copy=False) == "imported" for file in sources.glob("*.png"))
    import_seconds = time.perf_counter() - started
    # The fixture DB is separate from the user's empty library. Use the installed local model.
    engine = VisionEngine(Paths.default())
    attempted_network = []
    def deny_connection(*args, **kwargs):
        attempted_network.append("blocked")
        raise AssertionError("Analysis attempted a network connection")
    socket.socket.connect = deny_connection
    socket.socket.connect_ex = deny_connection
    socket.create_connection = deny_connection
    started = time.perf_counter()
    engine.load(print)
    load_seconds = time.perf_counter() - started
    import torch
    torch.cuda.reset_peak_memory_stats()
    class Progress:
        last = -1
        def emit(self, done, total, text):
            bucket = done // 250
            if bucket != self.last:
                print(text, flush=True)
                self.last = bucket
    class Task:
        progress = Progress()
        def isInterruptionRequested(self):
            return False
    started = time.perf_counter()
    result = analyze_task(db, engine, 16)(Task())
    analysis_seconds = time.perf_counter() - started
    assert not result["errors"], result["errors"][:3]
    assert db.stats()["ready"] == count
    started = time.perf_counter()
    matches = search(db, SearchQuery(weights={("hair_color", "blonde"): .75, ("build", "slim"): .25}))
    trait_search_ms = (time.perf_counter() - started) * 1000
    assert len(matches) == count
    assert all(matches[i]["match_score"] >= matches[i + 1]["match_score"] for i in range(len(matches) - 1))
    started = time.perf_counter()
    vector = engine.encode_text("a portrait in warm light")
    text_matches = search(db, SearchQuery(text="a portrait in warm light"), vector, engine.version)
    text_search_ms = (time.perf_counter() - started) * 1000
    assert len(text_matches) == count
    assert len(search(db, SearchQuery(reference_id=text_matches[0]["id"]))) == count - 1
    assert attempted_network == []
    report = dict(fixture_count=count, fixture_type="Synthetic illustrations; this measures throughput, not human-trait accuracy.",
        newly_imported=imported, import_seconds=round(import_seconds, 3), model_load_seconds=round(load_seconds, 3),
        newly_analyzed=result["analyzed"], analysis_seconds=round(analysis_seconds, 3),
        images_per_second=round(result["analyzed"] / max(analysis_seconds, .001), 2),
        trait_search_ms=round(trait_search_ms, 2), text_search_ms=round(text_search_ms, 2),
        gpu=engine.device_name, peak_gpu_allocated_mb=round(torch.cuda.max_memory_allocated() / 1024**2, 1),
        peak_gpu_reserved_mb=round(torch.cuda.max_memory_reserved() / 1024**2, 1),
        network_connections_attempted=len(attempted_network), model_version=engine.version,
        model_class=type(engine.model).__name__, processor_class=type(engine.processor).__name__)
    (root / "benchmark.json").write_text(json.dumps(report, indent=2), "utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
