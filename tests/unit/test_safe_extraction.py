"""Archive security boundaries: traversal, bombs, links, encryption, nesting."""

import io
import os
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from conftest import FakeConfig, RecordingLogger, needs_7z  # noqa: E402

from files.archive_backends import PasswordRequired
from files.archive_extraction import (
    ArchiveExtractor, ArchiveSecurityError, _ByteGuard, unsafe_reason,
)
from files.archive_prefs import load_prefs


def make_extractor(tmp_path, **overrides):
    cfg = FakeConfig(tmp_path, **overrides)
    return ArchiveExtractor(cfg, RecordingLogger()), cfg


def zip_with(path, entries):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries:
            zf.writestr(name, data)
    return path


class TestUnsafeNames:
    @pytest.mark.parametrize("name", [
        "../evil.txt", "a/../../evil.txt", "..\\evil.txt", "/etc/passwd",
        "C:/Windows/x.dll", "c:\\x", "a/b/../../../x",
    ])
    def test_rejected(self, name):
        assert unsafe_reason(name)

    @pytest.mark.parametrize("name", ["a.txt", "dir/sub/file name.psd", "ünï/فایل.psd", "..hidden", "a..b/c"])
    def test_allowed(self, name):
        assert unsafe_reason(name) is None


class TestZipSecurity:
    def test_zip_slip_is_refused_and_nothing_escapes(self, tmp_path):
        ex, _ = make_extractor(tmp_path)
        z = zip_with(tmp_path / "evil.zip", [("../escaped.txt", "x"), ("ok.txt", "y")])
        dest = tmp_path / "out" / "inner"
        with pytest.raises(ArchiveSecurityError):
            ex.extract_single(z, dest)
        assert not (tmp_path / "out" / "escaped.txt").exists()
        assert not (tmp_path / "escaped.txt").exists()

    def test_absolute_path_refused(self, tmp_path):
        ex, _ = make_extractor(tmp_path)
        z = zip_with(tmp_path / "abs.zip", [("/tmp/abs_escape.txt", "x")])
        with pytest.raises(ArchiveSecurityError):
            ex.extract_single(z, tmp_path / "o")

    def test_ratio_bomb_refused_before_writing(self, tmp_path):
        ex, _ = make_extractor(tmp_path, max_ratio=50, ratio_floor_mb=1)
        z = zip_with(tmp_path / "bomb.zip", [("zeros.bin", b"\0" * (30 * 1024 * 1024))])
        dest = tmp_path / "o"
        with pytest.raises(ArchiveSecurityError, match="bomb|ratio"):
            ex.extract_single(z, dest)
        assert not any(dest.rglob("*")) if dest.exists() else True

    def test_size_limit(self, tmp_path):
        ex, _ = make_extractor(tmp_path, max_extract_gb=0.001, max_ratio=100000)
        z = zip_with(tmp_path / "big.zip", [("a.bin", os.urandom(2 * 1024 * 1024))])
        with pytest.raises(ArchiveSecurityError, match="limit"):
            ex.extract_single(z, tmp_path / "o")

    def test_entry_count_limit(self, tmp_path):
        ex, _ = make_extractor(tmp_path, max_files=5)
        z = zip_with(tmp_path / "many.zip", [(f"f{i}.txt", "x") for i in range(20)])
        with pytest.raises(ArchiveSecurityError, match="entries"):
            ex.extract_single(z, tmp_path / "o")

    def test_byte_guard_catches_lying_headers(self, tmp_path):
        prefs = load_prefs(FakeConfig(tmp_path, max_ratio=10, ratio_floor_mb=1))
        guard = _ByteGuard(prefs, archive_bytes=1000, name="x.zip")
        guard.add(500_000)
        with pytest.raises(ArchiveSecurityError):
            guard.add(2_000_000)

    def test_timestamps_are_restored(self, tmp_path):
        ex, _ = make_extractor(tmp_path)
        with zipfile.ZipFile(tmp_path / "t.zip", "w") as zf:
            zf.writestr(zipfile.ZipInfo("old.txt", date_time=(2015, 6, 15, 12, 0, 0)), "x")
        ex.extract_single(tmp_path / "t.zip", tmp_path / "o")
        year = time.localtime((tmp_path / "o" / "old.txt").stat().st_mtime).tm_year
        assert year == 2015

    def test_zip_symlink_entries_are_skipped(self, tmp_path):
        ex, _ = make_extractor(tmp_path)
        with zipfile.ZipFile(tmp_path / "l.zip", "w") as zf:
            info = zipfile.ZipInfo("link")
            info.external_attr = (0o120777 << 16)
            zf.writestr(info, "/etc/passwd")
            zf.writestr("real.txt", "ok")
        files = ex.extract_single(tmp_path / "l.zip", tmp_path / "o")
        assert [f.name for f in files] == ["real.txt"]
        assert not (tmp_path / "o" / "link").exists()

    def test_encrypted_zip_needs_password(self, tmp_path):
        ex, _ = make_extractor(tmp_path)
        z = tmp_path / "e.zip"
        zip_with(z, [("a.txt", "x")])
        data = bytearray(z.read_bytes())
        # Set the "encrypted" general-purpose flag in both headers.
        for sig in (b"PK\x03\x04", b"PK\x01\x02"):
            i = data.find(sig)
            off = i + (6 if sig == b"PK\x03\x04" else 8)
            data[off] |= 1
        z.write_bytes(bytes(data))
        with pytest.raises(PasswordRequired):
            ex.extract_single(z, tmp_path / "o")


class TestTarSecurity:
    def test_traversal_refused(self, tmp_path):
        ex, _ = make_extractor(tmp_path)
        t = tmp_path / "evil.tar"
        with tarfile.open(t, "w") as tf:
            info = tarfile.TarInfo("../escaped.txt")
            info.size = 1
            tf.addfile(info, io.BytesIO(b"x"))
        with pytest.raises(ArchiveSecurityError):
            ex.extract_single(t, tmp_path / "o")
        assert not (tmp_path / "escaped.txt").exists()

    def test_links_and_devices_skipped_files_kept(self, tmp_path):
        ex, _ = make_extractor(tmp_path)
        t = tmp_path / "l.tar.gz"
        with tarfile.open(t, "w:gz") as tf:
            sym = tarfile.TarInfo("link")
            sym.type, sym.linkname = tarfile.SYMTYPE, "/etc/passwd"
            tf.addfile(sym)
            info = tarfile.TarInfo("real.txt")
            info.size = 2
            tf.addfile(info, io.BytesIO(b"ok"))
        files = ex.extract_single(t, tmp_path / "o")
        assert [f.name for f in files] == ["real.txt"]


@needs_7z
class TestSevenZipSecurity:
    def test_symlink_in_7z_is_not_extracted(self, tmp_path):
        ex, _ = make_extractor(tmp_path)
        src = tmp_path / "src"
        src.mkdir()
        (src / "real.txt").write_text("ok")
        os.symlink("/etc/passwd", src / "evil_link")
        arc = tmp_path / "l.7z"
        subprocess.run(["7z", "a", "-snl", str(arc), "*"], cwd=src, check=True, capture_output=True)
        files = ex.extract_single(arc, tmp_path / "o")
        assert not (tmp_path / "o" / "evil_link").exists()
        assert (tmp_path / "o" / "real.txt").read_text() == "ok"
        assert [f.name for f in files] == ["real.txt"]

    def test_encrypted_7z(self, tmp_path):
        ex, _ = make_extractor(tmp_path)
        src = tmp_path / "src"
        src.mkdir()
        (src / "secret.txt").write_text("classified")
        arc = tmp_path / "e.7z"
        subprocess.run(["7z", "a", "-psecret", "-mhe=on", str(arc), "*"], cwd=src,
                       check=True, capture_output=True)
        with pytest.raises(PasswordRequired):
            ex.extract_single(arc, tmp_path / "o1")
        files = ex.extract_single(arc, tmp_path / "o2", password="secret")
        assert files[0].read_text() == "classified"
        with pytest.raises(PasswordRequired):
            ex.extract_single(arc, tmp_path / "o3", password="wrong")

    def test_7z_bomb_refused(self, tmp_path):
        ex, _ = make_extractor(tmp_path, max_ratio=50, ratio_floor_mb=1)
        src = tmp_path / "src"
        src.mkdir()
        (src / "zeros.bin").write_bytes(b"\0" * (40 * 1024 * 1024))
        arc = tmp_path / "b.7z"
        subprocess.run(["7z", "a", str(arc), "*"], cwd=src, check=True, capture_output=True)
        with pytest.raises(ArchiveSecurityError):
            ex.extract_single(arc, tmp_path / "o")


class TestSweepAndNesting:
    def test_sweep_removes_everything_when_a_link_is_found(self, tmp_path):
        ex, _ = make_extractor(tmp_path)
        dest = tmp_path / "d"
        dest.mkdir()
        (dest / "a.txt").write_text("x")
        os.symlink("/etc", dest / "sneaky")
        with pytest.raises(ArchiveSecurityError):
            ex._sweep(dest, "x.zip")
        assert not dest.exists()

    def test_nested_archive_beyond_depth_is_preserved_not_deleted(self, tmp_path):
        """Regression: the depth-limited archive used to be unlinked, then archived while missing."""
        ex, _ = make_extractor(tmp_path)
        inner3 = zip_with(tmp_path / "inner3.zip", [("deep.txt", "deep")])
        inner2 = zip_with(tmp_path / "inner2.zip", [("inner3.zip", inner3.read_bytes()), ("two.txt", "2")])
        outer = zip_with(tmp_path / "outer.zip", [("inner2.zip", inner2.read_bytes()), ("one.txt", "1")])
        root, files = ex.extract(outer, tmp_path / "ws")
        names = sorted(f.name for f in files)
        assert "inner3.zip" in names                       # kept, still a zip
        assert all(f.exists() for f in files)              # nothing in the list is missing
        assert "inner2.zip" not in names                   # fully extracted
        assert {"one.txt", "two.txt"} <= set(names)

    def test_same_stem_archives_do_not_merge(self, tmp_path):
        ex, _ = make_extractor(tmp_path)
        a = zip_with(tmp_path / "pack.zip", [("x.txt", "from zip")])
        outer = zip_with(tmp_path / "o.zip", [("pack.zip", a.read_bytes())])
        root, files = ex.extract(outer, tmp_path / "ws")
        assert files
