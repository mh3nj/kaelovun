"""Archive backends: parsers, command construction, and real 7z/ZIP round trips."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from conftest import FakeConfig, needs_7z  # noqa: E402

from files.archive import ArchiveManager
from files.archive_backends import (
    ArchiveEntry, Cancelled, RarBackend, SevenZipBackend, ToolError, ToolLocator,
    ToolResult, ZipBackend, _chunk_args, list_entries, parse_7z_slt, parse_rar_lt,
    run_tool, test_archive as run_test_archive,
)
from files.archive_prefs import ArchivePrefs, load_prefs


SLT_SAMPLE = """\
7-Zip 23.01 (x64) : Copyright (c) 1999-2023 Igor Pavlov : 2023-06-20

Scanning the drive for archives:
1 file, 5000 bytes (5 KiB)

Listing archive: x.7z

--
Path = x.7z
Type = 7z
Physical Size = 5000
Headers Size = 150
Method = LZMA2:24
Solid = +
Blocks = 1

----------
Path = dir
Folder = +
Size = 0
Packed Size = 0
Attributes = D

Path = dir\\my file.psd
Folder = -
Size = 4096
Packed Size = 1000
Modified = 2024-01-02 03:04:05
Attributes = A
CRC = 1A2B3C4D
Encrypted = -
Method = LZMA2:24
Block = 0

Path = link
Folder = -
Size = 5
Attributes = A_ lrwxrwxrwx
Symbolic Link = target
"""

RAR_LT_SAMPLE = """\
UNRAR 7.00 freeware      Copyright (c) 1993-2024 Alexander Roshal

Archive: x.rar
Details: RAR 5

        Name: some folder
        Type: Directory
        Size: 0
       mtime: 2024-01-02 03:04:05,000000000

        Name: some folder/my file.psd
        Type: File
        Size: 4096
 Packed size: 1000
       Ratio: 24%
       mtime: 2024-01-02 03:04:05,000000000
  Attributes: -rw-r--r--
       CRC32: 1A2B3C4D
     Host OS: Windows
 Compression: RAR 5.0(v50) -m5 -md=64M

        Name: sym
        Type: Unix symbolic link
        Size: 0
"""


class TestParsers:
    def test_slt_parses_entries_and_ignores_header(self):
        meta, entries = parse_7z_slt(SLT_SAMPLE)
        assert meta["Type"] == "7z"
        assert [e.path for e in entries] == ["dir", "dir/my file.psd", "link"]

    def test_slt_flags(self):
        _meta, entries = parse_7z_slt(SLT_SAMPLE)
        d, f, link = entries
        assert d.is_dir and not f.is_dir
        assert f.size == 4096 and f.crc == 0x1A2B3C4D
        assert link.is_link and not f.is_link

    def test_rar_lt_is_key_value_blocks_not_columns(self):
        entries = parse_rar_lt(RAR_LT_SAMPLE)
        assert [e.path for e in entries] == ["some folder", "some folder/my file.psd", "sym"]
        folder, f, sym = entries
        assert folder.is_dir
        assert f.size == 4096 and f.crc == 0x1A2B3C4D
        assert sym.is_link

    def test_rar_lt_keeps_names_with_spaces_intact(self):
        # The old column parser split on whitespace and kept only the last word.
        entries = parse_rar_lt(RAR_LT_SAMPLE)
        assert "some folder/my file.psd" in [e.path for e in entries]


class TestChunking:
    def test_batches_stay_under_budget(self):
        names = [f"folder/file_{i:05d}.psd" for i in range(5000)]
        batches = _chunk_args(names, 20000)
        assert sum(len(b) for b in batches) == 5000
        for b in batches:
            assert sum(len(n) + 1 for n in b) < 20000

    def test_empty(self):
        assert _chunk_args([], 20000) == [[]]


class TestRarCommand:
    def make(self, tmp_path, **kw):
        prefs = load_prefs(FakeConfig(tmp_path, **kw))
        loc = ToolLocator(prefs)
        loc._rar = Path("Rar.exe")
        return RarBackend(loc, prefs)

    def test_switches(self, tmp_path):
        s = self.make(tmp_path, level="best", dict_mb=64, solid="solid", recovery_pct=3)._switches()
        assert "-ma5" in s and "-m5" in s and "-md64m" in s and "-s" in s and "-rr3p" in s
        assert not any(x.startswith("-sc") for x in s)

    def test_solid_modes_and_levels(self, tmp_path):
        assert "-s-" in self.make(tmp_path, solid="off")._switches()
        assert "-se" in self.make(tmp_path, solid="type")._switches()
        assert "-m1" in self.make(tmp_path, level="fast")._switches()

    def test_dictionary_is_rounded_to_a_power_of_two(self, tmp_path):
        assert "-md64m" in self.make(tmp_path, dict_mb=100)._switches()

    def test_big_file_lists_are_split_across_calls(self, tmp_path):
        backend = self.make(tmp_path)
        names = [f"some/long/folder/name/file_{i:05d}.psd" for i in range(2000)]
        calls = []

        def fake_run(argv, cwd=None, progress=None, cancel=None, **kw):
            calls.append(argv)
            Path(argv[argv.index("--") + 1]).write_bytes(b"x")
            return ToolResult(0, "", "")

        with patch("files.archive_backends.run_tool", fake_run):
            backend.create(tmp_path / "o.rar", tmp_path, names)
        assert len(calls) > 1
        for argv in calls:
            assert sum(len(a) + 1 for a in argv) < 32000
        assert sum(len(c) - (c.index("--") + 2) for c in calls) == 2000

    def test_nonzero_exit_is_a_failure_and_leaves_no_partial(self, tmp_path):
        backend = self.make(tmp_path)
        (tmp_path / "a.txt").write_text("x")

        def fake_run(argv, **kw):
            Path(argv[argv.index("--") + 1]).write_bytes(b"half")
            return ToolResult(1, "", "WARNING: cannot read file")

        with patch("files.archive_backends.run_tool", fake_run):
            with pytest.raises(ToolError):
                backend.create(tmp_path / "o.rar", tmp_path, ["a.txt"])
        assert not (tmp_path / "o.rar").exists()


@needs_7z
class TestSevenZipRoundTrip:
    @pytest.fixture
    def tree(self, tmp_path):
        root = tmp_path / "src"
        (root / "sub dir" / "ünï").mkdir(parents=True)
        (root / "empty").mkdir()
        (root / "a b.txt").write_text("hello " * 1000, encoding="utf-8")
        (root / "sub dir" / "ünï" / "فایل.psd").write_bytes(b"persian" * 100)
        (root / "r.avif").write_bytes(bytes(range(256)) * 50)
        return root

    def backend(self, tmp_path, cls=SevenZipBackend, **kw):
        prefs = load_prefs(FakeConfig(tmp_path, **kw))
        return cls(ToolLocator(prefs), prefs), ToolLocator(prefs)

    def test_whole_tree_keeps_empty_dirs_and_unicode(self, tree, tmp_path):
        b, loc = self.backend(tmp_path)
        out = b.create(tmp_path / "o.7z", tree, None)
        names = {e.path for e in list_entries(out, loc)}
        assert {"a b.txt", "empty", "sub dir/ünï/فایل.psd", "r.avif"} <= names
        assert run_test_archive(out, loc)

    def test_file_list_mode_only_includes_listed_files(self, tree, tmp_path):
        b, loc = self.backend(tmp_path)
        out = b.create(tmp_path / "o.7z", tree, ["a b.txt", "sub dir/ünï/فایل.psd"])
        files = {e.path for e in list_entries(out, loc) if not e.is_dir}
        assert files == {"a b.txt", "sub dir/ünï/فایل.psd"}

    def test_existing_output_is_replaced_not_appended_to(self, tree, tmp_path):
        b, loc = self.backend(tmp_path)
        out = tmp_path / "o.7z"
        b.create(out, tree, ["a b.txt"])
        b.create(out, tree, ["r.avif"])
        assert {e.path for e in list_entries(out, loc)} == {"r.avif"}

    def test_cancel_stops_and_removes_partial(self, tree, tmp_path):
        b, _ = self.backend(tmp_path)
        with pytest.raises(Cancelled):
            b.create(tmp_path / "o.7z", tree, None, cancel=lambda: True)
        assert not (tmp_path / "o.7z").exists()

    def test_zip_backend_roundtrip(self, tree, tmp_path):
        b, loc = self.backend(tmp_path, ZipBackend)
        out = b.create(tmp_path / "o.zip", tree, None)
        names = {e.path for e in list_entries(out, loc)}
        assert {"a b.txt", "empty", "sub dir/ünï/فایل.psd"} <= names
        assert run_test_archive(out, loc)

    def test_corrupt_archive_fails_test(self, tree, tmp_path):
        b, loc = self.backend(tmp_path)
        out = b.create(tmp_path / "o.7z", tree, None)
        data = bytearray(out.read_bytes())
        for i in range(40, 120):
            data[i] ^= 0xFF
        out.write_bytes(bytes(data))
        assert run_test_archive(out, loc) is False

    def test_smallest_keeps_only_the_smaller_one(self, tree, tmp_path, logger):
        mgr = ArchiveManager(FakeConfig(tmp_path), logger)

        class FakeRar(ZipBackend):
            fmt, ext = "rar", ".rar"

            def create(self, output, work_dir, rel_files, progress=None, cancel=None):
                Path(output).write_bytes(b"x" * 10_000_000)
                return Path(output)

        with patch.dict("files.archive.BACKENDS", {"rar": FakeRar}):
            out = mgr.create_tree(tree, tmp_path / "res", fmt="smallest")
        assert out.suffix == ".7z"
        assert not (tmp_path / "res.rar").exists()
        assert not (tmp_path / "res.zip").exists()


def test_run_tool_reports_progress_and_decodes_utf8():
    seen = []
    res = run_tool([sys.executable, "-c",
                    "import sys; sys.stdout.write('10% \\u00e9\\n55%\\n100%\\n')"],
                   progress=seen.append)
    assert res.returncode == 0 and "é" in res.stdout
    assert seen[-1] == 100.0


def test_run_tool_cancel_kills_process():
    with pytest.raises(Cancelled):
        run_tool([sys.executable, "-c", "import time; time.sleep(30)"], cancel=lambda: True)
