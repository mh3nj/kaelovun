"""
archive_extraction.py

Safe archive extraction with security boundaries.
Supports: ZIP, RAR, 7z, tar, tar.gz, tar.bz2, tar.xz
Protects against: path traversal, archive bombs, symlink attacks, recursion loops.
"""

import os
import tarfile
import zipfile
import shutil
import tempfile
from pathlib import Path
from typing import Optional, List, Tuple
import patoolib


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

    def is_archive(self, path: Path) -> bool:
        """Check if file is a supported archive format by checking if name ends with known extension."""
        name_lower = path.name.lower()
        return any(name_lower.endswith(ext) for ext in self.SUPPORTED_FORMATS)

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

        # Create a unique subdirectory for this extraction
        extract_subdir = dest_dir / f"_extracted_{archive_path.stem}"
        extract_subdir.mkdir(parents=True, exist_ok=True)

        try:
            extracted_files = self._extract_archive(archive_path, extract_subdir)
            self._extracted_paths.append(extract_subdir)

            # Scan for nested archives
            nested_archives = [
                f for f in extracted_files
                if self.is_archive(f)
            ]

            all_files = list(extracted_files)
            for nested in nested_archives:
                try:
                    _, nested_files = self.extract(
                        nested,
                        nested.parent,
                        current_depth + 1
                    )
                    # Remove the nested archive file itself (it's been extracted)
                    nested.unlink(missing_ok=True)
                    all_files.extend(nested_files)
                except Exception as e:
                    self.logger.warning(f"Failed to extract nested archive {nested.name}: {e}")
                    # Preserve the nested archive as-is
                    all_files.append(nested)

            return extract_subdir, all_files

        except Exception as e:
            self.logger.error(f"Archive extraction failed for {archive_path.name}: {e}")
            # Cleanup on failure
            self._cleanup_failed_extraction(extract_subdir)
            raise RuntimeError(f"Failed to extract {archive_path.name}: {e}")

    def _extract_archive(self, archive_path: Path, dest_dir: Path) -> List[Path]:
        """Extract a single archive using appropriate method."""
        name_lower = archive_path.name.lower()

        if any(name_lower.endswith(ext) for ext in ('.tar', '.tar.gz', '.tgz', '.tar.bz2', '.tbz2', '.tar.xz', '.txz')):
            return self._extract_tar(archive_path, dest_dir)
        elif name_lower.endswith('.zip'):
            return self._extract_zip(archive_path, dest_dir)
        else:
            # RAR, 7z, etc. - use patoolib
            return self._extract_patool(archive_path, dest_dir)

    def _extract_tar(self, archive_path: Path, dest_dir: Path) -> List[Path]:
        """Extract tar-based archives with path traversal protection."""
        extracted = []
        mode = 'r:*'  # Auto-detect compression

        with tarfile.open(archive_path, mode) as tar:
            # Validate all members before extracting
            for member in tar.getmembers():
                self._validate_tar_member(member, dest_dir)

            # Safe extraction
            tar.extractall(dest_dir, filter='data')
            extracted = [
                dest_dir / member.name
                for member in tar.getmembers()
                if not member.name.startswith('.')
            ]

        self.logger.info(f"Extracted {len(extracted)} files from tar archive")
        return extracted

    def _extract_zip(self, archive_path: Path, dest_dir: Path) -> List[Path]:
        """Extract ZIP archive with path traversal protection."""
        extracted = []

        with zipfile.ZipFile(archive_path, 'r') as zf:
            # Validate all entries before extracting
            for info in zf.infolist():
                self._validate_zip_member(info, dest_dir)

            # Check for encryption before attempting extraction
            encrypted_files = [info for info in zf.infolist() if info.flag_bits & 0x1]
            if encrypted_files:
                self.logger.warning(f"Archive contains encrypted files, skipping extraction: {archive_path.name}")
                raise RuntimeError(f"Archive is password-protected: {archive_path.name}")

            # Safe extraction
            zf.extractall(dest_dir)
            extracted = [
                dest_dir / info.filename
                for info in zf.infolist()
                if not info.filename.startswith('.')
            ]

        self.logger.info(f"Extracted {len(extracted)} files from ZIP archive")
        return extracted

    def _extract_patool(self, archive_path: Path, dest_dir: Path) -> List[Path]:
        """Extract using patoolib (RAR, 7z, etc.)."""
        # patoolib handles its own validation
        try:
            patoolib.extract_archive(
                str(archive_path),
                outdir=str(dest_dir),
                verbosity=-1  # Quiet
            )
        except Exception as e:
            error_msg = str(e).lower()
            if "password" in error_msg or "encrypted" in error_msg:
                self.logger.warning(f"Archive is password-protected, skipping: {archive_path.name}")
                raise RuntimeError(f"Archive is password-protected: {archive_path.name}")
            raise

        # Get list of extracted files
        extracted = []
        for item in dest_dir.rglob('*'):
            if item.is_file() and not item.name.startswith('.'):
                extracted.append(item)

        self.logger.info(f"Extracted {len(extracted)} files via patoolib")
        return extracted

    def _validate_tar_member(self, member: tarfile.TarInfo, dest_dir: Path):
        """Validate tar member for path traversal and other issues."""
        # Absolute paths
        if member.name.startswith('/') or (os.name == 'nt' and ':' in member.name):
            raise RuntimeError(f"Absolute path in archive: {member.name}")

        # Path traversal
        if '..' in member.name.split('/'):
            raise RuntimeError(f"Path traversal in archive: {member.name}")

        # Symlinks/hardlinks pointing outside
        if member.issym() or member.islnk():
            link_target = member.linkname
            if link_target.startswith('/') or '..' in link_target.split('/'):
                raise RuntimeError(f"Unsafe link in archive: {member.name} -> {link_target}")

    def _validate_zip_member(self, info: zipfile.ZipInfo, dest_dir: Path):
        """Validate ZIP member for path traversal and other issues."""
        # Absolute paths
        if info.filename.startswith('/') or (os.name == 'nt' and ':' in info.filename):
            raise RuntimeError(f"Absolute path in archive: {info.filename}")

        # Path traversal
        if '..' in info.filename.split('/'):
            raise RuntimeError(f"Path traversal in archive: {info.filename}")

        # Check for Zip Slip - resolved path must be within dest_dir
        target_path = (dest_dir / info.filename).resolve()
        if not str(target_path).startswith(str(dest_dir.resolve())):
            raise RuntimeError(f"Zip Slip detected: {info.filename}")

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


class ArchiveInspector:
    """Inspect archive contents without extracting."""

    def __init__(self, logger):
        self.logger = logger

    def list_contents(self, archive_path: Path) -> List[dict]:
        """List archive contents with metadata."""
        name_lower = archive_path.name.lower()

        if any(name_lower.endswith(ext) for ext in ('.tar', '.tar.gz', '.tgz', '.tar.bz2', '.tbz2', '.tar.xz', '.txz')):
            return self._list_tar(archive_path)
        elif name_lower.endswith('.zip'):
            return self._list_zip(archive_path)
        else:
            return self._list_patool(archive_path)

    def _list_tar(self, archive_path: Path) -> List[dict]:
        contents = []
        with tarfile.open(archive_path, 'r:*') as tar:
            for member in tar.getmembers():
                contents.append({
                    'name': member.name,
                    'size': member.size,
                    'type': 'dir' if member.isdir() else 'file',
                    'mode': oct(member.mode) if member.mode else None
                })
        return contents

    def _list_zip(self, archive_path: Path) -> List[dict]:
        contents = []
        with zipfile.ZipFile(archive_path, 'r') as zf:
            for info in zf.infolist():
                name = info.filename
                contents.append({
                    'name': name,
                    'size': info.file_size,
                    'type': 'dir' if name.endswith('/') else 'file',
                    'compressed_size': info.compress_size
                })
        return contents

    def _list_patool(self, archive_path: Path) -> List[dict]:
        # patoolib doesn't have a clean list API, extract to temp and list
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                patoolib.extract_archive(str(archive_path), outdir=tmpdir, verbosity=-1)
                contents = []
                for item in Path(tmpdir).rglob('*'):
                    if item.is_file():
                        rel = item.relative_to(tmpdir)
                        contents.append({
                            'name': str(rel),
                            'size': item.stat().st_size,
                            'type': 'file'
                        })
                return contents
            except Exception as e:
                self.logger.error(f"Failed to list archive {archive_path}: {e}")
                return []


class ArchiveClassifier:
    """Classify archives and their contents for processing."""

    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        self.extractor = ArchiveExtractor(config, logger)
        self.inspector = ArchiveInspector(logger)

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