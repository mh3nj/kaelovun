"""
requirements_check.py

Verify environment before starting. Warns about anything missing rather
than blocking startup entirely — someone batch-processing only PSDs today
shouldn't be locked out because Illustrator's path changed after an update.
The one hard requirement is an archiver able to build the chosen output format:
WinRAR for RAR, 7-Zip for 7z, nothing for ZIP ("smallest" needs at least one).
"""

from files.archive import ArchiveManager
from files.archive_prefs import load_prefs


def check_environment(config, logger=None):
    warn = logger.warning if logger else print
    missing = []
    _check_archiver(config, logger)
    engine = getattr(config, "ENGINE", "adobe")
    if engine == "affinity":
        affinity = getattr(config, "AFFINITY_PATH", None)
        if not affinity or not affinity.exists():
            missing.append(f"Affinity (engine is 'affinity' but not found at {affinity})")
        elif not _mcp_reachable(config):
            missing.append(
                "Affinity MCP server is not answering at "
                f"{config.AFFINITY_MCP_URL} — open Affinity and enable "
                "Settings → MCP Server (jobs will fail until then)"
            )
    else:
        if not config.PHOTOSHOP_PATH.exists():
            missing.append("Photoshop (PSD files will fail until this is fixed)")
        if not config.ILLUSTRATOR_PATH.exists():
            missing.append("Illustrator (AI/EPS files will fail until this is fixed)")
    if missing:
        for item in missing:
            warn(item)
    return True


def _check_archiver(config, logger=None):
    """Fail early (with an actionable message) if the chosen output format can't be built."""
    prefs = load_prefs(config)

    class _Quiet:
        def info(self, *_): pass
        warning = error = info

    status = ArchiveManager(config, logger or _Quiet()).format_status()
    wanted = prefs.format
    if wanted == "smallest":
        if not (status["7z"][0] or status["rar"][0]):
            raise RuntimeError("Output format is 'smallest' but neither 7-Zip nor WinRAR was found. "
                               + status["7z"][1])
        return
    ok, why = status[wanted]
    if not ok:
        others = [f for f in ("7z", "zip", "rar") if f != wanted and status[f][0]]
        hint = (f" You can switch the output format to {' or '.join(others)} in Settings > Archive."
                if others else "")
        raise RuntimeError(f"Output format is '{wanted}' but it can't be built: {why}{hint}")


def _mcp_reachable(config) -> bool:
    """Light TCP probe of the Affinity MCP port — no deps, no handshake."""
    import socket
    host = getattr(config, "AFFINITY_MCP_HOST", "127.0.0.1")
    port = int(getattr(config, "AFFINITY_MCP_PORT", 6767))
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False
