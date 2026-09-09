# Implementation notes

## Components

| Module | Responsibility |
|---|---|
| `config.py` | Portable paths, preferences, pinned model, offline environment |
| `database.py` | SQLite schema, transactions, manual overrides, exports and backups |
| `importer.py` | Recursive discovery, hashing, safe decoding, orientation, copying, previews |
| `vision.py` | Explicit model download; offline SigLIP loading, prototypes, embeddings |
| `search.py` | Weighted ranking, cosine retrieval, browser-search URL construction |
| `workers.py` | Background import, cancellable analysis queue, batch-size recovery |
| `gallery.py` | Qt list model, custom item painting, bounded preview cache, drop support |
| `editor.py` | Single/bulk tag editing, private notes, review state |
| `window.py` | Main UI, task lifecycle, search state, settings, library actions |
| `online.py` | Public Bing image-page adapter, validated downloads/cache, local reranking, saved-source provenance |
| `online_ui.py` | Opt-in online gallery, resolution controls, full-screen viewer, filmstrip, zoom/pan, saving |
| `online_verification.py` | Explicit neutral public-image smoke test for source and frozen builds |

## Data and precedence

The SQLite database uses foreign keys and WAL. Connections have a 30-second busy timeout and live only for the duration of an operation. Each analysis result atomically replaces that image's AI scores and embedding. Manual edits live in a separate table and survive reanalysis. A manual override replaces the entire AI score distribution for its trait; resetting to AI removes the override.

Every stored embedding has a model revision/prompt version. Image-similarity queries require the same version and vector dimension. This prevents comparing incompatible representations if the engine changes. Height is an explicit manual-only group. An absent height record behaves as Unknown.

Imports use SHA-256 content identity, not path identity. Copied images and thumbnails are written to temporary files before atomic replacement. A second hash validates copied bytes, and the source's size/modification time is checked for concurrent edits. Files that fail to decode are reported without aborting the whole import. Decompression-bomb warnings are treated as errors.

## Task lifecycle

The native interface has one long-running task slot. Import, model download, analysis, and text-embedding work run in a QThread. Database reads and manual corrections can coexist with analysis. GPU calls are serialized using an engine lock. A generation counter discards obsolete asynchronous text-search results after the user resets or runs another search.

Pause is cooperative: current work completes, then the task stops. Pending records persist across launches. Closing while a task is active requests cancellation and waits for normal completion before closing the application. GPU out-of-memory failures shrink the batch, and corrupt/missing files are isolated to individual records. Deleting library records is disabled while work is running.

## Packaging and validation

The app is frozen as a Windows x64 one-folder application using PyInstaller. Qt and CUDA DLLs remain external and replaceable. The model is a separate local data asset, not embedded in the executable. `build.ps1` runs tests, builds resources and the executable, and copies the model/docs/dependency notices. No personal image database is included by the build script.

`tests` covers database behavior, ranking, deduplication, manual precedence, EXIF handling, corrupt-file isolation, GPU batch recovery with a test double, native editing controls, theme persistence, and background-import completion. `scripts/verify_app.py` runs the actual GPU model over 1,500 synthetic fixtures with connection methods blocked. `run.py --verify-engine IMAGE --verify-report REPORT` checks the frozen application’s inference path. `--screenshot OUTPUT` provides a deterministic app-rendering check and exits.

The benchmark uses synthetic illustrations; it cannot establish human-trait accuracy. See the model-research document for limitations and a proposed accuracy evaluation.

## Online discovery (1.1)

Online searches occupy the existing background task slot. Bing search terms are made from an allowlist of descriptions; filenames, private notes, paths, image bytes, and reference embeddings are never passed to the provider. Users see and can edit outgoing terms before pressing Search online. Public result pages supply original URLs, source URLs, previews, and reported dimensions. Load more uses a new offset, with URL and preview-byte deduplication and a bounded result count. The public-page format is an external dependency; errors and access checks are reported without bypass attempts.

Downloads allow public HTTP(S) only, reject credentials and nonstandard ports, validate DNS addresses, pin a validated address on the connection, and recheck redirects. HTTPS retains hostname/certificate verification. Requests have time and byte limits, no cookies/auth/proxy state, and four concurrent preview workers. Images are decoded/verified before use, with format, pixel and byte limits. No HTML/scripts from result pages are rendered. Original bytes are kept; previews are reduced and stripped of metadata. Similarity runs on the local model in batches of eight. Reference vectors are reused only for the current model version. Otherwise the reference is encoded locally again.

The viewer has its own single download worker, separate from GPU analysis. A generation counter ignores obsolete downloads after navigation. Closing waits for cooperative completion before destroying the worker. Originals are loaded only when viewed, with a preview while waiting; full-size failures never silently save the preview. Saving uses the existing hashed importer and an additive `web_sources` table (schema 2); manual labels and notes survive duplicate saves. Offline cached galleries do not make network requests until the user opens an uncached original or starts a search. Cache eviction runs on app startup, new searches, and viewer close and leaves managed library originals untouched.

`run.py --data-dir data --verify-online --verify-report verification/online-report.json` explicitly uses the network for a neutral landscape query, ranks on the local GPU, downloads an original, and saves to a separate verification library. `scripts/capture_online_ui.py` renders only those neutral test results. Automated tests cover URL/DNS/redirect restrictions, cache/format validation, query privacy, deduplication, local ranking, provenance, no automatic network access, and viewer navigation/cancellation.
