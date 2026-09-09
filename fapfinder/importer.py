from __future__ import annotations

import hashlib
import os
import shutil
import warnings
from pathlib import Path

from PIL import Image, ImageOps

from .config import IMAGE_EXTENSIONS, Paths
from .database import Database

Image.MAX_IMAGE_PIXELS = 70_000_000


def discover_images(paths, stop=lambda: False):
    seen = set()
    for given in paths:
        path = Path(given).resolve()
        if path.is_dir():
            iterator = (Path(root) / name for root, dirs, files in os.walk(path, followlinks=False) for name in files)
        else:
            iterator = iter([path])
        for item in iterator:
            if stop():
                return
            if item.suffix.lower() not in IMAGE_EXTENSIONS or item.is_symlink():
                continue
            key = os.path.normcase(str(item))
            if key not in seen:
                seen.add(key)
                yield item


def open_image(path):
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(path) as source:
            source.seek(0)
            corrected = ImageOps.exif_transpose(source)
            if corrected.mode in ("RGBA", "LA") or "transparency" in corrected.info:
                rgba = corrected.convert("RGBA")
                background = Image.new("RGBA", rgba.size, "white")
                return Image.alpha_composite(background, rgba).convert("RGB")
            return corrected.convert("RGB")


def import_one(path, paths: Paths, db: Database, copy=True):
    path = Path(path).resolve()
    before = path.stat()
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    digest = hasher.hexdigest()
    if db.has_digest(digest):
        return "duplicate"
    image = open_image(path)
    width, height = image.size
    thumbnail = paths.thumbnails / f"{digest}.jpg"
    image.thumbnail((480, 600), Image.Resampling.LANCZOS)
    temp_thumb = thumbnail.with_suffix(".tmp")
    image.save(temp_thumb, format="JPEG", quality=85, optimize=True)
    temp_thumb.replace(thumbnail)
    image.close()
    stored_path = path
    if copy:
        stored_path = paths.originals / f"{digest}{path.suffix.lower()}"
        if stored_path != path:
            temp = stored_path.with_suffix(stored_path.suffix + ".tmp")
            try:
                shutil.copyfile(path, temp)
                # A file being edited during import must never get a misleading hash.
                with temp.open("rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                        raise OSError("Image changed during import. Try again after it finishes saving.")
                temp.replace(stored_path)
            finally:
                temp.unlink(missing_ok=True)
    after = path.stat()
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise OSError("Image changed during import. Try again after it finishes saving.")
    inserted = db.insert_image(dict(digest=digest, path=str(stored_path), source_path=str(path), name=path.name,
        thumbnail=str(thumbnail), width=width, height=height, bytes=before.st_size, managed=int(copy)))
    return "imported" if inserted else "duplicate"
