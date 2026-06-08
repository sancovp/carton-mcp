#!/usr/bin/env python3
"""
CartON Nightly Git Daemon
Runs git commit/push once per night at 2am
"""
import os
import sys
import time
import subprocess
from datetime import datetime, timedelta
from pathlib import Path


def run_git_operations():
    """Execute git commit and push operations."""
    heaven_data_dir = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
    wiki_path = Path(heaven_data_dir) / 'wiki'
    log_file = Path('/tmp/carton_nightly_git.log')

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        log_file.write_text(f"[{timestamp}] Starting nightly CartON git operations\n", 'a')

        if not wiki_path.exists():
            log_file.write_text(f"[{timestamp}] Wiki path does not exist: {wiki_path}\n", 'a')
            return

        # Check for uncommitted changes
        result = subprocess.run(
            ['git', 'status', '--porcelain'],
            cwd=wiki_path,
            capture_output=True,
            text=True
        )

        if not result.stdout.strip():
            log_file.write_text(f"[{timestamp}] No changes to commit\n", 'a')
            return

        # Commit changes
        subprocess.run(['git', 'add', '.'], cwd=wiki_path, check=True)
        subprocess.run(
            ['git', 'commit', '-m', f'CartON nightly update {timestamp}'],
            cwd=wiki_path,
            capture_output=True,
            text=True
        )
        log_file.write_text(f"[{timestamp}] Git commit complete\n", 'a')

        # Push if there are unpushed commits
        branch = subprocess.run(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            cwd=wiki_path,
            capture_output=True,
            text=True,
            check=True
        ).stdout.strip()

        unpushed = subprocess.run(
            ['git', 'log', f'origin/{branch}..{branch}', '--oneline'],
            cwd=wiki_path,
            capture_output=True,
            text=True
        ).stdout.strip()

        if unpushed:
            unpushed_count = len(unpushed.split('\n'))
            log_file.write_text(f"[{timestamp}] Pushing {unpushed_count} commits\n", 'a')
            subprocess.run(['git', 'push'], cwd=wiki_path, check=True)
            log_file.write_text(f"[{timestamp}] Git push complete\n", 'a')
        else:
            log_file.write_text(f"[{timestamp}] No commits to push\n", 'a')

        log_file.write_text(f"[{timestamp}] Nightly git operations complete\n", 'a')

    except Exception as e:
        log_file.write_text(f"[{timestamp}] Error: {e}\n", 'a')


def get_next_run_time():
    """Calculate next 2am run time."""
    now = datetime.now()
    next_run = now.replace(hour=2, minute=0, second=0, microsecond=0)

    # If 2am already passed today, schedule for tomorrow
    if now >= next_run:
        next_run += timedelta(days=1)

    return next_run


def main():
    """Main daemon loop."""
    print("[CartON Nightly Git Daemon] Started", file=sys.stderr)

    last_run_date = None

    while True:
        now = datetime.now()
        today = now.date()

        # Check if it's 2am (within 1 minute window) and haven't run today
        if now.hour == 2 and now.minute == 0 and last_run_date != today:
            print(f"[{now}] Running nightly git operations", file=sys.stderr)
            run_git_operations()
            last_run_date = today

        # Sleep for 60 seconds before next check
        time.sleep(60)


if __name__ == '__main__':
    main()
