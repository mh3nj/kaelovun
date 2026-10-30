"""
workspace.py

Where Kaelovun does its scratch work, and how it cleans up after itself.

* The base folder is configurable (Settings > Archive > Workspace folder). Big
  packages are copied/extracted here, so point it at a roomy, fast drive.
* Free space is checked on the drive that will actually be written to.
* Folders left behind by a crash or a killed process are swept at startup.
"""

import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Optional

BASE_NAME = "kaelovun_workspace"
STALE_PREFIXES = ("job_", "convert_")


def workspace_base(prefs=None) -> Path:
    """Base scratch folder (created if needed)."""
    configured = getattr(prefs, "workspace_dir", None) if prefs else None
    base = Path(configured) if configured else Path(tempfile.gettempdir()) / BASE_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def make_workspace(prefix: str, prefs=None) -> Path:
    """A fresh, uniquely named folder under the base."""
    return Path(tempfile.mkdtemp(prefix=prefix, dir=workspace_base(prefs)))


def free_gb(path) -> float:
    probe = Path(path)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free / (1024 ** 3)


def sweep_stale(prefs=None, logger=None, max_age_hours: float = 24) -> int:
    """Delete abandoned job_*/convert_* folders older than ``max_age_hours``."""
    base = workspace_base(prefs)
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for child in base.iterdir():
        if not (child.is_dir() and child.name.startswith(STALE_PREFIXES)):
            continue
        try:
            if child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    if removed and logger:
        logger.info(f"Removed {removed} abandoned workspace folder(s) from {base}")
    return removed


def remove_tree(path: Optional[Path]) -> None:
    """rmtree that also handles read-only files (common on Windows)."""
    if not path or not Path(path).exists():
        return

    def _onerror(func, p, _exc):
        try:
            os.chmod(p, 0o700)
            func(p)
        except OSError:
            pass

    shutil.rmtree(path, onerror=_onerror)
