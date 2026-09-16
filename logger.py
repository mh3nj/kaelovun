"""
logger.py

Application logging system.
"""

import logging
import sys
import threading


class Logger:

    def __init__(self, config):
        self._ui_callback = None
        self._lock = threading.Lock()

        # Filenames here are often Persian/Arabic; a cp1256 console would
        # raise UnicodeEncodeError mid-job. Degrade to ? instead of dying.
        for stream in (sys.stdout, sys.stderr):
            try:
                if stream is not None and hasattr(stream, "reconfigure"):
                    stream.reconfigure(errors="replace")
            except Exception:
                pass

        self.logger = logging.getLogger("Kaelovun")
        self.logger.setLevel(logging.INFO)
        formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

        file_handler = logging.FileHandler(config.LOG_FILE, encoding="utf-8")
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

    def set_ui_callback(self, callback):
        self._ui_callback = callback

    def info(self, message):
        self.logger.info(message)
        self._ui_log(f"INFO | {message}")

    def warning(self, message):
        self.logger.warning(message)
        self._ui_log(f"WARN | {message}")

    def error(self, message):
        self.logger.error(message)
        self._ui_log(f"ERROR | {message}")

    def _ui_log(self, text):
        if self._ui_callback:
            try:
                self._ui_callback(text)
            except Exception:
                pass
