# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/).
This project adheres to [Semantic Versioning](https://semver.org/).

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
