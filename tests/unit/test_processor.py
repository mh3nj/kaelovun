"""
test_processor.py

Unit tests for AssetProcessor pipeline step ordering:
preview → naming → hide layers → save → archive.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pipeline.processor import AssetProcessor
from pipeline.job import Job, JobStatus
from pipeline.asset_package import AssetFile, FileCategory
from files.naming import NameRequest


class MockConfig:
    def __init__(self):
        self.ENGINE = "adobe"
        self.MAX_ARCHIVE_DEPTH = 2
        self.SCRIPTS_DIR = Path("scripts")
        self.NAMING_MODE = "automation"


class MockLogger:
    def __init__(self):
        self.messages = []

    def info(self, msg):
        self.messages.append(("info", msg))

    def warning(self, msg):
        self.messages.append(("warning", msg))

    def error(self, msg):
        self.messages.append(("error", msg))


def make_processor():
    config = MockConfig()
    logger = MockLogger()
    preview = MagicMock()
    preview.convert_to_avif.return_value = (
        Path("test.avif"), Path("test.thumb.avif"), 800, 600
    )
    archive = MagicMock()
    photoshop = MagicMock()
    illustrator = MagicMock()
    storage = MagicMock()
    indesign = MagicMock()

    return AssetProcessor(
        config, logger, preview, archive,
        photoshop, illustrator, storage,
        indesign=indesign,
    )


class TestProcessorStepOrdering:
    """Test that processor follows correct step order: preview → naming → hide layers → save."""

    def test_preview_called_before_naming(self):
        processor = make_processor()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            psd_file = tmpdir / "test.psd"
            psd_file.write_text("fake psd")
            png_file = tmpdir / "test.png"
            png_file.write_text("fake png")
            avif_file = tmpdir / "test.avif"
            avif_file.write_text("fake avif")

            job = Job(psd_file)
            job.final_name = None

            call_order = []

            def mock_generate(asset_file, job):
                call_order.append("preview")
                asset_file.preview_path = Path("test.avif")
                asset_file.thumb_path = Path("test.thumb.avif")

            def mock_naming(job, package):
                call_order.append("naming")
                job.final_name = "MyName"

            def mock_process(asset_file, job):
                call_order.append("hide_layers")

            processor._generate_preview_for_file = mock_generate
            processor._request_package_name = mock_naming
            processor._process_transformable_file = mock_process
            processor._generate_contact_sheet = MagicMock()

            package = MagicMock()
            package.get_transformable_files.return_value = [
                AssetFile(
                    path=psd_file, relative_path=Path("test.psd"),
                    category=FileCategory.TRANSFORMABLE, processor_type="photoshop"
                )
            ]
            package.name = "test"
            package.get_all_files.return_value = []

            processor._process_package(package, job)

            assert call_order.index("preview") < call_order.index("naming")
            assert call_order.index("naming") < call_order.index("hide_layers")

    def test_naming_uses_final_name_when_set(self):
        processor = make_processor()
        package = MagicMock()
        job = Job(Path("/tmp/test.psd"))
        job.final_name = "PreNamed"
        processor._request_package_name(job, package)
        assert job.final_name == "PreNamed"

    def test_naming_uses_default_when_no_name_set(self):
        processor = make_processor()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            psd_file = tmpdir / "test.psd"
            psd_file.write_text("fake psd")

            job = Job(psd_file)
            job.final_name = None

            asset_file = AssetFile(
                path=psd_file, relative_path=Path("test.psd"),
                category=FileCategory.TRANSFORMABLE, processor_type="photoshop"
            )
            package = MagicMock()
            package.get_transformable_files.return_value = [asset_file]
            package.name = "test"

            processor._request_package_name(job, package)
            assert job.final_name == "test"

    def test_processing_sets_correct_job_statuses(self):
        job = Job(Path("/tmp/test.psd"))
        assert job.status == JobStatus.WAITING
        job.set_status(JobStatus.EXPORTING_PREVIEW)
        assert job.status == JobStatus.EXPORTING_PREVIEW
        job.set_status(JobStatus.WAITING_FOR_NAME)
        assert job.status == JobStatus.WAITING_FOR_NAME
        job.set_status(JobStatus.HIDING_LAYERS)
        assert job.status == JobStatus.HIDING_LAYERS
        job.set_status(JobStatus.SAVING)
        assert job.status == JobStatus.SAVING
        job.set_status(JobStatus.CREATING_ARCHIVE)
        assert job.status == JobStatus.CREATING_ARCHIVE

    def test_name_request_event_workflow(self):
        name_req = NameRequest()
        assert name_req.name is None
        assert not name_req.event.is_set()
        name_req.submit("MyArchive")
        assert name_req.name == "MyArchive"
        assert name_req.event.is_set()
        result = name_req.wait()
        assert result == "MyArchive"

    def test_processor_initializes_name_request(self):
        processor = make_processor()
        assert isinstance(processor.name_request, NameRequest)

    def test_processor_initializes_state_manager(self):
        from files.session import AssetStateManager
        processor = make_processor()
        assert isinstance(processor.state_manager, AssetStateManager)


class TestProcessorPreviewGeneration:
    """Test preview generation for different file types."""

    def test_generate_preview_for_psd_calls_photoshop(self):
        processor = make_processor()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            psd_file = tmpdir / "test.psd"
            psd_file.write_text("fake psd")
            asset_file = AssetFile(
                path=psd_file, relative_path=Path("test.psd"),
                category=FileCategory.TRANSFORMABLE, processor_type="photoshop"
            )
            processor._generate_preview_for_file(asset_file, Job(psd_file))
            processor.photoshop.export_preview.assert_called_once()

    def test_generate_preview_for_ai_calls_illustrator(self):
        processor = make_processor()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            ai_file = tmpdir / "test.ai"
            ai_file.write_text("fake ai")
            asset_file = AssetFile(
                path=ai_file, relative_path=Path("test.ai"),
                category=FileCategory.TRANSFORMABLE, processor_type="illustrator"
            )
            processor._generate_preview_for_file(asset_file, Job(ai_file))
            processor.illustrator.export_preview.assert_called_once()

    def test_generate_preview_for_indd_calls_indesign(self):
        processor = make_processor()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            indd_file = tmpdir / "test.indd"
            indd_file.write_text("fake indd")
            asset_file = AssetFile(
                path=indd_file, relative_path=Path("test.indd"),
                category=FileCategory.TRANSFORMABLE, processor_type="indesign"
            )
            processor._generate_preview_for_file(asset_file, Job(indd_file))
            processor.indesign.export_preview.assert_called_once()

    def test_generate_preview_sets_preview_path(self):
        processor = make_processor()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            psd_file = tmpdir / "test.psd"
            psd_file.write_text("fake psd")
            asset_file = AssetFile(
                path=psd_file, relative_path=Path("test.psd"),
                category=FileCategory.TRANSFORMABLE, processor_type="photoshop"
            )
            processor._generate_preview_for_file(asset_file, Job(psd_file))
            assert asset_file.preview_path is not None
            assert asset_file.thumb_path is not None


class TestProcessorTransformableFileProcessing:
    """Test _process_transformable_file step ordering."""

    def test_process_psd_opens_photoshop(self):
        processor = make_processor()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            psd_file = tmpdir / "test.psd"
            psd_file.write_text("fake psd")
            asset_file = AssetFile(
                path=psd_file, relative_path=Path("test.psd"),
                category=FileCategory.TRANSFORMABLE, processor_type="photoshop"
            )
            job = Job(psd_file)
            processor._process_transformable_file(asset_file, job)
            processor.photoshop.open_file.assert_called_once_with(psd_file)

    def test_process_indd_opens_indesign(self):
        processor = make_processor()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            indd_file = tmpdir / "test.indd"
            indd_file.write_text("fake indd")
            asset_file = AssetFile(
                path=indd_file, relative_path=Path("test.indd"),
                category=FileCategory.TRANSFORMABLE, processor_type="indesign"
            )
            job = Job(indd_file)
            processor._process_transformable_file(asset_file, job)
            processor.indesign.open_file.assert_called_once_with(indd_file)

    def test_process_indd_calls_hide_layers_then_save(self):
        processor = make_processor()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            indd_file = tmpdir / "test.indd"
            indd_file.write_text("fake indd")
            asset_file = AssetFile(
                path=indd_file, relative_path=Path("test.indd"),
                category=FileCategory.TRANSFORMABLE, processor_type="indesign"
            )
            job = Job(indd_file)
            processor._process_transformable_file(asset_file, job)
            processor.indesign.hide_layers.assert_called_once()
            processor.indesign.save.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
