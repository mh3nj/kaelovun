"""Archive conversion: correctness, safety, and what happens when things go wrong."""

import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from conftest import FakeConfig, RecordingLogger, needs_7z  # noqa: E402

from files.archive import ArchiveManager
from pipeline.convert import (
    ArchiveConverter, ConvertOptions, archive_stem, find_volumes, is_convertible,
)

pytestmark = needs_7z


def build_zip(path: Path, big=True):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("a b.txt", "hello " * (50000 if big else 1))
        zf.writestr("sub/پرونده.txt", "x" * (100000 if big else 1))
        zf.writestr("empty/", "")
    return path


@pytest.fixture
def conv(tmp_path):
    cfg = FakeConfig(tmp_path)
    return ArchiveConverter(cfg, RecordingLogger()), cfg


def entry_names(cfg, path):
    mgr = ArchiveManager(cfg, RecordingLogger())
    return {e.path: e.size for e in mgr.list_entries(path) if not e.is_dir}


def test_zip_to_7z_preserves_every_file_and_leaves_original(conv, tmp_path):
    c, cfg = conv
    src = build_zip(tmp_path / "pack.zip")
    before = src.read_bytes()
    r = c.convert(src, ConvertOptions(target="7z"))
    assert r.status == "converted", r.reason
    assert r.output == tmp_path / "pack.7z"
    assert src.read_bytes() == before
    assert entry_names(cfg, r.output) == entry_names(cfg, src)
    assert r.out_bytes < r.src_bytes and r.saved_pct > 90


def test_never_overwrites_an_existing_file(conv, tmp_path):
    c, _ = conv
    src = build_zip(tmp_path / "pack.zip")
    (tmp_path / "pack.7z").write_bytes(b"precious")
    r = c.convert(src, ConvertOptions(target="7z"))
    assert r.output.name == "pack (2).7z"
    assert (tmp_path / "pack.7z").read_bytes() == b"precious"


def test_preview_sidecars_are_copied_next_to_the_result(conv, tmp_path):
    c, _ = conv
    src = build_zip(tmp_path / "pack.zip")
    (tmp_path / "pack.avif").write_bytes(b"PREVIEW")
    (tmp_path / "pack.thumb.avif").write_bytes(b"THUMB")
    out = tmp_path / "out"
    out.mkdir()
    r = c.convert(src, ConvertOptions(target="7z", output_dir=out))
    assert r.status == "converted"
    assert r.output == out / "pack.7z"
    assert (out / "pack.avif").read_bytes() == b"PREVIEW"
    assert (out / "pack.thumb.avif").read_bytes() == b"THUMB"
    assert (tmp_path / "pack.avif").read_bytes() == b"PREVIEW"


def test_preview_sidecars_follow_the_unique_result_name(conv, tmp_path):
    c, _ = conv
    src = build_zip(tmp_path / "pack.zip")
    (tmp_path / "pack.7z").write_bytes(b"precious")
    (tmp_path / "pack.avif").write_bytes(b"OLD-PREVIEW")
    (tmp_path / "pack.thumb.avif").write_bytes(b"OLD-THUMB")
    r = c.convert(src, ConvertOptions(target="7z"))
    assert r.output.name == "pack (2).7z"
    assert (tmp_path / "pack (2).avif").read_bytes() == b"OLD-PREVIEW"
    assert (tmp_path / "pack (2).thumb.avif").read_bytes() == b"OLD-THUMB"
    assert (tmp_path / "pack.avif").read_bytes() == b"OLD-PREVIEW"


def test_preview_sidecar_copy_never_overwrites(conv, tmp_path):
    c, _ = conv
    src = build_zip(tmp_path / "pack.zip")
    (tmp_path / "pack.avif").write_bytes(b"SOURCE-PREVIEW")
    (tmp_path / "pack.7z").write_bytes(b"precious")
    (tmp_path / "pack (2).avif").write_bytes(b"KEEP-ME")
    r = c.convert(src, ConvertOptions(target="7z"))
    assert r.output.name == "pack (2).7z"
    assert (tmp_path / "pack (2).avif").read_bytes() == b"KEEP-ME"


def test_same_format_never_targets_the_source_itself(conv, tmp_path):
    c, _ = conv
    src = build_zip(tmp_path / "pack.zip")
    before = src.read_bytes()
    r = c.convert(src, ConvertOptions(target="zip", only_if_smaller=False))
    assert r.output != src and src.read_bytes() == before


def test_not_smaller_is_skipped_and_cleaned_up(conv, tmp_path):
    c, _ = conv
    src = tmp_path / "tiny.zip"
    with zipfile.ZipFile(src, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("a.txt", "x")
    r = c.convert(src, ConvertOptions(target="7z"))
    assert r.status == "skipped" and "smaller" in r.reason
    assert sorted(p.name for p in tmp_path.iterdir() if p.name != "ws") == ["tiny.zip"]
    forced = c.convert(src, ConvertOptions(target="7z", only_if_smaller=False))
    assert forced.status == "converted"


def test_dry_run_changes_nothing(conv, tmp_path):
    c, _ = conv
    src = build_zip(tmp_path / "pack.zip")
    r = c.convert(src, ConvertOptions(target="7z", dry_run=True))
    assert r.status == "dry-run" and "2 file" in r.reason
    assert sorted(p.name for p in tmp_path.iterdir() if p.name != "ws") == ["pack.zip"]


def test_verification_failure_discards_result_and_keeps_original(conv, tmp_path):
    c, _ = conv
    src = build_zip(tmp_path / "pack.zip")
    real = ArchiveManager.list_entries

    def lossy(self, archive, *a, **k):
        entries = real(self, archive, *a, **k)
        return [e for e in entries if not e.path.endswith("a b.txt")] if ".kaelovun-part" in str(archive) else entries

    with patch.object(ArchiveManager, "list_entries", lossy):
        r = c.convert(src, ConvertOptions(target="7z"))
    assert r.status == "failed" and "missing" in r.reason
    assert sorted(p.name for p in tmp_path.iterdir() if p.name != "ws") == ["pack.zip"]


def test_crash_during_compression_leaves_no_partial_file(conv, tmp_path):
    c, _ = conv
    src = build_zip(tmp_path / "pack.zip")

    def boom(self, root, output_base, **kw):
        Path(str(output_base) + ".7z").write_bytes(b"half written")
        raise RuntimeError("disk exploded")

    with patch.object(ArchiveManager, "create_tree", boom):
        r = c.convert(src, ConvertOptions(target="7z"))
    assert r.status == "failed" and "disk exploded" in r.reason
    assert sorted(p.name for p in tmp_path.iterdir() if p.name != "ws") == ["pack.zip"]


def test_unsafe_archive_is_refused(conv, tmp_path):
    c, _ = conv
    src = tmp_path / "evil.zip"
    with zipfile.ZipFile(src, "w") as zf:
        zf.writestr("../escape.txt", "x")
    r = c.convert(src, ConvertOptions(target="7z", only_if_smaller=False))
    assert r.status == "failed" and "safety" in r.reason
    assert not (tmp_path.parent / "escape.txt").exists()


def test_nested_archives_are_copied_not_unpacked(conv, tmp_path):
    c, cfg = conv
    inner = build_zip(tmp_path / "inner_src.zip", big=False)
    outer = tmp_path / "outer.zip"
    with zipfile.ZipFile(outer, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("inner.zip", inner.read_bytes() * 400)
        zf.writestr("readme.txt", "hi" * 5000)
    r = c.convert(outer, ConvertOptions(target="7z", only_if_smaller=False))
    assert r.status == "converted", r.reason
    assert set(entry_names(cfg, r.output)) == {"inner.zip", "readme.txt"}


def test_directory_and_non_first_volumes(conv, tmp_path):
    c, _ = conv
    build_zip(tmp_path / "a.zip")
    sub = tmp_path / "lib"
    sub.mkdir()
    build_zip(sub / "b.zip")
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / "set.part2.rar").write_bytes(b"x")
    found = {p.name for p in c.discover([tmp_path])}
    assert found == {"a.zip", "b.zip"}
    assert {p.name for p in c.discover([tmp_path], recursive=False)} == {"a.zip"}


def test_recycle_removes_original_only_after_success(conv, tmp_path):
    c, _ = conv
    src = build_zip(tmp_path / "pack.zip")
    trashed = []
    fake = type(sys)("send2trash")
    fake.send2trash = trashed.append
    with patch.dict(sys.modules, {"send2trash": fake}):
        r = c.convert(src, ConvertOptions(target="7z", keep_original="recycle"))
    assert r.original_removed and trashed == [str(src)]
    # failure path: nothing recycled
    trashed.clear()
    src2 = tmp_path / "evil.zip"
    with zipfile.ZipFile(src2, "w") as zf:
        zf.writestr("../x", "x")
    with patch.dict(sys.modules, {"send2trash": fake}):
        r2 = c.convert(src2, ConvertOptions(target="7z", keep_original="recycle"))
    assert r2.status == "failed" and trashed == []


def test_recycle_takes_orphan_previews_with_the_original(conv, tmp_path):
    c, _ = conv
    src = build_zip(tmp_path / "pack.zip")
    (tmp_path / "pack.avif").write_bytes(b"PREVIEW")
    (tmp_path / "pack.thumb.avif").write_bytes(b"THUMB")
    out = tmp_path / "out"
    out.mkdir()
    trashed = []
    fake = type(sys)("send2trash")
    fake.send2trash = trashed.append
    with patch.dict(sys.modules, {"send2trash": fake}):
        r = c.convert(src, ConvertOptions(target="7z", output_dir=out, keep_original="recycle"))
    assert r.status == "converted" and r.original_removed
    assert trashed == [str(src), str(tmp_path / "pack.avif"), str(tmp_path / "pack.thumb.avif")]
    # the result got its own copies before the originals were recycled
    assert (out / "pack.avif").read_bytes() == b"PREVIEW"
    assert (out / "pack.thumb.avif").read_bytes() == b"THUMB"


def test_recycle_keeps_previews_that_still_pair_with_the_result(conv, tmp_path):
    c, _ = conv
    src = build_zip(tmp_path / "pack.zip")
    (tmp_path / "pack.avif").write_bytes(b"PREVIEW")
    (tmp_path / "pack.thumb.avif").write_bytes(b"THUMB")
    trashed = []
    fake = type(sys)("send2trash")
    fake.send2trash = trashed.append
    with patch.dict(sys.modules, {"send2trash": fake}):
        r = c.convert(src, ConvertOptions(target="7z", keep_original="recycle"))
    assert r.status == "converted" and r.original_removed
    assert trashed == [str(src)]  # pack.7z still pairs with the previews
    assert (tmp_path / "pack.avif").read_bytes() == b"PREVIEW"
    assert (tmp_path / "pack.thumb.avif").read_bytes() == b"THUMB"


def test_smallest_builds_all_available_formats_and_keeps_the_winner(conv, tmp_path):
    c, _ = conv
    src = build_zip(tmp_path / "pack.zip")
    before = src.read_bytes()
    r = c.convert(src, ConvertOptions(target="smallest"))
    assert r.status == "converted", r.reason
    assert r.output.suffix.lstrip(".") in ("7z", "rar", "zip")
    assert src.read_bytes() == before
    assert r.out_bytes < r.src_bytes
    assert not [p.name for p in tmp_path.iterdir() if ".kaelovun-part" in p.name]


def test_smallest_skips_when_nothing_would_be_smaller(conv, tmp_path):
    c, _ = conv
    src = tmp_path / "tiny.zip"
    with zipfile.ZipFile(src, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("a.txt", "x")
    r = c.convert(src, ConvertOptions(target="smallest"))
    assert r.status == "skipped" and "smaller" in r.reason
    assert sorted(p.name for p in tmp_path.iterdir() if p.name != "ws") == ["tiny.zip"]


def test_mtime_is_carried_over(conv, tmp_path):
    import os
    c, _ = conv
    src = build_zip(tmp_path / "pack.zip")
    os.utime(src, (1_500_000_000, 1_500_000_000))
    r = c.convert(src, ConvertOptions(target="7z"))
    assert int(r.output.stat().st_mtime) == 1_500_000_000


def test_cancel(conv, tmp_path):
    c, _ = conv
    src = build_zip(tmp_path / "pack.zip")
    r = c.convert(src, ConvertOptions(target="7z"), cancel=lambda: True)
    assert r.status in ("cancelled", "failed")
    assert sorted(p.name for p in tmp_path.iterdir() if p.name != "ws") == ["pack.zip"]


class TestNaming:
    @pytest.mark.parametrize("name,stem", [
        ("a.tar.gz", "a"), ("a.b.zip", "a.b"), ("x.part1.rar", "x"),
        ("y.7z.001", "y"), ("Z.RAR", "Z"),
    ])
    def test_archive_stem(self, name, stem):
        assert archive_stem(Path(name)) == stem

    def test_is_convertible(self):
        assert is_convertible(Path("a.zip")) and is_convertible(Path("a.7z.001"))
        assert not is_convertible(Path("a.psd"))
        assert not is_convertible(Path("a.kaelovun-part.7z"))

    def test_volume_detection(self, tmp_path):
        for n in ("v.part1.rar", "v.part2.rar", "v.part3.rar"):
            (tmp_path / n).write_bytes(b"x")
        first, vols = find_volumes(tmp_path / "v.part1.rar")
        assert first and len(vols) == 3
        assert find_volumes(tmp_path / "v.part2.rar")[0] is False
        (tmp_path / "old.rar").write_bytes(b"x")
        (tmp_path / "old.r00").write_bytes(b"x")
        assert [p.name for p in find_volumes(tmp_path / "old.rar")[1]] == ["old.rar", "old.r00"]
