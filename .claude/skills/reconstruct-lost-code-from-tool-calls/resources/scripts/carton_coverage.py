#!/usr/bin/env python3
"""Per-day coverage of CartON Tool_Call nodes over the run window: total Tool_Call nodes that day (all
tools), how many are file-writing tools (Edit/Write/MultiEdit/NotebookEdit, by description head or
USES_TOOL), how many of those touch a path matching path_regex (description or TOUCHES_FILE), and how
many Bash calls mention such a path. A day with ZERO Tool_Call nodes is a HOLE: nothing is known about
it from CartON, which is not the same as "no edits".

Outputs: raw/carton_coverage.tsv (the table, also printed) and raw/carton_toolcalls.jsonl (every
matching file-writing Tool_Call, delinked, with its relationships). Read-only over neo4j."""
import datetime as dt
import json

from neo4j import READ_ACCESS

from delink import delink, residue
from recon_common import FROM, TO, PATH_RX, neo4j_driver, raw

FILE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


def main():
    start, end = dt.date.fromisoformat(FROM), dt.date.fromisoformat(TO)
    days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    drv = neo4j_driver()
    out = open(raw("carton_toolcalls.jsonl"), "w")
    table = open(raw("carton_coverage.tsv"), "w")
    header = "day\ttool_calls\tfile_write_calls\ttarget_file_writes\ttarget_bash\tnote"
    print(header)
    table.write(header + "\n")
    holes = 0
    with drv.session(default_access_mode=READ_ACCESS) as s:
        for d in days:
            pfx = "Tool_Call_" + d.strftime("%Y_%m_%d")
            rows = list(s.run(
                "MATCH (t:Wiki) WHERE t.n STARTS WITH $p "
                "OPTIONAL MATCH (t)-[:USES_TOOL]->(u:Wiki) "
                "OPTIONAL MATCH (t)-[:TOUCHES_FILE]->(f:Wiki) "
                "OPTIONAL MATCH (t)-[:PART_OF]->(it:Wiki) "
                "RETURN t.n AS n, t.d AS d, toString(t.t) AS t, collect(DISTINCT u.n) AS tools, "
                "collect(DISTINCT f.n) AS files, collect(DISTINCT it.n) AS parents", p=pfx))
            fw = sw = sb = 0
            for r in rows:
                tools = r["tools"] or []
                rawd = r["d"] or ""
                tool = delink(rawd.split("\n", 1)[0]).strip()
                is_fw = tool in FILE_TOOLS or any(x in FILE_TOOLS for x in tools)
                hit = bool(PATH_RX.search(rawd)) or any(PATH_RX.search(f or "") for f in r["files"])
                if is_fw:
                    fw += 1
                if is_fw and hit:
                    sw += 1
                    dd = delink(rawd)
                    out.write(json.dumps({"n": r["n"], "t": r["t"], "tool": tool, "tools": tools,
                                          "files": r["files"], "parents": r["parents"],
                                          "residue": residue(dd), "d": dd}, ensure_ascii=False) + "\n")
                if tool == "Bash" and hit:
                    sb += 1
            note = "HOLE: zero Tool_Call nodes" if not rows else ("thin" if len(rows) < 250 else "")
            holes += not rows
            line = f"{d}\t{len(rows)}\t{fw}\t{sw}\t{sb}\t{note}"
            print(line)
            table.write(line + "\n")
    drv.close()
    out.close()
    table.close()
    print(f"[{len(days)} days {FROM}..{TO}; {holes} HOLE day(s) with zero Tool_Call nodes]")


if __name__ == "__main__":
    main()
