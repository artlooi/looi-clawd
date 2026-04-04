#!/usr/bin/env python3
"""
soul_decide.py — Decision layer for the Soul Daemon.

Pure rule-based signal filtering — no LLM calls. Reads the latest collected
signals from signals_latest.json and determines which (if any) deserve a
user notification.

Architecture:
    - Threshold-based: each signal type has a minimum value to trigger.
    - Time-gated: night silence (00-08) blocks everything; work silence
      (10-16) blocks non-urgent signals only.
    - Dedup: sent_log.json tracks what was already sent today to avoid
      duplicate notifications within the same calendar day.

Data flow:
    signals_latest.json -> decide() -> JSON verdict (stdout) -> soul_notify.py

Output format (stdout JSON):
    {"should_send": true, "signals": [...], "reason": "..."}
    {"should_send": false, "reason": "night silence 00-08"}
"""
import json
import os
import datetime
import sys

# Timezone handling: prefer zoneinfo (Python 3.9+), fall back to fixed UTC+3
try:
    import zoneinfo
    TZ = zoneinfo.ZoneInfo(os.environ.get("SOUL_TIMEZONE", "YOUR_TIMEZONE"))
except ImportError:
    from datetime import timezone, timedelta
    TZ = timezone(timedelta(hours=3))

WORKSPACE = os.environ.get("SOUL_WORKSPACE", "/home/user/.openclaw/workspace")
SOUL_DIR = f"{WORKSPACE}/soul"

# ---------------------------------------------------------------------------
# Thresholds and configuration
# ---------------------------------------------------------------------------

# Minimum values for each signal type to trigger a notification
THRESHOLDS = {
    "open_thread_urgent": 1,
    "app_new_registration": 1,
    "channel_subscriber_delta": 5,
    "monitored_contact_silent_hours": 72,  # 3 days
}

# Weather descriptions containing these keywords trigger a warning
WEATHER_WARNINGS = ["storm", "thunder", "blizzard", "ice", "freezing", "fog"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_json(path):
    """Load a JSON file, returning empty dict if missing."""
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def already_sent_today(sent_log, key):
    """Check if a signal key was already sent in today's sent_log entry."""
    today = datetime.date.today().isoformat()
    entries = sent_log.get(today, {}).get("sent", [])
    return any(e.get("key") == key for e in entries)


# ---------------------------------------------------------------------------
# Main decision logic
# ---------------------------------------------------------------------------

def decide():
    """
    Evaluate collected signals against thresholds and time-of-day rules.

    Returns:
        dict with 'should_send' (bool), 'signals' (list), and 'reason' (str).
        Also prints the result as JSON to stdout for piping to soul_notify.py.
    """
    now_tz = datetime.datetime.now(tz=TZ)
    hour = now_tz.hour

    signals = load_json(f"{SOUL_DIR}/signals_latest.json")
    sent_log = load_json(f"{SOUL_DIR}/sent_log.json")

    active_signals = []

    # Night silence: suppress ALL notifications between midnight and 8 AM
    night_silence = 0 <= hour < 8

    # Work silence: suppress non-urgent notifications during focused work hours
    work_silence = 10 <= hour < 16

    # --- Rule 1: Urgent threads ---
    # These bypass work silence (important enough to interrupt) but not night
    urgent_count = signals.get("open_threads_urgent", 0)
    if urgent_count >= THRESHOLDS["open_thread_urgent"]:
        key = "urgent_threads"
        if not night_silence and not already_sent_today(sent_log, key):
            titles = signals.get("open_threads_urgent_titles", [])
            active_signals.append({
                "key": key,
                "type": "urgent_thread",
                "value": urgent_count,
                "detail": titles[:3],
                "label": f"{urgent_count} tasks require action"
            })

    # --- Rule 2: App registrations ---
    # Non-urgent: respects both night and work silence windows
    app_regs = signals.get("app_registrations_24h", 0)
    if app_regs >= THRESHOLDS["app_new_registration"]:
        key = "app_registration"
        if not night_silence and not work_silence and not already_sent_today(sent_log, key):
            active_signals.append({
                "key": key,
                "type": "app",
                "value": app_regs,
                "label": f"{app_regs} new registrations on your-app.example.com in 24h"
            })

    # --- Rule 3: Weather warnings ---
    # Check each city's weather description for dangerous conditions
    for city in ["city_a", "city_b"]:
        w = signals.get(f"weather_{city}", {})
        desc = w.get("desc", "").lower()
        if any(warn in desc for warn in WEATHER_WARNINGS):
            key = f"weather_{city}_warning"
            if not night_silence and not work_silence and not already_sent_today(sent_log, key):
                active_signals.append({
                    "key": key,
                    "type": "weather",
                    "value": desc,
                    "label": f"Dangerous weather in {city}: {w.get('desc')}, {w.get('temp')}C"
                })

    # --- Rule 4: Monitored contacts silence detection ---
    # Alert if a tracked contact hasn't messaged beyond the threshold
    for person, field, label in [
        ("contact_a", "contact_a_last_message_hours_ago", "Contact A"),
        ("contact_b", "contact_b_last_message_hours_ago", "Contact B"),
    ]:
        hours_ago = signals.get(field)
        if hours_ago and hours_ago >= THRESHOLDS["monitored_contact_silent_hours"]:
            key = f"{person}_silent"
            if not night_silence and not work_silence and not already_sent_today(sent_log, key):
                active_signals.append({
                    "key": key,
                    "type": "monitored_contact",
                    "value": hours_ago,
                    "label": f"{label} hasn't written in {hours_ago}h"
                })

    if not active_signals:
        reasons = []
        if night_silence:
            reasons.append("night silence 00-08")
        elif work_silence:
            reasons.append("work block 10-16")
        else:
            reasons.append("no signals above threshold")
        result = {"should_send": False, "reason": ", ".join(reasons)}
    else:
        result = {
            "should_send": True,
            "signals": active_signals,
            "reason": f"{len(active_signals)} active signals"
        }

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    decide()
