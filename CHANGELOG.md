# Changelog

All notable changes to this project are documented in this file.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html)

---

## [Unreleased]

### Changed
- **Renamed Palantir → Istari** everywhere: the app, installer, settings folder and the
  Windows autostart entry. Settings saved under the old name are adopted once
  (`%LOCALAPPDATA%\Palantir\settings.json` is copied, never moved); a stale `Palantir`
  autostart entry pointing at a removed path is cleaned up on startup.
- Auto-update is now fail-closed: the installer is only run when its published SHA256 could be
  read and matches. A missing checksum (or a network failure while fetching it) refuses the
  update instead of installing an unverified binary with elevated rights.
- Progress bars use Afterburner's graph scale, and fall back to the sensor's own maximum when
  that scale is missing or has been outgrown (a 5.5 GHz clock on a 5 GHz scale no longer pins
  the bar at full width).
- Dependencies are pinned; Pillow and numpy moved to the development requirements because only
  the icon generator needs them.
- Version metadata has a single writer (`tools/version_sync.py`), shared by `build.bat` and the
  release workflow; the icon generator now writes the file the build actually packages.

### Fixed
- GPU PWR no longer shows CPU package power, and GPU HOT no longer shows the VRAM temperature
  on cards that expose the memory sensor as "temperature 2".
- A wrong-typed field in `settings.json` used to discard every other setting; it now falls back
  for that field only, and any failed load backs the file up instead of overwriting it.
- The crash dialog no longer claims a crash log was saved when the log folder is not writable.
- "Launch at Windows startup" reflects the real registry state after a failed write, and
  registry/WinAPI failures are logged instead of being swallowed.
- `WS_EX_NOACTIVATE` failures are logged — silently losing it makes the overlay steal focus.

### Added
- Regression tests for the update integrity path, the crash-log contract, startup-registry
  failures and version-metadata drift (99 tests total).

---

## [1.0.22] — 2026-07-13

### Fixed
- RTSS FPS reading corrected
- Corner mask: the overlay's rounded corners no longer leave dark pixels outside the radius
- Anchor (pin position) click handling

---

## [1.0.21] — 2026-07-13

### Added
- Position pinning: snap the overlay to seven screen-edge presets, or leave it free

### Fixed
- RTSS FPS fallback for games that do not report a framerate to Afterburner (e.g. CS2)
- Update-error dialog improvements

---

## [1.0.20] — 2026-04-16

### Added
- PING (ms) latency sensor, measured in its own thread and cached

---

## [1.0.19] — 2026-04-16

### Fixed
- Reverted the `paintEvent` / `TranslucentBackground` approach; restored the original CSS
  `border-radius`

---

## [1.0.18] — 2026-04-16

### Added
- Bar layout mode, plus rounded corners for the overlay

---

## [1.0.17] — 2026-04-12

### Added
- Percentage size setting for the overlay

---

## [1.0.16] — 2026-04-05

### Fixed
- Startup console window: final fix (no console flashes when launching with Windows)

---

## [1.0.15] — 2026-04-04

### Fixed
- Startup console window and `moveToThread` errors on launch

---

## [1.0.14] — 2026-04-04

### Fixed
- Splash screen transparency

---

## [1.0.13] — 2026-04-04

### Changed
- Dead code removed (unused alias and imports)

---

## [1.0.12] — 2026-03-30

### Changed
- Update-flow test coverage

---

## [1.0.11] — 2026-03-30

### Fixed
- The app now closes when the updater launches the installer

---

## [1.0.10] — 2026-03-30

### Added
- Version consistency tests

### Fixed
- Quit animation from the tray menu (conflict with `leaveEvent`)
- `build.bat` now injects the version into `file_version_info.txt`

---

## [1.0.9] — 2026-03-30

### Fixed
- Quit animation did not run from the right-click menu

### Changed
- The release workflow injects the version from the tag

---

## [1.0.8] — 2026-03-30

### Fixed
- Restored the v1.0.3 code (stable release)

---

## [1.0.7] — 2026-03-30

### Fixed
- Quit: animation on a visible window, immediate exit when hidden
- Thread cleanup (`hw_thread.wait` restored)

---

## [1.0.6] — 2026-03-30

### Added
- Assets (overlay.png, settings.png) and the icon files added to the repository

### Fixed
- A hidden window is moved back to its previous position before the closing animation plays

---

## [1.0.5] — 2026-03-30

### Fixed
- Right-click quit animation: show the window, then play the animation

---

## [1.0.4] — 2026-03-30

### Fixed
- Quitting from the right-click menu while minimised now plays the closing animation

---

## [1.0.3] — 2026-03-30

### Fixed
- Quit: with `closeEvent` and the `_quitting` flag, `QApplication.quit()` now exits the event
  loop cleanly

---

## [1.0.2] — 2026-03-30

### Fixed
- External close messages no longer hide the overlay (`closeEvent` → `ignore`)
- Splash screen back to the filling-arc animation

---

## [1.0.1] — 2026-03-30

### Changed
- Splash screen: filling arc → unlock animation (the arm swings right-up, colour accent → green)
- Overlay corners: 18px `border-radius` (consistent with the settings dialog)

### Fixed
- Right-click → Quit did not work; a reliable shutdown is now scheduled with `QTimer.singleShot`

---

## [1.0.0] — 2026-03-30

### Added
- Real-time hardware monitoring — FPS, GPU/CPU usage, temperature, power, clocks, VRAM, RAM
- Always-on-top frameless overlay (`WS_EX_NOACTIVATE` — never steals focus from games)
- **Intro animation** — the overlay slides down from above and fades in (500 ms, OutCubic)
- **Outro animation** — slides down and fades out on quit (400 ms, InCubic)
- **Splash screen** — a filling arc spins in the middle of the screen while the app starts (~1.5 s)
- **Slide in/out** — show or hide the overlay by clicking the system tray icon (280 ms)
- **Hover opacity** — the overlay fades while the pointer is over it and returns on leave (350 ms)
- Drag-and-drop positioning, or lock it in place
- System tray integration with a context menu
- Per-sensor custom colours
- Dark / light theme plus Windows High Contrast support
- Sensor readings from MSI Afterburner shared memory (MAHM)
- Windows API integration for RAM usage
- Auto-update — checks the GitHub Releases API and installs silently
- Run at Windows startup (registry integration)
- Rotating log file (1 MB, 2 backups) plus detailed crash reports
- Atomic settings writes — `.tmp` then rename, for data integrity
- First-run welcome screen
- 14+ supported sensor types

### Technical
- PyQt6-based, pure Python
- A dedicated QThread polls the hardware in the background (never blocks the UI)
- Single-exe installer package via PyInstaller + Inno Setup
- PerMonitorV2 DPI awareness (multi-monitor on Windows 11)
- Windows App User Model ID (taskbar grouping and pinning)
- pytest-based unit test suite
