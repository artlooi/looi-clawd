# klin-system

OpenClaw extensions: memory, cron fallbacks, Soul Daemon autonomy.

Built by [Art Looi](https://linkedin.com/in/loooi) + Klin agent.

## What's here

### `skills/cron-model-fallback/`
OpenClaw cron jobs don't have model fallbacks out of the box. When your primary model is unavailable (rate limit, outage), scheduled tasks silently fail. This skill fixes that.

→ `fallback.py` — checks all cron jobs without explicit model and patches them

### `soul/`
Soul Daemon — a proactive "second mind" for OpenClaw. Collects signals (no LLM), decides if there's something worth saying, then calls LLM only when needed.

Cost: ~$0.002/day vs ~$0.08 with naive approach.

→ `soul_collect.py` — gathers signals: open threads, weather, radar registrations
→ `soul_decide.py` — pure Python decision layer, no LLM
→ `soul_notify.py` — calls LLM only when signal threshold is met
→ `soul_runner.sh` — runs the full chain

## Usage

Give this repo URL to your OpenClaw agent:
> "Read github.com/artlooi/klin-system and set up cron fallbacks and Soul Daemon"

Or clone and follow instructions in each subfolder.

## License
MIT
