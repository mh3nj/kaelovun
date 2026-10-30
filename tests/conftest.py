"""
Shared pytest setup.

Kaelovun's Adobe/Affinity controllers import pywin32 modules at import time.
On machines without pywin32 (Linux/macOS dev boxes, CI) we install light
stand-ins so the pure-Python parts of the pipeline stay testable.
Real Windows runs are unaffected: the stubs are only used if the import fails.
"""

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

# Make the project root importable no matter where pytest is launched from.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _install_pywin32_stubs():
    try:
        import win32com.client  # noqa: F401
        return
    except ImportError:
        pass

    win32com = types.ModuleType("win32com")
    client = types.ModuleType("win32com.client")
    client.Dispatch = MagicMock(name="Dispatch")
    client.GetActiveObject = MagicMock(name="GetActiveObject")
    client.constants = MagicMock(name="constants")
    win32com.client = client

    pywintypes = types.ModuleType("pywintypes")

    class com_error(Exception):
        pass

    pywintypes.com_error = com_error

    sys.modules.setdefault("win32com", win32com)
    sys.modules.setdefault("win32com.client", client)
    sys.modules.setdefault("pywintypes", pywintypes)


_install_pywin32_stubs()


# ──────────────────────────────────────────────────────────────
# Shared fixtures
# ──────────────────────────────────────────────────────────────
import shutil as _shutil

import pytest


class RecordingLogger:
    def __init__(self):
        self.messages = []

    def info(self, msg):
        self.messages.append(("info", str(msg)))

    def warning(self, msg):
        self.messages.append(("warning", str(msg)))

    def error(self, msg):
        self.messages.append(("error", str(msg)))

    def text(self, level=None):
        return "\n".join(m for lvl, m in self.messages if level in (None, lvl))


class FakeConfig:
    """Minimal Config stand-in. Everything archive-related is resolved from here."""

    def __init__(self, tmp_path, **overrides):
        self.SETTINGS_FILE = Path(tmp_path) / "settings.json"
        self.MAX_ARCHIVE_DEPTH = 2
        self.MAX_RETRIES = 2
        self.MINIMUM_FREE_SPACE_GB = 0
        self.NAMING_MODE = "automation"
        self.ENGINE = "adobe"
        self.ARCHIVE_OVERRIDES = {"workspace_dir": str(Path(tmp_path) / "ws")}
        self.ARCHIVE_OVERRIDES.update(overrides)


@pytest.fixture
def logger():
    return RecordingLogger()


@pytest.fixture
def config(tmp_path):
    return FakeConfig(tmp_path)


have_7z = _shutil.which("7z") is not None or _shutil.which("7zz") is not None
needs_7z = pytest.mark.skipif(not have_7z, reason="7-Zip (7z) is not installed")
