"""
scanner.py

Asset discovery system.
"""

from pathlib import Path
import shutil

from pipeline.job import Job
from files.archive_extraction import ArchiveClassifier


class AssetScanner:

    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        self.classifier = ArchiveClassifier(config, logger)

    def scan_folder(self, folder: Path) -> list:
        folder = Path(folder)
        self.logger.info(f"Scanning: {folder}")
        try:
            wanted = set(self.config.scannable_extensions())
        except AttributeError:
            wanted = {".psd", ".ai", ".eps"}
        jobs = []
        for item in folder.rglob("*"):
            if not item.is_file():
                continue
            extension = item.suffix.lower()
            if extension in wanted:
                job = Job(item)
                existing = self.find_existing_preview(item)
                if existing:
                    job.existing_preview = existing
                jobs.append(job)
        self.logger.info(f"Found {len(jobs)} scannable files ({sorted(wanted)}).")
        return jobs

    def scan_input(self, path: Path) -> list:
        """
        Universal input scanner.
        Handles: individual files, directories, and archives.
        """
        path = Path(path)
        self.logger.info(f"Scanning input: {path}")

        classification = self.classifier.classify(path)

        if classification['type'] == 'file':
            if path.suffix.lower() in self.config.scannable_extensions():
                return [Job(path)]
            else:
                self.logger.info(f"File {path.name} is not a scannable format, will be preserved")
                return []

        elif classification['type'] == 'directory':
            return self.scan_folder(path)

        elif classification['type'] == 'archive':
            self.logger.info(f"Input is an archive: {path.name}")
            # Archive will be extracted during processing, not during scanning
            # Return a special job that marks this as an archive to process
            job = Job(path)
            job.is_archive = True
            job.archive_metadata = classification
            return [job]

        return []

    def find_existing_preview(self, source: Path):
        extensions = [".png", ".jpg", ".jpeg", ".webp"]
        for ext in extensions:
            candidate = source.with_suffix(ext)
            if candidate.exists():
                return candidate
        return None

    def find_unknown_assets(self, folder: Path):
        check_folder = folder / "CHECK"
        check_folder.mkdir(exist_ok=True)
        supported = [".psd", ".ai", ".avif", ".png", ".jpg", ".jpeg"]
        moved = []
        for item in folder.iterdir():
            if item.name == "CHECK":
                continue
            if item.is_dir():
                files = list(item.rglob("*"))
                has_supported = any(
                    f.suffix.lower() in supported
                    for f in files if f.is_file()
                )
                if not has_supported:
                    destination = check_folder / item.name
                    shutil.move(str(item), str(destination))
                    moved.append(destination)
        self.logger.info(f"Moved {len(moved)} unknown folders.")
        return moved
