"""
app_settings.py

Machine-local user overrides persisted to data/settings.json.

Config ships the defaults. Anything changed in the Settings dialog
lands here, so reinstalls and rebuilds never wipe it. data/ is
gitignored, so this file never reaches GitHub.
"""

import json
from pathlib import Path


class AppSettings:

    # Keys the Settings dialog (and Config) may persist. Anything else
    # found in settings.json is ignored on load and dropped on save,
    # so hand-edited junk can never break startup.
    KNOWN_KEYS = (
        "ENGINE",
        "PHOTOSHOP_PATH",
        "ILLUSTRATOR_PATH",
        "WINRAR_PATH",
        "AFFINITY_PATH",
        "AFFINITY_MCP_PORT",
        "AFFINITY_STARTUP_WAIT",
        "AFFINITY_RECOVERY_WAIT",
        "SUPPORTED_SOURCE_EXTENSIONS",
        "PREVIEW_WIDTH",
        "PREVIEW_HEIGHT",
        "PREVIEW_FORMAT",
        "AVIF_QUALITY",
        "AVIF_SPEED",
        "THUMB_WIDTH",
        "THUMB_HEIGHT",
        "THUMB_FORMAT",
        "THUMB_QUALITY",
        "MINIMUM_FREE_SPACE_GB",
        "ADOBE_STARTUP_WAIT",
        "ADOBE_RECOVERY_WAIT",
        "DOCUMENT_TIMEOUT",
        "MAX_RETRIES",
        "ARCHIVE_PROFILE",
        "THEME",
        "NAMING_MODE",
    )

    def __init__(self, settings_file):
        self.settings_file = Path(settings_file)

    def load(self) -> dict:
        """Return stored overrides filtered to known keys ({} if none)."""
        try:
            raw = json.loads(self.settings_file.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {k: v for k, v in raw.items() if k in self.KNOWN_KEYS}

    def save(self, values: dict) -> dict:
        """Persist known keys only. Returns what was actually written."""
        clean = {k: v for k, v in values.items() if k in self.KNOWN_KEYS}
        self.settings_file.parent.mkdir(parents=True, exist_ok=True)
        self.settings_file.write_text(
            json.dumps(clean, indent=4, ensure_ascii=False), encoding="utf-8"
        )
        return clean

    def get(self, key, default=None):
        return self.load().get(key, default)

    def set(self, key, value):
        if key not in self.KNOWN_KEYS:
            raise KeyError(f"Unknown settings key: {key}")
        current = self.load()
        current[key] = value
        self.save(current)
