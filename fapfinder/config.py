from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

MODEL_ID = "google/siglip2-base-patch16-224"
# Pin the reviewed checkpoint; model code is never downloaded or executed.
MODEL_REVISION = "75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


@dataclass(frozen=True)
class Paths:
    root: Path

    @classmethod
    def default(cls):
        app_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
        return cls(Path(os.environ.get("FAPFINDER_DATA", app_dir / "data")).resolve())

    @property
    def database(self):
        return self.root / "library.sqlite3"

    @property
    def thumbnails(self):
        return self.root / "thumbnails"

    @property
    def originals(self):
        return self.root / "originals"

    @property
    def model(self):
        return self.root / "models" / "siglip2-base-patch16-224"

    def initialize(self):
        for path in (self.root, self.thumbnails, self.originals, self.model):
            path.mkdir(parents=True, exist_ok=True)

    def preferences(self):
        defaults = {"theme": "dark", "copy_originals": True, "auto_analyze": True, "device": "auto", "batch_size": 16}
        try:
            saved = json.loads((self.root / "preferences.json").read_text("utf-8"))
            defaults.update({k: v for k, v in saved.items() if k in defaults})
        except (OSError, ValueError, AttributeError):
            pass
        return defaults

    def save_preferences(self, value):
        target = self.root / "preferences.json"
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(value, indent=2), "utf-8")
        temp.replace(target)


def offline_environment():
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["DO_NOT_TRACK"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"


def model_ready(paths: Paths):
    needed = ("config.json", "model.safetensors", "preprocessor_config.json", "tokenizer.json", "tokenizer_config.json", "READY.json")
    return all((paths.model / name).is_file() for name in needed)
