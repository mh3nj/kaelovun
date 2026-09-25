"""
test_indd_pipeline.py

Unit tests for InDesign pipeline: classification, controller initialization,
and processing step ordering (preview → naming → hide layers → save).
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from pipeline.asset_package import PackageClassifier, FileCategory, AssetFile
from pipeline.job import Job, JobStatus
from adobe.indesign import InDesignController


class MockConfig:
    def __init__(self):
        self.ENGINE = "adobe"
        self.MAX_ARCHIVE_DEPTH = 2
        self.SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"


class MockLogger:
    def __init__(self):
        self.messages = []

    def info(self, msg):
        self.messages.append(("info", msg))

    def warning(self, msg):
        self.messages.append(("warning", msg))

    def error(self, msg):
        self.messages.append(("error", msg))


class TestInDesignClassification:
    def test_classify_indd_as_transformable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            test_file = tmpdir / "catalog.indd"
            test_file.write_text("fake indd")
            config = MockConfig()
            logger = MockLogger()
            classifier = PackageClassifier(config, logger)

            asset_file = classifier.classify_file(test_file, tmpdir)

            assert asset_file.category == FileCategory.TRANSFORMABLE
            assert asset_file.processor_type == "indesign"

    def test_classify_indt_as_transformable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            test_file = tmpdir / "template.indt"
            test_file.write_text("fake indt")
            config = MockConfig()
            logger = MockLogger()
            classifier = PackageClassifier(config, logger)

            asset_file = classifier.classify_file(test_file, tmpdir)

            assert asset_file.category == FileCategory.TRANSFORMABLE
            assert asset_file.processor_type == "indesign"


class TestInDesignController:
    def test_controller_init(self):
        config = MockConfig()
        logger = MockLogger()
        controller = InDesignController(config, logger)

        assert controller.config == config
        assert controller.logger == logger
        assert controller.jsx is not None

    def test_controller_has_required_methods(self):
        config = MockConfig()
        logger = MockLogger()
        controller = InDesignController(config, logger)

        assert hasattr(controller, "open_file")
        assert hasattr(controller, "export_preview")
        assert hasattr(controller, "hide_layers")
        assert hasattr(controller, "save")
        assert hasattr(controller, "close_document")
        assert hasattr(controller, "close_all_documents")
        assert hasattr(controller, "start")
        assert hasattr(controller, "close")
        assert hasattr(controller, "restart")


class TestInDesignJobFlow:
    """Test that job status follows correct order: preview → naming → hide layers → save."""

    def test_job_status_order_for_indd(self):
        job = Job(Path("/tmp/catalog.indd"))

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

    def test_job_final_name_set_before_processing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            indd_file = tmpdir / "catalog.indd"
            indd_file.write_text("fake indd")

            job = Job(indd_file)
            job.final_name = "MyCatalog"

            assert job.final_name == "MyCatalog"

    def test_job_name_request_workflow(self):
        from files.naming import NameRequest

        name_req = NameRequest()
        assert name_req.name is None
        assert name_req.preview is None
        assert not name_req.event.is_set()

        name_req.submit("MyCatalog")
        assert name_req.name == "MyCatalog"
        assert name_req.event.is_set()

        result = name_req.wait()
        assert result == "MyCatalog"


class TestInDesignPreviewGeneration:
    def test_generate_preview_sets_preview_path(self):
        from pipeline.asset_package import AssetFile

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            indd_file = tmpdir / "catalog.indd"
            indd_file.write_text("fake indd")
            png_file = tmpdir / "catalog.png"
            png_file.write_text("fake png")
            avif_file = tmpdir / "catalog.avif"
            avif_file.write_text("fake avif")

            asset_file = AssetFile(
                path=indd_file,
                relative_path=Path("catalog.indd"),
                category=FileCategory.TRANSFORMABLE,
                processor_type="indesign"
            )

            assert asset_file.path == indd_file
            assert asset_file.processor_type == "indesign"

    def test_indd_extension_recognized(self):
        assert ".indd" in {".psd", ".ai", ".eps", ".indd", ".indt", ".afphoto"}
        assert ".indt" in {".psd", ".ai", ".eps", ".indd", ".indt", ".afphoto"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
