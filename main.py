"""
main.py

Application entry point.
"""

from config import Config
from logger import Logger

from pipeline.scanner import AssetScanner
from pipeline.queue import JobQueue

from files.storage import StorageMonitor
from files.preview import PreviewProcessor
from files.archive import RarArchive

from adobe.photoshop import PhotoshopController
from adobe.illustrator import IllustratorController
from adobe.indesign import InDesignController
from affinity.affinity import AffinityController

from pipeline.processor import AssetProcessor

from files.session import SessionManager

from ui.app import ApplicationUI

from requirements_check import check_environment

try:
    from config import Config
except ImportError:
    print(
        "config.py not found.\n"
        "First-time setup: copy config.example.py to config.py "
        "(paths are auto-detected, no edits needed)."
    )
    raise SystemExit(1)


def main():

    config = Config()
    logger = Logger(config)
    logger.info("Kaelovun started.")

    check_environment(config, logger)

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

    app = ApplicationUI(config, logger, scanner, queue, session=session)

    logger.set_ui_callback(app.log)

    logger.info("Application ready.")
    app.run()


if __name__ == "__main__":
    main()
