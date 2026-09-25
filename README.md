<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/banner.webp">
    <img src="assets/banner.webp" alt="Kaelovun">
  </picture>
</p>

<p align="center">
  <strong>Kaelovun</strong>
</p>

<p align="center">
  <strong>Universal Creative Asset Processing & Preservation Engine</strong>
</p>

<p align="center">
  <a href="#"><img src="https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white" alt="Python 3.11+"></a>
  <a href="#"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License"></a>
  <a href="#"><img src="https://img.shields.io/badge/platform-Windows-blue?logo=windows&logoColor=white" alt="Windows"></a>
  <a href="#"><img src="https://custom-icon-badges.demolab.com/badge/Affinity-A7F175?logo=affinitystudio&logoColor=black" alt="Affinity"></a>
  <a href="#"><img src="https://img.shields.io/badge/Adobe-Photoshop-blueviolet?logo=adobephotoshop&logoColor=white" alt="Photoshop"></a>
  <a href="#"><img src="https://img.shields.io/badge/Adobe-Illustrator-orange?logo=adobeillustrator&logoColor=white" alt="Illustrator"></a>
  <a href="docs/affinity-setup.md"><img src="https://img.shields.io/badge/Affinity-supported-68d9f0" alt="Affinity"></a>
  <a href="https://github.com/mh3nj/kaelovun/releases"><img src="https://img.shields.io/badge/release-v1.5.0-brightgreen" alt="Release 1.5.0"></a>
  <a href="https://github.com/mh3nj/evoury"><img src="https://img.shields.io/badge/Evoury-DAM-ff69b4" alt="Evoury DAM"></a>
</p>

---

> **Note:** Kaelovun was previously named **Asset Organizer**. The application was rebranded in v1.3.1. In v1.4.0, Kaelovun evolved into a standalone universal creative-asset processing engine with package-based architecture, archive extraction, and headless CLI operation. In v1.5.0, safe-copy model for all inputs and manifest-based archive verification were added.

Kaelovun processes **any creative asset input** — individual files (PSD, AI, INDD, Affinity formats), directories, or archives (ZIP, RAR, 7z, tar, etc.) — automatically discovering, classifying, and processing them into verified RAR archives with AVIF previews.

**The philosophy:** *"Understand what you can. Preserve what you cannot."*

- **Automatic classification** — No manual mode selection. Kaelovun detects file types and selects the right processor.
- **Package preservation** — Directory structures are preserved. Licenses, docs, fonts, and unknown files are never deleted.
- **Safe archive handling** — Archives are extracted to secure workspaces with depth limiting, path traversal protection, and bomb detection.
- **Verified output** — Every RAR is integrity-tested before any cleanup occurs.
- **Headless-first** — Full CLI for automation, plus GUI for interactive use.
- **Evoury integration** — Works standalone or as Evoury's processing engine.

---

## Pipeline

Each **asset package** (file, directory, or archive) goes through these stages:

| # | Stage | Description |
|---|-------|-------------|
| 1 | **Discover** | Recursively scan input, classify every file |
| 2 | **Extract / Copy** | Archives extracted to isolated workspace; directories/files copied to safe workspace (configurable depth limit for archives) |
| 3 | **Classify** | Transformable / Preservable / Container / License-Doc |
| 4 | **Preview** | Generate AVIF previews + thumbnails for transformable assets |
| 5 | **Process** | Hide layers, save transformable files (Photoshop/Illustrator/Affinity) |
| 6 | **Reconstruct** | Preserve original directory structure in workspace |
| 7 | **Archive** | Create best-compression RAR5 (solid, verified) |
| 8 | **Verify** | Test archive integrity + manifest comparison (confirm all expected files exist) |
| 9 | **Cleanup** | Only after successful verification — remove workspace, keep originals |

---

## Features

- **Universal Input** — Single file, directory, or archive. Kaelovun figures it out.
- **Package Model** — Logical asset packages preserve directory hierarchy (`SOURCE/`, `EXPORT/`, `LICENSE/`, etc.)
- **Processor Architecture** — Photoshop, Illustrator, InDesign, Affinity, Image, PDF, Archive, Preservation processors
- **Conservative Preservation** — Unknown files, licenses, docs, fonts are always preserved
- **Safe Workspace (Safe-Copy Model)** — All inputs (files, directories, archives) copied to isolated workspace before processing; originals never modified
- **Manifest Verification** — RAR contents verified against expected file manifest (not just integrity test)
- **Configurable Preview Formats** — `PREVIEW_FORMAT` / `THUMB_FORMAT` settings (AVIF default, PNG/WebP/etc. supported)
- **Nested Archive Safety** — Configurable depth limit (default 2), preserves beyond boundary
- **Security** — Path traversal protection, symlink safety, archive bomb detection
- **CLI + GUI** — `kaelovun-cli` for automation, Tkinter GUI for interactive use
- **Session Persistence** — Resume interrupted jobs, recover from crashes
- **Verified RAR5** — Best compression, solid archive, integrity + manifest tested

---

## Screenshots

<p align="center">
  <img src="assets/screenshots/screenshots.webp" alt="screenshot" >
</p>

---

## Requirements

### Runtime

| Component | Notes |
|-----------|-------|
| **Windows 10+** | COM interop is Windows-only |
| **Adobe Photoshop CS6+** or **Illustrator CS6+** | Default engine: opening, exporting, layer operations |
| **Adobe InDesign CS6+** | Optional: INDD support |
| **Affinity** (unified Canva-era app) | Optional engine: needs Settings → MCP Server enabled ([setup](docs/affinity-setup.md)) |
| **WinRAR** (`Rar.exe`) | Required for archive creation |

### Development (running from source)

| Dependency | Version |
|-----------|---------|
| Python | 3.11+ |
| `pywin32` | latest |
| `Pillow` | 10.0+ |
| `pillow-avif-plugin` | latest |
| `patoolib` | latest |

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Installation

Kaelovun runs on Windows only (it depends on Adobe COM interop). The setup scripts and manual steps below all assume a Windows environment.

### First run: configuration

Every setup path below needs one manual step the first time:

```bash
copy config.example.py config.py
```

`config.example.py` is a template; the app never imports it. It reads `config.py`, so without that copy the app won't start.

You usually don't need to edit anything afterwards: Adobe and WinRAR paths are **auto-detected** from `C:\Program Files`. Only touch `config.py` if you want to force a specific Adobe version or override defaults. `config.py` is gitignored; only ever push `config.example.py`.

### Prebuilt executable (recommended)

Download the latest `Kaelovun-vX.Y.Z.zip` from the [Releases page](https://github.com/mh3nj/kaelovun/releases). Extract the **entire** archive and run `Kaelovun/Kaelovun.exe`. No Python or dependencies required; everything is bundled.

> **Extract everything, keep the folder together.** The exe needs its `_internal/` folder next to it (it holds `python3xx.dll` and the `scripts/` automation). If you move `Kaelovun.exe` out alone, or run it straight from inside the zip without extracting, Windows shows `Failed to load Python DLL ... _internal/python3xx.dll`. Fix: extract the full zip, then run `Kaelovun/Kaelovun.exe` from the extracted folder.

### Run from source with setup script

The repository includes two scripts that create a virtual environment, install dependencies, and launch the app:

**Windows:**
```batch
setup.bat
```

**Linux / macOS** (for development or testing; Adobe COM is Windows-only, so the pipeline itself will not work):
```bash
chmod +x setup.sh
./setup.sh
```

Each script checks for Python 3.11+, creates a `.venv` if one does not exist, installs `requirements.txt`, and runs `main.py`.

### Run from source manually

```bash
# Clone the repository
git clone https://github.com/mh3nj/kaelovun.git
cd kaelovun

# Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create config.py from the template (one-time; paths auto-detect)
copy config.example.py config.py

# Launch the GUI application
python main.py

# Or run headless CLI
python cli.py --help
```

### Build a standalone executable

```bash
pip install pyinstaller
python -m PyInstaller Kaelovun.spec --noconfirm
```

The runnable app will be at `dist/Kaelovun/Kaelovun.exe` (with `dist/Kaelovun/_internal/` next to it). It includes all dependencies and the `scripts/` folder containing Adobe ExtendScript files. Or run `scripts/build_release.bat`; it builds from the spec, verifies `_internal/python3*.dll` exists, and zips `dist/Kaelovun` to `Kaelovun-vX.Y.Z.zip` for you.

> **Always build from the `.spec` file.** Running `pyinstaller main.py` regenerates the spec with no data files and silently drops the `scripts/` folder, which makes every job fail with "Missing JSX".

> **Never run `build/Kaelovun/Kaelovun.exe`.** The `build/` folder only holds intermediate files; that exe always fails with `Failed to load Python DLL ... build/Kaelovun/_internal/python3xx.dll` because there is no `_internal/` there. Always run `dist/Kaelovun/Kaelovun.exe`.

---

## Usage

### GUI (Interactive)

1. Launch the application: `python main.py` or run `Kaelovun.exe`
2. Click **Select Folder** or **Select File** and choose a folder, file, or archive containing creative assets
3. Click **Start Queue**
4. For each package:
   - A preview appears (representative asset from the package)
   - Type a descriptive name and press Enter or click **Confirm**
   - Optionally, edit the document in Adobe and click **Regen Preview** before confirming
5. The app creates a `.rar` archive preserving the package structure

### CLI (Headless / Automation)

```bash
# Process a single file
python cli.py project.psd

# Process a directory (recursive)
python cli.py /path/to/project_folder

# Process an archive (extracts, processes, re-archives)
python cli.py project.zip

# Resume failed jobs from last session
python cli.py --resume-failed

# Use Affinity engine
python cli.py --engine affinity /path/to/file.afphoto

# Limit archive extraction depth
python cli.py --max-depth 3 archive.rar

# Keep workspace for debugging
python cli.py --no-cleanup project.psd

# List supported formats
python cli.py --list-formats
```

### Controls (GUI)

| Control | Action |
|---------|--------|
| **Select Folder** | Scan a folder recursively for creative assets |
| **Select File** | Select a single file or archive for processing |
| **Resume Failed** | Re-queue incomplete jobs from the last session |
| **Start Queue** | Begin sequential processing |
| **Pause / Resume** | Pause or resume between jobs |
| **Regen Preview** | Re-export the preview from the currently open document (during naming only) |
| **Confirm** | Accept the typed name and continue |
| **Theme** | Toggle dark and light themes |
| **Settings** | Engine, app paths, formats, preview, pipeline, theme |

---

## Configuration

Prefer the in-app route: **Settings** writes to `data/settings.json` (gitignored, machine-local) and applies instantly; no restart, no rebuild. `copy config.example.py config.py` is still the one-time first step (the app only reads `config.py`), but you rarely need to open it: Adobe, Affinity, and WinRAR paths auto-detect from `C:\Program Files`.

`config.py` ships the defaults; `data/settings.json` holds your overrides. Delete `settings.json` (or Settings → Reset defaults) to go back to stock.

| Setting | Default | Description |
|---------|---------|-------------|
| `ENGINE` | `adobe` | `adobe` (Photoshop/Illustrator) or `affinity` (unified app via MCP) |
| `MAX_ARCHIVE_DEPTH` | `2` | Maximum nested archive extraction depth |
| `PREVIEW_WIDTH` | 2000 | Max preview width in pixels |
| `PREVIEW_HEIGHT` | 2000 | Max preview height in pixels |
| `PREVIEW_FORMAT` | `AVIF` | Preview output format (`AVIF`, `PNG`, `WEBP`, etc.) |
| `THUMB_WIDTH` | 400 | Thumbnail width in pixels |
| `THUMB_HEIGHT` | 400 | Thumbnail height in pixels |
| `THUMB_FORMAT` | `AVIF` | Thumbnail output format |
| `AVIF_QUALITY` | 90 | AVIF encode quality (0–100) |
| `AVIF_SPEED` | 6 | AVIF encoding speed (0=slowest/best, 10=fastest) |
| `THUMB_QUALITY` | 70 | Thumbnail quality |
| `MINIMUM_FREE_SPACE_GB` | 1 | Disk space safety threshold |
| `ADOBE_STARTUP_WAIT` | 20 | Seconds to wait for Adobe to launch |
| `ADOBE_RECOVERY_WAIT` | 20 | Seconds to wait after restarting Adobe |
| `DOCUMENT_TIMEOUT` | 60 | Seconds to wait for a document to finish opening |
| `MAX_RETRIES` | 2 | Number of automatic retries on recoverable errors |
| `AFFINITY_MCP_PORT` | 6767 | Local Affinity scripting server port |
| `AFFINITY_STARTUP_WAIT` | 25 | Seconds to wait for Affinity to launch |
| `AFFINITY_RECOVERY_WAIT` | 20 | Seconds to wait after restarting Affinity |
| `AFFINITY_RESTART_EVERY` | 10 | Recycle self-launched Affinity every N files (3.2.1 can't close tabs; 0 = never) |
| `NAMING_MODE` | `manual` | `manual` (prompt) or `automation` (auto-name) |
| `THEME` | `dark` | Startup theme (`dark` or `light`) |

---

## Supported Formats

| Format | Open | Export | Hide Layers | Save | Close |
|--------|------|--------|-------------|------|-------|
| `.psd`, `.psb` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `.ai`, `.eps` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `.indd`, `.indt` | ✓* | ✓* | ✓* | ✓* | ✓* |
| `.afphoto` | Affinity-only | ✓ (1024px) | ✓ (artwork) | native-only | (3.2.1) |
| `.afdesign` | Affinity-only | ✓ (1024px) | ✓ (artwork) | native-only | (3.2.1) |
| `.afpub` | Affinity-only | ✓ (1024px) | ✓ (artwork) | native-only | (3.2.1) |

*InDesign support depends on COM API availability.

**Preserved (not transformed):** PDF, fonts (OTF/TTF/WOFF), images (JPG/PNG/TIFF/WebP/AVIF/HEIC), SVG, unknown files, licenses, documentation.

---

## Archive Handling

Kaelovun safely processes archives:

1. **Extract** to isolated temporary workspace
2. **Inspect** contents for nested archives (depth limited by `MAX_ARCHIVE_DEPTH`)
3. **Classify** every file (transformable / preservable / container / license)
4. **Process** transformable assets in workspace
5. **Reconstruct** preserving original directory structure
6. **Create** verified RAR5 archive
7. **Verify** integrity + manifest comparison before any cleanup

**Security protections:**
- Path traversal (`../`, absolute paths)
- Symlink/hardlink escapes
- Archive bombs (decompression ratio limits)
- Recursive extraction loops
- Malformed archive handling

**Supported archive formats:** ZIP, RAR, 7z, tar, tar.gz, tar.bz2, tar.xz

---

## Evoury Integration

[Evoury](https://github.com/mh3nj/evoury) is a full-featured digital asset management (DAM) platform. It provides an asset grid, catalog browsing, and search across your organized library.

Kaelovun is the **independent** ingestion pipeline for Evoury. Together they form a complete workflow:

```
Source files (PSD/AI/INDD/Affinity/archives/directories)
        │
        ▼
Kaelovun ────→ Verified RAR archives + AVIF previews
(processing engine)        │
                           ▼
                      Evoury DAM
                  (catalog & management)
```

**Key separation:**
- **Evoury:** Asset discovery, library, metadata, organization, search, relationships, UI
- **Kaelovun:** Inspection, classification, processing, transformation, preview generation, package handling, archive extraction, RAR creation, verification, preservation

You can use Kaelovun without Evoury. It produces standard files that work with any file manager or search tool.

---

## Architecture

```
main.py                     GUI entry point
cli.py                      CLI entry point (headless)
├── config.py               Global configuration (local-only, gitignored)
├── config.example.py       Sanitized config template (push to GitHub)
├── logger.py               File, console, and UI logging
├── requirements_check.py   Environment verification
│
├── pipeline/               Processing pipeline
│   ├── processor.py        Main package-based pipeline orchestrator
│   ├── queue.py            Sequential job queue (single-threaded)
│   ├── job.py              Job model and status enum
│   ├── scanner.py          Universal input scanner (file/dir/archive)
│   └── asset_package.py    AssetPackage model + classifier
│
├── adobe/                  Adobe COM integration
│   ├── photoshop.py        Photoshop COM controller
│   ├── illustrator.py      Illustrator COM controller
│   ├── indesign.py         InDesign COM controller (future)
│   ├── jsx_bridge.py       Loads and executes ExtendScript (.jsx)
│   └── recovery.py         Error classification and recovery
│
├── affinity/               Affinity MCP integration (unified Canva-era app)
│   ├── affinity.py         Affinity controller (open/render/hide/save/close)
│   ├── popups.py           Auto-dismiss updater + template/welcome popups
│   └── mcp_client.py       Stdlib-only MCP client (Streamable HTTP + SSE)
│
├── files/                  File operations
│   ├── app_settings.py     Settings store (data/settings.json overrides)
│   ├── archive.py          RAR creation via Rar.exe
│   ├── archive_extraction.py  Safe archive extraction + inspection
│   ├── cleanup.py          Post-verification cleanup
│   ├── filename.py         Name normalization and deduplication
│   ├── naming.py           Thread-safe name prompt
│   ├── preview.py          PNG to AVIF conversion
│   ├── session.py          Session persistence (data/session.json)
│   └── storage.py          Disk space monitoring
│
├── ui/                     User interface
│   ├── app.py              Tkinter GUI
│   └── settings_dialog.py  Settings dialog
│
└── scripts/                Adobe ExtendScript + Affinity JS automation
    ├── photoshop_export.jsx
    ├── illustrator_export.jsx
    ├── indesign_export.jsx  (future)
    └── affinity_pipeline.js
```

---

## Data Safety

**Highest priority: NEVER LOSE USER DATA.**

- Original files are **never modified in place** — all inputs (files, directories, archives) copied to isolated workspace before any processing
- Archive verification **must pass** (integrity + manifest) before any cleanup
- Unknown/unrecognized files are **preserved**, not deleted
- Licenses, EULAs, documentation are **conservatively detected and preserved**
- Crash recovery: `Resume Failed` restores incomplete jobs from session
- Partial processing never destroys originals

---

## Security

Archives are treated as hostile input:

- Path traversal blocked (`../`, absolute paths)
- Symlink/hardlink escapes prevented
- Archive bomb detection (decompression ratio monitoring)
- Recursive extraction depth limited (configurable)
- No arbitrary file execution
- Extracted content never escapes controlled workspace

---

## Testing

Run tests:

```bash
# Unit tests (no Adobe required)
python -m pytest tests/unit -v

# Integration tests (require Adobe/Affinity)
python -m pytest tests/integration -v

# All tests
python -m pytest tests/ -v
```

Test coverage includes:
- Individual PSD/AI/INDD/Affinity files
- Mixed directories with subdirectories
- ZIP/RAR/7z/tar archives
- Nested archives (depth limiting)
- Unknown file preservation
- License/document detection
- Unicode filenames, long paths, spaces
- Archive corruption handling
- Processing failure recovery
- Resume behavior
- Verification failure handling

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## License

MIT. See [LICENSE](LICENSE) for details.

---

<p align="center">
  <sub>Kaelovun — Universal Creative Asset Processing & Preservation Engine</sub>
</p>
<p align="center">
  <sub>Ingestion pipeline for <a href="https://github.com/mh3nj/evoury">Evoury</a> — works standalone</sub>
</p>