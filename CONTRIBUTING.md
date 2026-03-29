# Contributing to Screen Break

This is a side project maintained in spare time. Contributions are welcome -- but please be patient with response times.

## Development Setup

### Prerequisites

- **Python 3.10+** (3.12 recommended)
- **pip** package manager

Screen Break is cross-platform: Windows, macOS, and Linux are all supported.

### Local Development

```bash
# 1. Fork and clone the repo
git clone https://github.com/YOUR_USERNAME/screen-break.git
cd screen-break

# 2. Install dependencies
pip install pystray Pillow screeninfo

# 3. Run
python screen_break.py

# 4. Run in test mode (short intervals for faster testing)
python screen_break.py --test
```

### Platform-Specific Dependencies

**macOS** (only if building the .app bundle):
```bash
pip install pyobjc-framework-Quartz pyobjc-framework-Cocoa
```

**Linux** (system packages for system tray support):
```bash
sudo apt-get install python3-tk libgirepository1.0-dev libcairo2-dev gir1.2-ayatanaappindicator3-0.1
```

### Building Executables Locally

```bash
pip install pyinstaller
pyinstaller screen_break.spec
# Output: dist/ScreenBreak.exe (Windows), dist/ScreenBreak.app (macOS), or dist/ScreenBreak (Linux)
```

The CI workflow builds all three platforms automatically on tagged releases.

## How to Contribute

### Reporting Bugs

Use the [Bug Report](https://github.com/turqoisehex/screen-break/issues/new?template=bug_report.yml) issue template. Include:

- Steps to reproduce
- Expected vs actual behavior
- Your platform (Windows/macOS/Linux version)
- Any error output

### Suggesting Features

Use the [Feature Request](https://github.com/turqoisehex/screen-break/issues/new?template=feature_request.yml) issue template. Describe the problem you're solving, not just the solution you want.

### Submitting Code

1. Fork the repo
2. Create a branch from `master`: `git checkout -b feat/your-feature`
3. Make changes with clear commits
4. Test on your platform (ideally with `--test` mode)
5. Submit a PR against `master`

### Branch Naming

- `feat/` -- new features
- `fix/` -- bug fixes
- `docs/` -- documentation
- `refactor/` -- code restructuring

## Architecture Notes

Screen Break is a single-file application (`screen_break.py`, ~3700 lines). Key components:

- **BreakManager** -- orchestrates all break types (eye rest, micro-pause, scheduled)
- **System tray** -- pystray for cross-platform tray icon and menu
- **Overlays** -- tkinter windows for break notifications and exercises
- **Config** -- JSON files in user home directory (`screen_break_config.json`)
- **Stats** -- break history and streaks in `screen_break_stats.json`

### Important Patterns

- Module-level constants (BREATHING_PATTERNS, DESK_EXERCISES, etc.) must not be redefined later in the file -- classes reference the first definition at instantiation time
- Tray callbacks run in a separate thread -- use `self.root.after(0, ...)` to touch tkinter state
- Never use Unicode/emoji in `print()` statements -- Windows cp1252 consoles crash on non-ASCII characters

## Recognition

All contributors are recognized. We value bug reports, documentation, and community support -- not just code.

## Questions?

Open a [Discussion](https://github.com/turqoisehex/screen-break/discussions) or comment on a relevant issue.
