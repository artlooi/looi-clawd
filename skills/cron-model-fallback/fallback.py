#!/usr/bin/env python3
# Copyright (c) 2026 Arthur Arsyonov — looi.ru
# Licensed under MIT
"""
fallback.py — Cron model fallback chain for OpenClaw.

Tries models in priority order until one succeeds. Designed to wrap cron jobs
that would otherwise fail silently when a single model is unavailable.

The user configures their own fallback chain — no provider-specific logic.
Just: try model A → failed → try model B → failed → try model C.

Usage:
    python3 fallback.py --models "anthropic/claude-sonnet-4,google/gemini-2.5-flash,groq/llama-3.3-70b" \\
                        --prompt "Your task here"

    python3 fallback.py --models "anthropic/claude-sonnet-4,google/gemini-2.5-flash" \\
                        --prompt-file /path/to/task.txt

Authentication:
    OPENCLAW_TOKEN environment variable, or ~/.openclaw/openclaw.json → gateway.auth.token
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

# --- Constants ---
DEFAULT_TIMEOUT_SEC = 120
DEFAULT_MAX_TOKENS = 4096
TOKEN_ENV_VAR = "OPENCLAW_TOKEN"
CONFIG_PATH = Path.home() / ".openclaw" / "openclaw.json"

# Exit codes
EXIT_SUCCESS = 0
EXIT_ALL_FAILED = 1
EXIT_CONFIG_ERROR = 2


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def load_token() -> Optional[str]:
    """Load the OpenClaw auth token from env var or config file."""
    token = os.environ.get(TOKEN_ENV_VAR)
    if token:
        return token.strip()

    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open("r", encoding="utf-8") as fh:
                config = json.load(fh)
            token = str(
                config.get("gateway", {}).get("auth", {}).get("token", "")
            )
            if token:
                return token.strip()
        except (json.JSONDecodeError, OSError) as exc:
            print(f"WARNING: Could not read {CONFIG_PATH}: {exc}", file=sys.stderr)

    return None


def load_default_models() -> list[str]:
    """Try to read a default fallback chain from openclaw.json.

    Looks for: cron.fallbackModels (array of model strings).
    Returns empty list if not configured.
    """
    if not CONFIG_PATH.exists():
        return []
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as fh:
            config = json.load(fh)
        models = config.get("cron", {}).get("fallbackModels", [])
        if isinstance(models, list):
            return [str(m).strip() for m in models if str(m).strip()]
    except (json.JSONDecodeError, OSError):
        pass
    return []


# ---------------------------------------------------------------------------
# Core: try a single model
# ---------------------------------------------------------------------------

def try_model(
    model: str,
    prompt: str,
    token: str,
    agent: Optional[str],
    max_tokens: int,
    timeout_sec: int,
    quiet: bool,
) -> Optional[str]:
    """
    Attempt to run a prompt against a single model via `openclaw agent`.

    No provider-specific logic — just calls the CLI with --model and checks
    if it succeeds. The OpenClaw gateway handles provider routing.

    Returns the response text on success, or None on any failure.
    """
    if not quiet:
        print(f"  → Trying: {model}", file=sys.stderr)

    start = time.monotonic()

    try:
        cmd = [
            "openclaw", "agent",
            "--message", prompt,
            "--model", model,
            "--max-tokens", str(max_tokens),
            "--json",
        ]
        if agent:
            cmd.extend(["--agent", agent])

        env = {**os.environ, TOKEN_ENV_VAR: token} if token else dict(os.environ)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            env=env,
        )
        elapsed = time.monotonic() - start

        if result.returncode != 0:
            if not quiet:
                stderr_preview = result.stderr[:200].strip()
                print(f"  ✗ {model}: failed after {elapsed:.1f}s — {stderr_preview}", file=sys.stderr)
            return None

        output = result.stdout.strip()
        if not output:
            if not quiet:
                print(f"  ✗ {model}: empty response after {elapsed:.1f}s", file=sys.stderr)
            return None

        if not quiet:
            print(f"  ✓ {model}: OK ({elapsed:.1f}s)", file=sys.stderr)
        return output

    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        if not quiet:
            print(f"  ✗ {model}: timeout after {elapsed:.1f}s", file=sys.stderr)
        return None
    except FileNotFoundError:
        if not quiet:
            print("  ✗ 'openclaw' CLI not found in PATH", file=sys.stderr)
        return None
    except Exception as exc:
        elapsed = time.monotonic() - start
        if not quiet:
            print(f"  ✗ {model}: error after {elapsed:.1f}s — {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Fallback chain
# ---------------------------------------------------------------------------

def run_with_fallback(
    models: list[str],
    prompt: str,
    token: str,
    agent: Optional[str],
    max_tokens: int,
    timeout_sec: int,
    quiet: bool,
) -> tuple[Optional[str], str, int]:
    """
    Try each model in order. Return (result_text, winning_model, attempts).
    result_text is None if all models failed.
    """
    if not quiet:
        print(f"\n[fallback] {len(models)} model(s) in chain: {', '.join(models)}", file=sys.stderr)

    for attempt, model in enumerate(models, start=1):
        result = try_model(
            model=model,
            prompt=prompt,
            token=token,
            agent=agent,
            max_tokens=max_tokens,
            timeout_sec=timeout_sec,
            quiet=quiet,
        )
        if result is not None:
            if not quiet:
                print(
                    f"\n[fallback] ✓ Success: {model} (attempt {attempt}/{len(models)})",
                    file=sys.stderr,
                )
            return result, model, attempt

    if not quiet:
        print(f"\n[fallback] ✗ All {len(models)} model(s) failed.", file=sys.stderr)
    return None, "", len(models)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cron model fallback chain for OpenClaw.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  # Run a task with fallback chain
  python3 fallback.py \\
    --models "anthropic/claude-sonnet-4,google/gemini-2.5-flash,groq/llama-3.3-70b" \\
    --prompt "Summarize today's news"

  # Use defaults from openclaw.json (cron.fallbackModels)
  python3 fallback.py --prompt "Your task"

  # Use a specific agent
  python3 fallback.py \\
    --models "google/gemini-2.5-flash,anthropic/claude-haiku-4-5" \\
    --agent my-agent --prompt "Your task"

  # Read prompt from file
  python3 fallback.py --models "..." --prompt-file /path/to/task.txt

Configuration:
  Set OPENCLAW_TOKEN env var, or configure in ~/.openclaw/openclaw.json.
  Default fallback chain: openclaw.json → cron.fallbackModels (array).
        """,
    )

    parser.add_argument(
        "--models", type=str, default=None,
        help="Comma-separated model list in priority order. "
             "If omitted, reads from openclaw.json → cron.fallbackModels",
    )
    parser.add_argument(
        "--prompt", type=str, default=None,
        help="Task prompt string",
    )
    parser.add_argument(
        "--prompt-file", type=str, default=None, metavar="FILE",
        help="Path to file containing the task prompt",
    )
    parser.add_argument(
        "--agent", type=str, default=None,
        help="OpenClaw agent name (uses default agent if omitted)",
    )
    parser.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT_SEC,
        help=f"Seconds to wait per model attempt (default: {DEFAULT_TIMEOUT_SEC})",
    )
    parser.add_argument(
        "--max-tokens", type=int, default=DEFAULT_MAX_TOKENS,
        help=f"Maximum tokens in the response (default: {DEFAULT_MAX_TOKENS})",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress progress output; only print the final result",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # Resolve model list: CLI flag → config file → error
    if args.models:
        models = [m.strip() for m in args.models.split(",") if m.strip()]
    else:
        models = load_default_models()

    if not models:
        print(
            "ERROR: No models specified.\n"
            "  Use --models 'model1,model2,...' or configure\n"
            "  cron.fallbackModels in ~/.openclaw/openclaw.json",
            file=sys.stderr,
        )
        return EXIT_CONFIG_ERROR

    # Load auth token
    token = load_token()
    if not token:
        print(
            f"ERROR: No auth token found.\n"
            f"  Set {TOKEN_ENV_VAR} environment variable, or ensure\n"
            f"  {CONFIG_PATH} contains gateway.auth.token",
            file=sys.stderr,
        )
        return EXIT_CONFIG_ERROR

    # Resolve prompt
    prompt: Optional[str] = None

    if args.prompt_file:
        prompt_path = Path(args.prompt_file)
        if not prompt_path.exists():
            print(f"ERROR: Prompt file not found: {prompt_path}", file=sys.stderr)
            return EXIT_CONFIG_ERROR
        try:
            prompt = prompt_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            print(f"ERROR: Could not read prompt file: {exc}", file=sys.stderr)
            return EXIT_CONFIG_ERROR
    elif args.prompt:
        prompt = args.prompt.strip()

    if not prompt:
        print("ERROR: Provide a task via --prompt or --prompt-file.", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    # Run
    result, winning_model, attempts = run_with_fallback(
        models=models,
        prompt=prompt,
        token=token,
        agent=args.agent,
        max_tokens=args.max_tokens,
        timeout_sec=args.timeout,
        quiet=args.quiet,
    )

    if result is None:
        print(
            f"ERROR: All models failed after {attempts} attempt(s). "
            f"Models tried: {', '.join(models)}",
            file=sys.stderr,
        )
        return EXIT_ALL_FAILED

    print(result)
    return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
