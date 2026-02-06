#!/usr/bin/env python3
"""
Screen Break — Healthy Break Reminder
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Cross-platform break reminder app that runs in your system tray.
Reminds you to rest your eyes, stretch, and take regular breaks.

Features:
  - 20-20-20 eye rest reminders (every 20 min, look 20 feet away for 20 sec)
  - Micro-pause reminders for stretching and movement
  - Scheduled break times with customizable durations
  - Low energy mode for gentler reminders
  - Configurable work hours
  - All settings editable live and persist between sessions

Usage:
    python screen_break.py
    python screen_break.py --test   (short intervals for testing)
    pythonw screen_break.py         (Windows — no console)

Source: https://github.com/turqoisehex/screen-break
"""
from __future__ import annotations
import sys, os, platform
import argparse

# ─── tkinter check ────────────────────────────────────────────
try:
    import tkinter as tk
except ImportError:
    _s = platform.system()
    print("Error: tkinter is required.")
    if _s == "Darwin":
        print("  brew install python-tk@3.12  (or use python.org installer)")
    elif _s == "Linux":
        print("  sudo apt install python3-tk")
    sys.exit(1)

# ─── Auto-install pip deps ────────────────────────────────────
def _ensure_deps():
    import importlib, importlib.util, subprocess
    needed = {"pystray": "pystray", "PIL": "Pillow"}
    missing = [pkg for mod, pkg in needed.items()
               if importlib.util.find_spec(mod) is None]
    if not missing:
        return True
    print(f"  Installing: {', '.join(missing)} ...")
    for flags in [[], ["--user"]]:
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "--quiet"] + flags + missing,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("  ✓ Installed.\n")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    print(f"  ✗ Failed.  Run:  pip install {' '.join(missing)}\n")
    return False

HAS_TRAY = _ensure_deps()

# ─── Imports ──────────────────────────────────────────────────
import threading, datetime, json, math, random
from typing import Any, Callable, Optional

if HAS_TRAY:
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        HAS_TRAY = False

# ─── Platform ────────────────────────────────────────────────
IS_MAC = platform.system() == "Darwin"
IS_WIN = platform.system() == "Windows"
FONT = "Helvetica Neue" if IS_MAC else "Segoe UI" if IS_WIN else "DejaVu Sans"
MONO = "Menlo" if IS_MAC else "Consolas" if IS_WIN else "DejaVu Sans Mono"

if IS_WIN:
    try:
        import ctypes
        # Hide console window
        _h = ctypes.windll.kernel32.GetConsoleWindow()
        if _h:
            ctypes.windll.user32.ShowWindow(_h, 0)
        # Enable high-DPI awareness for crisp rendering
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except AttributeError:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# ─── Parse Args ──────────────────────────────────────────────
_parser = argparse.ArgumentParser(description="Screen Break break reminder")
_parser.add_argument("--test", action="store_true", help="Use short intervals for testing")
_args = _parser.parse_args()
TEST_MODE = _args.test

# ─── Named Constants ─────────────────────────────────────────
SLEEP_DETECTION_MINUTES = 120      # If >2 hours since last check, assume laptop slept
CATCHUP_WINDOW_SECONDS = 180       # Catch-up window for scheduled breaks (3 minutes)
COAST_MARGIN_MINUTES = 5           # Skip eye/micro if scheduled break within this margin
STARTUP_DISMISS_MS = 6000          # Auto-dismiss startup notification after 6 seconds
WARNING_ICON_SIZE = 62             # Size of warning clock icon (larger for visibility)
WARNING_ICON_MARGIN = 18           # Margin from screen edge

# ─── Config ───────────────────────────────────────────────────
CONFIG_FILE = os.path.join(os.path.expanduser("~"), "screen_break_config.json")
NOTES_FILE  = os.path.join(os.path.expanduser("~"), "screen_break_notes.json")
STATS_FILE  = os.path.join(os.path.expanduser("~"), "screen_break_stats.json")

# ─── Idle Detection ───────────────────────────────────────────
IDLE_CHECK_INTERVAL = 5  # Check idle every 5 seconds
DEFAULT_IDLE_THRESHOLD = 300  # 5 minutes of inactivity = idle

def get_idle_seconds() -> float:
    """Get seconds since last user input. Returns 0 if detection unavailable."""
    try:
        if IS_WIN:
            import ctypes
            from ctypes import Structure, c_uint, sizeof, byref, windll
            class LASTINPUTINFO(Structure):
                _fields_ = [("cbSize", c_uint), ("dwTime", c_uint)]
            lii = LASTINPUTINFO()
            lii.cbSize = sizeof(LASTINPUTINFO)
            if windll.user32.GetLastInputInfo(byref(lii)):
                millis = windll.kernel32.GetTickCount() - lii.dwTime
                return millis / 1000.0
        elif IS_MAC:
            import subprocess
            result = subprocess.run(
                ["ioreg", "-c", "IOHIDSystem"],
                capture_output=True, text=True, timeout=2
            )
            for line in result.stdout.split("\n"):
                if "HIDIdleTime" in line:
                    # Value is in nanoseconds
                    ns = int(line.split("=")[-1].strip())
                    return ns / 1_000_000_000
        else:  # Linux
            import subprocess
            result = subprocess.run(
                ["xprintidle"],
                capture_output=True, text=True, timeout=2
            )
            return int(result.stdout.strip()) / 1000.0
    except Exception:
        pass
    return 0.0

# ─── Sound System ─────────────────────────────────────────────
def play_sound(sound_type: str = "chime") -> None:
    """Play a notification sound. Types: 'chime', 'complete', 'warning'"""
    try:
        if IS_WIN:
            import winsound
            if sound_type == "chime":
                winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
            elif sound_type == "complete":
                winsound.PlaySound("SystemExclamation", winsound.SND_ALIAS | winsound.SND_ASYNC)
            else:
                winsound.PlaySound("SystemHand", winsound.SND_ALIAS | winsound.SND_ASYNC)
        elif IS_MAC:
            import subprocess
            sounds = {"chime": "Blow", "complete": "Glass", "warning": "Basso"}
            subprocess.Popen(["afplay", f"/System/Library/Sounds/{sounds.get(sound_type, 'Blow')}.aiff"])
        else:  # Linux
            import subprocess
            # Try paplay (PulseAudio) first, then aplay
            for cmd in [["paplay", "/usr/share/sounds/freedesktop/stereo/message.oga"],
                       ["aplay", "-q", "/usr/share/sounds/sound-icons/prompt.wav"]]:
                try:
                    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    break
                except FileNotFoundError:
                    continue
    except Exception:
        pass  # Silent fail - sound is optional

# ─── Exercise Suggestions ─────────────────────────────────────
EXERCISES = {
    "eye": [
        "Blink rapidly 20 times to refresh your eyes",
        "Look at something 20+ feet away for 20 seconds",
        "Close your eyes and relax for 20 seconds",
        "Roll your eyes in circles — clockwise, then counter-clockwise",
        "Focus on a near object, then a far object — repeat 5 times",
        "Gently massage your temples and around your eyes",
        "Cup your palms over closed eyes (palming) for 20 seconds",
        "Look up, down, left, right — hold each for 3 seconds",
    ],
    "stretch": [
        "Stand up and stretch your arms overhead",
        "Roll your shoulders backwards 10 times",
        "Tilt your head to each side, holding for 10 seconds",
        "Interlace fingers and push palms outward",
        "Stand and do a gentle standing forward fold",
        "Do 5 slow neck rolls in each direction",
        "Stretch your wrists — extend arm, pull fingers back gently",
        "Twist your torso left and right while seated",
        "Shrug shoulders up to ears, hold 5 seconds, release",
        "Clasp hands behind back and open your chest",
        "Do 10 calf raises while standing",
        "March in place for 30 seconds",
        "Touch your toes (or reach toward them)",
        "Do a doorway chest stretch",
        "Gentle side bends — reach one arm overhead and lean",
    ],
    "move": [
        "Walk to the window and look outside for a moment",
        "Get a glass of water and drink it",
        "Do 10 squats or chair squats",
        "Walk around your space for 2 minutes",
        "Do 10 wall push-ups",
        "Step outside for fresh air if possible",
        "Walk up and down stairs once",
        "Do some light jumping jacks",
        "Shake out your whole body for 30 seconds",
        "Take a short walk to another room and back",
    ],
}

def get_exercise(category: str = "stretch") -> str:
    """Get a random exercise suggestion."""
    exercises = EXERCISES.get(category, EXERCISES["stretch"])
    return random.choice(exercises)

# ─── Mini Reminders ───────────────────────────────────────────
MINI_REMINDERS = [
    ("💧", "Time to hydrate", "Take a sip of water"),
    ("🧘", "Posture check", "Sit up straight, shoulders back"),
    ("👁", "Blink break", "Blink slowly 10 times"),
    ("🫁", "Deep breath", "Take 3 slow, deep breaths"),
    ("🦶", "Foot check", "Uncross legs, feet flat on floor"),
    ("✊", "Hand stretch", "Shake out your hands and fingers"),
    ("😌", "Face relax", "Unclench your jaw, relax your face"),
]

def get_mini_reminder() -> tuple[str, str, str]:
    """Get a random mini reminder (emoji, title, description)."""
    return random.choice(MINI_REMINDERS)

DEFAULT_CONFIG = {
    "eye_rest_interval": 20,
    "micro_pause_interval": 45,
    "minimum_break_gap": 20,
    "warning_seconds": 60,
    "snooze_minutes": 5,
    "eye_rest_duration": 20,
    "low_energy_multiplier": 1.5,
    "work_start": "08:00",
    "work_end": "20:00",
    # Features
    "idle_detection": True,           # Pause timers when user is idle
    "idle_threshold": 300,            # Seconds of inactivity before considered idle
    "sound_enabled": True,            # Play sounds on break start
    "strict_mode": False,             # Prevent skipping breaks (only snooze allowed)
    "show_exercises": True,           # Show exercise suggestions during breaks
    "screen_dim": True,               # Dim screen during eye rest (more immersive)
    "pomodoro_mode": False,           # Use pomodoro timing (25 work / 5 break)
    "mini_reminders": False,          # Brief posture/hydration/blink nudges
    "mini_reminder_interval": 10,     # Minutes between mini reminders
    "breaks": [
        {"time": "09:45", "duration": 15, "title": "Stretch Break"},
        {"time": "11:30", "duration": 30, "title": "Movement & Mindfulness"},
        {"time": "13:30", "duration": 60, "title": "Lunch"},
        {"time": "16:00", "duration": 15, "title": "Active Recovery"},
        {"time": "17:00", "duration": 30, "title": "Recovery Break"},
        {"time": "20:00", "duration":  0, "title": "Shutdown"},
    ],
}

def load_config() -> dict[str, Any]:
    """Load config from file, falling back to defaults for missing/invalid values."""
    defaults = json.loads(json.dumps(DEFAULT_CONFIG))
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                user_cfg = json.load(f)
            if isinstance(user_cfg, dict):
                defaults.update(user_cfg)
        except (json.JSONDecodeError, IOError, OSError) as e:
            print(f"  ⚠ Config load error: {e}. Using defaults.")

    # Apply test mode overrides
    if TEST_MODE:
        defaults["eye_rest_interval"] = 1
        defaults["micro_pause_interval"] = 2
        defaults["minimum_break_gap"] = 1
        defaults["warning_seconds"] = 10

    # Validate numeric fields
    for key, min_val, default in [
        ("eye_rest_interval", 1, 20),
        ("micro_pause_interval", 1, 45),
        ("minimum_break_gap", 0, 20),
        ("warning_seconds", 5, 60),
        ("snooze_minutes", 1, 5),
        ("eye_rest_duration", 5, 20),
        ("low_energy_multiplier", 1.0, 1.5),
    ]:
        if not isinstance(defaults.get(key), (int, float)) or defaults[key] < min_val:
            defaults[key] = default

    return defaults

def save_config(cfg: dict[str, Any]) -> None:
    """Save config to file."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except (IOError, OSError) as e:
        print(f"  ⚠ Config save error: {e}")

# ─── Statistics ───────────────────────────────────────────────
DEFAULT_STATS = {
    "lifetime": {
        "eye_rest_taken": 0,
        "eye_rest_skipped": 0,
        "micro_taken": 0,
        "micro_skipped": 0,
        "scheduled_taken": 0,
        "scheduled_skipped": 0,
    },
    "today": {
        "date": None,
        "eye_rest_taken": 0,
        "micro_taken": 0,
        "scheduled_taken": 0,
    },
    "streak_days": 0,
    "last_active_date": None,
}

def load_stats() -> dict[str, Any]:
    """Load statistics from file."""
    stats = json.loads(json.dumps(DEFAULT_STATS))
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                # Deep merge
                for key in ["lifetime", "today"]:
                    if key in saved and isinstance(saved[key], dict):
                        stats[key].update(saved[key])
                for key in ["streak_days", "last_active_date"]:
                    if key in saved:
                        stats[key] = saved[key]
        except (json.JSONDecodeError, IOError, OSError):
            pass
    return stats

def save_stats(stats: dict[str, Any]) -> None:
    """Save statistics to file."""
    try:
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)
    except (IOError, OSError):
        pass

def update_stats_for_today(stats: dict[str, Any]) -> None:
    """Reset today's stats if it's a new day, update streak."""
    today = datetime.date.today().isoformat()
    if stats["today"].get("date") != today:
        # New day - check streak
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        if stats["last_active_date"] == yesterday:
            stats["streak_days"] = stats.get("streak_days", 0) + 1
        elif stats["last_active_date"] != today:
            stats["streak_days"] = 1
        # Reset today's counters
        stats["today"] = {
            "date": today,
            "eye_rest_taken": 0,
            "micro_taken": 0,
            "scheduled_taken": 0,
        }
    stats["last_active_date"] = today

# ─── Descriptions ─────────────────────────────────────────────
DESCS = {
    "Stretch Break": (
        "Stand up. Stretch your wrists, neck, and shoulders.\nRefill your water. Move around for a few minutes.",
        "Even a small stretch helps. Stand if you can,\nor roll your shoulders and wrists where you are."),
    "Movement & Mindfulness": (
        "Leave your desk. Walk outside, stretch, or sit\nsomewhere away from your screen. Screen-free time.",
        "Step away from your screen for a while.\nNo pressure to 'do' anything specific."),
    "Lunch": (
        "Full hour away from your workstation.\nEat a real meal, not at your desk.\nRest after eating if you need to.",
        "Time to eat something. Away from the screen.\nRest after if you need to."),
    "Active Recovery": (
        "Brief movement break.\nWalk, stretch, step outside for air.",
        "Pause for a few minutes.\nEven standing and looking out a window counts."),
    "Recovery Break": (
        "You've been going for hours.\nStep fully away. Snack, fresh air, anything not-work.",
        "Your brain has done a lot today.\nTake some real time away."),
    "Shutdown": (
        "Time to wrap up for the day.\nLog tomorrow's first task so you can let go.\nClear your desk. Hard disconnect.",
        "You've done enough today.\nWrite one line about where to start tomorrow.\nThen stop."),
}

def get_desc(title, low_energy=False):
    d = DESCS.get(title)
    if d: return d[1] if low_energy else d[0]
    return "Time for a break.\nTake it easy." if low_energy else f"Break: {title}.\nStep away from your screen."

# ─── Colours ──────────────────────────────────────────────────
C_BG       = "#111827";  C_CARD     = "#1e293b";  C_CARD_IN  = "#253349"
C_ACCENT   = "#f43f5e";  C_ACCENT2  = "#0ea5e9"
C_BTN_PRI  = "#1d4ed8";  C_BTN_SEC  = "#334155"
C_TEXT     = "#f1f5f9";  C_TEXT_DIM = "#94a3b8";  C_TEXT_MUT = "#64748b"
C_EYE_BG  = "#0c1222";  C_EYE_ACC  = "#22d3ee";  C_CD       = "#fbbf24"
C_W_BG    = "#1a1a2e";  C_W_GL     = "#0ea5e9"
C_OK      = "#22c55e";  C_ERR      = "#ef4444"

TICK = 10   # scheduler tick (seconds)

# ─── Test Mode Intervals ─────────────────────────────────────
if TEST_MODE:
    print("\n  ⚠  TEST MODE: Using short intervals")
    print("      Eye rest: 1 min, Micro-pause: 2 min\n")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class ScreenBreakApp:

    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()

        self.config = load_config()
        self.notes  = self._load_notes()
        self.stats  = load_stats()
        update_stats_for_today(self.stats)

        self.paused = False;  self.low_energy = False
        self.pause_started = None  # Track when pause began for timer adjustment
        self.idle = False;  self.idle_since = None  # Idle detection state
        self.overlay_up = False;  self.warning_up = False
        self.current_overlay = None;  self.warning_window = None
        self.pending_break = None;  self.snooze_until = None
        self.last_eye_rest = datetime.datetime.now()
        self.last_micro    = datetime.datetime.now()
        self.last_any_break = datetime.datetime.now()
        self.acked_today   = {};  self.today = datetime.date.today()
        self._warn_anim_id = None;  self._warn_rem = 0;  self._warn_total = 0
        self._status_win = None;  self._tip = None;  self._stats_win = None

        if HAS_TRAY:
            threading.Thread(target=self._run_tray, daemon=True).start()

        self.last_mini_reminder = datetime.datetime.now()
        self._mini_win = None
        self._pomodoro_count = 0  # Track pomodoro sessions for long break timing

        self._print_schedule()
        self._show_startup()
        self._start_idle_monitor()
        self._start_mini_reminders()
        self._tick()
        self.root.mainloop()

    def _start_mini_reminders(self) -> None:
        """Start mini reminder system (posture, hydration, blink nudges)."""
        def check_mini():
            if not self.config.get("mini_reminders", False):
                self.root.after(60000, check_mini)  # Check again in 1 min
                return
            if self.paused or self.idle or self.overlay_up or self.warning_up:
                self.root.after(60000, check_mini)
                return

            interval = self.config.get("mini_reminder_interval", 10)
            elapsed = (datetime.datetime.now() - self.last_mini_reminder).total_seconds() / 60

            if elapsed >= interval:
                self._show_mini_reminder()
                self.last_mini_reminder = datetime.datetime.now()

            self.root.after(60000, check_mini)  # Check every minute

        self.root.after(60000, check_mini)

    def _show_mini_reminder(self) -> None:
        """Show a brief mini reminder popup."""
        if self._mini_win:
            try:
                self._mini_win.destroy()
            except tk.TclError:
                pass

        emoji, title, desc = get_mini_reminder()

        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        try:
            win.attributes("-alpha", 0.95)
        except tk.TclError:
            pass
        win.configure(bg=C_CARD)

        # Position in bottom-right corner
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        w, h = 280, 70
        win.geometry(f"{w}x{h}+{sw-w-20}+{sh-h-60}")

        f = tk.Frame(win, bg=C_CARD, padx=12, pady=8)
        f.pack(fill="both", expand=True)

        tk.Label(f, text=f"{emoji}  {title}", font=(FONT, 11, "bold"),
                 fg=C_ACCENT2, bg=C_CARD).pack(anchor="w")
        tk.Label(f, text=desc, font=(FONT, 9), fg=C_TEXT_DIM, bg=C_CARD).pack(anchor="w")

        self._mini_win = win

        # Auto-dismiss after 4 seconds
        def dismiss():
            try:
                win.destroy()
            except tk.TclError:
                pass
            self._mini_win = None
        win.after(4000, dismiss)
        win.bind("<Button-1>", lambda e: dismiss())

    def _start_idle_monitor(self) -> None:
        """Start idle detection monitoring."""
        def check_idle():
            if not self.config.get("idle_detection", True):
                self.idle = False
                self.root.after(IDLE_CHECK_INTERVAL * 1000, check_idle)
                return

            threshold = self.config.get("idle_threshold", DEFAULT_IDLE_THRESHOLD)
            idle_secs = get_idle_seconds()

            was_idle = self.idle
            self.idle = idle_secs >= threshold

            if self.idle and not was_idle:
                # Just became idle - record when
                self.idle_since = datetime.datetime.now()
            elif not self.idle and was_idle and self.idle_since:
                # Returned from idle - adjust timers
                idle_duration = datetime.datetime.now() - self.idle_since
                self.last_eye_rest += idle_duration
                self.last_micro += idle_duration
                self.last_any_break += idle_duration
                self.idle_since = None

            self.root.after(IDLE_CHECK_INTERVAL * 1000, check_idle)

        self.root.after(IDLE_CHECK_INTERVAL * 1000, check_idle)

    # ━━━ Properties ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    @property
    def eye_iv(self) -> float:
        """Eye rest interval in minutes (adjusted for low energy and pomodoro mode)."""
        if self.config.get("pomodoro_mode", False):
            return 25.0  # Pomodoro: eye rest every 25 min (with the break)
        b = self.config.get("eye_rest_interval", 20)
        return b * (self.config.get("low_energy_multiplier", 1.5) if self.low_energy else 1.0)

    @property
    def micro_iv(self) -> float:
        """Micro-pause interval in minutes (adjusted for low energy and pomodoro mode)."""
        if self.config.get("pomodoro_mode", False):
            return 25.0  # Pomodoro: 25 min work sessions
        b = self.config.get("micro_pause_interval", 45)
        return b * (self.config.get("low_energy_multiplier", 1.5) if self.low_energy else 1.0)

    @property
    def pomodoro_break_duration(self) -> int:
        """Pomodoro break duration in minutes (5 regular, 15 every 4th)."""
        if hasattr(self, '_pomodoro_count'):
            if self._pomodoro_count > 0 and self._pomodoro_count % 4 == 0:
                return 15  # Long break every 4 pomodoros
        return 5  # Regular short break

    @staticmethod
    def _pt(s: str) -> datetime.time:
        """Parse time string (HH:MM) to datetime.time. Raises ValueError if invalid."""
        h, m = s.strip().split(":")
        return datetime.time(int(h), int(m))

    @staticmethod
    def _fmt12(s: str) -> str:
        """Convert HH:MM string to 12-hour format (e.g., '14:30' -> '2:30 PM')."""
        try:
            h, m = s.strip().split(":")
            h, m = int(h), int(m)
            suffix = "AM" if h < 12 else "PM"
            h12 = h % 12
            if h12 == 0:
                h12 = 12
            return f"{h12}:{m:02d} {suffix}"
        except (ValueError, AttributeError):
            return s

    # ━━━ Scheduling ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    def _tick(self):
        if not self.paused and not self.overlay_up and not self.warning_up and not self.idle:
            self._check()
        self.root.after(TICK * 1000, self._tick)

    def _check(self) -> None:
        now = datetime.datetime.now()
        t = now.time()

        if now.date() != self.today:
            self.today = now.date()
            self.acked_today.clear()

        try:
            ws = self._pt(self.config.get("work_start", "08:00"))
            we = self._pt(self.config.get("work_end",   "20:00"))
        except ValueError:
            ws, we = datetime.time(8), datetime.time(20)
        if t < ws or t > we:
            return

        if self.snooze_until and now < self.snooze_until:
            return
        self.snooze_until = None

        # ── Sleep/wake detection ──
        # If >2 hours since last check, assume laptop slept; reset timers
        # This prevents all breaks firing at once after laptop wakes
        since_last = (now - self.last_any_break).total_seconds() / 60
        if since_last > SLEEP_DETECTION_MINUTES:
            self._reset_all_timers()
            return

        # Handle backward time jump (system clock adjusted)
        if since_last < 0:
            self._reset_all_timers()
            return

        # ── Enforce minimum gap between ANY breaks ──
        min_gap = self.config.get("minimum_break_gap", 20)
        if since_last < min_gap:
            return

        warn_s = self.config.get("warning_seconds", 60)

        # ── Helper: check if scheduled break is within N minutes ──
        def sched_within(minutes: float) -> bool:
            for brk in self.config.get("breaks", []):
                if self.acked_today.get(brk["time"]) == now.date():
                    continue
                try:
                    bt = datetime.datetime.combine(now.date(), self._pt(brk["time"]))
                    diff = (bt - now).total_seconds() / 60
                    if 0 < diff <= minutes:
                        return True
                except ValueError:
                    continue
            return False

        # ── Priority 1: Scheduled breaks ──
        for brk in self.config.get("breaks", []):
            key = brk["time"]
            if self.acked_today.get(key) == now.date():
                continue
            try:
                bt = datetime.datetime.combine(now.date(), self._pt(brk["time"]))
            except ValueError:
                continue
            diff = (bt - now).total_seconds()

            if 0 < diff <= warn_s:
                self._begin_warning(self._show_long_break,
                    (brk["title"], brk["duration"], key), max(5, int(diff)))
                return
            if -CATCHUP_WINDOW_SECONDS <= diff <= 0:
                self._begin_warning(self._show_long_break,
                    (brk["title"], brk["duration"], key), 5)
                return

        # ── Priority 2: Micro-pause (skip if scheduled break within coast margin) ──
        el_mp = (now - self.last_micro).total_seconds() / 60
        if el_mp >= self.micro_iv:
            if not sched_within(COAST_MARGIN_MINUTES):
                self._begin_warning(self._show_micro, (), min(30, warn_s))
                return

        # ── Priority 3: Eye rest (skip if scheduled break within coast margin) ──
        el_er = (now - self.last_eye_rest).total_seconds() / 60
        if el_er >= self.eye_iv:
            # Also skip if micro-pause is due very soon
            if not sched_within(COAST_MARGIN_MINUTES) and el_mp < (self.micro_iv - COAST_MARGIN_MINUTES):
                self._begin_warning(self._show_eye_rest, (), warn_s)
                return

    # Reset all timers — used for micro-pauses and scheduled breaks (actual movement)
    # Eye rest uses its own logic since looking away doesn't count as movement
    def _reset_all_timers(self):
        now = datetime.datetime.now()
        self.last_eye_rest = now
        self.last_micro = now
        self.last_any_break = now

    # ━━━ Advance Warning ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    def _begin_warning(self, cb: Callable, args: tuple, countdown: int = 60) -> None:
        self.warning_up = True
        self.pending_break = (cb, args)
        self._warn_rem = countdown;  self._warn_total = countdown

        w = tk.Toplevel(self.root)
        w.overrideredirect(True);  w.attributes("-topmost", True)
        try:
            w.attributes("-alpha", 0.92)
        except tk.TclError:
            pass
        w.configure(bg=C_W_BG)

        sz, mg = WARNING_ICON_SIZE, WARNING_ICON_MARGIN
        sw = w.winfo_screenwidth()
        w.geometry(f"{sz}x{sz}+{sw-sz-mg}+{mg}")

        c = tk.Canvas(w, width=sz, height=sz, bg=C_W_BG, highlightthickness=0, cursor="hand2")
        c.pack()
        cx, cy, r = sz//2, sz//2, 20
        self._draw_clock(c, cx, cy, r, countdown, countdown)
        c.bind("<Button-1>", lambda e: self._dismiss_warning())

        self._tip = None
        def s_tip(e):
            self._tip = tk.Toplevel(w);  self._tip.overrideredirect(True)
            self._tip.attributes("-topmost", True);  self._tip.configure(bg=C_CARD)
            self._tip.geometry(f"210x28+{sw-sz-mg-220}+{mg+sz+4}")
            tk.Label(self._tip, text=f"Break in ~{self._warn_rem}s — click to go now",
                     font=(FONT, 9), fg=C_TEXT_DIM, bg=C_CARD, padx=6).pack(fill="both", expand=True)
        def h_tip(e):
            if self._tip:
                try:
                    self._tip.destroy()
                except tk.TclError:
                    pass
                self._tip = None
        c.bind("<Enter>", s_tip);  c.bind("<Leave>", h_tip)

        self.warning_window = w
        self._anim_warning(c, cx, cy, r)

    def _draw_clock(self, c, cx, cy, r, rem, tot):
        c.delete("all")
        gr = r + 5
        c.create_oval(cx-gr, cy-gr, cx+gr, cy+gr, fill="", outline=C_W_GL, width=1)
        c.create_oval(cx-r, cy-r, cx+r, cy+r, fill=C_CARD, outline=C_W_GL, width=2)
        if tot > 0:
            # Stopwatch style: fill clockwise as time elapses (not counter-clockwise drain)
            elapsed = tot - rem
            ext = (elapsed / tot) * 360
            c.create_arc(cx-r+4, cy-r+4, cx+r-4, cy+r-4,
                         start=90, extent=-ext, fill=C_W_GL, outline="", stipple="gray50")
        c.create_line(cx, cy, cx, cy-r+7, fill=C_TEXT, width=2)
        hx = cx + int((r-9)*math.sin(math.radians(60)))
        hy = cy - int((r-9)*math.cos(math.radians(60)))
        c.create_line(cx, cy, hx, hy, fill=C_TEXT, width=2)
        c.create_oval(cx-2, cy-2, cx+2, cy+2, fill=C_TEXT, outline="")

    def _anim_warning(self, c: tk.Canvas, cx: int, cy: int, r: int) -> None:
        if not self.warning_up or not self.warning_window:
            return
        if self._warn_rem <= 0:
            self._fire_pending();  return
        self._draw_clock(c, cx, cy, r, self._warn_rem, self._warn_total)
        phase = (self._warn_total - self._warn_rem) % 4 / 4.0
        alpha = 0.82 + 0.13 * math.sin(phase * 2 * math.pi)
        try:
            self.warning_window.attributes("-alpha", alpha)
        except tk.TclError:
            pass
        self._warn_rem -= 1
        self._warn_anim_id = self.root.after(1000, lambda: self._anim_warning(c, cx, cy, r))

    def _dismiss_warning(self) -> None:
        if self._warn_anim_id:
            try:
                self.root.after_cancel(self._warn_anim_id)
            except tk.TclError:
                pass
            self._warn_anim_id = None
        if self._tip:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None
        if self.warning_window:
            try:
                self.warning_window.destroy()
            except tk.TclError:
                pass
            self.warning_window = None
        self.root.after(100, self._fire_pending_safe)

    def _fire_pending_safe(self) -> None:
        if self.pending_break and self.warning_up:
            self._fire_pending()

    def _fire_pending(self) -> None:
        self.warning_up = False;  self._warn_anim_id = None
        if self._tip:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None
        if self.warning_window:
            try:
                self.warning_window.destroy()
            except tk.TclError:
                pass
            self.warning_window = None
        if self.pending_break:
            cb, args = self.pending_break;  self.pending_break = None
            cb(*args)

    # ━━━ Overlays ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _centre(self, ov: tk.Toplevel, w: int, h: int) -> None:
        sw, sh = ov.winfo_screenwidth(), ov.winfo_screenheight()
        ov.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    def _btn(self, p: tk.Frame, text: str, bg: str, cmd: Callable, bold: bool = False) -> tk.Button:
        wt = "bold" if bold else "normal"
        b = tk.Button(p, text=text, font=(FONT, 10, wt), bg=bg, fg=C_TEXT,
                      relief="flat", padx=18, pady=5, cursor="hand2", command=cmd)
        b.pack(side="left", padx=6)
        return b

    def _dismiss(self, ov: tk.Toplevel) -> None:
        self.overlay_up = False
        self.current_overlay = None
        try:
            ov.destroy()
        except tk.TclError:
            pass

    def _snooze(self, ov: tk.Toplevel) -> None:
        sm = self.config.get("snooze_minutes", 5)
        self.snooze_until = datetime.datetime.now() + datetime.timedelta(minutes=sm)
        self._dismiss(ov)

    # ── Eye rest (fullscreen, enforced) ────────────────────
    def _show_eye_rest(self) -> None:
        self.overlay_up = True
        # NOTE: last_eye_rest is set when user CLOSES the overlay, not now
        dur = self.config.get("eye_rest_duration", 20)

        # Play sound notification
        if self.config.get("sound_enabled", True):
            play_sound("chime")

        ov = tk.Toplevel(self.root)
        ov.attributes("-topmost", True)
        ov.configure(bg=C_EYE_BG)

        # Fullscreen
        sw = ov.winfo_screenwidth()
        sh = ov.winfo_screenheight()
        ov.geometry(f"{sw}x{sh}+0+0")
        ov.overrideredirect(True)
        if IS_MAC:
            ov.lift()
            ov.focus_force()

        # Screen dimming effect - start transparent and fade in
        use_dim = self.config.get("screen_dim", True)
        if use_dim:
            try:
                ov.attributes("-alpha", 0.0)
            except tk.TclError:
                use_dim = False

        # Center content frame
        cf = tk.Frame(ov, bg=C_EYE_BG)
        cf.place(relx=0.5, rely=0.5, anchor="center")

        # Fade in animation
        if use_dim:
            def fade_in(alpha=0.0):
                if alpha < 0.92:
                    try:
                        ov.attributes("-alpha", alpha)
                        ov.after(30, lambda: fade_in(alpha + 0.05))
                    except tk.TclError:
                        pass
                else:
                    try:
                        ov.attributes("-alpha", 0.92)
                    except tk.TclError:
                        pass
            ov.after(50, lambda: fade_in(0.0))

        tk.Label(cf, text="🌿", font=(FONT, 56), fg=C_EYE_ACC, bg=C_EYE_BG).pack(pady=(0, 16))
        tk.Label(cf, text="Look away — 20 feet or more", font=(FONT, 28, "bold"),
                 fg=C_EYE_ACC, bg=C_EYE_BG).pack(pady=(0, 16))

        # Show eye exercise if enabled
        if self.config.get("show_exercises", True):
            exercise = get_exercise("eye")
            hint_text = f"👁 {exercise}"
        else:
            hint_text = "Rest your eyes on something distant.\nBlink slowly. Let your focus soften."
        tk.Label(cf, text=hint_text, font=(FONT, 14), fg=C_TEXT_DIM, bg=C_EYE_BG,
                 justify="center", wraplength=600).pack(pady=(0, 30))

        # Countdown / button container
        self._eye_cd_frame = tk.Frame(cf, bg=C_EYE_BG)
        self._eye_cd_frame.pack()

        self._eye_cd_var = tk.StringVar(value=str(dur))
        self._eye_cd_label = tk.Label(self._eye_cd_frame, textvariable=self._eye_cd_var,
                                       font=(FONT, 64, "bold"), fg=C_CD, bg=C_EYE_BG)
        self._eye_cd_label.pack()

        # Button (hidden initially, will replace countdown)
        self._eye_close_btn = tk.Button(self._eye_cd_frame, text="  Continue  ",
                                         font=(FONT, 16, "bold"), bg=C_BTN_PRI, fg=C_TEXT,
                                         relief="flat", padx=32, pady=12, cursor="hand2",
                                         command=lambda: self._close_eye_rest(ov, completed=True))
        # Don't pack yet — will appear after countdown

        self.current_overlay = ov
        self._eye_countdown(ov, dur)

        # Escape closes after countdown (same as button)
        def on_escape(e):
            if not self._eye_close_btn.winfo_ismapped():
                return  # countdown still running, ignore
            self._close_eye_rest(ov, completed=True)
        ov.bind("<Escape>", on_escape)
        ov.focus_set()

    def _eye_countdown(self, ov, rem):
        if self.current_overlay != ov:
            return
        if rem <= 0:
            # Countdown done — hide number, show button
            self._eye_cd_label.pack_forget()
            self._eye_close_btn.pack()
            return
        self._eye_cd_var.set(str(rem))
        ov.after(1000, lambda: self._eye_countdown(ov, rem - 1))

    def _close_eye_rest(self, ov, completed: bool = False):
        # Eye rest only resets eye timer and 20-min gap
        # Does NOT reset micro-pause — looking away isn't the same as standing up
        now = datetime.datetime.now()
        self.last_eye_rest = now
        self.last_any_break = now
        # Track statistics
        if completed:
            self.stats["lifetime"]["eye_rest_taken"] = self.stats["lifetime"].get("eye_rest_taken", 0) + 1
            self.stats["today"]["eye_rest_taken"] = self.stats["today"].get("eye_rest_taken", 0) + 1
        else:
            self.stats["lifetime"]["eye_rest_skipped"] = self.stats["lifetime"].get("eye_rest_skipped", 0) + 1
        save_stats(self.stats)
        self._dismiss(ov)

    # ── Micro-pause ───────────────────────────────────────────
    def _show_micro(self) -> None:
        self.overlay_up = True
        # NOTE: timers reset when user clicks "Back from break", not now
        iv = int(self.micro_iv)

        # Play sound notification
        if self.config.get("sound_enabled", True):
            play_sound("chime")

        ov = tk.Toplevel(self.root)
        ov.overrideredirect(True);  ov.attributes("-topmost", True)
        ov.configure(bg=C_BG);  self._centre(ov, 500, 380)
        if IS_MAC: ov.lift()

        card = tk.Frame(ov, bg=C_CARD, padx=32, pady=22)
        card.pack(fill="both", expand=True, padx=2, pady=2)

        tk.Label(card, text="🧘  Time to move", font=(FONT, 16, "bold"),
                 fg=C_ACCENT, bg=C_CARD).pack(pady=(0, 10))

        # Show exercise suggestion if enabled
        if self.config.get("show_exercises", True):
            exercise = get_exercise("stretch")
            body = f"~{iv} minutes of focus — well done.\n\n💪 {exercise}"
        elif self.low_energy:
            body = (f"~{iv} minutes since last movement.\n\n"
                    "Roll your shoulders, flex your wrists,\nor stand for a moment.")
        else:
            body = (f"~{iv} minutes of focus — well done.\n\n"
                    "Stand up. Stretch wrists, neck, back.\n"
                    "Walk to the window or refill water.\n5 min — your work will be here.")
        tk.Label(card, text=body, font=(FONT, 10), fg=C_TEXT_DIM, bg=C_CARD,
                 justify="center", wraplength=420).pack(pady=(0, 8))
        tk.Label(card, text=datetime.datetime.now().strftime("%I:%M %p").lstrip("0"),
                 font=(FONT, 9), fg=C_TEXT_MUT, bg=C_CARD).pack(pady=(0, 6))

        # Countdown timer (5 minutes)
        self._micro_cd_var = tk.StringVar(value="5:00")
        tk.Label(card, textvariable=self._micro_cd_var,
                 font=(MONO, 28, "bold"), fg=C_CD, bg=C_CARD).pack(pady=(0, 10))

        bf = tk.Frame(card, bg=C_CARD);  bf.pack()
        sm = self.config.get("snooze_minutes", 5)

        def back_from_break():
            # Track statistics
            self.stats["lifetime"]["micro_taken"] = self.stats["lifetime"].get("micro_taken", 0) + 1
            self.stats["today"]["micro_taken"] = self.stats["today"].get("micro_taken", 0) + 1
            save_stats(self.stats)
            # Track pomodoro count for long break timing
            if self.config.get("pomodoro_mode", False):
                self._pomodoro_count += 1
            self._reset_all_timers()
            self._dismiss(ov)

        def skip_break():
            self.stats["lifetime"]["micro_skipped"] = self.stats["lifetime"].get("micro_skipped", 0) + 1
            save_stats(self.stats)
            self._reset_all_timers()
            self._dismiss(ov)

        self._btn(bf, "  Back from break  ", C_BTN_PRI, back_from_break)
        # In strict mode, only show snooze (no skip option via Escape)
        self._btn(bf, f"  {sm} more min  ", C_BTN_SEC, lambda: self._snooze(ov))
        self.current_overlay = ov

        # Start the 5-minute countdown
        self._micro_countdown(ov, 5 * 60)

        # Escape = back from break (unless strict mode)
        if self.config.get("strict_mode", False):
            ov.bind("<Escape>", lambda e: None)  # Disable escape in strict mode
        else:
            ov.bind("<Escape>", lambda e: skip_break())
        ov.focus_set()

    def _micro_countdown(self, ov, rem):
        if self.current_overlay != ov:
            return
        if rem < 0:
            rem = 0
        m, s = divmod(rem, 60)
        self._micro_cd_var.set(f"{m}:{s:02d}")
        if rem > 0:
            ov.after(1000, lambda: self._micro_countdown(ov, rem - 1))

    # ── Long / scheduled break ────────────────────────────────
    def _show_long_break(self, title: str, duration: int, break_key: str) -> None:
        self.overlay_up = True
        # NOTE: timers reset when user clicks "Back from break", not now

        # Play sound notification
        if self.config.get("sound_enabled", True):
            play_sound("chime")

        ov = tk.Toplevel(self.root)
        ov.overrideredirect(True);  ov.attributes("-topmost", True)
        ov.configure(bg=C_BG);  self._centre(ov, 560, 460)
        if IS_MAC: ov.lift();  ov.focus_force()

        card = tk.Frame(ov, bg=C_CARD, padx=32, pady=20)
        card.pack(fill="both", expand=True, padx=2, pady=2)
        dl = f" — {duration} min" if duration > 0 else ""
        tk.Label(card, text=f"⏸  {title}{dl}", font=(FONT, 17, "bold"),
                 fg=C_ACCENT, bg=C_CARD).pack(pady=(0, 10))
        body = get_desc(title, self.low_energy)

        # Add movement suggestion if enabled
        if self.config.get("show_exercises", True) and duration >= 10:
            exercise = get_exercise("move")
            body = body + f"\n\n🚶 {exercise}"

        tk.Label(card, text=body, font=(FONT, 11), fg=C_TEXT_DIM, bg=C_CARD,
                 justify="center", wraplength=460).pack(pady=(0, 10))

        tk.Label(card, text="Capture where you are (optional):",
                 font=(FONT, 9), fg=C_TEXT_MUT, bg=C_CARD, anchor="w").pack(fill="x", pady=(6, 2))
        note = tk.Text(card, height=3, font=(MONO, 10), bg=C_CARD_IN, fg=C_TEXT,
                       insertbackground=C_TEXT, relief="flat", padx=8, pady=6, wrap="word")
        note.pack(fill="x", pady=(0, 10))

        tk.Label(card, text=datetime.datetime.now().strftime("%I:%M %p").lstrip("0"),
                 font=(FONT, 9), fg=C_TEXT_MUT, bg=C_CARD).pack(pady=(0, 8))
        bf = tk.Frame(card, bg=C_CARD);  bf.pack()
        sm = self.config.get("snooze_minutes", 5)

        def back_from_break():
            self._grab_note(note)
            self.acked_today[break_key] = datetime.date.today()
            # Track statistics
            self.stats["lifetime"]["scheduled_taken"] = self.stats["lifetime"].get("scheduled_taken", 0) + 1
            self.stats["today"]["scheduled_taken"] = self.stats["today"].get("scheduled_taken", 0) + 1
            save_stats(self.stats)
            self._reset_all_timers()
            self._dismiss(ov)

        def skip_break():
            self.acked_today[break_key] = datetime.date.today()
            self.stats["lifetime"]["scheduled_skipped"] = self.stats["lifetime"].get("scheduled_skipped", 0) + 1
            save_stats(self.stats)
            self._reset_all_timers()
            self._dismiss(ov)

        def snz():
            self._grab_note(note);  self._snooze(ov)

        self._btn(bf, "  Back from break  ", C_BTN_PRI, back_from_break, bold=True)
        self._btn(bf, f"  {sm} more min  ", C_BTN_SEC, snz)
        self.current_overlay = ov

        # Escape = skip break (unless strict mode)
        if self.config.get("strict_mode", False):
            ov.bind("<Escape>", lambda e: None)  # Disable escape in strict mode
        else:
            ov.bind("<Escape>", lambda e: skip_break())
        ov.focus_set()

    # ━━━ Notes ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _grab_note(self, w: tk.Text) -> None:
        text = w.get("1.0", "end").strip()
        if not text:
            return
        self.notes.append({"time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "note": text})
        try:
            with open(NOTES_FILE, "w", encoding="utf-8") as f:
                json.dump(self.notes, f, indent=2)
        except (IOError, OSError) as e:
            print(f"  ⚠ Notes save error: {e}")

    def _load_notes(self) -> list[dict[str, str]]:
        if os.path.exists(NOTES_FILE):
            try:
                with open(NOTES_FILE, encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
            except (json.JSONDecodeError, IOError, OSError):
                pass
        return []

    def _show_notes_win(self) -> None:
        win = tk.Toplevel(self.root)
        win.title("Screen Break — Notes")
        win.geometry("580x450")
        win.configure(bg=C_BG)

        tk.Label(win, text="Saved Notes", font=(FONT, 15, "bold"),
                 fg=C_ACCENT2, bg=C_BG).pack(pady=(14, 8))

        fr = tk.Frame(win, bg=C_BG)
        fr.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        sb = tk.Scrollbar(fr)
        sb.pack(side="right", fill="y")
        txt = tk.Text(fr, font=(MONO, 10), bg=C_CARD, fg=C_TEXT,
                      relief="flat", padx=12, pady=10, wrap="word", yscrollcommand=sb.set)
        txt.pack(fill="both", expand=True)
        sb.config(command=txt.yview)

        if not self.notes:
            txt.insert("end", "No notes yet.\n\nNotes captured during break prompts appear here.")
        else:
            for e in reversed(self.notes):
                txt.insert("end", f"── {e['time']} ──\n{e['note']}\n\n")
        txt.configure(state="disabled")

        bf = tk.Frame(win, bg=C_BG)
        bf.pack(pady=(0, 12))

        def clear_notes() -> None:
            if not self.notes:
                return
            # Show confirmation dialog
            confirm = tk.Toplevel(win)
            confirm.title("Confirm Clear")
            confirm.configure(bg=C_CARD)
            confirm.geometry("300x120")
            confirm.transient(win)
            confirm.grab_set()
            # Center on parent
            confirm.geometry(f"+{win.winfo_x() + 140}+{win.winfo_y() + 150}")

            tk.Label(confirm, text=f"Delete all {len(self.notes)} notes?",
                     font=(FONT, 11, "bold"), fg=C_TEXT, bg=C_CARD).pack(pady=(16, 8))
            tk.Label(confirm, text="This cannot be undone.",
                     font=(FONT, 9), fg=C_TEXT_DIM, bg=C_CARD).pack(pady=(0, 12))

            btn_frame = tk.Frame(confirm, bg=C_CARD)
            btn_frame.pack()

            def do_clear():
                self.notes.clear()
                try:
                    with open(NOTES_FILE, "w", encoding="utf-8") as f:
                        json.dump([], f)
                except (IOError, OSError):
                    pass
                txt.configure(state="normal")
                txt.delete("1.0", "end")
                txt.insert("end", "Notes cleared.")
                txt.configure(state="disabled")
                confirm.destroy()

            tk.Button(btn_frame, text="Delete All", font=(FONT, 9), bg=C_ACCENT, fg=C_TEXT,
                      relief="flat", padx=12, pady=4, cursor="hand2", command=do_clear).pack(side="left", padx=4)
            tk.Button(btn_frame, text="Cancel", font=(FONT, 9), bg=C_BTN_SEC, fg=C_TEXT,
                      relief="flat", padx=12, pady=4, cursor="hand2", command=confirm.destroy).pack(side="left", padx=4)

        def export_notes() -> None:
            if not self.notes:
                return
            export_path = os.path.join(os.path.expanduser("~"), "screen_break_notes.md")
            try:
                with open(export_path, "w", encoding="utf-8") as f:
                    f.write("# Screen Break Notes\n\n")
                    for e in self.notes:
                        f.write(f"## {e['time']}\n\n{e['note']}\n\n---\n\n")
                # Show brief confirmation
                txt.configure(state="normal")
                txt.insert("1.0", f"✓ Exported to {export_path}\n\n")
                txt.configure(state="disabled")
            except (IOError, OSError) as err:
                txt.configure(state="normal")
                txt.insert("1.0", f"⚠ Export failed: {err}\n\n")
                txt.configure(state="disabled")

        tk.Button(bf, text="Export .md", font=(FONT, 9), bg=C_BTN_SEC, fg=C_TEXT_DIM,
                  relief="flat", padx=12, pady=4, cursor="hand2", command=export_notes).pack(side="left", padx=4)
        tk.Button(bf, text="Clear All", font=(FONT, 9), bg=C_BTN_SEC, fg=C_TEXT_DIM,
                  relief="flat", padx=12, pady=4, cursor="hand2", command=clear_notes).pack(side="left", padx=4)
        tk.Button(bf, text="Close", font=(FONT, 10), bg=C_BTN_SEC, fg=C_TEXT,
                  relief="flat", padx=16, pady=4, cursor="hand2", command=win.destroy).pack(side="left", padx=4)

    # ━━━ Statistics Window ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _show_stats_win(self) -> None:
        if self._stats_win:
            try: self._stats_win.lift();  self._stats_win.focus_force();  return
            except tk.TclError: self._stats_win = None

        win = tk.Toplevel(self.root)
        win.title("Screen Break — Statistics")
        win.geometry("400x480")
        win.configure(bg=C_BG)
        self._stats_win = win

        # Refresh stats for today
        update_stats_for_today(self.stats)

        tk.Label(win, text="Your Break Statistics", font=(FONT, 15, "bold"),
                 fg=C_ACCENT2, bg=C_BG).pack(pady=(14, 12))

        # Today's stats
        tf = tk.Frame(win, bg=C_CARD, padx=16, pady=12)
        tf.pack(fill="x", padx=14, pady=(0, 8))
        tk.Label(tf, text="📅  Today", font=(FONT, 12, "bold"),
                 fg=C_TEXT, bg=C_CARD).pack(anchor="w")
        today = self.stats.get("today", {})
        today_text = (f"Eye rests taken: {today.get('eye_rest_taken', 0)}\n"
                      f"Micro-pauses taken: {today.get('micro_taken', 0)}\n"
                      f"Scheduled breaks taken: {today.get('scheduled_taken', 0)}")
        tk.Label(tf, text=today_text, font=(FONT, 10), fg=C_TEXT_DIM,
                 bg=C_CARD, justify="left").pack(anchor="w", pady=(4, 0))

        # Streak
        sf = tk.Frame(win, bg=C_CARD, padx=16, pady=12)
        sf.pack(fill="x", padx=14, pady=(0, 8))
        streak = self.stats.get("streak_days", 0)
        streak_emoji = "🔥" if streak >= 7 else "⭐" if streak >= 3 else "📊"
        tk.Label(sf, text=f"{streak_emoji}  Current Streak: {streak} day{'s' if streak != 1 else ''}",
                 font=(FONT, 12, "bold"), fg=C_CD if streak >= 3 else C_TEXT, bg=C_CARD).pack(anchor="w")
        tk.Label(sf, text="Take at least one break each day to maintain your streak!",
                 font=(FONT, 9), fg=C_TEXT_MUT, bg=C_CARD).pack(anchor="w", pady=(2, 0))

        # Lifetime stats
        lf = tk.Frame(win, bg=C_CARD, padx=16, pady=12)
        lf.pack(fill="x", padx=14, pady=(0, 8))
        tk.Label(lf, text="📈  Lifetime", font=(FONT, 12, "bold"),
                 fg=C_TEXT, bg=C_CARD).pack(anchor="w")
        lt = self.stats.get("lifetime", {})
        lt_text = (f"Eye rests: {lt.get('eye_rest_taken', 0)} taken, {lt.get('eye_rest_skipped', 0)} skipped\n"
                   f"Micro-pauses: {lt.get('micro_taken', 0)} taken, {lt.get('micro_skipped', 0)} skipped\n"
                   f"Scheduled breaks: {lt.get('scheduled_taken', 0)} taken, {lt.get('scheduled_skipped', 0)} skipped")
        tk.Label(lf, text=lt_text, font=(FONT, 10), fg=C_TEXT_DIM,
                 bg=C_CARD, justify="left").pack(anchor="w", pady=(4, 0))

        # Completion rate
        total_taken = (lt.get('eye_rest_taken', 0) + lt.get('micro_taken', 0) + lt.get('scheduled_taken', 0))
        total_skipped = (lt.get('eye_rest_skipped', 0) + lt.get('micro_skipped', 0) + lt.get('scheduled_skipped', 0))
        total = total_taken + total_skipped
        rate = (total_taken / total * 100) if total > 0 else 0
        rate_color = C_OK if rate >= 80 else C_CD if rate >= 50 else C_ACCENT
        tk.Label(lf, text=f"Completion rate: {rate:.0f}%", font=(FONT, 11, "bold"),
                 fg=rate_color, bg=C_CARD).pack(anchor="w", pady=(8, 0))

        # Buttons
        bf = tk.Frame(win, bg=C_BG)
        bf.pack(pady=12)

        def reset_stats():
            if not any(self.stats.get("lifetime", {}).values()):
                return
            confirm = tk.Toplevel(win)
            confirm.title("Confirm Reset")
            confirm.configure(bg=C_CARD)
            confirm.geometry("280x100")
            confirm.transient(win)
            confirm.grab_set()
            confirm.geometry(f"+{win.winfo_x() + 60}+{win.winfo_y() + 150}")
            tk.Label(confirm, text="Reset all statistics?", font=(FONT, 11, "bold"),
                     fg=C_TEXT, bg=C_CARD).pack(pady=(14, 6))
            cbf = tk.Frame(confirm, bg=C_CARD)
            cbf.pack()
            def do_reset():
                self.stats = json.loads(json.dumps(DEFAULT_STATS))
                save_stats(self.stats)
                confirm.destroy()
                win.destroy()
                self._stats_win = None
            tk.Button(cbf, text="Reset", font=(FONT, 9), bg=C_ACCENT, fg=C_TEXT,
                      relief="flat", padx=12, pady=4, cursor="hand2", command=do_reset).pack(side="left", padx=4)
            tk.Button(cbf, text="Cancel", font=(FONT, 9), bg=C_BTN_SEC, fg=C_TEXT,
                      relief="flat", padx=12, pady=4, cursor="hand2", command=confirm.destroy).pack(side="left", padx=4)

        tk.Button(bf, text="Reset Stats", font=(FONT, 9), bg=C_BTN_SEC, fg=C_TEXT_DIM,
                  relief="flat", padx=12, pady=4, cursor="hand2", command=reset_stats).pack(side="left", padx=4)
        tk.Button(bf, text="Close", font=(FONT, 10), bg=C_BTN_SEC, fg=C_TEXT,
                  relief="flat", padx=16, pady=4, cursor="hand2", command=win.destroy).pack(side="left", padx=4)

        def on_close():
            self._stats_win = None
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", on_close)

    # ━━━ Status & Settings Window ━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _show_status_window(self):
        if self._status_win:
            try: self._status_win.lift();  self._status_win.focus_force();  return
            except tk.TclError: self._status_win = None

        win = tk.Toplevel(self.root)
        win.title("Screen Break — Status & Settings")
        win.configure(bg=C_BG);  win.resizable(False, True)
        self._status_win = win

        pad = dict(padx=20)

        # ══════ LIVE COUNTDOWNS ══════
        tk.Label(win, text="Live Countdowns", font=(FONT, 13, "bold"),
                 fg=C_ACCENT2, bg=C_BG).pack(pady=(14, 8), **pad, anchor="w")

        self._st_rows = {}
        for key, icon in [("eye", "🌿  Eye rest"), ("micro", "🧘  Micro-pause"), ("sched", "📋  Next break")]:
            lf = tk.Frame(win, bg=C_CARD, padx=14, pady=8);  lf.pack(fill="x", pady=2, **pad)
            tk.Label(lf, text=icon, font=(FONT, 10), fg=C_TEXT_DIM, bg=C_CARD, anchor="w").pack(fill="x")
            tv = tk.StringVar(value="--:--")
            tk.Label(lf, textvariable=tv, font=(MONO, 18, "bold"), fg=C_CD, bg=C_CARD, anchor="w").pack(fill="x")
            dv = tk.StringVar()
            tk.Label(lf, textvariable=dv, font=(FONT, 9), fg=C_TEXT_MUT, bg=C_CARD, anchor="w").pack(fill="x")
            self._st_rows[key] = (tv, dv)

        # ══════ SETTINGS ══════
        tk.Frame(win, bg=C_TEXT_MUT, height=1).pack(fill="x", pady=(14, 6), **pad)
        tk.Label(win, text="Settings", font=(FONT, 13, "bold"),
                 fg=C_ACCENT2, bg=C_BG).pack(pady=(0, 8), **pad, anchor="w")

        # ── Intervals ──
        ivf = tk.Frame(win, bg=C_BG);  ivf.pack(fill="x", **pad)

        ef = tk.Frame(ivf, bg=C_BG);  ef.pack(fill="x", pady=2)
        tk.Label(ef, text="Eye rest every", font=(FONT, 10), fg=C_TEXT_DIM,
                 bg=C_BG, width=18, anchor="w").pack(side="left")
        self._eye_spin = tk.Spinbox(ef, from_=5, to=120, width=4,
            font=(MONO, 10), bg=C_CARD_IN, fg=C_TEXT, buttonbackground=C_BTN_SEC,
            relief="flat", justify="center")
        self._eye_spin.pack(side="left");  self._eye_spin.delete(0, "end")
        self._eye_spin.insert(0, str(self.config.get("eye_rest_interval", 20)))
        tk.Label(ef, text=" min", font=(FONT, 10), fg=C_TEXT_MUT, bg=C_BG).pack(side="left")

        mf = tk.Frame(ivf, bg=C_BG);  mf.pack(fill="x", pady=2)
        tk.Label(mf, text="Micro-pause every", font=(FONT, 10), fg=C_TEXT_DIM,
                 bg=C_BG, width=18, anchor="w").pack(side="left")
        self._micro_spin = tk.Spinbox(mf, from_=10, to=120, width=4,
            font=(MONO, 10), bg=C_CARD_IN, fg=C_TEXT, buttonbackground=C_BTN_SEC,
            relief="flat", justify="center")
        self._micro_spin.pack(side="left");  self._micro_spin.delete(0, "end")
        self._micro_spin.insert(0, str(self.config.get("micro_pause_interval", 45)))
        tk.Label(mf, text=" min", font=(FONT, 10), fg=C_TEXT_MUT, bg=C_BG).pack(side="left")

        # ── Additional settings ──
        gf = tk.Frame(ivf, bg=C_BG);  gf.pack(fill="x", pady=2)
        tk.Label(gf, text="Min gap between breaks", font=(FONT, 10), fg=C_TEXT_DIM,
                 bg=C_BG, width=18, anchor="w").pack(side="left")
        self._gap_spin = tk.Spinbox(gf, from_=0, to=60, width=4,
            font=(MONO, 10), bg=C_CARD_IN, fg=C_TEXT, buttonbackground=C_BTN_SEC,
            relief="flat", justify="center")
        self._gap_spin.pack(side="left");  self._gap_spin.delete(0, "end")
        self._gap_spin.insert(0, str(self.config.get("minimum_break_gap", 20)))
        tk.Label(gf, text=" min", font=(FONT, 10), fg=C_TEXT_MUT, bg=C_BG).pack(side="left")

        edf = tk.Frame(ivf, bg=C_BG);  edf.pack(fill="x", pady=2)
        tk.Label(edf, text="Eye rest duration", font=(FONT, 10), fg=C_TEXT_DIM,
                 bg=C_BG, width=18, anchor="w").pack(side="left")
        self._eye_dur_spin = tk.Spinbox(edf, from_=5, to=60, width=4,
            font=(MONO, 10), bg=C_CARD_IN, fg=C_TEXT, buttonbackground=C_BTN_SEC,
            relief="flat", justify="center")
        self._eye_dur_spin.pack(side="left");  self._eye_dur_spin.delete(0, "end")
        self._eye_dur_spin.insert(0, str(self.config.get("eye_rest_duration", 20)))
        tk.Label(edf, text=" sec", font=(FONT, 10), fg=C_TEXT_MUT, bg=C_BG).pack(side="left")

        sf = tk.Frame(ivf, bg=C_BG);  sf.pack(fill="x", pady=2)
        tk.Label(sf, text="Snooze duration", font=(FONT, 10), fg=C_TEXT_DIM,
                 bg=C_BG, width=18, anchor="w").pack(side="left")
        self._snooze_spin = tk.Spinbox(sf, from_=1, to=30, width=4,
            font=(MONO, 10), bg=C_CARD_IN, fg=C_TEXT, buttonbackground=C_BTN_SEC,
            relief="flat", justify="center")
        self._snooze_spin.pack(side="left");  self._snooze_spin.delete(0, "end")
        self._snooze_spin.insert(0, str(self.config.get("snooze_minutes", 5)))
        tk.Label(sf, text=" min", font=(FONT, 10), fg=C_TEXT_MUT, bg=C_BG).pack(side="left")

        warnf = tk.Frame(ivf, bg=C_BG);  warnf.pack(fill="x", pady=2)
        tk.Label(warnf, text="Warning before break", font=(FONT, 10), fg=C_TEXT_DIM,
                 bg=C_BG, width=18, anchor="w").pack(side="left")
        self._warn_spin = tk.Spinbox(warnf, from_=10, to=300, width=4,
            font=(MONO, 10), bg=C_CARD_IN, fg=C_TEXT, buttonbackground=C_BTN_SEC,
            relief="flat", justify="center")
        self._warn_spin.pack(side="left");  self._warn_spin.delete(0, "end")
        self._warn_spin.insert(0, str(self.config.get("warning_seconds", 60)))
        tk.Label(warnf, text=" sec", font=(FONT, 10), fg=C_TEXT_MUT, bg=C_BG).pack(side="left")

        # ── Work hours ──
        wf = tk.Frame(ivf, bg=C_BG);  wf.pack(fill="x", pady=2)
        tk.Label(wf, text="Work hours", font=(FONT, 10), fg=C_TEXT_DIM,
                 bg=C_BG, width=18, anchor="w").pack(side="left")
        self._ws_entry = tk.Entry(wf, width=6, font=(MONO, 10), bg=C_CARD_IN,
                                  fg=C_TEXT, relief="flat", justify="center")
        self._ws_entry.pack(side="left");  self._ws_entry.insert(0, self.config.get("work_start", "08:00"))
        tk.Label(wf, text=" to ", font=(FONT, 10), fg=C_TEXT_MUT, bg=C_BG).pack(side="left")
        self._we_entry = tk.Entry(wf, width=6, font=(MONO, 10), bg=C_CARD_IN,
                                  fg=C_TEXT, relief="flat", justify="center")
        self._we_entry.pack(side="left");  self._we_entry.insert(0, self.config.get("work_end", "20:00"))

        # ── Features ──
        tk.Frame(win, bg=C_TEXT_MUT, height=1).pack(fill="x", pady=(10, 6), **pad)
        tk.Label(win, text="Features", font=(FONT, 11, "bold"),
                 fg=C_TEXT_DIM, bg=C_BG).pack(pady=(0, 4), **pad, anchor="w")

        featf = tk.Frame(win, bg=C_BG);  featf.pack(fill="x", **pad)

        # Idle detection checkbox and threshold
        idf = tk.Frame(featf, bg=C_BG);  idf.pack(fill="x", pady=2)
        self._idle_var = tk.BooleanVar(value=self.config.get("idle_detection", True))
        tk.Checkbutton(idf, text="Pause when idle for", font=(FONT, 10), fg=C_TEXT_DIM,
                       bg=C_BG, variable=self._idle_var, selectcolor=C_CARD_IN,
                       activebackground=C_BG, activeforeground=C_TEXT_DIM).pack(side="left")
        self._idle_spin = tk.Spinbox(idf, from_=60, to=1800, width=4,
            font=(MONO, 10), bg=C_CARD_IN, fg=C_TEXT, buttonbackground=C_BTN_SEC,
            relief="flat", justify="center")
        self._idle_spin.pack(side="left");  self._idle_spin.delete(0, "end")
        self._idle_spin.insert(0, str(self.config.get("idle_threshold", 300)))
        tk.Label(idf, text=" sec", font=(FONT, 10), fg=C_TEXT_MUT, bg=C_BG).pack(side="left")

        # Sound checkbox
        sndf = tk.Frame(featf, bg=C_BG);  sndf.pack(fill="x", pady=2)
        self._sound_var = tk.BooleanVar(value=self.config.get("sound_enabled", True))
        tk.Checkbutton(sndf, text="Play sound when breaks start", font=(FONT, 10), fg=C_TEXT_DIM,
                       bg=C_BG, variable=self._sound_var, selectcolor=C_CARD_IN,
                       activebackground=C_BG, activeforeground=C_TEXT_DIM).pack(side="left")

        # Exercises checkbox
        exf = tk.Frame(featf, bg=C_BG);  exf.pack(fill="x", pady=2)
        self._exercises_var = tk.BooleanVar(value=self.config.get("show_exercises", True))
        tk.Checkbutton(exf, text="Show exercise suggestions during breaks", font=(FONT, 10), fg=C_TEXT_DIM,
                       bg=C_BG, variable=self._exercises_var, selectcolor=C_CARD_IN,
                       activebackground=C_BG, activeforeground=C_TEXT_DIM).pack(side="left")

        # Strict mode checkbox
        strf = tk.Frame(featf, bg=C_BG);  strf.pack(fill="x", pady=2)
        self._strict_var = tk.BooleanVar(value=self.config.get("strict_mode", False))
        tk.Checkbutton(strf, text="Strict mode (can't skip breaks, only snooze)", font=(FONT, 10), fg=C_TEXT_DIM,
                       bg=C_BG, variable=self._strict_var, selectcolor=C_CARD_IN,
                       activebackground=C_BG, activeforeground=C_TEXT_DIM).pack(side="left")

        # Screen dimming checkbox
        dimf = tk.Frame(featf, bg=C_BG);  dimf.pack(fill="x", pady=2)
        self._dim_var = tk.BooleanVar(value=self.config.get("screen_dim", True))
        tk.Checkbutton(dimf, text="Dim screen during eye rest (fade in effect)", font=(FONT, 10), fg=C_TEXT_DIM,
                       bg=C_BG, variable=self._dim_var, selectcolor=C_CARD_IN,
                       activebackground=C_BG, activeforeground=C_TEXT_DIM).pack(side="left")

        # Pomodoro mode checkbox
        pomf = tk.Frame(featf, bg=C_BG);  pomf.pack(fill="x", pady=2)
        self._pomo_var = tk.BooleanVar(value=self.config.get("pomodoro_mode", False))
        tk.Checkbutton(pomf, text="Pomodoro mode (25 min work / 5 min break)", font=(FONT, 10), fg=C_TEXT_DIM,
                       bg=C_BG, variable=self._pomo_var, selectcolor=C_CARD_IN,
                       activebackground=C_BG, activeforeground=C_TEXT_DIM).pack(side="left")

        # Mini reminders checkbox with interval
        minif = tk.Frame(featf, bg=C_BG);  minif.pack(fill="x", pady=2)
        self._mini_var = tk.BooleanVar(value=self.config.get("mini_reminders", False))
        tk.Checkbutton(minif, text="Mini reminders (posture, hydration) every", font=(FONT, 10), fg=C_TEXT_DIM,
                       bg=C_BG, variable=self._mini_var, selectcolor=C_CARD_IN,
                       activebackground=C_BG, activeforeground=C_TEXT_DIM).pack(side="left")
        self._mini_spin = tk.Spinbox(minif, from_=5, to=60, width=3,
            font=(MONO, 10), bg=C_CARD_IN, fg=C_TEXT, buttonbackground=C_BTN_SEC,
            relief="flat", justify="center")
        self._mini_spin.pack(side="left");  self._mini_spin.delete(0, "end")
        self._mini_spin.insert(0, str(self.config.get("mini_reminder_interval", 10)))
        tk.Label(minif, text=" min", font=(FONT, 10), fg=C_TEXT_MUT, bg=C_BG).pack(side="left")

        # ── Scheduled Breaks ──
        tk.Frame(win, bg=C_TEXT_MUT, height=1).pack(fill="x", pady=(10, 6), **pad)
        tk.Label(win, text="Scheduled Breaks  (local time)", font=(FONT, 11, "bold"),
                 fg=C_TEXT_DIM, bg=C_BG).pack(pady=(0, 4), **pad, anchor="w")

        hdr = tk.Frame(win, bg=C_BG);  hdr.pack(fill="x", **pad)
        tk.Label(hdr, text="Time", font=(FONT, 9), fg=C_TEXT_MUT, bg=C_BG, width=7, anchor="w").pack(side="left")
        tk.Label(hdr, text="Dur", font=(FONT, 9), fg=C_TEXT_MUT, bg=C_BG, width=5, anchor="w").pack(side="left")
        tk.Label(hdr, text="Name", font=(FONT, 9), fg=C_TEXT_MUT, bg=C_BG, anchor="w").pack(side="left", fill="x", expand=True)

        self._brk_container = tk.Frame(win, bg=C_BG)
        self._brk_container.pack(fill="x", **pad)
        self._brk_rows = []
        for brk in self.config.get("breaks", []):
            self._add_brk_row(brk["time"], brk["duration"], brk["title"])

        tk.Button(win, text="+ Add break", font=(FONT, 9), bg=C_BTN_SEC, fg=C_TEXT_DIM,
                  relief="flat", padx=10, pady=2, cursor="hand2",
                  command=lambda: self._add_brk_row("12:00", 15, "New Break")).pack(
                      pady=(4, 0), **pad, anchor="w")

        # ── Controls ──
        tk.Frame(win, bg=C_TEXT_MUT, height=1).pack(fill="x", pady=(10, 6), **pad)
        self._save_fb = tk.StringVar()
        tk.Label(win, textvariable=self._save_fb, font=(FONT, 9), fg=C_OK, bg=C_BG).pack(**pad, anchor="w")

        bf = tk.Frame(win, bg=C_BG);  bf.pack(fill="x", pady=(0, 4), **pad)
        tk.Button(bf, text="Apply & Save", font=(FONT, 10, "bold"), bg=C_BTN_PRI, fg=C_TEXT,
                  relief="flat", padx=16, pady=5, cursor="hand2",
                  command=self._apply_settings).pack(side="left")
        tk.Button(bf, text="Reset defaults", font=(FONT, 9), bg=C_BTN_SEC, fg=C_TEXT_DIM,
                  relief="flat", padx=12, pady=5, cursor="hand2",
                  command=self._reset_defaults).pack(side="left", padx=(8, 0))
        tk.Button(bf, text="Close", font=(FONT, 10), bg=C_BTN_SEC, fg=C_TEXT,
                  relief="flat", padx=16, pady=5, cursor="hand2",
                  command=self._close_status).pack(side="right")

        self._st_state = tk.StringVar()
        tk.Label(win, textvariable=self._st_state, font=(FONT, 9),
                 fg=C_TEXT_MUT, bg=C_BG).pack(pady=(0, 10), **pad, anchor="w")

        self._update_status()
        win.protocol("WM_DELETE_WINDOW", self._close_status)

    def _add_brk_row(self, time_s="12:00", dur=15, title="New Break"):
        rf = tk.Frame(self._brk_container, bg=C_BG)
        rf.pack(fill="x", pady=1)

        te = tk.Entry(rf, width=6, font=(MONO, 10), bg=C_CARD_IN, fg=C_TEXT,
                      relief="flat", justify="center")
        te.pack(side="left", padx=(0, 4));  te.insert(0, time_s)

        ds = tk.Spinbox(rf, from_=0, to=180, width=4, font=(MONO, 10),
                        bg=C_CARD_IN, fg=C_TEXT, buttonbackground=C_BTN_SEC,
                        relief="flat", justify="center")
        ds.pack(side="left", padx=(0, 2));  ds.delete(0, "end");  ds.insert(0, str(dur))
        tk.Label(rf, text="m ", font=(FONT, 9), fg=C_TEXT_MUT, bg=C_BG).pack(side="left")

        ne = tk.Entry(rf, font=(FONT, 10), bg=C_CARD_IN, fg=C_TEXT, relief="flat")
        ne.pack(side="left", fill="x", expand=True, padx=(0, 4));  ne.insert(0, title)

        row = {"frame": rf, "time": te, "dur": ds, "title": ne}

        def rm():
            rf.destroy();  self._brk_rows.remove(row)
        tk.Button(rf, text="×", font=(FONT, 10, "bold"), bg=C_BG, fg=C_ACCENT,
                  relief="flat", width=2, cursor="hand2", command=rm).pack(side="left")

        self._brk_rows.append(row)

    def _apply_settings(self) -> None:
        try:
            eye = int(self._eye_spin.get())
            micro = int(self._micro_spin.get())
            gap = int(self._gap_spin.get())
            eye_dur = int(self._eye_dur_spin.get())
            snooze = int(self._snooze_spin.get())
            warn_sec = int(self._warn_spin.get())
            idle_threshold = int(self._idle_spin.get())

            if eye < 1 or micro < 1:
                self._save_fb.set("⚠ Intervals must be ≥ 1 min");  return
            if eye_dur < 5:
                self._save_fb.set("⚠ Eye rest duration must be ≥ 5 sec");  return
            if snooze < 1:
                self._save_fb.set("⚠ Snooze must be ≥ 1 min");  return
            if warn_sec < 10:
                self._save_fb.set("⚠ Warning must be ≥ 10 sec");  return
            if idle_threshold < 60:
                self._save_fb.set("⚠ Idle threshold must be ≥ 60 sec");  return

            ws = self._ws_entry.get().strip()
            we = self._we_entry.get().strip()
            for ts in [ws, we]:
                h, m = ts.split(":")
                assert 0 <= int(h) <= 23 and 0 <= int(m) <= 59

            breaks = []
            for row in self._brk_rows:
                t = row["time"].get().strip()
                d = int(row["dur"].get())
                n = row["title"].get().strip()
                if not t or not n:
                    continue
                h, m = t.split(":")
                assert 0 <= int(h) <= 23 and 0 <= int(m) <= 59
                breaks.append({"time": f"{int(h):02d}:{int(m):02d}", "duration": d, "title": n})

            breaks.sort(key=lambda b: b["time"])

            self.config["eye_rest_interval"] = eye
            self.config["micro_pause_interval"] = micro
            self.config["minimum_break_gap"] = gap
            self.config["eye_rest_duration"] = eye_dur
            self.config["snooze_minutes"] = snooze
            self.config["warning_seconds"] = warn_sec
            self.config["work_start"] = ws
            self.config["work_end"] = we
            self.config["breaks"] = breaks
            # New feature settings
            self.config["idle_detection"] = self._idle_var.get()
            self.config["idle_threshold"] = idle_threshold
            self.config["sound_enabled"] = self._sound_var.get()
            self.config["show_exercises"] = self._exercises_var.get()
            self.config["strict_mode"] = self._strict_var.get()
            self.config["screen_dim"] = self._dim_var.get()
            self.config["pomodoro_mode"] = self._pomo_var.get()
            self.config["mini_reminders"] = self._mini_var.get()
            try:
                mini_interval = int(self._mini_spin.get())
                if mini_interval >= 5:
                    self.config["mini_reminder_interval"] = mini_interval
            except ValueError:
                pass
            save_config(self.config)

            self._reset_all_timers()

            self._save_fb.set("✓ Saved — timers reset")
            self._status_win.after(4000, lambda: self._save_fb.set(""))

        except (ValueError, AssertionError):
            self._save_fb.set("⚠ Invalid input — check time format (HH:MM)")

    def _reset_defaults(self) -> None:
        dc = json.loads(json.dumps(DEFAULT_CONFIG))
        self.config.update(dc);  save_config(self.config)

        # Refresh widgets
        self._eye_spin.delete(0, "end");  self._eye_spin.insert(0, str(dc["eye_rest_interval"]))
        self._micro_spin.delete(0, "end");  self._micro_spin.insert(0, str(dc["micro_pause_interval"]))
        self._gap_spin.delete(0, "end");  self._gap_spin.insert(0, str(dc["minimum_break_gap"]))
        self._eye_dur_spin.delete(0, "end");  self._eye_dur_spin.insert(0, str(dc["eye_rest_duration"]))
        self._snooze_spin.delete(0, "end");  self._snooze_spin.insert(0, str(dc["snooze_minutes"]))
        self._warn_spin.delete(0, "end");  self._warn_spin.insert(0, str(dc["warning_seconds"]))
        self._ws_entry.delete(0, "end");  self._ws_entry.insert(0, dc["work_start"])
        self._we_entry.delete(0, "end");  self._we_entry.insert(0, dc["work_end"])
        # Reset feature checkboxes
        self._idle_var.set(dc["idle_detection"])
        self._idle_spin.delete(0, "end");  self._idle_spin.insert(0, str(dc["idle_threshold"]))
        self._sound_var.set(dc["sound_enabled"])
        self._exercises_var.set(dc["show_exercises"])
        self._strict_var.set(dc["strict_mode"])
        self._dim_var.set(dc["screen_dim"])
        self._pomo_var.set(dc["pomodoro_mode"])
        self._mini_var.set(dc["mini_reminders"])
        self._mini_spin.delete(0, "end");  self._mini_spin.insert(0, str(dc["mini_reminder_interval"]))

        for row in list(self._brk_rows):
            row["frame"].destroy()
        self._brk_rows.clear()
        for brk in dc["breaks"]:
            self._add_brk_row(brk["time"], brk["duration"], brk["title"])

        self._reset_all_timers()
        self._save_fb.set("✓ Reset to defaults")
        self._status_win.after(4000, lambda: self._save_fb.set(""))

    def _close_status(self) -> None:
        if self._status_win:
            try:
                self._status_win.destroy()
            except tk.TclError:
                pass
            self._status_win = None

    def _update_status(self) -> None:
        if not self._status_win:
            return
        try:
            self._status_win.winfo_exists()
        except tk.TclError:
            self._status_win = None
            return

        now = datetime.datetime.now()
        # When paused, use pause_started time for calculations (timers frozen)
        calc_time = self.pause_started if self.paused and self.pause_started else now

        # Check if outside work hours
        t = now.time()
        outside_hours = False
        try:
            ws = self._pt(self.config.get("work_start", "08:00"))
            we = self._pt(self.config.get("work_end", "20:00"))
            outside_hours = t < ws or t > we
        except ValueError:
            pass

        # ── Eye rest ──
        tv, dv = self._st_rows["eye"]
        if outside_hours:
            tv.set("—")
            dv.set("outside work hours")
        elif self.paused:
            tv.set("PAUSED")
            dv.set(f"every {int(self.eye_iv)} min")
        else:
            el = (calc_time - self.last_eye_rest).total_seconds()
            rem = max(0, self.eye_iv * 60 - el)
            m, s = divmod(int(rem), 60)
            tv.set(f"{m:02d}:{s:02d}")
            dv.set(f"every {int(self.eye_iv)} min")

        # ── Micro-pause ──
        tv, dv = self._st_rows["micro"]
        if outside_hours:
            tv.set("—")
            dv.set("outside work hours")
        elif self.paused:
            tv.set("PAUSED")
            dv.set(f"every {int(self.micro_iv)} min")
        else:
            el = (calc_time - self.last_micro).total_seconds()
            rem = max(0, self.micro_iv * 60 - el)
            m, s = divmod(int(rem), 60)
            tv.set(f"{m:02d}:{s:02d}")
            dv.set(f"every {int(self.micro_iv)} min")

        # ── Next scheduled break ──
        tv, dv = self._st_rows["sched"]
        if outside_hours:
            tv.set("—")
            dv.set("outside work hours")
        elif self.paused:
            tv.set("PAUSED")
            # Still show which break is next, just paused
            nxt = None
            for brk in self.config.get("breaks", []):
                key = brk["time"]
                if self.acked_today.get(key) == now.date(): continue
                try:
                    bt = datetime.datetime.combine(now.date(), self._pt(brk["time"]))
                except: continue
                diff = (bt - now).total_seconds()
                if diff > -60 and (nxt is None or diff < nxt[0]):
                    dl = f" ({brk['duration']}m)" if brk["duration"] > 0 else ""
                    nxt = (diff, f"{self._fmt12(brk['time'])} — {brk['title']}{dl}")
            dv.set(nxt[1] if nxt else "no more scheduled breaks today")
        elif self.warning_up and self.pending_break:
            tv.set(f"0:{self._warn_rem:02d}")
            dv.set("⏳ break imminent")
        else:
            nxt = None
            for brk in self.config.get("breaks", []):
                key = brk["time"]
                if self.acked_today.get(key) == now.date(): continue
                try:
                    bt = datetime.datetime.combine(now.date(), self._pt(brk["time"]))
                except: continue
                diff = (bt - now).total_seconds()
                if diff > -60 and (nxt is None or diff < nxt[0]):
                    dl = f" ({brk['duration']}m)" if brk["duration"] > 0 else ""
                    nxt = (diff, f"{self._fmt12(brk['time'])} — {brk['title']}{dl}")
            if nxt and nxt[0] > 0:
                m, s = divmod(int(nxt[0]), 60)
                h, m = divmod(m, 60)
                tv.set(f"{h}h {m:02d}m" if h > 0 else f"{m:02d}:{s:02d}")
                dv.set(nxt[1])
            else:
                tv.set("—");  dv.set("no more scheduled breaks today")

        # ── State line ──
        parts = []
        if outside_hours:
            parts.append("OUTSIDE WORK HOURS")
        if self.idle:
            parts.append("IDLE")
        if self.paused: parts.append("PAUSED")
        if self.low_energy: parts.append("LOW ENERGY")
        if self.overlay_up: parts.append("overlay active")
        if self.warning_up: parts.append("warning active")
        if self.snooze_until and calc_time < self.snooze_until:
            parts.append(f"snoozed ({int((self.snooze_until-calc_time).total_seconds())}s)")
        # Show if in minimum gap cooldown (use calc_time for pause-aware calculation)
        min_gap = self.config.get("minimum_break_gap", 20)
        since_last = (calc_time - self.last_any_break).total_seconds() / 60
        if since_last < min_gap and not self.overlay_up and not self.warning_up and not self.paused:
            gap_rem = int(min_gap - since_last)
            parts.append(f"{min_gap}-min gap ({gap_rem}m left)")
        self._st_state.set("  •  ".join(parts) if parts else "active")

        try:
            self._status_win.after(1000, self._update_status)
        except tk.TclError:
            self._status_win = None

    # ━━━ Startup ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _show_startup(self):
        ov = tk.Toplevel(self.root)
        ov.overrideredirect(True);  ov.attributes("-topmost", True)
        ov.configure(bg=C_CARD);  self._centre(ov, 440, 160)
        if IS_MAC: ov.lift()

        tk.Label(ov, text="✓  Screen Break is running", font=(FONT, 13, "bold"),
                 fg=C_ACCENT2, bg=C_CARD).pack(pady=(18, 4))

        detail = ("A clock will appear top-right ~1 min before each break.\n"
                  f"Settings in {'menu bar' if IS_MAC else 'system tray'} → right-click.\n"
                  "Click anywhere to dismiss this.")
        tk.Label(ov, text=detail, font=(FONT, 9), fg=C_TEXT_MUT, bg=C_CARD,
                 justify="center").pack(pady=(0, 4))

        tk.Label(ov, text=f"Times are local ({datetime.datetime.now().astimezone().tzinfo})",
                 font=(FONT, 8), fg=C_TEXT_MUT, bg=C_CARD).pack(pady=(0, 8))

        # Click anywhere to dismiss
        def dismiss(e=None):
            try:
                ov.destroy()
            except tk.TclError:
                pass
        ov.bind("<Button-1>", dismiss)
        # Also auto-close after a few seconds
        ov.after(STARTUP_DISMISS_MS, dismiss)

    def _print_schedule(self):
        print()
        print("  ┌───────────────────────────────────────────────┐")
        print("  │          Screen Break — Schedule             │")
        print("  ├───────────────────────────────────────────────┤")
        for brk in self.config.get("breaks", []):
            d = f"({brk['duration']} min)" if brk['duration'] > 0 else ""
            t12 = self._fmt12(brk['time'])
            print(f"  │  {t12:<8s}  {brk['title']:<22s} {d:>8s} │")
        print("  ├───────────────────────────────────────────────┤")
        ei, mi = int(self.eye_iv), int(self.micro_iv)
        mg = self.config.get("minimum_break_gap", 20)
        print(f"  │  Every {ei:>2d} min   20-20-20 eye rest            │")
        print(f"  │  Every {mi:>2d} min   Micro-pause (5 min)          │")
        print(f"  │  Minimum {mg} min between any breaks           │")
        tz = datetime.datetime.now().astimezone().tzinfo
        print(f"  │  Timezone: {str(tz):<34s} │")
        print("  └───────────────────────────────────────────────┘")
        if not HAS_TRAY:
            print("\n  ⚠  No tray icon (pystray not available).")
            print("     pip install pystray pillow")
        print()

    # ━━━ System Tray ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _create_tray_icon(self, paused: bool = False) -> Image.Image:
        """Create tray icon. Grayed out when paused."""
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        if paused:
            # Grayed out icon when paused
            draw.ellipse([4, 4, 60, 60], fill="#374151", outline="#6b7280", width=2)
            draw.rectangle([20, 18, 28, 46], fill="#9ca3af")
            draw.rectangle([36, 18, 44, 46], fill="#9ca3af")
        else:
            # Normal colorful icon
            draw.ellipse([4, 4, 60, 60], fill="#1e293b", outline="#0ea5e9", width=2)
            draw.rectangle([20, 18, 28, 46], fill="#f1f5f9")
            draw.rectangle([36, 18, 44, 46], fill="#f1f5f9")
        return img

    def _update_tray_icon(self) -> None:
        """Update tray icon to reflect paused state."""
        if HAS_TRAY and hasattr(self, "tray"):
            try:
                self.tray.icon = self._create_tray_icon(self.paused)
                self.tray.title = "Screen Break (PAUSED)" if self.paused else "Screen Break"
            except Exception:
                pass

    def _run_tray(self) -> None:
        img = self._create_tray_icon(self.paused)

        menu = pystray.Menu(
            pystray.MenuItem("Screen Break", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda item: "▶  Resume" if self.paused else "⏸  Pause",
                lambda icon, item: self._toggle_pause()),
            pystray.MenuItem(
                lambda item: "🔋  Normal energy" if self.low_energy else "🪫  Low energy",
                lambda icon, item: self._toggle_low_energy()),
            pystray.MenuItem("📊  Statistics",
                lambda icon, item: self.root.after(0, self._show_stats_win)),
            pystray.MenuItem("📝  Notes",
                lambda icon, item: self.root.after(0, self._show_notes_win)),
            pystray.MenuItem("⏱  Status & Settings",
                lambda icon, item: self.root.after(0, self._show_status_window)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        )
        self.tray = pystray.Icon("screen_break", img, "Screen Break", menu)
        self.tray.run()

    def _toggle_pause(self) -> None:
        now = datetime.datetime.now()
        if self.paused:
            # Resuming: adjust all timer timestamps by pause duration
            if self.pause_started:
                pause_duration = now - self.pause_started
                self.last_eye_rest += pause_duration
                self.last_micro += pause_duration
                self.last_any_break += pause_duration
                if self.snooze_until:
                    self.snooze_until += pause_duration
            self.pause_started = None
            self.paused = False
        else:
            # Pausing: record when pause started
            self.pause_started = now
            self.paused = True
        self._update_tray_icon()

    def _toggle_low_energy(self) -> None:
        self.low_energy = not self.low_energy
        # Don't reset timers - just changing the interval multiplier is enough
        # The computed properties (eye_iv, micro_iv) will automatically adjust

    def _quit(self, icon: Optional[Any] = None, item: Optional[Any] = None) -> None:
        if HAS_TRAY and hasattr(self, "tray"):
            self.tray.stop()
        self.root.after(0, self.root.quit)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if __name__ == "__main__":
    ScreenBreakApp()
