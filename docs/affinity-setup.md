# Affinity engine setup

Use the new unified **Affinity** (Canva-era, with `Affinity.exe` and a
`Settings → MCP Server` toggle) instead of Photoshop/Illustrator to
open PSD, AI, and EPS files — plus native `.afphoto`, `.afdesign`,
and `.afpub` files.

Classic Affinity V2 (separate Photo/Designer/Publisher apps) has no
scripting API and can only open files, not drive the pipeline. The
steps below apply to the unified app only.

---

## 1. Enable the scripting server

1. Open Affinity.
2. Go to **Settings → MCP Server** and turn it **on**.
3. Enable the **FileSystem** permission (scripts need it).
4. Keep Affinity open, or let Kaelovun launch it — either works.
   Your own open Affinity is never quit by the app.

## 2. Switch the engine

1. Launch Kaelovun.
2. Click **⚙ Settings → Engine → Affinity**.
3. Click **Test Affinity connection** — you want `reachable ✓`.
4. Click **Save**. The status bar now reads `Ready (Affinity)`.

No restart, no `config.py` editing. The choice is stored machine-local
in `data/settings.json` (gitignored, never pushed).

## 3. How each stage works under Affinity

Verified live against Affinity 3.2.1 (Windows):

| # | Stage | Adobe | Affinity |
|---|-------|-------|----------|
| 1 | Open | COM `Open()` | `Affinity.exe <file>` launch |
| 2 | Export PNG | ExtendScript render | MCP `render_spread` of the live canvas (JPEG, max 1024px) |
| 3 | Convert AVIF | same | same (1024px source is plenty for naming + thumbnails) |
| 4 | Name prompt | same | same |
| 5 | Hide layers | ExtendScript | SDK `selectAll()` + `hideSelection()` — artwork hides, locked background stays |
| 6 | Save | COM `Save()` | ❌ PSD imports can't save back (`SAVE_TO_TEMPORARY_ARCHIVE_ERROR`); job continues with original bytes |
| 7 | Close tab | COM `Close(2)` | ❌ `NOT_IMPLEMENTED` in 3.2.1 (Canva's own SDK tests note "waiting for close to be fixed"); tabs accumulate |
| 8–11 | Rename/Archive/Verify/Cleanup | same | same |

Connection details that cost us a debugging session, so you never repeat it:

- The MCP server is **IPv6-loopback-only**: `http://[::1]:6767`. `127.0.0.1:6767` refuses — this is Affinity, not your firewall or VPN.
- There is **no `/mcp` endpoint** (Streamable HTTP 404s). The client uses legacy SSE: `GET /sse` → session → `initialize` → preamble → tools. All handled automatically.
- The server requires the **`preamble` doc read** before `execute_script` works — also automatic.
- `render_spread` needs the open document's **`sessionUuid`** (from `doc.sessionUuid`), plus zero-based `spread_index`.
- Verify with: `Get-NetTCPConnection -LocalPort 6767` should show `::1 LISTENING` owned by Affinity.

---

## Known limitations

- **Tabs accumulate (your instance).** Nothing can close documents in 3.2.1. If Kaelovun launched Affinity itself, it recycles the app every `AFFINITY_RESTART_EVERY` files (default 10) to clear them — verified: relaunch comes back clean, no recovery prompts. If you opened Affinity yourself, it never quits it for you: split big batches and close tabs by hand. The queue-end log tells you how many tabs were left behind.
- **Archives hold the original bytes.** Hide happens in memory but PSDs can't save back, so the RAR contains the file as it was (layers visible). For `.afphoto`/`.afdesign` saves may succeed — watch the log.
- **Renders are max 1024px.** Affinity caps `render_spread`. Fine for naming/AVIFs, not a full-res export.
- **Adobe file fidelity.** Affinity opens PSD/AI but may rasterize or
  approximate exotic effects, smart objects, and artboards. Check the
  preview before confirming the name — that is what gets archived.
- **MCP must stay on.** If Affinity is closed or the server is off,
  startup warns and Affinity jobs fail with a message telling you
  exactly that. Adobe jobs are unaffected.
- **One document at a time**, same as Adobe. The controller closes
  the previous document before opening the next.

---

## Hardening the scripts for your exact build

The SDK reference lives inside your running Affinity. To pin the
scripts to your build's exact API:

1. Point an MCP inspector at `http://127.0.0.1:6767/sse`.
2. Call `read_sdk_documentation_topic` for the documents/layers
   topics and note the exact save/close/visibility calls.
3. Update the strategy lists in `scripts/affinity_pipeline.js`
   (`aoSave`, `aoClose`, `aoHideVisibleLayers`).
4. Rebuild the exe (scripts ship inside it — always build from
   `Kaelovun.spec`).

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `MCP server not reachable` at startup | Check `Get-NetTCPConnection -LocalPort 6767` shows `::1 LISTENING` — if not, open Affinity + enable Settings → MCP Server (VPN is not the cause: loopback bypasses it) |
| `NOT_ALLOWED` in the log | Enable the FileSystem permission under MCP Server settings |
| `Affinity document timeout` | File may need conversion on open — open it once manually first |
| Preview looks different from Adobe's | Expected — Affinity's PSD/AI import is an approximation |
| `Affinity hide-layers unsupported` warning | Cosmetic — archive keeps layers; see hardening above |
