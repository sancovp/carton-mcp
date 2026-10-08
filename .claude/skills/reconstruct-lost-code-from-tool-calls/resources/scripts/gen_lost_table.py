#!/usr/bin/env python3
"""Emit raw/lost_table.md: one row per lost-class op of ledger.json, with its verdict, whether it was
applied to the rebuilt files, and its patch — section 6 of INDEX.md."""
import json
import os

from recon_common import LOST, ROOT, raw


def main():
    rows = json.load(open(os.path.join(ROOT, "ledger.json")))["file_ops"]
    n = 0
    with open(raw("lost_table.md"), "w") as f:
        f.write("| # | ts (UTC) | Tool_Call node | tool_use id | file | status | add sha | remove sha | verdict | applied | patch |\n")
        f.write("|---|---|---|---|---|---|---|---|---|---|---|\n")
        for r in rows:
            if r["status"] not in LOST:
                continue
            n += 1
            f.write(f"| {n} | {r['ts'][:19]} | {r['tool_call_node']} | {r['tool_use_id'] or '(CartON only, LOSSY)'} | {r['file']} | "
                    f"{r['status']}{(' '+r['partial_kind']) if r['partial_kind'] else ''} | {r['adding_sha']} | {r['removing_sha']} | "
                    f"{r['verdict']} | {'yes' if r['applied_to_recovered_file'] else 'no'} | {os.path.basename(r['patch'] or '')} |\n")
    print(f"lost-class rows: {n} of {len(rows)} ledger rows")


if __name__ == "__main__":
    main()
