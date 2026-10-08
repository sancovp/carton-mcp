"""Delete concepts carton stored by mistake: the node, its edges and its wiki directory (card 816, issue 1301).

Isaac's ruling, verbatim: "To correct one already stored: delete the node, its edges and its wiki file".
Every node is backed up whole before anything is removed, and a node that a node outside the batch cites is
refused. The SOMA reflection and the chroma index are not touched.
"""
import json
import logging
import os
import shutil
import time
from pathlib import Path

logger = logging.getLogger(__name__)

READ_RECORDS = (
    "UNWIND $names AS nm OPTIONAL MATCH (n:Wiki {n: nm}) "
    "RETURN nm AS name, n IS NOT NULL AS exists, properties(n) AS props, "
    "[(n)-[r]->(t:Wiki) | {rel: type(r), target: t.n, props: properties(r)}] AS outbound, "
    "[(s:Wiki)-[r]->(n) | {rel: type(r), source: s.n, props: properties(r)}] AS inbound")
DELETE_NODES = "UNWIND $names AS nm MATCH (n:Wiki {n: nm}) DETACH DELETE n"
NOT_TOUCHED = "the SOMA reflection and the chroma index keep these names until each is rebuilt"


def _citations(record, batch):
    """PURE. The inbound edges of `record` from a node outside `batch` that it does not point back at."""
    points_at = {e["target"] for e in record.get("outbound") or []}
    return [e for e in record.get("inbound") or [] if e["source"] not in batch and e["source"] not in points_at]


def plan_deletion(names, records):
    """PURE. Which named concepts delete and which are refused.

    Args:
        names: the concept names asked for, in order.
        records: name -> {"exists", "outbound": [{"rel", "target"}], "inbound": [{"rel", "source"}]}.

    Returns:
        {"delete": [names in asked order], "refused": {name: reason}}. A name no node holds is refused, and
        so is a node cited by a node outside the batch along an edge it does not point back along; the batch
        is recomputed until no refusal changes it, so a member a refused member cites is refused too.
    """
    refused = {n: f"no node named {n}" for n in names if not (records.get(n) or {}).get("exists")}
    batch = [n for n in names if n not in refused]
    changed = True
    while changed:
        changed = False
        members = set(batch)
        for name in list(batch):
            citing = _citations(records[name], members)
            if citing:
                first = citing[0]
                more = f" and {len(citing) - 1} more" if len(citing) > 1 else ""
                refused[name] = f"cited by {first['source']} -[{first['rel']}]-> {name}{more}"
                batch.remove(name)
                changed = True
    return {"delete": batch, "refused": refused}


def delete_concepts(names, backup_dir, *, run, wiki_dir, dry_run=False, guard=None):
    """Back up and delete the named concepts that nothing outside the batch cites.

    Args:
        names: concept names to delete.
        backup_dir: directory the backup folder is created under.
        run: callable taking [(query, params)] and returning one row list per statement.
        wiki_dir: the directory holding one wiki directory per concept name.
        dry_run: read and plan only; write nothing.
        guard: optional callable(path) that raises when a wiki directory must not be removed.

    Returns:
        The report: what was asked, deleted and refused, the backup folder, how many wiki directories were
        removed, and what was not touched.
    """
    rows = run([(READ_RECORDS, {"names": list(names)})])[0]
    records = {r["name"]: r for r in rows}
    plan = plan_deletion(list(names), records)
    report = {"asked": len(names), "delete": plan["delete"], "refused": plan["refused"],
              "dry_run": dry_run, "not_touched": NOT_TOUCHED}
    if dry_run or not plan["delete"]:
        return report
    out = Path(backup_dir) / f"carton_delete_{time.strftime('%Y%m%dT%H%M%S')}"
    (out / "wiki").mkdir(parents=True)
    (out / "records.json").write_text(
        json.dumps({n: records[n] for n in plan["delete"]}, default=str, indent=1))
    dirs = []
    for name in plan["delete"]:
        d = Path(wiki_dir) / name
        if d.is_dir():
            if guard is not None:
                guard(d)
            shutil.copytree(d, out / "wiki" / name)
            dirs.append(d)
    run([(DELETE_NODES, {"names": plan["delete"]})])
    for d in dirs:
        shutil.rmtree(d)
    logger.info("carton_delete: deleted %d, refused %d, backup %s", len(plan["delete"]), len(plan["refused"]), out)
    report.update(backup=str(out), wiki_removed=len(dirs))
    return report


def main(argv=None):
    """`python3 -m carton_mcp.carton_delete [NAME ...] [--names-file F] --backup-dir DIR [--dry-run]`.

    Prints the report as JSON on stdout.
    """
    import argparse
    os.environ.setdefault("HEAVEN_ALLOW_STDOUT", "1")
    from carton_mcp.carton_pathguard import check_write, wiki_root
    from carton_mcp.carton_write_batch import execute_write_statements

    p = argparse.ArgumentParser(prog="carton_delete", description=__doc__.splitlines()[0])
    p.add_argument("names", nargs="*")
    p.add_argument("--names-file", help="one concept name per line")
    p.add_argument("--backup-dir", required=True)
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    names = list(a.names)
    if a.names_file:
        names += [ln.strip() for ln in Path(a.names_file).read_text().splitlines() if ln.strip()]
    if not names:
        p.error("name at least one concept")
    report = delete_concepts(names, a.backup_dir, run=execute_write_statements,
                             wiki_dir=wiki_root() / "concepts", dry_run=a.dry_run,
                             guard=lambda d: check_write(d, "wiki"))
    print(json.dumps(report, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
