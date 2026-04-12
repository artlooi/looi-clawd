#!/usr/bin/env python3
"""
soul_notify.py — Notification delivery layer for the Soul Daemon.

Reads the decision JSON from stdin (piped from soul_decide.py) and prepares
a pending notification for the user. Does NOT call the LLM directly — instead
writes a prompt + signal payload to pending_notify.json, which is picked up
by a heartbeat or cron integration that handles actual LLM summarization
and message delivery.

Architecture:
    - Receives decision via stdin JSON ({"should_send": true, "signals": [...]})
    - Composes an LLM prompt from the signal labels
    - Writes pending_notify.json for downstream delivery
    - Updates sent_log.json to prevent duplicate sends (used by soul_decide.py)

Data flow:
    soul_decide.py (stdout) | soul_notify.py (stdin) -> pending_notify.json
                                                     -> sent_log.json

Configuration:
    SOUL_TARGET_TOPIC env var controls which messaging topic receives alerts.
"""

import json
import sys
import os
import datetime

WORKSPACE = os.environ.get(
    "SOUL_WORKSPACE", os.path.expanduser("~/.openclaw/workspace")
)
SOUL_DIR = f"{WORKSPACE}/soul"


# ---------------------------------------------------------------------------
# Sent log management
# ---------------------------------------------------------------------------


def update_sent_log(signals):
    """
    Append sent signal keys to today's entry in sent_log.json.

    This log is read by soul_decide.py's already_sent_today() to prevent
    sending the same signal type more than once per calendar day.

    Args:
        signals: list of signal dicts, each with 'key' and 'label' fields.
    """
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
        log[today]["sent"].append(
            {
                "key": sig["key"],
                "timestamp": datetime.datetime.now().strftime("%H:%M"),
                "label": sig.get("label", ""),
            }
        )

    with open(log_path, "w") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Main notification logic
# ---------------------------------------------------------------------------


def notify():
    """
    Read decision from stdin, compose an LLM prompt, and save pending notification.

    If should_send is False, logs the reason and exits early.
    Otherwise:
        1. Builds a human-readable signal summary
        2. Composes an LLM prompt for interpreted notification text
        3. Writes pending_notify.json (picked up by delivery integration)
        4. Updates sent_log.json to mark these signals as sent
    """
    decision = json.load(sys.stdin)

    if not decision.get("should_send"):
        print(f"[soul_notify] No signal to send: {decision.get('reason')}")
        return

    signals = decision.get("signals", [])
    signal_text = "\n".join(f"- {s['label']}" for s in signals)

    # Prompt designed to produce a brief, partner-like interpretation
    # rather than a raw data dump or generic notification
    prompt = f"""You are a personal AI assistant — a second mind for the user.

Here are signals from their monitoring system:
{signal_text}

Write an interpreted summary: what is happening + indicators + what to pay attention to.
Keep it brief, 3-5 sentences. No fluff. Speak as a partner, not as a notification."""

    # Save pending notification (real send happens via heartbeat or cron integration)
    pending = {
        "timestamp": datetime.datetime.now().isoformat(),
        "prompt": prompt,
        "signals": signals,
        "target_topic": os.environ.get("SOUL_TARGET_TOPIC", "PERSONAL_TOPIC"),
        "status": "pending",
    }

    pending_path = f"{SOUL_DIR}/pending_notify.json"
    with open(pending_path, "w") as f:
        json.dump(pending, f, ensure_ascii=False, indent=2)

    # Mark signals as sent so soul_decide.py won't re-trigger them today
    update_sent_log(signals)

    print(f"[soul_notify] Pending notification saved: {len(signals)} signals")
    print(f"  → {pending_path}")
    for s in signals:
        print(f"  • {s['label']}")


if __name__ == "__main__":
    notify()
