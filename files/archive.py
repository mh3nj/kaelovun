"""
archive.py

ArchiveManager: build, test and list archives in RAR, 7z or ZIP.

    manager.create(files, output_base, work_dir=..., fmt="7z")   -> Path
    manager.create_tree(folder, output_base, fmt="smallest")     -> Path
    manager.test_archive(path) / list_entries(path) / list_archive(path)

``output_base`` is the destination WITHOUT an extension. The right one is added
for the chosen format, and the real path is returned, so "smallest" (build 7z and
RAR, keep the winner) can decide the extension itself.

``RarArchive`` is kept as an alias, and ``create_rar`` still works, so older code
and scripts keep running.
"""

import os
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from files.archive_prefs import ArchivePrefs, load_prefs
from files.archive_backends import (
    BACKENDS, ArchiveBackend, ArchiveEntry, Cancelled, ToolError, ToolLocator,
    human_size, list_entries as _list_entries, test_archive as _test_archive,
)


class ArchiveManager:

    def __init__(self, config, logger):
        self.config = config
        self.logger = logger

    # ── preferences / tools ──────────────────────────────────

    def prefs(self) -> ArchivePrefs:
        """Always re-read, so Settings changes apply to the very next archive."""
        return load_prefs(self.config)

    def locator(self, prefs: Optional[ArchivePrefs] = None) -> ToolLocator:
        return ToolLocator(prefs or self.prefs())

    def _rar_exe(self) -> Path:
        """Path to Rar.exe (kept for compatibility)."""
        exe = self.locator().rar()
        if not exe:
            raise ToolError(BACKENDS["rar"](self.locator(), self.prefs()).available()[1])
        return exe

    def format_status(self) -> Dict[str, Tuple[bool, str]]:
        """{'rar': (ok, reason), '7z': ..., 'zip': ...} for the UI and CLI."""
        prefs = self.prefs()
        loc = ToolLocator(prefs)
        return {fmt: cls(loc, prefs).available() for fmt, cls in BACKENDS.items()}

    # ── creating ─────────────────────────────────────────────

    def create(self, files: Sequence[Path], output_base: Path,
               work_dir: Optional[Path] = None, fmt: Optional[str] = None,
               progress: Optional[Callable[[float], None]] = None,
               cancel: Optional[Callable[[], bool]] = None,
               prefs: Optional[ArchivePrefs] = None) -> Path:
        """Archive ``files`` (kept relative to ``work_dir``). Returns the archive path."""
        files = [Path(f) for f in files]
        if not files:
            raise ToolError("Nothing to archive: file list is empty.")
        root = Path(work_dir) if work_dir else Path(os.path.commonpath(
            [str(f.parent) for f in files]))
        rel = []
        for f in files:
            try:
                rel.append(str(f.resolve().relative_to(root.resolve())))
            except ValueError:
                raise ToolError(f"{f} is outside the archive root {root}")
        # De-duplicate while keeping order: a file listed twice is still one entry.
        rel = list(dict.fromkeys(rel))
        return self._build(root, rel, output_base, fmt, progress, cancel, prefs)

    def create_tree(self, root: Path, output_base: Path, fmt: Optional[str] = None,
                    progress: Optional[Callable[[float], None]] = None,
                    cancel: Optional[Callable[[], bool]] = None,
                    prefs: Optional[ArchivePrefs] = None) -> Path:
        """Archive a whole folder tree (empty folders included)."""
        return self._build(Path(root), None, output_base, fmt, progress, cancel, prefs)

    def create_rar(self, files, output, work_dir=None):
        """Legacy entry point: always RAR, ``output`` includes ``.rar``."""
        output = Path(output)
        base = output.with_name(output.name[:-4]) if output.name.lower().endswith(".rar") else output
        return self.create(files, base, work_dir=work_dir, fmt="rar")

    def _build(self, root, rel_files, output_base, fmt, progress, cancel, prefs=None) -> Path:
        prefs = prefs or self.prefs()
        fmt = (fmt or prefs.format).lower()
        loc = ToolLocator(prefs)
        output_base = Path(output_base)

        if fmt == "smallest":
            return self._build_smallest(prefs, loc, root, rel_files, output_base, progress, cancel)
        if fmt not in BACKENDS:
            raise ToolError(f"Unknown archive format: {fmt}")
        backend: ArchiveBackend = BACKENDS[fmt](loc, prefs)
        ok, reason = backend.available()
        if not ok:
            raise ToolError(reason)
        out = output_base.with_name(output_base.name + backend.ext)
        self.logger.info(f"Creating {fmt.upper()} archive: {out.name}")
        result = backend.create(out, root, rel_files, progress, cancel)
        self.logger.info(f"Archive created: {out.name} ({human_size(result.stat().st_size)})")
        return result

    def _build_smallest(self, prefs, loc, root, rel_files, output_base, progress, cancel) -> Path:
        candidates = [BACKENDS[f](loc, prefs) for f in ("7z", "rar")]
        usable = [b for b in candidates if b.available()[0]]
        if not usable:
            raise ToolError("Neither 7-Zip nor WinRAR was found. " + candidates[0].available()[1])
        if len(usable) == 1:
            self.logger.warning(
                f"'Smallest' needs both 7-Zip and WinRAR; only {usable[0].fmt} is available, using it.")
        built: List[Path] = []
        try:
            for i, backend in enumerate(usable):
                out = output_base.with_name(output_base.name + backend.ext)
                sub = None
                if progress:
                    sub = (lambda pct, i=i, n=len(usable): progress((i + pct / 100.0) / n * 100.0))
                self.logger.info(f"Smallest mode: building {backend.fmt.upper()}...")
                built.append(backend.create(out, root, rel_files, sub, cancel))
        except BaseException:
            for p in built:
                p.unlink(missing_ok=True)
            raise
        winner = min(built, key=lambda p: p.stat().st_size)
        for p in built:
            if p != winner:
                self.logger.info(f"Smallest mode: dropping {p.suffix} ({human_size(p.stat().st_size)})")
                p.unlink(missing_ok=True)
        self.logger.info(f"Smallest mode: kept {winner.suffix} ({human_size(winner.stat().st_size)})")
        return winner

    # ── reading ──────────────────────────────────────────────

    def test_archive(self, archive: Path, password: Optional[str] = None,
                     progress=None, cancel=None) -> bool:
        archive = Path(archive)
        if not archive.exists():
            self.logger.error(f"Archive not found for testing: {archive}")
            return False
        try:
            ok = _test_archive(archive, self.locator(), password, progress, cancel)
        except Cancelled:
            raise
        except ToolError as exc:
            self.logger.error(f"Archive test could not run: {exc}")
            return False
        if not ok:
            self.logger.error(f"Archive integrity test FAILED: {archive.name}")
        return ok

    def list_entries(self, archive: Path, password: Optional[str] = None,
                     cancel=None) -> List[ArchiveEntry]:
        return _list_entries(Path(archive), self.locator(), password, cancel)

    def list_archive(self, archive: Path) -> List[str]:
        """File paths inside the archive (directories excluded)."""
        try:
            return [e.path for e in self.list_entries(archive) if not e.is_dir]
        except ToolError as exc:
            self.logger.warning(f"Could not list archive {Path(archive).name}: {exc}")
            return []


# Backwards-compatible name used across the code base and older tests.
RarArchive = ArchiveManager
