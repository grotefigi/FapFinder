"""Copy installed dependency license files into the portable distribution."""
from importlib.metadata import distributions
from pathlib import Path
import shutil

root = Path(__file__).resolve().parent.parent
destination = root / "dist" / "FapFinder" / "licenses"
copied = 0
for distribution in distributions():
    name = distribution.metadata.get("Name", "dependency")
    for file in distribution.files or []:
        source = Path(distribution.locate_file(file)).resolve()
        if source.name.upper().startswith(("LICENSE", "COPYING", "NOTICE")) and source.is_file():
            # Flatten filenames with their package-relative path to avoid collisions.
            safe_name = str(file).replace("\\", "__").replace("/", "__").replace(":", "_")
            target = destination / name / safe_name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            copied += 1
print(f"Copied {copied} dependency license/notice files.")
