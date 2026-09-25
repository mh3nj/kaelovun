"""
archive.py

RAR archive manager.
Uses Rar.exe (console CLI tool) for all operations.
Best compression (-m5), solid (-s), no comments.
"""

from pathlib import Path
import os
import subprocess


class RarArchive:

    def __init__(self, config, logger):
        self.config = config
        self.logger = logger

    def _rar_exe(self) -> Path:
        """Use Rar.exe (console) for CLI — more reliable than WinRAR.exe."""
        path = self.config.WINRAR_PATH  # points to Rar.exe
        if path.exists():
            return path
        # fallback to WinRAR.exe if Rar.exe missing
        fallback = self.config.WINRAR_GUI_PATH
        if fallback.exists():
            return fallback
        raise FileNotFoundError(
            "No RAR executable found. Expected at:\n"
            f"  {path}\n  {fallback}"
        )

    def create_rar(self, files, output: Path, work_dir: Path = None) -> Path:
        if not files:
            raise ValueError("No files to archive.")
        output = Path(output)
        rar = self._rar_exe()

        # Determine common parent directory for relative paths
        if work_dir is None:
            abs_files = [f.absolute() for f in files]
            work_dir = Path(os.path.commonpath(abs_files)) if abs_files else Path.cwd()
        else:
            work_dir = Path(work_dir).absolute()

        command = [
            str(rar),
            "a",
            "-r",
            "-m5",
            "-s",
            str(output),
        ]
        for file in files:
            try:
                rel = file.absolute().relative_to(work_dir)
            except ValueError:
                rel = file.absolute()
            command.append(str(rel))

        self.logger.info(f"Creating RAR: {output.name}")
        self.logger.info(f"  Files: {[f.name for f in files]}")
        self.logger.info(f"  Work dir: {work_dir}")

        result = subprocess.run(command, capture_output=True, text=True, cwd=work_dir)

        if result.returncode != 0:
            self.logger.error(f"Command: {' '.join(command)}")
            self.logger.error(f"stdout: {result.stdout}")
            self.logger.error(f"stderr: {result.stderr}")
            raise RuntimeError(
                f"RAR failed (exit {result.returncode}) for {output.name}"
            )

        if not output.exists():
            raise RuntimeError(f"RAR file not created: {output.name}")

        size_kb = output.stat().st_size / 1024
        self.logger.info(f"  Created: {output.name} ({size_kb:.1f} KB)")
        return output

    def test_archive(self, archive: Path) -> bool:
        rar = self._rar_exe()
        command = [
            str(rar),
            "t",
            str(archive),
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            self.logger.error(f"Test failed: {archive.name}")
            self.logger.error(result.stderr or result.stdout)
            return False
        self.logger.info(f"  Verified OK: {archive.name}")
        return True

    def list_archive(self, archive: Path) -> list[str]:
        """List contents of a RAR archive. Returns list of relative paths."""
        rar = self._rar_exe()
        # Use 'lt' (technical list) for more parseable output
        command = [
            str(rar),
            "lt",
            str(archive),
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            # Fallback to regular 'l' command
            command = [str(rar), "l", str(archive)]
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode != 0:
                self.logger.error(f"List failed: {archive.name}")
                self.logger.error(result.stderr or result.stdout)
                return []

        # Parse RAR technical list output - format:
        # Attr  Size  Packed  Ratio  Date  Time  Name
        # ----  ----  -----  -----  ----  ----  ----
        # -rw-r--r--  1234  567  46%  01-01-2024 12:00  folder/file.txt
        lines = result.stdout.splitlines()
        contents = []
        for line in lines:
            # Skip header lines
            if not line.strip():
                continue
            if line.startswith('Attr') or line.startswith('----'):
                continue
            if 'files' in line.lower() and 'bytes' in line.lower():
                continue
            # Technical format: attributes, size, packed, ratio, date, time, name
            # Split by whitespace, the last field is the name (may contain spaces)
            parts = line.split(None, 6)  # Split into max 7 parts
            if len(parts) >= 7:
                name = parts[6]  # Name is the 7th field
                if name and not all(c in '.A' for c in name):
                    contents.append(name.replace('\\', '/'))
            elif len(parts) >= 1:
                # Fallback: try to find the name part
                # The name is typically after the date/time fields
                candidate = parts[-1]
                if candidate and not all(c in '.A' for c in candidate):
                    contents.append(candidate.replace('\\', '/'))
        return contents
