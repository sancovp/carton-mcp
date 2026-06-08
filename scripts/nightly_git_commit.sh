#!/bin/bash
# CartON Nightly Git Commit/Push
# Runs once per night to commit and push all CartON wiki changes
# Scheduled via cron: 0 2 * * * /home/GOD/carton_mcp/scripts/nightly_git_commit.sh

set -e

HEAVEN_DATA_DIR="${HEAVEN_DATA_DIR:-/tmp/heaven_data}"
WIKI_PATH="$HEAVEN_DATA_DIR/wiki"
LOG_FILE="/tmp/carton_nightly_git.log"

echo "[$(date)] Starting nightly CartON git commit" >> "$LOG_FILE"

if [ ! -d "$WIKI_PATH" ]; then
    echo "[$(date)] Wiki path does not exist: $WIKI_PATH" >> "$LOG_FILE"
    exit 0
fi

cd "$WIKI_PATH"

# Check if there are uncommitted changes
if ! git status --porcelain | grep -q .; then
    echo "[$(date)] No changes to commit" >> "$LOG_FILE"
    exit 0
fi

# Add all changes
git add .

# Commit with timestamp
TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")
git commit -m "CartON nightly update $TIMESTAMP" 2>&1 >> "$LOG_FILE"

echo "[$(date)] Git commit complete" >> "$LOG_FILE"

# Push if there are unpushed commits
BRANCH=$(git rev-parse --abbrev-ref HEAD)
UNPUSHED=$(git log origin/$BRANCH..$BRANCH --oneline 2>/dev/null | wc -l)

if [ "$UNPUSHED" -gt 0 ]; then
    echo "[$(date)] Pushing $UNPUSHED commits" >> "$LOG_FILE"
    git push 2>&1 >> "$LOG_FILE"
    echo "[$(date)] Git push complete" >> "$LOG_FILE"
else
    echo "[$(date)] No commits to push" >> "$LOG_FILE"
fi

echo "[$(date)] Nightly git operations complete" >> "$LOG_FILE"
