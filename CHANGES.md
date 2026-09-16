# Kaelovun (formerly Asset Organizer) — audit & fixes, batch 5

Drop these 9 files into Kaelovun's root, same names.

Same approach as Evoury: read the actual code end to end before touching
anything, rather than guessing at what "needs recoding." Found six real
issues, all fixed.

## The headline one: EPS was never actually wired in anywhere

You were clear that PSD, AI, and EPS are the three formats that matter.
PSD and AI worked. EPS didn't — not because of some edge case, but because
**`scanner.py` never even looked for `.eps` files in the first place**
(`if extension in (".psd", ".ai"):`). Even if one had been found, every
routing point in `processor.py` — open, export preview, hide layers, save,
close, error-recovery restart — only recognized `.psd` or `.ai`, so it
would have hit `raise RuntimeError("Unsupported asset")` immediately.

The fix is low-risk: Illustrator opens/exports/saves EPS through the exact
same COM calls and JSX as AI (there's no format-specific logic in
`illustrator.py` at all), so EPS now just rides the same path AI already
uses at all six routing points. One honest caveat I can't verify without
testing: Illustrator's `Save()` on an EPS can sometimes prompt for EPS
export options depending on version/settings, unlike AI's silent save —
worth watching the first time an EPS goes through the queue.

## Session data was being saved but never read back

`SessionManager.save()` writes a full `session.json` after every single
job. `SessionManager.load()` reads it back. Grepped the whole codebase —
`load()` was never called from anywhere. All that state was write-only.

Added `failed_jobs()` — reads the last session, finds entries that didn't
reach "done", and returns the ones whose source file is still on disk (a
job only gets renamed after it fully succeeds, so an incomplete job's
source is always still sitting at its original path). Added a **"Resume
Failed" button** next to Select Folder in the UI that re-queues those from
scratch — matches your pipeline's own design ("always render fresh from
Adobe"), so this isn't fragile step-by-step resume, just "don't lose track
of what didn't finish."

## A narrow data-loss window in error handling

`processor.py`'s `handle_error()` was calling `session.save([job])` — just
that one job, not the full list — while `queue.py`'s worker loop *also*
saves the full job list in its `finally` block right after. In normal
operation the second save overwrites the first, so it self-corrects — but
if the app got killed in the gap between those two writes, `session.json`
would be left showing only that one failed job, silently losing every other
job's record. Removed the redundant partial save; the reliable full-list
save was already happening right after it anyway.

## Startup used to hard-block over one missing app

`requirements_check.py` refused to start the entire app if WinRAR,
Photoshop, *or* Illustrator was missing — even if you only wanted to batch
PSDs today and Illustrator's path just moved after an update. Now only
WinRAR is a hard requirement (every format needs it at the end regardless
of source app); Photoshop/Illustrator missing just logs a clear warning
through the real logger instead of `print()` (which needed the logger built
before the check runs — reordered `main.py` for that).

## The disk-space wait couldn't actually be stopped

`storage.py`'s `require_space()` loops on `time.sleep(10)` until space
frees up, with no way out. `queue.stop()` sets `running = False`, but this
loop never checked it — so stopping the queue while it was waiting on disk
space did nothing until space actually freed up. Added a `should_continue`
check the loop polls each iteration, wired to `queue.running` from
`main.py`, so stop now actually stops it.

## One dead config value

`AVIF_SPEED` was defined in `config.py` but never passed to either
`image.save()` call — quality was tunable, speed wasn't. Wired it into
both the full preview and thumbnail encode calls.
