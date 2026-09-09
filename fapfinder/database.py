from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from .traits import VALID_TAGS, TRAITS, label_for


class Database:
    """Short-lived connections allow background writers and the UI to coexist."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS images (
                    id INTEGER PRIMARY KEY, digest TEXT NOT NULL UNIQUE,
                    path TEXT NOT NULL, source_path TEXT NOT NULL, name TEXT NOT NULL,
                    thumbnail TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,
                    bytes INTEGER NOT NULL, managed INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending', error TEXT NOT NULL DEFAULT '',
                    favorite INTEGER NOT NULL DEFAULT 0, reviewed INTEGER NOT NULL DEFAULT 0,
                    notes TEXT NOT NULL DEFAULT '', imported_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    analyzed_at TEXT, model_version TEXT, embedding BLOB
                );
                CREATE INDEX IF NOT EXISTS images_status ON images(status);
                CREATE TABLE IF NOT EXISTS ai_tags (
                    image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
                    trait TEXT NOT NULL, value TEXT NOT NULL, score REAL NOT NULL CHECK(score BETWEEN 0 AND 1),
                    PRIMARY KEY(image_id,trait,value)
                );
                CREATE INDEX IF NOT EXISTS tags_lookup ON ai_tags(trait,value,score);
                CREATE TABLE IF NOT EXISTS manual_tags (
                    image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
                    trait TEXT NOT NULL, value TEXT NOT NULL, strength REAL NOT NULL CHECK(strength BETWEEN 0 AND 1),
                    PRIMARY KEY(image_id,trait)
                );
                CREATE TABLE IF NOT EXISTS web_sources (
                    image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
                    source_url TEXT NOT NULL, image_url TEXT NOT NULL,
                    saved_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    PRIMARY KEY(image_id, image_url)
                );
                PRAGMA user_version=2;
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=30000")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def has_digest(self, digest):
        with self.connect() as db:
            return db.execute("SELECT id FROM images WHERE digest=?", (digest,)).fetchone() is not None

    def insert_image(self, image):
        keys = ("digest", "path", "source_path", "name", "thumbnail", "width", "height", "bytes", "managed")
        with self.connect() as db:
            cursor = db.execute(f"INSERT OR IGNORE INTO images ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})", [image[k] for k in keys])
            return cursor.lastrowid if cursor.rowcount else None

    def stats(self):
        with self.connect() as db:
            row = db.execute("SELECT COUNT(*) total, COALESCE(SUM(status='ready'),0) ready, COALESCE(SUM(status='pending'),0) pending, COALESCE(SUM(status='error'),0) errors, COALESCE(SUM(favorite),0) favorites, COALESCE(SUM(status='ready' AND reviewed=0),0) review FROM images").fetchone()
            return dict(row)

    def list_images(self, view="all", filename=""):
        conditions, args = [], []
        if view == "favorites":
            conditions.append("favorite=1")
        elif view == "review":
            conditions.append("status='ready' AND reviewed=0")
        elif view == "pending":
            conditions.append("status IN ('pending','error')")
        if filename:
            conditions.append("(instr(lower(name),lower(?))>0 OR instr(lower(notes),lower(?))>0)")
            args.extend([filename, filename])
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT id,name,path,thumbnail,width,height,status,error,favorite,reviewed,notes,model_version FROM images" + where + " ORDER BY id DESC", args)]

    def get_image(self, image_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM images WHERE id=?", (image_id,)).fetchone()
            if not row:
                return None
            result = dict(row)
            result["ai_tags"] = [dict(r) for r in db.execute("SELECT trait,value,score FROM ai_tags WHERE image_id=? ORDER BY score DESC", (image_id,))]
            result["manual_tags"] = {r["trait"]: dict(r) for r in db.execute("SELECT trait,value,strength FROM manual_tags WHERE image_id=?", (image_id,))}
            result["web_sources"] = [dict(r) for r in db.execute("SELECT source_url,image_url,saved_at FROM web_sources WHERE image_id=?", (image_id,))]
            return result

    def pending(self, include_errors=False):
        with self.connect() as db:
            status = "status IN ('pending','error')" if include_errors else "status='pending'"
            return [dict(r) for r in db.execute(f"SELECT id,path FROM images WHERE {status} ORDER BY id")]

    def save_analysis(self, image_id, scores, embedding, version):
        vector = np.asarray(embedding, dtype="<f4")
        if vector.ndim != 1 or not np.all(np.isfinite(vector)) or not np.isclose(np.linalg.norm(vector), 1, atol=.01):
            raise ValueError("The model returned an invalid embedding.")
        tags = []
        for group, values in scores.items():
            for value, score in values.items():
                if (group, value) not in VALID_TAGS or not np.isfinite(score) or not 0 <= score <= 1:
                    raise ValueError("The model returned an invalid trait score.")
                tags.append((image_id, group, value, float(score)))
        with self.connect() as db:
            db.execute("DELETE FROM ai_tags WHERE image_id=?", (image_id,))
            db.executemany("INSERT INTO ai_tags(image_id,trait,value,score) VALUES (?,?,?,?)", tags)
            db.execute("UPDATE images SET status='ready',error='',embedding=?,model_version=?,analyzed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (vector.tobytes(), version, image_id))

    def mark_error(self, image_id, error):
        with self.connect() as db:
            db.execute("UPDATE images SET status='error',error=? WHERE id=?", (str(error)[:1500], image_id))

    def save_manual(self, image_ids, edits, notes=None, reviewed=None):
        for group, entry in edits.items():
            if group not in {t.key for t in TRAITS}:
                raise ValueError("Unknown trait")
            if entry is not None and ((group, entry[0]) not in VALID_TAGS or not 0 <= entry[1] <= 1):
                raise ValueError("Invalid manual tag")
        with self.connect() as db:
            for image_id in image_ids:
                for group, entry in edits.items():
                    db.execute("DELETE FROM manual_tags WHERE image_id=? AND trait=?", (image_id, group))
                    if entry is not None:
                        db.execute("INSERT INTO manual_tags VALUES (?,?,?,?)", (image_id, group, entry[0], entry[1]))
                if notes is not None:
                    db.execute("UPDATE images SET notes=? WHERE id=?", (notes, image_id))
                if reviewed is not None:
                    db.execute("UPDATE images SET reviewed=? WHERE id=?", (int(reviewed), image_id))

    def set_favorite(self, image_ids, favorite):
        with self.connect() as db:
            db.executemany("UPDATE images SET favorite=? WHERE id=?", [(int(favorite), i) for i in image_ids])

    def remove(self, image_ids):
        # Deliberately removes database records only; originals are never deleted.
        with self.connect() as db:
            db.executemany("DELETE FROM images WHERE id=?", [(i,) for i in image_ids])

    def effective_scores(self):
        with self.connect() as db:
            rows = db.execute("""SELECT a.image_id,a.trait,a.value,a.score FROM ai_tags a
                WHERE NOT EXISTS (SELECT 1 FROM manual_tags m WHERE m.image_id=a.image_id AND m.trait=a.trait)
                UNION ALL SELECT image_id,trait,value,strength AS score FROM manual_tags
                UNION ALL SELECT id,'height','unknown',1.0 FROM images i
                WHERE NOT EXISTS (SELECT 1 FROM manual_tags m WHERE m.image_id=i.id AND m.trait='height')""").fetchall()
            return [tuple(row) for row in rows]

    def embeddings(self, version=None):
        with self.connect() as db:
            query = "SELECT id,embedding,model_version FROM images WHERE embedding IS NOT NULL"
            rows = db.execute(query).fetchall()
            return {r["id"]: np.frombuffer(r["embedding"], dtype="<f4").copy() for r in rows if version is None or r["model_version"] == version}

    def export_json(self, path):
        path = Path(path).resolve()
        if path == self.path.resolve():
            raise ValueError("Choose a separate JSON file; the library database cannot be overwritten.")
        output = []
        for row in self.list_images():
            item = self.get_image(row["id"])
            item.pop("embedding", None)
            output.append(item)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps({"schema": 1, "score_note": "AI scores are relative prompt scores, not calibrated probabilities. Manual strengths are user-entered.", "images": output}, indent=2, ensure_ascii=False), "utf-8")
        temp.replace(path)

    def backup(self, target):
        target = Path(target).resolve()
        if target == self.path.resolve():
            raise ValueError("Choose a different file for the backup.")
        with self.connect() as source, sqlite3.connect(target) as destination:
            source.backup(destination)


def best_tags(image):
    result = {}
    for group in TRAITS:
        manual = image["manual_tags"].get(group.key)
        if manual:
            result[group.key] = (manual["value"], manual["strength"], "manual")
            continue
        candidates = sorted((t for t in image["ai_tags"] if t["trait"] == group.key), key=lambda t: t["score"], reverse=True)
        threshold = .75 if group.key == "age" else .55
        if candidates and candidates[0]["value"] != "unknown" and candidates[0]["score"] >= threshold and (len(candidates) < 2 or candidates[0]["score"] - candidates[1]["score"] >= .12):
            result[group.key] = (candidates[0]["value"], candidates[0]["score"], "AI estimate")
        else:
            result[group.key] = ("unknown", candidates[0]["score"] if candidates else 0, "uncertain")
    return result
