# FapFinder

A native Windows 11 image library with private, local AI analysis, editable visual traits, and weighted similarity search.

## Open the app

Double-click **Start FapFinder.vbs** in this project, or open **dist/FapFinder/FapFinder.exe** directly. The portable build includes Python, Qt, CUDA inference libraries, and the downloaded SigLIP 2 model. No account, API key, Python installation, or internet connection is needed to use the built app.

Keep the entire `dist/FapFinder` folder together. It contains the program, its `_internal` libraries, and its `data` folder. It can be copied to another writable folder on a Windows x64 computer. The app is unsigned; it has not been submitted to a signing service or installer store.

## First use

1. Click **Import images**, **Import folder**, or drop a folder onto the window. Subfolders are included. Supported formats: JPG/JPEG, PNG, WebP, BMP, and TIFF. Animated/multipage formats use their first frame.
2. Imports copy originals into the local library by default, create lightweight previews, and skip identical files by SHA-256. Automatic analysis starts after import. **Settings** can switch copying or automatic analysis off.
3. Choose traits on the right. Set each slider's **importance**: 0 ignores that trait, 100 gives it the most weight. Click **Search library**. Add a free-text description to combine local text similarity with your selected traits.
4. Double-click an image to inspect and edit tags. A manual tag's slider sets its **visual strength**, independent of the search importance. Select **Unknown / not visible** to override a bad estimate, or **Use AI suggestion** to remove your override. Click **Save changes**.
5. Hold Ctrl or Shift to select multiple images, then **Edit selected**. Unchanged fields are preserved. Right-click images to favorite them or find similar images.

**Analyze queue** processes pending and failed images. **Pause** stops after the current file/batch; completed work is saved. Reopen the app and click **Analyze queue** to continue. Import can be resumed by importing the same folder again; completed files are skipped. Closing during work requests a safe pause before the window exits.

## What it estimates

| Field | Behavior |
|---|---|
| Hair | Color, length, and texture |
| Apparent body build | Slim/skinny, average, curvy, plus-size, muscular |
| Visible skin tone | Light, medium, tan, deep; describes lighting-dependent appearance, not race/ethnicity |
| Apparent age | Broad adult ranges; unreliable and never age verification |
| Face shape | Oval, round, square, heart-shaped, long |
| Other traits | Framing, glasses, indoor/outdoor/studio setting |
| Actual height | Manual measurement bands only; no fabricated estimate from an uncalibrated photo |

The model scores predefined descriptions of the entire image. It does not identify people or associate faces across photographs. Multiple people, clothing, crops, editing, pose, or lighting can confuse it. No calibrated accuracy claim is made for these appearance labels. Review suggestions on your own images before relying on them.

**AI scores are relative prompt scores, not probabilities of correctness.** Automatic labels require a score of at least 55/100 and a 12-point lead over the next option; apparent age uses a more cautious 75/100 threshold. Otherwise the current label is Unknown, while the strongest raw suggestion remains visible for review. Search uses the full score distributions, including low-scoring alternatives, so broad exploratory searches still work. Manual tags replace the AI distribution for the edited field.

## Search scores

Trait search computes the weighted mean of the selected trait scores. Manual visual strength replaces the AI score for an overridden field. For example, blonde with importance 90 and slim with importance 10 emphasizes hair much more strongly. Raising **Minimum score** excludes weaker results; it does not change the ranking.

Text and “find similar” search use normalized image/text embeddings and cosine similarity, clipped to 0–100 for display. When text and trait criteria are combined, text contributes half and the weighted traits contribute half. A score is a ranking aid within a query, not a probability, and scores from different queries are not directly comparable. Filename/notes matching is a literal, case-insensitive filter; it also works before analysis.

## Find similar photos online

1. Select a photo in your library, then click **Find similar online** (also available in its right-click menu).
2. Review or edit the suggested description. Choose **HD** (1280 px+) or **Full HD** (1920 px+), then **Search online**.
3. Browse the gallery. Click any photo for a full-screen viewer with next/previous arrows, a filmstrip, wheel/double-click zoom, and drag to pan or swipe between photos. **Load more photos** adds another page; the Size slider changes gallery tile size.
4. The viewer loads the original from its public host and shows its actual dimensions. **Save to library** preserves the downloaded original, records its source link, and queues local analysis. **Open source** opens the original page in your browser. Unavailable originals leave a clearly marked small preview; they cannot be saved as if they were high-resolution files.

You can also open **Explore online** from the sidebar and type a description. The button below the library's trait controls carries your description and selected trait importance into online discovery. Height has no automatic online score.

Search uses Bing's public image index across many websites, with SafeSearch enabled. No search index covers every site; private, unindexed, unavailable, and blocked images are outside its coverage. This is a public search-page adapter, not an official paid API, so availability and result formats may change. No API key or subscription is required. The app stops at access checks and rate limits rather than bypassing them. Result/source information comes from the search index and can be stale. Image resolution is a size filter, not a guarantee of sharpness, aesthetic quality, or reuse rights; source links are retained.

Only the visible description goes to search. Images, embeddings, local filenames, and private notes are never uploaded. Downloaded previews are compared against your reference locally using SigLIP 2; description-only searches use local text similarity. When trait weights are provided, local trait scoring contributes half. Scores are cosine/trait ranking scores out of 100, not percentages of confidence; text-to-image scores are typically lower than image-to-image scores. Matching is about the image's overall appearance, not identifying a person.

Online results remain separate from your library until you press **Save to library**. The last gallery is cached for offline browsing. Opening an uncached original needs internet. Downloads contact search/image hosts using your normal IP address; **Open source** uses your browser's usual site state. No photo upload is needed for discovery.

## Privacy and storage

The built application stores everything beside its executable in `dist/FapFinder/data`. Running from source instead uses the project's top-level `data`. You can choose another location with `--data-dir "D:\MyLibrary"` or `FAPFINDER_DATA`.

- `library.sqlite3`: image records, original paths, tags, relative scores, manual strengths, notes, review flags, and embeddings.
- `thumbnails`: cached JPEG previews without EXIF metadata.
- `originals`: copied source images, with original bytes and metadata preserved.
- `models`: pinned model files and their SHA-256 manifest.
- `web-cache`: downloaded web previews, originals, and the last search description/results. Evicted toward a 300 MB limit on launch, new searches, and viewer close; active browsing can temporarily exceed it. Delete this folder with the app closed to clear online history and downloads. Saved library originals remain intact.
- `preferences.json` and rotating `app.log`: local preferences and error details.

There is no cloud AI, account, background update check, or telemetry. Normal model loading uses local paths, `local_files_only=True`, disabled remote code, safetensors weights, and offline environment settings. Network calls occur only for explicit model downloads, online searches, and opening/downloading online originals. Launching the app or opening the Explore online page does not connect to the network. The one-time dependency/model setup requires internet; the supplied portable build already contains the model.

The local database and copied photos are **not encrypted by this app**. Other software with access to this folder can read them. An OS-synced folder may still be synced by the operating system or another application.

Removing images from the library removes records and tags, while original files and cached copies are kept. Use **Settings → Back up database** for a consistent SQLite backup. To back up photos too, close the app and copy the entire data folder. To restore, close the app, preserve the current folder, and restore the saved data folder. Do not copy a live SQLite file on its own; its WAL may contain recent work.

## Hardware and verification

Configured for RTX 4050 Laptop GPU, 6 GB VRAM, 32 GB RAM, and i5-12450H. Default: CUDA FP16, batch 16, 224 px model input. GPU batches shrink automatically after an out-of-memory failure. CPU fallback is available in Settings and is automatic if CUDA is unavailable. Actual speed depends on image sizes, disk speed, GPU power mode, and other applications.

Local verification on this machine, 9 September 2026:

| Check | Result |
|---|---|
| Core, online discovery, and native UI automated tests | 32 passed |
| Online discovery smoke test | 35 public landscape candidates, 30 usable HD matches, local RTX 4050 ranking, original download and save with source verified |
| Online pagination | Second page: 35 results, 31 new image URLs |
| Bulk import workload | 1,500 unique synthetic 160 × 200 PNGs, 23.8 seconds |
| Local AI analysis | 1,500 / 1,500 succeeded, 33.0 seconds, 45.4 images/second |
| Model startup | 6.0 seconds |
| GPU memory measured by PyTorch | 799.5 MiB peak allocated; 834.0 MiB reserved; excludes driver/display overhead |
| Weighted trait search | 125 ms over 1,500 images |
| Text embedding + search | 39 ms with the model loaded |
| Offline verification | Socket connections blocked; zero attempts during load, analysis, and search |

Synthetic test fixtures verify capacity and execution, **not accuracy on real photographs**. Verification artifacts and neutral public-image smoke tests live under `verification`, separately from the app's data. Existing personal library data is preserved during updates. See `docs/MODEL_RESEARCH.md` for model selection and limitations.

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| Ctrl+O | Import images |
| Ctrl+Shift+O | Import folder |
| Ctrl+F | Focus description search |
| Ctrl+E | Edit selected images |
| Ctrl+A in gallery | Select all displayed images |
| Escape | Clear library search |
| Left / Right in online viewer | Previous / next photo |
| Home / End in online viewer | First / last photo |
| Escape in online viewer | Close viewer |

## Run or rebuild from source

Use Python 3.12 (3.10–3.13 supported by the setup check). From this directory:

```powershell
.\setup.ps1 -PythonExe 'C:\Path\To\Python312\python.exe'
.\.venv\Scripts\python.exe run.py
```

For a CPU-only installation, add `-CpuOnly`. `-SkipModel` leaves model setup to the app's Settings page. Dependencies are installed in a project-local `.venv`; the system Python environment is not modified.

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
.\build.ps1
```

`requirements.txt` pins direct dependencies; `requirements-lock.txt` records the tested full environment, including the CUDA-specific Torch build. Use the official CUDA index when reproducing that environment. `build.ps1` stages application files under `build/portable-stage`, then updates `dist/FapFinder` while preserving existing user data. It copies the installed model but does not copy personal library images. Close the app before rebuilding. Reserve roughly 20 GB for the source environment, build staging, and portable app, excluding your photos. Run the build script instead of calling PyInstaller directly against a portable folder containing your library.

The architecture is Qt/PySide6 with a virtualized gallery, background tasks, SQLite in WAL mode, NumPy ranking, and a single local SigLIP 2 engine. No web server or Electron runtime is used. The portable build is a real native desktop application with bundled dependencies.
