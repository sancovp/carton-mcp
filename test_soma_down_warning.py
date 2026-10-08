"""Issue #865: the warning add_concept_tool logs when SOMA refuses names the one sanctioned restart.

Run as a script from this directory, one MARKER line per test. Nothing here POSTs to SOMA: the
pure cases take their inputs as arguments, and the real-path case points SOMA_URL at a port that
nothing listens on.
"""

import os
import subprocess
import sys

import add_concept_tool as act

SCRIPT = act.RESTART_SOMA_SCRIPT
BARE_START = "python3 -m soma_prolog.api"


def t_url_is_local():
    assert act.soma_url_is_local("http://localhost:8091/event")
    assert act.soma_url_is_local("http://127.0.0.1:1/event")
    assert not act.soma_url_is_local("http://soma-container:8091/event")
    print("  MARKER: URL_IS_LOCAL_OK")


def t_argv_port():
    py = "/usr/bin/python3"
    assert act.soma_argv_port([py, "-m", "soma_prolog.api", "--port", "8091", ""]) == 8091
    assert act.soma_argv_port([py, "-m", "soma_prolog.api", "--port=8095"]) == 8095
    assert act.soma_argv_port([py, "-m", "soma_prolog.api"]) == 8091
    assert act.soma_argv_port(["bash", "-c", "python3 -m soma_prolog.api --port 8091"]) is None
    assert act.soma_argv_port([py, "-m", "carton_mcp.observation_worker_daemon"]) is None
    print("  MARKER: ARGV_PORT_OK")


def t_no_process_says_run_the_restart_now():
    text = act.soma_down_warning("http://127.0.0.1:8091/event", [])
    assert f"bash {SCRIPT}" in text and "NOW, in the background" in text, text
    assert "sophia-status" in text and "reads UP" in text and "issue 687" in text, text
    assert "http://127.0.0.1:8091/event" in text and BARE_START not in text, text
    print("  MARKER: NO_PROCESS_RUN_RESTART_NOW_OK")


def t_live_process_says_do_not_restart_now():
    text = act.soma_down_warning("http://127.0.0.1:8091/event", ["59845"])
    assert "pid 59845" in text and "Do NOT restart it now" in text, text
    assert "sophia-status" in text and f"bash {SCRIPT} in the background" in text, text
    assert BARE_START not in text, text
    print("  MARKER: LIVE_PROCESS_DO_NOT_RESTART_OK")


def t_remote_url_says_restart_where_it_runs():
    text = act.soma_down_warning("http://soma-container:8091/event", None)
    assert "names another host" in text and "the host that runs it" in text, text
    assert SCRIPT not in text and BARE_START not in text, text
    print("  MARKER: REMOTE_RESTART_WHERE_IT_RUNS_OK")


def t_nothing_serves_a_dead_port():
    assert act.local_soma_pids(1) == []
    print("  MARKER: DEAD_PORT_HAS_NO_PROCESS_OK")


def t_real_import_path_prints_the_restart():
    env = dict(os.environ, SOMA_URL="http://127.0.0.1:1/event")
    run = subprocess.run([sys.executable, "-c", "import add_concept_tool"], env=env,
                         cwd=os.path.dirname(os.path.abspath(__file__)),
                         capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr
    assert "SOMA DOES NOT ANSWER at http://127.0.0.1:1/event" in run.stderr, run.stderr
    assert f"bash {SCRIPT}" in run.stderr and "sophia-status" in run.stderr, run.stderr
    assert BARE_START not in run.stderr, run.stderr
    print("  MARKER: REAL_IMPORT_PATH_PRINTS_RESTART_OK")


if __name__ == "__main__":
    tests = [t_url_is_local, t_argv_port, t_no_process_says_run_the_restart_now,
             t_live_process_says_do_not_restart_now, t_remote_url_says_restart_where_it_runs,
             t_nothing_serves_a_dead_port, t_real_import_path_prints_the_restart]
    for t in tests:
        t()
    print(f"ALL {len(tests)} PASS")
