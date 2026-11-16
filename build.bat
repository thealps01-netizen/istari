@echo off
title Istari — Build
echo ============================================
echo   Istari  Build + Installer
echo ============================================
echo.

:: ── Verify Python ────────────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python not found in PATH.
    echo  Install Python 3.10+ from https://python.org
    pause & exit /b 1
)

:: ── Build venv ────────────────────────────────────────────────────────────────
:: Kept outside the repository: it is a machine-local cache of pinned
:: dependencies, and the project folder may sit in a synced directory.
set "VENV=%LOCALAPPDATA%\Istari\build-venv"
if not exist "%VENV%\Scripts\python.exe" (
    echo  [1/6] Creating build venv: %VENV%
    python -m venv "%VENV%"
    if errorlevel 1 ( echo  ERROR: could not create the build venv. & pause & exit /b 1 )
)
set "PY=%VENV%\Scripts\python.exe"

:: ── Install dependencies (pinned) ─────────────────────────────────────────────
echo  [1/6] Installing dependencies...
"%PY%" -m pip install -r requirements-dev.txt --quiet
if errorlevel 1 ( echo  ERROR: pip failed. & pause & exit /b 1 )

:: ── Generate icon ─────────────────────────────────────────────────────────────
echo  [2/6] Generating icon...
"%PY%" tools\make_icon.py
if errorlevel 1 ( echo  ERROR: icon generation failed; not packaging a stale istari.ico. & pause & exit /b 1 )

:: ── Tests ─────────────────────────────────────────────────────────────────────
:: The same suite CI runs before it publishes; a red suite is not packaged.
echo  [3/6] Running tests...
set "QT_QPA_PLATFORM=offscreen"
"%PY%" -m pytest tests -q
if errorlevel 1 ( echo  ERROR: tests failed. & pause & exit /b 1 )

:: ── Version metadata ─────────────────────────────────────────────────────────
:: Single writer of the derived version files (see tools/version_sync.py).
echo  [4/6] Syncing version metadata...
"%PY%" tools\version_sync.py --inject
if errorlevel 1 ( echo  ERROR: version sync failed. & pause & exit /b 1 )

:: ── Build exe (onedir via Istari.spec) ─────────────────────────────────────
echo  [5/6] Building Istari.exe...
"%PY%" -m PyInstaller Istari.spec --noconfirm
if errorlevel 1 ( echo  ERROR: PyInstaller build failed. & pause & exit /b 1 )

:: ── Create installer with Inno Setup ─────────────────────────────────────────
echo  [6/6] Creating installer...

:: Try PATH first, then common install locations
set ISCC=
where iscc >nul 2>&1 && set ISCC=iscc
if not defined ISCC (
    if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
)
if not defined ISCC (
    if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set ISCC="C:\Program Files\Inno Setup 6\ISCC.exe"
)
if not defined ISCC (
    if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
)

if defined ISCC (
    for /f %%v in ('"%PY%" -c "from version import __version__; print(__version__)"') do set APP_VER=%%v
    %ISCC% /DAppVersion=%APP_VER% istari.iss
    if errorlevel 1 ( echo  ERROR: Inno Setup failed. & pause & exit /b 1 )
    echo.
    echo  ============================================
    echo   Done!  installer\Istari_Setup.exe
    echo  ============================================
    echo.
) else (
    echo.
    echo  ERROR: Inno Setup 6 not found - no installer was produced.
    echo  The app itself was built: dist\Istari\Istari.exe
    echo.
    echo  To create the installer:
    echo    1. Download Inno Setup 6 from https://jrsoftware.org/isinfo.php
    echo    2. Run this build.bat again
    pause
    exit /b 2
)
pause
