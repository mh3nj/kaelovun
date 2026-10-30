"""
processor.py

Main asset processing pipeline with package-based architecture.

Pipeline order per package:
  1. Discover and classify package
  2. Extract archives to safe workspace (if needed)
  3. Generate previews for transformable assets   (open -> export -> close)
  4. Ask for the package name (GUI prompt or console)
  5. Process transformable assets (hide layers, save)
  6. Build the final archive under a temporary name   (RAR, 7z or ZIP)
  7. Verify it: integrity test + names + sizes (+ CRC32 in "paranoid" mode)
  8. Publish: atomically rename to a unique final name. Never overwrites anything.
  9. Cleanup (only after successful verification)
"""

import os
import shutil
import time
from pathlib import Path
from typing import List, Optional

from pipeline.job import JobStatus
from pipeline.asset_package import AssetPackage, PackageClassifier, FileCategory, AssetFile
from files.naming import NameRequest
from files.filename import FilenameManager
from files.cleanup import CleanupManager
from files.archive_extraction import ArchiveExtractor
from files.archive_prefs import load_prefs
from files.manifest import (
    Manifest, ManifestEntry, build_manifest, manifest_from_paths, verify_entries,
)
from files.session import AssetStateManager
from files.sidecar import write_sidecar
from files.workspace import free_gb, make_workspace, remove_tree, workspace_base
from files.archive_backends import human_size
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
        self.naming_backend = "console"      # the GUI sets this to "gui"
        self.output_dir: Optional[Path] = None   # CLI --output
        self.keep_workspace = False              # CLI --no-cleanup
        self.reports: List[dict] = []
        self._total_packages = 0
        self._processed = 0
        self._failed = 0
        self._workspace_root = None
        self._prefs = None
        self._kept_open = None      # (controller, asset) whose document stays open while naming

    # The GUI polls this name; keep both spellings working.
    @property
    def _total_assets(self) -> int:
        return self._total_packages

    # ──────────────────────────────────────────────
    # Entry point
    # ──────────────────────────────────────────────

    def process(self, job):
        """Process a job (file, directory or archive), retrying recoverable errors."""
        while True:
            try:
                self._process_once(job)
                return
            except Exception as error:
                if self.handle_error(job, error):
                    continue
                self._failed += 1
                return

    def _cancelled(self) -> bool:
        return not self.should_continue()

    def _process_once(self, job):
        started = time.monotonic()
        workspace_created = False
        folder_to_track = None
        job.archive_file = None
        try:
            self._prefs = prefs = load_prefs(self.config)
            if not self.storage.require_space(job.source_file.parent, should_continue=self.should_continue):
                raise RuntimeError("Queue stopped while waiting for disk space.")

            source_bytes = self._source_bytes(job.source_file)
            self._check_workspace_space(prefs, job, source_bytes)

            # Track folder-level state for directories and archives
            source_folder = None
            if job.is_archive:
                source_folder = job.source_file.parent
            elif job.source_file.is_dir():
                source_folder = job.source_file

            if source_folder:
                folder_to_track = source_folder
                self.state_manager.start_processing(source_folder)

            self._workspace_root = self._create_workspace(job)
            workspace_created = True

            package = self._prepare_package(job)
            self._process_package(package, job)
            self._create_final_archive(package, job)

            job.set_status(JobStatus.VERIFYING)
            if not self._verify_archive(job):
                raise RuntimeError(f"Archive verification failed for {job.archive_file.name}")

            self._publish_archive(package, job)

            job.set_status(JobStatus.CLEANUP)
            self._cleanup_workspace(package, job)

            job.set_status(JobStatus.DONE)
            self._processed += 1
            job.report = self._build_report(job, package, source_bytes, time.monotonic() - started)
            self.reports.append(job.report)
            self._write_sidecar_if_enabled(job, package, prefs)

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
        except BaseException:
            self._discard_partial(job)
            if folder_to_track:
                self.state_manager.mark_interrupted(folder_to_track)
            raise
        finally:
            if workspace_created and not self.keep_workspace:
                try:
                    self._cleanup_workspace_root()
                except Exception:
                    pass
            if folder_to_track and job.status == JobStatus.DONE:
                self.state_manager.mark_completed(folder_to_track)

    # ──────────────────────────────────────────────
    # Workspace
    # ──────────────────────────────────────────────

    def _create_workspace(self, job) -> Path:
        """Create a unique, safe scratch folder for this job."""
        workspace = make_workspace("job_", self._prefs)
        self.logger.info(f"Created workspace: {workspace}")
        return workspace

    def _check_workspace_space(self, prefs, job, source_bytes: int):
        """The scratch folder holds a full copy of the package; check THAT drive."""
        base = workspace_base(prefs)
        self.storage.require_space(base, should_continue=self.should_continue)
        if source_bytes and not job.is_archive:
            need_gb = source_bytes * 1.1 / (1024 ** 3)
            have_gb = free_gb(base)
            if have_gb < need_gb:
                raise RuntimeError(
                    f"Not enough space in the workspace folder ({base}): need about "
                    f"{need_gb:.1f} GB, only {have_gb:.1f} GB free. Choose a roomier "
                    f"'Workspace folder' in Settings > Archive.")

    def _cleanup_workspace_root(self):
        """Clean up the workspace root directory."""
        if self._workspace_root and self._workspace_root.exists():
            try:
                remove_tree(self._workspace_root)
                self.logger.info(f"Cleaned up workspace: {self._workspace_root}")
            except Exception as e:
                self.logger.warning(f"Could not clean up workspace: {e}")

    @staticmethod
    def _source_bytes(path: Path) -> int:
        try:
            if path.is_file():
                return path.stat().st_size
            return sum(Path(dp, fn).stat().st_size
                       for dp, _d, fns in os.walk(path) for fn in fns)
        except OSError:
            return 0

    # ──────────────────────────────────────────────
    # Package preparation
    # ──────────────────────────────────────────────

    def _prepare_package(self, job) -> AssetPackage:
        """Prepare AssetPackage from job input (file, directory, or archive)."""
        source = job.source_file

        if job.is_archive:
            # Extract archive to workspace
            job.set_status(JobStatus.EXTRACTING_ARCHIVE)
            self.extractor.cancel = self._cancelled
            try:
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
            except RuntimeError as e:
                if "password" in str(e).lower() or "encrypted" in str(e).lower():
                    self.logger.warning(f"Archive is password-protected, preserving as-is: {source.name}")
                    # Create a package with just the archive file itself (preserve as-is)
                    package = self.classifier.classify_package(
                        source.parent,
                        source_type="archive",
                        original_archive=source
                    )
                    # Filter to just this archive file
                    package.files = [f for f in package.files if f.path == source]
                    package.workspace_dir = source.parent
                    job.package_files = [f.path for f in package.files]
                    job.workspace_dir = package.workspace_dir
                    job.is_archive = False  # Treat as regular file for preservation
                else:
                    raise

        elif source.is_dir():
            # Directory input - COPY to workspace first (safe-copy model)
            job.set_status(JobStatus.EXTRACTING_ARCHIVE)
            workspace_copy = self._workspace_root / source.name
            shutil.copytree(source, workspace_copy)
            self.logger.info(f"Copied directory to workspace: {workspace_copy}")

            # Classify the copied contents
            package = self.classifier.classify_package(
                workspace_copy,
                source_type="directory",
                original_archive=None
            )
            package.workspace_dir = workspace_copy
            job.package_files = [f.path for f in package.files]

        else:
            # Single file input - copy to workspace
            workspace_file = self._workspace_root / source.name
            shutil.copy2(source, workspace_file)
            self.logger.info(f"Copied file to workspace: {workspace_file}")

            package = self.classifier.classify_package(workspace_file.parent, source_type="file")
            # Filter to just this file
            package.files = [f for f in package.files if f.path == workspace_file]
            package.workspace_dir = workspace_file.parent
            job.package_files = [f.path for f in package.files]

        job.workspace_dir = package.workspace_dir
        return package

    # ──────────────────────────────────────────────
    # Engine helpers
    # ──────────────────────────────────────────────

    def _controller_for(self, ext: str):
        """The app controller that handles ``ext`` (None = no app, e.g. plain images)."""
        if self._use_affinity(ext):
            return self._require_affinity()
        if ext == ".psd":
            return self.photoshop
        if ext in (".ai", ".eps"):
            return self.illustrator
        if ext in (".indd", ".indt"):
            if self.indesign:
                return self.indesign
            raise RuntimeError("InDesign controller not available")
        return None

    # ──────────────────────────────────────────────
    # Packages
    # ──────────────────────────────────────────────

    def _process_package(self, package: AssetPackage, job):
        """Process all transformable files in the package."""
        transformable = package.get_transformable_files()

        if not transformable and not job.is_archive:
            self.logger.info("No transformable files in package, skipping preview/processing")
            return

        if transformable:
            job.set_status(JobStatus.PROCESSING_PACKAGE)
            self.logger.info(f"Processing {len(transformable)} transformable files in package")

            # With the GUI prompt the representative document stays OPEN while you
            # name the package, so you can tweak it in the app and press "Regen Preview".
            interactive = (not job.is_archive and not job.final_name
                           and self.naming_backend == "gui"
                           and getattr(self.config, "NAMING_MODE", "manual") != "automation")
            representative = transformable[0] if interactive else None
            order = [a for a in transformable if a is not representative]
            if representative is not None:
                order.append(representative)    # last, so nothing closes it before naming

            # Generate all previews first
            try:
                for i, asset_file in enumerate(order):
                    if not self.should_continue():
                        raise RuntimeError("Queue stopped during package processing.")
                    self.logger.info(f"Generating preview {i+1}/{len(order)}")
                    try:
                        extra = {"keep_open": True} if asset_file is representative else {}
                        self._generate_preview_for_file(asset_file, job, **extra)
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
            finally:
                self._close_kept_open()

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

    # ──────────────────────────────────────────────
    # Naming
    # ──────────────────────────────────────────────

    def _request_package_name(self, job, package):
        """Request a name for the package. Respects NAMING_MODE and the naming backend."""
        if job.final_name:
            return
        transformable = package.get_transformable_files()
        default_name = transformable[0].path.stem if transformable else package.name

        if getattr(self.config, "NAMING_MODE", "manual") == "automation":
            job.final_name = default_name
            self.logger.info(f"Package name (auto): {job.final_name}")
            return

        name = None
        if self.naming_backend == "gui":
            name = self._ask_gui_name(job, transformable, default_name)
        else:
            try:
                name = input(f"Enter name for {default_name} [{default_name}]: ").strip()
            except (EOFError, KeyboardInterrupt, OSError):
                name = None

        name = self.filename.normalize(name) if name else ""
        job.final_name = name or default_name
        self.logger.info(f"Package name: {job.final_name}")

    def _ask_gui_name(self, job, transformable, default_name) -> Optional[str]:
        """Show the preview in the GUI and wait for a name (handles 'Regen Preview')."""
        job.set_status(JobStatus.WAITING_FOR_NAME)
        with_preview = (self._kept_open[1] if self._kept_open else None) or next(
            (a for a in transformable if a.preview_path and Path(a.preview_path).exists()), None)
        shown = Path(with_preview.preview_path) if with_preview else Path("no-preview")
        request = self.name_request.request_name(shown, default_name)
        try:
            while True:
                if not self.should_continue():
                    raise RuntimeError("Queue stopped while waiting for a name.")
                if not request.event.wait(0.5):
                    continue
                if request.regenerate_requested and with_preview:
                    request.regenerate_requested = False
                    request.event.clear()
                    try:
                        if self._kept_open and self._kept_open[1] is with_preview:
                            self._export_preview_from_open_document(with_preview, job)
                        else:
                            self._generate_preview_for_file(with_preview, job)
                        request.preview = Path(with_preview.preview_path)
                    except Exception as e:
                        self.logger.warning(f"Could not regenerate preview: {e}")
                    request.preview_version += 1
                    continue
                request.regenerate_requested = False
                return request.name
        finally:
            # Nothing should look like a pending prompt once we've moved on.
            request.preview = None

    # ──────────────────────────────────────────────
    # Previews
    # ──────────────────────────────────────────────

    def _close_kept_open(self):
        """Close the document that was held open for the naming prompt (if any)."""
        if self._kept_open:
            controller, _asset = self._kept_open
            self._kept_open = None
            try:
                controller.close_document()
            except Exception as e:
                self.logger.warning(f"Could not close the preview document: {e}")

    def _export_preview_from_open_document(self, asset_file: AssetFile, job):
        """'Regen Preview': re-export from the document you may have just edited."""
        controller, _asset = self._kept_open
        png = asset_file.path.with_suffix(".png")
        job.set_status(JobStatus.EXPORTING_PREVIEW)
        controller.export_preview(png)
        self._finish_preview(asset_file, job, png)

    def _generate_preview_for_file(self, asset_file: AssetFile, job, keep_open: bool = False):
        """
        Generate a preview for a transformable file.

        The document must be OPEN before a preview can be exported (every
        controller exports the active document), so: open -> export -> close.
        With ``keep_open`` the document stays open (until ``_close_kept_open``)
        so it can be edited while the user names the package.
        """
        png = asset_file.path.with_suffix(".png")
        ext = asset_file.path.suffix.lower()
        controller = self._controller_for(ext)

        if controller is not None:
            job.set_status(JobStatus.OPENING)
            controller.open_file(asset_file.path)
            exported = False
            try:
                job.set_status(JobStatus.EXPORTING_PREVIEW)
                controller.export_preview(png)
                exported = True
            finally:
                if keep_open and exported:
                    self._kept_open = (controller, asset_file)
                else:
                    controller.close_document()
        else:
            # For other formats, try to use PIL
            try:
                from PIL import Image
                img = Image.open(asset_file.path)
                img.save(png, "PNG")
            except Exception as e:
                self.logger.warning(f"Could not generate preview for {asset_file.path}: {e}")
                return

        self._finish_preview(asset_file, job, png)

    def _finish_preview(self, asset_file: AssetFile, job, png: Path):
        """PNG -> AVIF (+ thumbnail) and remember the result."""
        job.set_status(JobStatus.CONVERTING_AVIF)
        avif_path = asset_file.path.with_suffix(".avif")
        asset_file.preview_path, asset_file.thumb_path, w, h = self.preview.convert_to_avif(
            png, avif_path
        )
        self.preview.delete_file_safe(png)
        if not job.preview_file:
            job.preview_file = asset_file.preview_path

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

        # Name it after the archive, not the internal "_extracted_<name>" folder.
        base_name = job.source_file.stem if job.is_archive else package.name
        sheet_path = package.workspace_dir / f"{base_name}_contact_sheet.png"
        self.preview.create_contact_sheet([f.path for f in images], sheet_path, cols=4)

        try:
            avif_path = sheet_path.with_suffix(".avif")
            self.preview.convert_to_avif(sheet_path, avif_path)
            self.preview.delete_file_safe(sheet_path)

            sheet_asset = AssetFile(
                path=avif_path,
                relative_path=Path(f"{base_name}_contact_sheet.avif"),
                category=FileCategory.PRESERVABLE,
                preview_path=avif_path,
                thumb_path=avif_path.with_suffix(".thumb.avif")
            )
            package.add_file(sheet_asset)
            if not job.preview_file:
                job.preview_file = avif_path
            self.logger.info(f"Contact sheet preview created: {avif_path.name}")
        except Exception as e:
            self.logger.warning(f"Failed to create contact sheet AVIF: {e}")

    # ──────────────────────────────────────────────
    # Transformation
    # ──────────────────────────────────────────────

    def _process_transformable_file(self, asset_file: AssetFile, job):
        """Process a single transformable file (hide layers, save)."""
        ext = asset_file.path.suffix.lower()
        controller = self._controller_for(ext)
        if controller is None:
            raise RuntimeError(f"Unsupported format for processing: {ext}")

        job.set_status(JobStatus.OPENING)
        controller.open_file(asset_file.path)
        try:
            job.set_status(JobStatus.HIDING_LAYERS)
            controller.hide_layers()
            job.set_status(JobStatus.SAVING)
            controller.save()
        finally:
            controller.close_document()

    # ──────────────────────────────────────────────
    # Archive creation / verification / publishing
    # ──────────────────────────────────────────────

    def _archive_dir(self, package: AssetPackage, job) -> Path:
        """Where the finished archive is published."""
        override = job.output_dir or self.output_dir
        if override:
            folder = Path(override)
            folder.mkdir(parents=True, exist_ok=True)
            return folder
        # Archive goes next to the original source (job.source_file is the original input)
        if job.is_archive and job.archive_metadata:
            return job.source_file.parent
        if package.source_type in ("directory", "file"):
            return job.source_file.parent
        return package.root_path

    def _archive_stem(self, package: AssetPackage, job) -> str:
        name = job.final_name or (job.source_file.stem if job.is_archive else package.name)
        return self.filename.normalize(str(name)) or self.filename.normalize(package.name) or "package"

    def _create_final_archive(self, package: AssetPackage, job):
        """
        Build the archive under a temporary name next to its destination.

        Nothing is published yet: verification runs on this temporary file, and only a
        verified archive is renamed to its final, collision-free name.
        """
        job.set_status(JobStatus.CREATING_ARCHIVE)
        prefs = self._prefs or load_prefs(self.config)

        archive_dir = self._archive_dir(package, job)
        stem = self._archive_stem(package, job)
        partial_base = archive_dir / f"{stem}.kaelovun-part"

        # Collect all files to archive (preserving structure). A file that is both an
        # asset and its own preview (the contact sheet) is still just one entry.
        files_to_archive: List[Path] = []
        seen = set()
        for asset_file in package.get_all_files():
            candidates = [asset_file.path]
            if asset_file.preview_path and Path(asset_file.preview_path).exists():
                candidates.append(Path(asset_file.preview_path))
            if asset_file.thumb_path and Path(asset_file.thumb_path).exists():
                candidates.append(Path(asset_file.thumb_path))
            for c in candidates:
                if c not in seen:
                    seen.add(c)
                    files_to_archive.append(c)

        rel_paths = [p.relative_to(package.root_path) for p in files_to_archive]
        expected = build_manifest(package.root_path, rel_paths,
                                  with_crc=(prefs.verify == "paranoid"), cancel=self._cancelled)

        fmt = job.archive_format or prefs.format
        self.logger.info(f"Creating {fmt} archive with {len(files_to_archive)} files")
        archive_path = self.archive.create(
            files_to_archive, partial_base, work_dir=package.root_path,
            fmt=fmt, cancel=self._cancelled)

        job.archive_file = archive_path
        package.archive_path = archive_path
        package.archive_created = True
        job.expected_manifest = expected
        job.archive_dir = archive_dir
        job.archive_stem = stem

    def _verify_archive(self, job) -> bool:
        """Verify the created archive - integrity, then content manifest."""
        if not job.archive_file or not job.archive_file.exists():
            return False
        prefs = self._prefs or load_prefs(self.config)

        if prefs.test and not self.archive.test_archive(job.archive_file, cancel=self._cancelled):
            return False

        expected = getattr(job, 'expected_manifest', None)
        if not expected:
            self.logger.warning("No expected manifest available for verification")
            return True
        if not isinstance(expected, dict):          # legacy list of names
            expected = manifest_from_paths(expected)

        try:
            entries = self.archive.list_entries(job.archive_file, cancel=self._cancelled)
        except Exception as e:
            self.logger.error(f"Could not list archive for verification: {e}")
            return False
        result = verify_entries(expected, entries, check_crc=(prefs.verify == "paranoid"))
        if not result.ok:
            self.logger.error(f"Archive manifest mismatch: {result.describe()}")
            return False

        note = f"Manifest verified: {result.checked} files match (names + sizes"
        note += ", CRC32)" if prefs.verify == "paranoid" and not result.crc_unchecked else ")"
        self.logger.info(f"  {note}")
        return True

    def _previews_to_export(self, package: AssetPackage, job):
        """(preview, thumb) of the package's representative preview, if one exists."""
        chosen = job.preview_file
        if not chosen or not Path(chosen).exists():
            return None
        thumb = None
        for a in package.get_all_files():
            if a.preview_path and Path(a.preview_path) == Path(chosen):
                thumb = a.thumb_path if a.thumb_path and Path(a.thumb_path).exists() else None
                break
        return Path(chosen), thumb

    @staticmethod
    def _copy_atomic(src: Path, dest: Path):
        """Copy to a temporary '.kaelovun-part' name, then rename: readers never see half a file."""
        tmp = dest.with_name(f"{dest.stem}.kaelovun-part{dest.suffix}")
        try:
            shutil.copy2(src, tmp)
            os.replace(tmp, dest)
        except BaseException:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise

    def _publish_archive(self, package: AssetPackage, job):
        """
        Give the verified archive its final, never-colliding name.

        The preview (and thumbnail) are saved next to it with the SAME stem, which is
        how Evoury pairs them (``name.7z`` + ``name.avif`` + ``name.thumb.avif``). They are
        written first and the archive last, so the asset only "appears" once it is complete.
        """
        prefs = self._prefs or load_prefs(self.config)
        partial = Path(job.archive_file)
        previews = self._previews_to_export(package, job) if prefs.export_previews else None

        suffixes = [partial.suffix]
        if previews:
            suffixes += [previews[0].suffix, ".thumb" + (previews[1] or previews[0]).suffix]
        stem = self.filename.unique_stem(job.archive_dir, job.archive_stem, suffixes)
        if stem != job.archive_stem:
            self.logger.info(f"'{job.archive_stem}' already exists; saving as '{stem}'")

        if previews:
            preview, thumb = previews
            try:
                self._copy_atomic(preview, job.archive_dir / f"{stem}{preview.suffix}")
                if thumb:
                    self._copy_atomic(thumb, job.archive_dir / f"{stem}.thumb{thumb.suffix}")
                job.exported_preview = job.archive_dir / f"{stem}{preview.suffix}"
            except OSError as e:
                self.logger.warning(f"Could not save the preview next to the archive: {e}")

        final = job.archive_dir / f"{stem}{partial.suffix}"
        os.replace(partial, final)
        job.archive_file = final
        package.archive_path = final
        self.logger.info(f"Archive ready: {final.name} ({human_size(final.stat().st_size)})")

    def _discard_partial(self, job):
        """Remove a half-built archive after a failure so nothing junk is left behind."""
        partial = getattr(job, "archive_file", None)
        if partial and ".kaelovun-part" in Path(partial).name:
            try:
                Path(partial).unlink()
            except OSError:
                pass
            job.archive_file = None

    def _write_sidecar_if_enabled(self, job, package: AssetPackage, prefs):
        """
        <archive>.kaelovun.json: everything inside the archive (path, size, category)
        so Evoury can show the contents instantly, for RAR too, without opening it.
        """
        if not prefs.write_sidecar or not job.archive_file:
            return
        try:
            categories = {a.relative_path.as_posix(): a.category.name.lower()
                          for a in package.get_all_files()}
            manifest = getattr(job, "expected_manifest", None) or {}
            # CRC32 of every file lets Evoury find the same file in several packages. It comes
            # from the finished archive's own listing, so it costs no extra pass over the data.
            crcs = {}
            try:
                from files.manifest import _key
                crcs = {_key(e.path): e.crc for e in self.archive.list_entries(job.archive_file)
                        if not e.is_dir and e.crc is not None}
            except Exception as e:
                self.logger.warning(f"Could not read CRC32 values for the sidecar: {e}")
            files = []
            for key, entry in sorted(manifest.items()):
                item = {"path": entry.path, "size": entry.size}
                if key in categories:
                    item["category"] = categories[key]
                crc = entry.crc if entry.crc is not None else crcs.get(key)
                if crc is not None:
                    item["crc32"] = f"{crc:08X}"
                files.append(item)
            exported = job.exported_preview
            write_sidecar(job.archive_file, {
                "name": job.final_name,
                "format": Path(job.archive_file).suffix.lstrip("."),
                "source": {"name": job.source_file.name,
                           "type": "archive" if job.is_archive else package.source_type},
                "preview": Path(exported).name if exported else None,
                "settings": {"level": prefs.level, "solid": prefs.solid, "dict_mb": prefs.dict_mb},
                "files": files,
            })
        except Exception as e:
            self.logger.warning(f"Could not write sidecar: {e}")

    def _build_report(self, job, package: AssetPackage, source_bytes: int, seconds: float) -> dict:
        files = package.get_all_files()
        problems = [f"{a.relative_path.as_posix()}: {a.error}" for a in files
                    if getattr(a, "error", None)]
        archive = Path(job.archive_file)
        return {
            "name": job.final_name or archive.stem,
            "source": str(job.source_file),
            "archive": str(archive),
            "format": archive.suffix.lstrip("."),
            "source_bytes": source_bytes,
            "archive_bytes": archive.stat().st_size,
            "transformed": len(package.get_transformable_files()),
            "files": len(files),
            "seconds": round(seconds, 1),
            "retries": job.retry_count,
            "warnings": problems,
        }

    def _cleanup_workspace(self, package: AssetPackage, job):
        """Clean up workspace files after successful verification."""
        if job.is_archive:
            self.extractor.cleanup_all()
        elif package.workspace_dir and package.workspace_dir != package.root_path:
            # For directory and file inputs, the workspace is a copy in _workspace_root
            # Clean up the entire workspace root (which contains the copied package)
            if not self.keep_workspace:
                self._cleanup_workspace_root()

        # For directory/file inputs, the original files are NOT deleted
        # Only the loose files in workspace are cleaned up
        # The original source remains untouched per preservation philosophy

    # ──────────────────────────────────────────────
    # Progress and summary
    # ──────────────────────────────────────────────

    def set_queue_size(self, size: int):
        self._total_packages = size
        self._processed = 0
        self._failed = 0
        self.reports = []

    def get_summary(self) -> str:
        text = (
            f"Queue complete. "
            f"Total: {self._total_packages}, "
            f"Success: {self._processed}, "
            f"Failed: {self._failed}"
        )
        if self.reports:
            src = sum(r["source_bytes"] for r in self.reports)
            out = sum(r["archive_bytes"] for r in self.reports)
            warn = sum(len(r["warnings"]) for r in self.reports)
            text += f" | {human_size(src)} -> {human_size(out)}"
            if warn:
                text += f" | {warn} file(s) had problems (see log)"
        return text

    def _use_affinity(self, ext: str) -> bool:
        """Native Affinity files always use Affinity. PSD, AI and EPS follow
        ENGINE: with 'affinity' they open in Affinity instead of Photoshop
        or Illustrator."""
        if ext in (".afphoto", ".afdesign", ".afpub"):
            return True
        if ext in (".psd", ".ai", ".eps"):
            return getattr(self.config, "ENGINE", "adobe") == "affinity"
        return False

    def _require_affinity(self):
        if not self.affinity:
            raise RuntimeError(
                "Job needs Affinity but no Affinity controller is wired. "
                "Set ENGINE to 'adobe' or check the Affinity setup."
            )
        return self.affinity

    def handle_error(self, job, error) -> bool:
        """
        Log an error. Returns True when the job should be retried (recoverable
        Adobe/COM error with retries left); otherwise marks the job failed.
        """
        self.logger.error(f"{job.source_file.name}: {error}")
        max_retries = getattr(self.config, "MAX_RETRIES", 2)
        if self.recovery.is_recoverable(error) and job.can_retry(max_retries):
            job.increase_retry()
            job.error_message = str(error)
            self.logger.warning("Recoverable error detected. Restarting.")
            self.recovery.wait_ready()
            return True
        job.fail(error)
        return False
