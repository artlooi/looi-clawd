#!/usr/bin/env python3
"""Soul Daemon — Decision layer. No LLM. Pure rules."""
import json
import os
import datetime
import sys

try:
    import zoneinfo
    MSK = zoneinfo.ZoneInfo("Europe/Moscow")
except ImportError:
    from datetime import timezone, timedelta
    MSK = timezone(timedelta(hours=3))

WORKSPACE = "/home/looi/.openclaw/workspace"
SOUL_DIR = f"{WORKSPACE}/soul"

THRESHOLDS = {
    "open_thread_urgent": 1,
    "radar_new_registration": 1,
    "cronbun_subscriber_delta": 5,
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
    now_msk = datetime.datetime.now(tz=MSK)
    hour = now_msk.hour

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
                "label": f"{urgent_count} задач требуют действия"
            })

    # 2. Radar registrations — respect all silences
    radar_regs = signals.get("radar_registrations_24h", 0)
    if radar_regs >= THRESHOLDS["radar_new_registration"]:
        key = "radar_registration"
        if not night_silence and not work_silence and not already_sent_today(sent_log, key):
            active_signals.append({
                "key": key,
                "type": "radar",
                "value": radar_regs,
                "label": f"{radar_regs} новых регистраций на radar.looi.ru за 24ч"
            })

    # 3. Weather warnings
    for city in ["moscow", "volzhsky"]:
        w = signals.get(f"weather_{city}", {})
        desc = w.get("desc", "").lower()
        if any(warn in desc for warn in WEATHER_WARNINGS):
            key = f"weather_{city}_warning"
            if not night_silence and not work_silence and not already_sent_today(sent_log, key):
                active_signals.append({
                    "key": key,
                    "type": "weather",
                    "value": desc,
                    "label": f"Опасная погода в {'Москве' if city == 'moscow' else 'Волжском'}: {w.get('desc')}, {w.get('temp')}C"
                })

    # 4. Close persons silent (placeholder - hours_ago fields)
    for person, field, label in [
        ("lera", "lera_last_message_hours_ago", "Лера"),
        ("son", "son_last_message_hours_ago", "сын"),
    ]:
        hours_ago = signals.get(field)
        if hours_ago and hours_ago >= THRESHOLDS["close_person_silent_hours"]:
            key = f"{person}_silent"
            if not night_silence and not work_silence and not already_sent_today(sent_log, key):
                active_signals.append({
                    "key": key,
                    "type": "close_person",
                    "value": hours_ago,
                    "label": f"{label} не писал(а) {hours_ago}ч"
                })

    if not active_signals:
        reasons = []
        if night_silence:
            reasons.append("ночная тишина 00-08")
        elif work_silence:
            reasons.append("рабочий блок 10-16")
        else:
            reasons.append("нет сигналов выше порога")
        result = {"should_send": False, "reason": ", ".join(reasons)}
    else:
        result = {
            "should_send": True,
            "signals": active_signals,
            "reason": f"{len(active_signals)} активных сигналов"
        }

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    decide()
