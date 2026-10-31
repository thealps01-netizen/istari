# Contributing to Istari

Thanks for your interest in contributing!

## Setup

```bash
git clone https://github.com/thealps01-netizen/istari.git
cd istari
pip install -r requirements-dev.txt
```

## Running Tests

```bash
pytest tests/ -v
```

All tests must pass before submitting a pull request.

## Making Changes

1. Fork the repository and create a branch from `main`
2. Make your changes
3. Run the test suite — all tests must pass
4. Open a pull request with a clear description of what was changed and why

## Code Style

- Follow existing code style (no formatter enforced, just be consistent)
- Keep functions focused and small
- New hardware sensors go in `cfg.py` → `SENSOR_CATALOG`
- UI changes go in `dialogs.py` (settings/welcome) or `istari.py` (main overlay)
- Theme/color changes go in `themes.py`

## Building Locally

```bat
build.bat
```

Requires Python 3.10+ and [Inno Setup 6](https://jrsoftware.org/isinfo.php) for the installer step.
