"""
affinity.py

Unified Affinity (Canva-era) controller.

Same job contract as the Adobe controllers (open / export preview /
hide layers / save / close) but driven through Affinity's local MCP
scripting server instead of COM:

- Files are opened by launching Affinity.exe with the file path.
- Previews come from the MCP render tool (actual canvas pixels —
  no filesystem sandbox involved).
- Hide/save/close run as SDK scripts from scripts/affinity_pipeline.js.
  Those steps are best-effort by design: Affinity builds differ, so a
  failed step logs a warning and the pipeline continues with the
  original file bytes instead of failing the whole job.

The user's own Affinity instance is never quit — close() only quits
an instance this controller launched itself.
"""

import json
import subprocess
import time
from pathlib import Path

from affinity.mcp_client import MCPClient, MCPError

try:
    from affinity.popups import dismiss_affinity_popups
except ImportError:  # pragma: no cover - popup dismissal is best-effort
    def dismiss_affinity_popups(logger=None, timeout=0, poll=0.5):
        return 0


class AffinityController:

    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        self.mcp = MCPClient(config.AFFINITY_MCP_URL, logger)
        self._scripts_dir = Path(config.SCRIPTS_DIR)
        self._process = None
        self._launched_here = False
        self._ready = False
        self._files_opened = 0
        self._close_warned = False
        self._tabs_open = 0

    # ── lifecycle ──

    def start(self):
        if self._ready and self.mcp.is_reachable(timeout=2):
            return
        if not self._is_app_running():
            self.logger.info("Launching Affinity...")
            self._process = subprocess.Popen([str(self.config.AFFINITY_PATH)])
            self._launched_here = True
            time.sleep(self.config.AFFINITY_STARTUP_WAIT)
        else:
            self.logger.info("Connected to running Affinity.")
            self._launched_here = False
        # Startup blockers: the in-app updater ("update available" —
        # answer Later) and the template/welcome opener. Both appear
        # async after launch and would stall the queue, so sweep them
        # before the MCP handshake and again once ready.
        automation_mode = getattr(self.config, "NAMING_MODE", "manual") == "automation"
        try:
            dismiss_affinity_popups(logger=self.logger, timeout=6, automation_mode=automation_mode)
        except Exception:
            pass
        self._wait_for_mcp()
        try:
            self.mcp.initialize()
        except MCPError as error:
            raise RuntimeError(
                "Affinity MCP handshake failed. Enable it in Affinity → "
                f"Settings → MCP Server. ({error})"
            )
        self._ready = True
        self._log_probe()
        self.logger.info("Affinity ready.")

    def _is_app_running(self) -> bool:
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq Affinity.exe", "/FO", "CSV"],
                capture_output=True, text=True, timeout=15,
            )
            return "Affinity.exe" in result.stdout
        except Exception:
            return False

    def _wait_for_mcp(self):
        deadline = time.time() + self.config.AFFINITY_STARTUP_WAIT
        while time.time() < deadline:
            if self.mcp.is_reachable(timeout=2):
                return
            time.sleep(2)
        raise RuntimeError(
            "Affinity MCP server not reachable at "
            f"{self.config.AFFINITY_MCP_URL}. Enable it in Affinity → "
            "Settings → MCP Server, then retry."
        )

    def is_alive(self) -> bool:
        try:
            return self._is_app_running() and self.mcp.is_reachable(timeout=2)
        except Exception:
            return False

    # ── scripts ──

    def _run_script(self, function: str, argument=None):
        library = self._scripts_dir / "affinity_pipeline.js"
        if not library.exists():
            raise FileNotFoundError(f"Missing Affinity JS: {library}")
        if argument is None:
            call = f"{function}();"
        else:
            safe = str(argument).replace("\\", "/").replace('"', '\\"')
            call = f'{function}("{safe}");'
        return self.mcp.execute_script(library.read_text(encoding="utf-8") + "\n" + call)

    @staticmethod
    def _parse_result(output: str) -> dict:
        """The scripts always print one JSON line last — find it."""
        for line in reversed((output or "").splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    parsed = json.loads(line)
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    continue
        return {}

    def _log_probe(self):
        try:
            info = self._parse_result(self._run_script("aoProbe"))
            if info.get("ok"):
                self.logger.info(f"Affinity automation surface: {info}")
        except Exception:
            pass

    # ── pipeline steps ──

    def open_file(self, file: Path):
        self.start()
        self.close_all_documents()
        if self._should_recycle():
            self.restart()
        self.logger.info(f"Opening in Affinity: {file.name}")
        subprocess.Popen([str(self.config.AFFINITY_PATH), str(file)])
        # A late updater/template/PDF options popup can steal focus and stall the
        # open — sweep once before waiting for the document.
        automation_mode = getattr(self.config, "NAMING_MODE", "manual") == "automation"
        try:
            dismiss_affinity_popups(logger=self.logger, timeout=4, automation_mode=automation_mode)
        except Exception:
            pass
        self.wait_until_ready(file.name)
        self._files_opened += 1

    def _should_recycle(self) -> bool:
        """3.2.1 can't close tabs: recycle self-launched app every N files."""
        every = int(getattr(self.config, "AFFINITY_RESTART_EVERY", 0) or 0)
        return (every > 0 and self._launched_here
                and self._files_opened > 0 and self._files_opened % every == 0)

    def wait_until_ready(self, expected_name=None, timeout=None):
        timeout = timeout or self.config.DOCUMENT_TIMEOUT
        wanted = {expected_name.lower()} if expected_name else set()
        if expected_name:
            wanted.add(Path(expected_name).stem.lower())
        start = time.time()
        while True:
            try:
                info = self._parse_result(self._run_script("aoCurrentDocName"))
                current = (info.get("name") or "").lower()
                if current and (not wanted or current in wanted
                                or Path(current).stem in wanted):
                    return True
            except Exception:
                pass
            if time.time() - start > timeout:
                raise TimeoutError(
                    f"Affinity document timeout waiting for {expected_name}."
                )
            time.sleep(2)

    def export_preview(self, output: Path):
        # render_spread needs the open document's session UUID, which
        # only the SDK can tell us — fetch it first, then render.
        # Affinity caps renders at 1024px; the AVIF stage scales anyway.
        info = self._parse_result(self._run_script("aoSessionUuid"))
        session_uuid = info.get("sessionUuid")
        if not session_uuid:
            raise RuntimeError(
                f"Affinity preview failed: no session UUID "
                f"({info.get('error') or 'no open document'})."
            )
        mime, pixels = self.mcp.render_spread(session_uuid, 0)
        self.logger.info(f"Affinity rendered preview ({mime}, {len(pixels) // 1024} KB)")
        Path(output).write_bytes(pixels)

    def hide_layers(self):
        try:
            result = self._parse_result(self._run_script("aoHideVisibleLayers"))
            if result.get("ok"):
                self.logger.info(
                    "Affinity hid artwork layers "
                    f"(method={result.get('method')})."
                )
            else:
                self.logger.warning(
                    "Affinity hide-layers failed "
                    f"({result.get('error') or result.get('tried')}). "
                    "Archiving with layers as-is."
                )
        except Exception as error:
            self.logger.warning(f"Affinity hide-layers skipped: {error}")

    def save(self):
        try:
            result = self._parse_result(self._run_script("aoSave"))
            if result.get("ok"):
                self.logger.info("Affinity document saved.")
            else:
                self.logger.warning(
                    "Affinity save unsupported on this build "
                    f"({result.get('error') or result.get('tried')}). "
                    "Continuing with the file as-is."
                )
        except Exception as error:
            self.logger.warning(f"Affinity save skipped: {error}")

    def close_document(self):
        # Honest logging: 3.2.1 throws NOT_IMPLEMENTED for every close
        # path, so tabs accumulate. Warn once per queue (not per job),
        # count orphans for the end-of-queue summary, never fail the job.
        # (ASCII only here - cp1256 consoles mangle em-dashes.)
        try:
            result = self._parse_result(self._run_script("aoClose"))
            if result.get("ok") and not result.get("alreadyClosed"):
                self.logger.info("Affinity tab closed.")
                return
            if result.get("alreadyClosed"):
                self.logger.info("Affinity already had no open document.")
                return
            self._tabs_open += 1
            detail = result.get("error") or result.get("tried")
            if not self._close_warned:
                self._close_warned = True
                self.logger.warning(
                    f"Affinity cannot close tabs on this build ({detail}). "
                    "Tabs will accumulate - close them by hand for big batches. "
                    "Self-launched sessions recycle automatically "
                    f"(every {getattr(self.config, 'AFFINITY_RESTART_EVERY', 0)} files)."
                )
            else:
                self.logger.info(f"Affinity tab left open ({self._tabs_open} so far).")
        except Exception as error:
            self.logger.warning(f"Affinity close skipped: {error}")

    def close_all_documents(self):
        self.close_document()

    # ── recovery / shutdown ──

    def restart(self):
        # Only ever terminate an instance WE launched. Attached to the
        # user's own Affinity: just re-attach (no waits, no kill).
        if not self._launched_here:
            self._ready = False
            self.start()
            return
        self.logger.warning(
            f"Recycling self-launched Affinity after {self._files_opened} "
            "file(s) to clear unclosable tabs."
        )
        self.close_all_documents()
        if self._launched_here and self._process:
            try:
                self._process.terminate()
            except Exception:
                pass
            self._process = None
        self._ready = False
        time.sleep(10)
        self.start()
        time.sleep(self.config.AFFINITY_RECOVERY_WAIT)

    def close(self):
        try:
            self.close_all_documents()
        except Exception:
            pass
        if self._tabs_open:
            self.logger.warning(
                f"Affinity left {self._tabs_open} tab(s) open "
                "(3.2.1 cannot close them) - shut them by hand."
            )
        if self._launched_here and self._process:
            try:
                self._process.terminate()
                self.logger.info("Affinity closed.")
            except Exception as error:
                self.logger.warning(str(error))
        self._process = None
        self._ready = False
