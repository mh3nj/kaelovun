"""
test_archive_extraction.py

Unit tests for ArchiveExtractor and ArchiveInspector.
"""

import tempfile
from pathlib import Path
import zipfile

import pytest

from files.archive_extraction import ArchiveExtractor, ArchiveInspector, ArchiveClassifier
from files.archive import RarArchive
from files.session import AssetStateManager
from unittest.mock import MagicMock, patch


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
        self.config = MockConfig()
        self.logger = MockLogger()
        self.inspector = ArchiveInspector(self.config, self.logger)

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


class TestRarArchiveStructure:
    def test_create_rar_preserves_directory_structure(self):
        """RAR should preserve directory structure when work_dir is set."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            pkg_root = tmpdir / "pkg"
            pkg_root.mkdir()
            (pkg_root / "SOURCE").mkdir()
            (pkg_root / "SOURCE" / "logo.psd").write_text("psd")
            (pkg_root / "LICENSE").mkdir()
            (pkg_root / "LICENSE" / "license.pdf").write_text("license")

            rar_path = tmpdir / "output.rar"

            from files.archive import RarArchive
            from unittest.mock import MagicMock, patch

            config = MagicMock()
            config.WINRAR_PATH = Path("rar.exe")
            config.WINRAR_GUI_PATH = Path("WinRAR.exe")
            logger = MagicMock()

            archive = RarArchive(config, logger)

            files = [pkg_root / "SOURCE" / "logo.psd", pkg_root / "LICENSE" / "license.pdf"]

            # Create the output file so exists() passes
            rar_path.write_bytes(b"")

            with patch.object(archive, '_rar_exe', return_value=Path("rar.exe")):
                with patch('subprocess.run') as mock_run:
                    mock_run.return_value.returncode = 0
                    archive.create_rar(files, rar_path, work_dir=pkg_root)

                    call_kwargs = mock_run.call_args
                    assert call_kwargs.kwargs.get('cwd') == pkg_root

                    command = call_kwargs.args[0]
                    for arg in command:
                        if arg.endswith('.psd') or arg.endswith('.pdf'):
                            assert str(pkg_root) not in arg, f"Absolute path found in command: {arg}"

    def test_create_rar_without_work_dir_uses_common_parent(self):
        """Without work_dir, the common parent of all files should be used."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            config = MagicMock()
            config.WINRAR_PATH = Path("rar.exe")
            config.WINRAR_GUI_PATH = Path("WinRAR.exe")
            logger = MagicMock()

            archive = RarArchive(config, logger)

            f1 = tmpdir / "file1.psd"
            f2 = tmpdir / "file2.ai"
            f1.write_text("psd")
            f2.write_text("ai")

            output_path = tmpdir / "output.rar"
            output_path.write_bytes(b"")

            with patch.object(archive, '_rar_exe', return_value=Path("rar.exe")):
                with patch('subprocess.run') as mock_run:
                    mock_run.return_value.returncode = 0
                    archive.create_rar([f1, f2], output_path)

                    call_kwargs = mock_run.call_args
                    cwd = call_kwargs.kwargs.get('cwd')
                    assert cwd is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestAssetStateManager:
    def setup_method(self):
        self.config = MockConfig()
        self.logger = MockLogger()
        self.state_manager = AssetStateManager(self.config, self.logger)

    def test_state_file_creation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            folder = tmpdir / "project"
            folder.mkdir()

            self.state_manager.start_processing(folder)

            state_path = self.state_manager.state_path(folder)
            assert state_path.exists()

            state = self.state_manager.load_state(folder)
            assert state["status"] == "processing"
            assert state["started_at"] is not None

    def test_mark_file_completed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            folder = tmpdir / "project"
            folder.mkdir()
            (folder / "logo.psd").write_text("psd")

            self.state_manager.start_processing(folder)
            self.state_manager.mark_file_completed(folder, "logo.psd", archive_name="project.rar", preview_name="logo.avif")

            state = self.state_manager.load_state(folder)
            assert state["files"]["logo.psd"]["status"] == "completed"
            assert state["files"]["logo.psd"]["archive"] == "project.rar"
            assert state["files"]["logo.psd"]["preview"] == "logo.avif"

    def test_mark_interrupted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            folder = tmpdir / "project"
            folder.mkdir()

            self.state_manager.start_processing(folder)
            self.state_manager.mark_interrupted(folder)

            state = self.state_manager.load_state(folder)
            assert state["status"] == "interrupted"
            assert state["interrupted_at"] is not None

    def test_mark_completed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            folder = tmpdir / "project"
            folder.mkdir()

            self.state_manager.start_processing(folder)
            self.state_manager.mark_completed(folder)

            state = self.state_manager.load_state(folder)
            assert state["status"] == "completed"
            assert state["completed_at"] is not None

    def test_get_pending_files_skips_completed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            folder = tmpdir / "project"
            folder.mkdir()
            psd = folder / "logo.psd"
            psd.write_text("psd")
            rar = folder / "logo.rar"
            rar.write_bytes(b"")

            self.state_manager.start_processing(folder)
            self.state_manager.mark_file_completed(folder, "logo.psd", archive_name="logo.rar")
            self.state_manager.mark_completed(folder)

            from pipeline.job import Job
            job = Job(psd)
            pending = self.state_manager.get_pending_files(folder, [job])

            assert len(pending) == 0

    def test_get_pending_files_returns_pending(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            folder = tmpdir / "project"
            folder.mkdir()
            psd = folder / "logo.psd"
            psd.write_text("psd")

            self.state_manager.start_processing(folder)
            self.state_manager.mark_file_failed(folder, "logo.psd", "power outage")

            from pipeline.job import Job
            job = Job(psd)
            pending = self.state_manager.get_pending_files(folder, [job])

            assert len(pending) == 1
            assert pending[0].source_file == psd

    def test_state_file_survives_reload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            folder = tmpdir / "project"
            folder.mkdir()
            (folder / "logo.psd").write_text("psd")

            self.state_manager.start_processing(folder)
            self.state_manager.mark_file_completed(folder, "logo.psd")
            self.state_manager.mark_completed(folder)

            # Create new state manager (simulates app restart)
            state_manager2 = AssetStateManager(self.config, self.logger)
            state = state_manager2.load_state(folder)

            assert state["status"] == "completed"
            assert "logo.psd" in state["files"]