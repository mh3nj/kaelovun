"""
manifest.py

"Is the archive really what we meant to put in it?"

An expected manifest (path -> size [+ CRC32]) is built from the files on disk
*before* archiving. After archiving, the archive's own listing is compared to it.
Directories are ignored (empty-folder entries are not a content difference), paths
are compared after Unicode NFC normalisation (macOS-made archives use NFD), and a
file that appears twice in the input is simply one entry.
"""

import os
import unicodedata
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from files.archive_backends import ArchiveEntry, norm_path


@dataclass
class ManifestEntry:
    path: str
    size: int
    crc: Optional[int] = None


Manifest = Dict[str, ManifestEntry]


def _key(path: str) -> str:
    return unicodedata.normalize("NFC", norm_path(path))


def crc32_of(path: Path, cancel: Optional[Callable[[], bool]] = None) -> int:
    value = 0
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1 << 20)
            if not chunk:
                break
            value = zlib.crc32(chunk, value)
            if cancel and cancel():
                raise RuntimeError("Cancelled.")
    return value & 0xFFFFFFFF


def build_manifest(root: Path, rel_paths: Optional[Iterable] = None,
                   with_crc: bool = False,
                   cancel: Optional[Callable[[], bool]] = None) -> Manifest:
    """Manifest of ``rel_paths`` under ``root`` (or of every file when None)."""
    root = Path(root)
    if rel_paths is None:
        rel_paths = (
            Path(dp, fn).relative_to(root)
            for dp, _dirs, files in os.walk(root) for fn in files
        )
    manifest: Manifest = {}
    for rel in rel_paths:
        key = _key(str(rel))
        if key in manifest:
            continue
        full = root / rel
        crc = crc32_of(full, cancel) if with_crc else None
        manifest[key] = ManifestEntry(key, full.stat().st_size, crc)
    return manifest


def manifest_from_paths(paths: Iterable[str]) -> Manifest:
    """Names-only manifest (legacy list input)."""
    return {_key(p): ManifestEntry(_key(p), -1) for p in paths}


@dataclass
class VerifyResult:
    missing: List[str] = field(default_factory=list)
    extra: List[str] = field(default_factory=list)
    size_mismatch: List[str] = field(default_factory=list)
    crc_mismatch: List[str] = field(default_factory=list)
    crc_unchecked: int = 0
    checked: int = 0

    @property
    def ok(self) -> bool:
        return not (self.missing or self.extra or self.size_mismatch or self.crc_mismatch)

    def describe(self, limit: int = 5) -> str:
        parts = []
        for label, items in (("missing", self.missing), ("unexpected", self.extra),
                             ("wrong size", self.size_mismatch), ("wrong CRC", self.crc_mismatch)):
            if items:
                shown = ", ".join(items[:limit])
                more = f" (+{len(items) - limit} more)" if len(items) > limit else ""
                parts.append(f"{len(items)} {label}: {shown}{more}")
        return "; ".join(parts) or "ok"


def verify_entries(expected: Manifest, actual: Iterable[ArchiveEntry],
                   check_crc: bool = False) -> VerifyResult:
    """Compare an archive listing against the expected manifest."""
    result = VerifyResult()
    seen: Dict[str, ArchiveEntry] = {}
    for entry in actual:
        if entry.is_dir:
            continue
        seen[_key(entry.path)] = entry

    for key, want in expected.items():
        got = seen.get(key)
        if got is None:
            result.missing.append(key)
            continue
        result.checked += 1
        if want.size >= 0 and got.size != want.size:
            result.size_mismatch.append(key)
            continue
        if check_crc:
            if want.crc is not None and got.crc is not None:
                if want.crc != got.crc:
                    result.crc_mismatch.append(key)
            else:
                result.crc_unchecked += 1
    for key in seen:
        if key not in expected:
            result.extra.append(key)
    return result
