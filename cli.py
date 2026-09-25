"""
cli.py

Command-line interface for headless Kaelovun operation.
"""

import sys
import argparse
from pathlib import Path

from config import Config
from logger import Logger

from pipeline.scanner import AssetScanner
from pipeline.queue import JobQueue
from pipeline.job import Job

from files.storage import StorageMonitor
from files.preview import PreviewProcessor
from files.archive import RarArchive

from adobe.photoshop import PhotoshopController
from adobe.illustrator import IllustratorController
from adobe.indesign import InDesignController
from affinity.affinity import AffinityController

from pipeline.processor import AssetProcessor

from files.session import SessionManager

from requirements_check import check_environment


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Kaelovun - Creative Asset Processing and Preservation Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  kaelovun-cli /path/to/project.psd
  kaelovun-cli /path/to/project_folder
  kaelovun-cli /path/to/archive.zip
  kaelovun-cli --resume-failed
  kaelovun-cli --engine affinity /path/to/file.afphoto
        """
    )

    parser.add_argument(
        "input",
        nargs="?",
        help="Input file, directory, or archive to process"
    )

    parser.add_argument(
        "--engine",
        choices=["adobe", "affinity"],
        help="Processing engine to use (overrides config)"
    )

    parser.add_argument(
        "--output",
        "-o",
        help="Output directory for archives (default: next to source)"
    )

    parser.add_argument(
        "--resume-failed",
        action="store_true",
        help="Resume incomplete jobs from last session"
    )

    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Keep workspace files after processing (for debugging)"
    )

    parser.add_argument(
        "--max-depth",
        type=int,
        help="Maximum archive extraction depth (default: 2)"
    )

    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify existing archives, don't process"
    )

    parser.add_argument(
        "--list-formats",
        action="store_true",
        help="List supported input formats and exit"
    )

    parser.add_argument(
        "--version",
        action="version",
        version="Kaelovun 1.4.0"
    )

    return parser


def list_formats():
    """Print supported formats."""
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
    print("\nOutput:")
    print("  .rar (RAR5, best compression, solid, verified)")


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

    # Override config from CLI args
    if args.engine:
        config.ENGINE = args.engine
    if args.max_depth:
        config.MAX_ARCHIVE_DEPTH = args.max_depth

    logger = Logger(config)
    logger.info("Kaelovun CLI started.")

    try:
        check_environment(config, logger)
    except Exception as e:
        logger.error(f"Environment check failed: {e}")
        return 1

    storage = StorageMonitor(config, logger)
    preview = PreviewProcessor(config, logger)
    archive = RarArchive(config, logger)

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

    queue = JobQueue(processor, logger)
    processor.should_continue = lambda: queue.running

    scanner = AssetScanner(config, logger)

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
        input_path = Path(args.input)
        if not input_path.exists():
            logger.error(f"Input not found: {input_path}")
            return 1

        jobs = scanner.scan_input(input_path)
        if not jobs:
            logger.warning("No processable assets found")
            return 0

        queue.add_jobs(jobs)
        logger.info(f"Queued {len(jobs)} package(s) from {input_path}")

    else:
        logger.error("No input specified. Use --help for usage.")
        return 1

    # Run queue (headless - no UI)
    logger.info("Starting headless processing...")
    queue.start()

    # Wait for completion
    while queue.running or queue.paused:
        import time
        time.sleep(1)

    # Print summary
    logger.info("=" * 50)
    logger.info(processor.get_summary())
    logger.info("=" * 50)

    # Close applications
    try:
        processor.photoshop.close()
    except Exception:
        pass
    try:
        processor.illustrator.close()
    except Exception:
        pass
    try:
        indesign = getattr(processor, "indesign", None)
        if indesign:
            indesign.close()
    except Exception:
        pass
    try:
        affinity = getattr(processor, "affinity", None)
        if affinity:
            affinity.close()
    except Exception:
        pass

    return 0 if processor._failed == 0 else 1


def main():
    parser = create_parser()
    args = parser.parse_args()
    sys.exit(run_cli(args))


if __name__ == "__main__":
    main()