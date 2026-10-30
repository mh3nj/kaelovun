# Upgrading to 1.6.0

This zip has the same layout as your repo, so extract it over your Kaelovun folder.

**Delete these two files afterwards** (a zip can't remove files for you):

- `pipeline/queue.py`  (replaced by `pipeline/jobqueue.py`)
- `CHANGES.md`         (moved to `docs/history/audit-batch-5.md`)

**Your `config.py` is not in this zip** and keeps working: new settings are optional and are read from
`data/settings.json` / sensible defaults. Compare with `config.example.py` if you want the new
`ARCHIVE_PROFILE` keys and the commented `SEVENZIP_PATH` / `WORKSPACE_DIR` lines.

Then:

```bash
pip install -r requirements.txt        # patool (fixed name), Send2Trash, tkinterdnd2
# install 7-Zip (https://www.7-zip.org) if you want 7z output / reading RAR
python main.py                          # Settings > Archive to pick the format
pip install -r requirements-dev.txt && python -m pytest tests/unit
```

First RAR run: please check `data/kaelovun.log` for "Archive manifest mismatch" (RAR creation was not
runnable in the sandbox this release was built in; 7z, ZIP, conversion and extraction were tested against real 7-Zip).
