"""
filename.py

Asset naming manager.
"""

from pathlib import Path

_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}


class FilenameManager:

    def __init__(self, logger):
        self.logger = logger

    def normalize(self, name: str) -> str:
        name = name.strip()
        invalid = ['\\', '/', ':', '*', '?', '"', '<', '>', '|']
        for char in invalid:
            name = name.replace(char, "")
        # Windows silently strips trailing dots/spaces, which makes paths
        # you created unreachable; control characters are never valid.
        name = "".join(c for c in name if ord(c) >= 32).rstrip(" .")
        if name.upper() in _RESERVED:
            name = f"_{name}"
        return name

    def exists(self, folder: Path, name: str) -> bool:
        folder = Path(folder)
        extensions = [".psd", ".ai", ".avif", ".rar", ".7z", ".zip"]
        for ext in extensions:
            if (folder / f"{name}{ext}").exists():
                return True
        return False

    def unique_name(self, folder: Path, name: str) -> str:
        name = self.normalize(name)
        if not self.exists(folder, name):
            return name
        counter = 2
        while True:
            new_name = f"{name}{counter}"
            if not self.exists(folder, new_name):
                return new_name
            counter += 1

    @staticmethod
    def unique_path(folder: Path, stem: str, ext: str) -> Path:
        """
        First free path of the form ``stem.ext``, ``stem (2).ext``, ``stem (3).ext``...

        Never returns a path that already exists, so an output can never land
        on top of its own source archive or on an earlier result.
        """
        folder = Path(folder)
        candidate = folder / f"{stem}{ext}"
        counter = 2
        while candidate.exists():
            candidate = folder / f"{stem} ({counter}){ext}"
            counter += 1
        return candidate

    @staticmethod
    def unique_stem(folder: Path, stem: str, suffixes) -> str:
        """
        First ``stem`` / ``stem (2)`` / ``stem (3)`` ... for which NONE of
        ``stem + suffix`` exists. Used so an archive, its preview, its thumbnail
        and its sidecar always share one stem and never land on an existing file.
        """
        folder = Path(folder)
        candidate, counter = stem, 2
        while any((folder / f"{candidate}{suffix}").exists() for suffix in suffixes):
            candidate = f"{stem} ({counter})"
            counter += 1
        return candidate
