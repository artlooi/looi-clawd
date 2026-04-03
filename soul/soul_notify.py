#!/usr/bin/env python3
"""Soul Daemon — Notify layer. Reads decision from stdin, saves pending_notify.json."""
import json
import sys
import os
import datetime

WORKSPACE = "/home/looi/.openclaw/workspace"
SOUL_DIR = f"{WORKSPACE}/soul"


def update_sent_log(signals):
    today = datetime.date.today().isoformat()
    log_path = f"{SOUL_DIR}/sent_log.json"
    if os.path.exists(log_path):
        with open(log_path) as f:
            log = json.load(f)
    else:
        log = {}

    if today not in log:
        log[today] = {"sent": []}

    for sig in signals:
        log[today]["sent"].append({
            "key": sig["key"],
            "timestamp": datetime.datetime.now().strftime("%H:%M"),
            "label": sig.get("label", "")
        })

    with open(log_path, "w") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def notify():
    decision = json.load(sys.stdin)

    if not decision.get("should_send"):
        print(f"[soul_notify] No signal to send: {decision.get('reason')}")
        return

    signals = decision.get("signals", [])
    signal_text = "\n".join(f"- {s['label']}" for s in signals)

    prompt = f"""Ты второй ум Артура Арсенова — продуктового дизайнера, картостроителя.

Вот сигналы из его системы:
{signal_text}

Напиши интерпретированную сводку: что происходит + признаки + на что обратить внимание.
Кратко, 3-5 предложений. Без воды. Говори как партнёр, не как уведомление."""

    # Save pending notification (real send happens via heartbeat or cron integration)
    pending = {
        "timestamp": datetime.datetime.now().isoformat(),
        "prompt": prompt,
        "signals": signals,
        "target_topic": "topic:40",
        "status": "pending"
    }

    pending_path = f"{SOUL_DIR}/pending_notify.json"
    with open(pending_path, "w") as f:
        json.dump(pending, f, ensure_ascii=False, indent=2)

    update_sent_log(signals)

    print(f"[soul_notify] Pending notification saved: {len(signals)} signals")
    print(f"  → {pending_path}")
    for s in signals:
        print(f"  • {s['label']}")


if __name__ == "__main__":
    notify()
