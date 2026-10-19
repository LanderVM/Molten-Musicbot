"""Atomic JSON persistence and duration formatting."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from datetime import timedelta

logger = logging.getLogger("dashboard")
STATS_FILE = "data/dashboard_stats.json"


def _load_stats() -> dict:
    try:
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object")
        return data
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        # Preserve unreadable data instead of silently overwriting it on next save.
        backup = f"{STATS_FILE}.corrupt-{int(time.time())}"
        try:
            os.replace(STATS_FILE, backup)
            logger.error("Invalid dashboard stats backed up to %s: %s", backup, exc)
        except OSError:
            logger.exception("Unable to back up invalid dashboard stats: %s", exc)
        return {}


def _save_stats_sync(data: dict) -> None:
    directory = os.path.dirname(os.path.abspath(STATS_FILE))
    os.makedirs(directory, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=directory,
            prefix=".dashboard-",
            suffix=".tmp",
            delete=False,
        ) as f:
            temp_path = f.name
            json.dump(data, f, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, STATS_FILE)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


def _fmt_playtime(ms: int) -> str:
    s = ms // 1000
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {sec}s"
    return f"{sec}s"


def _fmt_uptime(delta: timedelta) -> str:
    days = delta.days
    h, rem = divmod(delta.seconds, 3600)
    m, s = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if h or days:
        parts.append(f"{h}h")
    if m or h or days:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)
