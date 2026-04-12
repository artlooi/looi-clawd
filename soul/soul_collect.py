#!/usr/bin/env python3
"""
soul_collect.py — Signal collection layer for the Soul Daemon.

Gathers external signals (weather, app registrations, urgent threads) from
multiple sources and persists them as JSON snapshots. Runs hourly via cron.
No LLM calls — pure HTTP fetches and file I/O.

Architecture:
    1. Read local state files (ved/state.json) for urgent task threads.
    2. Fetch weather data from wttr.in for configured cities.
    3. Query PocketBase API for recent app registrations.
    4. Persist signals to signals_latest.json (current), signals_prev.json
       (previous run), and signals_log.jsonl (append-only history).

Data flow:
    [external APIs] → collect() → signals_latest.json → soul_decide.py

Configuration:
    All paths and endpoints are configurable via environment variables.
    See SOUL_WORKSPACE, SOUL_CITY_A, SOUL_CITY_B, SOUL_POCKETBASE_URL.
"""

import json
import requests
import datetime
import os
import shutil

# --- Configuration ---
# Override these via environment variables or edit directly
WORKSPACE = os.environ.get(
    "SOUL_WORKSPACE", os.path.expanduser("~/.openclaw/workspace")
)
SOUL_DIR = f"{WORKSPACE}/soul"
VED_STATE_PATH = f"{WORKSPACE}/ved/state.json"
SIGNALS_LATEST_PATH = f"{SOUL_DIR}/signals_latest.json"
SIGNALS_PREV_PATH = f"{SOUL_DIR}/signals_prev.json"
SIGNALS_LOG_PATH = f"{SOUL_DIR}/signals_log.jsonl"
SENT_LOG_PATH = f"{SOUL_DIR}/sent_log.json"

# Cities for weather monitoring — configure as needed
# Format: {"key_name": "city_query_for_wttr.in"}
WEATHER_CITIES = {
    "city_a": os.environ.get("SOUL_CITY_A", "CityA"),
    "city_b": os.environ.get("SOUL_CITY_B", "CityB"),
}

# PocketBase API endpoint — replace with your own
POCKETBASE_URL = os.environ.get(
    "SOUL_POCKETBASE_URL",
    "http://YOUR_SERVER_IP:8090/api/collections/app_content/records?perPage=5&sort=-created",
)

# ---------------------------------------------------------------------------
# Directory and state initialization
# ---------------------------------------------------------------------------


def ensure_dirs():
    """Create workspace directories if they don't exist."""
    os.makedirs(SOUL_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(VED_STATE_PATH), exist_ok=True)


def create_dummy_ved_state():
    """Create a sample ved/state.json if none exists, for first-run testing."""
    if not os.path.exists(VED_STATE_PATH):
        dummy_data = {
            "open_threads": [
                {"title": "Urgent task 1", "urgency": "action_needed"},
                {"title": "Urgent task 2", "urgency": "action_needed"},
                {"title": "Non-urgent task", "urgency": "info"},
            ]
        }
        with open(VED_STATE_PATH, "w") as f:
            json.dump(dummy_data, f, ensure_ascii=False, indent=2)
        print(f"Created dummy {VED_STATE_PATH}")


# ---------------------------------------------------------------------------
# Main collection logic
# ---------------------------------------------------------------------------


def collect():
    """
    Collect all external signals into a single JSON snapshot.

    Steps:
        1. Read urgent threads from ved/state.json
        2. Fetch weather for each configured city
        3. Query PocketBase for 24h registration count
        4. Rotate signals_latest → signals_prev for delta detection
        5. Write new signals_latest.json
        6. Append to signals_log.jsonl (audit trail)

    All errors are caught per-source so one failing API doesn't block others.
    """
    ensure_dirs()
    create_dummy_ved_state()

    signals = {}
    current_time_utc = datetime.datetime.now(datetime.timezone.utc)
    signals["timestamp"] = current_time_utc.isoformat()

    # --- Source 1: Local task state ---
    # ved/state.json tracks open threads; we extract only "action_needed" urgency
    try:
        with open(VED_STATE_PATH, "r") as f:
            ved = json.load(f)
        urgent = [
            t
            for t in ved.get("open_threads", [])
            if t.get("urgency") == "action_needed"
        ]
        signals["open_threads_urgent"] = len(urgent)
        signals["open_threads_urgent_titles"] = [t.get("title") for t in urgent]
    except Exception as e:
        print(f"Error reading {VED_STATE_PATH}: {e}")
        signals["open_threads_urgent"] = 0
        signals["open_threads_urgent_titles"] = []

    # --- Source 2: Weather data ---
    # Fetch current conditions from wttr.in for each monitored city
    for key_name, city_query in WEATHER_CITIES.items():
        try:
            r = requests.get(f"https://wttr.in/{city_query}?format=j1", timeout=5)
            if r.ok:
                w = r.json()["current_condition"][0]
                signals[f"weather_{key_name}"] = {
                    "temp": w["temp_C"],
                    "desc": w["weatherDesc"][0]["value"],
                }
            else:
                print(f"Error fetching weather for {city_query}: {r.status_code}")
        except Exception as e:
            print(f"Error fetching weather for {city_query}: {e}")
            signals[f"weather_{key_name}"] = {"temp": "N/A", "desc": "Error"}

    # --- Source 3: App registration count from PocketBase ---
    # Count records created in the last 24 hours
    try:
        r = requests.get(POCKETBASE_URL, timeout=5)
        if r.ok:
            records = r.json().get("items", [])
            last_24h_registrations = 0
            time_24h_ago = current_time_utc - datetime.timedelta(hours=24)
            for record in records:
                created_at_str = record.get("created")
                if created_at_str:
                    created_at = datetime.datetime.fromisoformat(
                        created_at_str.replace("Z", "+00:00")
                    )
                    if created_at > time_24h_ago:
                        last_24h_registrations += 1
            signals["app_registrations_24h"] = last_24h_registrations
        else:
            print(f"Error fetching PocketBase data: {r.status_code}")
            signals["app_registrations_24h"] = 0
    except Exception as e:
        print(f"Error fetching PocketBase data: {e}")
        signals["app_registrations_24h"] = 0

    # --- Bookkeeping: ensure sent_log.json exists for soul_decide.py ---
    if not os.path.exists(SENT_LOG_PATH):
        with open(SENT_LOG_PATH, "w") as f:
            json.dump({}, f)

    # --- Rotate: archive previous snapshot before overwriting ---
    # This enables delta detection in soul_decide.py
    if os.path.exists(SIGNALS_LATEST_PATH):
        try:
            shutil.copy(SIGNALS_LATEST_PATH, SIGNALS_PREV_PATH)
        except Exception as e:
            print(f"Error copying {SIGNALS_LATEST_PATH} to {SIGNALS_PREV_PATH}: {e}")

    # --- Persist current snapshot ---
    try:
        with open(SIGNALS_LATEST_PATH, "w") as f:
            json.dump(signals, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error writing {SIGNALS_LATEST_PATH}: {e}")

    # --- Append to audit log (one JSON object per line) ---
    try:
        with open(SIGNALS_LOG_PATH, "a") as f:
            json.dump(signals, f, ensure_ascii=False)
            f.write("\n")
    except Exception as e:
        print(f"Error writing to {SIGNALS_LOG_PATH}: {e}")

    # --- Human-readable summary to stdout ---
    print(f"Soul Daemon collected signals at {signals['timestamp']}:")
    print(f"  Urgent threads: {signals['open_threads_urgent']}")
    for key_name, city_query in WEATHER_CITIES.items():
        print(
            f"  {city_query} weather: {signals.get(f'weather_{key_name}', {}).get('temp', 'N/A')}C, {signals.get(f'weather_{key_name}', {}).get('desc', 'N/A')}"
        )
    print(f"  New app registrations (24h): {signals['app_registrations_24h']}")


if __name__ == "__main__":
    collect()
