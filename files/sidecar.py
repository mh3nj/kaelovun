"""
sidecar.py

Optional ``<archive>.kaelovun.json`` written next to each finished archive.

A stable, machine-readable description of what Kaelovun produced, so Evoury
(or any other tool) can index a package without opening the archive.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1


def sidecar_path(archive: Path) -> Path:
    archive = Path(archive)
    return archive.with_name(archive.name + ".kaelovun.json")


def write_sidecar(archive: Path, info: dict) -> Path:
    payload = {
        "schema": SCHEMA_VERSION,
        "tool": "Kaelovun",
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "archive": Path(archive).name,
        "archive_bytes": Path(archive).stat().st_size,
        **info,
    }
    target = sidecar_path(archive)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(target)
    return target
