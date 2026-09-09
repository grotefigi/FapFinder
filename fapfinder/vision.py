from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path

import numpy as np

from .config import MODEL_ID, MODEL_REVISION, Paths, model_ready, offline_environment
from .importer import open_image
from .traits import prompt_groups

MODEL_FILES = ("config.json", "model.safetensors", "preprocessor_config.json", "special_tokens_map.json", "tokenizer.json", "tokenizer.model", "tokenizer_config.json")


class Cancelled(Exception):
    pass


def download_model(paths: Paths, progress=lambda *_: None, stop=lambda: False):
    """The only network operation in the analysis stack; called by explicit setup."""
    import requests

    paths.initialize()
    session = requests.Session()
    # No credentials or user photos are sent to the public model host.
    response = session.get(f"https://huggingface.co/api/models/{MODEL_ID}/revision/{MODEL_REVISION}", params={"blobs": "true"}, timeout=(15, 45))
    response.raise_for_status()
    metadata = response.json()
    revision = metadata["sha"]
    files = {entry["rfilename"]: entry for entry in metadata["siblings"]}
    total = sum(files[name].get("size", 0) for name in MODEL_FILES)
    done = 0
    manifest = {}
    for name in MODEL_FILES:
        if stop():
            raise Cancelled("Model download paused. Run setup again to continue.")
        entry = files[name]
        expected_size = entry.get("size", 0)
        expected_hash = entry.get("lfs", {}).get("sha256")
        target = paths.model / name
        if target.is_file() and target.stat().st_size == expected_size:
            with target.open("rb") as stream:
                existing_hash = hashlib.file_digest(stream, "sha256").hexdigest()
            if expected_hash and existing_hash == expected_hash:
                done += expected_size
                manifest[name] = existing_hash
                progress(done, total, name)
                continue
        temporary = target.with_suffix(target.suffix + ".partial")
        # Resume only the pinned file, never an arbitrary URL or user-provided host.
        offset = temporary.stat().st_size if temporary.exists() else 0
        headers = {"Range": f"bytes={offset}-"} if offset and offset < expected_size else {}
        with session.get(f"https://huggingface.co/{MODEL_ID}/resolve/{revision}/{name}", headers=headers, stream=True, timeout=(15, 45)) as result:
            result.raise_for_status()
            resume = bool(headers) and result.status_code == 206
            if not resume:
                offset = 0
            hasher = hashlib.sha256()
            if resume:
                with temporary.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        hasher.update(block)
            with temporary.open("ab" if resume else "wb") as stream:
                for block in result.iter_content(chunk_size=1024 * 1024):
                    if stop():
                        raise Cancelled("Model download paused. Run setup again to continue.")
                    if not block:
                        continue
                    stream.write(block)
                    hasher.update(block)
                    offset += len(block)
                    progress(done + offset, total, name)
        if expected_size and temporary.stat().st_size != expected_size:
            raise OSError(f"Incomplete model download: {name}. Run setup again.")
        if expected_hash and hasher.hexdigest() != expected_hash:
            temporary.unlink(missing_ok=True)
            raise OSError(f"Integrity check failed for {name}. Run setup again.")
        temporary.replace(target)
        manifest[name] = hasher.hexdigest()
        done += offset
    ready = paths.model / "READY.json"
    temp = ready.with_suffix(".tmp")
    temp.write_text(json.dumps({"model": MODEL_ID, "revision": revision, "sha256": manifest}, indent=2), "utf-8")
    temp.replace(ready)
    session.close()
    progress(total, total, "Model ready for offline use")


class VisionEngine:
    def __init__(self, paths: Paths, device="auto"):
        self.paths = paths
        self.device_preference = device
        self.model = None
        self.processor = None
        self.device = "cpu"
        self.device_name = "Not loaded"
        self._lock = threading.RLock()

    @property
    def version(self):
        try:
            revision = json.loads((self.paths.model / "READY.json").read_text("utf-8"))["revision"]
        except (OSError, ValueError, KeyError):
            revision = MODEL_REVISION
        return f"{MODEL_ID}@{revision}:prompts-v1:temp20"

    def load(self, progress=lambda *_: None):
        with self._lock:
            if self.model is not None:
                return
            if not model_ready(self.paths):
                raise RuntimeError("The local AI model is not installed. Open Settings and click Download model (1.6 GB).")
            offline_environment()
            progress("Loading local AI model…")
            import torch
            from transformers import AutoModel, AutoProcessor

            torch.set_num_threads(max(1, min(6, (os.cpu_count() or 4) // 2)))
            self.device = "cuda" if self.device_preference != "cpu" and torch.cuda.is_available() else "cpu"
            dtype = torch.float16 if self.device == "cuda" else torch.float32
            processor = AutoProcessor.from_pretrained(str(self.paths.model), local_files_only=True, trust_remote_code=False, use_fast=False)
            model = AutoModel.from_pretrained(str(self.paths.model), local_files_only=True, trust_remote_code=False,
                use_safetensors=True, dtype=dtype, attn_implementation="sdpa").eval().to(self.device)
            self.processor = processor
            self.model = model
            self.device_name = torch.cuda.get_device_name(0) if self.device == "cuda" else "CPU"
            self.groups = prompt_groups()
            self.prompt_index = []
            prompts = []
            for group, options in self.groups.items():
                for value, templates in options:
                    self.prompt_index.append((group, value, len(prompts), len(templates)))
                    prompts.extend(templates)
            try:
                encoded = []
                for start in range(0, len(prompts), 32):
                    encoded.append(self._encode_text(prompts[start:start + 32]))
                raw = np.concatenate(encoded)
                prototypes = []
                for group, value, start, length in self.prompt_index:
                    feature = raw[start:start + length].mean(axis=0)
                    prototypes.append(feature / max(np.linalg.norm(feature), 1e-8))
                self.prototypes = np.stack(prototypes)
                progress(f"Ready · {self.device_name}")
            except BaseException:
                self.model = None
                raise

    def _encode_text(self, prompts):
        import torch
        inputs = self.processor(text=[p.lower() for p in prompts], padding="max_length", truncation=True, max_length=64, return_tensors="pt").to(self.device)
        with torch.inference_mode():
            features = self.model.get_text_features(**inputs)
            if not torch.is_tensor(features):
                features = features.pooler_output
            features = torch.nn.functional.normalize(features.float(), dim=-1)
        return features.cpu().numpy()

    def encode_text(self, text):
        with self._lock:
            self.load()
            return self._encode_text([text])[0]

    def analyze(self, image_paths):
        with self._lock:
            self.load()
            import torch
            images = []
            try:
                for path in image_paths:
                    images.append(open_image(path))
                inputs = self.processor(images=images, return_tensors="pt").to(self.device)
                if self.device == "cuda":
                    inputs = {k: v.to(dtype=torch.float16) if v.is_floating_point() else v for k, v in inputs.items()}
                with torch.inference_mode():
                    features = self.model.get_image_features(**inputs)
                    if not torch.is_tensor(features):
                        features = features.pooler_output
                    features = torch.nn.functional.normalize(features.float(), dim=-1).cpu().numpy()
                logits = features @ self.prototypes.T * 20.0
                results = []
                for vector, row in zip(features, logits):
                    scores = {}
                    for group in self.groups:
                        indices = [i for i, item in enumerate(self.prompt_index) if item[0] == group]
                        values = row[indices]
                        exp = np.exp(values - values.max())
                        probs = exp / exp.sum()
                        scores[group] = {self.prompt_index[i][1]: float(p) for i, p in zip(indices, probs)}
                    results.append((scores, vector))
                return results
            finally:
                for image in images:
                    image.close()

    def recover_memory(self):
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
