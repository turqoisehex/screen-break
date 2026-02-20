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
            print("  [OK] Installed.\n")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    print(f"  [X] Failed.  Run:  pip install {' '.join(missing)}\n")
    return False

HAS_TRAY = _ensure_deps()

# ─── Imports ──────────────────────────────────────────────────
import threading, datetime, json, math, random, time
from typing import Any, Callable, Optional

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageTk

if HAS_TRAY:
    try:
        import pystray
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
DEFAULT_COAST_MARGIN = 10          # Default coast margin (now configurable)
STARTUP_DISMISS_MS = 6000          # Auto-dismiss startup notification after 6 seconds
WARNING_ICON_SIZE = 124            # Size of warning clock icon (2x for visibility)
WARNING_ICON_MARGIN = 18           # Margin from screen edge

# ─── Config ───────────────────────────────────────────────────
CONFIG_FILE = os.path.join(os.path.expanduser("~"), "screen_break_config.json")
NOTES_FILE  = os.path.join(os.path.expanduser("~"), "screen_break_notes.json")
STATS_FILE  = os.path.join(os.path.expanduser("~"), "screen_break_stats.json")

# ─── Idle Detection ───────────────────────────────────────────
IDLE_CHECK_INTERVAL = 5  # Check idle every 5 seconds
DEFAULT_IDLE_THRESHOLD = 300  # 5 minutes of inactivity = idle

_idle_impl = None  # Cached platform-specific idle detection function

def _init_idle_impl():
    """Set up platform-specific idle detection (called once, cached)."""
    global _idle_impl
    if _idle_impl is not None:
        return
    try:
        if IS_WIN:
            import ctypes
            from ctypes import Structure, c_uint, sizeof, byref, windll
            class LASTINPUTINFO(Structure):
                _fields_ = [("cbSize", c_uint), ("dwTime", c_uint)]
            def _win_idle():
                lii = LASTINPUTINFO()
                lii.cbSize = sizeof(LASTINPUTINFO)
                if windll.user32.GetLastInputInfo(byref(lii)):
                    return (windll.kernel32.GetTickCount() - lii.dwTime) / 1000.0
                return 0.0
            _idle_impl = _win_idle
        elif IS_MAC:
            import ctypes, ctypes.util
            cg = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreGraphics"))
            fn = cg.CGEventSourceSecondsSinceLastEventType
            fn.restype = ctypes.c_double
            fn.argtypes = [ctypes.c_int32, ctypes.c_uint32]
            # kCGEventSourceStateCombinedSessionState = 0, kCGAnyInputEventType = ~0
            _idle_impl = lambda: fn(0, 0xFFFFFFFF)
        else:  # Linux
            import subprocess
            def _linux_idle():
                result = subprocess.run(
                    ["xprintidle"], capture_output=True, text=True, timeout=2)
                return int(result.stdout.strip()) / 1000.0
            _idle_impl = _linux_idle
    except Exception:
        _idle_impl = lambda: 0.0

def get_idle_seconds() -> float:
    """Get seconds since last user input. Returns 0 if detection unavailable."""
    if _idle_impl is None:
        _init_idle_impl()
    try:
        return _idle_impl()
    except Exception:
        return 0.0

# ─── Sound System ─────────────────────────────────────────────
_sound_counter = 0

def play_sound(sound_type: str = "chime", custom_path: str = None) -> None:
    """Play a notification sound. Supports mp3, wav, and other common formats."""
    # Try custom sound first
    if custom_path and os.path.exists(custom_path):
        try:
            if IS_WIN:
                # Use Windows MCI (Media Control Interface) - plays mp3, wav, wma, etc. natively
                import ctypes
                winmm = ctypes.windll.winmm
                global _sound_counter
                _sound_counter += 1
                alias = f"sound_{_sound_counter}"
                # Open and play asynchronously
                winmm.mciSendStringW(f'open "{custom_path}" alias {alias}', None, 0, None)
                winmm.mciSendStringW(f'play {alias}', None, 0, None)
                # Schedule cleanup after 30 seconds (generous for any sound)
                import threading
                def cleanup():
                    import time; time.sleep(30)
                    try: winmm.mciSendStringW(f'close {alias}', None, 0, None)
                    except Exception: pass
                threading.Thread(target=cleanup, daemon=True).start()
                return
            elif IS_MAC:
                import subprocess
                subprocess.Popen(["afplay", custom_path])
                return
            else:  # Linux
                import subprocess
                # Try common Linux audio players in order of likelihood
                players = [
                    ["mpv", "--no-terminal", "--no-video", custom_path],
                    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", custom_path],
                    ["cvlc", "--play-and-exit", "--no-video", "-q", custom_path],
                    ["gst-play-1.0", custom_path],
                    ["paplay", custom_path],  # PulseAudio (wav/ogg only usually)
                    ["aplay", "-q", custom_path],  # ALSA (wav only)
                ]
                for cmd in players:
                    try:
                        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        return
                    except FileNotFoundError:
                        continue
        except Exception:
            pass  # Fall through to default

    # Default system sounds
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

# ─── Guided Eye Exercise Patterns ──────────────────────────────
EYE_EXERCISE_PATTERNS = [
    {
        "name": "Circle Trace",
        "instruction": "Follow the dot with your eyes",
        "duration": 20,
        "pattern": "circle",
    },
    {
        "name": "Figure Eight",
        "instruction": "Trace the infinity pattern",
        "duration": 20,
        "pattern": "figure8",
    },
    {
        "name": "Near-Far Focus",
        "instruction": "Focus near, then far",
        "duration": 20,
        "pattern": "nearfar",
    },
]

# ─── Breathing Exercise Patterns ───────────────────────────────
BREATHING_PATTERNS = {
    "box": {"name": "Box Breathing", "phases": [("Breathe In", 4), ("Hold", 4), ("Breathe Out", 4), ("Hold", 4)]},
    "relaxing": {"name": "4-7-8 Relaxing", "phases": [("Breathe In", 4), ("Hold", 7), ("Breathe Out", 8)]},
    "energizing": {"name": "Energizing", "phases": [("Breathe In", 4), ("Breathe Out", 4)]},
}

# ─── Desk Exercise Animations ──────────────────────────────────
DESK_EXERCISES = [
    {
        "name": "Shoulder Rolls",
        "frames": [
            "     O\n    /|\\\n    / \\",
            "     O\n   //|\\\\\n    / \\",
            "     O\n    /|\\\n    / \\",
            "     O\n   \\\\|//\n    / \\",
        ],
        "instruction": "Roll shoulders forward, up, back, down",
        "duration": 10,
    },
    {
        "name": "Neck Stretch",
        "frames": [
            "    O\n   /|\\\n   / \\",
            "   O \n   /|\\\n   / \\",
            "    O\n   /|\\\n   / \\",
            "    O\n   /|\\\n   / \\",
            "     O\n   /|\\\n   / \\",
        ],
        "instruction": "Tilt head slowly: left, center, right",
        "duration": 10,
    },
    {
        "name": "Wrist Circles",
        "frames": [
            "   \\O/\n    |\n   / \\",
            "   -O-\n    |\n   / \\",
            "   /O\\\n    |\n   / \\",
            "   -O-\n    |\n   / \\",
        ],
        "instruction": "Rotate wrists in circles, both directions",
        "duration": 10,
    },
    {
        "name": "Seated Twist",
        "frames": [
            "    O\n   /|\\\n   / \\",
            "    O\n  //| \n   / \\",
            "    O\n   /|\\\n   / \\",
            "    O\n    |\\\\\n   / \\",
        ],
        "instruction": "Twist torso gently left and right",
        "duration": 10,
    },
]

class GuidedEyeExercise:
    """Animated eye exercise with moving dot to follow."""

    def __init__(self, canvas: tk.Canvas, width: int, height: int, pattern: str = "circle"):
        self.canvas = canvas
        self.width = width
        self.height = height
        self.pattern = pattern
        self.dot = None
        self.angle = 0
        self.phase = 0
        self.running = False

        # Create the dot
        self.dot = canvas.create_oval(0, 0, 30, 30, fill=C_EYE_ACC, outline="")
        self._update_position()

    def _update_position(self):
        """Update dot position based on pattern."""
        cx, cy = self.width // 2, self.height // 2
        # Use most of canvas area for eye tracking (90% of half-width/height)
        radius_x = int(self.width * 0.45)
        radius_y = int(self.height * 0.45)

        if self.pattern == "circle":
            x = cx + radius_x * math.cos(self.angle)
            y = cy + radius_y * math.sin(self.angle)
        elif self.pattern == "figure8":
            # Figure-8 pattern spanning most of canvas width
            # Parametric: x = cos(t), y = sin(t)*cos(t) scaled
            x = cx + radius_x * math.cos(self.angle)
            y = cy + radius_y * math.sin(self.angle) * math.cos(self.angle)
        elif self.pattern == "nearfar":
            # Pulsing dot (near/far focus)
            pulse = (math.sin(self.angle * 2) + 1) / 2  # 0 to 1
            size = 15 + pulse * 35
            x, y = cx, cy
            self.canvas.coords(self.dot, x - size, y - size, x + size, y + size)
            return
        else:
            x, y = cx, cy

        self.canvas.coords(self.dot, x - 15, y - 15, x + 15, y + 15)

    def animate(self):
        """Advance animation one step (~60fps)."""
        if not self.running:
            return
        self.angle += 0.026
        if self.angle > 2 * math.pi:
            self.angle -= 2 * math.pi
        self._update_position()
        self.canvas.after(16, self.animate)

    def start(self):
        self.running = True
        self.animate()

    def stop(self):
        self.running = False


class BreathingExercise:
    """Animated breathing circle with phase prompts."""

    def __init__(self, canvas: tk.Canvas, label: tk.Label, width: int, height: int, pattern: str = "box"):
        self.canvas = canvas
        self.label = label
        self.width = width
        self.height = height
        self.pattern_data = BREATHING_PATTERNS.get(pattern, BREATHING_PATTERNS["box"])
        self.phases = self.pattern_data["phases"]
        self.phase_idx = 0
        self.phase_time = 0
        self.running = False
        self.circle = None
        self.base_radius = min(width, height) // 6
        self.current_radius = self.base_radius

        cx, cy = width // 2, height // 2
        r = self.base_radius
        self.circle = canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                         fill=C_ACCENT2, outline=C_TEXT, width=2)

    def animate(self):
        """Advance animation one step."""
        if not self.running:
            return

        phase_name, phase_duration = self.phases[self.phase_idx]
        progress = self.phase_time / (phase_duration * 10)  # 10 ticks per second

        # Update label
        self.label.config(text=phase_name)

        # Calculate radius based on phase
        if "In" in phase_name:
            # Expanding
            target = self.base_radius * 2
            self.current_radius = self.base_radius + (target - self.base_radius) * progress
        elif "Out" in phase_name:
            # Contracting
            start = self.base_radius * 2
            self.current_radius = start - (start - self.base_radius) * progress
        # Hold phases keep current radius

        # Update circle
        cx, cy = self.width // 2, self.height // 2
        r = self.current_radius
        self.canvas.coords(self.circle, cx - r, cy - r, cx + r, cy + r)

        # Advance time
        self.phase_time += 1
        if self.phase_time >= phase_duration * 10:
            self.phase_time = 0
            self.phase_idx = (self.phase_idx + 1) % len(self.phases)

        self.canvas.after(100, self.animate)

    def start(self):
        self.running = True
        self.animate()

    def stop(self):
        self.running = False


class DeskExerciseAnimation:
    """ASCII-art frame animation for desk exercises."""

    def __init__(self, label: tk.Label, exercise: dict):
        self.label = label
        self.frames = exercise["frames"]
        self.frame_idx = 0
        self.running = False

    def animate(self):
        """Show next frame."""
        if not self.running:
            return
        self.label.config(text=self.frames[self.frame_idx])
        self.frame_idx = (self.frame_idx + 1) % len(self.frames)
        self.label.after(600, self.animate)

    def start(self):
        self.running = True
        self.animate()

    def stop(self):
        self.running = False


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
    # Premium features
    "coast_margin_minutes": 10,       # Skip eye/micro if scheduled break within this margin
    "focus_mode": True,               # Auto-pause during fullscreen apps (presentation mode)
    "multi_monitor_overlay": True,    # Show overlay on all monitors
    "hydration_tracking": False,      # Hydration reminders
    "hydration_goal": 8,              # Glasses per day
    "hydration_reminder_interval": 30,# Minutes between hydration reminders
    "custom_sound_enabled": False,    # Use custom sound file
    "custom_sound_path": "",          # Path to custom .wav file
    "use_custom_messages": False,     # Use custom break messages
    "custom_messages": [],            # List of custom motivational messages
    "theme": "nord",                  # Theme: dark, light, nord
    "guided_eye_exercises": False,    # Animated eye exercise routines
    "breathing_exercises": False,     # Breathing animation during breaks
    "desk_exercises": False,          # Animated desk exercises
    "focus_session_duration": 25,     # Focus session length in minutes
    # Accessibility (Windows 11 tray icon is hidden by default)
    "show_floating_widget": True,     # Persistent countdown widget on screen
    "widget_position": None,          # Saved [x, y] position (None = bottom-right default)
    "show_in_taskbar": True,          # Show app in Windows taskbar (clickable)
    "status_always_on_top": False,    # Keep Settings window above other windows
    # Breathing circle widget (always-on-top ambient breathing guide)
    "breathing_widget_enabled": False,
    "breathing_widget_inhale": 4.0,   # Inhale duration in seconds (float)
    "breathing_widget_hold_in": 0.0,  # Hold at peak in seconds (float)
    "breathing_widget_exhale": 4.0,   # Exhale duration in seconds (float)
    "breathing_widget_hold_out": 0.0, # Hold at bottom in seconds (float)
    "breathing_widget_alpha": 0.7,    # Window opacity 0.05-1.0
    "breathing_widget_bg": "transparent",  # "transparent", "dark", "teal"
    "breathing_widget_size": 120,     # Circle diameter in px (60+, no upper limit)
    "breathing_widget_click_through": True,  # Click passes through widget (Ctrl+drag to move)
    "breathing_widget_position": None,  # Saved [x, y]
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
            print(f"  [!] Config load error: {e}. Using defaults.")

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
        ("minimum_break_gap", 1, 20),
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
        print(f"  [!] Config save error: {e}")

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
    "daily_history": [],  # Last 7 days: [{"date": "YYYY-MM-DD", "eye": N, "micro": N, "scheduled": N}, ...]
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
                for key in ["streak_days", "last_active_date", "daily_history"]:
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
        # Archive previous day's stats to daily_history
        prev_date = stats["today"].get("date")
        if prev_date and any([stats["today"].get("eye_rest_taken", 0),
                              stats["today"].get("micro_taken", 0),
                              stats["today"].get("scheduled_taken", 0)]):
            history_entry = {
                "date": prev_date,
                "eye": stats["today"].get("eye_rest_taken", 0),
                "micro": stats["today"].get("micro_taken", 0),
                "scheduled": stats["today"].get("scheduled_taken", 0),
            }
            if "daily_history" not in stats:
                stats["daily_history"] = []
            stats["daily_history"].append(history_entry)
            # Keep only last 7 days
            stats["daily_history"] = stats["daily_history"][-7:]

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
C_OK      = "#22c55e";  C_ERR      = "#ef4444";  C_GENTLE  = "#2dd4bf"

TICK = 10   # scheduler tick (seconds)

# ─── Tooltip Helper ───────────────────────────────────────────
class ToolTip:
    """Simple tooltip for tkinter widgets."""
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, event=None):
        x = self.widget.winfo_rootx() + 25
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        label = tk.Label(self.tip, text=self.text, font=(FONT, 9), fg=C_TEXT, bg=C_CARD,
                         relief="solid", borderwidth=1, padx=6, pady=4)
        label.pack()

    def _hide(self, event=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None

# ─── Themes ──────────────────────────────────────────────────
THEMES = {
    "dark": {
        "bg": "#111827", "card": "#1e293b", "card_in": "#253349",
        "accent": "#f43f5e", "accent2": "#0ea5e9",
        "btn_pri": "#1d4ed8", "btn_sec": "#334155",
        "text": "#f1f5f9", "text_dim": "#94a3b8", "text_mut": "#64748b",
        "eye_bg": "#0c1222", "eye_acc": "#22d3ee", "cd": "#fbbf24",
        "w_bg": "#1a1a2e", "w_gl": "#0ea5e9",
        "ok": "#22c55e", "err": "#ef4444", "gentle": "#2dd4bf",
    },
    "light": {
        "bg": "#f8fafc", "card": "#ffffff", "card_in": "#f1f5f9",
        "accent": "#e11d48", "accent2": "#0284c7",
        "btn_pri": "#2563eb", "btn_sec": "#e2e8f0",
        "text": "#1e293b", "text_dim": "#475569", "text_mut": "#94a3b8",
        "eye_bg": "#e0f2fe", "eye_acc": "#0369a1", "cd": "#d97706",
        "w_bg": "#e2e8f0", "w_gl": "#2563eb",
        "ok": "#16a34a", "err": "#dc2626", "gentle": "#0d9488",
    },
    "nord": {
        "bg": "#2e3440", "card": "#3b4252", "card_in": "#434c5e",
        "accent": "#bf616a", "accent2": "#88c0d0",
        "btn_pri": "#5e81ac", "btn_sec": "#4c566a",
        "text": "#eceff4", "text_dim": "#d8dee9", "text_mut": "#a3be8c",
        "eye_bg": "#242933", "eye_acc": "#8fbcbb", "cd": "#ebcb8b",
        "w_bg": "#242933", "w_gl": "#88c0d0",
        "ok": "#a3be8c", "err": "#bf616a", "gentle": "#8fbcbb",
    },
}

def apply_theme(theme_name: str) -> None:
    """Apply a theme by updating global color constants."""
    global C_BG, C_CARD, C_CARD_IN, C_ACCENT, C_ACCENT2
    global C_BTN_PRI, C_BTN_SEC, C_TEXT, C_TEXT_DIM, C_TEXT_MUT
    global C_EYE_BG, C_EYE_ACC, C_CD, C_W_BG, C_W_GL, C_OK, C_ERR, C_GENTLE

    theme = THEMES.get(theme_name, THEMES["dark"])
    C_BG = theme["bg"];       C_CARD = theme["card"];       C_CARD_IN = theme["card_in"]
    C_ACCENT = theme["accent"]; C_ACCENT2 = theme["accent2"]
    C_BTN_PRI = theme["btn_pri"]; C_BTN_SEC = theme["btn_sec"]
    C_TEXT = theme["text"];   C_TEXT_DIM = theme["text_dim"]; C_TEXT_MUT = theme["text_mut"]
    C_EYE_BG = theme["eye_bg"]; C_EYE_ACC = theme["eye_acc"]; C_CD = theme["cd"]
    C_W_BG = theme["w_bg"];   C_W_GL = theme["w_gl"]
    C_OK = theme["ok"];       C_ERR = theme["err"];         C_GENTLE = theme["gentle"]

# ─── Fullscreen Detection ────────────────────────────────────
def is_fullscreen_app_active() -> bool:
    """Check if a fullscreen application is active (Windows only)."""
    if not IS_WIN:
        return False
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32

        # Get foreground window
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False

        # Get window rect
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))

        # Get screen dimensions
        screen_w = user32.GetSystemMetrics(0)  # SM_CXSCREEN
        screen_h = user32.GetSystemMetrics(1)  # SM_CYSCREEN

        # Check if window covers entire screen (with small margin for taskbar issues)
        win_w = rect.right - rect.left
        win_h = rect.bottom - rect.top

        return (win_w >= screen_w - 10 and win_h >= screen_h - 10 and
                rect.left <= 5 and rect.top <= 5)
    except Exception:
        return False

# ─── Multi-Monitor Support ───────────────────────────────────
try:
    from screeninfo import get_monitors
    HAS_SCREENINFO = True
except ImportError:
    HAS_SCREENINFO = False

def get_all_monitors() -> list:
    """Get list of all monitors as (x, y, width, height) tuples."""
    if HAS_SCREENINFO:
        try:
            return [(m.x, m.y, m.width, m.height) for m in get_monitors()]
        except Exception:
            pass
    return [(0, 0, None, None)]  # Fallback: use tkinter's screen dimensions

# ─── Hydration Stats ─────────────────────────────────────────
def get_hydration_today(stats: dict) -> int:
    """Get today's hydration count, resetting if new day."""
    today = datetime.date.today().isoformat()
    hydration = stats.setdefault("hydration", {"date": None, "glasses": 0})
    if hydration.get("date") != today:
        hydration["date"] = today
        hydration["glasses"] = 0
    return hydration.get("glasses", 0)

def log_hydration(stats: dict) -> int:
    """Log a glass of water and return new count."""
    today = datetime.date.today().isoformat()
    hydration = stats.setdefault("hydration", {"date": today, "glasses": 0})
    if hydration.get("date") != today:
        hydration["date"] = today
        hydration["glasses"] = 0
    hydration["glasses"] = hydration.get("glasses", 0) + 1
    return hydration["glasses"]

# ─── Test Mode Intervals ─────────────────────────────────────
if TEST_MODE:
    print("\n  [!] TEST MODE: Using short intervals")
    print("      Eye rest: 1 min, Micro-pause: 2 min\n")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class ScreenBreakApp:

    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()  # Hide immediately; may be replaced by taskbar mode below

        self.config = load_config()
        self.notes  = self._load_notes()
        self.stats  = load_stats()
        update_stats_for_today(self.stats)

        # Apply theme from config
        apply_theme(self.config.get("theme", "nord"))

        # Taskbar presence: show app in taskbar so users can find it
        # (Windows 11 hides tray icons in overflow by default)
        if self.config.get("show_in_taskbar", True):
            self.root.deiconify()
            self.root.title("Screen Break")
            self.root.geometry("1x1+0+0")
            try:
                self.root.attributes("-alpha", 0.0)
            except tk.TclError:
                pass
            self.root.iconify()
            self.root.protocol("WM_DELETE_WINDOW", lambda: self.root.iconify())
            self.root.bind("<Map>", self._on_taskbar_click)

        self.paused = False;  self.low_energy = False
        self.pause_started = None  # Track when pause began for timer adjustment
        self.idle = False;  self.idle_since = None  # Idle detection state
        self.overlay_up = False;  self.warning_up = False
        self.current_overlay = None;  self.warning_window = None
        self.pending_break = None;  self.snooze_until = None
        self._mini_ind = None;  self._mini_ov = None;  self._mini_done_notif = None
        self._break_rem = 0
        self.last_eye_rest = datetime.datetime.now()
        self.last_micro    = datetime.datetime.now()
        self.last_any_break = datetime.datetime.now()
        self.acked_today   = {};  self.today = datetime.date.today()
        self._warn_anim_id = None;  self._warn_rem = 0;  self._warn_total = 0
        self._status_win = None;  self._tip = None;  self._stats_win = None;  self._notes_win = None;  self._msg_editor_win = None

        if HAS_TRAY:
            threading.Thread(target=self._run_tray, daemon=True).start()

        # Floating widget state
        self._widget_win = None
        self._widget_label = None
        self._widget_dragged = False
        self._widget_drag_x = 0
        self._widget_drag_y = 0

        # Breathing circle widget state
        self._breath_win = None
        self._breath_canvas = None
        self._breath_photo = None  # prevent GC of PhotoImage
        self._breath_running = False
        self._breath_dragged = False
        self._breath_drag_x = 0
        self._breath_drag_y = 0
        self._breath_hwnd = None
        self._breath_ct_active = False  # click-through currently on
        # Cached GDI resources for layered window rendering
        self._breath_hdc_screen = None
        self._breath_hdc_mem = None
        self._breath_hbmp = None
        self._breath_ppv = None
        self._breath_old_bmp = None

        self.last_mini_reminder = datetime.datetime.now()
        self._mini_win = None
        self.last_hydration_reminder = datetime.datetime.now()
        self._hydration_win = None
        self.fullscreen_active = False  # Track fullscreen state

        # Animation instances for exercises
        self._eye_exercise = None
        self._breathing_exercise = None
        self._desk_exercise = None

        # Focus session state
        self._focus_win = None
        self._focus_dialog = None
        self._focus_timer_id = None
        self._focus_timer_var = None
        self._focus_task = None
        self._focus_duration = 0
        self._focus_remaining = 0

        self._print_schedule()
        self._show_startup()
        if self.config.get("show_floating_widget", True):
            self.root.after(500, self._create_floating_widget)
        if self.config.get("breathing_widget_enabled", False):
            self.root.after(600, self._create_breathing_widget)
        self._start_idle_monitor()
        self._start_mini_reminders()
        self._start_hydration_reminders()
        self._tick()
        self.root.mainloop()

    def _is_work_hours(self) -> bool:
        """Check if current time is within configured work hours."""
        try:
            t = datetime.datetime.now().time()
            ws = self._pt(self.config.get("work_start", "08:00"))
            we = self._pt(self.config.get("work_end", "20:00"))
            return ws <= t < we
        except ValueError:
            return True  # If parsing fails, assume work hours

    def _start_mini_reminders(self) -> None:
        """Start mini reminder system (posture, hydration, blink nudges)."""
        def check_mini():
            if not self.config.get("mini_reminders", False):
                self.root.after(60000, check_mini)  # Check again in 1 min
                return
            if self.paused or self.idle or self.overlay_up or self.warning_up:
                self.root.after(60000, check_mini)
                return
            if not self._is_work_hours():
                self.root.after(60000, check_mini)
                return
            if self.config.get("focus_mode", False) and self.fullscreen_active:
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
        w, h = 420, 120
        win.geometry(f"{w}x{h}+{sw-w-20}+{sh-h-60}")

        f = tk.Frame(win, bg=C_CARD, padx=20, pady=14)
        f.pack(fill="both", expand=True)

        tk.Label(f, text=f"{emoji}  {title}", font=(FONT, 16, "bold"),
                 fg=C_ACCENT2, bg=C_CARD).pack(anchor="w")
        tk.Label(f, text=desc, font=(FONT, 12), fg=C_TEXT_DIM, bg=C_CARD).pack(anchor="w", pady=(4, 0))

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

    def _start_hydration_reminders(self) -> None:
        """Start hydration reminder system."""
        def check_hydration():
            if not self.config.get("hydration_tracking", False):
                self.root.after(60000, check_hydration)  # Check again in 1 min
                return
            if self.paused or self.idle or self.overlay_up or self.warning_up:
                self.root.after(60000, check_hydration)
                return
            if not self._is_work_hours():
                self.root.after(60000, check_hydration)
                return
            # Check if fullscreen mode should block
            if self.config.get("focus_mode", False) and self.fullscreen_active:
                self.root.after(60000, check_hydration)
                return

            interval = self.config.get("hydration_reminder_interval", 30)
            elapsed = (datetime.datetime.now() - self.last_hydration_reminder).total_seconds() / 60
            if elapsed >= interval:
                self.last_hydration_reminder = datetime.datetime.now()
                self.root.after(0, self._show_hydration_popup)

            self.root.after(60000, check_hydration)

        self.root.after(60000, check_hydration)

    def _show_hydration_popup(self) -> None:
        """Show hydration reminder popup with counter."""
        if self._hydration_win:
            try:
                self._hydration_win.destroy()
            except tk.TclError:
                pass

        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        try:
            win.attributes("-alpha", 0.95)
        except tk.TclError:
            pass
        win.configure(bg=C_CARD)

        # Position bottom-right
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        w, h = 300, 140
        win.geometry(f"{w}x{h}+{sw-w-20}+{sh-h-60}")

        f = tk.Frame(win, bg=C_CARD, padx=16, pady=12)
        f.pack(fill="both", expand=True)

        glasses = get_hydration_today(self.stats)
        goal = self.config.get("hydration_goal", 8)

        tk.Label(f, text="💧 Hydration Reminder", font=(FONT, 12, "bold"),
                 fg=C_ACCENT2, bg=C_CARD).pack()
        tk.Label(f, text=f"You've had {glasses}/{goal} glasses today",
                 font=(FONT, 10), fg=C_TEXT_DIM, bg=C_CARD).pack(pady=(4, 8))

        bf = tk.Frame(f, bg=C_CARD)
        bf.pack()

        def log_drink():
            log_hydration(self.stats)
            save_stats(self.stats)
            try:
                win.destroy()
            except tk.TclError:
                pass
            self._hydration_win = None

        def dismiss():
            try:
                win.destroy()
            except tk.TclError:
                pass
            self._hydration_win = None

        tk.Button(bf, text="  +1 Glass  ", font=(FONT, 10), bg=C_BTN_PRI, fg=C_TEXT,
                  relief="flat", padx=12, pady=4, cursor="hand2", command=log_drink).pack(side="left", padx=4)
        tk.Button(bf, text="Dismiss", font=(FONT, 9), bg=C_BTN_SEC, fg=C_TEXT_DIM,
                  relief="flat", padx=8, pady=4, cursor="hand2", command=dismiss).pack(side="left")

        self._hydration_win = win

        # Auto-dismiss after 30 seconds
        def auto_dismiss():
            try:
                if win.winfo_exists():
                    dismiss()
            except tk.TclError:
                pass
        win.after(30000, auto_dismiss)

    # ── Focus Sessions ─────────────────────────────────────────
    def _show_focus_session_dialog(self) -> None:
        """Show dialog to start a new focus session, or close if running."""
        # If focus session timer is running, close it
        if self._focus_win:
            try:
                if self._focus_win.winfo_exists():
                    # End the session
                    if self._focus_timer_id:
                        try:
                            self.root.after_cancel(self._focus_timer_id)
                        except (tk.TclError, ValueError):
                            pass
                        self._focus_timer_id = None
                    self._focus_win.destroy()
                    self._focus_win = None
                    return
            except tk.TclError:
                self._focus_win = None

        # If dialog is already open, focus it
        if self._focus_dialog:
            try:
                if self._focus_dialog.winfo_exists():
                    self._focus_dialog.lift()
                    self._focus_dialog.focus_force()
                    return
            except tk.TclError:
                self._focus_dialog = None

        win = tk.Toplevel(self.root)
        win.title("Start Focus Session")
        win.geometry("350x180")
        win.configure(bg=C_BG)
        win.transient(self._status_win if self._status_win else self.root)
        self._focus_dialog = win

        def on_close():
            self._focus_dialog = None
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", on_close)

        tk.Label(win, text="🎯 Start Focus Session", font=(FONT, 14, "bold"),
                 fg=C_ACCENT2, bg=C_BG).pack(pady=(16, 12))

        # Task name input
        tf = tk.Frame(win, bg=C_BG)
        tf.pack(fill="x", padx=20)
        tk.Label(tf, text="What are you working on?", font=(FONT, 10),
                 fg=C_TEXT_DIM, bg=C_BG).pack(anchor="w")
        task_entry = tk.Entry(tf, font=(FONT, 11), bg=C_CARD_IN, fg=C_TEXT,
                              relief="flat", insertbackground=C_TEXT)
        task_entry.pack(fill="x", pady=(4, 8), ipady=4)
        task_entry.focus_set()

        # Duration
        df = tk.Frame(win, bg=C_BG)
        df.pack(fill="x", padx=20)
        tk.Label(df, text="Duration:", font=(FONT, 10), fg=C_TEXT_DIM, bg=C_BG).pack(side="left")
        dur_spin = tk.Spinbox(df, from_=5, to=120, width=4, font=(MONO, 10),
                              bg=C_CARD_IN, fg=C_TEXT, buttonbackground=C_BTN_SEC,
                              relief="flat", justify="center")
        dur_spin.pack(side="left", padx=4)
        dur_spin.delete(0, "end")
        dur_spin.insert(0, str(self.config.get("focus_session_duration", 25)))
        tk.Label(df, text="minutes", font=(FONT, 10), fg=C_TEXT_MUT, bg=C_BG).pack(side="left")

        # Buttons
        bf = tk.Frame(win, bg=C_BG)
        bf.pack(pady=16)

        def start_session():
            task = task_entry.get().strip() or "Focus Session"
            try:
                duration = max(1, min(120, int(dur_spin.get())))
            except ValueError:
                duration = 25
            self.config["focus_session_duration"] = duration
            save_config(self.config)
            self._focus_dialog = None
            win.destroy()
            self._start_focus_session(task, duration)

        def cancel():
            self._focus_dialog = None
            win.destroy()

        tk.Button(bf, text="  Start  ", font=(FONT, 10, "bold"), bg=C_BTN_PRI, fg=C_TEXT,
                  relief="flat", padx=16, pady=4, cursor="hand2", command=start_session).pack(side="left", padx=4)
        tk.Button(bf, text="Cancel", font=(FONT, 10), bg=C_BTN_SEC, fg=C_TEXT_DIM,
                  relief="flat", padx=12, pady=4, cursor="hand2", command=cancel).pack(side="left")

        task_entry.bind("<Return>", lambda e: start_session())

    def _start_focus_session(self, task: str, duration: int) -> None:
        """Start a focus session with the given task name and duration."""
        self._focus_task = task
        self._focus_duration = duration
        self._focus_remaining = duration * 60  # seconds

        # Create floating timer window
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        try:
            win.attributes("-alpha", 0.92)
        except tk.TclError:
            pass
        win.configure(bg=C_CARD)

        # Position top-right
        sw = win.winfo_screenwidth()
        w, h = 260, 90
        win.geometry(f"{w}x{h}+{sw-w-20}+{20}")

        self._focus_win = win

        f = tk.Frame(win, bg=C_CARD, padx=12, pady=8)
        f.pack(fill="both", expand=True)

        # Header with task name
        hf = tk.Frame(f, bg=C_CARD)
        hf.pack(fill="x")
        tk.Label(hf, text="🎯", font=(FONT, 12), fg=C_ACCENT2, bg=C_CARD).pack(side="left")
        task_label = tk.Label(hf, text=task[:25] + ("..." if len(task) > 25 else ""),
                              font=(FONT, 10, "bold"), fg=C_TEXT, bg=C_CARD)
        task_label.pack(side="left", padx=(4, 0))

        # Timer
        self._focus_timer_var = tk.StringVar(value=f"{duration}:00")
        tk.Label(f, textvariable=self._focus_timer_var, font=(MONO, 28, "bold"),
                 fg=C_CD, bg=C_CARD).pack()

        # End button
        def end_session(completed=False):
            if self._focus_timer_id:
                try:
                    self.root.after_cancel(self._focus_timer_id)
                except (tk.TclError, ValueError):
                    pass
            self._focus_timer_id = None
            if self._focus_win:
                try:
                    self._focus_win.destroy()
                except tk.TclError:
                    pass
                self._focus_win = None
            if completed:
                # Track and trigger break
                self.stats["lifetime"]["focus_sessions"] = self.stats["lifetime"].get("focus_sessions", 0) + 1
                self.stats["today"]["focus_sessions"] = self.stats["today"].get("focus_sessions", 0) + 1
                save_stats(self.stats)
                # Show micro-pause as reward
                self._show_micro()

        tk.Button(f, text="End", font=(FONT, 9), bg=C_BTN_SEC, fg=C_TEXT_DIM,
                  relief="flat", padx=8, pady=2, cursor="hand2",
                  command=lambda: end_session(False)).pack()

        # Start countdown
        def tick():
            if not self._focus_win or not self._focus_win.winfo_exists():
                return
            if self._focus_remaining <= 0:
                end_session(completed=True)
                return
            m, s = divmod(self._focus_remaining, 60)
            self._focus_timer_var.set(f"{m}:{s:02d}")
            # Only decrement when not paused and not idle
            if not self.paused and not self.idle:
                self._focus_remaining -= 1
            self._focus_timer_id = self.root.after(1000, tick)

        self._focus_timer_id = self.root.after(1000, tick)

        # Escape to end session
        win.bind("<Escape>", lambda e: end_session(False))
        # Right-click to end session
        win.bind("<Button-3>", lambda e: end_session(False))

        # Allow dragging (left-click on frame, not buttons)
        def start_drag(e):
            win._drag_x = e.x
            win._drag_y = e.y
        def do_drag(e):
            x = win.winfo_x() + e.x - win._drag_x
            y = win.winfo_y() + e.y - win._drag_y
            win.geometry(f"+{x}+{y}")
        f.bind("<Button-1>", start_drag)
        f.bind("<B1-Motion>", do_drag)

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
                # Returned from idle - reset or adjust timers
                # (skip if paused; pause resume handles it)
                if not self.paused:
                    now = datetime.datetime.now()
                    idle_duration = now - self.idle_since
                    total_idle_secs = threshold + idle_duration.total_seconds()

                    # Idle >= threshold counts as eye rest - reset 20-min timer
                    self.last_eye_rest = now

                    # Idle >= 5 min counts as a full break - reset 45-min timer
                    if total_idle_secs >= 300:
                        self.last_micro = now
                    else:
                        self.last_micro += idle_duration

                    self.last_any_break = now
                    self.last_mini_reminder += idle_duration
                    self.last_hydration_reminder += idle_duration
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

    @staticmethod
    def _pt(s: str) -> datetime.time:
        """Parse time string (HH:MM) to datetime.time. Raises ValueError if invalid."""
        h, m = str(s).strip().split(":")
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
        # Check fullscreen state for focus mode
        if self.config.get("focus_mode", False):
            self.fullscreen_active = is_fullscreen_app_active()
        else:
            self.fullscreen_active = False

        # Safety valve: if warning_up is stuck but window is gone, clear it
        if self.warning_up and not self.warning_window:
            self.warning_up = False
            self.pending_break = None

        # Skip break checking if paused, in break, idle, or in fullscreen focus mode
        if not self.paused and not self.overlay_up and not self.warning_up and not self.idle:
            if not (self.config.get("focus_mode", False) and self.fullscreen_active):
                self._check()
        self.root.after(TICK * 1000, self._tick)

    def _check(self) -> None:
        now = datetime.datetime.now()
        t = now.time()

        if now.date() != self.today:
            self.today = now.date()
            self.acked_today.clear()
            update_stats_for_today(self.stats)
            save_stats(self.stats)

        try:
            ws = self._pt(self.config.get("work_start", "08:00"))
            we = self._pt(self.config.get("work_end",   "20:00"))
        except ValueError:
            ws, we = datetime.time(8), datetime.time(20)
        if t < ws or t >= we:
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
        coast_margin = self.config.get("coast_margin_minutes", DEFAULT_COAST_MARGIN)
        el_mp = (now - self.last_micro).total_seconds() / 60
        if el_mp >= self.micro_iv:
            if not sched_within(coast_margin):
                self._begin_warning(self._show_micro, (), min(30, warn_s))
                return

        # ── Priority 3: Eye rest (skip if scheduled break within coast margin) ──
        el_er = (now - self.last_eye_rest).total_seconds() / 60
        if el_er >= self.eye_iv:
            # Also skip if micro-pause is due very soon (but only if coast_margin < micro_iv)
            micro_soon_threshold = max(0, self.micro_iv - coast_margin)
            if not sched_within(coast_margin) and (micro_soon_threshold == 0 or el_mp < micro_soon_threshold):
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
        cx, cy, r = sz//2, sz//2, 40
        self._draw_clock(c, cx, cy, r, countdown, countdown)
        c.bind("<Button-1>", lambda e: self._dismiss_warning())

        self._tip = None
        def s_tip(e):
            self._tip = tk.Toplevel(w);  self._tip.overrideredirect(True)
            self._tip.attributes("-topmost", True);  self._tip.configure(bg=C_CARD)
            self._tip.geometry(f"240x32+{sw-sz-mg-250}+{mg+sz+4}")
            tk.Label(self._tip, text=f"Break in ~{self._warn_rem}s -- click to go now",
                     font=(FONT, 10), fg=C_TEXT_DIM, bg=C_CARD, padx=8).pack(fill="both", expand=True)
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
        gr = r + 10
        c.create_oval(cx-gr, cy-gr, cx+gr, cy+gr, fill="", outline=C_W_GL, width=2)
        c.create_oval(cx-r, cy-r, cx+r, cy+r, fill=C_CARD, outline=C_W_GL, width=3)
        if tot > 0:
            # Stopwatch style: fill clockwise as time elapses (not counter-clockwise drain)
            elapsed = tot - rem
            ext = (elapsed / tot) * 360
            c.create_arc(cx-r+8, cy-r+8, cx+r-8, cy+r-8,
                         start=90, extent=-ext, fill=C_W_GL, outline="", stipple="gray50")
        c.create_line(cx, cy, cx, cy-r+14, fill=C_TEXT, width=3)
        hx = cx + int((r-18)*math.sin(math.radians(60)))
        hy = cy - int((r-18)*math.cos(math.radians(60)))
        c.create_line(cx, cy, hx, hy, fill=C_TEXT, width=3)
        c.create_oval(cx-3, cy-3, cx+3, cy+3, fill=C_TEXT, outline="")

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
        self.warning_up = False
        if self._warn_anim_id:
            try:
                self.root.after_cancel(self._warn_anim_id)
            except (tk.TclError, ValueError):
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

    # ── Minimize / restore break overlay ─────────────────
    def _minimize_break(self, ov: tk.Toplevel, remaining: int,
                        total: int, restore_cb: Callable) -> None:
        """Hide break overlay and show a small countdown indicator top-right."""
        try:
            ov.withdraw()
        except tk.TclError:
            return

        self._mini_ov = ov
        self._mini_restore_cb = restore_cb
        self._mini_rem = remaining
        self._mini_total = total

        # Small indicator window (top-right corner)
        ind = tk.Toplevel(self.root)
        ind.overrideredirect(True);  ind.attributes("-topmost", True)
        try:
            ind.attributes("-alpha", 0.92)
        except tk.TclError:
            pass
        ind.configure(bg=C_CARD)
        sw = ind.winfo_screenwidth()
        ind.geometry(f"180x50+{sw - 200}+{18}")

        f = tk.Frame(ind, bg=C_CARD, padx=10, pady=6)
        f.pack(fill="both", expand=True)

        self._mini_cd_var = tk.StringVar(value=self._fmt_mm_ss(remaining))
        tk.Label(f, textvariable=self._mini_cd_var,
                 font=(MONO, 16, "bold"), fg=C_CD, bg=C_CARD).pack(side="left")
        tk.Label(f, text="  on break", font=(FONT, 9), fg=C_TEXT_MUT,
                 bg=C_CARD).pack(side="left", padx=(4, 0))

        ind.bind("<Button-1>", lambda e: self._restore_break())
        ind.configure(cursor="hand2")

        self._mini_ind = ind
        self._mini_countdown_tick()

    def _fmt_mm_ss(self, sec: int) -> str:
        m, s = divmod(max(0, sec), 60)
        return f"{m}:{s:02d}"

    def _mini_countdown_tick(self) -> None:
        """Tick the minimized-break countdown indicator."""
        if not self._mini_ind:
            return
        try:
            if not self._mini_ind.winfo_exists():
                return
        except tk.TclError:
            return

        if self._mini_rem > 0:
            self._mini_rem -= 1
            self._mini_cd_var.set(self._fmt_mm_ss(self._mini_rem))
            self._mini_ind.after(1000, self._mini_countdown_tick)
        else:
            # Time's up — show a "break done" notification
            self._mini_cd_var.set("0:00")
            self._show_break_done_notif()

    def _show_break_done_notif(self) -> None:
        """Replace the minimized indicator with a 'break complete' notification."""
        # Destroy the small countdown indicator
        if self._mini_ind:
            try:
                self._mini_ind.destroy()
            except tk.TclError:
                pass
            self._mini_ind = None

        # Play sound
        if self.config.get("sound_enabled", True):
            custom = self.config.get("custom_sound_path") if self.config.get("custom_sound_enabled") else None
            play_sound("chime", custom)

        notif = tk.Toplevel(self.root)
        notif.overrideredirect(True);  notif.attributes("-topmost", True)
        try:
            notif.attributes("-alpha", 0.95)
        except tk.TclError:
            pass
        notif.configure(bg=C_CARD)
        sw = notif.winfo_screenwidth()
        notif.geometry(f"260x80+{sw - 280}+{18}")

        f = tk.Frame(notif, bg=C_CARD, padx=14, pady=10)
        f.pack(fill="both", expand=True)

        tk.Label(f, text="Break complete!", font=(FONT, 13, "bold"),
                 fg=C_ACCENT2, bg=C_CARD).pack(anchor="w")
        tk.Label(f, text="Click to finish  |  break overlay is ready",
                 font=(FONT, 9), fg=C_TEXT_MUT, bg=C_CARD).pack(anchor="w", pady=(2, 0))
        notif.configure(cursor="hand2")

        self._mini_done_notif = notif

        def finish(e=None):
            try:
                notif.destroy()
            except tk.TclError:
                pass
            self._mini_done_notif = None
            self._restore_break()

        notif.bind("<Button-1>", finish)
        # Auto-dismiss after 30 seconds and restore overlay
        notif.after(30000, finish)

    def _restore_break(self) -> None:
        """Bring back the hidden break overlay."""
        # Clean up indicator / notification
        for w in (self._mini_ind, getattr(self, "_mini_done_notif", None)):
            if w:
                try:
                    w.destroy()
                except tk.TclError:
                    pass
        self._mini_ind = None
        self._mini_done_notif = None

        restore_cb = getattr(self, "_mini_restore_cb", None)
        ov = getattr(self, "_mini_ov", None)
        if ov:
            try:
                if restore_cb:
                    restore_cb()
                ov.deiconify()
                ov.attributes("-topmost", True)
                ov.lift()
                ov.focus_force()
            except tk.TclError:
                pass
            self._mini_ov = None
            self._mini_restore_cb = None

    def _dismiss(self, ov: tk.Toplevel) -> None:
        self.overlay_up = False
        self.current_overlay = None
        # Also clean up any minimized-break state
        for w in (getattr(self, "_mini_ind", None),
                  getattr(self, "_mini_done_notif", None)):
            if w:
                try:
                    w.destroy()
                except tk.TclError:
                    pass
        self._mini_ind = None
        self._mini_done_notif = None
        self._mini_ov = None
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
            custom = self.config.get("custom_sound_path") if self.config.get("custom_sound_enabled") else None
            play_sound("chime", custom)

        ov = tk.Toplevel(self.root)
        ov.attributes("-topmost", True)
        ov.configure(bg=C_EYE_BG)

        # Get monitors for multi-monitor support
        monitors = get_all_monitors() if self.config.get("multi_monitor_overlay", True) else [(0, 0, None, None)]
        self._eye_overlays = [ov]  # Track all overlays

        # Primary monitor setup
        mx, my, mw, mh = monitors[0]
        sw = mw if mw else ov.winfo_screenwidth()
        sh = mh if mh else ov.winfo_screenheight()
        ov.geometry(f"{sw}x{sh}+{mx}+{my}")
        ov.overrideredirect(True)
        ov.lift()
        ov.focus_force()

        # Create dim overlays on secondary monitors
        for mon in monitors[1:]:
            sx, sy, smw, smh = mon
            if smw and smh:
                sec = tk.Toplevel(self.root)
                sec.overrideredirect(True)
                sec.attributes("-topmost", True)
                sec.configure(bg=C_EYE_BG)
                sec.geometry(f"{smw}x{smh}+{sx}+{sy}")
                try:
                    sec.attributes("-alpha", 0.85)
                except tk.TclError:
                    pass
                # Simple centered message
                tk.Label(sec, text="🌿\nLook away — rest your eyes", font=(FONT, 20),
                         fg=C_EYE_ACC, bg=C_EYE_BG, justify="center"
                         ).place(relx=0.5, rely=0.5, anchor="center")
                self._eye_overlays.append(sec)

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

        # Guided eye exercise animation
        self._eye_exercise = None
        if self.config.get("guided_eye_exercises", False):
            pattern = random.choice(EYE_EXERCISE_PATTERNS)
            tk.Label(cf, text=pattern["name"], font=(FONT, 28, "bold"),
                     fg=C_EYE_ACC, bg=C_EYE_BG).pack(pady=(0, 8))
            tk.Label(cf, text=pattern["instruction"], font=(FONT, 14), fg=C_TEXT_DIM,
                     bg=C_EYE_BG).pack(pady=(0, 16))

            # Canvas for animated dot - large for proper eye tracking
            eye_canvas = tk.Canvas(cf, width=700, height=500, bg=C_EYE_BG, highlightthickness=0)
            eye_canvas.pack(pady=(0, 20))
            self._eye_exercise = GuidedEyeExercise(eye_canvas, 700, 500, pattern["pattern"])
            self._eye_exercise.start()
        else:
            tk.Label(cf, text="Look away — 20 feet or more", font=(FONT, 28, "bold"),
                     fg=C_EYE_ACC, bg=C_EYE_BG).pack(pady=(0, 16))

            # Show eye exercise text if enabled
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
        # Stop eye exercise animation if running
        if self._eye_exercise:
            self._eye_exercise.stop()
            self._eye_exercise = None
        # Destroy secondary monitor overlays
        for sec_ov in getattr(self, '_eye_overlays', [])[1:]:
            try:
                sec_ov.destroy()
            except tk.TclError:
                pass
        self._eye_overlays = []
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
            custom = self.config.get("custom_sound_path") if self.config.get("custom_sound_enabled") else None
            play_sound("chime", custom)

        # Determine if we need extra height for animations
        has_breathing = self.config.get("breathing_exercises", False)
        has_desk = self.config.get("desk_exercises", False)
        win_height = 450 + (120 if has_breathing else 0) + (100 if has_desk else 0)

        ov = tk.Toplevel(self.root)
        ov.overrideredirect(True);  ov.attributes("-topmost", True)
        ov.configure(bg=C_BG);  self._centre(ov, 500, win_height)
        ov.lift();  ov.focus_force()

        card = tk.Frame(ov, bg=C_CARD, padx=32, pady=22)
        card.pack(fill="both", expand=True, padx=2, pady=2)

        tk.Label(card, text="🧘  Time to move", font=(FONT, 16, "bold"),
                 fg=C_ACCENT, bg=C_CARD).pack(pady=(0, 10))

        # Show custom message or exercise suggestion
        if self.config.get("use_custom_messages") and self.config.get("custom_messages"):
            custom_msg = random.choice(self.config["custom_messages"])
            body = f"~{iv} minutes of focus — well done.\n\n💬 {custom_msg}"
        elif self.config.get("show_exercises", True):
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

        # Breathing exercise animation
        self._breathing_exercise = None
        if has_breathing:
            breath_frame = tk.Frame(card, bg=C_CARD)
            breath_frame.pack(pady=(8, 8))

            pattern = random.choice(list(BREATHING_PATTERNS.keys()))
            tk.Label(breath_frame, text=BREATHING_PATTERNS[pattern]["name"],
                     font=(FONT, 10, "bold"), fg=C_ACCENT2, bg=C_CARD).pack()

            breath_canvas = tk.Canvas(breath_frame, width=120, height=80, bg=C_CARD, highlightthickness=0)
            breath_canvas.pack()

            breath_label = tk.Label(breath_frame, text="", font=(FONT, 10), fg=C_TEXT_DIM, bg=C_CARD)
            breath_label.pack()

            self._breathing_exercise = BreathingExercise(breath_canvas, breath_label, 120, 80, pattern)
            self._breathing_exercise.start()

        # Desk exercise animation
        self._desk_exercise = None
        if has_desk:
            desk_frame = tk.Frame(card, bg=C_CARD)
            desk_frame.pack(pady=(8, 8))

            exercise_data = random.choice(DESK_EXERCISES)
            tk.Label(desk_frame, text=exercise_data["name"],
                     font=(FONT, 10, "bold"), fg=C_ACCENT2, bg=C_CARD).pack()

            desk_label = tk.Label(desk_frame, text=exercise_data["frames"][0],
                                  font=(MONO, 12), fg=C_TEXT_DIM, bg=C_CARD)
            desk_label.pack()

            tk.Label(desk_frame, text=exercise_data["instruction"],
                     font=(FONT, 9), fg=C_TEXT_MUT, bg=C_CARD).pack()

            self._desk_exercise = DeskExerciseAnimation(desk_label, exercise_data)
            self._desk_exercise.start()

        tk.Label(card, text="Capture where you are (optional):",
                 font=(FONT, 9), fg=C_TEXT_MUT, bg=C_CARD, anchor="w").pack(fill="x", pady=(6, 2))
        note = tk.Text(card, height=2, font=(MONO, 10), bg=C_CARD_IN, fg=C_TEXT,
                       insertbackground=C_TEXT, relief="flat", padx=8, pady=6, wrap="word")
        note.pack(fill="x", pady=(0, 8))

        tk.Label(card, text=datetime.datetime.now().strftime("%I:%M %p").lstrip("0"),
                 font=(FONT, 9), fg=C_TEXT_MUT, bg=C_CARD).pack(pady=(6, 6))

        # Countdown timer (5 minutes)
        self._micro_cd_var = tk.StringVar(value="5:00")
        self._break_rem = 5 * 60  # Track remaining for minimize
        tk.Label(card, textvariable=self._micro_cd_var,
                 font=(MONO, 28, "bold"), fg=C_CD, bg=C_CARD).pack(pady=(0, 10))

        bf = tk.Frame(card, bg=C_CARD);  bf.pack()
        sm = self.config.get("snooze_minutes", 5)

        def back_from_break():
            self._grab_note(note)
            # Stop animations
            if self._breathing_exercise:
                self._breathing_exercise.stop()
            if self._desk_exercise:
                self._desk_exercise.stop()
            # Track statistics
            self.stats["lifetime"]["micro_taken"] = self.stats["lifetime"].get("micro_taken", 0) + 1
            self.stats["today"]["micro_taken"] = self.stats["today"].get("micro_taken", 0) + 1
            save_stats(self.stats)
            self._reset_all_timers()
            self._dismiss(ov)

        def skip_break():
            # Stop animations
            if self._breathing_exercise:
                self._breathing_exercise.stop()
            if self._desk_exercise:
                self._desk_exercise.stop()
            self.stats["lifetime"]["micro_skipped"] = self.stats["lifetime"].get("micro_skipped", 0) + 1
            save_stats(self.stats)
            self._reset_all_timers()
            self._dismiss(ov)

        def snooze_micro():
            self._grab_note(note)
            if self._breathing_exercise:
                self._breathing_exercise.stop()
            if self._desk_exercise:
                self._desk_exercise.stop()
            self._snooze(ov)

        def minimize_micro():
            self._grab_note(note)
            self._minimize_break(ov, self._break_rem, 5 * 60, restore_micro)

        def restore_micro():
            # Update the countdown display with current remaining
            m, s = divmod(max(0, self._break_rem), 60)
            self._micro_cd_var.set(f"{m}:{s:02d}")

        self._btn(bf, "  Back from break  ", C_BTN_PRI, back_from_break)
        self._btn(bf, f"  {sm} more min  ", C_BTN_SEC, snooze_micro)
        if not self.config.get("strict_mode", False):
            self._btn(bf, "  Minimize  ", C_BTN_SEC, minimize_micro)
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
        self._break_rem = rem  # Track for minimize
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
            custom = self.config.get("custom_sound_path") if self.config.get("custom_sound_enabled") else None
            play_sound("chime", custom)

        ov = tk.Toplevel(self.root)
        ov.overrideredirect(True);  ov.attributes("-topmost", True)
        ov.configure(bg=C_BG);  self._centre(ov, 560, 520)
        ov.lift();  ov.focus_force()

        card = tk.Frame(ov, bg=C_CARD, padx=32, pady=20)
        card.pack(fill="both", expand=True, padx=2, pady=2)
        dl = f" — {duration} min" if duration > 0 else ""
        tk.Label(card, text=f"⏸  {title}{dl}", font=(FONT, 17, "bold"),
                 fg=C_ACCENT, bg=C_CARD).pack(pady=(0, 10))
        body = get_desc(title, self.low_energy)

        # Add custom message or movement suggestion
        if self.config.get("use_custom_messages") and self.config.get("custom_messages"):
            custom_msg = random.choice(self.config["custom_messages"])
            body = body + f"\n\n💬 {custom_msg}"
        elif self.config.get("show_exercises", True) and duration >= 10:
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
                 font=(FONT, 9), fg=C_TEXT_MUT, bg=C_CARD).pack(pady=(0, 4))

        # Countdown timer
        total_sec = max(1, duration) * 60
        self._long_cd_var = tk.StringVar(value=self._fmt_mm_ss(total_sec))
        self._break_rem = total_sec
        tk.Label(card, textvariable=self._long_cd_var,
                 font=(MONO, 28, "bold"), fg=C_CD, bg=C_CARD).pack(pady=(0, 10))

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

        def minimize_long():
            self._grab_note(note)
            self._minimize_break(ov, self._break_rem, total_sec, restore_long)

        def restore_long():
            self._long_cd_var.set(self._fmt_mm_ss(self._break_rem))

        self._btn(bf, "  Back from break  ", C_BTN_PRI, back_from_break, bold=True)
        self._btn(bf, f"  {sm} more min  ", C_BTN_SEC, snz)
        if not self.config.get("strict_mode", False):
            self._btn(bf, "  Minimize  ", C_BTN_SEC, minimize_long)
        self.current_overlay = ov

        # Start countdown
        self._long_countdown(ov, total_sec)

        # Escape = skip break (unless strict mode)
        if self.config.get("strict_mode", False):
            ov.bind("<Escape>", lambda e: None)  # Disable escape in strict mode
        else:
            ov.bind("<Escape>", lambda e: skip_break())
        ov.focus_set()

    def _long_countdown(self, ov, rem):
        if self.current_overlay != ov:
            return
        if rem < 0:
            rem = 0
        self._break_rem = rem
        self._long_cd_var.set(self._fmt_mm_ss(rem))
        if rem > 0:
            ov.after(1000, lambda: self._long_countdown(ov, rem - 1))

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
            print(f"  [!] Notes save error: {e}")

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
        if self._notes_win:
            try: self._notes_win.lift();  self._notes_win.focus_force();  return
            except tk.TclError: self._notes_win = None

        win = tk.Toplevel(self.root)
        win.title("Screen Break — Notes")
        win.geometry("580x450")
        win.configure(bg=C_BG)
        self._notes_win = win

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
                txt.insert("end", f"── {e.get('time', 'Unknown')} ──\n{e.get('note', '')}\n\n")
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
            confirm.protocol("WM_DELETE_WINDOW", confirm.destroy)
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
                        f.write(f"## {e.get('time', 'Unknown')}\n\n{e.get('note', '')}\n\n---\n\n")
                # Show brief confirmation
                txt.configure(state="normal")
                txt.insert("1.0", f"✓ Exported to {export_path}\n\n")
                txt.configure(state="disabled")
            except (IOError, OSError) as err:
                txt.configure(state="normal")
                txt.insert("1.0", f"⚠ Export failed: {err}\n\n")
                txt.configure(state="disabled")

        def on_close():
            self._notes_win = None
            win.destroy()

        tk.Button(bf, text="Export .md", font=(FONT, 9), bg=C_BTN_SEC, fg=C_TEXT_DIM,
                  relief="flat", padx=12, pady=4, cursor="hand2", command=export_notes).pack(side="left", padx=4)
        tk.Button(bf, text="Clear All", font=(FONT, 9), bg=C_BTN_SEC, fg=C_TEXT_DIM,
                  relief="flat", padx=12, pady=4, cursor="hand2", command=clear_notes).pack(side="left", padx=4)
        tk.Button(bf, text="Close", font=(FONT, 10), bg=C_BTN_SEC, fg=C_TEXT,
                  relief="flat", padx=16, pady=4, cursor="hand2", command=on_close).pack(side="left", padx=4)

        win.protocol("WM_DELETE_WINDOW", on_close)

    # ━━━ Statistics Window ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _show_stats_win(self) -> None:
        if self._stats_win:
            try: self._stats_win.lift();  self._stats_win.focus_force();  return
            except tk.TclError: self._stats_win = None

        win = tk.Toplevel(self.root)
        win.title("Screen Break — Statistics")
        win.geometry("400x580")
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
        tk.Label(sf, text="Days with at least one break taken",
                 font=(FONT, 9), fg=C_TEXT_MUT, bg=C_CARD).pack(anchor="w", pady=(2, 0))

        # Weekly chart
        cf = tk.Frame(win, bg=C_CARD, padx=16, pady=12)
        cf.pack(fill="x", padx=14, pady=(0, 8))
        tk.Label(cf, text="📊  Last 7 Days", font=(FONT, 12, "bold"),
                 fg=C_TEXT, bg=C_CARD).pack(anchor="w")

        # Build chart data - include today + history
        chart_data = []
        history = self.stats.get("daily_history", [])
        for entry in history[-6:]:  # Last 6 days from history
            chart_data.append(entry)
        # Add today
        today_entry = {
            "date": datetime.date.today().isoformat(),
            "eye": today.get("eye_rest_taken", 0),
            "micro": today.get("micro_taken", 0),
            "scheduled": today.get("scheduled_taken", 0),
        }
        chart_data.append(today_entry)

        # Pad to 7 days if needed
        while len(chart_data) < 7:
            chart_data.insert(0, {"date": "", "eye": 0, "micro": 0, "scheduled": 0})

        # Draw bar chart
        canvas = tk.Canvas(cf, width=340, height=100, bg=C_CARD, highlightthickness=0)
        canvas.pack(pady=(8, 4))

        bar_width = 35
        gap = 12
        max_val = max(1, max(d["eye"] + d["micro"] + d["scheduled"] for d in chart_data))
        scale = 70 / max_val

        for i, day in enumerate(chart_data):
            x = 15 + i * (bar_width + gap)
            total = day["eye"] + day["micro"] + day["scheduled"]

            # Stacked bars
            y = 85
            if day["eye"] > 0:
                h = day["eye"] * scale
                canvas.create_rectangle(x, y - h, x + bar_width, y, fill=C_EYE_ACC, outline="")
                y -= h
            if day["micro"] > 0:
                h = day["micro"] * scale
                canvas.create_rectangle(x, y - h, x + bar_width, y, fill=C_ACCENT, outline="")
                y -= h
            if day["scheduled"] > 0:
                h = day["scheduled"] * scale
                canvas.create_rectangle(x, y - h, x + bar_width, y, fill=C_ACCENT2, outline="")

            # Day label
            if day["date"]:
                try:
                    d = datetime.date.fromisoformat(day["date"])
                    label = d.strftime("%a")[:2]
                except ValueError:
                    label = ""
            else:
                label = ""
            canvas.create_text(x + bar_width // 2, 95, text=label, font=(FONT, 8), fill=C_TEXT_MUT)

        # Legend
        legend_frame = tk.Frame(cf, bg=C_CARD)
        legend_frame.pack(anchor="w")
        for color, label in [(C_EYE_ACC, "Eye"), (C_ACCENT, "Micro"), (C_ACCENT2, "Sched")]:
            lf = tk.Frame(legend_frame, bg=C_CARD)
            lf.pack(side="left", padx=(0, 12))
            tk.Canvas(lf, width=10, height=10, bg=color, highlightthickness=0).pack(side="left", padx=(0, 4))
            tk.Label(lf, text=label, font=(FONT, 8), fg=C_TEXT_MUT, bg=C_CARD).pack(side="left")

        # Lifetime stats
        lf = tk.Frame(win, bg=C_CARD, padx=16, pady=12)
        lf.pack(fill="x", padx=14, pady=(0, 8))
        tk.Label(lf, text="📈  Lifetime", font=(FONT, 12, "bold"),
                 fg=C_TEXT, bg=C_CARD).pack(anchor="w")
        lt = self.stats.get("lifetime", {})
        lt_text = (f"Eye rests completed: {lt.get('eye_rest_taken', 0)}\n"
                   f"Micro-pauses completed: {lt.get('micro_taken', 0)}\n"
                   f"Scheduled breaks completed: {lt.get('scheduled_taken', 0)}")
        tk.Label(lf, text=lt_text, font=(FONT, 10), fg=C_TEXT_DIM,
                 bg=C_CARD, justify="left").pack(anchor="w", pady=(4, 0))

        # Total breaks - cumulative progress
        total_taken = (lt.get('eye_rest_taken', 0) + lt.get('micro_taken', 0) + lt.get('scheduled_taken', 0))
        tk.Label(lf, text=f"Total breaks: {total_taken}", font=(FONT, 11, "bold"),
                 fg=C_OK, bg=C_CARD).pack(anchor="w", pady=(8, 0))

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
            confirm.protocol("WM_DELETE_WINDOW", confirm.destroy)
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

        def on_close():
            self._stats_win = None
            win.destroy()

        tk.Button(bf, text="Reset Stats", font=(FONT, 9), bg=C_BTN_SEC, fg=C_TEXT_DIM,
                  relief="flat", padx=12, pady=4, cursor="hand2", command=reset_stats).pack(side="left", padx=4)
        tk.Button(bf, text="Close", font=(FONT, 10), bg=C_BTN_SEC, fg=C_TEXT,
                  relief="flat", padx=16, pady=4, cursor="hand2", command=on_close).pack(side="left", padx=4)

        win.protocol("WM_DELETE_WINDOW", on_close)

    # ━━━ Status & Settings Window ━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _show_status_window(self):
        if self._status_win:
            try: self._status_win.lift();  self._status_win.focus_force();  return
            except tk.TclError: self._status_win = None

        win = tk.Toplevel(self.root)
        win.title("Screen Break — Status & Settings")
        win.configure(bg=C_BG);  win.resizable(False, True)
        if self.config.get("status_always_on_top", False):
            win.attributes("-topmost", True)
        self._status_win = win

        pad = dict(padx=20)

        # ══════ CONTROL BUTTONS ══════
        ctrl_frame = tk.Frame(win, bg=C_BG)
        ctrl_frame.pack(fill="x", pady=(14, 8), **pad)

        self._pause_btn = tk.Button(ctrl_frame, text="⏸ Pause", font=(FONT, 9), bg=C_BTN_SEC, fg=C_TEXT,
                  relief="flat", width=9, pady=4, cursor="hand2", command=self._toggle_pause_ui)
        self._pause_btn.pack(side="left", padx=(0, 6))
        ToolTip(self._pause_btn, "Pause all break reminders")

        self._gentle_btn = tk.Button(ctrl_frame, text="🪫 Gentle", font=(FONT, 9),
                  bg=C_BTN_SEC, fg=C_TEXT_DIM, relief="flat", width=9, pady=4, cursor="hand2",
                  command=self._toggle_gentle_ui)
        self._gentle_btn.pack(side="left", padx=(0, 6))
        self._update_gentle_btn()
        ToolTip(self._gentle_btn, "Gentler reminders (1.5x longer intervals)")

        stats_btn = tk.Button(ctrl_frame, text="📊 Stats", font=(FONT, 9), bg=C_BTN_SEC, fg=C_TEXT_DIM,
                  relief="flat", padx=10, pady=4, cursor="hand2",
                  command=self._toggle_stats_win)
        stats_btn.pack(side="left", padx=(0, 6))
        ToolTip(stats_btn, "View break statistics and streaks")

        notes_btn = tk.Button(ctrl_frame, text="📝 Notes", font=(FONT, 9), bg=C_BTN_SEC, fg=C_TEXT_DIM,
                  relief="flat", padx=10, pady=4, cursor="hand2",
                  command=self._toggle_notes_win)
        notes_btn.pack(side="left", padx=(0, 6))
        ToolTip(notes_btn, "View notes captured during breaks")

        focus_btn = tk.Button(ctrl_frame, text="🎯 Focus", font=(FONT, 9), bg=C_BTN_SEC, fg=C_TEXT_DIM,
                  relief="flat", padx=10, pady=4, cursor="hand2",
                  command=self._show_focus_session_dialog)
        focus_btn.pack(side="left")
        ToolTip(focus_btn, "Start a timed focus session")

        # ══════ COUNTDOWNS (FIXED TOP) ══════
        self._st_rows = {}
        for key, icon in [("eye", "🌿  Eye rest"), ("micro", "🧘  Micro-pause"), ("sched", "📋  Next break")]:
            lf = tk.Frame(win, bg=C_CARD, padx=14, pady=8);  lf.pack(fill="x", pady=2, **pad)
            tk.Label(lf, text=icon, font=(FONT, 10), fg=C_TEXT_DIM, bg=C_CARD, anchor="w").pack(fill="x")
            tv = tk.StringVar(value="--:--")
            tk.Label(lf, textvariable=tv, font=(MONO, 18, "bold"), fg=C_CD, bg=C_CARD, anchor="w").pack(fill="x")
            dv = tk.StringVar()
            tk.Label(lf, textvariable=dv, font=(FONT, 9), fg=C_TEXT_MUT, bg=C_CARD, anchor="w").pack(fill="x")
            self._st_rows[key] = (tv, dv)

        # ══════ COLLAPSIBLE SETTINGS SECTION ══════
        self._settings_expanded = tk.BooleanVar(value=True)
        settings_header = tk.Frame(win, bg=C_BG)
        settings_header.pack(fill="x", **pad)

        # Container for all settings content
        self._settings_container = tk.Frame(win, bg=C_BG)

        def toggle_settings():
            if self._settings_expanded.get():
                self._settings_container.pack(fill="both", expand=True, after=settings_header)
                self._settings_btn_frame.pack(side="right")
                settings_toggle_btn.config(text="▼ Settings")
                # Expand window to show settings
                win.update_idletasks()
                win.geometry("")  # Reset to natural size
            else:
                self._settings_container.pack_forget()
                self._settings_btn_frame.pack_forget()
                settings_toggle_btn.config(text="▶ Settings")
                # Shrink window to compact size
                win.update_idletasks()
                win.geometry("")  # Reset to natural size

        settings_toggle_btn = tk.Button(settings_header, text="▼ Settings", font=(FONT, 13, "bold"),
                            fg=C_ACCENT2, bg=C_BG, relief="flat", cursor="hand2",
                            command=lambda: [self._settings_expanded.set(not self._settings_expanded.get()), toggle_settings()])
        settings_toggle_btn.pack(side="left")

        # Buttons on same row as Settings toggle (inside header so they hide with settings)
        self._settings_btn_frame = tk.Frame(settings_header, bg=C_BG)
        self._settings_btn_frame.pack(side="right")

        self._save_fb = tk.StringVar()
        tk.Label(self._settings_btn_frame, textvariable=self._save_fb, font=(FONT, 8), fg=C_OK, bg=C_BG).pack(side="left", padx=(0, 8))
        tk.Button(self._settings_btn_frame, text="Apply & Save", font=(FONT, 9), bg=C_BTN_PRI, fg=C_TEXT,
                  relief="flat", padx=10, pady=2, cursor="hand2",
                  command=self._apply_settings).pack(side="left")
        tk.Button(self._settings_btn_frame, text="Reset", font=(FONT, 9), bg=C_BTN_SEC, fg=C_TEXT_DIM,
                  relief="flat", padx=8, pady=2, cursor="hand2",
                  command=self._reset_defaults).pack(side="left", padx=(6, 0))

        # Show settings container initially
        self._settings_container.pack(fill="both", expand=True)

        # ══════ SCROLLABLE SETTINGS AREA ══════
        scroll_container = tk.Frame(self._settings_container, bg=C_BG)
        scroll_container.pack(fill="both", expand=True, pady=(6, 0))

        canvas = tk.Canvas(scroll_container, bg=C_BG, highlightthickness=0, height=320)
        scrollbar = tk.Scrollbar(scroll_container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        scroll_frame = tk.Frame(canvas, bg=C_BG)
        canvas_window = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")

        # Mousewheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        def _on_enter(event):
            canvas.bind_all("<MouseWheel>", _on_mousewheel)
        def _on_leave(event):
            canvas.unbind_all("<MouseWheel>")
        canvas.bind("<Enter>", _on_enter)
        canvas.bind("<Leave>", _on_leave)

        # Update scroll region when content changes
        def _configure_scroll(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(canvas_window, width=event.width)
        scroll_frame.bind("<Configure>", _configure_scroll)
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_window, width=e.width))

        spad = dict(padx=20)  # Padding inside scroll area

        # ══════ INTERVALS & TIMING ══════
        tk.Label(scroll_frame, text="Intervals & Timing", font=(FONT, 11, "bold"),
                 fg=C_TEXT_DIM, bg=C_BG).pack(pady=(4, 6), **spad, anchor="w")

        ivf = tk.Frame(scroll_frame, bg=C_BG);  ivf.pack(fill="x", **spad)

        ef = tk.Frame(ivf, bg=C_BG);  ef.pack(fill="x", pady=2)
        tk.Label(ef, text="Eye rest every", font=(FONT, 10), fg=C_TEXT_DIM,
                 bg=C_BG, width=22, anchor="w").pack(side="left")
        self._eye_spin = tk.Spinbox(ef, from_=5, to=120, width=4,
            font=(MONO, 10), bg=C_CARD_IN, fg=C_TEXT, buttonbackground=C_BTN_SEC,
            relief="flat", justify="center")
        self._eye_spin.pack(side="left");  self._eye_spin.delete(0, "end")
        self._eye_spin.insert(0, str(self.config.get("eye_rest_interval", 20)))
        tk.Label(ef, text=" min", font=(FONT, 10), fg=C_TEXT_MUT, bg=C_BG).pack(side="left")

        mf = tk.Frame(ivf, bg=C_BG);  mf.pack(fill="x", pady=2)
        tk.Label(mf, text="Micro-pause every", font=(FONT, 10), fg=C_TEXT_DIM,
                 bg=C_BG, width=22, anchor="w").pack(side="left")
        self._micro_spin = tk.Spinbox(mf, from_=10, to=120, width=4,
            font=(MONO, 10), bg=C_CARD_IN, fg=C_TEXT, buttonbackground=C_BTN_SEC,
            relief="flat", justify="center")
        self._micro_spin.pack(side="left");  self._micro_spin.delete(0, "end")
        self._micro_spin.insert(0, str(self.config.get("micro_pause_interval", 45)))
        tk.Label(mf, text=" min", font=(FONT, 10), fg=C_TEXT_MUT, bg=C_BG).pack(side="left")

        gf = tk.Frame(ivf, bg=C_BG);  gf.pack(fill="x", pady=2)
        tk.Label(gf, text="Min gap between breaks", font=(FONT, 10), fg=C_TEXT_DIM,
                 bg=C_BG, width=22, anchor="w").pack(side="left")
        self._gap_spin = tk.Spinbox(gf, from_=0, to=60, width=4,
            font=(MONO, 10), bg=C_CARD_IN, fg=C_TEXT, buttonbackground=C_BTN_SEC,
            relief="flat", justify="center")
        self._gap_spin.pack(side="left");  self._gap_spin.delete(0, "end")
        self._gap_spin.insert(0, str(self.config.get("minimum_break_gap", 20)))
        tk.Label(gf, text=" min", font=(FONT, 10), fg=C_TEXT_MUT, bg=C_BG).pack(side="left")

        edf = tk.Frame(ivf, bg=C_BG);  edf.pack(fill="x", pady=2)
        tk.Label(edf, text="Eye rest duration", font=(FONT, 10), fg=C_TEXT_DIM,
                 bg=C_BG, width=22, anchor="w").pack(side="left")
        self._eye_dur_spin = tk.Spinbox(edf, from_=5, to=60, width=4,
            font=(MONO, 10), bg=C_CARD_IN, fg=C_TEXT, buttonbackground=C_BTN_SEC,
            relief="flat", justify="center")
        self._eye_dur_spin.pack(side="left");  self._eye_dur_spin.delete(0, "end")
        self._eye_dur_spin.insert(0, str(self.config.get("eye_rest_duration", 20)))
        tk.Label(edf, text=" sec", font=(FONT, 10), fg=C_TEXT_MUT, bg=C_BG).pack(side="left")

        sf = tk.Frame(ivf, bg=C_BG);  sf.pack(fill="x", pady=2)
        tk.Label(sf, text="Snooze duration", font=(FONT, 10), fg=C_TEXT_DIM,
                 bg=C_BG, width=22, anchor="w").pack(side="left")
        self._snooze_spin = tk.Spinbox(sf, from_=1, to=30, width=4,
            font=(MONO, 10), bg=C_CARD_IN, fg=C_TEXT, buttonbackground=C_BTN_SEC,
            relief="flat", justify="center")
        self._snooze_spin.pack(side="left");  self._snooze_spin.delete(0, "end")
        self._snooze_spin.insert(0, str(self.config.get("snooze_minutes", 5)))
        tk.Label(sf, text=" min", font=(FONT, 10), fg=C_TEXT_MUT, bg=C_BG).pack(side="left")

        warnf = tk.Frame(ivf, bg=C_BG);  warnf.pack(fill="x", pady=2)
        tk.Label(warnf, text="Warning before break", font=(FONT, 10), fg=C_TEXT_DIM,
                 bg=C_BG, width=22, anchor="w").pack(side="left")
        self._warn_spin = tk.Spinbox(warnf, from_=10, to=300, width=4,
            font=(MONO, 10), bg=C_CARD_IN, fg=C_TEXT, buttonbackground=C_BTN_SEC,
            relief="flat", justify="center")
        self._warn_spin.pack(side="left");  self._warn_spin.delete(0, "end")
        self._warn_spin.insert(0, str(self.config.get("warning_seconds", 60)))
        tk.Label(warnf, text=" sec", font=(FONT, 10), fg=C_TEXT_MUT, bg=C_BG).pack(side="left")

        wf = tk.Frame(ivf, bg=C_BG);  wf.pack(fill="x", pady=2)
        tk.Label(wf, text="Work hours", font=(FONT, 10), fg=C_TEXT_DIM,
                 bg=C_BG, width=22, anchor="w").pack(side="left")
        self._ws_entry = tk.Entry(wf, width=6, font=(MONO, 10), bg=C_CARD_IN,
                                  fg=C_TEXT, relief="flat", justify="center")
        self._ws_entry.pack(side="left");  self._ws_entry.insert(0, self.config.get("work_start", "08:00"))
        tk.Label(wf, text=" to ", font=(FONT, 10), fg=C_TEXT_MUT, bg=C_BG).pack(side="left")
        self._we_entry = tk.Entry(wf, width=6, font=(MONO, 10), bg=C_CARD_IN,
                                  fg=C_TEXT, relief="flat", justify="center")
        self._we_entry.pack(side="left");  self._we_entry.insert(0, self.config.get("work_end", "20:00"))

        # Coast margin setting
        coastf = tk.Frame(ivf, bg=C_BG);  coastf.pack(fill="x", pady=2)
        tk.Label(coastf, text="Skip if scheduled within", font=(FONT, 10), fg=C_TEXT_DIM,
                 bg=C_BG, width=22, anchor="w").pack(side="left")
        self._coast_spin = tk.Spinbox(coastf, from_=0, to=30, width=3,
            font=(MONO, 10), bg=C_CARD_IN, fg=C_TEXT, buttonbackground=C_BTN_SEC,
            relief="flat", justify="center")
        self._coast_spin.pack(side="left");  self._coast_spin.delete(0, "end")
        self._coast_spin.insert(0, str(self.config.get("coast_margin_minutes", 10)))
        tk.Label(coastf, text=" min", font=(FONT, 10), fg=C_TEXT_MUT, bg=C_BG).pack(side="left")

        # ══════ SCHEDULED BREAKS ══════
        tk.Frame(scroll_frame, bg=C_TEXT_MUT, height=1).pack(fill="x", pady=(10, 6), **spad)
        tk.Label(scroll_frame, text="Scheduled Breaks  (local time)", font=(FONT, 11, "bold"),
                 fg=C_TEXT_DIM, bg=C_BG).pack(pady=(0, 4), **spad, anchor="w")

        hdr = tk.Frame(scroll_frame, bg=C_BG);  hdr.pack(fill="x", **spad)
        tk.Label(hdr, text="Time", font=(FONT, 9), fg=C_TEXT_MUT, bg=C_BG, width=7, anchor="w").pack(side="left")
        tk.Label(hdr, text="Dur", font=(FONT, 9), fg=C_TEXT_MUT, bg=C_BG, width=5, anchor="w").pack(side="left")
        tk.Label(hdr, text="Name", font=(FONT, 9), fg=C_TEXT_MUT, bg=C_BG, anchor="w").pack(side="left", fill="x", expand=True)

        self._brk_container = tk.Frame(scroll_frame, bg=C_BG)
        self._brk_container.pack(fill="x", **spad)
        self._brk_rows = []
        for brk in self.config.get("breaks", []):
            self._add_brk_row(brk["time"], brk["duration"], brk["title"])

        tk.Button(scroll_frame, text="+ Add break", font=(FONT, 9), bg=C_BTN_SEC, fg=C_TEXT_DIM,
                  relief="flat", padx=10, pady=2, cursor="hand2",
                  command=lambda: self._add_brk_row("12:00", 15, "New Break")).pack(
                      pady=(4, 8), **spad, anchor="w")

        # ══════ FEATURES ══════
        tk.Frame(scroll_frame, bg=C_TEXT_MUT, height=1).pack(fill="x", pady=(6, 6), **spad)
        tk.Label(scroll_frame, text="Features", font=(FONT, 11, "bold"),
                 fg=C_TEXT_DIM, bg=C_BG).pack(pady=(0, 4), **spad, anchor="w")

        featf = tk.Frame(scroll_frame, bg=C_BG);  featf.pack(fill="x", **spad)

        # Presentation mode (focus_mode) - auto-pause during fullscreen/Zoom
        focf = tk.Frame(featf, bg=C_BG);  focf.pack(fill="x", pady=2)
        self._focus_var = tk.BooleanVar(value=self.config.get("focus_mode", True))
        tk.Checkbutton(focf, text="Presentation mode (auto-pause during fullscreen/Zoom)", font=(FONT, 10), fg=C_TEXT_DIM,
                       bg=C_BG, variable=self._focus_var, selectcolor=C_CARD_IN,
                       activebackground=C_BG, activeforeground=C_TEXT_DIM).pack(side="left")

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
        tk.Checkbutton(strf, text="Strict mode (snooze option only)", font=(FONT, 10), fg=C_TEXT_DIM,
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

        # Multi-monitor
        mmf = tk.Frame(featf, bg=C_BG);  mmf.pack(fill="x", pady=2)
        self._multimon_var = tk.BooleanVar(value=self.config.get("multi_monitor_overlay", True))
        tk.Checkbutton(mmf, text="Show overlay on all monitors", font=(FONT, 10), fg=C_TEXT_DIM,
                       bg=C_BG, variable=self._multimon_var, selectcolor=C_CARD_IN,
                       activebackground=C_BG, activeforeground=C_TEXT_DIM).pack(side="left")

        # Floating widget
        wdgf = tk.Frame(featf, bg=C_BG);  wdgf.pack(fill="x", pady=2)
        self._widget_var = tk.BooleanVar(value=self.config.get("show_floating_widget", True))
        tk.Checkbutton(wdgf, text="Floating countdown widget (always visible)", font=(FONT, 10), fg=C_TEXT_DIM,
                       bg=C_BG, variable=self._widget_var, selectcolor=C_CARD_IN,
                       activebackground=C_BG, activeforeground=C_TEXT_DIM).pack(side="left")

        # Taskbar presence
        tbf = tk.Frame(featf, bg=C_BG);  tbf.pack(fill="x", pady=2)
        self._taskbar_var = tk.BooleanVar(value=self.config.get("show_in_taskbar", True))
        tk.Checkbutton(tbf, text="Show in taskbar (restart to apply)", font=(FONT, 10), fg=C_TEXT_DIM,
                       bg=C_BG, variable=self._taskbar_var, selectcolor=C_CARD_IN,
                       activebackground=C_BG, activeforeground=C_TEXT_DIM).pack(side="left")

        # Always on top for settings window
        aotf = tk.Frame(featf, bg=C_BG);  aotf.pack(fill="x", pady=2)
        self._aot_var = tk.BooleanVar(value=self.config.get("status_always_on_top", False))
        tk.Checkbutton(aotf, text="Settings window always on top", font=(FONT, 10), fg=C_TEXT_DIM,
                       bg=C_BG, variable=self._aot_var, selectcolor=C_CARD_IN,
                       activebackground=C_BG, activeforeground=C_TEXT_DIM).pack(side="left")

        # --- Breathing circle widget ---
        bw_header = tk.Label(featf, text="Breathing Circle", font=(FONT, 10, "bold"),
                             fg=C_ACCENT2, bg=C_BG, anchor="w")
        bw_header.pack(fill="x", pady=(8, 2))

        bwf = tk.Frame(featf, bg=C_BG);  bwf.pack(fill="x", pady=2)
        self._breath_enabled_var = tk.BooleanVar(value=self.config.get("breathing_widget_enabled", False))
        tk.Checkbutton(bwf, text="Breathing circle widget (always visible)", font=(FONT, 10), fg=C_TEXT_DIM,
                       bg=C_BG, variable=self._breath_enabled_var, selectcolor=C_CARD_IN,
                       activebackground=C_BG, activeforeground=C_TEXT_DIM).pack(side="left")

        bwrow1 = tk.Frame(featf, bg=C_BG);  bwrow1.pack(fill="x", pady=1, padx=(20, 0))
        tk.Label(bwrow1, text="In:", font=(FONT, 10), fg=C_TEXT_MUT, bg=C_BG).pack(side="left")
        self._breath_inhale_spin = tk.Spinbox(bwrow1, from_=1, to=20, width=4, increment=0.5,
            format="%.1f", font=(MONO, 10), bg=C_CARD_IN, fg=C_TEXT, buttonbackground=C_BTN_SEC,
            relief="flat", justify="center")
        self._breath_inhale_spin.pack(side="left");  self._breath_inhale_spin.delete(0, "end")
        self._breath_inhale_spin.insert(0, str(float(self.config.get("breathing_widget_inhale", 4))))
        tk.Label(bwrow1, text="s Hold:", font=(FONT, 10), fg=C_TEXT_MUT, bg=C_BG).pack(side="left")
        self._breath_hold_in_spin = tk.Spinbox(bwrow1, from_=0, to=15, width=4, increment=0.5,
            format="%.1f", font=(MONO, 10), bg=C_CARD_IN, fg=C_TEXT, buttonbackground=C_BTN_SEC,
            relief="flat", justify="center")
        self._breath_hold_in_spin.pack(side="left");  self._breath_hold_in_spin.delete(0, "end")
        self._breath_hold_in_spin.insert(0, str(float(self.config.get("breathing_widget_hold_in", 0))))
        tk.Label(bwrow1, text="s", font=(FONT, 10), fg=C_TEXT_MUT, bg=C_BG).pack(side="left")

        bwrow1b = tk.Frame(featf, bg=C_BG);  bwrow1b.pack(fill="x", pady=1, padx=(20, 0))
        tk.Label(bwrow1b, text="Out:", font=(FONT, 10), fg=C_TEXT_MUT, bg=C_BG).pack(side="left")
        self._breath_exhale_spin = tk.Spinbox(bwrow1b, from_=1, to=20, width=4, increment=0.5,
            format="%.1f", font=(MONO, 10), bg=C_CARD_IN, fg=C_TEXT, buttonbackground=C_BTN_SEC,
            relief="flat", justify="center")
        self._breath_exhale_spin.pack(side="left");  self._breath_exhale_spin.delete(0, "end")
        self._breath_exhale_spin.insert(0, str(float(self.config.get("breathing_widget_exhale", 4))))
        tk.Label(bwrow1b, text="s Hold:", font=(FONT, 10), fg=C_TEXT_MUT, bg=C_BG).pack(side="left")
        self._breath_hold_out_spin = tk.Spinbox(bwrow1b, from_=0, to=15, width=4, increment=0.5,
            format="%.1f", font=(MONO, 10), bg=C_CARD_IN, fg=C_TEXT, buttonbackground=C_BTN_SEC,
            relief="flat", justify="center")
        self._breath_hold_out_spin.pack(side="left");  self._breath_hold_out_spin.delete(0, "end")
        self._breath_hold_out_spin.insert(0, str(float(self.config.get("breathing_widget_hold_out", 0))))
        tk.Label(bwrow1b, text="s", font=(FONT, 10), fg=C_TEXT_MUT, bg=C_BG).pack(side="left")

        bwrow2 = tk.Frame(featf, bg=C_BG);  bwrow2.pack(fill="x", pady=1, padx=(20, 0))
        tk.Label(bwrow2, text="Size:", font=(FONT, 10), fg=C_TEXT_MUT, bg=C_BG).pack(side="left")
        self._breath_size_spin = tk.Spinbox(bwrow2, from_=60, to=9999, width=4, increment=10,
            font=(MONO, 10), bg=C_CARD_IN, fg=C_TEXT, buttonbackground=C_BTN_SEC,
            relief="flat", justify="center")
        self._breath_size_spin.pack(side="left");  self._breath_size_spin.delete(0, "end")
        self._breath_size_spin.insert(0, str(self.config.get("breathing_widget_size", 120)))
        tk.Label(bwrow2, text="px  Opacity:", font=(FONT, 10), fg=C_TEXT_MUT, bg=C_BG).pack(side="left")
        self._breath_alpha_spin = tk.Spinbox(bwrow2, from_=5, to=100, width=3, increment=5,
            font=(MONO, 10), bg=C_CARD_IN, fg=C_TEXT, buttonbackground=C_BTN_SEC,
            relief="flat", justify="center")
        self._breath_alpha_spin.pack(side="left");  self._breath_alpha_spin.delete(0, "end")
        self._breath_alpha_spin.insert(0, str(int(self.config.get("breathing_widget_alpha", 0.7) * 100)))
        tk.Label(bwrow2, text="%", font=(FONT, 10), fg=C_TEXT_MUT, bg=C_BG).pack(side="left")

        bwrow3 = tk.Frame(featf, bg=C_BG);  bwrow3.pack(fill="x", pady=1, padx=(20, 0))
        tk.Label(bwrow3, text="Bg:", font=(FONT, 10), fg=C_TEXT_MUT, bg=C_BG).pack(side="left")
        self._breath_bg_var = tk.StringVar(value=self.config.get("breathing_widget_bg", "transparent"))
        for bg_name in ["transparent", "dark", "teal"]:
            tk.Radiobutton(bwrow3, text=bg_name.capitalize(), variable=self._breath_bg_var, value=bg_name,
                          font=(FONT, 9), fg=C_TEXT_DIM, bg=C_BG, selectcolor=C_CARD_IN,
                          activebackground=C_BG, activeforeground=C_TEXT_DIM).pack(side="left", padx=2)

        bwrow4 = tk.Frame(featf, bg=C_BG);  bwrow4.pack(fill="x", pady=1, padx=(20, 0))
        self._breath_ct_var = tk.BooleanVar(value=self.config.get("breathing_widget_click_through", True))
        tk.Checkbutton(bwrow4, text="Click-through (Ctrl+drag to move)", font=(FONT, 10), fg=C_TEXT_DIM,
                       bg=C_BG, variable=self._breath_ct_var, selectcolor=C_CARD_IN,
                       activebackground=C_BG, activeforeground=C_TEXT_DIM).pack(side="left")

        # Theme selection (applies instantly)
        themef = tk.Frame(featf, bg=C_BG);  themef.pack(fill="x", pady=2)
        tk.Label(themef, text="Theme:", font=(FONT, 10), fg=C_TEXT_DIM, bg=C_BG).pack(side="left")
        self._theme_var = tk.StringVar(value=self.config.get("theme", "dark"))

        def apply_theme_now():
            theme = self._theme_var.get()
            apply_theme(theme)
            self.config["theme"] = theme
            save_config(self.config)
            # Reopen window to show new colors
            if self._status_win:
                self._status_win.destroy()
                self._status_win = None
                self.root.after(100, self._show_status_window)

        for theme_name in ["dark", "light", "nord"]:
            tk.Radiobutton(themef, text=theme_name.capitalize(), variable=self._theme_var, value=theme_name,
                          font=(FONT, 9), fg=C_TEXT_DIM, bg=C_BG, selectcolor=C_CARD_IN,
                          activebackground=C_BG, activeforeground=C_TEXT_DIM,
                          command=apply_theme_now).pack(side="left", padx=4)

        # Hydration tracking
        hydf = tk.Frame(featf, bg=C_BG);  hydf.pack(fill="x", pady=2)
        self._hydration_var = tk.BooleanVar(value=self.config.get("hydration_tracking", False))
        tk.Checkbutton(hydf, text="Hydration reminders every", font=(FONT, 10), fg=C_TEXT_DIM,
                       bg=C_BG, variable=self._hydration_var, selectcolor=C_CARD_IN,
                       activebackground=C_BG, activeforeground=C_TEXT_DIM).pack(side="left")
        self._hydration_spin = tk.Spinbox(hydf, from_=15, to=120, width=3,
            font=(MONO, 10), bg=C_CARD_IN, fg=C_TEXT, buttonbackground=C_BTN_SEC,
            relief="flat", justify="center")
        self._hydration_spin.pack(side="left");  self._hydration_spin.delete(0, "end")
        self._hydration_spin.insert(0, str(self.config.get("hydration_reminder_interval", 30)))
        tk.Label(hydf, text=" min, goal:", font=(FONT, 10), fg=C_TEXT_MUT, bg=C_BG).pack(side="left")
        self._hydration_goal_spin = tk.Spinbox(hydf, from_=1, to=20, width=2,
            font=(MONO, 10), bg=C_CARD_IN, fg=C_TEXT, buttonbackground=C_BTN_SEC,
            relief="flat", justify="center")
        self._hydration_goal_spin.pack(side="left");  self._hydration_goal_spin.delete(0, "end")
        self._hydration_goal_spin.insert(0, str(self.config.get("hydration_goal", 8)))
        tk.Label(hydf, text=" glasses", font=(FONT, 10), fg=C_TEXT_MUT, bg=C_BG).pack(side="left")

        # Custom sound
        csf = tk.Frame(featf, bg=C_BG);  csf.pack(fill="x", pady=2)
        self._custom_sound_var = tk.BooleanVar(value=self.config.get("custom_sound_enabled", False))
        tk.Checkbutton(csf, text="Custom sound:", font=(FONT, 10), fg=C_TEXT_DIM,
                       bg=C_BG, variable=self._custom_sound_var, selectcolor=C_CARD_IN,
                       activebackground=C_BG, activeforeground=C_TEXT_DIM).pack(side="left")
        self._sound_path_entry = tk.Entry(csf, width=25, font=(FONT, 9), bg=C_CARD_IN,
                                          fg=C_TEXT, relief="flat")
        self._sound_path_entry.pack(side="left", padx=2)
        self._sound_path_entry.insert(0, self.config.get("custom_sound_path", ""))

        def browse_sound():
            from tkinter import filedialog
            path = filedialog.askopenfilename(filetypes=[("Audio", "*.mp3 *.wav *.ogg *.m4a"), ("All", "*.*")])
            if path:
                self._sound_path_entry.delete(0, "end")
                self._sound_path_entry.insert(0, path)

        tk.Button(csf, text="...", font=(FONT, 9), bg=C_BTN_SEC, fg=C_TEXT_DIM,
                  relief="flat", padx=4, cursor="hand2", command=browse_sound).pack(side="left")

        # Custom messages
        cmf = tk.Frame(featf, bg=C_BG);  cmf.pack(fill="x", pady=2)
        self._custom_msg_var = tk.BooleanVar(value=self.config.get("use_custom_messages", False))
        tk.Checkbutton(cmf, text="Use custom break messages", font=(FONT, 10), fg=C_TEXT_DIM,
                       bg=C_BG, variable=self._custom_msg_var, selectcolor=C_CARD_IN,
                       activebackground=C_BG, activeforeground=C_TEXT_DIM).pack(side="left")
        tk.Button(cmf, text="Edit...", font=(FONT, 9), bg=C_BTN_SEC, fg=C_TEXT_DIM,
                  relief="flat", padx=6, cursor="hand2", command=self._show_message_editor).pack(side="left", padx=4)

        # Guided eye exercises
        eyef = tk.Frame(featf, bg=C_BG);  eyef.pack(fill="x", pady=2)
        self._guided_eye_var = tk.BooleanVar(value=self.config.get("guided_eye_exercises", False))
        tk.Checkbutton(eyef, text="Guided eye exercise routines", font=(FONT, 10), fg=C_TEXT_DIM,
                       bg=C_BG, variable=self._guided_eye_var, selectcolor=C_CARD_IN,
                       activebackground=C_BG, activeforeground=C_TEXT_DIM).pack(side="left")

        # Breathing exercises
        brf = tk.Frame(featf, bg=C_BG);  brf.pack(fill="x", pady=2)
        self._breathing_var = tk.BooleanVar(value=self.config.get("breathing_exercises", False))
        tk.Checkbutton(brf, text="Breathing exercises during breaks", font=(FONT, 10), fg=C_TEXT_DIM,
                       bg=C_BG, variable=self._breathing_var, selectcolor=C_CARD_IN,
                       activebackground=C_BG, activeforeground=C_TEXT_DIM).pack(side="left")

        # Desk exercises
        deskf = tk.Frame(featf, bg=C_BG);  deskf.pack(fill="x", pady=2)
        self._desk_var = tk.BooleanVar(value=self.config.get("desk_exercises", False))
        tk.Checkbutton(deskf, text="Animated desk exercises", font=(FONT, 10), fg=C_TEXT_DIM,
                       bg=C_BG, variable=self._desk_var, selectcolor=C_CARD_IN,
                       activebackground=C_BG, activeforeground=C_TEXT_DIM).pack(side="left")

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

    def _show_message_editor(self) -> None:
        """Show editor for custom break messages."""
        if hasattr(self, '_msg_editor_win') and self._msg_editor_win:
            try:
                self._msg_editor_win.lift()
                self._msg_editor_win.focus_force()
                return
            except tk.TclError:
                self._msg_editor_win = None

        win = tk.Toplevel(self.root)
        win.title("Custom Break Messages")
        win.geometry("450x350")
        win.configure(bg=C_BG)
        win.transient(self._status_win)
        self._msg_editor_win = win

        def on_close():
            self._msg_editor_win = None
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", on_close)

        tk.Label(win, text="Custom Break Messages", font=(FONT, 13, "bold"),
                 fg=C_ACCENT2, bg=C_BG).pack(pady=(14, 8))
        tk.Label(win, text="One message per line. Shown randomly during breaks.",
                 font=(FONT, 9), fg=C_TEXT_DIM, bg=C_BG).pack()

        txt = tk.Text(win, font=(FONT, 10), bg=C_CARD, fg=C_TEXT,
                      relief="flat", padx=10, pady=8, height=12, wrap="word")
        txt.pack(fill="both", expand=True, padx=14, pady=10)

        # Load existing messages
        messages = self.config.get("custom_messages", [])
        txt.insert("1.0", "\n".join(messages))

        def save_messages():
            content = txt.get("1.0", "end").strip()
            self.config["custom_messages"] = [m.strip() for m in content.split("\n") if m.strip()]
            save_config(self.config)
            on_close()

        bf = tk.Frame(win, bg=C_BG)
        bf.pack(pady=(0, 14))
        tk.Button(bf, text="Save", font=(FONT, 10), bg=C_BTN_PRI, fg=C_TEXT,
                  relief="flat", padx=16, pady=5, cursor="hand2", command=save_messages).pack(side="left", padx=4)
        tk.Button(bf, text="Cancel", font=(FONT, 10), bg=C_BTN_SEC, fg=C_TEXT_DIM,
                  relief="flat", padx=12, pady=5, cursor="hand2", command=on_close).pack(side="left")

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
            if gap > eye:
                self._save_fb.set("⚠ Break gap must not exceed eye rest interval");  return

            ws = self._ws_entry.get().strip()
            we = self._we_entry.get().strip()
            for ts in [ws, we]:
                h, m = ts.split(":")
                if not (0 <= int(h) <= 23 and 0 <= int(m) <= 59):
                    raise ValueError("Invalid time")

            breaks = []
            for row in self._brk_rows:
                t = row["time"].get().strip()
                d = int(row["dur"].get())
                n = row["title"].get().strip()
                if not t or not n:
                    continue
                h, m = t.split(":")
                if not (0 <= int(h) <= 23 and 0 <= int(m) <= 59):
                    raise ValueError("Invalid break time")
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

            # Advanced settings
            self.config["focus_mode"] = self._focus_var.get()
            self.config["multi_monitor_overlay"] = self._multimon_var.get()
            self.config["theme"] = self._theme_var.get()
            self.config["hydration_tracking"] = self._hydration_var.get()
            try:
                self.config["hydration_reminder_interval"] = int(self._hydration_spin.get())
                self.config["hydration_goal"] = int(self._hydration_goal_spin.get())
            except ValueError:
                pass
            self.config["custom_sound_enabled"] = self._custom_sound_var.get()
            self.config["custom_sound_path"] = self._sound_path_entry.get().strip()
            self.config["use_custom_messages"] = self._custom_msg_var.get()
            self.config["guided_eye_exercises"] = self._guided_eye_var.get()
            self.config["breathing_exercises"] = self._breathing_var.get()
            self.config["desk_exercises"] = self._desk_var.get()
            try:
                self.config["coast_margin_minutes"] = int(self._coast_spin.get())
            except ValueError:
                pass

            # Widget & taskbar settings
            self.config["show_floating_widget"] = self._widget_var.get()
            self.config["show_in_taskbar"] = self._taskbar_var.get()
            self.config["status_always_on_top"] = self._aot_var.get()
            if self._status_win:
                try:
                    self._status_win.attributes("-topmost", self._aot_var.get())
                except tk.TclError:
                    pass

            # Apply floating widget toggle live
            if self._widget_var.get() and not self._widget_win:
                self._create_floating_widget()
            elif not self._widget_var.get() and self._widget_win:
                self._destroy_floating_widget()

            # Breathing circle widget settings
            self.config["breathing_widget_enabled"] = self._breath_enabled_var.get()
            for key, spin, lo in [
                ("breathing_widget_inhale", self._breath_inhale_spin, 1),
                ("breathing_widget_hold_in", self._breath_hold_in_spin, 0),
                ("breathing_widget_exhale", self._breath_exhale_spin, 1),
                ("breathing_widget_hold_out", self._breath_hold_out_spin, 0),
            ]:
                try:
                    self.config[key] = max(lo, round(float(spin.get()), 1))
                except ValueError:
                    pass
            try:
                self.config["breathing_widget_size"] = max(60, int(self._breath_size_spin.get()))
            except ValueError:
                pass
            try:
                self.config["breathing_widget_alpha"] = max(0.05, min(1.0, int(self._breath_alpha_spin.get()) / 100))
            except ValueError:
                pass
            self.config["breathing_widget_bg"] = self._breath_bg_var.get()
            self.config["breathing_widget_click_through"] = self._breath_ct_var.get()

            # Apply breathing widget toggle live (recreate to pick up size/bg/alpha changes)
            if self._breath_enabled_var.get():
                self._destroy_breathing_widget()
                self._create_breathing_widget()
            elif self._breath_win:
                self._destroy_breathing_widget()

            # Apply theme if changed
            apply_theme(self.config["theme"])

            save_config(self.config)

            self._reset_all_timers()

            self._save_fb.set("✓ Saved — timers reset")
            def _clear_fb():
                try: self._save_fb.set("")
                except tk.TclError: pass
            self._status_win.after(4000, _clear_fb)

        except ValueError:
            self._save_fb.set("⚠ Invalid input — check numbers and time format")

    def _reset_defaults(self) -> None:
        dc = json.loads(json.dumps(DEFAULT_CONFIG))
        self.config.update(dc);  save_config(self.config)

        # Refresh interval widgets
        self._eye_spin.delete(0, "end");  self._eye_spin.insert(0, str(dc["eye_rest_interval"]))
        self._micro_spin.delete(0, "end");  self._micro_spin.insert(0, str(dc["micro_pause_interval"]))
        self._gap_spin.delete(0, "end");  self._gap_spin.insert(0, str(dc["minimum_break_gap"]))
        self._eye_dur_spin.delete(0, "end");  self._eye_dur_spin.insert(0, str(dc["eye_rest_duration"]))
        self._snooze_spin.delete(0, "end");  self._snooze_spin.insert(0, str(dc["snooze_minutes"]))
        self._warn_spin.delete(0, "end");  self._warn_spin.insert(0, str(dc["warning_seconds"]))
        self._ws_entry.delete(0, "end");  self._ws_entry.insert(0, dc["work_start"])
        self._we_entry.delete(0, "end");  self._we_entry.insert(0, dc["work_end"])
        self._coast_spin.delete(0, "end");  self._coast_spin.insert(0, str(dc["coast_margin_minutes"]))

        # Reset feature checkboxes
        self._focus_var.set(dc["focus_mode"])
        self._idle_var.set(dc["idle_detection"])
        self._idle_spin.delete(0, "end");  self._idle_spin.insert(0, str(dc["idle_threshold"]))
        self._sound_var.set(dc["sound_enabled"])
        self._exercises_var.set(dc["show_exercises"])
        self._strict_var.set(dc["strict_mode"])
        self._dim_var.set(dc["screen_dim"])
        self._pomo_var.set(dc["pomodoro_mode"])
        self._mini_var.set(dc["mini_reminders"])
        self._mini_spin.delete(0, "end");  self._mini_spin.insert(0, str(dc["mini_reminder_interval"]))
        self._multimon_var.set(dc["multi_monitor_overlay"])
        self._theme_var.set(dc["theme"])
        self._hydration_var.set(dc["hydration_tracking"])
        self._hydration_spin.delete(0, "end");  self._hydration_spin.insert(0, str(dc["hydration_reminder_interval"]))
        self._hydration_goal_spin.delete(0, "end");  self._hydration_goal_spin.insert(0, str(dc["hydration_goal"]))
        self._custom_sound_var.set(dc["custom_sound_enabled"])
        self._sound_path_entry.delete(0, "end");  self._sound_path_entry.insert(0, dc["custom_sound_path"])
        self._custom_msg_var.set(dc["use_custom_messages"])
        self._guided_eye_var.set(dc["guided_eye_exercises"])
        self._breathing_var.set(dc["breathing_exercises"])
        self._desk_var.set(dc["desk_exercises"])
        self._aot_var.set(dc["status_always_on_top"])

        # Reset breathing widget controls
        self._breath_enabled_var.set(dc["breathing_widget_enabled"])
        for spin, key in [
            (self._breath_inhale_spin, "breathing_widget_inhale"),
            (self._breath_hold_in_spin, "breathing_widget_hold_in"),
            (self._breath_exhale_spin, "breathing_widget_exhale"),
            (self._breath_hold_out_spin, "breathing_widget_hold_out"),
        ]:
            spin.delete(0, "end");  spin.insert(0, str(dc[key]))
        self._breath_size_spin.delete(0, "end");  self._breath_size_spin.insert(0, str(dc["breathing_widget_size"]))
        self._breath_alpha_spin.delete(0, "end");  self._breath_alpha_spin.insert(0, str(int(dc["breathing_widget_alpha"] * 100)))
        self._breath_bg_var.set(dc["breathing_widget_bg"])
        self._breath_ct_var.set(dc["breathing_widget_click_through"])
        self._destroy_breathing_widget()

        # Reset scheduled breaks
        for row in list(self._brk_rows):
            row["frame"].destroy()
        self._brk_rows.clear()
        for brk in dc["breaks"]:
            self._add_brk_row(brk["time"], brk["duration"], brk["title"])

        self._reset_all_timers()
        self._save_fb.set("✓ Reset to defaults")
        def _clear_fb():
            try: self._save_fb.set("")
            except tk.TclError: pass
        self._status_win.after(4000, _clear_fb)

    def _close_status(self) -> None:
        # Clean up global mousewheel binding from settings scroll area
        try:
            self.root.unbind_all("<MouseWheel>")
        except tk.TclError:
            pass
        if self._status_win:
            try:
                self._status_win.destroy()
            except tk.TclError:
                pass
            self._status_win = None

    def _toggle_status_window(self) -> None:
        """Toggle status window - close if open, open if closed."""
        if self._status_win:
            try:
                if self._status_win.winfo_exists():
                    self._close_status()
                    return
            except tk.TclError:
                self._status_win = None
        self._show_status_window()

    def _toggle_pause_ui(self) -> None:
        """Toggle pause and update UI button."""
        self._toggle_pause()
        self._update_pause_btn()

    def _update_pause_btn(self) -> None:
        """Update pause button text based on state."""
        if hasattr(self, '_pause_btn') and self._pause_btn:
            try:
                self._pause_btn.config(text="▶ Resume" if self.paused else "⏸ Pause")
            except tk.TclError:
                pass

    def _toggle_gentle_ui(self) -> None:
        """Toggle gentle mode and update UI button."""
        self._toggle_low_energy()
        self._update_gentle_btn()

    def _update_gentle_btn(self) -> None:
        """Update gentle mode button style based on state."""
        if hasattr(self, '_gentle_btn') and self._gentle_btn:
            try:
                if self.low_energy:
                    # Active - soft teal
                    self._gentle_btn.config(bg=C_GENTLE, fg=C_BG)
                else:
                    # Inactive - muted
                    self._gentle_btn.config(bg=C_BTN_SEC, fg=C_TEXT_DIM)
            except tk.TclError:
                pass

    def _toggle_stats_win(self) -> None:
        """Toggle stats window - close if open, open positioned to side."""
        if self._stats_win:
            try:
                if self._stats_win.winfo_exists():
                    self._stats_win.destroy()
                    self._stats_win = None
                    return
            except tk.TclError:
                self._stats_win = None
        self._show_stats_win()
        self._position_popup(self._stats_win)

    def _toggle_notes_win(self) -> None:
        """Toggle notes window - close if open, open positioned to side."""
        if self._notes_win:
            try:
                if self._notes_win.winfo_exists():
                    self._notes_win.destroy()
                    self._notes_win = None
                    return
            except tk.TclError:
                self._notes_win = None
        self._show_notes_win()
        self._position_popup(self._notes_win)

    def _position_popup(self, popup_win) -> None:
        """Position popup window to the side of status window, away from screen edge."""
        if not popup_win or not self._status_win:
            return
        try:
            self._status_win.update_idletasks()
            popup_win.update_idletasks()
            # Get status window position
            sx = self._status_win.winfo_x()
            sy = self._status_win.winfo_y()
            sw = self._status_win.winfo_width()
            # Get popup size
            pw = popup_win.winfo_width()
            ph = popup_win.winfo_height()
            # Get screen width
            screen_w = self._status_win.winfo_screenwidth()
            # Position to the side furthest from screen edge
            if sx > screen_w / 2:
                # Status is on right side, put popup on left
                px = sx - pw - 10
            else:
                # Status is on left side, put popup on right
                px = sx + sw + 10
            popup_win.geometry(f"+{max(0, px)}+{sy}")
        except tk.TclError:
            pass

    def _update_status(self) -> None:
        if not self._status_win:
            return
        try:
            if not self._status_win.winfo_exists():
                self._status_win = None
                return
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
            outside_hours = t < ws or t >= we
        except ValueError:
            pass

        # ── Eye rest ──
        tv, dv = self._st_rows["eye"]
        if outside_hours:
            tv.set("—")
            dv.set("outside work hours")
        elif self.idle:
            tv.set("IDLE")
            dv.set("timers paused — awaiting activity")
        elif self.config.get("focus_mode", False) and self.fullscreen_active:
            tv.set("PRESENTING")
            dv.set("auto-paused — fullscreen detected")
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
        elif self.idle:
            tv.set("IDLE")
            dv.set("timers paused — awaiting activity")
        elif self.config.get("focus_mode", False) and self.fullscreen_active:
            tv.set("PRESENTING")
            dv.set("auto-paused — fullscreen detected")
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
                except (ValueError, AttributeError): continue
                diff = (bt - now).total_seconds()
                if diff > -60 and (nxt is None or diff < nxt[0]):
                    dl = f" ({brk['duration']}m)" if brk["duration"] > 0 else ""
                    nxt = (diff, f"{self._fmt12(brk['time'])} — {brk['title']}{dl}")
            dv.set(nxt[1] if nxt else "no more scheduled breaks today")
        elif self.warning_up and self.pending_break:
            tv.set(f"00:{self._warn_rem:02d}")
            dv.set("⏳ break imminent")
        else:
            nxt = None
            for brk in self.config.get("breaks", []):
                key = brk["time"]
                if self.acked_today.get(key) == now.date(): continue
                try:
                    bt = datetime.datetime.combine(now.date(), self._pt(brk["time"]))
                except (ValueError, AttributeError): continue
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

        # Update control buttons
        self._update_pause_btn()
        self._update_gentle_btn()

        try:
            self._status_win.after(1000, self._update_status)
        except tk.TclError:
            self._status_win = None

    # ━━━ Startup ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _show_startup(self):
        ov = tk.Toplevel(self.root)
        ov.overrideredirect(True);  ov.attributes("-topmost", True)
        ov.configure(bg=C_CARD);  self._centre(ov, 400, 150)
        if IS_MAC: ov.lift()

        tk.Label(ov, text="Screen Break is running", font=(FONT, 14, "bold"),
                 fg=C_ACCENT2, bg=C_CARD).pack(pady=(20, 6))

        tk.Label(ov, text="Breaks appear automatically. A clock icon\nwill show in the corner before each one.",
                 font=(FONT, 9), fg=C_TEXT_DIM, bg=C_CARD,
                 justify="center").pack(pady=(0, 8))

        tray = "menu bar" if IS_MAC else "system tray"
        tk.Label(ov, text=f"{tray} > right-click for settings",
                 font=(FONT, 9), fg=C_TEXT_MUT, bg=C_CARD).pack(pady=(0, 14))

        # Click anywhere to dismiss
        def dismiss(e=None):
            try:
                ov.destroy()
            except tk.TclError:
                pass
        ov.bind("<Button-1>", dismiss)
        for child in ov.winfo_children():
            child.bind("<Button-1>", dismiss)
        # Also auto-close after a few seconds
        ov.after(STARTUP_DISMISS_MS, dismiss)

        # If no tray, bind Ctrl+Q globally as a quit shortcut
        if not HAS_TRAY:
            self.root.bind_all("<Control-q>", lambda e: self._quit())
            self.root.bind_all("<Control-Q>", lambda e: self._quit())

    def _print_schedule(self):
        try:
            print()
            print("  +-----------------------------------------------+")
            print("  |          Screen Break -- Schedule              |")
            print("  +-----------------------------------------------+")
            for brk in self.config.get("breaks", []):
                d = f"({brk['duration']} min)" if brk['duration'] > 0 else ""
                t12 = self._fmt12(brk['time'])
                print(f"  |  {t12:<8s}  {brk['title']:<22s} {d:>8s} |")
            print("  +-----------------------------------------------+")
            ei, mi = int(self.eye_iv), int(self.micro_iv)
            mg = self.config.get("minimum_break_gap", 20)
            print(f"  |  Every {ei:>2d} min   20-20-20 eye rest            |")
            print(f"  |  Every {mi:>2d} min   Micro-pause (5 min)          |")
            print(f"  |  Minimum {mg} min between any breaks           |")
            tz = datetime.datetime.now().astimezone().tzinfo
            print(f"  |  Timezone: {str(tz):<34s} |")
            print("  +-----------------------------------------------+")
            if not HAS_TRAY:
                print("\n  [!] No tray icon (pystray not available).")
                print("      pip install pystray pillow")
            print()
        except (UnicodeEncodeError, OSError):
            pass  # silently skip on consoles that can't print

    # ━━━ Taskbar Presence ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _on_taskbar_click(self, event=None) -> None:
        """Handle taskbar button click: open status window, re-minimize root."""
        # Ignore events from child windows
        if event and event.widget is not self.root:
            return
        self.root.after(10, self.root.iconify)
        self.root.after(50, self._show_status_window)

    # ━━━ Floating Widget ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _create_floating_widget(self) -> None:
        """Create a small always-on-top countdown widget."""
        if self._widget_win:
            return
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        try:
            win.attributes("-alpha", 0.88)
        except tk.TclError:
            pass
        win.configure(bg=C_ACCENT)

        # Position: saved or default bottom-right
        pos = self.config.get("widget_position")
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        w, h = 150, 32
        if pos and isinstance(pos, list) and len(pos) == 2:
            x, y = int(pos[0]), int(pos[1])
            # Clamp to screen bounds
            x = max(0, min(x, sw - w))
            y = max(0, min(y, sh - h))
        else:
            x, y = sw - w - 20, sh - h - 60
        win.geometry(f"{w}x{h}+{x}+{y}")

        lbl = tk.Label(win, text="Screen Break", font=(FONT, 9, "bold"),
                       fg="#ffffff", bg=C_ACCENT, cursor="hand2", padx=8)
        lbl.pack(fill="both", expand=True)

        self._widget_win = win
        self._widget_label = lbl

        # Dragging + click
        for widget in (win, lbl):
            widget.bind("<Button-1>", self._widget_press)
            widget.bind("<B1-Motion>", self._widget_drag)
            widget.bind("<ButtonRelease-1>", self._widget_release)
            widget.bind("<Button-3>", self._widget_menu)

        self._update_floating_widget()

    def _widget_press(self, event) -> None:
        """Record mouse position for drag."""
        self._widget_drag_x = event.x_root - self._widget_win.winfo_x()
        self._widget_drag_y = event.y_root - self._widget_win.winfo_y()
        self._widget_dragged = False

    def _widget_drag(self, event) -> None:
        """Move widget with mouse."""
        x = event.x_root - self._widget_drag_x
        y = event.y_root - self._widget_drag_y
        self._widget_win.geometry(f"+{x}+{y}")
        self._widget_dragged = True

    def _widget_release(self, event) -> None:
        """On release: save position if dragged, else open status window."""
        if self._widget_dragged:
            # Save position
            x = self._widget_win.winfo_x()
            y = self._widget_win.winfo_y()
            self.config["widget_position"] = [x, y]
            save_config(self.config)
        else:
            self._toggle_status_window()

    def _widget_menu(self, event) -> None:
        """Show right-click context menu on widget."""
        menu = tk.Menu(self._widget_win, tearoff=0)
        pause_text = "Resume" if self.paused else "Pause"
        menu.add_command(label=pause_text, command=lambda: self.root.after(0, self._toggle_pause_from_widget))
        menu.add_command(label="Settings", command=lambda: self.root.after(0, self._show_status_window))
        menu.add_separator()
        menu.add_command(label="Quit", command=lambda: self.root.after(0, self._quit))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _toggle_pause_from_widget(self) -> None:
        """Toggle pause and update widget + tray."""
        self._toggle_pause()
        self._update_tray_icon()
        if hasattr(self, '_pause_btn') and self._pause_btn:
            self._update_pause_btn()

    def _update_floating_widget(self) -> None:
        """Refresh the widget countdown every second."""
        if not self._widget_win:
            return
        try:
            if not self._widget_win.winfo_exists():
                self._widget_win = None
                return
        except tk.TclError:
            self._widget_win = None
            return

        now = datetime.datetime.now()
        calc_time = self.pause_started if self.paused and self.pause_started else now

        # Check work hours
        t = now.time()
        outside_hours = False
        try:
            ws = self._pt(self.config.get("work_start", "08:00"))
            we = self._pt(self.config.get("work_end", "20:00"))
            outside_hours = t < ws or t >= we
        except ValueError:
            pass

        # Determine text
        if outside_hours:
            text = "Off hours"
        elif self.idle:
            text = "IDLE"
        elif self.config.get("focus_mode", False) and self.fullscreen_active:
            text = "Presenting"
        elif self.paused:
            text = "PAUSED"
        else:
            # Find the soonest countdown
            best_label = "Eye"
            el = (calc_time - self.last_eye_rest).total_seconds()
            best_rem = max(0, self.eye_iv * 60 - el)

            el = (calc_time - self.last_micro).total_seconds()
            micro_rem = max(0, self.micro_iv * 60 - el)
            if micro_rem < best_rem:
                best_rem = micro_rem
                best_label = "Micro"

            # Check scheduled breaks
            for brk in self.config.get("breaks", []):
                key = brk["time"]
                if self.acked_today.get(key) == now.date():
                    continue
                try:
                    bt = datetime.datetime.combine(now.date(), self._pt(brk["time"]))
                except (ValueError, AttributeError):
                    continue
                diff = (bt - now).total_seconds()
                if diff > 0 and diff < best_rem:
                    best_rem = diff
                    best_label = "Break"

            m, s = divmod(int(best_rem), 60)
            h, m2 = divmod(m, 60)
            if h > 0:
                text = f"{best_label} {h}h {m2:02d}m"
            else:
                text = f"{best_label} {m:02d}:{s:02d}"

        try:
            self._widget_label.config(text=text)
        except tk.TclError:
            pass

        try:
            self._widget_win.after(1000, self._update_floating_widget)
        except tk.TclError:
            self._widget_win = None

    def _destroy_floating_widget(self) -> None:
        """Tear down the floating widget."""
        if self._widget_win:
            try:
                self._widget_win.destroy()
            except tk.TclError:
                pass
            self._widget_win = None
            self._widget_label = None

    # ━━━ Breathing Circle Widget ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    _BREATH_CHROMA = (1, 1, 1)  # RGB tuple used as transparent key

    # Original teal palette — 6 bands from dark outer glow to bright core
    _BREATH_TEAL = [
        (13, 61, 61),    # outermost  #0d3d3d
        (10, 92, 82),    #            #0a5c52
        (15, 118, 110),  #            #0f766e
        (16, 153, 142),  #            #10998e
        (20, 184, 166),  #            #14b8a6
        (45, 212, 191),  # core       #2dd4bf
    ]
    _BREATH_RING_STEP = 0.18  # radius multiplier increment per ring

    def _create_breathing_widget(self) -> None:
        """Create an always-on-top breathing circle widget."""
        if self._breath_win:
            return

        size = self.config.get("breathing_widget_size", 120)
        bg_mode = self.config.get("breathing_widget_bg", "transparent")
        alpha = self.config.get("breathing_widget_alpha", 0.7)
        win_w = size + 20
        win_h = size + 20

        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)

        # Decide rendering path: per-pixel alpha (Windows transparent) or canvas
        self._breath_use_layered = False
        if bg_mode == "transparent" and IS_WIN:
            # Per-pixel alpha via UpdateLayeredWindow — no -transparentcolor needed
            win.configure(bg="black")
            self._breath_use_layered = True
            self._breath_bg_rgb = (0, 0, 0)  # unused for layered rendering
        elif bg_mode == "transparent":
            # Non-Windows fallback: chroma key (has aliased edges)
            chroma_hex = "#%02x%02x%02x" % self._BREATH_CHROMA
            win.configure(bg=chroma_hex)
            try:
                win.attributes("-transparentcolor", chroma_hex)
                win.attributes("-alpha", max(0.05, min(1.0, alpha)))
            except tk.TclError:
                win.configure(bg="#111827")
                bg_mode = "dark"
            self._breath_bg_rgb = self._BREATH_CHROMA
        if bg_mode == "teal":
            win.configure(bg="#0d3d3d")
            self._breath_bg_rgb = (13, 61, 61)
            try:
                win.attributes("-alpha", max(0.05, min(1.0, alpha)))
            except tk.TclError:
                pass
        elif bg_mode == "dark":
            win.configure(bg="#111827")
            self._breath_bg_rgb = (17, 24, 39)
            try:
                win.attributes("-alpha", max(0.05, min(1.0, alpha)))
            except tk.TclError:
                pass

        # Position
        pos = self.config.get("breathing_widget_position")
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        if pos and isinstance(pos, list) and len(pos) == 2:
            x, y = int(pos[0]), int(pos[1])
            x = max(0, min(x, sw - win_w))
            y = max(0, min(y, sh - win_h))
        else:
            x, y = sw - win_w - 20, sh - win_h - 100
        win.geometry(f"{win_w}x{win_h}+{x}+{y}")

        # Canvas (used for rendering in non-layered mode, events in all modes)
        canvas_bg = "black" if self._breath_use_layered else win.cget("bg")
        canvas = tk.Canvas(win, width=win_w, height=win_h,
                           bg=canvas_bg, highlightthickness=0)
        canvas.pack(fill="both", expand=True)

        self._breath_win = win
        self._breath_canvas = canvas
        self._breath_photo = None
        self._breath_img_id = canvas.create_image(win_w // 2, win_h // 2, anchor="center")
        self._breath_win_w = win_w
        self._breath_win_h = win_h

        for widget in (win, canvas):
            widget.bind("<Button-1>", self._breath_press)
            widget.bind("<B1-Motion>", self._breath_drag)
            widget.bind("<ButtonRelease-1>", self._breath_release)
            widget.bind("<Button-3>", self._breath_menu)

        # HWND setup (Windows)
        self._breath_hwnd = None
        self._breath_ct_active = False
        if IS_WIN:
            try:
                win.update_idletasks()
                GA_ROOT = 2
                self._breath_hwnd = ctypes.windll.user32.GetAncestor(
                    win.winfo_id(), GA_ROOT)
            except Exception:
                self._breath_hwnd = None

        # For layered mode, set WS_EX_LAYERED on the HWND
        if self._breath_use_layered and self._breath_hwnd:
            try:
                GWL_EXSTYLE = -20
                WS_EX_LAYERED = 0x00080000
                style = ctypes.windll.user32.GetWindowLongW(self._breath_hwnd, GWL_EXSTYLE)
                style |= WS_EX_LAYERED
                ctypes.windll.user32.SetWindowLongW(self._breath_hwnd, GWL_EXSTYLE, style)
            except Exception:
                self._breath_use_layered = False

        # Click-through
        if self._breath_hwnd and self.config.get("breathing_widget_click_through", True):
            self._breath_set_click_through(True)

        self._breath_running = True
        self._animate_breathing_widget()
        self._breath_poll_ctrl()

    def _breath_set_click_through(self, enable: bool) -> None:
        """Toggle WS_EX_TRANSPARENT on the breathing widget (Windows)."""
        if not self._breath_hwnd:
            return
        try:
            GWL_EXSTYLE = -20
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_LAYERED = 0x00080000
            style = ctypes.windll.user32.GetWindowLongW(self._breath_hwnd, GWL_EXSTYLE)
            if enable:
                style |= WS_EX_TRANSPARENT | WS_EX_LAYERED
            else:
                style &= ~WS_EX_TRANSPARENT
            ctypes.windll.user32.SetWindowLongW(self._breath_hwnd, GWL_EXSTYLE, style)
            self._breath_ct_active = enable
        except Exception:
            pass

    def _breath_poll_ctrl(self) -> None:
        """Poll Ctrl key independently of animation (runs even when paused)."""
        if not self._breath_win or not self._breath_hwnd:
            return
        try:
            if not self._breath_win.winfo_exists():
                return
        except tk.TclError:
            return
        if self.config.get("breathing_widget_click_through", True):
            try:
                VK_CONTROL = 0x11
                ctrl_held = (ctypes.windll.user32.GetAsyncKeyState(VK_CONTROL) & 0x8000) != 0
                if ctrl_held and self._breath_ct_active:
                    self._breath_set_click_through(False)
                elif not ctrl_held and not self._breath_ct_active and not self._breath_dragged:
                    self._breath_set_click_through(True)
            except Exception:
                pass
        try:
            self._breath_win.after(50, self._breath_poll_ctrl)
        except tk.TclError:
            pass

    def _breath_draw_rings(self, img_w: int, img_h: int, core_r: float,
                           bg: tuple[int, ...]) -> Image.Image:
        """Draw the 6 teal rings at a given resolution on the specified background."""
        img = Image.new("RGB", (img_w, img_h), bg)
        draw = ImageDraw.Draw(img)
        cx, cy = img_w // 2, img_h // 2
        n = len(self._BREATH_TEAL)
        step = self._BREATH_RING_STEP
        for i, rgb in enumerate(self._BREATH_TEAL):
            factor = 1.0 + (n - 1 - i) * step
            r = core_r * factor
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=rgb)
        return img

    def _breath_init_gdi(self, w: int, h: int) -> bool:
        """Create and cache GDI resources for layered window rendering."""
        self._breath_free_gdi()
        try:
            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32

            class BMI(ctypes.Structure):
                _fields_ = [
                    ("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                    ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                    ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                    ("biSizeImage", ctypes.c_uint32), ("biXPM", ctypes.c_int32),
                    ("biYPM", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                    ("biClrImportant", ctypes.c_uint32),
                ]
            bmi = BMI(40, w, -h, 1, 32, 0, 0, 0, 0, 0, 0)

            hdc_screen = user32.GetDC(0)
            hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
            ppv = ctypes.c_void_p()
            hbmp = gdi32.CreateDIBSection(hdc_mem, ctypes.byref(bmi), 0,
                                          ctypes.byref(ppv), None, 0)
            if not hbmp or not ppv:
                gdi32.DeleteDC(hdc_mem)
                user32.ReleaseDC(0, hdc_screen)
                return False

            self._breath_hdc_screen = hdc_screen
            self._breath_hdc_mem = hdc_mem
            self._breath_hbmp = hbmp
            self._breath_ppv = ppv
            self._breath_old_bmp = gdi32.SelectObject(hdc_mem, hbmp)
            return True
        except Exception:
            return False

    def _breath_free_gdi(self) -> None:
        """Release cached GDI resources."""
        try:
            gdi32 = ctypes.windll.gdi32
            user32 = ctypes.windll.user32
            if self._breath_old_bmp and self._breath_hdc_mem:
                gdi32.SelectObject(self._breath_hdc_mem, self._breath_old_bmp)
            if self._breath_hbmp:
                gdi32.DeleteObject(self._breath_hbmp)
            if self._breath_hdc_mem:
                gdi32.DeleteDC(self._breath_hdc_mem)
            if self._breath_hdc_screen:
                user32.ReleaseDC(0, self._breath_hdc_screen)
        except Exception:
            pass
        self._breath_hdc_screen = None
        self._breath_hdc_mem = None
        self._breath_hbmp = None
        self._breath_ppv = None
        self._breath_old_bmp = None

    def _breath_update_layered_window(self, bgra_bytes: bytes, w: int, h: int) -> None:
        """Send BGRA pixels to the window via UpdateLayeredWindow (cached GDI)."""
        if not self._breath_hwnd:
            return
        if not self._breath_ppv:
            if not self._breath_init_gdi(w, h):
                return
        try:
            ctypes.memmove(self._breath_ppv, bgra_bytes, len(bgra_bytes))

            alpha_byte = max(1, min(255, int(
                self.config.get("breathing_widget_alpha", 0.7) * 255)))
            blend = (ctypes.c_ubyte * 4)(0, 0, alpha_byte, 1)
            sz = (ctypes.c_long * 2)(w, h)
            pt_src = (ctypes.c_long * 2)(0, 0)

            ctypes.windll.user32.UpdateLayeredWindow(
                self._breath_hwnd, self._breath_hdc_screen, None, sz,
                self._breath_hdc_mem, pt_src, 0, blend, 2)
        except Exception:
            pass

    def _animate_breathing_widget(self) -> None:
        """60fps animation — 6-ring teal circle, per-pixel alpha or canvas rendering."""
        if not self._breath_running or not self._breath_win:
            return
        try:
            if not self._breath_win.winfo_exists():
                self._breath_win = None
                return
        except tk.TclError:
            self._breath_win = None
            return

        # --- Compute breath factor (0=contracted, 1=expanded) ---
        inhale_t = max(1.0, float(self.config.get("breathing_widget_inhale", 4)))
        hold_in_t = max(0.0, float(self.config.get("breathing_widget_hold_in", 0)))
        exhale_t = max(1.0, float(self.config.get("breathing_widget_exhale", 4)))
        hold_out_t = max(0.0, float(self.config.get("breathing_widget_hold_out", 0)))
        total_cycle = inhale_t + hold_in_t + exhale_t + hold_out_t

        t = time.time() % total_cycle
        if t < inhale_t:
            progress = t / inhale_t
            breath = 0.5 - 0.5 * math.cos(math.pi * progress)
        elif t < inhale_t + hold_in_t:
            breath = 1.0
        elif t < inhale_t + hold_in_t + exhale_t:
            progress = (t - inhale_t - hold_in_t) / exhale_t
            breath = 0.5 + 0.5 * math.cos(math.pi * progress)
        else:
            breath = 0.0

        # --- Common geometry ---
        win_w = self._breath_win_w
        win_h = self._breath_win_h
        n = len(self._BREATH_TEAL)
        step = self._BREATH_RING_STEP
        outermost_factor = 1.0 + (n - 1) * step

        if self._breath_use_layered:
            # --- Per-pixel alpha path (1x RGBA — no separate alpha mask) ---
            half = min(win_w, win_h) / 2
            max_r = (half - 4) / outermost_factor
            min_r = max_r * 0.33
            core_r = min_r + (max_r - min_r) * breath

            # Draw rings directly on transparent RGBA
            rgba = Image.new("RGBA", (win_w, win_h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(rgba)
            cx, cy = win_w // 2, win_h // 2
            for i, rgb in enumerate(self._BREATH_TEAL):
                factor = 1.0 + (n - 1 - i) * step
                r = core_r * factor
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=rgb + (255,))

            # All pixels are either (R,G,B,255) or (0,0,0,0) so premultiply
            # is identity — just swap R<->B for BGRA byte order
            r_ch, g_ch, b_ch, a_ch = rgba.split()
            bgra = Image.merge("RGBA", (b_ch, g_ch, r_ch, a_ch))
            self._breath_update_layered_window(bgra.tobytes(), win_w, win_h)
        else:
            # --- Canvas path (2x supersample for dark/teal backgrounds) ---
            scale = 2
            img_w, img_h = win_w * scale, win_h * scale
            half = min(img_w, img_h) / 2
            max_r = (half - 8 * scale) / outermost_factor
            min_r = max_r * 0.33
            core_r = min_r + (max_r - min_r) * breath
            rgb_img = self._breath_draw_rings(img_w, img_h, core_r, self._breath_bg_rgb)
            rgb_img = rgb_img.filter(ImageFilter.GaussianBlur(radius=1.0))
            rgb_img = rgb_img.resize((win_w, win_h), Image.LANCZOS)
            try:
                self._breath_photo = ImageTk.PhotoImage(rgb_img)
                self._breath_canvas.itemconfig(self._breath_img_id, image=self._breath_photo)
            except tk.TclError:
                return

        # Schedule next frame (~60fps)
        try:
            self._breath_win.after(16, self._animate_breathing_widget)
        except tk.TclError:
            self._breath_running = False

    def _breath_press(self, event) -> None:
        """Record mouse position for drag."""
        self._breath_drag_x = event.x_root - self._breath_win.winfo_x()
        self._breath_drag_y = event.y_root - self._breath_win.winfo_y()
        self._breath_dragged = False

    def _breath_drag(self, event) -> None:
        """Move breathing widget with mouse."""
        x = event.x_root - self._breath_drag_x
        y = event.y_root - self._breath_drag_y
        self._breath_win.geometry(f"+{x}+{y}")
        self._breath_dragged = True

    def _breath_release(self, event) -> None:
        """Save position if dragged, then re-enable click-through."""
        if self._breath_dragged:
            x = self._breath_win.winfo_x()
            y = self._breath_win.winfo_y()
            self.config["breathing_widget_position"] = [x, y]
            save_config(self.config)
            self._breath_dragged = False
            # Re-enable click-through after drag completes
            if self._breath_hwnd and self.config.get("breathing_widget_click_through", True):
                self._breath_set_click_through(True)

    def _breath_menu(self, event) -> None:
        """Right-click context menu on breathing widget."""
        menu = tk.Menu(self._breath_win, tearoff=0)
        if self._breath_running:
            menu.add_command(label="Pause", command=self._breath_toggle_pause)
        else:
            menu.add_command(label="Resume", command=self._breath_toggle_pause)
        menu.add_command(label="Settings",
                         command=lambda: self.root.after(0, self._show_status_window))
        menu.add_separator()
        menu.add_command(label="Close",
                         command=lambda: self.root.after(0, self._destroy_breathing_widget))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _breath_toggle_pause(self) -> None:
        """Toggle breathing animation pause/resume."""
        if self._breath_running:
            self._breath_running = False
        else:
            self._breath_running = True
            self._animate_breathing_widget()

    def _destroy_breathing_widget(self) -> None:
        """Tear down the breathing circle widget."""
        self._breath_running = False
        self._breath_free_gdi()
        if self._breath_hwnd:
            self._breath_set_click_through(False)
            self._breath_hwnd = None
        self._breath_ct_active = False
        if self._breath_win:
            try:
                self._breath_win.destroy()
            except tk.TclError:
                pass
            self._breath_win = None
            self._breath_canvas = None
            self._breath_photo = None

    # ━━━ System Tray ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _create_tray_icon(self, paused: bool = False) -> Image.Image:
        """Create Windows 3.1 style stopwatch tray icon."""
        size = 64
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        if paused:
            TEAL = (100, 110, 110, 255)
            DARK_TEAL = (70, 80, 80, 255)
            LIGHT_CYAN = (140, 150, 150, 255)
        else:
            TEAL = (0, 128, 128, 255)
            DARK_TEAL = (0, 80, 80, 255)
            LIGHT_CYAN = (128, 192, 192, 255)
        BLACK = (0, 0, 0, 255)
        WHITE = (255, 255, 255, 255)
        GRAY = (128, 128, 128, 255)

        cx, cy = 32, 36
        r_outer = 23
        r_inner = r_outer - 5

        # Crown button
        draw.rectangle([cx-4+1, 14+1, cx+4+1, 20+1], fill=(64,64,64,255))
        draw.rectangle([cx-4, 14, cx+4, 20], fill=TEAL, outline=BLACK)
        draw.line([(cx-3, 15), (cx+3, 15)], fill=LIGHT_CYAN)
        draw.line([(cx-3, 15), (cx-3, 19)], fill=LIGHT_CYAN)

        # Outer ring + teal rim
        draw.ellipse([cx-r_outer, cy-r_outer, cx+r_outer, cy+r_outer], fill=BLACK)
        draw.ellipse([cx-r_outer+1, cy-r_outer+1, cx+r_outer-1, cy+r_outer-1], fill=TEAL)

        # Rim bevel
        for a_deg in range(200, 345):
            a = math.radians(a_deg)
            bx = int(cx + (r_outer-2) * math.cos(a))
            by = int(cy + (r_outer-2) * math.sin(a))
            draw.point((bx, by), fill=LIGHT_CYAN)
        for a_deg in range(20, 165):
            a = math.radians(a_deg)
            bx = int(cx + (r_outer-2) * math.cos(a))
            by = int(cy + (r_outer-2) * math.sin(a))
            draw.point((bx, by), fill=DARK_TEAL)

        # Inner face
        draw.ellipse([cx-r_inner-1, cy-r_inner-1, cx+r_inner+1, cy+r_inner+1], fill=BLACK)
        draw.ellipse([cx-r_inner, cy-r_inner, cx+r_inner, cy+r_inner], fill=WHITE)

        # Crosshatch on face
        r_sq = (r_inner - 1) ** 2
        for offset in range(-2*r_inner, 2*r_inner+1, 4):
            pts = []
            for x in range(cx-r_inner+1, cx+r_inner):
                y = x + offset
                if (x-cx)**2 + (y-cy)**2 <= r_sq:
                    pts.append((x, y))
            if len(pts) >= 2:
                draw.line([pts[0], pts[-1]], fill=TEAL)
            pts = []
            for x in range(cx-r_inner+1, cx+r_inner):
                y = -x + offset + 2*cy
                if (x-cx)**2 + (y-cy)**2 <= r_sq:
                    pts.append((x, y))
            if len(pts) >= 2:
                draw.line([pts[0], pts[-1]], fill=TEAL)

        # Tick marks
        for h in [0, 90, 180, 270]:
            a = math.radians(h - 90)
            ti, to = r_inner - 7, r_inner - 2
            draw.line([(int(cx+ti*math.cos(a)), int(cy+ti*math.sin(a))),
                       (int(cx+to*math.cos(a)), int(cy+to*math.sin(a)))], fill=BLACK, width=2)

        # Clock hand
        ha = math.radians(-60)
        hl = r_inner - 8
        hx, hy = int(cx + hl * math.cos(ha)), int(cy + hl * math.sin(ha))
        draw.line([(cx+1, cy+1), (hx+1, hy+1)], fill=GRAY, width=2)
        draw.line([(cx, cy), (hx, hy)], fill=BLACK, width=2)

        # Center hub
        draw.ellipse([cx-3, cy-3, cx+3, cy+3], fill=TEAL, outline=BLACK)

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
            # Hidden default item for left-click
            pystray.MenuItem("Open", lambda icon, item: self.root.after(0, self._toggle_status_window),
                           default=True, visible=False),
            pystray.MenuItem("Screen Break",
                lambda icon, item: self.root.after(0, self._show_status_window)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda item: "▶  Resume" if self.paused else "⏸  Pause",
                lambda icon, item: self.root.after(0, self._toggle_pause)),
            pystray.MenuItem(
                lambda item: "✓  Gentle mode" if self.low_energy else "🪫  Gentle mode",
                lambda icon, item: self.root.after(0, self._toggle_low_energy)),
            pystray.MenuItem("📊  Statistics",
                lambda icon, item: self.root.after(0, self._show_stats_win)),
            pystray.MenuItem("📝  Notes",
                lambda icon, item: self.root.after(0, self._show_notes_win)),
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
        save_stats(self.stats)
        if HAS_TRAY and hasattr(self, "tray"):
            self.tray.stop()
        self.root.after(0, self.root.quit)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if __name__ == "__main__":
    ScreenBreakApp()
