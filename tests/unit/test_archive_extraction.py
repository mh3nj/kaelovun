"""
test_archive_extraction.py

Unit tests for ArchiveExtractor and ArchiveInspector.
"""

import tempfile
from pathlib import Path
import zipfile

import pytest

from files.archive_extraction import ArchiveExtractor, ArchiveInspector, ArchiveClassifier


class MockConfig:
    def __init__(self):
        self.MAX_ARCHIVE_DEPTH = 2


class MockLogger:
    def __init__(self):
        self.messages = []

    def info(self, msg):
        self.messages.append(("info", msg))

    def warning(self, msg):
        self.messages.append(("warning", msg))

    def error(self, msg):
        self.messages.append(("error", msg))


class TestArchiveExtractor:
    def setup_method(self):
        self.config = MockConfig()
        self.logger = MockLogger()
        self.extractor = ArchiveExtractor(self.config, self.logger)

    def test_is_archive_zip(self):
        assert self.extractor.is_archive(Path("test.zip")) is True

    def test_is_archive_rar(self):
        assert self.extractor.is_archive(Path("test.rar")) is True

    def test_is_archive_7z(self):
        assert self.extractor.is_archive(Path("test.7z")) is True

    def test_is_archive_tar_gz(self):
        assert self.extractor.is_archive(Path("test.tar.gz")) is True

    def test_is_archive_tgz(self):
        assert self.extractor.is_archive(Path("test.tgz")) is True

    def test_is_archive_not_archive(self):
        assert self.extractor.is_archive(Path("test.psd")) is False
        assert self.extractor.is_archive(Path("test.txt")) is False

    def test_extract_zip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            # Create a test zip
            zip_path = tmpdir / "test.zip"
            with zipfile.ZipFile(zip_path, 'w') as zf:
                zf.writestr("file1.txt", "content1")
                zf.writestr("subdir/file2.txt", "content2")

            dest = tmpdir / "extracted"
            dest.mkdir()

            extract_root, files = self.extractor.extract(zip_path, dest)

            assert extract_root.exists()
            assert len(files) == 2
            # Check files were extracted
            extracted_names = {f.name for f in files}
            assert "file1.txt" in extracted_names
            assert "file2.txt" in extracted_names

    def test_extract_nested_zip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            # Create nested zip: outer.zip contains inner.zip which contains file.txt
            inner_zip = tmpdir / "inner.zip"
            with zipfile.ZipFile(inner_zip, 'w') as zf:
                zf.writestr("inner_file.txt", "inner content")

            outer_zip = tmpdir / "outer.zip"
            with zipfile.ZipFile(outer_zip, 'w') as zf:
                zf.write(inner_zip, "inner.zip")

            dest = tmpdir / "extracted"
            dest.mkdir()

            # With max_depth=2, it should extract both levels
            extract_root, files = self.extractor.extract(outer_zip, dest)

            # Should have extracted both inner.zip and inner_file.txt
            file_names = {f.name for f in files}
            assert "inner_file.txt" in file_names


class TestArchiveInspector:
    def setup_method(self):
        self.logger = MockLogger()
        self.inspector = ArchiveInspector(self.logger)

    def test_list_zip_contents(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            zip_path = tmpdir / "test.zip"
            with zipfile.ZipFile(zip_path, 'w') as zf:
                zf.writestr("file1.txt", "content1")
                zf.writestr("subdir/file2.txt", "content2")

            contents = self.inspector.list_contents(zip_path)

            assert len(contents) == 2
            names = {c['name'] for c in contents}
            assert "file1.txt" in names
            assert "subdir/file2.txt" in names


class TestArchiveClassifier:
    def setup_method(self):
        self.config = MockConfig()
        self.logger = MockLogger()
        self.classifier = ArchiveClassifier(self.config, self.logger)

    def test_classify_archive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            zip_path = tmpdir / "test.zip"
            with zipfile.ZipFile(zip_path, 'w') as zf:
                zf.writestr("file1.psd", "fake psd")
                zf.writestr("file2.ai", "fake ai")

            result = self.classifier.classify(zip_path)

            assert result['type'] == 'archive'
            assert result['path'] == zip_path
            assert result['has_nested_archives'] is False

    def test_classify_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            (tmpdir / "file.psd").write_text("psd")

            result = self.classifier.classify(tmpdir)

            assert result['type'] == 'directory'

    def test_classify_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            file_path = tmpdir / "file.psd"
            file_path.write_text("psd")

            result = self.classifier.classify(file_path)

            assert result['type'] == 'file'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])