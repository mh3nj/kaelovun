"""
archive_prefs.py

One place that answers "how should archives be built and handled right now?".

Preferences are resolved on every call, in this order (later wins):

    built-in defaults
      -> config.ARCHIVE_PROFILE (legacy keys like "method"/"solid" still work)
      -> data/settings.json     (what the Settings dialog saves)
      -> config.ARCHIVE_OVERRIDES (one-run overrides, e.g. command-line flags)

Reading settings.json directly (instead of relying on Config to copy values
over) means new settings keep working even if your local, gitignored
config.py predates them, and changes made in Settings apply to the very next
archive with no restart.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from files.app_settings import AppSettings

FORMATS = ("rar", "7z", "zip", "smallest")
LEVELS = ("fast", "normal", "best")
SOLID_MODES = ("solid", "type", "off")
VERIFY_LEVELS = ("standard", "paranoid")
DICT_SIZES_MB = (16, 32, 64, 128, 256, 512, 1024)

DEFAULT_PROFILE = {
    # What to build
    "format": "rar",            # rar | 7z | zip | smallest (build 7z + ZIP + RAR, keep the smallest)
    "level": "best",            # fast | normal | best
    "solid": "solid",           # solid | type (solid per file type) | off
    "dict_mb": 64,              # LZMA2 / RAR dictionary. RAM use is roughly 10x for 7z at "best".
    "recovery_pct": 0,          # RAR only: recovery record, % of archive size
    "store_precompressed": True,  # RAR only: store AVIF/JPG/MP4/... instead of recompressing
    "threads": 0,               # 0 = let the tool decide
    # How hard to check it
    "test": True,               # run the archiver's own integrity test
    "verify": "standard",       # standard = names + sizes | paranoid = also CRC32 of every file
    # Extras
    "write_sidecar": False,     # write <archive>.kaelovun.json next to each archive
    "export_previews": True,    # also save <name>.avif + <name>.thumb.avif next to the archive (Evoury reads these)
    # Safety limits applied to every archive Kaelovun reads
    "max_extract_gb": 200,      # refuse archives that claim to unpack to more than this
    "max_ratio": 300,           # refuse unpack:archive ratios above this ...
    "ratio_floor_mb": 512,      # ... but only once more than this much has been unpacked
    "max_files": 250_000,       # refuse archives with more entries than this
}

# Extensions RAR should store instead of trying to recompress.
PRECOMPRESSED_TYPES = (
    "avif", "webp", "jpg", "jpeg", "png", "heic", "gif",
    "mp4", "mov", "mkv", "webm", "mp3", "aac", "flac", "ogg",
    "zip", "rar", "7z", "gz", "bz2", "xz", "woff2",
)


@dataclass
class ArchivePrefs:
    format: str = "rar"
    level: str = "best"
    solid: str = "solid"
    dict_mb: int = 64
    recovery_pct: int = 0
    store_precompressed: bool = True
    threads: int = 0
    test: bool = True
    verify: str = "standard"
    write_sidecar: bool = False
    export_previews: bool = True
    max_extract_gb: float = 200
    max_ratio: float = 300
    ratio_floor_mb: float = 512
    max_files: int = 250_000

    sevenzip_path: Optional[Path] = None
    rar_path: Optional[Path] = None
    rar_gui_path: Optional[Path] = None
    workspace_dir: Optional[Path] = None

    extra: dict = field(default_factory=dict)

    @property
    def max_extract_bytes(self) -> int:
        return int(self.max_extract_gb * (1024 ** 3))

    @property
    def ratio_floor_bytes(self) -> int:
        return int(self.ratio_floor_mb * (1024 ** 2))


def _coerce_choice(value, allowed, default):
    if isinstance(value, str) and value.lower() in allowed:
        return value.lower()
    return default


def _coerce_int(value, default, lo, hi):
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, number))


def _coerce_float(value, default, lo, hi):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, number))


def _coerce_bool(value, default):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return default


def _legacy_to_new(profile: dict) -> dict:
    """Translate the original ARCHIVE_PROFILE keys to the current ones."""
    out = dict(profile)
    if "method" in out and "level" not in out:
        out["level"] = {"best": "best", "normal": "normal", "fast": "fast"}.get(
            str(out["method"]).lower(), "best")
    if isinstance(out.get("solid"), bool):
        out["solid"] = "solid" if out["solid"] else "off"
    if isinstance(out.get("recovery"), bool) and "recovery_pct" not in out:
        out["recovery_pct"] = 3 if out["recovery"] else 0
    return out


def _as_path(value) -> Optional[Path]:
    if isinstance(value, Path):
        return value
    if isinstance(value, str) and value.strip():
        return Path(value.strip())
    return None


def load_prefs(config, settings: Optional[dict] = None) -> ArchivePrefs:
    """Resolve the current archive preferences for ``config``."""
    merged = dict(DEFAULT_PROFILE)

    legacy = getattr(config, "ARCHIVE_PROFILE", None)
    if isinstance(legacy, dict):
        merged.update(_legacy_to_new(legacy))

    stored = settings
    if stored is None:
        settings_file = getattr(config, "SETTINGS_FILE", None)
        stored = AppSettings(settings_file).load() if settings_file else {}
    stored_profile = stored.get("ARCHIVE_PROFILE")
    if isinstance(stored_profile, dict):
        merged.update(_legacy_to_new(stored_profile))

    overrides = getattr(config, "ARCHIVE_OVERRIDES", None)
    if isinstance(overrides, dict):
        merged.update(_legacy_to_new({k: v for k, v in overrides.items() if k in DEFAULT_PROFILE or k in ("method", "recovery")}))

    prefs = ArchivePrefs(
        format=_coerce_choice(merged["format"], FORMATS, "rar"),
        level=_coerce_choice(merged["level"], LEVELS, "best"),
        solid=_coerce_choice(merged["solid"], SOLID_MODES, "solid"),
        dict_mb=_coerce_int(merged["dict_mb"], 64, 1, 1024),
        recovery_pct=_coerce_int(merged["recovery_pct"], 0, 0, 10),
        store_precompressed=_coerce_bool(merged["store_precompressed"], True),
        threads=_coerce_int(merged["threads"], 0, 0, 64),
        test=_coerce_bool(merged["test"], True),
        verify=_coerce_choice(merged["verify"], VERIFY_LEVELS, "standard"),
        write_sidecar=_coerce_bool(merged["write_sidecar"], False),
        export_previews=_coerce_bool(merged["export_previews"], True),
        max_extract_gb=_coerce_float(merged["max_extract_gb"], 200, 0.001, 100_000),
        max_ratio=_coerce_float(merged["max_ratio"], 300, 2, 1_000_000),
        ratio_floor_mb=_coerce_float(merged["ratio_floor_mb"], 512, 1, 1_000_000),
        max_files=_coerce_int(merged["max_files"], 250_000, 1, 100_000_000),
    )

    prefs.sevenzip_path = (
        _as_path(stored.get("SEVENZIP_PATH"))
        or _as_path(getattr(config, "SEVENZIP_PATH", None))
    )
    prefs.rar_path = _as_path(getattr(config, "WINRAR_PATH", None))
    prefs.rar_gui_path = _as_path(getattr(config, "WINRAR_GUI_PATH", None))
    prefs.workspace_dir = (
        _as_path((overrides or {}).get("workspace_dir") if isinstance(overrides, dict) else None)
        or _as_path(stored.get("WORKSPACE_DIR"))
        or _as_path(getattr(config, "WORKSPACE_DIR", None))
    )
    return prefs
