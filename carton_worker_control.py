"""Worker lifecycle control for the observation daemon — matching, stopping, restarting.

THE INVARIANT THIS MODULE HOLDS: an operation on the worker REPORTS WHAT HAPPENED, never
what was attempted. The defect it replaces (issue #276) did the opposite in both halves —
it killed with a pattern that could not match the running worker, spawned a replacement
that exited on the pid lock, and reported `✅ Daemon restarted: PID N` regardless. Every
dev-flow instruction in this repo that ends "…then restart the daemon" was defeated by it,
silently, and an agent that installs a fix and sees that tick is testing OLD CODE while
believing it is testing new code.

TWO LAUNCH FORMS, and that is the whole bug:

    python3 /…/site-packages/carton_mcp/observation_worker_daemon.py   ← path form
    python3 -m carton_mcp.observation_worker_daemon                    ← module form

`pkill -f observation_worker_daemon.py` matches the first and NOT the second. supervisord
uses the second (application/carton-saas/box/supervisord.conf), and the worker found running
on this box was the second. So the verb worked against a daemon it had started itself and
failed against one started by supervisord or by hand — which is exactly why it stayed hidden.

WHY THERE IS NO pkill HERE AT ALL. Matching is done in a pure function over `ps` output and
the kill is by explicit PID. That removes the `pkill -f` self-match hazard by construction
rather than by remembering the bracket trick (`pkill-pgrep-bracket-trick-no-self-match`),
and — the load-bearing half — it is what makes the outcome VERIFIABLE: you cannot confirm
that the thing you killed is gone if you never knew which pid it was.

One capability, one module (the carton_breaker / carton_pathguard / carton_deadletter
precedent). Onion: the pure functions take no I/O and are unit-testable standalone; the
adapters below them are thin and each one reports what it observed.
"""

import fcntl
import logging
import os
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# The two ways the worker is ever launched. Both are real and both are in use.
WORKER_MODULE = "carton_mcp.observation_worker_daemon"
WORKER_FILE = "observation_worker_daemon.py"

# A worker's whole thread group must be gone before its pid lock is free, and a big worker
# takes seconds to tear down: 97948 at 1.85 GB took about 7-10 s on 2026-10-04 (card 814).
# The cap costs nothing on success, because stop_workers returns the moment the group dies.
DEFAULT_STOP_TIMEOUT_S = 60.0
DEFAULT_START_GRACE_S = 2.0
DEFAULT_RELEASE_TIMEOUT_S = 60.0

# The one name of the worker's pid lock: the daemon takes it, a restart reads who holds it.
WORKER_PID_FILE = Path("/tmp/carton_worker.pid")


# ---------------------------------------------------------------- pure


def is_worker_command(cmdline):
    """True when `cmdline` is an observation-worker process, in EITHER launch form.

    Deliberately substring-based rather than a regex over an assumed argv shape: the path
    form carries an absolute path that differs per install (site-packages vs a source
    checkout) and the module form carries none at all. What both share is the dotted or
    slashed module name, and nothing else on this box legitimately carries it.

    The `-m` form is matched on the DOTTED name so that a mere mention of the file (a log
    path, an editor, a grep) does not read as a running worker.
    """
    if not cmdline:
        return False
    text = str(cmdline)
    return WORKER_FILE in text or WORKER_MODULE in text


def select_worker_pids(ps_lines, exclude_pids=()):
    """Pure: the worker PIDs in `ps -eo pid,args`-shaped lines, minus `exclude_pids`.

    Excluding is how a caller keeps its own process (and its own `ps` child) out of the
    answer — the self-match problem, solved by identity rather than by pattern.
    """
    excluded = {int(p) for p in exclude_pids}
    pids = []
    for line in ps_lines or []:
        parts = str(line).strip().split(None, 1)
        if len(parts) != 2:
            continue
        raw_pid, cmdline = parts
        try:
            pid = int(raw_pid)
        except ValueError:
            continue
        if pid in excluded:
            continue
        if is_worker_command(cmdline):
            pids.append(pid)
    return pids


def group_alive(leader_state, thread_states):
    """Pure: can this pid still do work, given its leader's state and every thread's state?

    Alive while any thread is neither Z nor X. With no thread readable the leader decides,
    and an unreadable leader counts as alive, because the signal check already said so.
    """
    if thread_states:
        return any(s not in ("Z", "X") for s in thread_states)
    return leader_state != "Z"


def lock_holders(path, fd_table, exclude_pids=()):
    """Pure: the pids whose open fds resolve to `path`, minus `exclude_pids`, sorted."""
    target = os.path.realpath(str(path))
    excluded = {int(p) for p in exclude_pids}
    return sorted({int(pid) for pid, fd_target in fd_table
                   if fd_target == target and int(pid) not in excluded})


def restart_verdict(before, survivors, spawned_pid, spawned_alive, holders=(), waited_for=(),
                    stop_s=None):
    """Pure: did the restart ACTUALLY happen? Returns (ok, message).

    This is the whole point of the module. The old code reported the pid it handed to
    Popen and checked nothing, so all three of these failures read as success:
      - nothing was killed, because the pattern matched nothing;
      - the spawned process exited immediately on the pid lock held by the survivor;
      - both at once, which is what actually happened on 2026-09-01.

    `holders` are the pids still holding the pid file when the spawn was found gone;
    `waited_for` are the pids a successful respawn waited on to let go of it; `stop_s` is
    how long the old workers took to die, reported so a growing stop time is seen early.
    """
    if survivors:
        return False, (f"❌ Daemon restart FAILED: {len(survivors)} old worker(s) still "
                       f"running {sorted(survivors)} — they were not killed, so anything "
                       f"you install now is NOT what is running. Kill them by pid and retry.")
    if spawned_pid is None:
        return False, ("❌ Daemon restart FAILED: no replacement worker was spawned "
                       f"(stopped {len(before)}).")
    if not spawned_alive and holders:
        return False, (f"❌ Daemon restart FAILED: spawned PID {spawned_pid} exited on the "
                       f"pid-file lock, which PID(s) {sorted(holders)} still hold — NO worker "
                       f"this call started is draining the queue. Read them with "
                       f"`ps -o pid,stat,args -p {','.join(str(p) for p in sorted(holders))}`; "
                       f"a worker among them runs the code it started with.")
    if not spawned_alive:
        return False, (f"❌ Daemon restart FAILED: spawned PID {spawned_pid} is already gone. "
                       f"A worker exits immediately when another holds the pid-file lock, so "
                       f"check for a survivor this did not see before trusting any restart.")
    took = f" in {stop_s:.1f} s" if stop_s is not None and before else ""
    waited = (f"; it first waited for PID(s) {sorted(waited_for)} to release the pid-file lock"
              if waited_for else "")
    return True, (f"✅ Daemon restarted: PID {spawned_pid} is alive; "
                  f"stopped {len(before)} old worker(s) {sorted(before)}{took}{waited}")


def worker_env(env=None):
    """The env a worker needs, carried explicitly (`daemon-needs-env-vars`).

    A worker inherits nothing useful from an MCP server's environment, and a missing
    NEO4J_* is not a loud failure — it is a daemon that comes up and writes nothing.
    """
    source = os.environ if env is None else env
    out = dict(source)
    defaults = {
        "NEO4J_URI": source.get("NEO4J_URI", "bolt://host.docker.internal:7687"),
        "NEO4J_USER": source.get("NEO4J_USER", "neo4j"),
        "NEO4J_PASSWORD": source.get("NEO4J_PASSWORD", "password"),
        "HEAVEN_DATA_DIR": source.get("HEAVEN_DATA_DIR", "/tmp/heaven_data"),
        "GITHUB_PAT": source.get("GITHUB_PAT"),
        "REPO_URL": source.get("REPO_URL"),
        "OPENAI_API_KEY": source.get("OPENAI_API_KEY"),
    }
    out.update({k: v for k, v in defaults.items() if v is not None})
    return out


# ---------------------------------------------------------------- thin adapters


def _ps_lines():
    try:
        out = subprocess.run(["ps", "-eo", "pid,args"], capture_output=True, text=True,
                             timeout=10).stdout
        return out.splitlines()[1:]
    except Exception:
        logger.warning("could not list processes", exc_info=True)
        return []


def running_worker_pids(exclude_self=True):
    """The worker PIDs alive right now. Never raises; [] when ps cannot be read."""
    exclude = {os.getpid()} if exclude_self else set()
    return select_worker_pids(_ps_lines(), exclude)


def _alive(pid):
    """True when `pid` can still do work. A ZOMBIE cannot, and is reported dead.

    ⛔ `os.kill(pid, 0)` ALONE IS NOT LIVENESS, and believing it caused a live outage on
    2026-09-01. A process that has been killed but not yet reaped by its parent stays in the
    table as a zombie: it has a pid, it accepts signal 0, and it will never run another
    instruction. `spawn_worker`'s Popen child is exactly that case — whoever spawned it never
    `wait()`s it — so after a SIGTERM that WORKED, `stop_workers` saw the corpse, called it a
    SURVIVOR, and `restart_verdict` refused a restart that had in fact succeeded. Nothing was
    then spawned, and the box was left with no worker at all while the verb reported failure.
    Measured: `ps -o pid,ppid,stat,args -p 52558` → `52558 52432 Zs [python3] <defunct>`.

    That is the same class of defect this module exists to remove, pointing the other way:
    the first version reported success it had not verified, and this reported a failure that
    had not happened. Both come from asking a question whose answer does not mean what it
    looks like.

    ⛔ THE LEADER'S STATE ALONE IS NOT LIVENESS EITHER (card 814, measured 2026-10-04). A
    killed multi-threaded worker shows its LEADER as Z while another thread is still exiting,
    and Linux tears the address space down before it closes the file table, so that thread
    still holds the pid flock. Reading the leader called worker 597 dead, the spawn lost the
    lock and the box was left with no worker. So every thread under /proc/PID/task is read
    and `group_alive` decides.

    The state is read from /proc where there is one. Anywhere else the signal check is all we
    have, and a zombie is not distinguishable this cheaply — so it falls back rather than
    guessing.
    """
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError, PermissionError):
        return False
    try:
        tids = os.listdir(f"/proc/{pid}/task")
    except OSError:
        tids = []
    threads = [s for s in (_proc_state(f"/proc/{pid}/task/{t}/stat") for t in tids) if s]
    return group_alive(_proc_state(f"/proc/{pid}/stat"), threads)


def _proc_state(stat_path):
    """The state letter in a /proc stat file, or None when it cannot be read.

    Field 3 is the state. The comm field before it can contain spaces AND parentheses, so
    the split is on the LAST ')' rather than on whitespace.
    """
    try:
        with open(stat_path) as fh:
            return fh.read().rsplit(")", 1)[1].split()[0]
    except (OSError, IndexError):
        return None


def lock_is_free(pid_file):
    """True when nobody holds the flock on `pid_file`: take it without blocking, let it go.

    Append mode, so probing never truncates a winner's pid (the acquire_pid_lock rule). This
    is the one test of the lock itself: a dying worker's last thread drops its fd table
    before the deferred close releases the flock, so for that last stretch no fd names a
    holder while the lock is still held (card 814, measured).
    """
    handle = open(pid_file, "a")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    finally:
        handle.close()
    return True


def _fd_table(pids=None):
    """Every (pid, fd target) on the box, or of `pids`, read through each THREAD's fd dir.

    Through the threads because a zombie leader's own /proc/PID/fd refuses (EACCES) while
    its other threads still hold the files, the pid flock among them. Unreadable entries
    are skipped.
    """
    if pids is None:
        try:
            pids = [int(p) for p in os.listdir("/proc") if p.isdigit()]
        except OSError:
            return []
    table = set()
    for pid in pids:
        try:
            tids = os.listdir(f"/proc/{pid}/task")
        except OSError:
            continue
        for tid in tids:
            fd_dir = f"/proc/{pid}/task/{tid}/fd"
            try:
                fds = os.listdir(fd_dir)
            except OSError:
                continue
            for fd in fds:
                try:
                    table.add((int(pid), os.readlink(f"{fd_dir}/{fd}")))
                except OSError:
                    continue
    return sorted(table)


def acquire_pid_lock(pid_file, pid=None):
    """Take the worker's exclusive pid lock, WITHOUT truncating the file unless we won it.

    Returns `(handle, True)` when this process owns the lock. THE HANDLE MUST BE KEPT ALIVE
    for the process's lifetime — closing it releases the lock, and a released lock is how two
    workers end up draining the same queue. Returns `(None, False)` when another worker
    already holds it. Anything else propagates, because a lock that could not be ATTEMPTED
    and a lock that was LOST are different facts and the caller reports them differently.

    ⛔ THE ORDER IS THE ENTIRE POINT (issue #276 item 4). Opening with `'w'` truncates AT
    OPEN, which happens BEFORE flock can refuse — so a starter that lost the race had already
    emptied the winner's pid file on its way to exiting gracefully. The file was then empty
    while a healthy worker still held the lock on it, and any reader trusting the pid file
    concluded no worker was running. Append mode never truncates, so a loser leaves the
    contents byte-identical; the winner truncates only once the lock is HELD. `truncate(0)`
    takes an explicit size rather than relying on the file position, which in append mode is
    not where a reader would assume. Same reasoning as the append-mode log handle in
    `spawn_worker` below.
    """
    handle = open(pid_file, "a")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None, False
    except Exception:
        handle.close()
        raise
    handle.truncate(0)
    handle.write(str(os.getpid() if pid is None else pid))
    handle.flush()
    return handle, True


def stop_workers(pids, timeout_s=DEFAULT_STOP_TIMEOUT_S, sleep_fn=None):
    """SIGTERM each pid, then wait for it to actually die. Returns the SURVIVORS.

    Returning survivors rather than a success flag is deliberate: the caller must be able
    to say WHICH process refused to die, because "the restart failed" and "pid 12244 is
    still running your old code" are different pieces of information to act on.
    """
    sleep_fn = sleep_fn or time.sleep
    for pid in pids:
        try:
            os.kill(pid, 15)
        except Exception:
            logger.warning("could not signal worker %s", pid, exc_info=True)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        remaining = [p for p in pids if _alive(p)]
        if not remaining:
            return []
        sleep_fn(0.25)
    return [p for p in pids if _alive(p)]


def spawn_worker(daemon_path, log_path="/tmp/carton_worker.log", env=None):
    """Start one worker from its file path. Returns the pid, or None if it would not start."""
    try:
        proc = subprocess.Popen(
            ["python3", str(daemon_path)],
            env=worker_env(env),
            stdout=open(log_path, "a"),      # APPEND: 'w' truncated the history you need
            stderr=subprocess.STDOUT,        # exactly when a restart has gone wrong
            start_new_session=True)
        return proc.pid
    except Exception:
        logger.error("could not spawn a worker from %s", daemon_path, exc_info=True)
        return None


def restart_worker(daemon_path, log_path="/tmp/carton_worker.log", env=None,
                   grace_s=DEFAULT_START_GRACE_S, sleep_fn=None, pid_file=WORKER_PID_FILE,
                   release_timeout_s=DEFAULT_RELEASE_TIMEOUT_S, find_workers=None):
    """Stop every running worker, start one, and report WHAT HAPPENED.

    `find_workers` lists the workers to stop, the real process table by default; a test
    passes its own so that it can never stop the live worker.
    """
    sleep_fn = sleep_fn or time.sleep
    before = (find_workers or running_worker_pids)()
    began = time.monotonic()
    survivors = stop_workers(before, sleep_fn=sleep_fn)
    stop_s = time.monotonic() - began
    if survivors:
        return restart_verdict(before, survivors, None, False, stop_s=stop_s)
    spawned = spawn_worker(daemon_path, log_path=log_path, env=env)
    # A worker that loses the pid-file lock exits ~immediately, so a liveness check taken
    # the same instant would report a corpse as healthy. Wait, then look.
    sleep_fn(grace_s)
    if spawned and not _alive(spawned):
        return _respawn_after_release(before, spawned, daemon_path, log_path, env, grace_s,
                                      sleep_fn, pid_file, release_timeout_s, stop_s)
    return restart_verdict(before, [], spawned, bool(spawned), stop_s=stop_s)


def _respawn_after_release(before, lost, daemon_path, log_path, env, grace_s, sleep_fn,
                           pid_file, release_timeout_s, stop_s=None):
    """The spawn `lost` exited on the pid lock: name its holders, wait for the lock, spawn again.

    It waits on the LOCK, never on the named holders: a dying worker's last stretch holds
    the flock with no fd left to name it by.
    """
    holders = lock_holders(pid_file, _fd_table(), exclude_pids=(lost,))
    deadline = time.monotonic() + release_timeout_s
    while not lock_is_free(pid_file) and time.monotonic() < deadline:
        sleep_fn(0.25)
    if not lock_is_free(pid_file):
        still = lock_holders(pid_file, _fd_table()) or holders
        return restart_verdict(before, [], lost, False, holders=still)
    spawned = spawn_worker(daemon_path, log_path=log_path, env=env)
    sleep_fn(grace_s)
    if spawned and _alive(spawned):
        return restart_verdict(before, [], spawned, True, waited_for=holders, stop_s=stop_s)
    return restart_verdict(before, [], spawned, False,
                           holders=lock_holders(pid_file, _fd_table()) if spawned else ())
