The `observation_worker_daemon` runs as a standalone process and does NOT inherit env vars from Claude
Code's MCP config (`.claude.json`). Restarted without them it loses `NEO4J_URI`, `NEO4J_USER`,
`NEO4J_PASSWORD`, `GIINT_TREEKANBAN_BOARD` (needed for PBML auto-lane-move) and `HEAVEN_DATA_DIR`.

Restart the worker through carton's own tool. Isaac 2026-10-04, verbatim: *"observation worker restart
happens thru carton's tool for it."*

```
mcp__carton__carton_management(restart_bg_server=True)
```

It runs `carton_worker_control.restart_worker`: SIGTERM every running worker by pid, wait until each is
dead, spawn one from the installed daemon file with `worker_env` — the carton MCP server's own environment
plus defaults for `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` and `HEAVEN_DATA_DIR` — and report what it
observed. `GIINT_TREEKANBAN_BOARD` reaches the worker only when the carton MCP env carries it.

It waits until every thread of each old worker is gone, because a killed worker's last thread holds the
pid lock after its leader already reads as a zombie, and when its spawn still loses that lock it waits for
the lock and spawns once more (issue #1294, card 814).

Read its answer: `✅ Daemon restarted: PID N is alive; stopped … in S s` names the new worker and how
long the old one took to die. `❌` names what failed: the survivors still running, or the pids still
holding the pid lock. Then confirm the new pid's start time is later than the installed daemon file's
mtime, so it runs the installed code.

The shell launch below is the fallback for when carton's tool cannot run:

```bash
NEO4J_URI="bolt://host.docker.internal:7687" \
NEO4J_USER="neo4j" \
NEO4J_PASSWORD="password" \
HEAVEN_DATA_DIR="/tmp/heaven_data" \
GIINT_TREEKANBAN_BOARD="poimandres_v2" \
nohup python3 -m carton_mcp.observation_worker_daemon >> /tmp/heaven_data/observation_worker_stdout.log 2>&1 &
```

Use `>>` (append), never `>` — a truncating redirect silently destroys the history you may be about to
need.

⛔ THE LIVE LOG IS `/tmp/heaven_data/observation_worker_stdout.log`, NOT `/tmp/carton_daemon.log`. That
second file holds only whatever some older launch wrote, and a log that is stale but present is worse
than one that is absent — it answers you, and the answer is from yesterday.

A WATCHDOG RESPAWN WRITES TO A THIRD FILE, `/tmp/carton_worker.log`. When a manual restart races a
watchdog respawn, the manual launch loses the PID-file lock and exits gracefully, so its log freezes at
the race moment while the SURVIVING worker writes elsewhere.

THE PROCEDURE: find the LIVE worker's actual log with `ls -la /proc/<worker-pid>/fd/1`. Never assume the
redirect. Then check THAT file's mtime.

Before trusting ANY line in a daemon log, check its mtime against now: `stat -c %y <log>; date`.

NEVER restart the daemon without setting env vars.
NEVER assume env vars are inherited from Claude Code.
NEVER read a daemon log without checking its mtime first.
Check the live log after a restart for "Neo4j shared connection established".
