"""
ClawMate Cron Manager — 封装 openclaw cron add/rm/run 操作。

Usage:
    from cron_manager import add_cron, remove_all, run_cron, _get_cron_bin
"""

from __future__ import annotations

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


def _cron_list_stdout(cron_bin: str | None = None) -> str:
    """Run `openclaw cron list` and return stdout as plain text."""
    bin_path = cron_bin or _get_cron_bin()
    result = subprocess.run(
        [bin_path, "cron", "list"],
        timeout=10, capture_output=True, text=True,
    )
    if result.returncode != 0:
        return ""
    return result.stdout


def resolve_cron_id(cron_bin: str | None, name: str) -> str | None:
    """
    Parse `openclaw cron list` table output and find the UUID for a cron job
    whose name contains `name[:20]`.

    Cron names are truncated to 24 chars (21 + '...') in table output,
    so prefix matching uses the first 20 characters.

    Returns the UUID string, or None if not found.
    """
    stdout = _cron_list_stdout(cron_bin)
    if not stdout:
        return None
    prefix = name[:20]
    for line in stdout.split("\n"):
        if prefix in line:
            return line.split()[0] if line.strip() else None
    return None


def remove_all(cron_bin: str | None, name: str) -> int:
    """
    Remove ALL cron jobs matching `name[:20]`.
    Uses a while loop to catch duplicates.
    Returns the number removed.
    """
    bin_path = cron_bin or _get_cron_bin()
    count = 0
    while True:
        job_id = resolve_cron_id(bin_path, name)
        if not job_id:
            break
        try:
            subprocess.run(
                [bin_path, "cron", "rm", job_id],
                timeout=10, capture_output=True,
            )
            count += 1
        except Exception:
            break
    return count


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
    Add (or replace) an openclaw cron job.

    If a job with the same name prefix already exists, it is removed first
    to avoid duplicates and stale config.

    Returns True on success.
    """
    bin_path = cron_bin or _get_cron_bin()

    # Remove existing to avoid duplicates and stale config
    remove_all(bin_path, name)

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
    Trigger immediate execution of a cron job by name prefix.
    Returns True if the job was found and triggered.
    """
    bin_path = cron_bin or _get_cron_bin()
    job_id = resolve_cron_id(bin_path, name)
    if not job_id:
        return False
    try:
        subprocess.run(
            [bin_path, "cron", "run", job_id],
            timeout=10, capture_output=True,
        )
        return True
    except Exception:
        return False

