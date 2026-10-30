"""
themes.py

Loads the mh3nj VS Code color themes (assets/themes/*.json) and maps them
onto the flat color roles Kaelovun's tkinter widgets use. Every widget in the
app reads from this dict, so a theme is just a set of role -> color entries.

Theme ids are the JSON file stems ("anar-dark", "baran-light", ...). Each
theme carries its VS Code "type" (dark/light), which picks the header logo.
"""

import json
import sys
from pathlib import Path

# VS Code color key -> Kaelovun role. First match wins.
_ROLE_SOURCES = {
    "bg": ("editor.background", "sideBar.background", "activityBar.background"),
    "frame_bg": ("sideBar.background", "editor.background", "activityBar.background"),
    "fg": ("editor.foreground", "sideBar.foreground", "foreground"),
    "entry_bg": ("input.background", "editor.background", "sideBar.background"),
    "entry_fg": ("input.foreground", "editor.foreground", "foreground"),
    "button_bg": ("button.background", "activityBarBadge.background", "badge.background"),
    "button_fg": ("button.foreground", "activityBarBadge.foreground", "editor.foreground"),
    "preview_bg": ("editorGutter.background", "editor.background"),
    "log_bg": ("terminal.background", "panel.background", "editor.background"),
    "log_fg": ("terminal.foreground", "editor.foreground", "foreground"),
    "select_bg": ("list.activeSelectionBackground", "selection.background", "input.background"),
}

# What a role falls back to when the theme does not define it at all.
_FALLBACKS = {
    "bg": "#2b2b2b",
    "frame_bg": "#2b2b2b",
    "fg": "#ffffff",
    "entry_bg": "#3c3c3c",
    "entry_fg": "#ffffff",
    "button_bg": "#4a4a4a",
    "button_fg": "#ffffff",
    "preview_bg": "#1e1e1e",
    "log_bg": "#1e1e1e",
    "log_fg": "#cccccc",
    "select_bg": "#3c3c3c",
}


def _hex6(value: str) -> str:
    """VS Code themes use #RRGGBB or #RRGGBBAA; tkinter wants #RRGGBB."""
    value = str(value).strip()
    if value.startswith("#") and len(value) >= 7:
        return value[:7]
    return value


def _pretty(theme_id: str) -> str:
    return theme_id.replace("-", " ").title()


def _theme_dirs():
    base = Path(__file__).resolve().parent.parent
    candidates = [base / "assets" / "themes"]
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        candidates += [exe_dir / "_internal" / "assets" / "themes",
                       exe_dir / "assets" / "themes"]
    return candidates


def load_themes() -> dict:
    """{theme_id: {name, type, bg, fg, ...}} from every *.json in the themes dir."""
    themes = {}
    for folder in _theme_dirs():
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            colors = raw.get("colors") if isinstance(raw, dict) else None
            if not isinstance(colors, dict):
                continue
            theme_id = path.stem
            roles = {"name": str(raw.get("name") or _pretty(theme_id)),
                     "type": "light" if raw.get("type") == "light" else "dark"}
            for role, sources in _ROLE_SOURCES.items():
                value = next((colors[k] for k in sources if isinstance(colors.get(k), str)), None)
                roles[role] = _hex6(value) if value else _FALLBACKS[role]
            themes[theme_id] = roles
    if not themes:
        themes["dark"] = {"name": "Dark", "type": "dark", **_FALLBACKS}
    return themes


THEMES = load_themes()
