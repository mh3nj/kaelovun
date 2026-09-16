# Roadmap

Planned features and development priorities for Kaelovun.

---

## Near-term

### InDesign (.indd) support

Add a new `indesign.py` COM controller matching the structure of `photoshop.py` and `illustrator.py`. This would enable the full pipeline for InDesign documents: open, export preview, save, and close.

- New COM bindings for InDesign
- ExtendScript for InDesign PNG export
- Integration into `processor.py` routing
- Inclusion in `scanner.py` file discovery

### `queue.py` rename

Rename the project's `queue.py` to `jobqueue.py` to remove the stdlib namespace collision. This is a prerequisite for adding dependencies that import from Python's standard `queue` module.

### Parallel preview conversion

Move PNG-to-AVIF conversion to a thread pool so the CPU-bound encode can overlap with the next job's Adobe export. The pipeline stays sequential in terms of Adobe operations; only the encode step becomes concurrent.

### Evoury API integration

Push completed asset metadata directly to Evoury's API after each job. This would let the DAM catalog update automatically as files are organized.

---

## Medium-term

### Watch folder / hot folder mode

Monitor a folder for new Adobe files and queue them automatically. No manual scanning needed. Drop a PSD into the watched folder and the pipeline picks it up.

- Filesystem watcher via `ReadDirectoryChangesW` (Windows)
- Debounce rapid saves from Adobe auto-save
- Optional: move processed files to an organized archive folder

### Batch rename without re-archiving

Allow renaming already-organized assets by updating the RAR archive in-place. Useful when a name could be more descriptive.

### AI-assisted naming suggestions

Use a local or cloud-based vision model to suggest descriptive keywords from the asset preview. The user can accept, edit, or override.

- Local option: ONNX Runtime with a small image captioning model
- Cloud option: OpenAI or Anthropic API with vision support (opt-in)

### Export profiles

Support multiple output configurations:

| Profile | Preview | Thumbnail | Archive |
|---------|---------|-----------|---------|
| Full | 2000px AVIF | 400px AVIF | RAR (source + AVIF) |
| Light | 2000px AVIF | 400px AVIF | None |
| Minimal | 2000px JPEG | — | ZIP (source only) |

---

## Long-term

### Network and cloud watch folders

Extend the hot folder feature to network shares and cloud storage (OneDrive, Dropbox, Google Drive). Handle partial writes, slow sync, and conflict files.

### Web UI

A lightweight web interface for remote operation:

- Start, stop, and monitor the queue from a browser
- Name assets from a tablet or second screen
- Mobile-friendly preview viewing

### Plugin system

A documented API for custom extensions:

- Export formats (WebP, JPEG-XL, PDF)
- Naming engines (auto-tagging, metadata extraction)
- Archive formats (ZIP, 7z, tar.gz)
- Post-processing hooks (upload to CDN, notify Slack, update CMS)

### Multi-worker queue

On server-class machines with multiple Adobe licenses, distribute jobs across multiple Adobe instances (one per worker process). Each worker gets its own Adobe COM connection.

### Asset versioning

Track versions of the same asset:

- `logo_v1.rar`, `logo_v2.rar`
- Compare current and previous previews
- Rollback to an earlier version

---

## Completed

### 1.2.0

- Regenerate Preview button
- Photoshop document leak fix
- Missing thumbnail configuration fix
- Document name verification in `wait_until_ready()`

### 1.1.0

- EPS format support
- Resume Failed session recovery
- Disk space wait cancellation
- Startup requirement relaxation

### 1.0.0

- Initial release with PSD/AI pipeline
- Human-in-the-loop naming
- AVIF conversion with thumbnails
- RAR archiving with verification
- Session persistence
- Tkinter UI
