#!/usr/bin/env python3
"""Soul Daemon — Decision layer. No LLM. Pure rules."""
import json
import os
import datetime
import sys

try:
    import zoneinfo
    TZ = zoneinfo.ZoneInfo(os.environ.get("SOUL_TIMEZONE", "Europe/Moscow"))
except ImportError:
    from datetime import timezone, timedelta
    TZ = timezone(timedelta(hours=3))

WORKSPACE = os.environ.get("SOUL_WORKSPACE", "/home/user/.openclaw/workspace")
SOUL_DIR = f"{WORKSPACE}/soul"

THRESHOLDS = {
    "open_thread_urgent": 1,
    "app_new_registration": 1,
    "channel_subscriber_delta": 5,
    "close_person_silent_hours": 72,  # 3 days
}

WEATHER_WARNINGS = ["storm", "thunder", "blizzard", "ice", "freezing", "fog"]


def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def already_sent_today(sent_log, key):
    today = datetime.date.today().isoformat()
    entries = sent_log.get(today, {}).get("sent", [])
    return any(e.get("key") == key for e in entries)


def decide():
    now_tz = datetime.datetime.now(tz=TZ)
    hour = now_tz.hour

    signals = load_json(f"{SOUL_DIR}/signals_latest.json")
    sent_log = load_json(f"{SOUL_DIR}/sent_log.json")

    active_signals = []

    # Silence window: 00:00-08:00
    night_silence = 0 <= hour < 8

    # Work silence: 10:00-16:00 (only blocks non-urgent)
    work_silence = 10 <= hour < 16

    # 1. Urgent threads — bypass work silence, not night silence
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

    # 2. App registrations — respect all silences
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

    # 3. Weather warnings
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

    # 4. Close persons silent (placeholder - hours_ago fields)
    for person, field, label in [
        ("contact_a", "contact_a_last_message_hours_ago", "Contact A"),
        ("contact_b", "contact_b_last_message_hours_ago", "Contact B"),
    ]:
        hours_ago = signals.get(field)
        if hours_ago and hours_ago >= THRESHOLDS["close_person_silent_hours"]:
            key = f"{person}_silent"
            if not night_silence and not work_silence and not already_sent_today(sent_log, key):
                active_signals.append({
                    "key": key,
                    "type": "close_person",
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
