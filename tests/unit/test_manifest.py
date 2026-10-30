import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from files.archive_backends import ArchiveEntry
from files.manifest import build_manifest, crc32_of, manifest_from_paths, verify_entries


def make_tree(root):
    (root / "d").mkdir(parents=True)
    (root / "a.txt").write_text("hello")
    (root / "d" / "b.bin").write_bytes(b"\x00" * 10)
    return root


def entries_for(manifest):
    return [ArchiveEntry(path=m.path, size=m.size, crc=m.crc) for m in manifest.values()]


def test_matching_archive_passes(tmp_path):
    m = build_manifest(make_tree(tmp_path), with_crc=True)
    r = verify_entries(m, entries_for(m), check_crc=True)
    assert r.ok and r.checked == 2


def test_duplicate_inputs_are_one_entry(tmp_path):
    make_tree(tmp_path)
    m = build_manifest(tmp_path, [Path("a.txt"), Path("a.txt"), Path("d/b.bin")])
    assert len(m) == 2          # a file listed twice (asset + its own preview) is still one entry


def test_missing_extra_and_size_mismatch(tmp_path):
    m = build_manifest(make_tree(tmp_path))
    actual = [ArchiveEntry("a.txt", 999), ArchiveEntry("surprise.txt", 1)]
    r = verify_entries(m, actual)
    assert r.missing == ["d/b.bin"] and r.extra == ["surprise.txt"] and r.size_mismatch == ["a.txt"]
    assert not r.ok and "missing" in r.describe()


def test_directories_are_ignored(tmp_path):
    m = build_manifest(make_tree(tmp_path))
    actual = entries_for(m) + [ArchiveEntry("d", 0, is_dir=True), ArchiveEntry("empty", 0, is_dir=True)]
    assert verify_entries(m, actual).ok


def test_crc_mismatch_detected_only_in_paranoid(tmp_path):
    m = build_manifest(make_tree(tmp_path), with_crc=True)
    bad = entries_for(m)
    bad[0].crc ^= 1
    assert verify_entries(m, bad, check_crc=False).ok
    assert verify_entries(m, bad, check_crc=True).crc_mismatch


def test_unicode_normalisation_and_separators(tmp_path):
    nfd = "cafe\u0301.txt"      # macOS-style decomposed name
    m = manifest_from_paths(["caf\u00e9.txt", "dir\\x.txt"])
    r = verify_entries(m, [ArchiveEntry(nfd, 1), ArchiveEntry("dir/x.txt", 1)])
    assert r.ok


def test_crc32_matches_zlib(tmp_path):
    import zlib
    p = tmp_path / "f"
    p.write_bytes(b"abc" * 1000)
    assert crc32_of(p) == zlib.crc32(b"abc" * 1000) & 0xFFFFFFFF
