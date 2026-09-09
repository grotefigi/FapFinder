import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fapfinder.config import Paths
from fapfinder.vision import download_model

if __name__ == "__main__":
    paths = Paths(Path(sys.argv[1]).resolve()) if len(sys.argv) > 1 else Paths.default()
    previous = [-1]
    def progress(done, total, name):
        percent = int(done / max(total, 1) * 100)
        if percent != previous[0]:
            print(f"{percent}% | {name} | {done / 1e9:.2f} / {total / 1e9:.2f} GB", flush=True)
            previous[0] = percent
    download_model(paths, progress)
