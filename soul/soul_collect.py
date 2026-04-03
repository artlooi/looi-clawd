
import json
import requests
import datetime
import os
import shutil

WORKSPACE = "/home/looi/.openclaw/workspace"
SOUL_DIR = f"{WORKSPACE}/soul"
VED_STATE_PATH = f"{WORKSPACE}/ved/state.json"
SIGNALS_LATEST_PATH = f"{SOUL_DIR}/signals_latest.json"
SIGNALS_PREV_PATH = f"{SOUL_DIR}/signals_prev.json"
SIGNALS_LOG_PATH = f"{SOUL_DIR}/signals_log.jsonl"
SENT_LOG_PATH = f"{SOUL_DIR}/sent_log.json"

def ensure_dirs():
    os.makedirs(SOUL_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(VED_STATE_PATH), exist_ok=True)

def create_dummy_ved_state():
    if not os.path.exists(VED_STATE_PATH):
        dummy_data = {
            "open_threads": [
                {"title": "Urgent task 1", "urgency": "action_needed"},
                {"title": "Urgent task 2", "urgency": "action_needed"},
                {"title": "Non-urgent task", "urgency": "info"}
            ]
        }
        with open(VED_STATE_PATH, "w") as f:
            json.dump(dummy_data, f, ensure_ascii=False, indent=2)
        print(f"Created dummy {VED_STATE_PATH}")

def collect():
    ensure_dirs()
    create_dummy_ved_state()

    signals = {}
    current_time_utc = datetime.datetime.now(datetime.timezone.utc)
    signals["timestamp"] = current_time_utc.isoformat()

    # 1. ved/state.json
    try:
        with open(VED_STATE_PATH, "r") as f:
            ved = json.load(f)
        urgent = [t for t in ved.get("open_threads", []) if t.get("urgency") == "action_needed"]
        signals["open_threads_urgent"] = len(urgent)
        signals["open_threads_urgent_titles"] = [t.get("title") for t in urgent]
    except Exception as e:
        print(f"Error reading {VED_STATE_PATH}: {e}")
        signals["open_threads_urgent"] = 0
        signals["open_threads_urgent_titles"] = []

    # 2. Погода
    for city_en, city_ru, name_key in [("Moscow", "Москва", "moscow"), ("Volzhsky", "Волжский", "volzhsky")]:
        try:
            r = requests.get(f"https://wttr.in/{city_en}?format=j1", timeout=5)
            if r.ok:
                w = r.json()["current_condition"][0]
                signals[f"weather_{name_key}"] = {
                    "temp": w["temp_C"],
                    "desc": w["weatherDesc"][0]["value"]
                }
            else:
                print(f"Error fetching weather for {city_ru}: {r.status_code}")
        except Exception as e:
            print(f"Error fetching weather for {city_ru}: {e}")
            signals[f"weather_{name_key}"] = {"temp": "N/A", "desc": "Error"}

    # 3. PocketBase API для radar.looi.ru
    try:
        pocketbase_url = "http://64.188.74.59:8090/api/collections/radar_content/records?perPage=5&sort=-created"
        r = requests.get(pocketbase_url, timeout=5)
        if r.ok:
            records = r.json().get("items", [])
            last_24h_registrations = 0
            time_24h_ago = current_time_utc - datetime.timedelta(hours=24)
            for record in records:
                created_at_str = record.get("created")
                if created_at_str:
                    created_at = datetime.datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                    if created_at > time_24h_ago:
                        last_24h_registrations += 1
            signals["radar_registrations_24h"] = last_24h_registrations
        else:
            print(f"Error fetching PocketBase data: {r.status_code}")
            signals["radar_registrations_24h"] = 0
    except Exception as e:
        print(f"Error fetching PocketBase data: {e}")
        signals["radar_registrations_24h"] = 0

    # 4. Читает soul/sent_log.json (для delta проверки в decide)
    # This part is for soul_decide, not collect directly, but we ensure the file exists.
    if not os.path.exists(SENT_LOG_PATH):
        with open(SENT_LOG_PATH, "w") as f:
            json.dump({}, f)

    # 5. Копирует предыдущий signals_latest.json в signals_prev.json перед перезаписью
    if os.path.exists(SIGNALS_LATEST_PATH):
        try:
            shutil.copy(SIGNALS_LATEST_PATH, SIGNALS_PREV_PATH)
        except Exception as e:
            print(f"Error copying {SIGNALS_LATEST_PATH} to {SIGNALS_PREV_PATH}: {e}")

    # 6. Сохраняет результат в soul/signals_latest.json
    try:
        with open(SIGNALS_LATEST_PATH, "w") as f:
            json.dump(signals, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error writing {SIGNALS_LATEST_PATH}: {e}")

    # 7. Логирует строку в soul/signals_log.jsonl
    try:
        with open(SIGNALS_LOG_PATH, "a") as f:
            json.dump(signals, f, ensure_ascii=False)
            f.write("\n")
    except Exception as e:
        print(f"Error writing to {SIGNALS_LOG_PATH}: {e}")

    # 8. Принт в stdout: краткий статус
    print(f"Soul Daemon collected signals at {signals['timestamp']}:")
    print(f"  Urgent threads: {signals['open_threads_urgent']}")
    print(f"  Moscow weather: {signals.get('weather_moscow', {}).get('temp', 'N/A')}C, {signals.get('weather_moscow', {}).get('desc', 'N/A')}")
    print(f"  Volzhsky weather: {signals.get('weather_volzhsky', {}).get('temp', 'N/A')}C, {signals.get('weather_volzhsky', {}).get('desc', 'N/A')}")
    print(f"  New radar registrations (24h): {signals['radar_registrations_24h']}")

if __name__ == "__main__":
    collect()
