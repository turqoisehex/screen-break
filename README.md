# Screen Break

A healthy break reminder app that runs in your system tray. Reminds you to rest your eyes, stretch, and take regular breaks throughout your workday.

## Features

- **20-20-20 Eye Rest** — Every 20 minutes, look at something 20 feet away for 20 seconds
- **Micro-pause Reminders** — Stand up, stretch, and move around every 45 minutes
- **Scheduled Breaks** — Set specific times for longer breaks (lunch, afternoon recovery, etc.)
- **Exercise Suggestions** — Get stretch and movement ideas during breaks
- **Idle Detection** — Automatically pauses when you're away from your computer
- **Statistics & Streaks** — Track your breaks and build healthy habits
- **Sound Notifications** — Audio alerts when breaks start
- **Strict Mode** — Prevent skipping breaks (only snooze allowed)
- **Screen Dimming** — Smooth fade-in effect during eye rest for a more immersive break
- **Pomodoro Mode** — Alternative 25-minute work / 5-minute break cycle (long break every 4th)
- **Mini Reminders** — Quick posture, hydration, and blink nudges between breaks
- **Low Energy Mode** — Gentler, less frequent reminders when you're not feeling 100%
- **Advance Warning** — A clock icon appears before each break so you can wrap up
- **Work Hours** — Only active during your configured work hours
- **Notes** — Capture where you left off before taking a break
- **Fully Configurable** — All intervals, durations, and settings can be customized
- **Cross-platform** — Works on Windows, macOS, and Linux

## Installation

### Windows (Recommended)

1. Download `ScreenBreak.exe` from the [Releases](../../releases) page
2. Run it — the app appears in your system tray
3. Right-click the tray icon to access settings

### From Source

Requires Python 3.10+

```bash
# Clone the repo
git clone https://github.com/turqoisehex/screen-break.git
cd screen-break

# Install dependencies
pip install pystray Pillow

# Run
python screen_break.py

# Or run with short intervals for testing
python screen_break.py --test
```

## Usage

Once running, Screen Break lives in your system tray:

- **Right-click** the tray icon — access menu:
  - **Pause/Resume** — temporarily disable all reminders
  - **Low energy** — switch to gentler reminder intervals (1.5x longer)
  - **Statistics** — view your break history and streaks
  - **Notes** — view/export notes captured during breaks
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

### Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `eye_rest_interval` | 20 | Minutes between eye rest reminders |
| `micro_pause_interval` | 45 | Minutes between micro-pause reminders |
| `minimum_break_gap` | 20 | Minimum minutes between any two breaks |
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
| `mini_reminders` | false | Enable posture/hydration/blink nudges |
| `mini_reminder_interval` | 10 | Minutes between mini reminders |

## Building from Source

To create a standalone executable:

```bash
# Install PyInstaller
pip install pyinstaller

# Build
pyinstaller screen_break.spec

# Output: dist/ScreenBreak.exe (Windows) or dist/ScreenBreak (macOS/Linux)
```

## Why Take Breaks?

Research shows that regular breaks:
- Reduce eye strain and prevent computer vision syndrome
- Lower risk of repetitive strain injuries
- Improve focus and productivity
- Reduce mental fatigue
- Support better posture and physical health

The 20-20-20 rule (every 20 minutes, look at something 20 feet away for 20 seconds) is recommended by eye care professionals to reduce digital eye strain.

## License

MIT License — feel free to use, modify, and share.

## Contributing

Issues and pull requests welcome!
