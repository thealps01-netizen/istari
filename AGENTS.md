# AGENTS.md — Istari

Guidance for any coding agent (Hermes, Codex, Claude Code) working in this repository.
Human-facing docs: `README.md` (users), `docs/MIMARI.md` (deep architecture, Turkish).

## What this is

A Windows-only, always-on-top, frameless hardware-monitor overlay: live FPS, GPU/CPU usage,
temperatures, power, clocks, VRAM, RAM and ping. Pure Python + PyQt6, no native modules.

Sensor data comes from MSI Afterburner's shared memory (MAHM). FPS falls back to RTSS's
shared memory and then to Afterburner's frametime. RAM and ping read the Windows API / a TCP
probe, so they work without Afterburner.

## Layout

| File | Role |
|------|------|
| `istari.py` | Overlay widget, splash screen, tray, animations, `__main__` entry point |
| `hw.py` | MAHM + RTSS + Windows API readers, `HardwareWorker` (background QThread) |
| `cfg.py` | Sensor catalogue, settings persistence, startup registry entry, legacy migration |
| `dialogs.py` | Settings dialog, first-run welcome dialog |
| `themes.py` | Theme palettes + QSS builders, high-contrast detection |
| `updater.py` | GitHub Releases check, download, SHA256 verification, installer launch |
| `crash_handler.py`, `logger.py`, `version.py` | Crash dialog, rotating logs, version (source of truth) |
| `tools/make_icon.py` | Generates the icon the build packages (`istari.ico` in the repo root) |
| `tools/version_sync.py` | The only writer of `version.py`, `file_version_info.txt`, `istari.iss` |

## Run and test

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt
.venv/Scripts/python istari.py            # from source (dev logs, see below)
.venv/Scripts/python -m pytest tests/ -q  # the suite CI runs
```

Runtime data: `%LOCALAPPDATA%\Istari\` (`settings.json`, `logs\istari.log`) — running from
source writes there too, so the repository working copy stays free of runtime state.

## Build and release

- `build.bat` builds the app + installer. It creates its own pinned virtualenv at
  `%LOCALAPPDATA%\Istari\build-venv` (outside the repo) — do not install the build
  dependencies into the global interpreter.
- A release is a `v*.*.*` tag: CI runs the tests, writes the version from the tag with
  `tools/version_sync.py --from-tag`, builds, writes `Istari_Setup.exe` + its `.sha256`,
  and publishes both. The updater refuses to install a release whose checksum it cannot read.
- Never hand-edit `file_version_info.txt` or the `AppVersion` line in `istari.iss`; run
  `python tools/version_sync.py --inject` (a test fails if they drift from `version.py`).

## Conventions

- **English** in code, comments, docstrings, tests, docs, manifests and commit messages.
  UI copy follows the product language (English; there is no Turkish locale).
- **Pinned dependencies** in `requirements.txt` / `requirements-dev.txt`; Pillow and numpy are
  build-time only (icon generation) and must not become runtime imports.
- **Silent failure is a defect**: a swallowed exception needs a log line or a UI signal. The
  user must never be told a write succeeded when it did not (see the checksum, registry and
  crash-log paths for the pattern).
- One writer per fact: version metadata, the icon, and the settings file each have exactly one
  generator; consumers read its output instead of keeping a second copy.

## Traps in this codebase

- `setWindowFlags()` recreates the native window and clears the extended styles, so
  `_apply_no_activate()` (WS_EX_NOACTIVATE) must run after every flag change — losing it makes
  the overlay steal focus from games.
- MAHM's `minLimit`/`maxLimit` are the *graph range*, not session maxima; `hw._usable_max()`
  decides when the bar scale is usable and falls back to the catalogue `bar_max`.
- MAHM sensor names differ per card/Afterburner version. Candidate lists in `cfg.SENSOR_CATALOG`
  must name their component ("gpu1 power", not "power"), or a bare name binds another sensor.
- UI work happens on the Qt thread; all I/O (sensor reads, network, downloads) runs in
  background threads. Never block the event loop.
