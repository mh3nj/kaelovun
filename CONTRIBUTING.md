# Contributing

Thank you for considering a contribution. This document covers the practical details: how to set up a development environment, what the conventions are, and how to submit changes.

---

## Code of conduct

This project follows a standard [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you agree to uphold it. If you encounter unacceptable behavior, open an issue or contact the maintainers.

---

## How to contribute

### Reporting bugs

Open an issue and include:

- The version or commit hash you are running
- Your Windows version and Adobe version (Photoshop, Illustrator, or both)
- What you expected to happen
- What actually happened
- Any log output from `data/kaelovun.log` or the UI log area

### Suggesting features

Open an issue describing the problem you want to solve. Focus on the use case rather than a specific implementation. Feature requests that align with the [roadmap](ROADMAP.md) are more likely to be accepted.

### Submitting pull requests

1. Open an issue describing what you plan to change, unless it is a small fix.
2. Fork the repository and create a branch from `main`.
3. Make your changes.
4. Run the syntax check: `python -m py_compile` on each modified `.py` file.
5. Test the queue with at least one `.psd` file to confirm the pipeline completes end to end.
6. Update the relevant documentation if your change affects behavior, configuration, or the UI.
7. Open a pull request against `main`.

---

## Development setup

### Requirements

- Windows 10+
- Python 3.11+
- Adobe Photoshop and/or Illustrator (any version CS6+)
- WinRAR (for archive testing)

### Setup

```bash
git clone https://github.com/mh3nj/kaelovun.git
cd kaelovun
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Configuration

Edit `config.py` to point to your Adobe and WinRAR installations:

```python
self.PHOTOSHOP_PATH = Path(r"C:\Program Files\Adobe\Adobe Photoshop [VERSION]\Photoshop.exe")
self.ILLUSTRATOR_PATH = Path(r"C:\Program Files\Adobe\Adobe Illustrator [VERSION]\Support Files\Contents\Windows\Illustrator.exe")
self.WINRAR_PATH = Path(r"C:\Program Files\WinRAR\Rar.exe")
```

### Launch

```bash
python main.py
```

---

## Project structure

```
main.py                  Entry point — wires all components
config.py                Global configuration
logger.py                Logging (file + console + UI)
requirements_check.py    Environment verification on startup

scanner.py               Recursive folder scanning
queue.py                 Sequential job queue
processor.py             Main pipeline orchestrator
job.py                   Job model and status enum

photoshop.py             Photoshop COM controller
illustrator.py           Illustrator COM controller
jsx_bridge.py            ExtendScript (.jsx) loader and executor
naming.py                Thread-safe name prompt
preview.py               PNG to AVIF conversion
filename.py              Name normalization and deduplication

archive.py               RAR creation and verification
storage.py               Disk space monitoring
cleanup.py               Post-archive source deletion
session.py               Session persistence
adobe_recovery.py        Error classification and automatic recovery

ui.py                    Tkinter graphical interface

scripts/
    photoshop_export.jsx  Photoshop ExtendScript automation
    illustrator_export.jsx Illustrator ExtendScript automation
```

---

## Coding conventions

- **Python 3.11+** — the minimum supported version. Use modern syntax where appropriate.
- **No type annotations required** — the codebase does not use them consistently and there is no type checker configured.
- **Imports** — standard library first, then third-party, then local. One import per line.
- **Docstrings** — present on classes and public methods. Short descriptions are fine. Keep them accurate.
- **Error handling** — use exceptions for control flow in the pipeline. The `handle_error` method in `processor.py` classifies errors as recoverable or fatal.
- **COM calls** — wrap in try/except. Adobe COM can throw `com_error` for transient issues.
- **Logging** — use `self.logger` everywhere. Include the filename of the affected asset when relevant.
- **No print()** — use the logger. The logger writes to a file, the console, and the UI log area.

### Threading notes

The application has two threads: the UI thread (tkinter main loop) and a worker thread (the queue). Communication between them uses `threading.Event`.

- Never call Adobe COM from the UI thread.
- Never block the UI thread with I/O or COM calls.
- The `NameRequest` class is the only cross-thread communication channel. Use it if you add new interactive features.

---

## Testing

The project does not have an automated test suite. Manual testing is required:

1. Run the queue with a small folder of test files.
2. Verify each stage of the pipeline completes (preview export, AVIF conversion, naming, layer hiding, save, close, rename, archive, cleanup).
3. Test the "Resume Failed" flow by killing the app mid-queue and restarting.
4. Test "Regen Preview" by editing the document in Adobe during the naming step.

---

## Documentation

If you change user-facing behavior, update these files:

- `README.md` — for new features, changed workflows, or new configuration options
- `issues.md` — for new known limitations
- `CHANGELOG.md` — add an entry under the next version number

---

## Release process

1. Update the version number in `CHANGELOG.md` and `config.py` if applicable.
2. Run `python -m PyInstaller Kaelovun.spec --noconfirm`.
3. Test the built executable from `dist/Kaelovun/`.
4. Create a GitHub release with the executable attached and a summary of changes.
