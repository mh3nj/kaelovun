"""
indesign.py

Persistent InDesign controller.
Opens INDD/INDT files, exports previews, hides layers, saves.
"""

from pathlib import Path
import time
import subprocess

import win32com.client
from adobe.jsx_bridge import JSXBridge


class InDesignController:

    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        self.app = None
        self.jsx = JSXBridge(config.SCRIPTS_DIR, logger)

    def start(self):
        if self.app:
            return
        self.logger.info("Starting InDesign...")
        try:
            self.app = win32com.client.Dispatch("InDesign.Application")
        except Exception:
            # Try to find InDesign path
            import glob
            indesign_paths = glob.glob(r"C:\Program Files\Adobe\Adobe InDesign *\InDesign.exe")
            if indesign_paths:
                subprocess.Popen([indesign_paths[-1]])
                time.sleep(self.config.ADOBE_STARTUP_WAIT)
                self.app = win32com.client.Dispatch("InDesign.Application")
            else:
                raise RuntimeError("InDesign not found. Install InDesign or set path in config.")
        self.logger.info("InDesign ready.")

    def open_file(self, file: Path):
        self.start()
        self.close_all_documents()
        self.logger.info(f"Opening in InDesign: {file.name}")
        self.app.Open(str(file))
        self.wait_until_ready(file.name)

    def wait_until_ready(self, expected_name=None, timeout=60):
        start = time.time()
        while True:
            try:
                if self.app.Documents.Count > 0:
                    if expected_name:
                        doc = self.app.ActiveDocument
                        if doc and doc.Name.lower() == expected_name.lower():
                            return True
                    else:
                        return True
            except Exception:
                pass
            if time.time() - start > timeout:
                raise TimeoutError("InDesign document timeout.")
            time.sleep(1)

    def execute(self, script: str):
        self.app.DoScript(script, win32com.client.constants.idJavascript)

    def _run_script(self, function: str, argument=None):
        script = self.jsx.build_call(function, argument)
        full = self.jsx.load_script("indesign_export.jsx") + "\n" + script
        self.execute(full)

    def export_preview(self, output: Path):
        self._run_script("exportPreview", output)

    def hide_layers(self):
        self._run_script("hideVisibleLayers")

    def save(self):
        self.app.ActiveDocument.Save()

    def close_document(self):
        try:
            self.app.ActiveDocument.Close(win32com.client.constants.idYes)
            self.logger.info("INDD tab closed.")
        except Exception as error:
            self.logger.warning(str(error))

    def close_all_documents(self):
        try:
            while self.app.Documents.Count > 0:
                doc = self.app.Documents.Item(1)
                doc.Close(win32com.client.constants.idYes)
        except Exception:
            pass

    def restart(self):
        self.logger.warning("Restarting InDesign.")
        self.close_all_documents()
        try:
            self.app.Quit()
        except Exception:
            pass
        self.app = None
        time.sleep(10)
        self.start()
        time.sleep(self.config.ADOBE_RECOVERY_WAIT)

    def close(self):
        if not self.app:
            return
        try:
            self.close_all_documents()
            self.app.Quit()
            self.app = None
            self.logger.info("InDesign closed.")
        except Exception as error:
            self.logger.warning(str(error))