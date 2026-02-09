# ScreenBreak Project Documentation

Complete technical documentation for the ScreenBreak application. Use this file to resume development if conversation context is lost.

## Architecture Overview

**Single-file application:** `screen_break.py` (~3680 lines)
- Pure Python + tkinter (no external GUI frameworks)
- System tray integration via `pystray`
- Cross-platform: Windows, macOS, Linux

**Data files (in user home directory):**
- `~/screen_break_config.json` - All settings
- `~/screen_break_stats.json` - Break statistics and streaks
- `~/screen_break_notes.json` - User notes captured during breaks

---

## Feature Implementation Details

### Core Break System

**Three break types:**
1. **Eye Rest** - 20-20-20 rule (every 20 min, look 20 feet away, 20 seconds)
2. **Micro-pause** - Stand/stretch breaks (every 45 min)
3. **Scheduled** - Fixed-time breaks (lunch, recovery, etc.)

**Break flow:**
1. Warning phase (clock icon in tray, configurable seconds)
2. Break overlay appears (fullscreen or windowed)
3. Countdown timer
4. User can skip (unless strict mode) or snooze

**Coast margin:** Skips eye rest if a scheduled break is coming soon (configurable, default 10 min)

### Premium Features (v2.0)

#### 1. Focus/Presentation Mode
- **Purpose:** Auto-pause breaks during fullscreen apps (presentations, games, videos)
- **Implementation:** Windows API via ctypes - `GetForegroundWindow()` + `GetWindowRect()`
- **Config:** `focus_mode: true` (ON by default)
- **Location:** `_is_fullscreen_active()` method, checked in `_tick()` before `_check()`

#### 2. Multi-Monitor Overlay
- **Purpose:** Show break overlay on all connected monitors
- **Implementation:** Uses `screeninfo` library to enumerate monitors
- **Behavior:** Primary monitor gets full UI, secondary monitors get simple dim + text
- **Config:** `multi_monitor_overlay: true`
- **Fallback:** Gracefully degrades if screeninfo not installed

#### 3. Custom Break Sounds
- **Purpose:** User-selected audio files instead of system beep
- **Formats:** .wav, .mp3, .ogg
- **Implementation:** Windows MCI (Media Control Interface) via ctypes
- **Config:** `custom_sound_enabled`, `custom_sound_path`
- **UI:** File picker button in Settings

#### 4. Hydration Tracking
- **Purpose:** Remind user to drink water, track daily intake
- **Implementation:** Separate reminder popup with "+1 Glass" button
- **Config:** `hydration_tracking`, `hydration_goal` (default 8), `hydration_reminder_interval` (default 30 min)
- **Stats:** Stored in daily_history for charts

#### 5. Themes (Dark/Light/Nord)
- **Purpose:** Visual customization
- **Implementation:** Global color constants (C_BG, C_TEXT, etc.) updated via `_apply_theme()`
- **Themes:** dark, light, nord (nord is default)
- **Config:** `theme: "nord"`
- **Note:** Changes apply instantly without restart

#### 6. Guided Eye Exercises
- **Purpose:** Animated exercises instead of simple "look away" message
- **Patterns:**
  - Circle trace - dot moves in circle
  - Figure-8 - horizontal figure-8 pattern
  - Near-far focus - pulsing dot (focus near/far)
- **Implementation:** `GuidedEyeExercise` class with Canvas animation
- **Canvas size:** 700x500 pixels for proper eye tracking range
- **Config:** `guided_eye_exercises: true`

#### 7. Breathing Exercises
- **Purpose:** Guided breathing during micro-pauses
- **Patterns:**
  - Box breathing (4-4-4-4)
  - Relaxing (4-7-8)
  - Energizing (6-0-2-0)
- **Implementation:** `BreathingExercise` class with pulsing circle animation
- **Phases:** Inhale (expand) → Hold → Exhale (contract) → Hold
- **Config:** `breathing_exercises: true`

#### 8. Desk Exercises
- **Purpose:** Animated stretch instructions during micro-pauses
- **Implementation:** ASCII-art frame-based animations
- **Exercises:** Shoulder rolls, neck stretches, wrist circles
- **Config:** `desk_exercises: true`

#### 9. Custom Break Messages
- **Purpose:** User-defined motivational messages shown during breaks
- **Implementation:** List of strings, random selection
- **Config:** `use_custom_messages`, `custom_messages: [...]`
- **UI:** "Edit Messages..." button opens text editor dialog

#### 10. Focus Session Timer (Pomodoro)
- **Purpose:** Named work sessions with timer
- **Flow:** Dialog → Enter task name → Start → Countdown → Completion
- **Config:** `focus_session_enabled`, `focus_session_duration` (default 25 min)
- **Stats:** Completed sessions tracked

#### 11. Daily/Weekly Reports
- **Purpose:** Visual history of break compliance
- **Implementation:** Canvas-based stacked bar charts
- **Data:** Last 7 days, breaks by type (eye/micro/scheduled)
- **Access:** Stats button in tray menu or status window

---

## UI Structure

### System Tray Menu
```
Pause/Resume
Gentle mode (low energy)
─────────────
Stats
Notes
Focus (start focus session)
─────────────
Status & Settings
Quit
```

### Status & Settings Window

**Layout (top to bottom):**
1. **Action buttons row:** Pause, Gentle, Stats, Notes, Focus
2. **Timer cards:** Eye rest, Micro-pause, Next break (with countdowns)
3. **Collapsible Settings section:**
   - Header row: "▼ Settings" toggle + Apply/Save + Reset buttons
   - Scrollable settings area with categories

**Settings categories:**
- Intervals & Timing
- Scheduled Breaks (editable list)
- Theme selector
- Features (checkboxes for each premium feature)
- Sound settings
- Hydration settings

---

## Configuration Schema

```python
DEFAULT_CONFIG = {
    # Core intervals
    "eye_rest_interval": 20,        # minutes
    "micro_pause_interval": 45,     # minutes
    "minimum_break_gap": 20,        # minutes
    "warning_seconds": 60,
    "snooze_minutes": 5,
    "eye_rest_duration": 20,        # seconds
    "coast_margin_minutes": 10,     # skip eye rest if scheduled within

    # Work hours
    "work_start": "08:00",
    "work_end": "20:00",

    # Idle detection
    "idle_detection": True,
    "idle_threshold": 300,          # seconds

    # Core features
    "sound_enabled": True,
    "show_exercises": True,
    "strict_mode": False,
    "screen_dim": True,
    "pomodoro_mode": False,
    "low_energy_multiplier": 1.5,

    # Premium features
    "focus_mode": True,             # presentation mode (ON by default)
    "multi_monitor_overlay": True,
    "theme": "nord",                # dark, light, nord
    "guided_eye_exercises": False,
    "breathing_exercises": False,
    "desk_exercises": False,

    # Custom sounds
    "custom_sound_enabled": False,
    "custom_sound_path": "",

    # Custom messages
    "use_custom_messages": False,
    "custom_messages": [],

    # Hydration
    "hydration_tracking": False,
    "hydration_goal": 8,
    "hydration_reminder_interval": 30,

    # Focus sessions
    "focus_session_enabled": False,
    "focus_session_duration": 25,

    # Mini reminders
    "mini_reminders": False,
    "mini_reminder_interval": 10,

    # Scheduled breaks
    "scheduled_breaks": [
        {"time": "09:45", "duration": 15, "title": "Stretch Break"},
        {"time": "11:30", "duration": 30, "title": "Movement & Mindfulness"},
        {"time": "13:30", "duration": 60, "title": "Lunch"},
        {"time": "16:00", "duration": 15, "title": "Active Recovery"},
        {"time": "17:00", "duration": 30, "title": "Recovery Break"},
        {"time": "20:00", "duration": 0, "title": "Shutdown"}
    ]
}
```

---

## Key Classes

### ScreenBreakApp
Main application class. Handles:
- Tray icon and menu
- Timer logic (`_tick()`, `_check()`)
- Overlay windows
- Settings UI
- Statistics

### GuidedEyeExercise
Canvas-based eye exercise animation.
- `__init__(canvas, width, height, pattern)`
- `start()`, `stop()`
- `_update_position()` - calculates dot position based on pattern
- `animate()` - animation loop

### BreathingExercise
Canvas-based breathing animation.
- `__init__(canvas, width, height, pattern)`
- `start()`, `stop()`
- `_update()` - updates circle size and instruction text
- Patterns defined as list of (phase_name, duration_seconds)

---

## Known Issues & Edge Cases

1. **Test mode intervals:** Use `--test` flag for 1-minute eye rest, 2-minute micro-pause
2. **Fullscreen detection:** Windows-only via ctypes; other platforms skip this check
3. **Multi-monitor:** Requires `screeninfo` package; gracefully falls back to single monitor
4. **Sound playback:** Windows MCI for custom sounds; system beep as fallback
5. **Console encoding:** All `print()` output must use ASCII only — Windows cp1252 crashes on Unicode/emoji

### Open TODOs
- **Exe icon at 16x16:** Tray, taskbar, and large Explorer icons all look great. Only the small details-view icon in Explorer is garbled. ICO now uses BMP format for small sizes (was PNG). The 16x16 design still has too much detail — next step is to render at higher resolution and LANCZOS downscale, or use a minimal design for 16x16 only.

---

## Build & Release

**Local build:**
```powershell
cd D:\Documents\Scripts\ScreenBreak
pip install pyinstaller pystray Pillow screeninfo
pyinstaller screen_break.spec
# Output: dist/ScreenBreak.exe
```

**GitHub Actions:** `.github/workflows/release.yml`
- Triggers on version tags (v*)
- Builds for Windows, macOS, Linux
- Creates GitHub release with binaries

**To release:**
```powershell
git tag v2.0.0
git push origin v2.0.0
```

---

## Development Tips

1. **Quick testing:** `python screen_break.py --test` uses short intervals
2. **Theme testing:** Change theme in Settings, changes apply instantly
3. **Feature flags:** Most features have enable/disable config options
4. **Logging:** Print statements go to console when run from terminal

---

## File Structure

```
ScreenBreak/
├── screen_break.py          # Main application (single file, ~3680 lines)
├── screen_break.spec         # PyInstaller build spec (generates icon on build)
├── generate_icon_win31.py    # Standalone Win 3.1 style icon generator
├── icon.ico                  # Windows icon (generated, multi-size)
├── icon.png                  # PNG icon (generated, 256px)
├── README.md                 # User documentation
├── PROJECT.md                # This file (developer docs)
├── .gitignore                # Ignores build/, dist/, __pycache__/
└── .github/
    └── workflows/
        └── release.yml       # CI/CD for releases
```

## Version History

- **v2.0** — Initial premium features release (themes, exercises, hydration, focus sessions, etc.)
- **v2.1** — 25 code review fixes across 5 rounds (custom messages wired in, gap validation, presentation mode, TclError protection, idle recovery, focus session improvements, stats saved on quit, etc.) + Win 3.1 icon (WIP) + Unicode crash fix
