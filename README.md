# Screen Break

[![Release](https://img.shields.io/github/v/release/turqoisehex/screen-break)](https://github.com/turqoisehex/screen-break/releases/latest)
[![License](https://img.shields.io/github/license/turqoisehex/screen-break)](LICENSE)
[![Stars](https://img.shields.io/github/stars/turqoisehex/screen-break?style=social)](https://github.com/turqoisehex/screen-break)

A healthy break reminder app that runs in your system tray. Reminds you to rest your eyes, stretch, and take regular breaks throughout your workday.

## Install

Download the latest release for your platform:

**[Download Screen Break](../../releases/latest)**

| Platform | File |
|----------|------|
| Windows | `ScreenBreak-Windows.exe` |
| macOS | `ScreenBreak-macOS.dmg` |
| Linux | `ScreenBreak-Linux` |

**Windows / Linux:** Run the downloaded file — the app appears in your system tray.

**macOS:**
1. Open the `.dmg` and drag **Screen Break** to **Applications**
2. Open it from Applications. On first launch, macOS will show a security warning because the app is not from the App Store
3. Click **Open** when prompted (or go to **System Settings > Privacy & Security** and click **Open Anyway**)
4. The app appears in your **menu bar** (top-right). Right-click the icon for settings

> **From source:** Requires Python 3.10+. `pip install pystray Pillow screeninfo` then `python screen_break.py`.

## Features

### Core Features
- **20-20-20 Eye Rest** — Every 20 minutes, look at something 20 feet away for 20 seconds
- **Micro-pause Reminders** — Stand up, stretch, and move around every 45 minutes
- **Scheduled Breaks** — Set specific times for longer breaks (lunch, afternoon recovery, etc.)
- **Exercise Suggestions** — Get stretch and movement ideas during breaks
- **Idle Detection** — Automatically pauses when you're away from your computer
- **Statistics & Streaks** — Track your breaks and build healthy habits
- **Sound Notifications** — Audio alerts when breaks start
- **Strict Mode** — Prevent skipping breaks (only snooze allowed)
- **Screen Dimming** — Smooth fade-in effect during eye rest
- **Pomodoro Mode** — Alternative 25-minute work / 5-minute break cycle
- **Mini Reminders** — Quick posture, hydration, and blink nudges between breaks
- **Low Energy Mode** — Gentler, less frequent reminders when you're not feeling 100%
- **Advance Warning** — A clock icon appears before each break so you can wrap up
- **Work Hours** — Only active during your configured work hours
- **Notes** — Capture where you left off before taking a break

### Premium Features (v2.0+)
- **Presentation Mode** — Auto-pauses breaks during fullscreen apps (presentations, games, videos)
- **Multi-Monitor Support** — Break overlays appear on all connected monitors
- **Custom Sounds** — Use your own .wav, .mp3, or .ogg files for notifications
- **Themes** — Dark, Light, and Nord color schemes with instant switching
- **Guided Eye Exercises** — Animated dot-tracking exercises (circle, figure-8, near-far focus)
- **Breathing Exercises** — Guided breathing with visual animation (box, relaxing, energizing patterns)
- **Desk Exercises** — Animated stretch instructions during micro-pauses
- **Custom Messages** — Add your own motivational messages to display during breaks
- **Hydration Tracking** — Water intake reminders with daily goal tracking
- **Focus Sessions** — Pomodoro-style timer with task naming
- **Daily/Weekly Reports** — Visual charts showing your break history

## Usage

Once running, Screen Break lives in your system tray:

- **Right-click** the tray icon — access menu:
  - **Pause/Resume** — temporarily disable all reminders
  - **Gentle mode** — switch to gentler reminder intervals (1.5x longer)
  - **Stats** — view your break history, streaks, and charts
  - **Notes** — view/export notes captured during breaks
  - **Focus** — start a named focus session with timer
  - **Status & Settings** — configure everything
  - **Quit** — exit the app

### Break Types

| Type | Default Interval | Purpose |
|------|------------------|---------|
| Eye Rest | Every 20 min | Look away from screen (20-20-20 rule) |
| Micro-pause | Every 45 min | Stand, stretch, move around |
| Scheduled | Set times | Longer breaks (lunch, recovery, etc.) |

### Default Schedule

| Time | Break | Duration |
|------|-------|----------|
| 9:45 AM | Stretch Break | 15 min |
| 11:30 AM | Movement & Mindfulness | 30 min |
| 1:30 PM | Lunch | 60 min |
| 4:00 PM | Active Recovery | 15 min |
| 5:00 PM | Recovery Break | 30 min |
| 8:00 PM | Shutdown | — |

All times and durations are fully customizable in Settings.

## Configuration

Settings are stored in your home directory:
- **Config:** `~/screen_break_config.json`
- **Notes:** `~/screen_break_notes.json`
- **Statistics:** `~/screen_break_stats.json`

### Settings Reference

| Setting | Default | Description |
|---------|---------|-------------|
| `eye_rest_interval` | 20 | Minutes between eye rest reminders |
| `micro_pause_interval` | 45 | Minutes between micro-pause reminders |
| `minimum_break_gap` | 20 | Minimum minutes between any two breaks |
| `coast_margin_minutes` | 10 | Skip eye rest if scheduled break is within this many minutes |
| `warning_seconds` | 60 | Seconds of advance warning before breaks |
| `snooze_minutes` | 5 | Duration of snooze when clicking "X more min" |
| `eye_rest_duration` | 20 | Seconds for eye rest countdown |
| `low_energy_multiplier` | 1.5 | Interval multiplier in low energy mode |
| `work_start` | "08:00" | Start of work hours (24h format) |
| `work_end` | "20:00" | End of work hours (24h format) |
| `idle_detection` | true | Pause timers when user is idle |
| `idle_threshold` | 300 | Seconds of inactivity before considered idle |
| `sound_enabled` | true | Play sound when breaks start |
| `show_exercises` | true | Show exercise suggestions during breaks |
| `strict_mode` | false | Prevent skipping breaks (only snooze) |
| `screen_dim` | true | Smooth fade-in effect during eye rest |
| `pomodoro_mode` | false | Use 25 min work / 5 min break cycles |
| `focus_mode` | true | Auto-pause during fullscreen apps |
| `theme` | "nord" | Color theme: dark, light, or nord |
| `guided_eye_exercises` | false | Enable animated eye exercises |
| `breathing_exercises` | false | Enable breathing exercises during micro-pauses |
| `desk_exercises` | false | Enable animated desk stretch instructions |
| `hydration_tracking` | false | Enable water intake tracking |
| `hydration_goal` | 8 | Daily water glasses goal |
| `multi_monitor_overlay` | true | Show break overlay on all monitors |

## Building from Source

To create a standalone executable:

```bash
# Install build dependencies
pip install pyinstaller pystray Pillow screeninfo

# Build
pyinstaller screen_break.spec

# Output: dist/ScreenBreak.exe (Windows), dist/ScreenBreak.app (macOS), or dist/ScreenBreak (Linux)
```

## Why Take Breaks?

Research shows that regular breaks:
- Reduce eye strain and prevent computer vision syndrome
- Lower risk of repetitive strain injuries
- Improve focus and productivity
- Reduce mental fatigue
- Support better posture and physical health

The 20-20-20 rule (every 20 minutes, look at something 20 feet away for 20 seconds) is recommended by eye care professionals to reduce digital eye strain.

## Contributing

Contributions are welcome! This is a side project maintained in spare time, so please be patient with response times.

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines. Check out issues labeled [`good first issue`](https://github.com/turqoisehex/screen-break/labels/good%20first%20issue) for beginner-friendly tasks.

## License

[MIT](LICENSE)
