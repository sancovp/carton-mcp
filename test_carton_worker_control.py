"""Tests for carton_worker_control — worker matching, stopping, restart verdicts (issue #276).

Standalone gate in this repo's script convention (the test_carton_breaker.py /
test_carton_deadletter.py precedent): flat import of the sibling module,
`python3 test_carton_worker_control.py`, one PASS line per test.

THE CENTREPIECE IS THE CONTROLLED PAIR, not the green run. The defect being fixed is a
PATTERN that failed to match reality, so the only test that means anything is one that
runs the OLD pattern and the NEW matcher against the SAME real command lines and shows
them disagreeing. Both command lines below are verbatim from a live `ps` on this box —
the path form measured 2026-09-01, the module form recorded in issue #276's own
measurement — because a matcher tested against invented strings proves only that it
matches the strings its author imagined.
"""

import os

import carton_worker_control as wc

# Verbatim from the real surface. Do not "tidy" these — their exact shape is the test.
PATH_FORM = ("python3 /home/GOD/.pyenv/versions/3.11.6/lib/python3.11/site-packages/"
             "carton_mcp/observation_worker_daemon.py")
MODULE_FORM = "/home/GOD/.pyenv/versions/3.11.6/bin/python3 -m carton_mcp.observation_worker_daemon"

# The pattern the pre-fix code used, at server_fastmcp.py:1348 and :3792.
PRE_FIX_PATTERN = "observation_worker_daemon.py"


def t_the_controlled_pair_the_old_pattern_misses_the_module_form():
    # THE WHOLE BUG, as an assertion. `pkill -f observation_worker_daemon.py` is a substring
    # match on the command line, so this is exactly what the shell was doing.
    assert PRE_FIX_PATTERN in PATH_FORM, "sanity: the old pattern did match the path form"
    assert PRE_FIX_PATTERN not in MODULE_FORM, \
        "sanity: the old pattern must MISS the module form — that is the defect"

    # ...and the new matcher catches both.
    assert wc.is_worker_command(PATH_FORM), "the new matcher must match the path form"
    assert wc.is_worker_command(MODULE_FORM), \
        "the new matcher must match the MODULE form — the case the old pattern missed"
    print("  MARKER: CONTROLLED_PAIR_OLD_PATTERN_MISSES_MODULE_FORM_OK")


def t_matcher_rejects_things_that_are_not_workers():
    for junk in ("", None, "python3 -m carton_mcp.server_fastmcp",
                 "tail -f /tmp/carton_worker.log",
                 "python3 test_carton_worker_control.py"):
        assert not wc.is_worker_command(junk), f"matched a non-worker: {junk!r}"
    print("  MARKER: MATCHER_REJECTS_NON_WORKERS_OK")


def t_select_pids_parses_real_ps_output_and_excludes_self():
    lines = [
        f"  13198 {PATH_FORM}",
        f"  40021 {MODULE_FORM}",
        "  99999 python3 -m carton_mcp.server_fastmcp",
        "   4242 [kworker/0:1]",
        "garbage-with-no-pid",
        "",
    ]
    assert wc.select_worker_pids(lines) == [13198, 40021]
    # excluding by IDENTITY is how the caller keeps itself out — the self-match problem
    # solved without a pattern trick
    assert wc.select_worker_pids(lines, exclude_pids=(13198,)) == [40021]
    assert wc.select_worker_pids([]) == []
    assert wc.select_worker_pids(None) == []
    print("  MARKER: SELECT_PIDS_PARSES_AND_EXCLUDES_OK")


def t_verdict_refuses_to_call_it_a_restart_when_the_old_worker_survived():
    # THE HEADLINE FAILURE OF #276: the kill matched nothing, so the old worker kept running
    # its old code while the verb printed a tick. This must be impossible to report as success.
    ok, msg = wc.restart_verdict([12244], [12244], 91559, True)
    assert ok is False, "a surviving old worker is NOT a successful restart"
    assert "12244" in msg, "it must NAME the survivor so it can be killed by pid"
    assert "NOT what is running" in msg
    print("  MARKER: VERDICT_REFUSES_ON_SURVIVOR_OK")


def t_verdict_refuses_when_the_replacement_died_on_the_pid_lock():
    # The OTHER half of #276: the spawned worker exits 0 by design when another holds the
    # pid-file lock, and the old code reported the pid it had handed to Popen regardless.
    ok, msg = wc.restart_verdict([12244], [], 91559, False)
    assert ok is False
    assert "91559" in msg and "already gone" in msg
    assert "pid-file lock" in msg, "the message must say WHY a fresh pid vanishes"
    print("  MARKER: VERDICT_REFUSES_ON_DEAD_REPLACEMENT_OK")


def t_verdict_refuses_when_nothing_was_spawned():
    ok, msg = wc.restart_verdict([12244], [], None, False)
    assert ok is False and "no replacement worker was spawned" in msg
    print("  MARKER: VERDICT_REFUSES_ON_NO_SPAWN_OK")


def t_verdict_reports_success_only_with_evidence_on_both_sides():
    ok, msg = wc.restart_verdict([12244], [], 91559, True)
    assert ok is True
    assert "91559" in msg and "is alive" in msg
    assert "12244" in msg, "it reports WHICH old worker it stopped, not just how many"
    print("  MARKER: VERDICT_SUCCESS_NEEDS_EVIDENCE_OK")


def t_worker_env_carries_what_a_daemon_cannot_inherit():
    # `daemon-needs-env-vars`: a worker started without NEO4J_* comes up and writes nothing,
    # which is not a loud failure. Defaults must be present; absent optionals must not be
    # injected as the literal None that would break subprocess.
    env = wc.worker_env(env={"PATH": "/usr/bin"})
    assert env["NEO4J_URI"] == "bolt://host.docker.internal:7687"
    assert env["NEO4J_USER"] == "neo4j" and env["NEO4J_PASSWORD"] == "password"
    assert env["HEAVEN_DATA_DIR"] == "/tmp/heaven_data"
    assert env["PATH"] == "/usr/bin", "the caller's own env survives"
    assert "GITHUB_PAT" not in env, "an absent optional must not appear at all"
    assert all(v is not None for v in env.values()), "no None may reach subprocess"
    # an explicit value is never overridden by the default
    assert wc.worker_env(env={"NEO4J_URI": "bolt://elsewhere:7687"})["NEO4J_URI"] \
        == "bolt://elsewhere:7687"
    print("  MARKER: WORKER_ENV_CARRIES_DEFAULTS_OK")


def t_stop_reports_the_survivor_rather_than_claiming_success():
    # A pid that will not die must come back as a SURVIVOR, not be silently accepted. Uses
    # pid 1, which exists and cannot be killed from here — a real unkillable process rather
    # than a mock that agrees with itself.
    survivors = wc.stop_workers([1], timeout_s=0.5, sleep_fn=lambda _s: None)
    assert survivors == [1], f"an unkillable pid must be reported as a survivor: {survivors}"
    # and an empty list is trivially satisfied
    assert wc.stop_workers([], sleep_fn=lambda _s: None) == []
    print("  MARKER: STOP_REPORTS_SURVIVOR_OK")


def t_a_zombie_is_not_alive_and_is_not_a_survivor():
    # A REAL zombie, made on purpose — not a mock that agrees with itself. A child that has
    # exited and has NOT been wait()ed keeps its pid and still answers os.kill(pid, 0).
    # Believing that answer left this box with NO worker on 2026-09-01: the SIGTERM had
    # worked, stop_workers read the corpse as a SURVIVOR, and restart_verdict refused a
    # restart that had already succeeded — so nothing was spawned.
    import subprocess
    import time

    child = subprocess.Popen(["true"])
    try:
        for _ in range(100):                       # let it exit; deliberately do NOT reap it
            try:
                with open(f"/proc/{child.pid}/stat") as fh:
                    if fh.read().rsplit(")", 1)[1].split()[0] == "Z":
                        break
            except OSError:
                pass
            time.sleep(0.02)
        else:
            raise AssertionError("could not produce a zombie to test against")

        os.kill(child.pid, 0)   # the OLD check: does NOT raise on a zombie — that IS the trap
        assert wc._alive(child.pid) is False, "a zombie must not be reported alive"
        assert wc.stop_workers([child.pid], timeout_s=0.5, sleep_fn=lambda _s: None) == [], \
            "a zombie must not be reported as a survivor that refused to die"
    finally:
        child.wait()            # reap it, so this test leaves nothing behind
    print("  MARKER: ZOMBIE_IS_NOT_ALIVE_OK")


def t_running_worker_pids_reads_the_real_process_table_without_matching_itself():
    # Runs the REAL ps. It must never return this test's own pid — that is the self-match
    # failure `pkill -f` has by construction and this design does not.
    pids = wc.running_worker_pids()
    assert isinstance(pids, list)
    assert os.getpid() not in pids, "the caller must never match itself"
    print(f"  MARKER: RUNNING_WORKER_PIDS_OK (live workers: {pids})")


def _assert_imports_what_it_calls(consumer, label):
    """The import-consistency rule, applied to ONE consumer of this module.

    EXTRACTED rather than copied when the second consumer arrived. Two copies of a guard
    drift, and a guard that has drifted is worse than no guard at all, because it still
    reports green — which is precisely the failure this rule exists to catch. Same shape as
    the helper in test_carton_deadletter.py.

    Reads the INSTALLED consumer on purpose: a source edit that was never pip-installed is
    exactly the state in which py_compile, every suite and a live proof are all green while
    the running system has none of the change.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(consumer))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "carton_mcp.carton_worker_control":
            imported |= {a.name for a in node.names}
    assert imported, f"the {label} imports nothing from carton_worker_control — wiring is gone"
    for name in sorted(imported):
        assert hasattr(wc, name), \
            f"the {label} imports {name!r}, which this module does not define"

    defined_here = {n for n in dir(wc) if not n.startswith("_") and callable(getattr(wc, n))
                    and getattr(getattr(wc, n), "__module__", None) == wc.__name__}
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    missing = (called & defined_here) - imported
    assert not missing, f"the {label} calls {sorted(missing)} without importing them"


def t_the_mcp_server_imports_every_symbol_it_calls_from_this_module():
    # Same import-consistency rule the dead-letter suite pins, applied to this module's
    # consumer. It exists because a symbol was once called from the daemon without being
    # imported while py_compile, the suites and a live proof were all green.
    import carton_mcp.server_fastmcp as server
    _assert_imports_what_it_calls(server, "MCP server")
    print("  MARKER: MCP_SERVER_IMPORTS_WHAT_IT_CALLS_OK")


def _pre_fix_acquire(pid_file, pid=None):
    """The pre-change pid-lock acquisition, VERBATIM from observation_worker_daemon.py.

    Kept here so the pair is a real comparison and not a description of one. The entire
    defect is the ORDER of the first two statements: `'w'` truncates AT OPEN, which happens
    before flock is ever called, so a loser has already emptied the file when it is refused.
    """
    import fcntl as _fcntl
    handle = open(pid_file, 'w')                                        # ← truncates, always
    _fcntl.flock(handle.fileno(), _fcntl.LOCK_EX | _fcntl.LOCK_NB)      # ← refuses, too late
    handle.write(str(os.getpid() if pid is None else pid))
    handle.flush()
    return handle, True


def t_the_controlled_pair_a_losing_starter_does_not_blank_the_pid_file():
    # THE WHOLE OF ISSUE #276 ITEM 4. A REAL flock on a REAL file, held by a REAL second file
    # description — flock treats separate open() calls independently even within one process,
    # so this is a genuine lock contest and not two mocks agreeing with each other.
    import fcntl
    import tempfile
    WINNER = "12244"

    def _held_by_a_winner(path):
        h = open(path, "w")
        h.write(WINNER)
        h.flush()
        fcntl.flock(h.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return h

    with tempfile.TemporaryDirectory() as tmp:
        pid_path = os.path.join(tmp, "carton_worker.pid")

        # PRE-FIX: the loser destroys the winner's pid on its way to being refused.
        winner = _held_by_a_winner(pid_path)
        try:
            try:
                _pre_fix_acquire(pid_path, pid=99999)
            except BlockingIOError:
                pass  # exactly what the daemon caught, and it exited 0 right here
            with open(pid_path) as f:
                assert f.read() == "", \
                    "pre-fix must have BLANKED the file — that is the defect being fixed"
        finally:
            winner.close()

        # FIXED: the loser is refused and changes nothing.
        winner = _held_by_a_winner(pid_path)
        try:
            handle, acquired = wc.acquire_pid_lock(pid_path, pid=99999)
            assert acquired is False and handle is None, "the loser must not claim the lock"
            with open(pid_path) as f:
                assert f.read() == WINNER, \
                    "the loser must leave the winner's pid BYTE-IDENTICAL"
        finally:
            winner.close()
    print("  MARKER: CONTROLLED_PAIR_LOSER_DOES_NOT_BLANK_OK")


def t_the_winner_replaces_stale_content_and_actually_holds_the_lock():
    # The other half: append mode must not mean APPEND. Stale content from a previous run has
    # to be replaced, which is what truncate(0)-after-lock does, and the lock has to really
    # exclude — a fix that stopped truncating but also stopped locking would pass the pair
    # above and be far worse.
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        pid_path = os.path.join(tmp, "carton_worker.pid")
        with open(pid_path, "w") as f:
            f.write("999999999")          # a stale pid from a previous worker

        handle, acquired = wc.acquire_pid_lock(pid_path, pid=4242)
        try:
            assert acquired is True and handle is not None
            with open(pid_path) as f:
                assert f.read() == "4242", "the winner must REPLACE stale content, not append"
            h2, a2 = wc.acquire_pid_lock(pid_path, pid=5150)
            assert a2 is False and h2 is None, "the held lock must actually exclude"
            with open(pid_path) as f:
                assert f.read() == "4242", "and that loser still changes nothing"
        finally:
            handle.close()
    print("  MARKER: WINNER_REPLACES_AND_HOLDS_OK")


def t_the_daemon_imports_every_symbol_it_calls_from_this_module():
    # The same rule as the server case above, applied to the OTHER consumer — through the
    # SAME helper, so the two can never drift apart. This is the case that would have caught
    # acquire_pid_lock being called from the daemon without being imported.
    import carton_mcp.observation_worker_daemon as daemon
    _assert_imports_what_it_calls(daemon, "daemon")
    print("  MARKER: DAEMON_IMPORTS_WHAT_IT_CALLS_OK")


# ---------------------------------------------------------------- card 814 (issue 1294)
# On 2026-10-04 one restart_bg_server call left the box with NO worker: stop_workers called
# worker 597 dead while its pid flock was still held, the spawn exited on that lock, and
# nothing spawned again. The pairs below reproduce the mechanism with a real dying process.


def _leader_only_alive(pid):
    """The pre-card-814 _alive, VERBATIM: it read the thread-group leader and nothing else."""
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError, PermissionError):
        return False
    try:
        with open(f"/proc/{pid}/stat") as fh:
            state = fh.read().rsplit(")", 1)[1].split()[0]
        return state != "Z"
    except (OSError, IndexError):
        return True


def _leader_fd_names(pid, path):
    """True when the LEADER's own /proc/PID/fd lists `path`, the walk a naive fd table does."""
    target = os.path.realpath(path)
    try:
        fds = os.listdir(f"/proc/{pid}/fd")
    except OSError:
        return False
    for fd in fds:
        try:
            if os.readlink(f"/proc/{pid}/fd/{fd}") == target:
                return True
        except OSError:
            continue
    return False


def _lock_is_free(path):
    import fcntl
    h = open(path, "a")
    try:
        fcntl.flock(h.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(h.fileno(), fcntl.LOCK_UN)
        return True
    except BlockingIOError:
        return False
    finally:
        h.close()


# A worker's shape: the pid flock, a touched heap and a dozen threads.
_DYING_WORKER = r'''
import fcntl, sys, threading, time
h = open(sys.argv[1], "a")
fcntl.flock(h.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
heap = [bytearray(1 << 20) for _ in range(int(sys.argv[2]))]
for b in heap:
    b[::4096] = b"x" * len(b[::4096])
for _ in range(12):
    threading.Thread(target=time.sleep, args=(1000,), daemon=True).start()
print("ready", flush=True)
time.sleep(1000)
'''

# A held zombie leader: the main thread makes the raw exit syscall (ctypes releases the GIL
# for the call), so the leader turns Z while the other thread lives on holding the flock.
_ZOMBIE_LEADER = r'''
import ctypes, fcntl, platform, sys, threading, time
h = open(sys.argv[1], "a")
fcntl.flock(h.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
threading.Thread(target=time.sleep, args=(1000,), daemon=True).start()
print("ready", flush=True)
ctypes.CDLL(None).syscall({"x86_64": 60, "aarch64": 93}[platform.machine()], 0)
'''

# Holds the pid lock for argv[2] seconds, matching no worker launch form.
_LOCK_HOLDER = r'''
import fcntl, sys, time
h = open(sys.argv[1], "a")
fcntl.flock(h.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
print("ready", flush=True)
time.sleep(float(sys.argv[2]))
'''

# The daemon's own lock install, against a scratch pid file: a loser exits 0, a winner stays.
_FAKE_DAEMON = '''
import sys, time
sys.path.insert(0, {moddir!r})
import carton_worker_control as wc
handle, acquired = wc.acquire_pid_lock({pid_file!r})
if not acquired:
    sys.exit(0)
time.sleep(60)
'''


def t_group_alive_counts_every_thread_not_the_leader_alone():
    assert wc.group_alive("Z", ["Z", "R"]) is True, (
        "INVARIANT a zombie leader with a thread still running is alive, because that thread "
        "still holds the pid flock. FIX group_alive answers True while any thread state is "
        "neither Z nor X")
    assert wc.group_alive("Z", ["Z", "Z"]) is False, (
        "INVARIANT a group whose every thread is a zombie is dead, so a reaped-late worker is "
        "never a survivor. FIX group_alive answers False when every thread is Z or X")
    assert wc.group_alive("Z", ["X", "Z"]) is False, "INVARIANT X is dead like Z"
    assert wc.group_alive("S", ["S", "S"]) is True, "INVARIANT a sleeping worker is alive"
    assert wc.group_alive("Z", []) is False, (
        "INVARIANT with no thread readable the leader decides: a zombie leader is dead. "
        "FIX group_alive falls back to the leader state")
    assert wc.group_alive(None, []) is True, (
        "INVARIANT with nothing readable the signal check already said alive, so it stays "
        "alive. FIX group_alive treats an unreadable leader as alive")
    print("  MARKER: GROUP_ALIVE_COUNTS_EVERY_THREAD_OK")


def t_the_controlled_pair_a_dying_worker_holds_its_lock_until_its_last_thread():
    # THE WHOLE OF CARD 814, as a measurement. One SIGTERMed child, sampled on the same
    # instants by the leader-only check (verbatim, above) and by wc._alive. A sample counts
    # only when the lock is STILL held after both readings, so it was held during them.
    import signal
    import subprocess
    import sys
    import tempfile
    import time

    with tempfile.TemporaryDirectory() as tmp:
        pid_path = os.path.join(tmp, "carton_worker.pid")
        for kill in range(1, 6):
            child = subprocess.Popen([sys.executable, "-c", _DYING_WORKER, pid_path, "300"],
                                     stdout=subprocess.PIPE, text=True)
            samples = old_dead = new_dead = named = leader_named = 0
            try:
                assert child.stdout.readline().strip() == "ready"
                os.kill(child.pid, signal.SIGTERM)
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    new_says_dead = not wc._alive(child.pid)
                    old_says_dead = not _leader_only_alive(child.pid)
                    holders = (wc.lock_holders(pid_path, wc._fd_table(pids=[child.pid]))
                               if old_says_dead else [])
                    via_leader = old_says_dead and _leader_fd_names(child.pid, pid_path)
                    if _lock_is_free(pid_path):
                        break
                    samples += 1
                    new_dead += new_says_dead
                    if old_says_dead:
                        old_dead += 1
                        named += child.pid in holders
                        leader_named += via_leader
            finally:
                if child.poll() is None:
                    child.kill()
                child.wait()
            if old_dead:
                break
        else:
            raise AssertionError(
                "could not open the zombie-leader window in 5 kills: the leader-only check "
                "never read dead while the lock was held, so this run decided nothing")

    assert new_dead == 0, (
        f"INVARIANT _alive answers alive while any thread of a dying worker still holds the "
        f"pid lock, so stop_workers never calls it dead early: _alive read dead in {new_dead} "
        f"of {samples} samples with the lock held. FIX _alive passes every state under "
        f"/proc/PID/task to group_alive")
    # Naming is reported, not asserted, here: whether a sample lands while the exiting thread
    # still has its fds is a race (38 of 202 in one run, 0 of 186 in the next). The last
    # stretch drops the fd table before the deferred close frees the flock, which is why the
    # restart waits on lock_is_free. The naming invariant is pinned on a held fixture below.
    print(f"  MARKER: ZOMBIE_LEADER_PAIR_OK (kill {kill}: {samples} samples with the lock held; "
          f"leader-only dead in {old_dead}, _alive dead in {new_dead}; holder named through the "
          f"threads in {named}, through the leader in {leader_named})")


def t_a_held_zombie_leader_is_alive_and_named_through_its_threads():
    # The state the restart misread, HELD still: the main thread makes the raw exit syscall,
    # so the leader is a zombie while its other thread lives on holding the flock. No race.
    import signal
    import subprocess
    import sys
    import tempfile
    import time

    with tempfile.TemporaryDirectory() as tmp:
        pid_path = os.path.join(tmp, "carton_worker.pid")
        child = subprocess.Popen([sys.executable, "-c", _ZOMBIE_LEADER, pid_path],
                                 stdout=subprocess.PIPE, text=True)
        try:
            assert child.stdout.readline().strip() == "ready"
            for _ in range(200):
                if wc._proc_state(f"/proc/{child.pid}/stat") == "Z":
                    break
                time.sleep(0.01)
            else:
                raise AssertionError("could not hold a zombie leader to test against")
            assert not _lock_is_free(pid_path), "sanity: the live thread still holds the flock"
            assert _leader_only_alive(child.pid) is False, (
                "sanity: the leader-only check reads this holder dead — the card 814 defect")
            assert wc._alive(child.pid) is True, (
                "INVARIANT a zombie leader whose thread still runs and holds the pid lock is "
                "alive, so stop_workers waits for it. FIX _alive asks group_alive over every "
                "/proc/PID/task state")
            assert not _leader_fd_names(child.pid, pid_path), (
                "sanity: the zombie leader's own /proc/PID/fd cannot name the holder")
            assert child.pid in wc.lock_holders(pid_path, wc._fd_table(pids=[child.pid])), (
                "INVARIANT lock_holders over _fd_table names a holder whose leader is a "
                "zombie, where the leader's own fd dir cannot. FIX _fd_table reads "
                "/proc/PID/task/TID/fd")
            assert child.pid in wc.lock_holders(pid_path, wc._fd_table()), (
                "INVARIANT the whole-box walk names it too. FIX _fd_table with no pids walks "
                "every /proc/PID")
        finally:
            os.kill(child.pid, signal.SIGKILL)
            child.wait()
    print("  MARKER: HELD_ZOMBIE_LEADER_ALIVE_AND_NAMED_OK")


def t_lock_holders_names_every_pid_that_holds_the_pid_file():
    pid_file = "/tmp/carton_worker.pid"
    table = [(597, pid_file), (597, pid_file), (612, "/tmp/other.log"), (94179, pid_file),
             (700, "/tmp/carton_worker.pid.bak")]
    got = wc.lock_holders(pid_file, table)
    assert got == [597, 94179], (
        f"INVARIANT lock_holders returns each pid holding the pid file once, sorted, and no "
        f"pid holding another file: got {got}. FIX lock_holders compares each fd target with "
        f"the real path of the pid file and dedupes")
    assert wc.lock_holders(pid_file, table, exclude_pids=(94179,)) == [597], (
        "INVARIANT exclude_pids keeps the caller's own spawn out. FIX lock_holders drops them")
    assert wc.lock_holders(pid_file, []) == []
    print("  MARKER: LOCK_HOLDERS_NAMES_THE_HOLDERS_OK")


def t_fd_table_reads_the_real_process_table():
    import fcntl
    import tempfile

    me = os.getpid()
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "carton_worker.pid")
        h = open(path, "a")
        fcntl.flock(h.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            assert me in wc.lock_holders(path, wc._fd_table()), (
                "INVARIANT the whole-box fd table shows this process holding the file it locked. "
                "FIX _fd_table walks every /proc/PID/task/TID/fd and yields (pid, target)")
            assert me in wc.lock_holders(path, wc._fd_table(pids=[me])), (
                "INVARIANT pids narrows the walk without losing a holder. FIX _fd_table(pids)")
        finally:
            h.close()
        assert me not in wc.lock_holders(path, wc._fd_table(pids=[me])), (
            "INVARIANT a closed file is held by nobody")
    print("  MARKER: FD_TABLE_READS_THE_REAL_TABLE_OK")


def t_verdict_names_the_lock_holders_and_whom_it_waited_for():
    ok, msg = wc.restart_verdict([597], [], 94179, False, holders=[597])
    assert ok is False, "INVARIANT a spawn that lost the pid lock is not a restart"
    assert "597" in msg and "94179" in msg, (
        f"INVARIANT the verdict names the spawn that lost and the pid holding the lock, so the "
        f"agent can act on that pid: {msg!r}. FIX restart_verdict names holders")
    assert "no worker" in msg.lower(), (
        f"INVARIANT the verdict says no worker this call started drains the queue: {msg!r}. "
        f"FIX restart_verdict says so when holders is non-empty")
    ok, msg = wc.restart_verdict([597], [], 97948, True, waited_for=[597])
    assert ok is True and "97948" in msg, "INVARIANT a live respawn is a restart"
    assert "597" in msg and "waited" in msg, (
        f"INVARIANT a success after waiting says whom it waited for: {msg!r}. FIX "
        f"restart_verdict names waited_for")
    print("  MARKER: VERDICT_NAMES_HOLDERS_AND_WAITED_FOR_OK")


def t_restart_waits_for_the_lock_holder_and_spawns_again():
    # The restart itself, end to end on a scratch pid file. find_workers is empty, so this
    # case can never stop the live worker; the holder is a process no launch form matches,
    # exactly what stop_workers cannot see.
    import subprocess
    import sys
    import tempfile

    moddir = os.path.dirname(os.path.abspath(wc.__file__))
    with tempfile.TemporaryDirectory() as tmp:
        pid_file = os.path.join(tmp, "carton_worker.pid")
        daemon = os.path.join(tmp, "fake_daemon.py")
        with open(daemon, "w") as f:
            f.write(_FAKE_DAEMON.format(moddir=moddir, pid_file=pid_file))
        holder = subprocess.Popen([sys.executable, "-c", _LOCK_HOLDER, pid_file, "3"],
                                  stdout=subprocess.PIPE, text=True)
        now = []
        try:
            assert holder.stdout.readline().strip() == "ready"
            ok, msg = wc.restart_worker(daemon, log_path=os.path.join(tmp, "worker.log"),
                                        grace_s=0.5, pid_file=pid_file, release_timeout_s=15,
                                        find_workers=lambda: [])
            now = [p for p in wc.lock_holders(pid_file, wc._fd_table()) if p != holder.pid]
            assert ok is True, (
                f"INVARIANT one restart call ends with a live worker when the pid lock is held "
                f"by a process that lets go: got {msg!r}. FIX restart_worker waits for the "
                f"holders of pid_file to release it, then spawns once more")
            assert str(holder.pid) in msg, (
                f"INVARIANT the verdict names the holder it waited for, pid {holder.pid}: "
                f"{msg!r}. FIX the respawn verdict carries waited_for")
            assert now, (
                "INVARIANT after the call a worker holds the pid lock. FIX the respawn uses the "
                "same daemon file and pid file")
        finally:
            if holder.poll() is None:
                holder.kill()
            holder.wait()
            for pid in now:
                try:
                    os.kill(pid, 9)
                except OSError:
                    pass
    print("  MARKER: RESTART_WAITS_FOR_THE_HOLDER_OK")


def t_the_daemon_locks_the_one_pid_file_a_restart_reads():
    # A restart names holders of WORKER_PID_FILE; that only means anything if the daemon
    # locks that same file. Reads the INSTALLED daemon, like the import cases above.
    import ast
    import inspect
    import carton_mcp.observation_worker_daemon as daemon

    tree = ast.parse(inspect.getsource(daemon))
    literals = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and n.value == "/tmp/carton_worker.pid"]
    assert not literals, (
        "INVARIANT the daemon's pid lock path has one name, WORKER_PID_FILE, which a restart "
        "reads the holders of: the installed daemon still spells /tmp/carton_worker.pid itself. "
        "FIX the daemon imports WORKER_PID_FILE from carton_worker_control and locks it")
    assert "WORKER_PID_FILE" in {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
                                 and n.module == "carton_mcp.carton_worker_control"
                                 for a in n.names}, (
        "INVARIANT the daemon imports WORKER_PID_FILE. FIX import it beside acquire_pid_lock")
    print("  MARKER: DAEMON_LOCKS_THE_ONE_PID_FILE_OK")


TESTS = [
    t_group_alive_counts_every_thread_not_the_leader_alone,
    t_the_controlled_pair_a_dying_worker_holds_its_lock_until_its_last_thread,
    t_a_held_zombie_leader_is_alive_and_named_through_its_threads,
    t_lock_holders_names_every_pid_that_holds_the_pid_file,
    t_fd_table_reads_the_real_process_table,
    t_verdict_names_the_lock_holders_and_whom_it_waited_for,
    t_restart_waits_for_the_lock_holder_and_spawns_again,
    t_the_daemon_locks_the_one_pid_file_a_restart_reads,
    t_the_controlled_pair_the_old_pattern_misses_the_module_form,
    t_the_controlled_pair_a_losing_starter_does_not_blank_the_pid_file,
    t_the_winner_replaces_stale_content_and_actually_holds_the_lock,
    t_the_daemon_imports_every_symbol_it_calls_from_this_module,
    t_matcher_rejects_things_that_are_not_workers,
    t_select_pids_parses_real_ps_output_and_excludes_self,
    t_verdict_refuses_to_call_it_a_restart_when_the_old_worker_survived,
    t_verdict_refuses_when_the_replacement_died_on_the_pid_lock,
    t_verdict_refuses_when_nothing_was_spawned,
    t_verdict_reports_success_only_with_evidence_on_both_sides,
    t_worker_env_carries_what_a_daemon_cannot_inherit,
    t_stop_reports_the_survivor_rather_than_claiming_success,
    t_a_zombie_is_not_alive_and_is_not_a_survivor,
    t_running_worker_pids_reads_the_real_process_table_without_matching_itself,
    t_the_mcp_server_imports_every_symbol_it_calls_from_this_module,
]

if __name__ == "__main__":
    failed = 0
    for t in TESTS:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except Exception as e:
            failed += 1
            import traceback
            print(f"  FAIL  {t.__name__}: {e}")
            traceback.print_exc()
    print(f"\nall {len(TESTS)} passed" if not failed else f"\n{failed}/{len(TESTS)} FAILED")
    raise SystemExit(1 if failed else 0)
