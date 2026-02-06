# Screen Break Enhancement Plan

## Features from Commercial Apps to Add

### Phase 1: Core Improvements (High Value)

1. **Idle Detection** ✓
   - Pause break timers when user is away from computer
   - Resume when activity detected
   - Configurable idle threshold (default: 5 minutes)
   - Show "idle detected" in status

2. **Statistics & Tracking** ✓
   - Track breaks taken vs skipped
   - Daily/weekly break streaks
   - Total breaks today
   - Persistent stats file

3. **Exercise/Stretch Suggestions** ✓
   - Rotating suggestions during micro-pauses
   - Eye exercises during eye rest
   - Stretches categorized by body part
   - User can add custom suggestions

4. **Sound Notifications** ✓
   - Gentle chime when break starts
   - Optional sound for warning
   - Configurable: on/off, volume
   - Use system sounds (cross-platform)

5. **Strict Mode** ✓
   - Prevent skipping/dismissing breaks
   - Only "snooze" option, no "dismiss"
   - Configurable per-break-type

### Phase 2: Polish (Medium Value)

6. **Multiple Snooze Options**
   - Quick buttons: 2 min, 5 min, 10 min
   - Or postpone until next natural break

7. **Keyboard Shortcuts**
   - Skip break: Ctrl+Shift+S
   - Pause/Resume: Ctrl+Shift+P
   - Show status: Ctrl+Shift+B

8. **Break Completion Tracking**
   - Mark breaks as completed vs skipped
   - Show in statistics

9. **Fullscreen Break Option**
   - Option to make all breaks fullscreen
   - Blocks screen more aggressively

### Phase 3: Advanced (Lower Priority)

10. **Pomodoro Mode**
    - Alternative to scheduled breaks
    - 25 min work / 5 min break cycle
    - Long break every 4 cycles

11. **Do Not Disturb Detection**
    - Respect system DND mode
    - Platform-specific implementation

12. **Calendar Integration**
    - Pause during meetings
    - Complex, maybe future version

---

## Implementation Details

### Idle Detection
```python
# Track last input time using ctypes on Windows
# Compare to threshold, pause timers if idle
# Resume and credit idle time when activity returns
```

### Statistics Storage
```json
{
  "lifetime": {
    "eye_rest_taken": 1234,
    "eye_rest_skipped": 56,
    "micro_taken": 789,
    "micro_skipped": 12,
    "scheduled_taken": 345,
    "scheduled_skipped": 6
  },
  "today": {
    "date": "2024-01-15",
    "eye_rest_taken": 8,
    "micro_taken": 3,
    "scheduled_taken": 2,
    "streak_days": 5
  }
}
```

### Exercise Suggestions
- Eye: "Blink rapidly 20 times", "Look up, down, left, right", "Focus near then far"
- Neck: "Tilt head left, hold 10s", "Chin tucks", "Neck rolls"
- Shoulders: "Shoulder shrugs", "Arm circles", "Doorway stretch"
- Wrists: "Wrist circles", "Prayer stretch", "Finger spreads"
- Back: "Cat-cow stretch", "Seated twist", "Stand and reach up"
- Legs: "Calf raises", "Leg swings", "Quad stretch"

### Sound System
- Use winsound on Windows
- Use AppKit on macOS
- Use subprocess + paplay on Linux
- Fallback: system bell
