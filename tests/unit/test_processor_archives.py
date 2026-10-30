"""Processor behaviour that protects data: preview order, naming, publish, retry."""

import sys
import threading
import time
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from conftest import FakeConfig, RecordingLogger, needs_7z  # noqa: E402

from files.archive import ArchiveManager
from pipeline.asset_package import AssetFile, FileCategory
from pipeline.job import Job, JobStatus
from pipeline.processor import AssetProcessor


def make_processor(tmp_path, **overrides):
    cfg = FakeConfig(tmp_path, **overrides)
    cfg.ADOBE_RECOVERY_WAIT = 0
    logger = RecordingLogger()
    storage = MagicMock()
    storage.require_space.return_value = True
    p = AssetProcessor(cfg, logger, MagicMock(), ArchiveManager(cfg, logger),
                       MagicMock(), MagicMock(), storage, indesign=MagicMock(), affinity=MagicMock())
    p.state_manager = MagicMock()
    return p


def make_project(tmp_path, name="project"):
    d = tmp_path / name
    (d / "sub").mkdir(parents=True)
    (d / "readme.txt").write_text("hello " * 2000)
    (d / "sub" / "data.bin").write_bytes(b"\x01" * 5000)
    return d


def snapshot(folder: Path):
    return {p.name: p.read_bytes() for p in folder.rglob("*") if p.is_file()}


# ── preview / naming order ───────────────────────────────────

class TestPreviewOrder:
    def test_document_is_opened_before_preview_export_then_closed(self, tmp_path):
        p = make_processor(tmp_path)
        calls = []
        p.photoshop.open_file.side_effect = lambda f: calls.append("open")
        p.photoshop.export_preview.side_effect = lambda f: calls.append("export")
        p.photoshop.close_document.side_effect = lambda: calls.append("close")
        p.preview.convert_to_avif.return_value = (Path("a.avif"), Path("a.thumb.avif"), 1, 1)
        psd = tmp_path / "x.psd"
        psd.write_text("psd")
        asset = AssetFile(psd, Path("x.psd"), FileCategory.TRANSFORMABLE, "photoshop")
        p._generate_preview_for_file(asset, Job(psd))
        assert calls == ["open", "export", "close"]

    def test_document_is_closed_even_if_export_fails(self, tmp_path):
        p = make_processor(tmp_path)
        p.photoshop.export_preview.side_effect = RuntimeError("no active document")
        psd = tmp_path / "x.psd"
        psd.write_text("psd")
        asset = AssetFile(psd, Path("x.psd"), FileCategory.TRANSFORMABLE, "photoshop")
        with pytest.raises(RuntimeError):
            p._generate_preview_for_file(asset, Job(psd))
        p.photoshop.close_document.assert_called_once()


class TestEditBeforeRegen:
    """The README promise: edit the open document, press Regen Preview, then name."""

    def test_representative_document_stays_open_through_naming_then_closes(self, tmp_path):
        p = make_processor(tmp_path)
        p.naming_backend, p.config.NAMING_MODE = "gui", "manual"
        events = []
        ps = p.photoshop
        ps.open_file.side_effect = lambda f: events.append(f"open:{Path(f).name}")
        ps.export_preview.side_effect = lambda f: events.append("export")
        ps.close_document.side_effect = lambda: events.append("close")
        ps.hide_layers.side_effect = lambda: events.append("hide")
        ps.save.side_effect = lambda: events.append("save")
        p.preview.convert_to_avif.side_effect = lambda png, avif: (avif, avif, 1, 1)
        files = []
        for n in ("a.psd", "b.psd"):
            f = tmp_path / n
            f.write_text("x")
            (tmp_path / n.replace(".psd", ".avif")).write_bytes(b"avif")
            files.append(AssetFile(f, Path(n), FileCategory.TRANSFORMABLE, "photoshop"))
        pkg = MagicMock()
        pkg.get_transformable_files.return_value = files
        pkg.name = "pkg"

        def user():
            for _ in range(200):
                if p.name_request.preview:
                    break
                time.sleep(0.02)
            events.append("user-sees-prompt")
            p.name_request.request_regenerate()
            for _ in range(200):
                if p.name_request.preview_version >= 1:
                    break
                time.sleep(0.02)
            p.name_request.submit("named")

        threading.Thread(target=user, daemon=True).start()
        job = Job(files[0].path)
        p._process_package(pkg, job)
        # b is previewed and closed first; a (the representative) stays open for the prompt,
        # is re-exported in place on Regen, and only then closed and processed.
        assert events[:4] == ["open:b.psd", "export", "close", "open:a.psd"]
        i = events.index("user-sees-prompt")
        assert events[i - 1] == "export" and "close" not in events[4:i]
        assert events[i + 1] == "export"                         # regen: no re-open
        assert events[i + 2] == "close"                          # closed before processing
        assert events[i + 3:i + 6] == ["open:a.psd", "hide", "save"]
        assert job.final_name == "named"

    def test_document_is_closed_even_if_naming_fails(self, tmp_path):
        p = make_processor(tmp_path)
        p.naming_backend, p.config.NAMING_MODE = "gui", "manual"
        p.preview.convert_to_avif.side_effect = lambda png, avif: (avif, avif, 1, 1)
        f = tmp_path / "a.psd"
        f.write_text("x")
        a = AssetFile(f, Path("a.psd"), FileCategory.TRANSFORMABLE, "photoshop")
        pkg = MagicMock()
        pkg.get_transformable_files.return_value = [a]
        pkg.name = "pkg"
        calls = {"n": 0}

        def stop_after_first_check():
            calls["n"] += 1
            return calls["n"] < 2
        p.should_continue = stop_after_first_check
        with pytest.raises(RuntimeError):
            p._process_package(pkg, Job(f))
        assert p._kept_open is None
        p.photoshop.close_document.assert_called()


class TestGuiNaming:
    def make_asset(self, tmp_path):
        psd = tmp_path / "poster.psd"
        psd.write_text("psd")
        prev = tmp_path / "poster.avif"
        prev.write_bytes(b"avif")
        a = AssetFile(psd, Path("poster.psd"), FileCategory.TRANSFORMABLE, "photoshop", preview_path=prev)
        pkg = MagicMock()
        pkg.get_transformable_files.return_value = [a]
        pkg.name = "pkg"
        return a, pkg

    def run_prompt(self, p, job, pkg, responder):
        p.naming_backend = "gui"
        p.config.NAMING_MODE = "manual"
        t = threading.Thread(target=responder, daemon=True)
        t.start()
        p._request_package_name(job, pkg)
        t.join(2)

    def test_prompt_shows_preview_and_default_then_uses_typed_name(self, tmp_path):
        p = make_processor(tmp_path)
        a, pkg = self.make_asset(tmp_path)
        seen = {}

        def responder():
            for _ in range(100):
                if p.name_request.preview:
                    break
                time.sleep(0.02)
            seen["preview"] = p.name_request.preview
            seen["default"] = p.name_request.default_name
            p.name_request.submit("My: Cool/Poster")

        job = Job(a.path)
        self.run_prompt(p, job, pkg, responder)
        assert seen["preview"] == a.preview_path and seen["default"] == "poster"
        assert job.final_name == "My CoolPoster"           # illegal characters stripped
        assert p.name_request.preview is None              # no stale prompt left behind

    def test_regenerate_re_exports_preview_then_waits_again(self, tmp_path):
        p = make_processor(tmp_path)
        a, pkg = self.make_asset(tmp_path)
        p.preview.convert_to_avif.return_value = (a.preview_path, None, 1, 1)

        def responder():
            for _ in range(100):
                if p.name_request.preview:
                    break
                time.sleep(0.02)
            p.name_request.request_regenerate()
            for _ in range(200):
                if p.name_request.preview_version >= 1:
                    break
                time.sleep(0.02)
            p.name_request.submit("final")

        job = Job(a.path)
        self.run_prompt(p, job, pkg, responder)
        assert job.final_name == "final"
        p.photoshop.export_preview.assert_called_once()

    def test_blank_name_falls_back_to_default(self, tmp_path):
        p = make_processor(tmp_path)
        a, pkg = self.make_asset(tmp_path)

        def responder():
            for _ in range(100):
                if p.name_request.preview:
                    break
                time.sleep(0.02)
            p.name_request.submit("   ")

        job = Job(a.path)
        self.run_prompt(p, job, pkg, responder)
        assert job.final_name == "poster"

    def test_stopping_the_queue_unblocks_the_prompt(self, tmp_path):
        p = make_processor(tmp_path)
        a, pkg = self.make_asset(tmp_path)
        p.naming_backend, p.config.NAMING_MODE = "gui", "manual"
        p.should_continue = lambda: False
        with pytest.raises(RuntimeError, match="stopped"):
            p._request_package_name(Job(a.path), pkg)


# ── publishing ───────────────────────────────────────────────

@needs_7z
class TestPublish:
    def test_folder_becomes_verified_archive_next_to_source_and_source_is_untouched(self, tmp_path):
        p = make_processor(tmp_path, format="7z")
        src = make_project(tmp_path)
        before = snapshot(src)
        job = Job(src)
        p.process(job)
        assert job.status == JobStatus.DONE, job.error_message
        assert job.archive_file == tmp_path / "project.7z"
        assert snapshot(src) == before
        assert not list(tmp_path.glob("*.kaelovun-part*"))
        assert p.reports[0]["format"] == "7z" and p.get_summary().startswith("Queue complete.")

    def test_existing_archive_is_never_overwritten_or_appended_to(self, tmp_path):
        p = make_processor(tmp_path, format="7z")
        src = make_project(tmp_path)
        (tmp_path / "project.7z").write_bytes(b"precious")
        job = Job(src)
        p.process(job)
        assert job.archive_file.name == "project (2).7z"
        assert (tmp_path / "project.7z").read_bytes() == b"precious"

    def test_archive_job_never_writes_over_its_own_source(self, tmp_path):
        """Regression: pack.zip -> pack.zip meant 'update the original archive in place'."""
        p = make_processor(tmp_path, format="zip")
        src = tmp_path / "pack.zip"
        with zipfile.ZipFile(src, "w") as zf:
            zf.writestr("a.txt", "hello " * 1000)
        original = src.read_bytes()
        job = Job(src)
        job.is_archive = True
        job.archive_metadata = {"x": 1}
        p.process(job)
        assert job.status == JobStatus.DONE, job.error_message
        assert src.read_bytes() == original
        assert job.archive_file.name == "pack (2).zip"

    def test_contact_sheet_duplicate_entries_do_not_fail_verification(self, tmp_path):
        """Regression: a file that is both an asset and its own preview was counted twice."""
        p = make_processor(tmp_path, format="7z")
        root = make_project(tmp_path)
        sheet = root / "sheet.avif"
        sheet.write_bytes(b"avif")
        asset = AssetFile(sheet, Path("sheet.avif"), FileCategory.PRESERVABLE,
                          preview_path=sheet, thumb_path=root / "sheet.thumb.avif")
        (root / "sheet.thumb.avif").write_bytes(b"t")
        pkg = MagicMock()
        pkg.root_path, pkg.name, pkg.source_type = root, "project", "directory"
        pkg.get_all_files.return_value = [asset]
        job = Job(root)
        job.final_name = "dup"
        p._prefs = __import__("files.archive_prefs", fromlist=["load_prefs"]).load_prefs(p.config)
        p._create_final_archive(pkg, job)
        assert p._verify_archive(job) is True
        p._publish_archive(pkg, job)
        names = {e.path for e in p.archive.list_entries(job.archive_file)}
        assert names == {"sheet.avif", "sheet.thumb.avif"}

    def test_failed_verification_leaves_no_archive_behind(self, tmp_path):
        p = make_processor(tmp_path, format="7z")
        src = make_project(tmp_path)
        p._verify_archive = lambda job: False
        job = Job(src)
        p.process(job)
        assert job.status == JobStatus.FAILED
        assert not list(tmp_path.glob("*.7z")) and not list(tmp_path.glob("*part*"))
        assert p._failed == 1

    def test_output_dir_option(self, tmp_path):
        p = make_processor(tmp_path, format="7z")
        p.output_dir = tmp_path / "out"
        job = Job(make_project(tmp_path))
        p.process(job)
        assert job.archive_file.parent == tmp_path / "out"

    def test_sidecar_written_when_enabled(self, tmp_path):
        p = make_processor(tmp_path, format="7z", write_sidecar=True)
        src = make_project(tmp_path)
        job = Job(src)
        p.process(job)
        side = Path(str(job.archive_file) + ".kaelovun.json")
        assert side.exists()
        import json
        data = json.loads(side.read_text(encoding="utf-8"))
        assert data["archive"] == job.archive_file.name and data["tool"] == "Kaelovun"
        # Evoury lists these without opening the archive, so every entry needs a size
        sizes = {f["path"]: f["size"] for f in data["files"]}
        assert sizes == {"readme.txt": (src / "readme.txt").stat().st_size,
                         "sub/data.bin": 5000}
        assert data["archive_bytes"] == job.archive_file.stat().st_size
        # CRC32 per file (from the archive's own listing) so Evoury can spot a file that is in
        # several packages without opening any of them
        import zlib
        expected = {"readme.txt": zlib.crc32((src / "readme.txt").read_bytes()),
                    "sub/data.bin": zlib.crc32(b"\x01" * 5000)}
        assert {f["path"]: int(f["crc32"], 16) for f in data["files"]} == expected


# ── errors / retry ───────────────────────────────────────────

class TestRetry:
    def test_recoverable_error_retries_once_and_counts_success_not_failure(self, tmp_path):
        p = make_processor(tmp_path)
        attempts = []

        def flaky(job):
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("General Photoshop error occurred")
            job.set_status(JobStatus.DONE)
            p._processed += 1

        p._process_once = flaky
        job = Job(tmp_path / "x.psd")
        p.process(job)
        assert len(attempts) == 2 and job.retry_count == 1
        assert p._failed == 0 and p._processed == 1

    def test_retries_are_bounded(self, tmp_path):
        p = make_processor(tmp_path)
        p._process_once = MagicMock(side_effect=RuntimeError("scratch disk is full"))
        job = Job(tmp_path / "x.psd")
        p.process(job)
        assert p._process_once.call_count == p.config.MAX_RETRIES + 1
        assert p._failed == 1 and job.status == JobStatus.FAILED

    def test_gui_progress_attribute_exists(self, tmp_path):
        p = make_processor(tmp_path)
        p.set_queue_size(7)
        assert p._total_assets == 7 == p._total_packages


# ── previews next to the archive (the Evoury contract) ───────

@needs_7z
class TestPreviewExport:
    def build(self, tmp_path, **cfg):
        p = make_processor(tmp_path, format="7z", **cfg)
        root = make_project(tmp_path)
        prev, thumb = root / "poster.avif", root / "poster.thumb.avif"
        prev.write_bytes(b"avif-bytes")
        thumb.write_bytes(b"thumb-bytes")
        asset = AssetFile(root / "poster.psd", Path("poster.psd"), FileCategory.TRANSFORMABLE,
                          preview_path=prev, thumb_path=thumb)
        (root / "poster.psd").write_text("psd")
        pkg = MagicMock()
        pkg.root_path, pkg.name, pkg.source_type = root, "project", "directory"
        pkg.get_all_files.return_value = [asset]
        job = Job(root)
        job.final_name = "Poster Pack"
        job.preview_file = prev
        p._prefs = __import__("files.archive_prefs", fromlist=["load_prefs"]).load_prefs(p.config)
        p._create_final_archive(pkg, job)
        assert p._verify_archive(job)
        return p, pkg, job

    def test_archive_preview_and_thumbnail_share_one_stem(self, tmp_path):
        p, pkg, job = self.build(tmp_path)
        p._publish_archive(pkg, job)
        names = sorted(f.name for f in tmp_path.iterdir() if f.is_file())
        assert names == ["Poster Pack.7z", "Poster Pack.avif", "Poster Pack.thumb.avif"]
        assert (tmp_path / "Poster Pack.avif").read_bytes() == b"avif-bytes"
        assert (tmp_path / "Poster Pack.thumb.avif").read_bytes() == b"thumb-bytes"

    def test_a_leftover_preview_moves_all_three_to_the_next_free_stem(self, tmp_path):
        (tmp_path / "Poster Pack.avif").write_bytes(b"someone else's file")
        p, pkg, job = self.build(tmp_path)
        p._publish_archive(pkg, job)
        assert (tmp_path / "Poster Pack.avif").read_bytes() == b"someone else's file"
        assert job.archive_file.name == "Poster Pack (2).7z"
        assert (tmp_path / "Poster Pack (2).avif").exists()
        assert (tmp_path / "Poster Pack (2).thumb.avif").exists()

    def test_can_be_turned_off(self, tmp_path):
        p, pkg, job = self.build(tmp_path, export_previews=False)
        p._publish_archive(pkg, job)
        assert sorted(f.name for f in tmp_path.iterdir() if f.is_file()) == ["Poster Pack.7z"]

    def test_no_temporary_files_are_left_behind(self, tmp_path):
        p, pkg, job = self.build(tmp_path)
        p._publish_archive(pkg, job)
        assert not list(tmp_path.glob("*kaelovun-part*"))
