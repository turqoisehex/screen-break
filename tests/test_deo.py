"""Unit tests for Deo mode's pure decision engine (deo_decide).

Runs headless — no Tk, no display, no file I/O. deo_decide is a pure function
of (now, cfg, usage), so these tests exercise it directly without touching
ScreenBreakApp or any GUI code.
"""
import datetime
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from screen_break import deo_decide, DeoState, DeoReason, DEFAULT_CONFIG, DEFAULT_STATS


def base_cfg(**overrides):
    cfg = {
        "deo_allowed_start": "09:00",
        "deo_allowed_end": "18:00",
        "deo_daily_limit_minutes": 120,
        "deo_warn_ramp_minutes": 10,
    }
    cfg.update(overrides)
    return cfg


def base_usage(**overrides):
    usage = {"used_seconds": 0, "bonus_seconds": 0}
    usage.update(overrides)
    return usage


def dt(h, m, s=0):
    return datetime.datetime(2026, 7, 24, h, m, s)


def test_before_window_locks():
    d = deo_decide(dt(8, 0), base_cfg(), base_usage())
    assert d.state == DeoState.LOCK
    assert d.reason == DeoReason.BEFORE_WINDOW
    assert d.ramp_intensity == 1.0


def test_at_window_start_is_allowed():
    d = deo_decide(dt(9, 0), base_cfg(), base_usage())
    assert d.state == DeoState.ALLOWED


def test_one_minute_before_window_start_locks():
    d = deo_decide(dt(8, 59), base_cfg(), base_usage())
    assert d.state == DeoState.LOCK
    assert d.reason == DeoReason.BEFORE_WINDOW


def test_after_window_end_locks():
    d = deo_decide(dt(18, 1), base_cfg(), base_usage())
    assert d.state == DeoState.LOCK
    assert d.reason == DeoReason.AFTER_WINDOW


def test_exactly_at_window_end_locks():
    # "off by 6pm" — the boundary itself is locked, not allowed.
    d = deo_decide(dt(18, 0), base_cfg(), base_usage())
    assert d.state == DeoState.LOCK
    assert d.reason == DeoReason.AFTER_WINDOW


def test_mid_window_under_budget_allowed():
    d = deo_decide(dt(12, 0), base_cfg(), base_usage(used_seconds=60 * 60))
    assert d.state == DeoState.ALLOWED
    assert d.ramp_intensity == 0.0


def test_budget_exhausted_locks_even_inside_window():
    d = deo_decide(dt(12, 0), base_cfg(), base_usage(used_seconds=120 * 60))
    assert d.state == DeoState.LOCK
    assert d.reason == DeoReason.BUDGET_EXHAUSTED


def test_budget_exceeded_locks():
    d = deo_decide(dt(12, 0), base_cfg(), base_usage(used_seconds=200 * 60))
    assert d.state == DeoState.LOCK
    assert d.reason == DeoReason.BUDGET_EXHAUSTED


def test_bonus_seconds_extend_budget():
    # Exactly at the unmodified limit, but with bonus minutes granted via unlock.
    d = deo_decide(dt(12, 0), base_cfg(), base_usage(used_seconds=120 * 60, bonus_seconds=600))
    assert d.state != DeoState.LOCK


def test_ramp_starts_at_configured_threshold():
    # 121 min limit, 111 min used -> exactly 10 min (600s) remaining -> ramp boundary.
    cfg = base_cfg(deo_daily_limit_minutes=121, deo_warn_ramp_minutes=10)
    d = deo_decide(dt(12, 0), cfg, base_usage(used_seconds=111 * 60))
    assert d.state == DeoState.WARN
    assert 0.0 <= d.ramp_intensity <= 0.05  # just entering the ramp -> near-zero intensity


def test_ramp_intensity_increases_toward_lockout():
    cfg = base_cfg(deo_daily_limit_minutes=130, deo_warn_ramp_minutes=10)
    early = deo_decide(dt(12, 0), cfg, base_usage(used_seconds=119 * 60))   # 11 min left -> ALLOWED
    mid = deo_decide(dt(12, 0), cfg, base_usage(used_seconds=125 * 60))    # 5 min left -> WARN
    late = deo_decide(dt(12, 0), cfg, base_usage(used_seconds=129 * 60 + 50))  # 10s left -> WARN, high intensity
    assert early.state == DeoState.ALLOWED
    assert mid.state == DeoState.WARN
    assert late.state == DeoState.WARN
    assert mid.ramp_intensity < late.ramp_intensity
    assert late.ramp_intensity > 0.9


def test_ramp_intensity_is_monotonic_non_decreasing_as_time_passes():
    cfg = base_cfg(deo_daily_limit_minutes=130, deo_warn_ramp_minutes=10)
    intensities = []
    for used_min in range(120, 130):
        d = deo_decide(dt(12, 0), cfg, base_usage(used_seconds=used_min * 60))
        if d.state == DeoState.WARN:
            intensities.append(d.ramp_intensity)
    assert intensities == sorted(intensities)


def test_ramp_clamped_to_window_end_not_just_budget():
    # Huge budget, but window closes in 3 minutes -> ramp driven by window end.
    cfg = base_cfg(deo_daily_limit_minutes=600, deo_warn_ramp_minutes=10)
    d = deo_decide(dt(17, 57), cfg, base_usage(used_seconds=0))
    assert d.state == DeoState.WARN
    assert d.remaining_seconds <= 180


def test_malformed_time_strings_fall_back_to_defaults():
    cfg = base_cfg(deo_allowed_start="garbage", deo_allowed_end="also garbage")
    d = deo_decide(dt(12, 0), cfg, base_usage())
    assert d.state == DeoState.ALLOWED  # falls back to 09:00-18:00 defaults, noon is inside


def test_negative_or_invalid_limit_falls_back_to_default():
    d = deo_decide(dt(12, 0), base_cfg(deo_daily_limit_minutes=-5), base_usage(used_seconds=0))
    assert d.state == DeoState.ALLOWED  # falls back to 120 min default, not immediately locked


def test_negative_used_seconds_clamped():
    d = deo_decide(dt(12, 0), base_cfg(), base_usage(used_seconds=-500))
    assert d.state == DeoState.ALLOWED


def test_override_until_unlocks_even_before_window():
    # Parent's hidden-gesture unlock must work regardless of *why* it locked.
    cfg = base_cfg()
    override = dt(9, 0) + datetime.timedelta(minutes=10)
    d = deo_decide(dt(8, 0), cfg, base_usage(override_until=override.isoformat()))
    assert d.state != DeoState.LOCK


def test_override_until_unlocks_after_budget_exhausted():
    cfg = base_cfg()
    override = dt(12, 0) + datetime.timedelta(minutes=10)
    d = deo_decide(dt(12, 0), cfg, base_usage(used_seconds=999999, override_until=override.isoformat()))
    assert d.state != DeoState.LOCK


def test_override_until_expires_and_reverts_to_normal_rules():
    cfg = base_cfg()
    override = dt(12, 0) - datetime.timedelta(minutes=1)  # already in the past
    d = deo_decide(dt(12, 0), cfg, base_usage(used_seconds=999999, override_until=override.isoformat()))
    assert d.state == DeoState.LOCK
    assert d.reason == DeoReason.BUDGET_EXHAUSTED


def test_override_until_ramps_down_near_its_own_expiry():
    cfg = base_cfg(deo_warn_ramp_minutes=10)
    override = dt(12, 0) + datetime.timedelta(minutes=5)
    d = deo_decide(dt(12, 0), cfg, base_usage(override_until=override.isoformat()))
    assert d.state == DeoState.WARN


def test_malformed_override_until_falls_back_to_normal_rules():
    d = deo_decide(dt(12, 0), base_cfg(), base_usage(override_until="not-a-date"))
    assert d.state == DeoState.ALLOWED


def test_default_config_and_stats_are_internally_consistent():
    # Sanity check that the schema added to DEFAULT_CONFIG/DEFAULT_STATS actually
    # round-trips through deo_decide without raising.
    d = deo_decide(dt(12, 0), DEFAULT_CONFIG, DEFAULT_STATS["deo"])
    assert d.state in (DeoState.ALLOWED, DeoState.WARN, DeoState.LOCK)
