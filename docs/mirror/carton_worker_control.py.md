# doc(m): carton_worker_control.py

**Module:** `carton-mcp/carton_worker_control.py`  •  **Mirrors:** the module 1:1 (IMPL — what the code IS)  •  **Projected from the HALO SEEM store:** 1 sealed boundary lands here

## Features whose sealed boundary lands in this module

### Worker_Restart — feature boundary of `Giint_Feature_Carton_Mcp_Worker_Restart`

- **user action:** the agent calls the carton carton_management MCP tool with restart_bg_server, because a pip install changes no running observation worker, and one call must end with a live worker running the installed code, or a named survivor, and say which
- **doc(v):** `docs/vision/_carton_worker_control.md`
- **outputs to:** `['dead_letter_lane_fires']`
- **sealed:** v3, key `e610c45b7e4265a1`, commit `65b574104`, valid from 2026-10-04T07:21:03
- **ranges in this module** (layer order):
  - `L1 restart` · `carton_worker_control.py:371-415` — restart_worker: list the workers (find_workers, the process table by default), stop them and time how long each whole thread group takes to die (up to DEFAULT_STOP_TIMEOUT_S, 60 s), spawn one, wait the grace; when the spawn is gone, _respawn_after_release names the pid file holders, waits up to release_timeout_s for lock_is_free, spawns once more; the verdict carries the stop time and whom it waited for, or the holders still there (card 814)
  - `L2 control` · `carton_worker_control.py:1-53` — the module header: an operation on the worker reports what happened, never what was attempted; the two launch forms; no pkill, matching is pure over ps output and the kill is by pid; the constants, WORKER_PID_FILE the one name of /tmp/carton_worker.pid that the daemon locks and a restart reads the holders of, and DEFAULT_RELEASE_TIMEOUT_S, the bound on waiting for that lock (card 814)
  - `L2 control` · `carton_worker_control.py:56-175` — the pure core: is_worker_command and select_worker_pids match the worker in both launch forms; group_alive answers alive while any thread is neither Z nor X, the leader deciding only when no thread is readable (card 814: a zombie leader whose other thread still exits holds the pid flock); lock_holders names the pids whose fds resolve to the pid file; restart_verdict turns before, survivors, the spawned pid liveness, the holders and whom it waited for into the verdict; worker_env carries the NEO4J and HEAVEN_DATA_DIR defaults over the caller env
  - `L2 control` · `carton_worker_control.py:178-368` — the adapters: _ps_lines and running_worker_pids read the process table; _alive reads the leader and every /proc/PID/task state and asks group_alive; _proc_state reads one stat state; lock_is_free takes the flock without blocking and lets it go, the one test of the lock itself, because a dying worker last thread drops its fd table before the deferred close frees the flock; _fd_table reads every /proc/PID/task/TID/fd, since a zombie leader /proc/PID/fd refuses; acquire_pid_lock takes the flock in append mode and truncates only once held; stop_workers SIGTERMs by pid and waits; spawn_worker launches python3 on the daemon file with worker_env in its own session
- **also passes through:** `server_fastmcp.py`, `observation_worker_daemon.py`, `test_carton_worker_control.py`

---

Projected by `seem docm` from the SEEM index (index.json, validity.json, the drafts); `doc-mirror-commit` regenerates it on every change of this module. Never written by hand and never by a spawned model (issue #225): what is not sealed in HALO SEEM is not in this doc(m).
