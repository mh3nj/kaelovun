# Known Limitations

## Summary

| Issue | Status | Impact |
|-------|--------|--------|
| EPS may trigger Illustrator save dialog | Adobe limitation | Pipeline pauses until dialog is dismissed |
| Photoshop required for PSD files | Expected (Adobe engine) | Non-PSD workflows unaffected |
| Illustrator required for AI/EPS files | Expected (Adobe engine) | Non-AI workflows unaffected |
| Affinity MCP server off / Affinity closed | Expected (Affinity engine) | Startup warns; Affinity jobs fail with a clear message |
| Session file can corrupt on crash | Known | Delete `data/session.json` to recover |
| Source file deletion race with antivirus | Known | May require manual cleanup |
| Single-threaded queue | By design | Processing time is linear per file |
| No InDesign (.indd) support | Unimplemented | — |
| WinRAR path is hardcoded in config.py | By design | Requires rebuild to change |
| DPI issues on mixed-monitor setups | tkinter limitation | Visual only |
| ~~`queue.py` shadows stdlib `queue`~~ | Resolved in 1.6.0 | Renamed to `jobqueue.py` |

---

## EPS save dialog

**Status:** Adobe limitation  
**Impact:** Pipeline pauses until dialog is dismissed

Illustrator may prompt for EPS export options when saving an `.eps` file via COM. This does not happen with `.ai` or `.psd` files.

**Workaround:** Before processing EPS files, disable "Show Export Options when Saving EPS" in Illustrator (Edit → Preferences → File Handling & Clipboard).

**Root cause:** EPS uses a different internal save path. The COM `Save()` call triggers the export options dialog for EPS output.

---

## Affinity close/save on build 3.2.1

**Status:** Verified upstream gap (Canva's own SDK tests: "waiting for close to be fixed")
**Impact:** Tabs accumulate; PSDs archive with layers as-is

- `doc.close()` / `closeAsync()` throw `NOT_IMPLEMENTED` — nothing can close tabs yet. Split large batches; close tabs by hand.
- `doc.save()` throws `SAVE_TO_TEMPORARY_ARCHIVE_ERROR` for PSD imports (no PSD write-back). Rename, archive, verify, and cleanup still run on the original bytes.
- Hide layers **works** (`selectAll()` + `hideSelection()`, render-confirmed), but only affects the in-memory view since save can't persist it for PSDs.
- Renders cap at 1024px (`render_spread` limit).

**Workaround:** None needed for organizing — previews, naming, archives all work. For clean-layer archives, prefer the Adobe engine until Canva ships the fix.

---

## Affinity PSD/AI fidelity

**Status:** Affinity limitation
**Impact:** Previews (and archives) may differ from Adobe's rendering

Affinity imports PSD/AI as an approximation: exotic effects, smart objects, and artboards may rasterize or shift. Always check the preview at the naming prompt before confirming.

---

## Session file corruption
**Status:** Known  
**Impact:** Resume Failed becomes unavailable until the file is removed

If the app is force-killed during `session.save()`, `data/session.json` may be left in a partially written state. On the next launch, `SessionManager.load()` raises `json.JSONDecodeError`.

**Workaround:** Delete `data/session.json` from the `data/` directory and restart. Session data is informational only. The application works without it. "Resume Failed" will not be available until a new session is saved.

---

## Source file deletion race

**Status:** Known  
**Impact:** May require manual cleanup

After the RAR archive is verified, `cleanup.py` deletes the source file. On Windows, antivirus software or Windows Search Indexer may hold an open handle. The cleanup retries with 1-second delays for up to 5 attempts, then raises an error.

**Workaround:** Delete the source file manually. The archive and AVIF are already complete and verified.

---

## Single-threaded queue

**Status:** By design  
**Impact:** Large batches take linear time

The queue processes all assets sequentially on a single worker thread. For batches of 1000+ files, total time is the sum of per-file processing time.

**Rationale:**

- Adobe COM is single-threaded and does not benefit from concurrency.
- Multiple Adobe instances would consume excessive memory and license seats.
- Each file opens only after the previous one is fully closed.

---

## No InDesign support

**Status:** Unimplemented

`.indd` files are not supported. Adding support would require:

- A new `indesign.py` COM controller
- An InDesign ExtendScript for PNG export
- Routing additions in `processor.py`

---

## WinRAR path is hardcoded

**Status:** By design  
**Impact:** Requires rebuild to use a custom WinRAR installation path

The WinRAR path defaults to `C:\Program Files\WinRAR\Rar.exe` in `config.py`. There is no runtime path configuration.

**Workaround:** Edit `config.py` and rebuild with PyInstaller.

---

## DPI / multi-monitor scaling

**Status:** tkinter limitation  
**Impact:** Visual blurriness on mixed-DPI setups

On Windows systems with different DPI scaling across multiple monitors, the tkinter UI may appear blurry. This is a known limitation of tkinter.

---

## `queue.py` namespace collision (resolved in 1.6.0)

**Status:** fixed: the module is now `pipeline/jobqueue.py`.

**Status:** Design debt  
**Impact:** May affect future library dependencies

The project's `queue.py` shadows the Python standard library `queue` module (which provides `Queue`, `LifoQueue`, and `PriorityQueue`). PyInstaller warns about this during builds. Any third-party library importing from the standard `queue` may resolve to the wrong module.

**Recommendation:** Rename `queue.py` to `jobqueue.py` and update all imports. The project's own code is not affected — it never imports from stdlib `queue` — but this should be addressed before adding new dependencies.

---

## Unsupported configurations

| Configuration | Reason |
|---------------|--------|
| macOS / Linux | COM interop is Windows-only |
| Adobe CS5 or earlier | Untested; COM API may differ |
| Network or portable drives | Disk space checks and file locking may behave differently |
