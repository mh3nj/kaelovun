"""
cli.py

Command-line interface for headless Kaelovun operation.

Three modes:
  process   (default)      run the full asset pipeline on files / folders / archives
  convert   --convert-to   convert existing archives between RAR, 7z and ZIP only
  verify    --verify-only  integrity-test existing archives
"""

import sys
import time
import argparse
from pathlib import Path

from config import Config
from logger import Logger

from files.archive_prefs import FORMATS, LEVELS, VERIFY_LEVELS, load_prefs

VERSION = "1.7.0"


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Kaelovun - Creative Asset Processing and Preservation Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  kaelovun-cli /path/to/project.psd
  kaelovun-cli /path/to/project_folder --format 7z
  kaelovun-cli /path/to/archive.zip --format smallest
  kaelovun-cli --plan /path/to/folder                   (show what would happen)
  kaelovun-cli --resume-failed

Convert existing archives (no Adobe/Affinity needed):
  kaelovun-cli --convert-to 7z /path/to/old.rar
  kaelovun-cli --convert-to 7z /path/to/library --original recycle
  kaelovun-cli --convert-to rar /path/to/a.7z /path/to/b.zip --level best
  kaelovun-cli --convert-to 7z /path/to/library --plan   (preview only)

Check archives:
  kaelovun-cli --verify-only /path/to/folder_or_archive
        """
    )

    parser.add_argument("input", nargs="*",
                        help="Input file(s), directory(ies), or archive(s)")

    parser.add_argument("--engine", choices=["adobe", "affinity"],
                        help="Processing engine to use (overrides config)")
    parser.add_argument("--output", "-o",
                        help="Output directory for archives (default: next to source)")
    parser.add_argument("--name",
                        help="Name for the output archive (overrides interactive prompt)")
    parser.add_argument("--resume-failed", action="store_true",
                        help="Resume incomplete jobs from last session")
    parser.add_argument("--no-cleanup", action="store_true",
                        help="Keep workspace files after processing (for debugging)")
    parser.add_argument("--max-depth", type=int,
                        help="Maximum archive extraction depth (default: 2)")

    group = parser.add_argument_group("archive output")
    group.add_argument("--format", choices=FORMATS,
                       help="Archive format to produce (default: from Settings). "
                            "'smallest' builds 7z, ZIP and RAR and keeps the smallest")
    group.add_argument("--level", choices=LEVELS, help="Compression level")
    group.add_argument("--verify", choices=VERIFY_LEVELS, dest="verify_level",
                       help="standard = names+sizes, paranoid = also CRC32 of every file")
    group.add_argument("--workspace", help="Scratch folder for temporary work (pick a roomy drive)")

    conv = parser.add_argument_group("convert / verify existing archives")
    conv.add_argument("--convert-to", choices=("7z", "rar", "zip"), metavar="FORMAT",
                      help="Convert the given archives (or every archive in the given "
                           "folders) to FORMAT: 7z, rar or zip")
    conv.add_argument("--original", choices=("keep", "recycle"), default="keep",
                      help="What to do with the original after a verified conversion "
                           "(recycle = Recycle Bin, never a permanent delete). Default: keep")
    conv.add_argument("--allow-larger", action="store_true",
                      help="Keep the converted archive even if it is not smaller")
    conv.add_argument("--no-recursive", action="store_true",
                      help="Do not look inside sub-folders for archives")
    conv.add_argument("--ask-password", action="store_true",
                      help="Prompt for the password of encrypted archives")
    conv.add_argument("--password", help="Password for encrypted archives "
                                         "(visible in shell history; prefer --ask-password)")
    conv.add_argument("--verify-only", action="store_true",
                      help="Only integrity-test the given archives, don't process")

    parser.add_argument("--plan", "--dry-run", dest="plan", action="store_true",
                        help="Show what would happen without changing anything")
    parser.add_argument("--list-formats", action="store_true",
                        help="List supported formats and tool availability, then exit")
    parser.add_argument("--version", action="version", version=f"Kaelovun {VERSION}")
    return parser


# ──────────────────────────────────────────────────────────────
# Info
# ──────────────────────────────────────────────────────────────

def list_formats(config=None, logger=None):
    """Print supported formats and which archivers are available."""
    print("Supported input formats:")
    print("  Creative files:")
    print("    .psd, .psb          - Photoshop")
    print("    .ai, .eps           - Illustrator")
    print("    .indd, .indt        - InDesign")
    print("    .afphoto, .afdesign, .afpub  - Affinity")
    print("  Archives:")
    print("    .zip, .rar, .7z")
    print("    .tar, .tar.gz, .tgz, .tar.bz2, .tbz2, .tar.xz, .txz")
    print("  Directories:")
    print("    Any folder containing supported files")
    print("\nOutput formats:")
    if config is None:
        try:
            config = Config()
        except Exception:
            config = None
    if config is not None:
        from files.archive import ArchiveManager

        class _Quiet:
            def info(self, *_): pass
            warning = error = info

        status = ArchiveManager(config, logger or _Quiet()).format_status()
        notes = {"rar": "RAR5 (needs WinRAR)", "7z": "7z / LZMA2 (needs 7-Zip)",
                 "zip": "ZIP / Deflate (built in)"}
        for fmt in ("rar", "7z", "zip"):
            ok, why = status[fmt]
            print(f"  {fmt:<4} {notes[fmt]:<28} {'available' if ok else 'NOT AVAILABLE - ' + why}")
        prefs = load_prefs(config)
        print(f"  smallest  builds 7z, ZIP and RAR, keeps the smallest")
        print(f"\nCurrent default: {prefs.format}, level {prefs.level}, "
              f"solid={prefs.solid}, verify={prefs.verify}")
    else:
        print("  rar, 7z, zip, smallest")


def _fmt_size(n):
    from files.archive_backends import human_size
    return human_size(n)


# ──────────────────────────────────────────────────────────────
# Convert / verify modes
# ──────────────────────────────────────────────────────────────

def _password(args):
    if args.password:
        return args.password
    if args.ask_password:
        import getpass
        return getpass.getpass("Archive password: ")
    return None


def _progress_printer():
    tty = sys.stderr.isatty()
    last = [""]

    def show(stage, pct):
        if not tty:
            return
        text = stage if pct is None else f"{stage} {pct:3.0f}%"
        if text != last[0]:
            last[0] = text
            sys.stderr.write("\r" + text[:100].ljust(100))
            sys.stderr.flush()

    def done():
        if tty and last[0]:
            sys.stderr.write("\r" + " " * 100 + "\r")
            sys.stderr.flush()
    return show, done


def run_convert(args, config, logger) -> int:
    from pipeline.convert import ArchiveConverter, ConvertOptions

    if not args.input:
        logger.error("Nothing to convert. Give archive files or folders after --convert-to FORMAT.")
        return 1
    missing = [p for p in args.input if not Path(p).exists()]
    if missing:
        for p in missing:
            logger.error(f"Not found: {p}")
        return 1

    opts = ConvertOptions(
        target=args.convert_to,
        level=args.level,
        keep_original=args.original,
        output_dir=Path(args.output) if args.output else None,
        only_if_smaller=not args.allow_larger,
        password=_password(args),
        dry_run=args.plan,
        verify=args.verify_level,
    )
    converter = ArchiveConverter(config, logger)
    targets = converter.discover(args.input, recursive=not args.no_recursive)
    if not targets:
        logger.warning("No archives found to convert.")
        return 0
    logger.info(f"{'Planning' if args.plan else 'Converting'} {len(targets)} archive(s) to {args.convert_to}")

    show, done = _progress_printer()
    try:
        results = converter.convert_many(targets, opts, progress=show)
    except KeyboardInterrupt:
        done()
        logger.warning("Interrupted. Originals were not touched.")
        return 130
    done()

    logger.info("=" * 50)
    for r in results:
        logger.info(r.line())
    logger.info(ArchiveConverter.summarize(results))
    logger.info("=" * 50)
    return 0 if all(r.status in ("converted", "skipped", "dry-run") for r in results) else 1


def run_verify_only(args, config, logger) -> int:
    from files.archive import ArchiveManager
    from pipeline.convert import is_convertible
    import os

    if not args.input:
        logger.error("Nothing to verify. Give archive files or folders.")
        return 1
    archives = []
    for raw in args.input:
        p = Path(raw)
        if p.is_dir():
            for dp, _d, fns in os.walk(p):
                archives += [Path(dp, f) for f in sorted(fns) if is_convertible(Path(f))]
        elif p.is_file():
            archives.append(p)
        else:
            logger.error(f"Not found: {p}")
            return 1
    manager = ArchiveManager(config, logger)
    bad = 0
    for a in archives:
        ok = manager.test_archive(a, password=_password(args))
        count = len(manager.list_archive(a)) if ok else 0
        logger.info(f"{'OK  ' if ok else 'FAIL'} {a}" + (f"  ({count} files)" if ok else ""))
        bad += 0 if ok else 1
    logger.info(f"{len(archives) - bad} OK, {bad} failed")
    return 0 if bad == 0 else 1


# ──────────────────────────────────────────────────────────────
# Main entry
# ──────────────────────────────────────────────────────────────

def _apply_overrides(args, config):
    overrides = {}
    if args.format:
        overrides["format"] = args.format
    if args.level:
        overrides["level"] = args.level
    if args.verify_level:
        overrides["verify"] = args.verify_level
    if args.workspace:
        overrides["workspace_dir"] = args.workspace
    if overrides:
        config.ARCHIVE_OVERRIDES = overrides


def run_cli(args: argparse.Namespace) -> int:
    """Run CLI with parsed arguments."""
    if args.list_formats:
        list_formats()
        return 0

    try:
        config = Config()
    except ImportError:
        print("config.py not found. Run: copy config.example.py config.py")
        return 1

    if args.engine:
        config.ENGINE = args.engine
    if args.max_depth:
        config.MAX_ARCHIVE_DEPTH = args.max_depth
    _apply_overrides(args, config)

    logger = Logger(config)
    logger.info("Kaelovun CLI started.")

    # Modes that need neither Adobe nor Affinity
    if args.convert_to:
        return run_convert(args, config, logger)
    if args.verify_only:
        return run_verify_only(args, config, logger)

    # Everything below is the full pipeline.
    from pipeline.scanner import AssetScanner
    from pipeline.jobqueue import JobQueue
    from pipeline.job import Job
    from pipeline.processor import AssetProcessor
    from files.storage import StorageMonitor
    from files.preview import PreviewProcessor
    from files.archive import ArchiveManager
    from files.session import SessionManager
    from files.workspace import sweep_stale
    from adobe.photoshop import PhotoshopController
    from adobe.illustrator import IllustratorController
    from adobe.indesign import InDesignController
    from affinity.affinity import AffinityController
    from requirements_check import check_environment

    scanner = AssetScanner(config, logger)

    if args.plan:
        return run_plan(args, config, logger, scanner)

    try:
        check_environment(config, logger)
    except Exception as e:
        logger.error(f"Environment check failed: {e}")
        return 1

    sweep_stale(load_prefs(config), logger)

    storage = StorageMonitor(config, logger)
    preview = PreviewProcessor(config, logger)
    archive = ArchiveManager(config, logger)

    photoshop = PhotoshopController(config, logger)
    illustrator = IllustratorController(config, logger)
    indesign = InDesignController(config, logger)
    affinity = AffinityController(config, logger)

    processor = AssetProcessor(
        config, logger, preview, archive,
        photoshop, illustrator, storage,
        indesign=indesign,
        affinity=affinity,
    )
    if args.output:
        processor.output_dir = Path(args.output)
    processor.keep_workspace = args.no_cleanup

    queue = JobQueue(processor, logger)
    processor.should_continue = lambda: queue.running

    session = SessionManager(config, logger)
    processor.session = session
    queue.session = session

    # Handle resume-failed
    if args.resume_failed:
        sources = session.failed_jobs()
        if not sources:
            logger.info("No incomplete jobs from last session")
            return 0
        jobs = [Job(source) for source in sources]
        queue.add_jobs(jobs)
        logger.info(f"Re-queued {len(jobs)} incomplete job(s)")

    # Handle input
    elif args.input:
        total = 0
        for raw in args.input:
            input_path = Path(raw)
            if not input_path.exists():
                logger.error(f"Input not found: {input_path}")
                return 1
            jobs = scanner.scan_input(input_path)
            if not jobs:
                logger.warning(f"No processable assets found in {input_path}")
                continue
            if args.name:
                for job in jobs:
                    job.final_name = args.name
            queue.add_jobs(jobs)
            total += len(jobs)
            logger.info(f"Queued {len(jobs)} package(s) from {input_path}")
        if total == 0:
            return 0
    else:
        logger.error("No input specified. Use --help for usage.")
        return 1

    # Run queue (headless - no UI)
    logger.info("Starting headless processing...")
    queue.start()
    try:
        queue.join()
    except KeyboardInterrupt:
        logger.warning("Interrupted - finishing the current package, then stopping.")
        queue.stop()
        queue.join()

    # Print summary
    logger.info("=" * 50)
    logger.info(processor.get_summary())
    for r in processor.reports:
        logger.info(f"  {r['name']}.{r['format']}: {_fmt_size(r['source_bytes'])} -> "
                    f"{_fmt_size(r['archive_bytes'])} in {r['seconds']}s")
        for warning in r["warnings"]:
            logger.warning(f"    ! {warning}")
    logger.info("=" * 50)

    return 0 if processor._failed == 0 else 1


def run_plan(args, config, logger, scanner) -> int:
    """--plan: show what the pipeline would do. Writes nothing."""
    from files.archive_extraction import ArchiveInspector

    if not args.input:
        logger.error("Nothing to plan. Give files, folders or archives.")
        return 1
    prefs = load_prefs(config)
    inspector = ArchiveInspector(config, logger)
    logger.info(f"Plan: output format '{prefs.format}', level '{prefs.level}', "
                f"verify '{prefs.verify}'" + (f", into {args.output}" if args.output else ", next to each source"))
    count = 0
    for raw in args.input:
        p = Path(raw)
        if not p.exists():
            logger.error(f"Input not found: {p}")
            return 1
        for job in scanner.scan_input(p):
            count += 1
            src = job.source_file
            if job.is_archive:
                contents = inspector.list_contents(src)
                files = [c for c in contents if c["type"] == "file"]
                size = sum(c["size"] for c in files)
                logger.info(f"  ARCHIVE  {src.name}: {len(files)} files, {_fmt_size(size)} unpacked "
                            f"-> will be extracted, processed and rebuilt as {prefs.format}")
            elif src.is_dir():
                logger.info(f"  FOLDER   {src.name}: copied to the workspace, processed, "
                            f"rebuilt as {prefs.format}")
            else:
                logger.info(f"  FILE     {src.name}: {_fmt_size(src.stat().st_size)} "
                            f"-> preview + layers hidden, packed as {prefs.format}")
    logger.info(f"{count} package(s) would be processed. Nothing was changed.")
    return 0


def main():
    parser = create_parser()
    args = parser.parse_args()
    sys.exit(run_cli(args))


if __name__ == "__main__":
    main()
