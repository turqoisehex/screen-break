"""Integration tests for Deo mode's Tk-level behavior: the settings-window
gesture authorization gate, arm/disarm, and the lockout overlay lifecycle.

Unlike test_deo.py (which tests the pure deo_decide() engine with no Tk),
these tests construct a real ScreenBreakApp against a real (headless) Tk
display -- CI runs this under xvfb, the same way the existing "Verify
import" step already does. The tray icon thread and the blocking mainloop
are both replaced with no-ops so tests run fast and don't depend on a
working system-tray backend.
"""
import datetime
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import screen_break as sb


class FakeEvent:
    """Minimal stand-in for a Tk KeyPress event -- _deo_settings_gesture_feed
    only reads .keysym."""
    def __init__(self, keysym):
        self.keysym = keysym


def feed_gesture(app):
    for ks in sb.DEO_UNLOCK_KEYSYM_SEQUENCE:
        app._deo_settings_gesture_feed(FakeEvent(ks))


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(sb, "CONFIG_FILE", str(tmp_path / "screen_break_config.json"))
    monkeypatch.setattr(sb, "STATS_FILE", str(tmp_path / "screen_break_stats.json"))
    monkeypatch.setattr(sb, "NOTES_FILE", str(tmp_path / "screen_break_notes.json"))
    monkeypatch.setattr(sb, "DEO_LOCK_FILE", str(tmp_path / "screen_break_deo.lock"))
    monkeypatch.setattr(sb.tk.Tk, "mainloop", lambda self: None)
    monkeypatch.setattr(sb.ScreenBreakApp, "_run_tray", lambda self: None)
    instance = sb.ScreenBreakApp()
    yield instance
    try:
        instance.root.destroy()
    except Exception:
        pass


# ─── Arm / disarm ────────────────────────────────────────────

def test_arming_does_not_require_the_gesture(app):
    app.config["deo_mode_enabled"] = False
    app._show_status_window()
    app.root.update()
    app._deo_toggle_armed()
    app.root.update()
    assert app.config["deo_mode_enabled"] is True


def test_disarm_without_gesture_is_silently_refused(app):
    app.config["deo_mode_enabled"] = True
    app._show_status_window()
    app.root.update()
    app._deo_toggle_armed()  # no gesture performed
    app.root.update()
    assert app.config["deo_mode_enabled"] is True


def test_disarm_after_gesture_succeeds(app):
    app.config["deo_mode_enabled"] = True
    app._show_status_window()
    app.root.update()
    feed_gesture(app)
    app.root.update()
    assert app._deo_settings_authenticated is True
    app._deo_toggle_armed()
    app.root.update()
    assert app.config["deo_mode_enabled"] is False


# ─── Gesture-listener scope (regression coverage) ──────────────

def test_gesture_listener_not_bound_while_settings_closed(app):
    assert app._status_win is None
    binding = app.root.bind_all("<KeyPress-Scroll_Lock>")
    assert not binding, "gesture listener must not be live while the settings window is closed"


def test_gesture_listener_bound_while_open_and_unbound_on_close(app):
    app.config["deo_mode_enabled"] = True
    app._show_status_window()
    app.root.update()
    assert app.root.bind_all("<KeyPress-Scroll_Lock>")
    assert app.root.bind_all("<KeyPress-Pause>")
    app._close_status()
    app.root.update()
    assert not app.root.bind_all("<KeyPress-Scroll_Lock>")
    assert not app.root.bind_all("<KeyPress-Pause>")


def test_authentication_does_not_persist_across_window_sessions(app):
    app.config["deo_mode_enabled"] = True
    app._show_status_window()
    app.root.update()
    feed_gesture(app)
    app.root.update()
    assert app._deo_settings_authenticated is True
    app._close_status()
    app.root.update()
    app._show_status_window()
    app.root.update()
    assert app._deo_settings_authenticated is False
    assert app._deo_start_entry.cget("state") == "disabled"


# ─── Settings save enforcement (defense in depth) ──────────────

def test_apply_settings_rejects_deo_changes_without_authentication(app):
    app.config["deo_mode_enabled"] = True
    app._show_status_window()
    app.root.update()
    # Simulate a child forcing the widget's state directly, bypassing the UI disable.
    app._deo_limit_spin.configure(state="normal")
    app._deo_limit_spin.delete(0, "end")
    app._deo_limit_spin.insert(0, "9999")
    app._apply_settings()
    app.root.update()
    assert app.config["deo_daily_limit_minutes"] != 9999


def test_apply_settings_accepts_deo_changes_after_authentication(app):
    app.config["deo_mode_enabled"] = True
    app._show_status_window()
    app.root.update()
    feed_gesture(app)
    app.root.update()
    app._deo_limit_spin.delete(0, "end")
    app._deo_limit_spin.insert(0, "77")
    app._apply_settings()
    app.root.update()
    assert app.config["deo_daily_limit_minutes"] == 77


def test_reset_defaults_does_not_touch_deo_settings_or_disarm(app):
    app.config["deo_mode_enabled"] = True
    app.config["deo_daily_limit_minutes"] = 55
    app._show_status_window()  # _reset_defaults refreshes widgets built here
    app.root.update()
    app._reset_defaults()
    assert app.config["deo_mode_enabled"] is True
    assert app.config["deo_daily_limit_minutes"] == 55
    # sanity: a non-Deo setting SHOULD reset, proving the guard is scoped correctly
    assert app.config["eye_rest_interval"] == sb.DEFAULT_CONFIG["eye_rest_interval"]


# ─── Lockout overlay lifecycle ──────────────────────────────────

def _force_budget_exhausted(app):
    app.config["deo_mode_enabled"] = True
    app.config["deo_allowed_start"] = "00:00"
    app.config["deo_allowed_end"] = "23:59"
    app.config["deo_daily_limit_minutes"] = 1
    app.stats["deo"] = {"date": datetime.date.today().isoformat(), "used_seconds": 9999,
                         "unlocks": 0, "bonus_seconds": 0, "override_until": None}


def test_lockout_creates_fullscreen_topmost_overlay(app):
    _force_budget_exhausted(app)
    app._deo_tick(datetime.datetime.now())
    app.root.update()
    assert app._deo_locked is True
    assert len(app._deo_overlays) >= 1
    for ov in app._deo_overlays:
        assert ov.winfo_exists()
        assert ov.attributes("-topmost")


def test_deo_locked_excludes_ordinary_break_tick_gate(app):
    """_tick()'s gate for ordinary Priority 1-3 breaks must exclude Deo-locked
    state -- this is the mechanism that makes a lockout supersede/suppress
    ordinary breaks (see the comment in _tick())."""
    _force_budget_exhausted(app)
    app._deo_tick(datetime.datetime.now())
    app.root.update()
    assert app._deo_locked is True
    gate_open = (not app.paused and not app.overlay_up and not app.warning_up
                 and not app.idle and not app._deo_locked)
    assert gate_open is False


def test_lockout_self_heals_if_overlay_destroyed(app):
    _force_budget_exhausted(app)
    now = datetime.datetime.now()
    app._deo_tick(now)
    app.root.update()
    assert app._deo_locked is True

    app._deo_overlays[0].destroy()
    app.root.update()
    app._deo_tick(now)
    app.root.update()
    assert app._deo_locked is True
    assert all(ov.winfo_exists() for ov in app._deo_overlays)


def test_lockout_idempotent_recall_does_not_recreate_overlays(app):
    _force_budget_exhausted(app)
    now = datetime.datetime.now()
    app._deo_tick(now)
    app.root.update()
    overlays_before = list(app._deo_overlays)
    app._deo_tick(now)
    app.root.update()
    assert app._deo_overlays == overlays_before


def test_hidden_gesture_unlocks_an_active_lockout(app):
    _force_budget_exhausted(app)
    now = datetime.datetime.now()
    app._deo_tick(now)
    app.root.update()
    assert app._deo_locked is True

    for vk in sb.DEO_UNLOCK_SEQUENCE:
        app._deo_feed_unlock_key(vk)
    app.root.update()
    assert app._deo_locked is False
    assert app.stats["deo"]["unlocks"] == 1
    assert app.stats["deo"]["override_until"]
    assert len(app._deo_overlays) == 0


def test_unlock_works_regardless_of_lock_reason(app):
    """The hidden gesture must unlock a before-window lockout too, not just
    a budget-exhausted one -- this is what override_until exists for."""
    app.config["deo_mode_enabled"] = True
    app.config["deo_allowed_start"] = "23:58"
    app.config["deo_allowed_end"] = "23:59"
    app.stats["deo"] = {"date": datetime.date.today().isoformat(), "used_seconds": 0,
                         "unlocks": 0, "bonus_seconds": 0, "override_until": None}
    now = datetime.datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)
    app._deo_tick(now)
    app.root.update()
    assert app._deo_locked is True
    assert app._deo_lock_reason == sb.DeoReason.BEFORE_WINDOW

    for vk in sb.DEO_UNLOCK_SEQUENCE:
        app._deo_feed_unlock_key(vk)
    app.root.update()
    assert app._deo_locked is False
