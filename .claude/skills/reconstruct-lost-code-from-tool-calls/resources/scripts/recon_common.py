#!/usr/bin/env python3
"""Shared run config and read-only git helpers for the lost-code reconstruction scripts.

Every script reads ONE run config: the JSON file named by the RECON_CONFIG environment variable, shaped
like ../specifics_template.json. Git is read with show, log, grep and cat-file only; neo4j is opened
READ_ACCESS. Outputs go under the config's out_dir (raw/ holds the intermediate data), and everything a
script prints is ALSO kept in raw/<script>.out — a shell redirect is refused by the bash file guard, so
the scripts keep their own record."""
import atexit
import json
import os
import re
import subprocess
import sys


def load_config():
    path = os.environ.get("RECON_CONFIG")
    if not path:
        sys.exit("RECON_CONFIG is not set: export RECON_CONFIG=<run dir>/recon_config.json "
                 "(its shape is resources/specifics_template.json)")
    with open(path) as f:
        cfg = json.load(f)
    missing = [k for k in ("repo", "path_regex", "from", "to", "out_dir") if not cfg.get(k)]
    if missing:
        sys.exit(f"{path} lacks {missing}")
    return cfg


CFG = load_config()
REPO = CFG["repo"].rstrip("/")
PREFIX = REPO + "/"
PATH_RX = re.compile(CFG["path_regex"])
FROM, TO = CFG["from"], CFG["to"]
ALIASES = [tuple(a) for a in CFG.get("path_aliases", [])]
TRANSCRIPTS_ROOT = CFG.get("transcripts_root", "/home/GOD/.claude/projects")
ROOT = CFG["out_dir"].rstrip("/")
RAW = os.path.join(ROOT, "raw")
os.makedirs(RAW, exist_ok=True)
MINLEN = 8
LOST = {"COMMITTED_THEN_LOST", "NEVER_COMMITTED", "PARTIAL", "DELETION_NOT_IN_HEAD"}


def raw(name):
    return os.path.join(RAW, name)


class _Tee:
    def __init__(self, stream, path):
        self.stream, self.file = stream, open(path, "w")

    def write(self, s):
        self.stream.write(s)
        self.file.write(s)
        return len(s)

    def flush(self):
        self.stream.flush()
        self.file.flush()


def _keep_printed_output():
    script = os.path.splitext(os.path.basename(getattr(sys.modules.get("__main__"), "__file__", "") or ""))[0]
    if script:
        sys.stdout = _Tee(sys.stdout, raw(script + ".out"))
        atexit.register(sys.stdout.flush)


_keep_printed_output()


def in_window(ts):
    return bool(ts) and FROM <= ts[:10] <= TO


def transcript_start():
    """Earliest timestamp in any transcript, written by extract_transcripts.py."""
    meta = raw("transcripts_meta.json")
    if not os.path.exists(meta):
        sys.exit(f"{meta} is absent: run extract_transcripts.py first")
    return json.load(open(meta))["earliest"]


def neo4j_driver():
    from neo4j import GraphDatabase
    return GraphDatabase.driver(os.environ.get("NEO4J_URI", "bolt://host.docker.internal:7687"),
                                auth=(os.environ.get("NEO4J_USER", "neo4j"),
                                      os.environ.get("NEO4J_PASSWORD", "password")))


def git(*args, check=False):
    p = subprocess.run(["git", "-C", REPO, *args], capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(p.stderr)
    return p


def norm(s):
    return re.sub(r"\s+", " ", s.strip())


def lines_norm(text):
    return [norm(l) for l in (text or "").split("\n")]


def rel_paths(fp):
    """Repo-relative spellings of a file path: itself plus its alias under every configured move."""
    if not fp.startswith(PREFIX):
        return []
    rel = fp[len(PREFIX):]
    out = [rel]
    for a, b in ALIASES:
        if rel.startswith(a):
            out.append(b + rel[len(a):])
        elif rel.startswith(b):
            out.append(a + rel[len(b):])
    return out


def ere(line):
    toks = line.split(" ")
    esc = [re.sub(r"([.\[\]()*+?{}|^$\\])", r"\\\1", t) for t in toks]
    return "[[:space:]]+".join(esc)
