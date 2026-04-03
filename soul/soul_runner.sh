#!/bin/bash
# Soul Daemon runner — запускает полную цепочку collect → decide → notify
set -e
WORKSPACE="/home/looi/.openclaw/workspace"
LOG="$WORKSPACE/soul/daemon.log"
timestamp=$(date '+%Y-%m-%d %H:%M:%S')

echo "[$timestamp] soul_runner start" >> "$LOG"

python3 "$WORKSPACE/soul/soul_collect.py" >> "$LOG" 2>&1

DECISION=$(python3 "$WORKSPACE/soul/soul_decide.py" 2>> "$LOG")
echo "$DECISION" >> "$LOG"

if echo "$DECISION" | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0 if d.get('should_send') else 1)" 2>/dev/null; then
    echo "$DECISION" | python3 "$WORKSPACE/soul/soul_notify.py" >> "$LOG" 2>&1
    echo "[$timestamp] soul_runner: notification queued" >> "$LOG"
else
    REASON=$(echo "$DECISION" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('reason',''))" 2>/dev/null)
    echo "[$timestamp] soul_runner: silent ($REASON)" >> "$LOG"
fi
