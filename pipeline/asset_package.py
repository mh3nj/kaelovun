"""
asset_package.py

Asset Package model - represents a logical collection of files
that should be processed and archived together.
"""

from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from enum import Enum


class FileCategory(Enum):
    """File classification for processing decisions."""
    TRANSFORMABLE = "transformable"      # PSD, AI, INDD, etc. - can be processed
    PRESERVABLE = "preservable"          # PDF, fonts, images, unknown - preserve as-is
    CONTAINER = "container"              # Archives, packages - extract and process contents
    LICENSE_DOC = "license_doc"          # Licenses, EULAs, docs - always preserve


@dataclass
class AssetFile:
    """Represents a single file in an asset package."""
    path: Path
    relative_path: Path  # Relative to package root
    category: FileCategory
    processor_type: Optional[str] = None  # e.g., "photoshop", "illustrator", "image"
    original_size: int = 0
    processed_size: int = 0
    preview_path: Optional[Path] = None
    thumb_path: Optional[Path] = None
    error: Optional[str] = None

    def __post_init__(self):
        if self.original_size == 0 and self.path.exists():
            self.original_size = self.path.stat().st_size


@dataclass
class AssetPackage:
    """
    An Asset Package is a logical collection of related files and directories
    that should be preserved together.
    """
    root_path: Path
    name: str
    files: List[AssetFile] = field(default_factory=list)
    source_type: str = "directory"  # "file", "directory", "archive"
    original_archive: Optional[Path] = None
    workspace_dir: Optional[Path] = None
    previews_generated: bool = False
    archive_created: bool = False
    archive_path: Optional[Path] = None
    verification_passed: bool = False

    def __post_init__(self):
        if not self.name:
            self.name = self.root_path.name

    def add_file(self, file: AssetFile):
        self.files.append(file)

    def get_transformable_files(self) -> List[AssetFile]:
        return [f for f in self.files if f.category == FileCategory.TRANSFORMABLE]

    def get_preservable_files(self) -> List[AssetFile]:
        return [f for f in self.files if f.category in (FileCategory.PRESERVABLE, FileCategory.LICENSE_DOC)]

    def get_all_files(self) -> List[AssetFile]:
        return self.files

    def get_directory_structure(self) -> Dict:
        """Return the directory structure as nested dict."""
        structure = {}
        for asset_file in self.files:
            parts = asset_file.relative_path.parts
            current = structure
            for part in parts[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]
            current[parts[-1]] = asset_file
        return structure


class PackageClassifier:
    """Classify files into processing categories."""

    # Known transformable extensions (Adobe/Affinity creative formats)
    TRANSFORMABLE_EXTS = {
        '.psd', '.psb',          # Photoshop
        '.ai', '.eps',           # Illustrator
        '.indd', '.indt',        # InDesign
        '.afphoto', '.afdesign', '.afpub',  # Affinity
    }

    # Known preservable extensions (don't transform, just preserve)
    PRESERVABLE_EXTS = {
        # Images
        '.jpg', '.jpeg', '.png', '.tiff', '.tif', '.bmp', '.gif', '.webp', '.avif', '.heic',
        # Documents
        '.pdf', '.txt', '.md', '.rtf',
        # Fonts
        '.otf', '.ttf', '.woff', '.woff2', '.eot',
        # Vector
        '.svg',
        # Other common creative assets
        '.ico', '.icns',
    }

    # License/document indicators in filenames
    LICENSE_INDICATORS = {
        'license', 'licence', 'eula', 'terms', 'copyright', 'credits',
        'readme', 'notice', 'legal', 'agreement', 'disclaimer',
        'changelog', 'changes', 'history', 'version', 'authors',
        'contributors', 'acknowledgments', 'thanks', 'attribution',
    }

    def __init__(self, config, logger):
        self.config = config
        self.logger = logger

    def classify_file(self, file_path: Path, package_root: Path) -> AssetFile:
        """Classify a single file and return AssetFile."""
        try:
            rel_path = file_path.relative_to(package_root)
        except ValueError:
            rel_path = file_path.name

        ext = file_path.suffix.lower()
        stem_lower = file_path.stem.lower()

        # Determine category
        if ext in self.TRANSFORMABLE_EXTS:
            category = FileCategory.TRANSFORMABLE
            processor_type = self._get_processor_type(ext)
        elif ext in self.PRESERVABLE_EXTS:
            # Check if it's a license/document
            if any(indicator in stem_lower for indicator in self.LICENSE_INDICATORS):
                category = FileCategory.LICENSE_DOC
            else:
                category = FileCategory.PRESERVABLE
            processor_type = None
        elif self._is_archive(file_path):
            category = FileCategory.CONTAINER
            processor_type = "archive"
        else:
            # Unknown - preserve conservatively
            category = FileCategory.PRESERVABLE
            processor_type = None

        return AssetFile(
            path=file_path,
            relative_path=rel_path,
            category=category,
            processor_type=processor_type
        )

    def _get_processor_type(self, ext: str) -> str:
        """Map extension to processor type."""
        if ext in ('.psd', '.psb'):
            return 'photoshop'
        elif ext in ('.ai', '.eps'):
            return 'illustrator'
        elif ext in ('.indd', '.indt'):
            return 'indesign'
        elif ext in ('.afphoto', '.afdesign', '.afpub'):
            return 'affinity'
        return 'unknown'

    def _is_archive(self, path: Path) -> bool:
        """Check if file is an archive."""
        suffixes = ''.join(path.suffixes).lower()
        archive_exts = {'.zip', '.rar', '.7z', '.tar', '.tar.gz', '.tgz',
                        '.tar.bz2', '.tbz2', '.tar.xz', '.txz'}
        return suffixes in archive_exts or path.suffix.lower() in archive_exts

    def classify_package(self, root_path: Path, source_type: str = "directory",
                         original_archive: Optional[Path] = None) -> AssetPackage:
        """Classify all files in a package."""
        package = AssetPackage(
            root_path=root_path,
            name=root_path.name,
            source_type=source_type,
            original_archive=original_archive
        )

        for file_path in root_path.rglob('*'):
            if file_path.is_file() and not file_path.name.startswith('.'):
                asset_file = self.classify_file(file_path, root_path)
                package.add_file(asset_file)

        self.logger.info(f"Package '{package.name}': {len(package.files)} files, "
                         f"{len(package.get_transformable_files())} transformable, "
                         f"{len(package.get_preservable_files())} preservable")
        return package