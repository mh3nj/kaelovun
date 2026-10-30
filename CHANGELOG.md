# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/).
This project adheres to [Semantic Versioning](https://semver.org/).

---

## Unreleased

### Added
- A converted archive now inherits the source's previews: `Name.avif` and `Name.thumb.avif` are **copied** (never moved) next to the result, under the result's final name, so Evoury shows the preview right away. The originals stay untouched and nothing existing is ever overwritten.
- **Convert Archives** has a new **Smallest** target: it builds 7z, ZIP and RAR all at Best compression, keeps whichever comes out smallest (a missing tool is skipped, not an error), and deletes the losers. Still respects "only keep a result that is smaller".
- "Move the original to the Recycle Bin" now takes the original's `Name.avif` / `Name.thumb.avif` along, but only when nothing left next to the source would pair with them (if the result keeps the same name, the previews stay, since they are now the result's previews).
- The Convert window has an **Archive options...** button that opens the Settings Archive tab directly. The two share the same stored settings, so a change made in either place applies to both, and the "Settings default" compression entry refreshes right after saving.
- **34 themes from the mh3nj collection** (17 families, dark and light) ship in `assets/themes/` and replace the old two-tone dark/light pair. Pick one in Settings > Appearance (applies after Save) or cycle through all of them with the theme button. The app remembers your choice, and the header logo flips between its dark and white mark to match the theme.

### Changed
- **Convert Archives** now spells out its targets (ZIP / 7-Zip / WinRAR / Smallest) and every compression level shows the exact flags it maps to (7z `-mx`, RAR `-m`, ZIP level), instead of vague "Fast / Normal / Best" labels. The Settings dialog shows the same details. The "Settings default" entry names the level it resolves to, so it is never a mystery.
- The Convert window's **Convert to / Compression / Original file** rows are no longer choices: they are read-only announcers that show exactly what Settings > Archive says right now (output format, compression level, and the new **After converting** choice: keep the original or move it to the Recycle Bin). Change them in Settings, and the announcers refresh the moment you save.

### Fixed
- **The Affinity engine now opens PSD files too.** Selecting Affinity (with its MCP server enabled) used to still launch Photoshop for PSDs, because only AI/EPS followed the engine pick while PSD was hard-wired to Photoshop. Now PSD, AI and EPS all open in Affinity when it is the active engine; native .afphoto/.afdesign/.afpub files always did and still do.

---

## 1.6.2 — 2026-10-26

### Changed
- The sidecar now also records the **CRC32 of every file** (taken from the finished archive's own listing, so there is no extra pass over the data). Evoury uses it to find the same file inside several packages and packages that mostly contain the same files, without opening any archive.

---

## 1.6.1 — 2026-10-26

### Fixed
- **Previews were no longer saved next to the archive.** Since the package model (1.4) the preview and thumbnail only existed *inside* the archive, but Evoury looks for `Name.avif` and `Name.thumb.avif` next to `Name.<archive>`. They are now written beside every archive with the same name (new setting: *Save the preview next to each archive*, on by default). They are written first and the archive last, so Evoury never sees a half-finished package.
- When a name is already taken, the archive, preview, thumbnail and sidecar all move together to the next free name (`Pack (2).7z`, `Pack (2).avif`, ...) instead of only the archive.

### Changed
- The optional sidecar (`<archive>.kaelovun.json`) now lists every file in the archive with its **size** and category (and CRC32 in paranoid mode), plus the archive's own size. Evoury uses it to show an archive's contents instantly, including RAR.
- Temporary files use the `.kaelovun-part` marker everywhere (archive, preview, thumbnail), which Evoury ignores while they are being written.

---

## 1.6.0 — 2026-10-24

### Added
- **7z and ZIP output** next to RAR, plus **Smallest** (build 7z and RAR, keep the smaller). Choose in Settings > Archive or with `--format`. 7z needs 7-Zip, RAR needs WinRAR, ZIP is built in.
- **Archive converter**: change existing archives between RAR / 7z / ZIP (TAR.* as input), from the GUI (**Convert Archives**) or the CLI (`--convert-to`). Verified, never modifies the original, never overwrites, optional Recycle Bin for originals, multi-volume and password support, `--plan` preview.
- **Settings > Archive tab**: format, level, solid mode, dictionary size, RAR recovery record, verification level, safety limits, 7-Zip path, scratch (workspace) folder.
- **Safety limits** for archives Kaelovun opens: unpacked size, unpack ratio and entry count, enforced before unpacking and again on the bytes written.
- **CLI**: `--format`, `--level`, `--verify`, `--workspace`, `--plan`/`--dry-run`, `--verify-only`, `--convert-to`, `--original`, multiple inputs. `--output`, `--no-cleanup` and `--verify-only` were accepted but silently ignored; they now work.
- **Paranoid verification** (CRC32 of every file) and an optional **sidecar manifest** (`<archive>.kaelovun.json`).
- **GUI**: end-of-queue summary, drag and drop (with `tkinterdnd2`), default name pre-filled in the naming box, persistent name history with Tab completion.
- **Workspace**: configurable scratch folder, free-space check on the drive actually used, stale workspaces swept at startup.
- Tests: ~100 new tests (backends, parsers, security, conversion, queue, processor, GUI-facing flows). `tests/conftest.py` stubs pywin32 so the pure-Python suite runs without Windows.

### Fixed
- **Preview was exported before any document was opened.** Every controller exports the *active* document, so the preview step could not work for PSD/AI/INDD/Affinity files. It now opens the document first. The representative document stays open while you name the package, so *edit in the app, then Regen Preview* works again.
- **GUI naming never received a preview.** The processor never raised the name request, so the GUI prompt didn't appear and the console `input()` path was used. The GUI backend is now wired up (and falls back to the default name when no one answers).
- **An archive could be written over its own source.** For archive inputs the output was `<source folder>/<stem>.rar`, which for `pack.rar` is the source itself, and `rar a` updates an existing archive in place. Output is now built under a temporary name and published with a unique name.
- **The manifest check could not work with real RAR output.** `rar lt` prints `Key: value` blocks, not columns, so names with spaces were mangled and extra tokens appeared. Listing now uses 7-Zip's `-slt` format (and a correct `rar lt` parser as a fallback). A file that was both an asset and its own preview (the contact sheet) was also counted twice and could fail verification.
- **Nested archives at the depth limit were deleted** after being "preserved", leaving a missing file in the archive list. They are now kept.
- **No archive-bomb protection existed** for RAR/7z (and none for the ratio on any format) despite being documented. Added (see above).
- **RAR listing in the classifier always failed** (`_list_rar` called a method with the wrong arguments) and extracted the whole archive just to list it. Listing no longer extracts.
- **Archives with many files could exceed the Windows command-line limit.** File lists now go through a UTF-8 list file (7z) or are batched (RAR).
- **Disk-space check looked at the wrong drive** (the source's, not the scratch folder's).
- **Queue**: stopping a paused queue hung the worker forever; pause set before start was lost; the job list was not thread-safe.
- **Retry accounting**: a job that succeeded on retry was counted as failed, and retry was recursive.
- **GUI**: the progress label raised an error every second (`_total_assets` did not exist) and never updated; log lines were drawn from worker threads; Settings > Save discarded settings it doesn't edit; **Select File** was not themed.
- `requirements.txt` listed `patoolib`, which is not a PyPI package. The package is `patool`.
- The startup check required WinRAR even when the output format was 7z or ZIP.
- Unicode filenames in tool output are decoded as UTF-8; passwords go through stdin, never the command line.
- Contact sheets are named after the archive (`pack_contact_sheet.avif`) instead of the internal `_extracted_pack_contact_sheet.avif`.
- File-name normalisation now strips trailing dots/spaces, control characters and reserved device names (`CON`, `NUL`...).

### Changed
- `pipeline/queue.py` is now `pipeline/jobqueue.py` (it shadowed the standard-library `queue`). `pipeline/__init__.py` imports lazily so the converter and `--verify-only` work without Adobe/Affinity installed.
- `RarArchive` is now `ArchiveManager`; `RarArchive` and `create_rar()` remain as aliases.
- `ARCHIVE_PROFILE` is now actually used (old `method`/`solid`/`recovery` keys are still understood).
- `CHANGES.md` (audit notes) moved to `docs/history/`.

### Notes
- RAR creation and `rar lt` parsing follow WinRAR's documented switches (`-ma5 -m5 -md -s/-se/-s- -rr -ms`) but were not run against a real `Rar.exe` while developing this release; everything 7z/ZIP/convert/extraction related was exercised against real 7-Zip. Run a RAR job once and check `data/kaelovun.log` for "Archive manifest mismatch".

---

## 1.5.0

### Added
- Safe-copy model for all inputs (files, directories, archives) and manifest-based archive verification.

---

## 1.4.0 — 2026-09-25

### Fixed
- **Archive processing bug:** `scan_folder` now properly marks `.zip`, `.rar`, and other archive files with `is_archive=True`. Previously archives were treated as opaque files and re-compiled without extraction, causing massive RARs (up to 3TB). Archives are now properly extracted, contents classified, and re-archived with the actual asset files.
- **Archive cleanup:** Extracted archive files are now properly cleaned up between jobs via `cleanup_all()`.
- **Archive naming:** Output RARs are now named after the source archive file stem instead of always "background".
- **`_use_affinity` fix:** `.psd` files are no longer incorrectly routed to Affinity (which cannot open PSDs). `.psd` always uses Photoshop; `.ai`/`.eps` follow the `ENGINE` setting.

### Added
- **Contact sheet preview for archives:** When an archive contains multiple images, Kaelovun generates a grid contact sheet (all images in one picture) with full AVIF preview and thumbnail. This lets Evoury display the archive as a single browsable card instead of an unviewable archive.
- **`PreviewProcessor.create_contact_sheet()`:** New method that creates a grid/contact sheet PNG from a list of image paths, configurable column count.

---

## 1.3.1 — 2026-09-15 (rebranded as Kaelovun — 2026-09-16)

### Changed

- **Rebrand: Asset Organizer → Kaelovun.** Application title, window, logging (`Kaelovun`), settings, setup scripts, and documentation now use Kaelovun throughout. Previous name retained below in history for reference. No pipeline behavior changes.
- **Theme-aware branding.** New `assets/icons/icon-white.png` (light) and `assets/icons/icon-dark.png` (dark) logos; the in-app header and window icon swap automatically with the dark/light theme. Renamed log file to `data/kaelovun.log` and build to `Kaelovun.exe` via `Kaelovun.spec`.
- **Repository.** Moved to `https://github.com/mh3nj/kaelovun` with updated README badges, install paths (`Kaelovun-v1.3.1.zip` → `Kaelovun/Kaelovun.exe`), and release assets.

### Fixed

- **Photoshop locked-visible layers.** `hideVisibleLayers` now unlocks every lock kind (`allLocked`/`locked`/pixels/position/transparent) before hiding, per-layer isolated, children before groups — one stubborn layer can no longer abort the loop and leave the file big. (`scripts/photoshop_export.jsx`)
- **Illustrator locked layers.** Same unlock-first hardening for layers/sublayers plus `pageItems[].locked`, then hide. (`scripts/illustrator_export.jsx`)
- **Affinity locked layers.** `aoHideVisibleLayers` now runs select-all → unlock-all/unlock-selection → hide-selection in 3 passes (layers freed in pass N hide in pass N+1) and clears the selection after. (`scripts/affinity_pipeline.js`)
- **Affinity startup popups.** Kaelovun now auto-dismisses the in-app updater (answers Later/No/Skip/Close) and the template/welcome/new-document opener (Close/Cancel/Escape) on Affinity start and before each open — Affinity-owned windows only, best-effort, never fails the job. (`affinity/popups.py`, `affinity.py`)

---

## 1.3.0 — 2026-09-13

### Added

- **Affinity engine.** New `ENGINE` setting (`adobe`/`affinity`). In Affinity mode PSD/AI/EPS open in the unified Affinity app (Canva-era) via its local MCP scripting server, and native `.afphoto`/`.afdesign`/`.afpub` files become scannable. (`affinity/`, `processor.py`, `scanner.py`)
- **Stdlib-only MCP client.** Persistent SSE session on the IPv6-only `[::1]:6767` (no new dependencies), automatic preamble handshake, schema-driven tool calls. (`affinity/mcp_client.py`)
- **Affinity pipeline scripts.** Probe, session-UUID, hide-layers (`selectAll`+`hideSelection`, render-confirmed), save, close, and current-doc-name helpers answering in one JSON line; close/save degrade honestly where 3.2.1 throws `NOT_IMPLEMENTED`. (`scripts/affinity_pipeline.js`)
- **Canvas-rendered previews.** Affinity previews come from `render_spread` keyed by document session UUID (live pixels, max 1024px, no filesystem sandbox); the existing AVIF/thumbnail path consumes them unchanged. (`affinity.py`, `preview.py`)
- **⚙ Settings dialog.** Engine, app paths (Browse/Auto + found/missing status), formats, preview/AVIF numbers, pipeline timeouts, theme — saved machine-local to `data/settings.json` and applied live, no restart or rebuild. (`ui/settings_dialog.py`, `files/app_settings.py`)
- **Persisted theme.** The Theme toggle now survives restarts. (`ui/app.py`)
- **Engine indicator.** Status bar shows `Ready (Adobe)` / `Ready (Affinity)`. (`ui/app.py`)
- **Affinity startup checks.** Warns when the exe is missing or the MCP server is off instead of failing mid-queue. (`requirements_check.py`)
- **Affinity setup guide.** `docs/affinity-setup.md` covers enabling MCP, switching engines, per-stage behavior, limitations, and hardening scripts to an exact build.
- **Tab recycle.** `AFFINITY_RESTART_EVERY` (default 10) recycles self-launched Affinity to clear tabs 3.2.1 can't close (verified clean, no recovery prompts); close warnings fire once per queue plus an end-of-queue orphan count. (`affinity.py`)
- **Console-safe logging.** stdout/stderr use replace-on-error so non-locale (e.g. Persian) filenames can't crash a job mid-log. (`logger.py`)

---

## 1.2.0 — 2026-07-24

### Added

- **Regenerate Preview button.** Edit the open document in Adobe while the naming prompt is showing, then click "Regen Preview." The document saves, re-exports as PNG, reconverts to AVIF and thumbnail, and the UI updates. The pipeline never leaves the naming step. (`naming.py`, `processor.py`, `ui.py`)
- **Preview version counter** on `NameRequest`. Lets the UI detect when a preview has been regenerated and re-display it. (`naming.py`)

### Fixed

- **Photoshop document accumulation.** `open_file()` now calls `close_all_documents()` before opening a new one. Any error mid-pipeline that prevented the normal close step no longer leaves orphaned documents open in Photoshop. (`photoshop.py`)
- **Illustrator document accumulation.** Same fix for consistency. (`illustrator.py`)
- **Stale document detection.** `wait_until_ready()` now checks that the expected document name has loaded, not just that `Documents.Count > 0`. A leftover document from a previous error no longer causes false ready signals. (`photoshop.py`, `illustrator.py`)
- **Document leak on pipeline error.** `process()` in `processor.py` now has a `finally` block that closes the document if the pipeline exited before reaching the normal close step. (`processor.py`)
- **Missing thumbnail config.** `THUMB_WIDTH`, `THUMB_HEIGHT`, and `THUMB_QUALITY` were referenced by `preview.py` but not defined in `config.py`. Running any queue would crash with `AttributeError` on the first asset. (`config.py`)
- **`needs_restart()` crash.** `_files_opened` was never initialized or incremented, causing `AttributeError` on call. Now initialized to `0` and incremented on each `open_file()`. (`photoshop.py`)

### Changed

- `needs_restart()` now checks `_files_opened % interval == 0` instead of accessing an undefined attribute. (`photoshop.py`)

---

## 1.1.0 — 2026-07-18

### Added

- **EPS support.** `.eps` files are now scanned and processed through the Illustrator pipeline at all routing points (open, export preview, hide layers, save, close, error recovery). (`scanner.py`, `processor.py`)
- **Resume Failed button.** Reads the last session, finds entries that never reached "done" and whose source file is still on disk, and re-queues them. (`session.py`, `ui.py`)

### Fixed

- **Session data was write-only.** `SessionManager.load()` existed but was never called. Added `failed_jobs()` to extract recoverable entries. (`session.py`)
- **Data-loss window in error handling.** `handle_error()` was saving only the failed job to `session.json` while the worker loop's `finally` block saved the full list immediately after. If the app was killed between writes, the session would be corrupt. Removed the redundant partial save. (`processor.py`, `queue.py`)
- **Startup blocked on missing Adobe apps.** Missing Photoshop or Illustrator prevented the app from starting, even if the user only needed one. Now only WinRAR is a hard requirement. Missing Adobe apps log a warning. (`requirements_check.py`, `main.py`)
- **Disk-space wait was unstoppable.** `require_space()` looped on `time.sleep(10)` with no cancellation path. Added `should_continue` polling wired to `queue.running`. (`storage.py`, `main.py`)
- **`AVIF_SPEED` was dead config.** Defined in `config.py` but never passed to `image.save()`. Wired into both the full preview and thumbnail encode calls. (`preview.py`, `config.py`)

---

## 1.0.0 — 2026-07-10

### Added

- Initial release.
- Sequential PSD/AI batch processing pipeline: open, export PNG, convert AVIF, name prompt, hide layers, save, close, rename, archive, verify, cleanup.
- Adobe COM integration for Photoshop and Illustrator.
- Human-in-the-loop naming with visual preview, name normalization, and deduplication.
- PNG-to-AVIF conversion with full preview and thumbnail tier.
- RAR archive creation via WinRAR CLI with integrity verification.
- Persistent session state (`data/session.json`) saved after every job.
- Disk space guard with automatic pause and resume.
- Automatic Adobe restart on recoverable errors.
- Tkinter GUI with dark/light theme toggle, name history, and progress tracking.
- Recursive folder scanning.
- ExtendScript JSX automation for Photoshop and Illustrator.
- Thread-safe event-based communication between UI and worker.
