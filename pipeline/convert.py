"""
convert.py

Convert existing archives between formats (RAR <-> 7z <-> ZIP, TAR.* -> any).

Nothing else touches the archive: no Adobe, no previews, no renaming of the
contents. The contents go in exactly as they came out.

Safety model
------------
* The source archive is never modified. The result is built under a temporary name
  next to its destination and only renamed into place after it has passed:
    1. extraction check   - what came out matches what the source archive lists
    2. the archiver's own integrity test
    3. content check      - every file present with the right size (+CRC32 if paranoid)
* Only ONE archive layer is unpacked. Archives nested inside are copied untouched.
* The result never overwrites anything: an existing name gets " (2)", " (3)", ...
* By default a conversion that does not make the file smaller is discarded.
* "Delete the original" means the Recycle Bin, never a permanent delete.
"""

import dataclasses
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Tuple

from files.archive import ArchiveManager
from files.archive_backends import (
    ArchiveEntry, Cancelled, PasswordRequired, ToolError, human_size,
)
from files.archive_extraction import ArchiveExtractor, ArchiveSecurityError
from files.archive_prefs import FORMATS, LEVELS, load_prefs
from files.filename import FilenameManager
from files.manifest import ManifestEntry, build_manifest, verify_entries
from files.workspace import free_gb, make_workspace, remove_tree

PART_MARK = ".kaelovun-part"
CONVERT_TARGETS = ("7z", "rar", "zip")

_RAR_PART = re.compile(r"^(?P<base>.+)\.part0*(?P<num>\d+)\.rar$", re.I)
_SPLIT = re.compile(r"^(?P<base>.+\.(?:7z|zip|rar))\.(?P<num>\d{3})$", re.I)
_ARCHIVE_SUFFIXES = (".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".tbz2", ".txz",
                     ".tar", ".zip", ".rar", ".7z")


# ──────────────────────────────────────────────────────────────
# Data
# ──────────────────────────────────────────────────────────────

@dataclass
class ConvertOptions:
    target: str = "7z"                      # 7z | rar | zip
    level: Optional[str] = None             # None = Settings default
    keep_original: str = "keep"             # keep | recycle
    output_dir: Optional[Path] = None       # None = next to the source
    only_if_smaller: bool = True
    preserve_mtime: bool = True
    password: Optional[str] = None
    dry_run: bool = False
    verify: Optional[str] = None            # standard | paranoid | None = Settings default


@dataclass
class ConvertResult:
    source: Path
    status: str = "failed"                  # converted | skipped | failed | cancelled | dry-run
    reason: str = ""
    output: Optional[Path] = None
    src_bytes: int = 0
    out_bytes: int = 0
    file_count: int = 0
    unpacked_bytes: int = 0
    seconds: float = 0.0
    volumes: List[Path] = field(default_factory=list)
    original_removed: bool = False

    @property
    def saved_bytes(self) -> int:
        return self.src_bytes - self.out_bytes if self.status == "converted" else 0

    @property
    def saved_pct(self) -> float:
        return (self.saved_bytes / self.src_bytes * 100.0) if self.src_bytes and self.status == "converted" else 0.0

    def line(self) -> str:
        name = self.source.name
        if self.status == "converted":
            sign = "saved" if self.saved_bytes >= 0 else "grew by"
            return (f"OK   {name} -> {self.output.name}  "
                    f"{human_size(self.src_bytes)} -> {human_size(self.out_bytes)} "
                    f"({sign} {human_size(abs(self.saved_bytes))}, {abs(self.saved_pct):.0f}%)")
        if self.status == "dry-run":
            return f"PLAN {name}: {self.reason}"
        tag = {"skipped": "SKIP", "cancelled": "STOP"}.get(self.status, "FAIL")
        return f"{tag} {name}: {self.reason}"


Progress = Optional[Callable[[str, Optional[float]], None]]


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def is_convertible(path: Path) -> bool:
    name = Path(path).name.lower()
    if PART_MARK in name:
        return False
    return name.endswith(_ARCHIVE_SUFFIXES) or bool(_SPLIT.match(name))


def archive_stem(path: Path) -> str:
    """File name without the archive extension (handles .tar.gz and volume suffixes)."""
    name = Path(path).name
    m = _RAR_PART.match(name)
    if m:
        return m.group("base")
    m = _SPLIT.match(name)
    if m:
        name = m.group("base")
    low = name.lower()
    for suffix in _ARCHIVE_SUFFIXES:
        if low.endswith(suffix):
            return name[: -len(suffix)]
    return Path(name).stem


def find_volumes(path: Path) -> Tuple[bool, List[Path]]:
    """
    (is_first_volume, all_volumes). A single archive is (True, [path]).
    Understands name.partN.rar, name.rar + name.r00.., and name.7z.001 / .zip.001.
    """
    path = Path(path)
    folder = path.parent
    m = _RAR_PART.match(path.name)
    if m:
        base = m.group("base").lower()
        vols = sorted(
            (p for p in folder.iterdir()
             if (mm := _RAR_PART.match(p.name)) and mm.group("base").lower() == base),
            key=lambda p: int(_RAR_PART.match(p.name).group("num")))
        return int(m.group("num")) == 1, vols or [path]
    m = _SPLIT.match(path.name)
    if m:
        base = m.group("base").lower()
        vols = sorted(
            (p for p in folder.iterdir()
             if (mm := _SPLIT.match(p.name)) and mm.group("base").lower() == base),
            key=lambda p: int(_SPLIT.match(p.name).group("num")))
        return int(m.group("num")) == 1, vols or [path]
    if re.search(r"\.r\d\d$", path.name, re.I):
        return False, [path]
    if path.suffix.lower() == ".rar":
        extras = sorted(p for p in folder.glob(f"{glob_escape(path.stem)}.r[0-9][0-9]"))
        return True, [path] + extras
    return True, [path]


def glob_escape(text: str) -> str:
    return re.sub(r"([\[\]*?])", r"[\1]", text)


# ──────────────────────────────────────────────────────────────
# Converter
# ──────────────────────────────────────────────────────────────

class ArchiveConverter:

    def __init__(self, config, logger, archive_manager: Optional[ArchiveManager] = None):
        self.config = config
        self.logger = logger
        self.archive = archive_manager or ArchiveManager(config, logger)
        self.extractor = ArchiveExtractor(config, logger)
        self.filename = FilenameManager(logger)

    # ── discovery ────────────────────────────────────────────

    def discover(self, paths: Iterable, recursive: bool = True) -> List[Path]:
        """Expand files/folders into the archives to convert (first volumes only)."""
        found: List[Path] = []
        seen = set()

        def add(p: Path):
            key = p.resolve()
            if key in seen or not is_convertible(p):
                return
            first, _vols = find_volumes(p)
            if not first:
                return
            seen.add(key)
            found.append(p)

        for raw in paths:
            p = Path(raw)
            if p.is_dir():
                walker = os.walk(p) if recursive else [(str(p), [], [f.name for f in p.iterdir() if f.is_file()])]
                for dirpath, dirnames, filenames in walker:
                    dirnames.sort()
                    for fn in sorted(filenames):
                        add(Path(dirpath, fn))
            elif p.is_file():
                add(p)
        return found

    # ── batch ────────────────────────────────────────────────

    def convert_many(self, paths: Iterable, opts: ConvertOptions, progress: Progress = None,
                     cancel: Optional[Callable[[], bool]] = None,
                     on_result: Optional[Callable[[ConvertResult], None]] = None) -> List[ConvertResult]:
        results: List[ConvertResult] = []
        targets = self.discover(paths)
        for i, path in enumerate(targets):
            if cancel and cancel():
                break
            wrapped = None
            if progress:
                wrapped = (lambda stage, pct, i=i, n=len(targets), name=path.name:
                           progress(f"[{i + 1}/{len(targets)}] {name}: {stage}", pct))
            result = self.convert(path, opts, wrapped, cancel)
            results.append(result)
            if on_result:
                on_result(result)
        return results

    @staticmethod
    def summarize(results: List[ConvertResult]) -> str:
        done = [r for r in results if r.status == "converted"]
        skipped = [r for r in results if r.status == "skipped"]
        failed = [r for r in results if r.status in ("failed", "cancelled")]
        src = sum(r.src_bytes for r in done)
        out = sum(r.out_bytes for r in done)
        text = f"{len(done)} converted, {len(skipped)} skipped, {len(failed)} failed"
        if done:
            delta = src - out
            word = "saved" if delta >= 0 else "grew by"
            pct = abs(delta) / src * 100 if src else 0
            text += f" | {human_size(src)} -> {human_size(out)} ({word} {human_size(abs(delta))}, {pct:.0f}%)"
        return text

    # ── single archive ───────────────────────────────────────

    def convert(self, source: Path, opts: ConvertOptions, progress: Progress = None,
                cancel: Optional[Callable[[], bool]] = None) -> ConvertResult:
        started = time.monotonic()
        source = Path(source)
        result = ConvertResult(source=source)
        scratch: dict = {}
        try:
            self._convert(source, opts, result, progress, cancel, scratch)
        except Cancelled:
            result.status, result.reason = "cancelled", "Cancelled."
        except PasswordRequired:
            result.status, result.reason = "skipped", "password-protected (enter the password to convert it)"
        except ArchiveSecurityError as exc:
            result.status, result.reason = "failed", f"refused for safety: {exc}"
        except Exception as exc:
            result.status, result.reason = "failed", str(exc)
        finally:
            # Whatever happened, leave nothing behind but a finished, verified result.
            partial = scratch.get("partial")
            if partial and Path(partial).exists():
                try:
                    Path(partial).unlink()
                except OSError:
                    pass
            remove_tree(scratch.get("workspace"))
        result.seconds = time.monotonic() - started
        self.logger.info(result.line())
        return result

    def _say(self, progress: Progress, stage: str, pct: Optional[float] = None):
        if progress:
            progress(stage, pct)

    def _convert(self, source: Path, opts: ConvertOptions, result: ConvertResult,
                 progress: Progress, cancel, scratch: dict) -> None:
        prefs = load_prefs(self.config)
        changes = {}
        if opts.level in LEVELS:
            changes["level"] = opts.level
        if opts.verify in ("standard", "paranoid"):
            changes["verify"] = opts.verify
        if changes:
            prefs = dataclasses.replace(prefs, **changes)

        target = opts.target.lower()
        if target not in CONVERT_TARGETS:
            raise ToolError(f"Unknown target format: {opts.target}")

        if not source.exists():
            raise ToolError("file not found")
        if source.is_dir() or not is_convertible(source):
            result.status, result.reason = "skipped", "not a supported archive"
            return
        first, volumes = find_volumes(source)
        if not first:
            result.status, result.reason = "skipped", "part of a multi-volume set; select the first part"
            return
        result.volumes = volumes
        result.src_bytes = sum(v.stat().st_size for v in volumes)

        backend_ok, why = self.archive.format_status()[target]
        if not backend_ok:
            raise ToolError(why)

        out_dir = Path(opts.output_dir) if opts.output_dir else source.parent
        stem = self.filename.normalize(archive_stem(source)) or "archive"
        ext = "." + target
        final = self.filename.unique_path(out_dir, stem, ext)

        self.extractor.cancel = cancel
        self.extractor.password = opts.password

        # 1. Inspect (never unpacks)
        self._say(progress, "inspecting", None)
        report = self.extractor.inspect(source, opts.password)
        result.file_count = report.file_count
        result.unpacked_bytes = report.total_bytes

        if opts.dry_run:
            result.status = "dry-run"
            result.reason = (f"{report.file_count} file(s), {human_size(report.total_bytes)} unpacked "
                             f"-> {final.name}")
            return

        out_dir.mkdir(parents=True, exist_ok=True)
        need_gb = result.src_bytes * 1.1 / (1024 ** 3)
        if free_gb(out_dir) < need_gb:
            raise ToolError(f"not enough free space in {out_dir} (need about {need_gb:.1f} GB)")

        workspace = make_workspace("convert_", prefs)
        scratch["workspace"] = workspace
        content = workspace / "content"

        # 2. Unpack ONE layer
        self._say(progress, "extracting", None)
        self.extractor.progress = (lambda pct: self._say(progress, "extracting", pct)) if progress else None
        self.extractor.extract_single(source, content, opts.password, archive_bytes=result.src_bytes)

        # 3. Did we get out exactly what the archive says is in it?
        self._say(progress, "checking extraction", None)
        paranoid = prefs.verify == "paranoid"
        extracted = build_manifest(content, None, with_crc=paranoid, cancel=cancel)
        from_source = {
            _k(e.path): ManifestEntry(_k(e.path), e.size, e.crc if paranoid else None)
            for e in report.files
        }
        check = verify_entries(
            from_source,
            [ArchiveEntry(path=m.path, size=m.size, crc=m.crc) for m in extracted.values()],
            check_crc=paranoid)
        if not check.ok:
            raise ToolError(f"extraction does not match the source archive ({check.describe()})")

        # 4. Build the new archive under a temporary name
        partial_base = out_dir / f"{stem}{PART_MARK}"
        scratch["partial"] = partial_base.with_name(partial_base.name + ext)
        self._say(progress, "compressing", 0.0)
        partial = self.archive.create_tree(
            content, partial_base, fmt=target, cancel=cancel, prefs=prefs,
            progress=(lambda pct: self._say(progress, "compressing", pct)) if progress else None)
        scratch["partial"] = partial

        # 5. Verify it
        self._say(progress, "verifying", None)
        if prefs.test and not self.archive.test_archive(partial, cancel=cancel):
            raise ToolError("the new archive failed its integrity test")
        listing = self.archive.list_entries(partial, cancel=cancel)
        check = verify_entries(extracted, listing, check_crc=paranoid)
        if not check.ok:
            raise ToolError(f"the new archive does not match its contents ({check.describe()})")

        result.out_bytes = partial.stat().st_size

        # 6. Worth keeping?
        if opts.only_if_smaller and result.out_bytes >= result.src_bytes:
            result.status = "skipped"
            result.reason = (f"{target} would not be smaller ({human_size(result.out_bytes)} vs "
                             f"{human_size(result.src_bytes)}); original left alone")
            return

        # 7. Publish atomically, never over anything that exists.
        final = self.filename.unique_path(out_dir, stem, ext)
        os.replace(partial, final)
        scratch["partial"] = None
        if opts.preserve_mtime:
            try:
                st = source.stat()
                os.utime(final, (st.st_atime, st.st_mtime))
            except OSError:
                pass
        result.output = final
        result.status = "converted"

        # 8. Optionally recycle the original (only after everything above passed)
        if opts.keep_original == "recycle":
            result.original_removed = self._recycle(volumes)

    def _recycle(self, paths: List[Path]) -> bool:
        try:
            from send2trash import send2trash
        except ImportError:
            self.logger.warning("Send2Trash is not installed; the original was kept. "
                                "Install it with: pip install Send2Trash")
            return False
        try:
            for p in paths:
                send2trash(str(p))
            return True
        except Exception as exc:
            self.logger.warning(f"Could not move the original to the Recycle Bin: {exc}")
            return False


def _k(path: str) -> str:
    import unicodedata
    from files.archive_backends import norm_path
    return unicodedata.normalize("NFC", norm_path(path))
