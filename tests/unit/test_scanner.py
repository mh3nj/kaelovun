"""
test_scanner.py

Unit tests for AssetScanner.
"""

import tempfile
from pathlib import Path

import pytest

from pipeline.scanner import AssetScanner


class MockConfig:
    def __init__(self):
        self.SUPPORTED_SOURCE_EXTENSIONS = [".psd", ".ai"]
        self.SUPPORTED_AFFINITY_EXTENSIONS = [".afphoto", ".afdesign", ".afpub"]
        self.ENGINE = "adobe"

    def scannable_extensions(self):
        exts = list(self.SUPPORTED_SOURCE_EXTENSIONS)
        if self.ENGINE == "affinity":
            for ext in self.SUPPORTED_AFFINITY_EXTENSIONS:
                if ext not in exts:
                    exts.append(ext)
        return exts


class MockLogger:
    def __init__(self):
        self.messages = []

    def info(self, msg):
        self.messages.append(("info", msg))

    def warning(self, msg):
        self.messages.append(("warning", msg))

    def error(self, msg):
        self.messages.append(("error", msg))


class TestAssetScanner:
    def setup_method(self):
        self.config = MockConfig()
        self.logger = MockLogger()
        self.scanner = AssetScanner(self.config, self.logger)

    def test_scan_folder_finds_psd_and_ai(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            (tmpdir / "logo.psd").write_text("psd")
            (tmpdir / "icon.ai").write_text("ai")
            (tmpdir / "readme.txt").write_text("txt")

            jobs = self.scanner.scan_folder(tmpdir)

            assert len(jobs) == 2
            extensions = {job.source_file.suffix for job in jobs}
            assert ".psd" in extensions
            assert ".ai" in extensions

    def test_scan_folder_recursive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            (tmpdir / "logo.psd").write_text("psd")
            (tmpdir / "SOURCE").mkdir()
            (tmpdir / "SOURCE" / "icon.ai").write_text("ai")
            (tmpdir / "EXPORT").mkdir()
            (tmpdir / "EXPORT" / "final.png").write_text("png")

            jobs = self.scanner.scan_folder(tmpdir)

            assert len(jobs) == 2

    def test_scan_folder_ignores_non_supported(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            (tmpdir / "doc.pdf").write_text("pdf")
            (tmpdir / "font.otf").write_text("otf")
            (tmpdir / "image.jpg").write_text("jpg")

            jobs = self.scanner.scan_folder(tmpdir)

            assert len(jobs) == 0

    def test_scan_input_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            file_path = tmpdir / "logo.psd"
            file_path.write_text("psd")

            jobs = self.scanner.scan_input(file_path)

            assert len(jobs) == 1
            assert jobs[0].source_file == file_path

    def test_scan_input_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            (tmpdir / "logo.psd").write_text("psd")
            (tmpdir / "icon.ai").write_text("ai")

            jobs = self.scanner.scan_input(tmpdir)

            assert len(jobs) == 2

    def test_scan_input_archive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            # Create a zip file
            import zipfile
            zip_path = tmpdir / "project.zip"
            with zipfile.ZipFile(zip_path, 'w') as zf:
                zf.writestr("logo.psd", "psd")
                zf.writestr("icon.ai", "ai")

            jobs = self.scanner.scan_input(zip_path)

            assert len(jobs) == 1
            assert jobs[0].source_file == zip_path
            assert jobs[0].is_archive is True
            assert jobs[0].archive_metadata is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])