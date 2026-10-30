"""
archive_extraction.py

Safe archive extraction with real security boundaries.
Supports: ZIP, RAR, 7z, tar, tar.gz, tar.bz2, tar.xz

What "safe" means here, and where each check lives:

* Before anything is written, the archive is *inspected* (listed, never unpacked):
  path traversal / absolute paths / drive letters, entry count, total unpacked
  size, unpack-to-archive ratio, encryption, and links are all judged up front.
* ZIP and TAR are unpacked by streaming code that enforces the byte limit on the
  data actually written (headers can lie), restores timestamps, and refuses to
  create links or devices.
* RAR / 7z / anything else is unpacked by 7-Zip *after* the same inspection,
  with links excluded.
* Every extraction ends with a sweep: nothing may sit outside the destination and
  no link or junction may exist inside it.

Limits are configurable (Settings > Archive > Safety limits).
"""

import os
import shutil
import tarfile
import tempfile
import zipfile
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from files.archive_prefs import ArchivePrefs, load_prefs
from files.archive_backends import (
    ArchiveEntry, Cancelled, PasswordRequired, SevenZip, ToolError, ToolLocator,
    archive_kind, human_size, list_entries, norm_path,
)

CHUNK = 1 << 20


class ArchiveSecurityError(RuntimeError):
    """The archive violates a safety rule and was refused."""


# ──────────────────────────────────────────────────────────────
# Path rules
# ──────────────────────────────────────────────────────────────

_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def unsafe_reason(name: str) -> Optional[str]:
    """Why ``name`` must not be extracted, or None when it is fine."""
    n = name.replace("\\", "/")
    if "\x00" in n:
        return "NUL byte in name"
    if n.startswith("/") or _DRIVE_RE.match(n):
        return "absolute path"
    parts = [p for p in n.split("/") if p]
    if ".." in parts:
        return "path traversal (..)"
    if os.name == "nt" and any(":" in p for p in parts):
        return "alternate data stream / drive reference"
    return None


def _inside(dest: Path, target: Path) -> bool:
    dest_real = os.path.realpath(dest)
    target_real = os.path.realpath(target)
    return target_real == dest_real or target_real.startswith(dest_real + os.sep)


def _is_reparse(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(os.path, "isjunction", None)
        return bool(is_junction and is_junction(path))
    except OSError:
        return False


# ──────────────────────────────────────────────────────────────
# Inspection
# ──────────────────────────────────────────────────────────────

@dataclass
class InspectionReport:
    entries: List[ArchiveEntry]
    archive_bytes: int
    total_bytes: int = 0
    file_count: int = 0
    encrypted: bool = False
    links: List[str] = field(default_factory=list)
    unsafe: List[Tuple[str, str]] = field(default_factory=list)

    @property
    def ratio(self) -> float:
        return self.total_bytes / max(1, self.archive_bytes)

    @property
    def files(self) -> List[ArchiveEntry]:
        return [e for e in self.entries if not e.is_dir and not e.is_link]


def build_report(entries: List[ArchiveEntry], archive_bytes: int) -> InspectionReport:
    report = InspectionReport(entries=entries, archive_bytes=archive_bytes)
    for entry in entries:
        reason = unsafe_reason(entry.path)
        if reason:
            report.unsafe.append((entry.path, reason))
        if entry.is_link:
            report.links.append(entry.path)
        if entry.encrypted:
            report.encrypted = True
        if not entry.is_dir and not entry.is_link:
            report.file_count += 1
            report.total_bytes += entry.size
    return report


def enforce_limits(report: InspectionReport, prefs: ArchivePrefs, name: str) -> None:
    """Raise ArchiveSecurityError when the report breaks any safety limit."""
    if report.unsafe:
        path, reason = report.unsafe[0]
        raise ArchiveSecurityError(f"{name}: unsafe entry '{path}' ({reason})")
    if len(report.entries) > prefs.max_files:
        raise ArchiveSecurityError(
            f"{name}: {len(report.entries):,} entries exceeds the limit of {prefs.max_files:,}")
    if report.total_bytes > prefs.max_extract_bytes:
        raise ArchiveSecurityError(
            f"{name}: would unpack to {human_size(report.total_bytes)}, "
            f"over the {prefs.max_extract_gb:g} GB limit")
    if report.total_bytes > prefs.ratio_floor_bytes and report.ratio > prefs.max_ratio:
        raise ArchiveSecurityError(
            f"{name}: unpack ratio {report.ratio:,.0f}:1 looks like an archive bomb "
            f"(limit {prefs.max_ratio:g}:1)")


class _ByteGuard:
    """Enforces limits on bytes *actually written*, not on what headers claim."""

    def __init__(self, prefs: ArchivePrefs, archive_bytes: int, name: str):
        self.prefs, self.archive_bytes, self.name = prefs, max(1, archive_bytes), name
        self.written = 0

    def add(self, count: int) -> None:
        self.written += count
        if self.written > self.prefs.max_extract_bytes:
            raise ArchiveSecurityError(
                f"{self.name}: exceeded the {self.prefs.max_extract_gb:g} GB unpack limit")
        if (self.written > self.prefs.ratio_floor_bytes
                and self.written / self.archive_bytes > self.prefs.max_ratio):
            raise ArchiveSecurityError(
                f"{self.name}: unpack ratio exceeded {self.prefs.max_ratio:g}:1 (archive bomb?)")


# ──────────────────────────────────────────────────────────────
# Extractor
# ──────────────────────────────────────────────────────────────

class ArchiveExtractor:
    """Safe archive extractor with configurable depth limiting."""

    SUPPORTED_FORMATS = {
        '.zip', '.rar', '.7z', '.tar', '.tar.gz', '.tgz',
        '.tar.bz2', '.tbz2', '.tar.xz', '.txz'
    }

    def __init__(self, config, logger, max_depth: int = None):
        self.config = config
        self.logger = logger
        self.max_depth = max_depth if max_depth is not None else getattr(config, 'MAX_ARCHIVE_DEPTH', 2)
        self._extracted_paths: List[Path] = []
        self.password: Optional[str] = None
        self.progress: Optional[Callable[[float], None]] = None
        self.cancel: Optional[Callable[[], bool]] = None

    def is_archive(self, path: Path) -> bool:
        """Check if file is a supported archive format by checking if name ends with known extension."""
        name_lower = path.name.lower()
        return any(name_lower.endswith(ext) for ext in self.SUPPORTED_FORMATS)

    # ── public API ───────────────────────────────────────────

    def inspect(self, archive_path: Path, password: Optional[str] = None) -> InspectionReport:
        """List and judge an archive without unpacking it. Raises if it breaks a rule."""
        archive_path = Path(archive_path)
        prefs = load_prefs(self.config)
        entries = list_entries(archive_path, ToolLocator(prefs), password or self.password, self.cancel)
        report = build_report(entries, archive_path.stat().st_size)
        enforce_limits(report, prefs, archive_path.name)
        if report.encrypted and not (password or self.password):
            raise PasswordRequired(f"Archive is password-protected: {archive_path.name}")
        return report

    def extract_single(self, archive_path: Path, dest_dir: Path,
                       password: Optional[str] = None,
                       archive_bytes: Optional[int] = None) -> List[Path]:
        """
        Unpack ONE archive layer straight into ``dest_dir`` (nested archives are
        left exactly as they are). Used by the converter; ``extract`` builds on it.
        Returns every extracted file.
        """
        archive_path, dest_dir = Path(archive_path), Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        password = password or self.password
        prefs = load_prefs(self.config)
        loc = ToolLocator(prefs)
        kind = archive_kind(archive_path)

        if kind in ("zip", "tar") or loc.sevenzip():
            entries = list_entries(archive_path, loc, password, self.cancel)
            total_archive_bytes = archive_bytes or archive_path.stat().st_size
            report = build_report(entries, total_archive_bytes)
            enforce_limits(report, prefs, archive_path.name)
            if report.encrypted and not password:
                raise PasswordRequired(f"Archive is password-protected: {archive_path.name}")
            free = shutil.disk_usage(dest_dir).free
            if report.total_bytes * 1.05 > free:
                raise ToolError(
                    f"Not enough free space to unpack {archive_path.name}: needs about "
                    f"{human_size(report.total_bytes)}, only {human_size(free)} free "
                    f"(choose a roomier Workspace folder in Settings > Archive).")
            if report.links:
                self.logger.warning(
                    f"{archive_path.name}: skipping {len(report.links)} link entr"
                    f"{'y' if len(report.links) == 1 else 'ies'} (links are never extracted)")
            guard = _ByteGuard(prefs, total_archive_bytes, archive_path.name)
            if kind == "zip":
                self._extract_zip(archive_path, dest_dir, guard, password)
            elif kind == "tar":
                self._extract_tar(archive_path, dest_dir, guard)
            else:
                SevenZip(loc.sevenzip()).extract(
                    archive_path, dest_dir, password, exclude=report.links,
                    progress=self.progress, cancel=self.cancel)
        else:
            self.logger.warning(
                f"7-Zip not found: extracting {archive_path.name} with the fallback extractor. "
                f"Size/ratio limits cannot be enforced in advance. Install 7-Zip for full protection.")
            self._extract_patool(archive_path, dest_dir)

        self._sweep(dest_dir, archive_path.name)
        files = [Path(dp, fn) for dp, _d, fns in os.walk(dest_dir) for fn in fns]
        self.logger.info(f"Extracted {len(files)} file(s) from {archive_path.name}")
        return files

    def extract(
        self,
        archive_path: Path,
        dest_dir: Path,
        current_depth: int = 0
    ) -> Tuple[Path, List[Path]]:
        """
        Extract archive safely to destination directory.

        Returns:
            Tuple of (extraction_root, list_of_extracted_files)

        Raises:
            RuntimeError: On extraction failure or security violation
        """
        if current_depth >= self.max_depth:
            self.logger.warning(
                f"Max archive depth ({self.max_depth}) reached for {archive_path.name}. "
                f"Preserving as-is."
            )
            return dest_dir, [archive_path]

        self.logger.info(f"Extracting archive: {archive_path.name} (depth={current_depth})")

        # A unique subfolder per archive, so a.zip and a.rar in one folder never merge.
        extract_subdir = dest_dir / f"_extracted_{archive_path.stem}"
        counter = 2
        while extract_subdir.exists():
            extract_subdir = dest_dir / f"_extracted_{archive_path.stem}_{counter}"
            counter += 1
        extract_subdir.mkdir(parents=True, exist_ok=True)

        try:
            extracted = self.extract_single(archive_path, extract_subdir)
            extracted_files = [f for f in extracted if not f.name.startswith('.')]
            self._extracted_paths.append(extract_subdir)

            all_files = list(extracted_files)
            for nested in [f for f in extracted_files if self.is_archive(f)]:
                try:
                    _, nested_files = self.extract(nested, nested.parent, current_depth + 1)
                    preserved = (len(nested_files) == 1 and nested_files[0] == nested)
                    if preserved:
                        # Depth limit reached: keep the nested archive exactly as it was.
                        continue
                    nested.unlink(missing_ok=True)
                    all_files.remove(nested)
                    all_files.extend(nested_files)
                except Cancelled:
                    raise
                except Exception as e:
                    self.logger.warning(f"Failed to extract nested archive {nested.name}: {e}")
                    # Preserve the nested archive as-is (it stays in all_files)

            return extract_subdir, all_files

        except Exception as e:
            self.logger.error(f"Archive extraction failed for {archive_path.name}: {e}")
            self._cleanup_failed_extraction(extract_subdir)
            if isinstance(e, (PasswordRequired, ArchiveSecurityError, Cancelled)):
                raise type(e)(f"Failed to extract {archive_path.name}: {e}") from e
            raise RuntimeError(f"Failed to extract {archive_path.name}: {e}")

    # ── format handlers ──────────────────────────────────────

    def _extract_tar(self, archive_path: Path, dest_dir: Path, guard: _ByteGuard) -> None:
        with tarfile.open(archive_path, 'r:*') as tar:
            for member in tar:
                if self.cancel and self.cancel():
                    raise Cancelled("Cancelled.")
                reason = unsafe_reason(member.name)
                if reason:
                    raise ArchiveSecurityError(f"Unsafe entry '{member.name}' ({reason})")
                target = dest_dir / norm_path(member.name)
                if not _inside(dest_dir, target):
                    raise ArchiveSecurityError(f"Entry escapes destination: {member.name}")
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    src = tar.extractfile(member)
                    with open(target, 'wb') as out:
                        while True:
                            chunk = src.read(CHUNK)
                            if not chunk:
                                break
                            guard.add(len(chunk))
                            out.write(chunk)
                    self._set_mtime(target, member.mtime)
                # links, devices and fifos are skipped on purpose

    def _extract_zip(self, archive_path: Path, dest_dir: Path, guard: _ByteGuard,
                     password: Optional[str]) -> None:
        with zipfile.ZipFile(archive_path, 'r') as zf:
            if password:
                zf.setpassword(password.encode('utf-8'))
            for info in zf.infolist():
                if self.cancel and self.cancel():
                    raise Cancelled("Cancelled.")
                reason = unsafe_reason(info.filename)
                if reason:
                    raise ArchiveSecurityError(f"Unsafe entry '{info.filename}' ({reason})")
                target = dest_dir / norm_path(info.filename)
                if not _inside(dest_dir, target):
                    raise ArchiveSecurityError(f"Zip Slip detected: {info.filename}")
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    continue  # symlink entry
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with zf.open(info) as src, open(target, 'wb') as out:
                        while True:
                            chunk = src.read(CHUNK)
                            if not chunk:
                                break
                            guard.add(len(chunk))
                            out.write(chunk)
                except RuntimeError as exc:  # wrong/missing password
                    raise PasswordRequired(
                        f"Archive is password-protected: {archive_path.name}") from exc
                try:
                    self._set_mtime(target, time.mktime(info.date_time + (0, 0, -1)))
                except (OverflowError, ValueError):
                    pass

    def _extract_patool(self, archive_path: Path, dest_dir: Path) -> None:
        """Fallback when 7-Zip is not installed (RAR/7z/other)."""
        try:
            import patoolib
        except ImportError as exc:
            raise ToolError("Neither 7-Zip nor the 'patool' package is available to extract "
                            f"{archive_path.name}. Install 7-Zip.") from exc
        try:
            patoolib.extract_archive(str(archive_path), outdir=str(dest_dir), verbosity=-1)
        except Exception as e:
            msg = str(e).lower()
            if "password" in msg or "encrypted" in msg:
                self.logger.warning(f"Archive is password-protected: {archive_path.name}")
                raise PasswordRequired(f"Archive is password-protected: {archive_path.name}")
            raise

    # ── safety sweep ─────────────────────────────────────────

    def _sweep(self, dest_dir: Path, name: str) -> None:
        """Nothing may be a link, and nothing may live outside ``dest_dir``."""
        for dirpath, dirnames, filenames in os.walk(dest_dir, followlinks=False):
            for item in list(dirnames) + list(filenames):
                p = Path(dirpath, item)
                if _is_reparse(p) or not _inside(dest_dir, p):
                    shutil.rmtree(dest_dir, ignore_errors=True)
                    raise ArchiveSecurityError(
                        f"{name}: extraction produced a link or an escaping path ({p.name}); refused")

    @staticmethod
    def _set_mtime(path: Path, mtime) -> None:
        try:
            if mtime and mtime > 0:
                os.utime(path, (mtime, mtime))
        except (OSError, OverflowError, ValueError):
            pass

    def _cleanup_failed_extraction(self, extract_dir: Path):
        """Clean up partially extracted archive on failure."""
        try:
            if extract_dir.exists():
                shutil.rmtree(extract_dir)
                self.logger.info(f"Cleaned up failed extraction: {extract_dir}")
        except Exception as e:
            self.logger.warning(f"Could not clean up failed extraction: {e}")

    def cleanup_all(self):
        """Clean up all extracted temporary directories."""
        for path in self._extracted_paths:
            try:
                if path.exists():
                    shutil.rmtree(path)
                    self.logger.info(f"Cleaned up extraction: {path}")
            except Exception as e:
                self.logger.warning(f"Could not clean up {path}: {e}")
        self._extracted_paths.clear()


# ──────────────────────────────────────────────────────────────
# Inspector / classifier (public API unchanged)
# ──────────────────────────────────────────────────────────────

class ArchiveInspector:
    """Inspect archive contents without extracting."""

    def __init__(self, config, logger):
        self.config = config
        self.logger = logger

    def list_contents(self, archive_path: Path) -> List[dict]:
        """List archive contents with metadata."""
        prefs = load_prefs(self.config)
        try:
            entries = list_entries(Path(archive_path), ToolLocator(prefs))
        except (ToolError, zipfile.BadZipFile, tarfile.TarError, OSError) as e:
            self.logger.error(f"Failed to list archive {archive_path}: {e}")
            return []
        contents = []
        for e in entries:
            item = {'name': e.path, 'size': e.size, 'type': 'dir' if e.is_dir else 'file'}
            if e.packed is not None:
                item['compressed_size'] = e.packed
            contents.append(item)
        return contents


class ArchiveClassifier:
    """Classify archives and their contents for processing."""

    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        self.extractor = ArchiveExtractor(config, logger)
        self.inspector = ArchiveInspector(config, logger)

    def classify(self, path: Path) -> dict:
        """
        Classify a path as: 'file', 'directory', 'archive', 'nested_archive'

        Returns dict with classification and metadata.
        """
        if path.is_dir():
            return {'type': 'directory', 'path': path}

        if self.extractor.is_archive(path):
            # Inspect to check for nested archives
            try:
                contents = self.inspector.list_contents(path)
                has_nested = any(
                    self.extractor.is_archive(Path(item['name']))
                    for item in contents
                )
            except Exception as e:
                self.logger.warning(f"Failed to inspect archive {path.name}: {e}")
                contents = []
                has_nested = False
            return {
                'type': 'archive',
                'path': path,
                'has_nested_archives': has_nested,
                'content_count': len(contents)
            }

        return {'type': 'file', 'path': path}
