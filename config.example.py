"""
config.example.py

Sanitized public copy of the app configuration — safe to push to GitHub.
This file contains no machine-specific paths.

Setup on a new machine:
    1. Copy this file to `config.py` (config.py is gitignored).
    2. Nothing else required: Adobe / Affinity / WinRAR paths are
       auto-detected from C:\\Program Files. Override any path below to
       force it, or use the in-app Settings dialog (stored machine-local
       in data/settings.json, never pushed).
"""

import glob
from pathlib import Path

from files.app_settings import AppSettings


class Config:

    def __init__(self):

        self.BASE_DIR = Path(__file__).parent
        self.DATA_DIR = self.BASE_DIR / "data"
        self.DATA_DIR.mkdir(exist_ok=True)

        self.SESSION_FILE = self.DATA_DIR / "session.json"
        self.LOG_FILE = self.DATA_DIR / "kaelovun.log"
        self.SETTINGS_FILE = self.DATA_DIR / "settings.json"

        # ── Processing engine ────────────────────
        # "adobe"    — Photoshop/Illustrator via COM (default, unchanged).
        # "affinity" — new unified Affinity (Canva-era) via its local
        #              MCP scripting server. PSD/AI/EPS open in Affinity
        #              instead of Adobe; native .afphoto/.afdesign/.afpub
        #              additionally become scannable.
        self.ENGINE = "adobe"

        self.SUPPORTED_SOURCE_EXTENSIONS = [".psd", ".ai"]
        self.SUPPORTED_AFFINITY_EXTENSIONS = [".afphoto", ".afdesign", ".afpub"]

        # ── Adobe & WinRAR paths ─────────────────────
        # Auto-detected from C:\Program Files when the configured path
        # doesn't exist. Set an exact path below to force a specific
        # version instead of the newest one found.
        self.PHOTOSHOP_PATH = self._auto_detect(
            Path(r"C:\Program Files\Adobe\Adobe Photoshop\Photoshop.exe"),
            r"C:\Program Files\Adobe\Adobe Photoshop*\Photoshop.exe",
            r"C:\Program Files (x86)\Adobe\Adobe Photoshop*\Photoshop.exe",
        )
        self.ILLUSTRATOR_PATH = self._auto_detect(
            Path(r"C:\Program Files\Adobe\Adobe Illustrator\Support Files\Contents\Windows\Illustrator.exe"),
            r"C:\Program Files\Adobe\Adobe Illustrator*\Support Files\Contents\Windows\Illustrator.exe",
            r"C:\Program Files (x86)\Adobe\Adobe Illustrator*\Support Files\Contents\Windows\Illustrator.exe",
        )
        self.WINRAR_PATH = self._auto_detect(
            Path(r"C:\Program Files\WinRAR\Rar.exe"),
            r"C:\Program Files\WinRAR\Rar.exe",
            r"C:\Program Files (x86)\WinRAR\Rar.exe",
        )
        self.WINRAR_GUI_PATH = self._auto_detect(
            Path(r"C:\Program Files\WinRAR\WinRAR.exe"),
            r"C:\Program Files\WinRAR\WinRAR.exe",
            r"C:\Program Files (x86)\WinRAR\WinRAR.exe",
        )
        # New unified Affinity (Canva-era). Classic V2 Photo/Designer
        # installs are picked up as fallbacks for opening files, but
        # only the unified app exposes the MCP scripting server.
        self.AFFINITY_PATH = self._auto_detect(
            Path(r"C:\Program Files\Affinity\Affinity\Affinity.exe"),
            r"C:\Program Files\Affinity\Affinity\Affinity.exe",
            r"C:\Program Files\WindowsApps\SerifEuropeLtd.Affinity_*Affinity.exe",
            r"C:\Program Files\WindowsApps\Canva*.Affinity_*Affinity.exe",
            r"C:\Program Files\Affinity\Photo 2\Photo.exe",
            r"C:\Program Files\Affinity\Designer 2\Designer.exe",
        )
        # Affinity's MCP server is IPv6-loopback-only ([::1]:6767).
        # Never change this to 127.0.0.1 — the server refuses IPv4.
        self.AFFINITY_MCP_HOST = "::1"
        self.AFFINITY_MCP_PORT = 6767
        self.AFFINITY_MCP_URL = self._mcp_url()
        self.AFFINITY_STARTUP_WAIT = 25
        self.AFFINITY_RECOVERY_WAIT = 20
        # 3.2.1 cannot close tabs, so they accumulate per job. When THIS
        # app launched Affinity itself, recycle it every N files to clear
        # them (0 = never). Never touches your own Affinity instance:
        # attached sessions only get a warning + end-of-queue summary.
        self.AFFINITY_RESTART_EVERY = 10

        self.PREVIEW_WIDTH = 2000
        self.PREVIEW_HEIGHT = 2000
        self.AVIF_QUALITY = 90
        self.AVIF_SPEED = 6
        self.THUMB_WIDTH = 400
        self.THUMB_HEIGHT = 400
        self.THUMB_QUALITY = 70

        # Only the drive holding the source folder is ever written to
        # (PNG/AVIF previews + final RAR live next to the source).
        # A single job needs at most ~1 GB, so requiring 10 GB was excessive.
        self.MINIMUM_FREE_SPACE_GB = 1

        self.ADOBE_STARTUP_WAIT = 20
        self.ADOBE_RECOVERY_WAIT = 20
        self.DOCUMENT_TIMEOUT = 60
        self.MAX_RETRIES = 2
        self.MAX_ARCHIVE_DEPTH = 2

        self.ARCHIVE_PROFILE = {
            "method": "best",
            "solid": True,
            "recovery": False,
            "test": True
        }

        self.THEME = "dark"

        # Locate the JSX scripts folder across all deployment layouts:
        # dev source tree, PyInstaller _internal (with datas), or a plain
        # copy next to the exe. Picks the first one that actually exists.
        self.SCRIPTS_DIR = self._find_scripts_dir()

        # Machine-local overrides from the Settings dialog win over
        # every default above. Missing/invalid values fall back silently.
        self._apply_user_settings()

    def _apply_user_settings(self):
        overrides = AppSettings(self.SETTINGS_FILE).load()
        if not overrides:
            return
        path_keys = {"PHOTOSHOP_PATH", "ILLUSTRATOR_PATH", "WINRAR_PATH",
                     "WINRAR_GUI_PATH", "AFFINITY_PATH"}
        int_keys = {"PREVIEW_WIDTH", "PREVIEW_HEIGHT", "AVIF_QUALITY",
                    "AVIF_SPEED", "THUMB_WIDTH", "THUMB_HEIGHT",
                    "THUMB_QUALITY", "MINIMUM_FREE_SPACE_GB",
                    "ADOBE_STARTUP_WAIT", "ADOBE_RECOVERY_WAIT",
                    "AFFINITY_MCP_PORT", "AFFINITY_STARTUP_WAIT",
                    "AFFINITY_RECOVERY_WAIT", "AFFINITY_RESTART_EVERY",
                    "DOCUMENT_TIMEOUT", "MAX_RETRIES", "MAX_ARCHIVE_DEPTH"}
        for key, value in overrides.items():
            if key in path_keys and isinstance(value, str) and value:
                setattr(self, key, Path(value))
            elif key == "ENGINE" and value in ("adobe", "affinity"):
                self.ENGINE = value
            elif key == "THEME" and value in ("dark", "light"):
                self.THEME = value
            elif key in int_keys:
                try:
                    setattr(self, key, int(value))
                except (TypeError, ValueError):
                    continue
            elif key == "SUPPORTED_SOURCE_EXTENSIONS" and isinstance(value, list):
                cleaned = [str(e).lower() for e in value if str(e).startswith(".")]
                if cleaned:
                    self.SUPPORTED_SOURCE_EXTENSIONS = cleaned
            elif key == "ARCHIVE_PROFILE" and isinstance(value, dict):
                self.ARCHIVE_PROFILE.update(value)
        # The MCP URL always follows the (possibly overridden) host/port.
        self.AFFINITY_MCP_URL = self._mcp_url()

    def _mcp_url(self) -> str:
        host = self.AFFINITY_MCP_HOST
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"http://{host}:{self.AFFINITY_MCP_PORT}"

    def scannable_extensions(self) -> list:
        """Extensions the scanner should pick up for the active engine."""
        exts = list(self.SUPPORTED_SOURCE_EXTENSIONS)
        if self.ENGINE == "affinity":
            for ext in self.SUPPORTED_AFFINITY_EXTENSIONS:
                if ext not in exts:
                    exts.append(ext)
        return exts

    @staticmethod
    def _auto_detect(configured: Path, *patterns: str) -> Path:
        if configured.exists():
            return configured
        matches = []
        for pattern in patterns:
            matches.extend(glob.glob(pattern))
        if matches:
            matches.sort()
            return Path(matches[-1])
        return configured

    def _find_scripts_dir(self):
        import sys
        candidates = [self.BASE_DIR / "scripts"]
        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).parent
            candidates.append(exe_dir / "_internal" / "scripts")
            candidates.append(exe_dir / "scripts")
        for candidate in candidates:
            if candidate.is_dir():
                return candidate
        return candidates[0]
