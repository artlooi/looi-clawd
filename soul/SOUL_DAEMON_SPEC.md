# Soul Daemon Spec v1
> Digital nervous system for the agent. A second mind. Not spam — a signal when the moment is right.
> Principle: better to miss 3 weak signals than to send 1 noisy one.

---

## 1. Architecture

```
[Cron every 60 min]
       ↓
[soul_collect.py] — NO LLM
  ├── reads ved/state.json → open_threads, urgency
  ├── wttr.in CityA + CityB → weather
  ├── PocketBase API your-app.example.com → new registrations/views in 24h
  ├── Telegram bot history → close contacts (last message + timestamp)
  ├── Channel stats → subscribers (delta in 24h)
  └── Result → soul/signals_latest.json

[soul_decide.py] — NO LLM
  ├── Reads signals_latest.json
  ├── Compares with soul/signals_prev.json (delta)
  ├── Applies silence rules (time, already sent, weak signal)
  ├── If threshold not reached → exit (do nothing)
  └── If threshold reached → pass data to LLM agent

[g-flash agent] — ONLY if there is a signal
  ├── Receives: signals_latest.json + open_threads context
  ├── Generates: interpreted summary (what + indicators + what to pay attention to)
  └── Sends to Telegram topic:40 (personal) or topic:39 (system)
```

**Key principle:** LLM runs only when data has already been filtered. Collection and decision — pure Python.

---

## 2. Sources v1 (stable, implementable now)

| Source | Method | What we get |
|---|---|---|
| `ved/state.json` | `json.load()` | open_threads with urgency=action_needed |
| Weather | `wttr.in/:city?format=j1` | temp, description, CityA + CityB |
| your-app.example.com | PocketBase REST API (YOUR_SERVER_IP:8090) | new records/registrations in 24h |
| @your-channel | Telegram Bot API | subscriber delta (if available) |
| Close contacts | Telegram Bot API sessions history | timestamp of last message |

**[Skeptic]:** PocketBase API — no auth token, need to add. Telegram sessions history — not guaranteed to be directly accessible, need to verify endpoint. Better to start with wttr.in + ved + app API as the most reliable.

---

## 3. Sources v2 (after stabilizing v1)

- YouTube channels — RSS feed for new videos
- Telegram channels — parsing via Bot API or MTProto
- Web mentions — web_fetch + parsing
- Name mentions — Serper/Tavily search once per day
- Facebook — difficult without API, skip for now

---

## 4. Silence rules (when NOT to send)

```python
SILENCE_RULES = [
    # Time
    lambda: 10 <= now_tz.hour < 16,  # work block
    lambda: 0 <= now_tz.hour < 8,    # night (non-critical)

    # Already sent today on this topic
    lambda signal: signal["key"] in sent_today,

    # Weak signal — no changes
    lambda signal: signal["delta"] == 0 and signal["urgency"] != "critical",

    # User is active in conversation (incoming message <30 min ago)
    lambda: last_user_message_age_min < 30,
]
```

**[Skeptic]:** Determining "user is active" — no direct API. Stub: if heartbeat detected activity in last 30 min → stay silent. Implement via `soul/user_last_seen.json` written by heartbeat.

---

## 5. Threshold rules (what constitutes a strong enough signal)

```python
THRESHOLDS = {
    "open_thread_urgent": True,           # urgency == "action_needed" → always signal
    "app_new_registration": 1,            # ≥1 new registration in 24h
    "channel_subscriber_delta": 5,        # +5 subscribers in 24h
    "weather_warning": ["rain", "storm", "ice"],  # dangerous weather
    "close_person_silent_days": 3,        # contact hasn't written in >3 days
    "close_person_silent_days_alt": 7,    # another contact hasn't written in >7 days
}
```

Everything below these thresholds — don't send, only log to `soul/signals_log.jsonl`.

---

## 6. Schedule

```cron
# Soul Daemon — every hour, except night
0 8-23 * * * python3 /home/user/.openclaw/workspace/soul/soul_collect.py >> /home/user/.openclaw/workspace/soul/daemon.log 2>&1
```

**Why not every 30 min:** most sources update once every few hours. One hour is a reasonable balance between freshness and noise. At night (00:00-08:00) — don't run (except for critical urgency in ved).

---

## 7. State storage

**`soul/sent_log.json`** — what was already sent:
```json
{
  "2026-04-03": {
    "sent": [
      {"key": "app_registration", "timestamp": "10:15", "summary": "..."},
      {"key": "contact_silent", "timestamp": "19:00", "summary": "..."}
    ]
  }
}
```

**`soul/signals_latest.json`** — latest data snapshot (overwritten each time):
```json
{
  "timestamp": "2026-04-03T15:00:00",
  "open_threads_urgent": 2,
  "app_registrations_24h": 3,
  "channel_delta": 0,
  "weather_city_a": {"temp": 12, "desc": "Cloudy"},
  "weather_city_b": {"temp": 18, "desc": "Clear"},
  "contact_a_last_message_hours_ago": 6,
  "contact_b_last_message_hours_ago": 72
}
```

**`soul/signals_prev.json`** — previous snapshot for computing deltas.

**`soul/signals_log.jsonl`** — all snapshots for debugging and analysis.

---

## 8. Token cost estimate

| Scenario | Tokens | Cost |
|---|---|---|
| No signal (Python only) | 0 | $0 |
| Signal present → g-flash synthesis | ~800 in + ~300 out | ~$0.0005 |
| **1 active day (3-4 signals)** | ~4400 | **~$0.002** |
| **1 quiet day (0-1 signal)** | ~800 | **~$0.0004** |

This is an order of magnitude cheaper than heartbeat. Main savings: collection and filtering without LLM.

---

## 9. v1 plan — what to implement first

**Week 1 — collection and silence only:**
```python
# soul/soul_collect.py
import json, requests, datetime

WORKSPACE = "/home/user/.openclaw/workspace"

def collect():
    signals = {}

    # 1. ved/state.json
    with open(f"{WORKSPACE}/ved/state.json") as f:
        ved = json.load(f)
    urgent = [t for t in ved.get("open_threads", [])
              if t.get("urgency") == "action_needed"]
    signals["open_threads_urgent"] = len(urgent)
    signals["open_threads_urgent_titles"] = [t.get("title") for t in urgent]

    # 2. Weather
    for city, name in [("CityA", "city_a"), ("CityB", "city_b")]:
        r = requests.get(f"https://wttr.in/{city}?format=j1", timeout=5)
        if r.ok:
            w = r.json()["current_condition"][0]
            signals[f"weather_{name}"] = {
                "temp": w["temp_C"],
                "desc": w["weatherDesc"][0]["value"]
            }

    # 3. Save
    prev_path = f"{WORKSPACE}/soul/signals_latest.json"
    if os.path.exists(prev_path):
        import shutil
        shutil.copy(prev_path, f"{WORKSPACE}/soul/signals_prev.json")

    signals["timestamp"] = datetime.datetime.now().isoformat()
    with open(prev_path, "w") as f:
        json.dump(signals, f, ensure_ascii=False, indent=2)

    print(f"Collected: {len(signals)} signals")

if __name__ == "__main__":
    collect()
```

**Week 2:** add soul_decide.py + silence rules + first LLM synthesis (g-flash).
**Week 3:** connect PocketBase API + Telegram sessions for close contacts.

---

## Risks (Skeptic, final word)

1. **Telegram sessions** — no direct API for reading conversations with specific people. Need MTProto or a special endpoint. Without this — close contacts remain outside v1.
2. **Channel stats** — no public API for subscriber delta. Need a custom solution.
3. **Threshold drift** — in a month "3 new registrations" might be the norm, not a signal. Thresholds need manual review once a month.
4. **Weather noise** — "Cloudy in CityB" is not a signal. Filter only extreme conditions.
5. **LLM hallucination** — g-flash might "imagine" an interpretation. Give it only raw facts, don't ask it to interpret people's intentions.

---

*Created: 2026-04-03. Author: the agent + Council (Skeptic/Practitioner/Architect).*
