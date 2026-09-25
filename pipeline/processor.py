"""
processor.py

Main asset processing pipeline with package-based architecture.

Pipeline order per package:
  1. Discover and classify package
  2. Extract archives to safe workspace (if needed)
  3. Generate previews for transformable assets
  4. Process transformable assets (hide layers, save)
  5. Reconstruct package preserving structure
  6. Create final RAR archive
  7. Verify archive
  8. Cleanup (only after successful verification)
"""

from pathlib import Path
import tempfile
import shutil

from pipeline.job import JobStatus
from pipeline.asset_package import AssetPackage, PackageClassifier, FileCategory, AssetFile
from files.naming import NameRequest
from files.filename import FilenameManager
from files.cleanup import CleanupManager
from files.archive_extraction import ArchiveExtractor
from files.session import AssetStateManager
from adobe.recovery import AdobeRecovery


class AssetProcessor:

    def __init__(self, config, logger, preview, archive, photoshop, illustrator, storage, session=None, indesign=None, affinity=None):
        self.config = config
        self.logger = logger
        self.preview = preview
        self.archive = archive
        self.photoshop = photoshop
        self.illustrator = illustrator
        self.indesign = indesign
        self.affinity = affinity
        self.storage = storage
        self.session = session

        self.name_request = NameRequest()
        self.filename = FilenameManager(logger)
        self.cleanup_manager = CleanupManager(logger)
        self.recovery = AdobeRecovery(config, logger)
        self.classifier = PackageClassifier(config, logger)
        self.extractor = ArchiveExtractor(config, logger, max_depth=getattr(config, 'MAX_ARCHIVE_DEPTH', 2))
        self.state_manager = AssetStateManager(config, logger)

        self.should_continue = lambda: True
        self._total_packages = 0
        self._processed = 0
        self._failed = 0
        self._workspace_root = None

    def process(self, job):
        """Main entry point - process a job which may be a file, directory, or archive."""
        workspace_created = False
        folder_to_track = None
        try:
            if not self.storage.require_space(job.source_file.parent, should_continue=self.should_continue):
                raise RuntimeError("Queue stopped while waiting for disk space.")

            # Track folder-level state for directories and archives
            source_folder = None
            if job.is_archive:
                source_folder = job.source_file.parent
            elif job.source_file.is_dir():
                source_folder = job.source_file

            if source_folder:
                folder_to_track = source_folder
                self.state_manager.start_processing(source_folder)

            # Create workspace
            self._workspace_root = self._create_workspace(job)
            workspace_created = True

            # Classify input into an AssetPackage
            package = self._prepare_package(job)

            # Process the package
            self._process_package(package, job)

            # Create final archive
            self._create_final_archive(package, job)

            # Verify archive
            job.set_status(JobStatus.VERIFYING)
            if not self._verify_archive(job):
                raise RuntimeError(f"Archive verification failed for {job.archive_file.name}")

            # Only now cleanup
            job.set_status(JobStatus.CLEANUP)
            self._cleanup_workspace(package, job)

            job.set_status(JobStatus.DONE)
            self._processed += 1

            # Mark file as completed in state tracking
            if folder_to_track:
                archive_name = job.archive_file.name if job.archive_file else None
                preview_name = None
                thumb_name = None
                if job.source_file.suffix.lower() in ('.psd', '.ai', '.eps', '.indd', '.indt'):
                    preview_name = job.source_file.stem + ".avif"
                    thumb_name = job.source_file.stem + ".thumb.avif"
                self.state_manager.mark_file_completed(
                    folder_to_track, job.source_file.name,
                    archive_name=archive_name,
                    preview_name=preview_name,
                    thumb_name=thumb_name
                )

        except Exception as error:
            self._failed += 1
            self.handle_error(job, error)
            if folder_to_track:
                self.state_manager.mark_interrupted(folder_to_track)
        finally:
            if workspace_created:
                try:
                    self._cleanup_workspace_root()
                except Exception:
                    pass
            if folder_to_track and job.status == JobStatus.DONE:
                self.state_manager.mark_completed(folder_to_track)

    def _create_workspace(self, job) -> Path:
        """Create a safe temporary workspace for processing."""
        # Use a location with plenty of space, preferably same drive as source
        source_drive = job.source_file.drive or str(job.source_file.anchor)
        workspace_base = Path(tempfile.gettempdir()) / "kaelovun_workspace"
        workspace_base.mkdir(parents=True, exist_ok=True)

        # Create unique workspace for this job
        workspace = workspace_base / f"job_{id(job)}"
        workspace.mkdir(parents=True, exist_ok=True)
        self.logger.info(f"Created workspace: {workspace}")
        return workspace

    def _cleanup_workspace_root(self):
        """Clean up the workspace root directory."""
        if self._workspace_root and self._workspace_root.exists():
            try:
                shutil.rmtree(self._workspace_root)
                self.logger.info(f"Cleaned up workspace: {self._workspace_root}")
            except Exception as e:
                self.logger.warning(f"Could not clean up workspace: {e}")

    def _prepare_package(self, job) -> AssetPackage:
        """Prepare AssetPackage from job input (file, directory, or archive)."""
        source = job.source_file

        if job.is_archive:
            # Extract archive to workspace
            job.set_status(JobStatus.EXTRACTING_ARCHIVE)
            extract_root, extracted_files = self.extractor.extract(source, self._workspace_root)

            # Classify the extracted contents
            package = self.classifier.classify_package(
                extract_root,
                source_type="archive",
                original_archive=source
            )
            package.workspace_dir = extract_root
            job.extracted_root = extract_root
            job.package_files = [f.path for f in package.files]

        elif source.is_dir():
            # Directory input
            package = self.classifier.classify_package(source, source_type="directory")
            package.workspace_dir = source
            job.package_files = [f.path for f in package.files]

        else:
            # Single file input
            package = self.classifier.classify_package(source.parent, source_type="file")
            # Filter to just this file
            package.files = [f for f in package.files if f.path == source]
            package.workspace_dir = source.parent
            job.package_files = [f.path for f in package.files]

        job.workspace_dir = package.workspace_dir
        return package

    def _process_package(self, package: AssetPackage, job):
        """Process all transformable files in the package."""
        transformable = package.get_transformable_files()

        if not transformable and not job.is_archive:
            self.logger.info("No transformable files in package, skipping preview/processing")
            return

        if transformable:
            job.set_status(JobStatus.PROCESSING_PACKAGE)
            self.logger.info(f"Processing {len(transformable)} transformable files in package")

            # Generate all previews first
            for i, asset_file in enumerate(transformable):
                if not self.should_continue():
                    raise RuntimeError("Queue stopped during package processing.")
                self.logger.info(f"Generating preview {i+1}/{len(transformable)}")
                try:
                    self._generate_preview_for_file(asset_file, job)
                except Exception as e:
                    self.logger.error(f"Failed to generate preview for {asset_file.relative_path}: {e}")
                    asset_file.error = str(e)

            # Request name for the package before hiding layers
            if job.is_archive:
                # For archives, use the archive stem as default name
                if not job.final_name:
                    job.final_name = job.source_file.stem
                self.logger.info(f"Archive name: {job.final_name}")
            else:
                # Request name from user
                self._request_package_name(job, package)

            # Now process all files (hide layers, save)
            for i, asset_file in enumerate(transformable):
                if not self.should_continue():
                    raise RuntimeError("Queue stopped during package processing.")
                self.logger.info(f"Processing {asset_file.relative_path} ({i+1}/{len(transformable)})")
                try:
                    self._process_transformable_file(asset_file, job)
                except Exception as e:
                    self.logger.error(f"Failed to process {asset_file.relative_path}: {e}")
                    asset_file.error = str(e)

        if job.is_archive:
            self._generate_contact_sheet(package, job)

    def _request_package_name(self, job, package):
        """Request a name for the package. CLI uses stdin, GUI uses NameRequest."""
        if job.final_name:
            return
        transformable = package.get_transformable_files()
        default_name = transformable[0].path.stem if transformable else package.name
        if self.name_request.event and not self.name_request.event.is_set():
            try:
                self.name_request.preview = transformable[0].preview_path if transformable else None
                name = self.name_request.wait()
                if name:
                    job.final_name = name
                    return
            except Exception:
                pass
        try:
            name = input(f"Enter name for {default_name} [{default_name}]: ").strip()
            if name:
                job.final_name = name
                return
        except (EOFError, KeyboardInterrupt):
            pass
        job.final_name = default_name
        self.logger.info(f"Package name: {job.final_name}")

    def _generate_preview_for_file(self, asset_file: AssetFile, job):
        """Generate preview for a transformable file."""
        # For package processing, we generate previews for naming but
        # the user names the PACKAGE not individual files
        # We'll use the first transformable file's preview as the package preview

        png = asset_file.path.with_suffix(".png")
        ext = asset_file.path.suffix.lower()

        if self._use_affinity(ext):
            self._require_affinity().export_preview(png)
        elif ext == ".psd":
            self.photoshop.export_preview(png)
        elif ext in (".ai", ".eps"):
            self.illustrator.export_preview(png)
        elif ext in (".indd", ".indt"):
            if self.indesign:
                self.indesign.export_preview(png)
            else:
                raise RuntimeError("InDesign controller not available")
        else:
            # For other formats, try to use PIL
            try:
                from PIL import Image
                img = Image.open(asset_file.path)
                img.save(png, "PNG")
            except Exception as e:
                self.logger.warning(f"Could not generate preview for {asset_file.path}: {e}")
                return

        # Convert to AVIF
        avif_path = asset_file.path.with_suffix(".avif")
        asset_file.preview_path, asset_file.thumb_path, w, h = self.preview.convert_to_avif(
            png, avif_path
        )
        self.preview.delete_file_safe(png)

    def _generate_contact_sheet(self, package: AssetPackage, job):
        """Create a grid contact sheet from all preservable images in the package."""
        if not self.preview:
            return
        images = [f for f in package.get_all_files()
                  if f.category in (FileCategory.PRESERVABLE, FileCategory.LICENSE_DOC)
                  and f.path.suffix.lower() in self.preview._image_extensions]
        if len(images) < 2:
            self.logger.info("Not enough images for contact sheet, skipping")
            return

        job.set_status(JobStatus.GENERATING_PREVIEW)
        self.logger.info(f"Creating contact sheet with {len(images)} images")

        sheet_path = package.workspace_dir / f"{package.name}_contact_sheet.png"
        self.preview.create_contact_sheet([f.path for f in images], sheet_path, cols=4)

        try:
            avif_path = sheet_path.with_suffix(".avif")
            self.preview.convert_to_avif(sheet_path, avif_path)
            self.preview.delete_file_safe(sheet_path)

            sheet_asset = AssetFile(
                path=avif_path,
                relative_path=Path(f"{package.name}_contact_sheet.avif"),
                category=FileCategory.PRESERVABLE,
                preview_path=avif_path,
                thumb_path=avif_path.with_suffix(".thumb.avif")
            )
            package.add_file(sheet_asset)
            self.logger.info(f"Contact sheet preview created: {avif_path.name}")
        except Exception as e:
            self.logger.warning(f"Failed to create contact sheet AVIF: {e}")

    def _process_transformable_file(self, asset_file: AssetFile, job):
        """Process a single transformable file (hide layers, save)."""
        ext = asset_file.path.suffix.lower()

        # Open document
        job.set_status(JobStatus.OPENING)
        if self._use_affinity(ext):
            self._require_affinity().open_file(asset_file.path)
        elif ext == ".psd":
            self.photoshop.open_file(asset_file.path)
        elif ext in (".ai", ".eps"):
            self.illustrator.open_file(asset_file.path)
        elif ext in (".indd", ".indt"):
            if self.indesign:
                self.indesign.open_file(asset_file.path)
            else:
                raise RuntimeError("InDesign controller not available")
        else:
            raise RuntimeError(f"Unsupported format for processing: {ext}")

        try:
            # Hide layers
            job.set_status(JobStatus.HIDING_LAYERS)
            if self._use_affinity(ext):
                self._require_affinity().hide_layers()
            elif ext == ".psd":
                self.photoshop.hide_layers()
            elif ext in (".ai", ".eps"):
                self.illustrator.hide_layers()
            elif ext in (".indd", ".indt"):
                if self.indesign:
                    self.indesign.hide_layers()
                else:
                    raise RuntimeError("InDesign controller not available")

            # Save
            job.set_status(JobStatus.SAVING)
            if self._use_affinity(ext):
                self._require_affinity().save()
            elif ext == ".psd":
                self.photoshop.save()
            elif ext in (".ai", ".eps"):
                self.illustrator.save()
            elif ext in (".indd", ".indt"):
                if self.indesign:
                    self.indesign.save()
                else:
                    raise RuntimeError("InDesign controller not available")

        finally:
            # Close document
            if self._use_affinity(ext):
                self._require_affinity().close_document()
            elif ext == ".psd":
                self.photoshop.close_document()
            elif ext in (".ai", ".eps"):
                self.illustrator.close_document()
            elif ext in (".indd", ".indt"):
                if self.indesign:
                    self.indesign.close_document()

    def _create_final_archive(self, package: AssetPackage, job):
        """Create the final RAR archive preserving package structure."""
        job.set_status(JobStatus.CREATING_ARCHIVE)

        # Determine archive name
        if job.final_name:
            archive_name = job.final_name
        elif job.is_archive:
            archive_name = job.source_file.stem
        else:
            archive_name = package.name

        # Archive goes next to the original source
        if job.is_archive and job.archive_metadata:
            archive_dir = job.source_file.parent
        else:
            archive_dir = package.root_path.parent if package.source_type == "directory" else package.root_path

        archive_path = archive_dir / f"{archive_name}.rar"

        # Collect all files to archive (preserving structure)
        files_to_archive = []
        for asset_file in package.get_all_files():
            files_to_archive.append(asset_file.path)
            if asset_file.preview_path and asset_file.preview_path.exists():
                files_to_archive.append(asset_file.preview_path)
            if asset_file.thumb_path and asset_file.thumb_path.exists():
                files_to_archive.append(asset_file.thumb_path)

        self.logger.info(f"Creating archive with {len(files_to_archive)} files")
        self.archive.create_rar(files_to_archive, archive_path, work_dir=package.root_path)

        job.archive_file = archive_path
        package.archive_path = archive_path
        package.archive_created = True

    def _verify_archive(self, job) -> bool:
        """Verify the created archive."""
        if not job.archive_file or not job.archive_file.exists():
            return False

        # Test archive integrity
        if not self.archive.test_archive(job.archive_file):
            return False

        # Verify expected files are present (optional - RAR test covers this)
        return True

    def _cleanup_workspace(self, package: AssetPackage, job):
        """Clean up workspace files after successful verification."""
        if job.is_archive:
            self.extractor.cleanup_all()
        elif package.workspace_dir and package.workspace_dir != package.root_path:
            self.extractor.cleanup_all()

        # For directory/file inputs, the original files are NOT deleted
        # Only the loose files in workspace are cleaned up
        # The original source remains untouched per preservation philosophy

    def set_queue_size(self, size: int):
        self._total_packages = size
        self._processed = 0
        self._failed = 0

    def get_summary(self) -> str:
        return (
            f"Queue complete. "
            f"Total: {self._total_packages}, "
            f"Success: {self._processed}, "
            f"Failed: {self._failed}"
        )

    def _use_affinity(self, ext: str) -> bool:
        """Native Affinity files always use Affinity; PSD uses only Photoshop.
        AI/EPS follow ENGINE since both Affinity and Illustrator support them."""
        if ext in (".afphoto", ".afdesign", ".afpub"):
            return True
        if ext == ".psd":
            return False
        return ext in (".ai", ".eps") and getattr(self.config, "ENGINE", "adobe") == "affinity"

    def _require_affinity(self):
        if not self.affinity:
            raise RuntimeError(
                "Job needs Affinity but no Affinity controller is wired. "
                "Set ENGINE to 'adobe' or check the Affinity setup."
            )
        return self.affinity

    def handle_error(self, job, error):
        self.logger.error(f"{job.source_file.name}: {error}")
        if self.recovery.is_recoverable(error) and job.can_retry(self.config.MAX_RETRIES):
            job.increase_retry()
            job.error_message = str(error)
            self.logger.warning("Recoverable error detected. Restarting.")
            # Restart relevant app
            self.recovery.wait_ready()
            self.process(job)
            return
        job.fail(error)