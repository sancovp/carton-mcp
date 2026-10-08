#!/usr/bin/env python3
"""CartON Bash Tool_Calls for the days the transcripts do NOT cover (from the window start up to the
earliest transcript day): dump those that write a target file or run a git verb that can drop
working-tree bytes, classified with the same rules as the transcript pass. Writes raw/carton_bash.jsonl.
Whitespace inside commands is collapsed at storage (issue 943). Read-only over neo4j.
When the whole window is inside transcript coverage there is nothing to do, and it says so."""
import datetime as dt
import json
import re
import sys

from neo4j import READ_ACCESS

from bash_targets import targets
from delink import delink
from destructive import SEG, destructive
from recon_common import FROM, TO, PATH_RX, neo4j_driver, raw, transcript_start


def main():
    d0 = dt.date.fromisoformat(FROM)
    d1 = min(dt.date.fromisoformat(TO), dt.date.fromisoformat(transcript_start()[:10]))
    out = open(raw("carton_bash.jsonl"), "w")
    if d1 < d0:
        out.close()
        print(f"window {FROM}..{TO} starts after the transcripts begin ({transcript_start()}): "
              "no CartON-only Bash days to scan")
        return
    drv = neo4j_driver()
    n_all = n_keep = 0
    with drv.session(default_access_mode=READ_ACCESS) as s:
        d = d0
        while d <= d1:
            pfx = "Tool_Call_" + d.strftime("%Y_%m_%d")
            for r in s.run("MATCH (t:Wiki) WHERE t.n STARTS WITH $p RETURN t.n AS n, t.d AS d ORDER BY t.n", p=pfx):
                rawd = r["d"] or ""
                if not rawd.startswith("[Bash]") and not rawd.startswith("Bash"):
                    continue
                n_all += 1
                dd = delink(rawd)
                m = re.match(r"\s*Bash\s*\n\s*\n\s*Args:\s*\n(.*)\Z", dd, re.S)
                if not m:
                    continue
                try:
                    cmd = json.loads(m.group(1)).get("command", "")
                except json.JSONDecodeError as e:
                    print("PARSE-FAIL", r["n"], e, file=sys.stderr)
                    continue
                segs = [g.group(0) for g in SEG.finditer(cmd) if destructive(g.group(1), g.group(2))]
                tg = targets(cmd) if PATH_RX.search(cmd) else []
                if not segs and not tg:
                    continue
                n_keep += 1
                out.write(json.dumps({"n": r["n"], "cmd": cmd, "writes": tg, "discards": segs}) + "\n")
                print(f"{r['n']}\twrites={tg}\tdiscards={segs}\t{cmd.splitlines()[0][:160] if cmd else ''}")
            d += dt.timedelta(days=1)
    drv.close()
    out.close()
    print(f"bash tool calls scanned {d0}..{d1}: {n_all}; with target writes or discards: {n_keep}")


if __name__ == "__main__":
    main()
