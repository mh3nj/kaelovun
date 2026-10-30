"""
archive_backends.py

Everything that talks to archivers.

    ToolLocator     finds 7z / Rar.exe (settings -> bundled -> PATH -> Program Files)
    run_tool        runs a tool with live progress, cancel, UTF-8 output, no console flash
    SevenZipBackend 7z (LZMA2) and, through the same binary, anything 7-Zip can read
    RarBackend      RAR5 through Rar.exe (WinRAR). Needed to *create* RAR; 7-Zip can't.
    ZipBackend      pure-Python ZIP, so ZIP output works with no external tools at all
    list_entries    one listing API for zip / tar / 7z / rar / ...
    test_archive    integrity test through the best tool available for the format

Design rules
------------
* Never build a shell string. Arguments are always a list.
* File lists go through a UTF-8 list file (7z) or are chunked (RAR) so a package
  with thousands of files never hits the Windows command-line length limit.
* A non-zero exit code is a failure, including "warnings": a warning can mean a
  file was skipped, and for an archiver that is data loss.
* Passwords are fed through stdin, never put on the command line.
"""

import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

from files.archive_prefs import ArchivePrefs, PRECOMPRESSED_TYPES

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

TAR_SUFFIXES = (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")
_PROGRESS_RE = re.compile(r"(\d{1,3})%")

ProgressCb = Optional[Callable[[float], None]]
CancelCb = Optional[Callable[[], bool]]


# ──────────────────────────────────────────────────────────────
# Errors
# ──────────────────────────────────────────────────────────────

class ToolError(RuntimeError):
    """An archiver failed, is missing, or produced something unusable."""


class PasswordRequired(ToolError):
    """The archive is encrypted and no (or the wrong) password was supplied."""


class Cancelled(ToolError):
    """The operation was cancelled by the caller."""


# ──────────────────────────────────────────────────────────────
# Data
# ──────────────────────────────────────────────────────────────

@dataclass
class ArchiveEntry:
    path: str                      # always "/" separated, no leading "./"
    size: int = 0
    is_dir: bool = False
    crc: Optional[int] = None      # CRC32 when the format/tool reports one
    encrypted: bool = False
    is_link: bool = False
    packed: Optional[int] = None


def norm_path(name: str) -> str:
    """Normalise an archive member name to forward slashes, no leading ./ or trailing /."""
    n = name.replace("\\", "/")
    while n.startswith("./"):
        n = n[2:]
    return n.rstrip("/")


def human_size(num: float) -> str:
    num = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024 or unit == "TB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} TB"


def archive_kind(path) -> str:
    """'zip' | 'tar' | 'rar' | '7z' | 'other' (by file name)."""
    name = Path(path).name.lower()
    if name.endswith(TAR_SUFFIXES):
        return "tar"
    if name.endswith(".zip"):
        return "zip"
    if name.endswith(".rar") or re.search(r"\.r\d\d$", name) or re.search(r"\.part0*1\.rar$", name):
        return "rar"
    if name.endswith(".7z") or re.search(r"\.7z\.\d{3}$", name):
        return "7z"
    return "other"


# ──────────────────────────────────────────────────────────────
# Tool discovery
# ──────────────────────────────────────────────────────────────

class ToolLocator:
    """Finds 7-Zip and Rar.exe. Results are cached per instance."""

    def __init__(self, prefs: ArchivePrefs, base_dir: Optional[Path] = None):
        self.prefs = prefs
        self.base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
        self._sevenzip = ...
        self._rar = ...

    def _vendor_dirs(self) -> List[Path]:
        dirs = [self.base_dir / "vendor" / "7z", self.base_dir / "vendor", self.base_dir]
        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).parent
            dirs += [exe_dir / "_internal" / "vendor" / "7z", exe_dir / "vendor" / "7z", exe_dir]
        return dirs

    def sevenzip(self) -> Optional[Path]:
        if self._sevenzip is not ...:
            return self._sevenzip
        candidates: List[Path] = []
        if self.prefs.sevenzip_path:
            candidates.append(self.prefs.sevenzip_path)
        for folder in self._vendor_dirs():
            for exe in ("7z.exe", "7zz.exe", "7z", "7zz"):
                candidates.append(folder / exe)
        for exe in ("7z", "7zz"):
            found = shutil.which(exe)
            if found:
                candidates.append(Path(found))
        for pf in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                   r"C:\Program Files", r"C:\Program Files (x86)"):
            if pf:
                candidates.append(Path(pf) / "7-Zip" / "7z.exe")
        # 7za (standalone) can't read RAR, so it's the last resort.
        found = shutil.which("7za")
        if found:
            candidates.append(Path(found))
        self._sevenzip = next((c for c in candidates if _is_file(c)), None)
        return self._sevenzip

    def rar(self) -> Optional[Path]:
        if self._rar is not ...:
            return self._rar
        candidates: List[Path] = []
        for p in (self.prefs.rar_path, self.prefs.rar_gui_path):
            if p:
                candidates.append(p)
        found = shutil.which("rar")
        if found:
            candidates.append(Path(found))
        self._rar = next((c for c in candidates if _is_file(c)), None)
        return self._rar


def _is_file(path: Path) -> bool:
    try:
        return Path(path).is_file()
    except OSError:
        return False


# ──────────────────────────────────────────────────────────────
# Process runner
# ──────────────────────────────────────────────────────────────

@dataclass
class ToolResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def text(self) -> str:
        return (self.stdout or "") + ("\n" + self.stderr if self.stderr else "")


def run_tool(
    cmd: Sequence,
    cwd: Optional[Path] = None,
    progress: ProgressCb = None,
    cancel: CancelCb = None,
    input_text: Optional[str] = None,
    timeout: Optional[float] = None,
) -> ToolResult:
    """
    Run an external tool and capture its output.

    * stdout/stderr are drained on threads (no pipe deadlocks on big listings)
    * percentages ("37%") in the output are forwarded to ``progress``
    * ``cancel()`` is polled; when it returns True the process is killed
    * output is decoded as UTF-8 (callers pass -sccUTF-8 to 7z) with errors replaced
    """
    argv = [str(c) for c in cmd]
    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(cwd) if cwd else None,
            stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=CREATE_NO_WINDOW,
        )
    except OSError as exc:
        raise ToolError(f"Could not start {Path(argv[0]).name}: {exc}") from exc

    out_buf, err_buf = bytearray(), bytearray()
    last_pct = [-1]

    def pump(stream, buf, report):
        try:
            while True:
                chunk = stream.read1(65536) if hasattr(stream, "read1") else stream.read(65536)
                if not chunk:
                    break
                buf.extend(chunk)
                if report and progress:
                    matches = _PROGRESS_RE.findall(chunk.decode("utf-8", "replace"))
                    if matches:
                        pct = min(100, int(matches[-1]))
                        if pct != last_pct[0]:
                            last_pct[0] = pct
                            try:
                                progress(float(pct))
                            except Exception:
                                pass
        except (OSError, ValueError):
            pass

    t_out = threading.Thread(target=pump, args=(proc.stdout, out_buf, True), daemon=True)
    t_err = threading.Thread(target=pump, args=(proc.stderr, err_buf, False), daemon=True)
    t_out.start()
    t_err.start()

    if input_text is not None:
        try:
            proc.stdin.write(input_text.encode("utf-8"))
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass

    started = time.monotonic()
    try:
        while proc.poll() is None:
            if cancel and cancel():
                proc.kill()
                proc.wait()
                raise Cancelled("Cancelled.")
            if timeout and time.monotonic() - started > timeout:
                proc.kill()
                proc.wait()
                raise ToolError(f"{Path(argv[0]).name} timed out after {timeout:.0f}s")
            time.sleep(0.05)
    finally:
        t_out.join(timeout=5)
        t_err.join(timeout=5)

    return ToolResult(
        proc.returncode,
        out_buf.decode("utf-8", "replace"),
        err_buf.decode("utf-8", "replace"),
    )


_PASSWORD_HINTS = ("wrong password", "enter password", "encrypted", "password is incorrect",
                   "incorrect password", "can not open encrypted")


def _looks_like_password_problem(text: str) -> bool:
    low = text.lower()
    return any(h in low for h in _PASSWORD_HINTS)


# ──────────────────────────────────────────────────────────────
# Listing parsers (pure functions, unit-tested with captured output)
# ──────────────────────────────────────────────────────────────

_UNIX_LINK_MODE = re.compile(r"(?:^|\s)l[rwxstST-]{9}(?:\s|$)")


def parse_7z_slt(text: str) -> Tuple[dict, List[ArchiveEntry]]:
    """Parse ``7z l -slt`` output into (archive_properties, entries)."""
    meta: dict = {}
    entries: List[ArchiveEntry] = []
    block: dict = {}
    in_entries = False
    in_meta = False

    def flush():
        nonlocal block
        if block.get("Path") is not None:
            entries.append(_entry_from_slt(block))
        block = {}

    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if line.startswith("----------"):
            in_entries, in_meta = True, False
            block = {}
            continue
        if line == "--":
            in_meta, in_entries = True, False
            continue
        if not line.strip():
            if in_entries:
                flush()
            continue
        if " = " in line or line.endswith(" ="):
            key, _, value = line.partition(" =")
            key = key.strip()
            value = value[1:] if value.startswith(" ") else value
            if in_entries:
                block[key] = value
            elif in_meta:
                meta[key] = value
    if in_entries:
        flush()
    return meta, entries


def _entry_from_slt(block: dict) -> ArchiveEntry:
    attrs = block.get("Attributes", "")
    is_dir = block.get("Folder") == "+" or attrs.startswith("D")
    is_link = bool(
        block.get("Symbolic Link") or block.get("Hard Link") or block.get("Link")
        or _UNIX_LINK_MODE.search(attrs)
    )
    crc = None
    crc_text = (block.get("CRC") or "").strip()
    if crc_text:
        try:
            crc = int(crc_text, 16)
        except ValueError:
            crc = None

    def to_int(value):
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None

    return ArchiveEntry(
        path=norm_path(block.get("Path", "")),
        size=to_int(block.get("Size")) or 0,
        is_dir=is_dir,
        crc=crc,
        encrypted=(block.get("Encrypted") or "").strip() == "+",
        is_link=is_link,
        packed=to_int(block.get("Packed Size")),
    )


def parse_rar_lt(text: str) -> List[ArchiveEntry]:
    """
    Parse ``Rar.exe lt`` (technical list). RAR prints one ``Key: value`` block per
    entry, NOT a column table, which is why the old column parser could not work.
    """
    entries: List[ArchiveEntry] = []
    block: dict = {}

    def flush():
        nonlocal block
        name = block.get("Name")
        if name is not None:
            kind = (block.get("Type") or "").lower()
            crc = None
            for key in ("CRC32", "CRC"):
                if block.get(key):
                    try:
                        crc = int(block[key].split()[0], 16)
                    except ValueError:
                        crc = None
                    break
            try:
                size = int((block.get("Size") or "0").split()[0])
            except ValueError:
                size = 0
            entries.append(ArchiveEntry(
                path=norm_path(name),
                size=size,
                is_dir="directory" in kind,
                crc=crc,
                encrypted="encrypted" in (block.get("Flags") or "").lower(),
                is_link="link" in kind,
            ))
        block = {}

    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if not line.strip():
            flush()
            continue
        key, sep, value = line.strip().partition(":")
        if not sep:
            continue
        key = key.strip()
        # A new "Name:" starts a new entry even if the blank separator was missing.
        if key == "Name" and "Name" in block:
            flush()
        block[key] = value.strip()
    flush()
    return entries


# ──────────────────────────────────────────────────────────────
# 7-Zip wrapper (works on anything 7-Zip understands)
# ──────────────────────────────────────────────────────────────

class SevenZip:
    """Thin, strict wrapper around the 7z command line."""

    def __init__(self, exe: Path):
        self.exe = Path(exe)

    def _argv(self, command: str, *switches: str) -> list:
        return [str(self.exe), command, "-y", "-sccUTF-8", *switches]

    def list(self, archive: Path, password: Optional[str] = None,
             cancel: CancelCb = None) -> Tuple[dict, List[ArchiveEntry]]:
        res = run_tool(self._argv("l", "-slt") + ["--", str(archive)],
                       cancel=cancel, input_text=_pw(password))
        if res.returncode not in (0, 1):
            if _looks_like_password_problem(res.text):
                raise PasswordRequired(f"Archive is password-protected: {Path(archive).name}")
            raise ToolError(f"7-Zip could not read {Path(archive).name}: {_tail(res)}")
        meta, entries = parse_7z_slt(res.stdout)
        if not entries and "Type" not in meta:
            if _looks_like_password_problem(res.text):
                raise PasswordRequired(f"Archive is password-protected: {Path(archive).name}")
            raise ToolError(f"7-Zip could not list {Path(archive).name}: {_tail(res)}")
        return meta, entries

    def test(self, archive: Path, password: Optional[str] = None,
             progress: ProgressCb = None, cancel: CancelCb = None) -> bool:
        res = run_tool(self._argv("t", "-bsp1") + ["--", str(archive)],
                       progress=progress, cancel=cancel, input_text=_pw(password))
        return res.returncode == 0

    def extract(self, archive: Path, dest: Path, password: Optional[str] = None,
                exclude: Iterable[str] = (), progress: ProgressCb = None,
                cancel: CancelCb = None) -> None:
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        switches = ["-bsp1", "-aoa", f"-o{dest}"]
        excl_file = None
        exclude = [e for e in exclude if e]
        try:
            if exclude:
                excl_file = _write_list_file(exclude)
                switches += ["-scsUTF-8", f"-x@{excl_file}"]
            res = run_tool(self._argv("x", *switches) + ["--", str(archive)],
                           progress=progress, cancel=cancel, input_text=_pw(password))
        finally:
            _remove_quietly(excl_file)
        if res.returncode != 0:
            if _looks_like_password_problem(res.text):
                raise PasswordRequired(f"Archive is password-protected: {Path(archive).name}")
            raise ToolError(f"7-Zip failed to extract {Path(archive).name} "
                            f"(exit {res.returncode}): {_tail(res)}")

    def add(self, output: Path, work_dir: Path, rel_files: Optional[Sequence[str]],
            args: Sequence[str], progress: ProgressCb = None, cancel: CancelCb = None) -> None:
        list_file = None
        try:
            switches = list(args) + ["-bsp1"]
            if rel_files is None:
                targets = ["*"]
            else:
                list_file = _write_list_file(rel_files)
                switches += ["-scsUTF-8"]
                targets = [f"@{list_file}"]
            # No "--" here: it would stop 7z from treating @listfile as a list.
            # The output path is made absolute so it can't be mistaken for a switch.
            res = run_tool(self._argv("a", *switches) + [str(Path(output).absolute())] + targets,
                           cwd=work_dir, progress=progress, cancel=cancel)
        finally:
            _remove_quietly(list_file)
        if res.returncode != 0:
            raise ToolError(f"7-Zip failed to create {Path(output).name} "
                            f"(exit {res.returncode}): {_tail(res)}")


def _pw(password: Optional[str]) -> Optional[str]:
    return None if password is None else password + "\n"


def _tail(res: ToolResult, lines: int = 6) -> str:
    text = (res.stderr.strip() or res.stdout.strip())
    parts = [p for p in text.splitlines() if p.strip()]
    return " | ".join(parts[-lines:]) if parts else "(no output)"


def _write_list_file(names: Iterable[str]) -> Path:
    fd, name = tempfile.mkstemp(prefix="kaelovun_", suffix=".lst")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        for item in names:
            handle.write(str(item) + "\n")
    return Path(name)


def _remove_quietly(path: Optional[Path]) -> None:
    if path:
        try:
            Path(path).unlink()
        except OSError:
            pass


def _pow2_floor(value: int) -> int:
    value = max(1, int(value))
    return 1 << (value.bit_length() - 1)


# ──────────────────────────────────────────────────────────────
# Backends
# ──────────────────────────────────────────────────────────────

class ArchiveBackend:
    fmt = ""
    ext = ""

    def __init__(self, locator: ToolLocator, prefs: ArchivePrefs):
        self.locator = locator
        self.prefs = prefs

    def available(self) -> Tuple[bool, str]:
        raise NotImplementedError

    def create(self, output: Path, work_dir: Path, rel_files: Optional[Sequence[str]],
               progress: ProgressCb = None, cancel: CancelCb = None) -> Path:
        """
        Create ``output`` (full path including the extension) from ``work_dir``.
        ``rel_files`` are work_dir-relative paths, or None for "the whole tree".
        """
        raise NotImplementedError


class SevenZipBackend(ArchiveBackend):
    fmt, ext = "7z", ".7z"

    def available(self):
        return (True, "") if self.locator.sevenzip() else (
            False, "7-Zip (7z.exe) not found. Install 7-Zip or set its path in Settings > Archive.")

    def create(self, output, work_dir, rel_files, progress=None, cancel=None):
        exe = self.locator.sevenzip()
        if not exe:
            raise ToolError(self.available()[1])
        p = self.prefs
        level = {"fast": 1, "normal": 5, "best": 9}[p.level]
        args = ["-t7z", "-m0=lzma2", f"-mx={level}", f"-md={p.dict_mb}m"]
        if p.solid == "off":
            args.append("-ms=off")
        elif p.solid == "type":
            args.append("-ms=e")
        else:
            args += ["-ms=on", "-mqs=on"]
        args.append("-mmt=on" if not p.threads else f"-mmt={p.threads}")
        _unlink_quietly(output)
        try:
            SevenZip(exe).add(output, work_dir, rel_files, args, progress, cancel)
        except BaseException:
            _unlink_quietly(output)
            raise
        return output


class RarBackend(ArchiveBackend):
    fmt, ext = "rar", ".rar"
    # Keep each Rar.exe call well under the 32,767 character Windows limit.
    MAX_ARGV_CHARS = 20000

    def available(self):
        return (True, "") if self.locator.rar() else (
            False, "Rar.exe (WinRAR) not found. RAR output needs WinRAR installed "
                   "(7-Zip can read RAR but cannot create it).")

    def _switches(self) -> List[str]:
        p = self.prefs
        s = ["-ma5", {"fast": "-m1", "normal": "-m3", "best": "-m5"}[p.level],
             f"-md{_pow2_floor(p.dict_mb)}m"]
        s.append({"solid": "-s", "type": "-se", "off": "-s-"}[p.solid])
        if p.recovery_pct:
            s.append(f"-rr{p.recovery_pct}p")
        if p.threads:
            s.append(f"-mt{p.threads}")
        if p.store_precompressed:
            s.append("-ms" + ";".join(f"*.{e}" for e in PRECOMPRESSED_TYPES))
        s += ["-r", "-y", "-idc"]
        return s

    def create(self, output, work_dir, rel_files, progress=None, cancel=None):
        exe = self.locator.rar()
        if not exe:
            raise ToolError(self.available()[1])
        _unlink_quietly(output)
        base = [str(exe), "a"] + self._switches() + ["--", str(output)]
        try:
            if rel_files is None:
                self._run(base + ["*"], work_dir, progress, cancel)
            else:
                batches = _chunk_args(list(rel_files), self.MAX_ARGV_CHARS - sum(len(a) + 1 for a in base))
                for i, batch in enumerate(batches):
                    # `rar a` on an existing archive appends, so batches build one archive.
                    sub = (lambda pct, i=i, n=len(batches): progress((i + pct / 100.0) / n * 100.0)) \
                        if progress else None
                    self._run(base + batch, work_dir, sub, cancel)
        except BaseException:
            _unlink_quietly(output)
            raise
        if not Path(output).exists():
            raise ToolError(f"RAR file not created: {Path(output).name}")
        return output

    @staticmethod
    def _run(argv, cwd, progress, cancel):
        res = run_tool(argv, cwd=cwd, progress=progress, cancel=cancel)
        if res.returncode != 0:
            raise ToolError(f"RAR failed (exit {res.returncode}): {_tail(res)}")


class ZipBackend(ArchiveBackend):
    fmt, ext = "zip", ".zip"

    def available(self):
        return True, ""

    def create(self, output, work_dir, rel_files, progress=None, cancel=None):
        level = {"fast": 1, "normal": 6, "best": 9}[self.prefs.level]
        store = {f".{e}" for e in PRECOMPRESSED_TYPES} if self.prefs.store_precompressed else set()
        work_dir = Path(work_dir)
        if rel_files is None:
            items: List[Tuple[str, bool]] = []
            for dirpath, dirnames, filenames in os.walk(work_dir):
                dirnames.sort()
                rel_dir = Path(dirpath).relative_to(work_dir)
                if str(rel_dir) != ".":
                    items.append((rel_dir.as_posix(), True))
                for fn in sorted(filenames):
                    items.append(((rel_dir / fn).as_posix(), False))
        else:
            items = [(Path(r).as_posix(), False) for r in rel_files]

        total = sum((work_dir / r).stat().st_size for r, d in items if not d) or 1
        done = 0
        _unlink_quietly(output)
        try:
            with zipfile.ZipFile(output, "w", allowZip64=True) as zf:
                for rel, is_dir in items:
                    if cancel and cancel():
                        raise Cancelled("Cancelled.")
                    src = work_dir / rel
                    if is_dir:
                        zf.write(src, rel)
                        continue
                    method = zipfile.ZIP_STORED if src.suffix.lower() in store else zipfile.ZIP_DEFLATED
                    zf.write(src, rel, compress_type=method, compresslevel=level)
                    done += src.stat().st_size
                    if progress:
                        progress(min(100.0, done * 100.0 / total))
        except BaseException:
            _unlink_quietly(output)
            raise
        return output


def _chunk_args(items: List[str], budget: int) -> List[List[str]]:
    budget = max(budget, 2000)
    batches, current, used = [], [], 0
    for item in items:
        cost = len(item) + 3
        if current and used + cost > budget:
            batches.append(current)
            current, used = [], 0
        current.append(item)
        used += cost
    if current:
        batches.append(current)
    return batches or [[]]


def _unlink_quietly(path) -> None:
    try:
        Path(path).unlink()
    except (FileNotFoundError, OSError):
        pass


BACKENDS = {"rar": RarBackend, "7z": SevenZipBackend, "zip": ZipBackend}


# ──────────────────────────────────────────────────────────────
# Listing and testing (any format)
# ──────────────────────────────────────────────────────────────

def list_entries(path: Path, locator: ToolLocator, password: Optional[str] = None,
                 cancel: CancelCb = None) -> List[ArchiveEntry]:
    path = Path(path)
    kind = archive_kind(path)
    if kind == "zip":
        return _list_zip(path, password)
    if kind == "tar":
        return _list_tar(path)
    exe = locator.sevenzip()
    if exe:
        return SevenZip(exe).list(path, password, cancel)[1]
    rar = locator.rar()
    if rar and kind == "rar":
        res = run_tool([str(rar), "lt", "-idc", "--", str(path)], cancel=cancel)
        if res.returncode != 0:
            if _looks_like_password_problem(res.text):
                raise PasswordRequired(f"Archive is password-protected: {path.name}")
            raise ToolError(f"Rar.exe could not list {path.name}: {_tail(res)}")
        return parse_rar_lt(res.stdout)
    raise ToolError("7-Zip is required to read this archive type and was not found. "
                    "Install 7-Zip or set its path in Settings > Archive.")


def _list_zip(path: Path, password: Optional[str] = None) -> List[ArchiveEntry]:
    out = []
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            mode = (info.external_attr >> 16) & 0o170000
            out.append(ArchiveEntry(
                path=norm_path(info.filename),
                size=info.file_size,
                is_dir=info.is_dir(),
                crc=info.CRC if not info.is_dir() else None,
                encrypted=bool(info.flag_bits & 0x1),
                is_link=(mode == 0o120000),
                packed=info.compress_size,
            ))
    return out


def _list_tar(path: Path) -> List[ArchiveEntry]:
    out = []
    with tarfile.open(path, "r:*") as tar:
        for member in tar:
            out.append(ArchiveEntry(
                path=norm_path(member.name),
                size=member.size if member.isfile() else 0,
                is_dir=member.isdir(),
                is_link=member.issym() or member.islnk(),
            ))
    return out


def test_archive(path: Path, locator: ToolLocator, password: Optional[str] = None,
                 progress: ProgressCb = None, cancel: CancelCb = None) -> bool:
    """Integrity-test an archive with the most authoritative tool available."""
    path = Path(path)
    kind = archive_kind(path)
    if kind == "zip":
        try:
            with zipfile.ZipFile(path) as zf:
                if password:
                    zf.setpassword(password.encode("utf-8"))
                return zf.testzip() is None
        except (zipfile.BadZipFile, RuntimeError, OSError):
            return False
    if kind == "tar":
        try:
            with tarfile.open(path, "r:*") as tar:
                for member in tar:
                    if member.isfile():
                        handle = tar.extractfile(member)
                        while handle and handle.read(1 << 20):
                            if cancel and cancel():
                                raise Cancelled("Cancelled.")
            return True
        except (tarfile.TarError, EOFError, OSError):
            return False
    rar = locator.rar()
    if kind == "rar" and rar:
        res = run_tool([str(rar), "t", "-idc", "-y", "--", str(path)],
                       progress=progress, cancel=cancel)
        return res.returncode == 0
    exe = locator.sevenzip()
    if exe:
        return SevenZip(exe).test(path, password, progress, cancel)
    raise ToolError("No tool available to test this archive (install 7-Zip).")
