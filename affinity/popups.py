"""
popups.py

Dismiss Affinity startup blockers without user clicks:

- Updater popup ("update available" — answer Later/No/Skip/Close).
- Template / welcome / new-document opener (Close/Cancel/Escape).

Stdlib + pywin32 only (pywin32 is already a hard dependency).
All failures are silent best-effort: the pipeline must never fail
because a popup could not be dismissed.

Only windows owned by Affinity.exe (plus classic Photo.exe /
Designer.exe fallbacks) are ever touched, matched by title
keywords. Anything else on the desktop is left alone.
"""

import time

try:
    import win32api
    import win32con
    import win32gui
    import win32process
    _HAS_WIN32 = True
except ImportError:  # non-Windows dev / missing pywin32
    _HAS_WIN32 = False

_AFFINITY_EXES = {"affinity.exe", "photo.exe", "designer.exe", "publisher.exe"}

# Matched case-insensitively against the top-level window title.
_UPDATER_KEYWORDS = (
    "update available",
    "software update",
    "new version available",
    "affinity update",
    "check for updates",
)

_TEMPLATE_KEYWORDS = (
    "new document",
    "templates",
    "template",
    "welcome",
    "create new",
    "new from template",
)

_PDF_OPTIONS_KEYWORDS = (
    "pdf options",
    "import pdf",
    "open pdf",
)

# Button labels we are willing to press, in preference order.
_UPDATER_BUTTONS = (
    "later",
    "remind me later",
    "remind me",
    "skip",
    "not now",
    "no",
    "close",
    "cancel",
    "ok",
)

_TEMPLATE_BUTTONS = (
    "close",
    "cancel",
    "ok",
)

# PDF options: in automation mode, we want "Load all pages" then "OK"
_PDF_OPTIONS_BUTTONS = (
    "load all pages",
    "load pages",
    "all pages",
    "ok",
)


def _log(logger, message):
    try:
        if logger:
            logger.info(f"[affinity-popups] {message}")
    except Exception:
        pass


def _owning_exe(hwnd) -> str:
    """Lowercase exe basename owning hwnd, or '' when unknown."""
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        handle = win32api.OpenProcess(0x0400 | 0x0010, False, pid)  # QUERY_INFO | VM_READ
        try:
            path = win32process.GetModuleFileNameEx(handle, 0)
        finally:
            win32api.CloseHandle(handle)
        return (path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] or "").lower()
    except Exception:
        return ""


def _is_affinity_window(hwnd) -> bool:
    if not _HAS_WIN32:
        return False
    try:
        if not win32gui.IsWindowVisible(hwnd):
            return False
        exe = _owning_exe(hwnd)
        return exe in _AFFINITY_EXES
    except Exception:
        return False


def _classify(title: str):
    lowered = (title or "").lower()
    for keyword in _UPDATER_KEYWORDS:
        if keyword in lowered:
            return "updater"
    for keyword in _TEMPLATE_KEYWORDS:
        if keyword in lowered:
            return "template"
    for keyword in _PDF_OPTIONS_KEYWORDS:
        if keyword in lowered:
            return "pdf_options"
    return None


def _child_buttons(hwnd) -> list:
    """[(child_hwnd, text)] for direct child button-ish controls."""
    found = []

    def _enum(child, _):
        try:
            text = win32gui.GetWindowText(child) or ""
            cls = (win32gui.GetClassName(child) or "").lower()
            if text and ("button" in cls or "static" in cls or text.strip()):
                found.append((child, text))
        except Exception:
            pass
        return True

    try:
        win32gui.EnumChildWindows(hwnd, _enum, None)
    except Exception:
        pass
    return found


def _click_button(child_hwnd) -> bool:
    try:
        win32gui.SendMessage(child_hwnd, win32con.BM_CLICK, 0, 0)
        return True
    except Exception:
        return False


def _press_escape(hwnd) -> None:
    try:
        win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, win32con.VK_ESCAPE, 0)
        win32gui.PostMessage(hwnd, win32con.WM_KEYUP, win32con.VK_ESCAPE, 0)
    except Exception:
        pass


def _close_window(hwnd) -> None:
    try:
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    except Exception:
        pass


def _dismiss_once(kind: str, hwnd, logger=None, automation_mode=False) -> bool:
    """Try buttons first, fall back to Escape then WM_CLOSE."""
    if kind == "updater":
        wanted = _UPDATER_BUTTONS
    elif kind == "template":
        wanted = _TEMPLATE_BUTTONS
    elif kind == "pdf_options":
        wanted = _PDF_OPTIONS_BUTTONS if automation_mode else ()
    else:
        wanted = ()

    buttons = _child_buttons(hwnd)
    lowered = [(h, (t or "").strip().lower().replace("&", "")) for h, t in buttons]

    for label in wanted:
        for child, text in lowered:
            if text == label or (label in text and len(text) < 40):
                if _click_button(child):
                    _log(logger, f"Dismissed {kind} popup via '{text}' button.")
                    return True

    # For PDF options in automation mode, if no button found, don't force close
    # (the user might need to interact). For others, fall back.
    if kind == "pdf_options" and automation_mode:
        return False

    # No friendly button: Escape first (template dialogs honour it),
    # then a hard close. The updater treats close as "later".
    _press_escape(hwnd)
    time.sleep(0.4)
    try:
        if not win32gui.IsWindow(hwnd):
            _log(logger, f"Dismissed {kind} popup via Escape.")
            return True
    except Exception:
        return True
    _close_window(hwnd)
    _log(logger, f"Closed {kind} popup window.")
    return True


def dismiss_affinity_popups_once(logger=None, automation_mode=False) -> int:
    """Single sweep over Affinity-owned popups. Returns dismissals."""
    if not _HAS_WIN32:
        return 0
    targets = []
    try:
        def _enum(hwnd, _):
            try:
                title = win32gui.GetWindowText(hwnd) or ""
                if not title.strip():
                    return True
                kind = _classify(title)
                if kind and _is_affinity_window(hwnd):
                    targets.append((kind, hwnd, title))
            except Exception:
                pass
            return True

        win32gui.EnumWindows(_enum, None)
    except Exception:
        return 0

    dismissed = 0
    for kind, hwnd, title in targets:
        try:
            if _dismiss_once(kind, hwnd, logger=logger, automation_mode=automation_mode):
                dismissed += 1
        except Exception:
            continue
    return dismissed


def dismiss_affinity_popups(logger=None, timeout=8, poll=0.5, automation_mode=False) -> int:
    """Sweep for up to `timeout` seconds (popups appear async)."""
    if not _HAS_WIN32:
        return 0
    deadline = time.time() + max(0, timeout)
    total = 0
    while time.time() < deadline:
        total += dismiss_affinity_popups_once(logger=logger, automation_mode=automation_mode)
        time.sleep(poll)
    return total
