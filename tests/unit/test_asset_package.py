"""
test_asset_package.py

Unit tests for AssetPackage and PackageClassifier.
"""

import tempfile
from pathlib import Path

import pytest

from pipeline.asset_package import AssetPackage, PackageClassifier, FileCategory, AssetFile


class MockConfig:
    def __init__(self):
        pass


class MockLogger:
    def __init__(self):
        self.messages = []

    def info(self, msg):
        self.messages.append(("info", msg))

    def warning(self, msg):
        self.messages.append(("warning", msg))

    def error(self, msg):
        self.messages.append(("error", msg))


class TestFileCategory:
    def test_categories_exist(self):
        assert FileCategory.TRANSFORMABLE.value == "transformable"
        assert FileCategory.PRESERVABLE.value == "preservable"
        assert FileCategory.CONTAINER.value == "container"
        assert FileCategory.LICENSE_DOC.value == "license_doc"


class TestAssetFile:
    def test_asset_file_creation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            test_file = tmpdir / "test.psd"
            test_file.write_text("fake psd content")

            asset_file = AssetFile(
                path=test_file,
                relative_path=Path("test.psd"),
                category=FileCategory.TRANSFORMABLE,
                processor_type="photoshop"
            )

            assert asset_file.path == test_file
            assert asset_file.relative_path == Path("test.psd")
            assert asset_file.category == FileCategory.TRANSFORMABLE
            assert asset_file.processor_type == "photoshop"
            assert asset_file.original_size > 0


class TestPackageClassifier:
    def setup_method(self):
        self.config = MockConfig()
        self.logger = MockLogger()
        self.classifier = PackageClassifier(self.config, self.logger)

    def test_classify_psd_as_transformable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            test_file = tmpdir / "logo.psd"
            test_file.write_text("fake psd")

            asset_file = self.classifier.classify_file(test_file, tmpdir)

            assert asset_file.category == FileCategory.TRANSFORMABLE
            assert asset_file.processor_type == "photoshop"

    def test_classify_ai_as_transformable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            test_file = tmpdir / "logo.ai"
            test_file.write_text("fake ai")

            asset_file = self.classifier.classify_file(test_file, tmpdir)

            assert asset_file.category == FileCategory.TRANSFORMABLE
            assert asset_file.processor_type == "illustrator"

    def test_classify_indd_as_transformable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            test_file = tmpdir / "catalog.indd"
            test_file.write_text("fake indd")

            asset_file = self.classifier.classify_file(test_file, tmpdir)

            assert asset_file.category == FileCategory.TRANSFORMABLE
            assert asset_file.processor_type == "indesign"

    def test_classify_affinity_as_transformable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            test_file = tmpdir / "design.afphoto"
            test_file.write_text("fake afphoto")

            asset_file = self.classifier.classify_file(test_file, tmpdir)

            assert asset_file.category == FileCategory.TRANSFORMABLE
            assert asset_file.processor_type == "affinity"

    def test_classify_pdf_as_preservable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            test_file = tmpdir / "document.pdf"
            test_file.write_text("fake pdf")

            asset_file = self.classifier.classify_file(test_file, tmpdir)

            assert asset_file.category == FileCategory.PRESERVABLE
            assert asset_file.processor_type is None

    def test_classify_license_pdf_as_license_doc(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            test_file = tmpdir / "LICENSE.pdf"
            test_file.write_text("fake license")

            asset_file = self.classifier.classify_file(test_file, tmpdir)

            assert asset_file.category == FileCategory.LICENSE_DOC
            assert asset_file.processor_type is None

    def test_classify_readme_as_license_doc(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            test_file = tmpdir / "README.txt"
            test_file.write_text("readme content")

            asset_file = self.classifier.classify_file(test_file, tmpdir)

            assert asset_file.category == FileCategory.LICENSE_DOC

    def test_classify_eula_as_license_doc(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            test_file = tmpdir / "EULA.txt"
            test_file.write_text("eula content")

            asset_file = self.classifier.classify_file(test_file, tmpdir)

            assert asset_file.category == FileCategory.LICENSE_DOC

    def test_classify_font_as_preservable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            test_file = tmpdir / "font.otf"
            test_file.write_text("fake font")

            asset_file = self.classifier.classify_file(test_file, tmpdir)

            assert asset_file.category == FileCategory.PRESERVABLE

    def test_classify_image_as_preservable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            test_file = tmpdir / "photo.jpg"
            test_file.write_text("fake jpg")

            asset_file = self.classifier.classify_file(test_file, tmpdir)

            assert asset_file.category == FileCategory.PRESERVABLE

    def test_classify_unknown_as_preservable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            test_file = tmpdir / "unknown.xyz"
            test_file.write_text("fake unknown")

            asset_file = self.classifier.classify_file(test_file, tmpdir)

            assert asset_file.category == FileCategory.PRESERVABLE

    def test_classify_archive_as_container(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            test_file = tmpdir / "archive.zip"
            test_file.write_text("fake zip")

            asset_file = self.classifier.classify_file(test_file, tmpdir)

            assert asset_file.category == FileCategory.CONTAINER
            assert asset_file.processor_type == "archive"


class TestAssetPackage:
    def setup_method(self):
        self.config = MockConfig()
        self.logger = MockLogger()
        self.classifier = PackageClassifier(self.config, self.logger)

    def test_package_creation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            (tmpdir / "logo.psd").write_text("psd")
            (tmpdir / "logo.ai").write_text("ai")
            (tmpdir / "LICENSE.pdf").write_text("license")

            package = self.classifier.classify_package(tmpdir)

            assert package.name == tmpdir.name
            assert len(package.files) == 3

            transformable = package.get_transformable_files()
            assert len(transformable) == 2

            preservable = package.get_preservable_files()
            assert len(preservable) == 1
            assert preservable[0].category == FileCategory.LICENSE_DOC

    def test_package_with_subdirectories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            (tmpdir / "SOURCE").mkdir()
            (tmpdir / "SOURCE" / "logo.psd").write_text("psd")
            (tmpdir / "EXPORT").mkdir()
            (tmpdir / "EXPORT" / "logo.png").write_text("png")
            (tmpdir / "LICENSE").mkdir()
            (tmpdir / "LICENSE" / "license.txt").write_text("license")

            package = self.classifier.classify_package(tmpdir)

            assert len(package.files) == 3

            # Check relative paths preserved
            rel_paths = [f.relative_path for f in package.files]
            assert Path("SOURCE/logo.psd") in rel_paths
            assert Path("EXPORT/logo.png") in rel_paths
            assert Path("LICENSE/license.txt") in rel_paths


if __name__ == "__main__":
    pytest.main([__file__, "-v"])