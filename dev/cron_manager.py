"""
ClawMate Cron Manager — 封装 openclaw cron add/run 操作（v1.25 精简版）。

删除 resolve_cron_id / remove_all / _cron_list_stdout（不再需要）。
保留 add_cron / run_cron / _get_cron_bin。
add_cron 不再内部调用 remove_all（由调用者负责幂等清理）。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys


def _get_cron_bin() -> str:
    """Return path to openclaw CLI, or 'echo' in test mode."""
    bin_path = shutil.which("openclaw")
    if not bin_path and hasattr(sys, "_called_from_test"):
        bin_path = "echo"
    if not bin_path:
        raise RuntimeError("openclaw CLI not found in PATH")
    return bin_path


def add_cron(
    cron_bin: str | None,
    name: str,
    agent_id: str,
    message: str,
    every: str = "6h",
    session: str = "isolated",
    no_deliver: bool = True,
) -> bool:
    """
    Add an openclaw cron job. Caller is responsible for removing existing
    jobs with the same name before calling add_cron.

    Returns True on success.
    """
    bin_path = cron_bin or _get_cron_bin()

    # Build args — message is passed via the last positional arg after --message
    args = [
        bin_path, "cron", "add",
        "--name", name,
        "--agent", agent_id,
        "--session", session,
        "--every", every,
    ]
    if no_deliver:
        args.append("--no-deliver")
    args.append("--message")
    args.append(message[:40000])  # truncate to safe length

    try:
        result = subprocess.run(
            args,
            timeout=10, capture_output=True, text=True,
        )
        return result.returncode == 0
    except Exception:
        return False


def run_cron(cron_bin: str | None, name: str) -> bool:
    """
    Trigger immediate execution of a cron job by exact name.
    Returns True if the job was found and triggered.
    """
    bin_path = cron_bin or _get_cron_bin()

    try:
        result = subprocess.run(
            [bin_path, "cron", "list", "--json"],
            timeout=15, capture_output=True, text=True,
        )
        if result.returncode != 0:
            return False

        entries = json.loads(result.stdout)
        jobs = entries if isinstance(entries, list) else entries.get("jobs", entries.get("items", []))
        for job in jobs:
            if job.get("name") == name:
                subprocess.run(
                    [bin_path, "cron", "run", job["id"]],
                    timeout=10, capture_output=True,
                )
                return True
    except Exception:
        pass
    return False
