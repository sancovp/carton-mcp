---
name: skill-carton-daemon-restart
description: "WHAT: how to diagnose and restart the CartON observation worker daemon when it dies — check the worker log for the crash reason and relaunch the daemon with the required Neo4j env vars. WHEN: when ps aux shows no observation_worker process, carton_management says the daemon is off, queued observations stop being processed, or _ensure_daemon_running fails."
---

'''Restart the CartON observation worker daemon when it dies. Check /tmp/carton_worker.log for crash reason. Common issue: GITHUB_PAT/REPO_URL env vars missing (now optional). Launch manually with NEO4J env vars if _ensure_daemon_running() fails.''' '''Replayable skill pattern - context+action''' '''System infrastructure — daemons '''Skill category classification''' '''Personal domain category enum for observation tagging''' '''System infrastructure management''' '''Starting '''How to diagnose and restart the CartON observation worker daemon''' '''When ps aux shows no observation_worker process or carton_management says daemon is off''' '''A running observation_worker_daemon.py process with Neo4j connection'''

---
## Skill Contents

- `reference.md` — detailed reference (read for full docs)
