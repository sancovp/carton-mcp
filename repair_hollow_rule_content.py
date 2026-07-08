"""Repair the 61 hollow HAS_CONTENT->_Unnamed claude_code_rule nodes (Isaac 2026-06-15).

These are project-scoped rules of the gnosys-plugin-v2 starsystem whose real body
lives in an on-disk .claude/rules/*.md file (NOT in n.d — n.d is auto-linker
relationship prose). has_content/has_name/has_scope all carry a duplicate _Unnamed
edge. Re-derive each body from disk and fill has_content properly; clear the
_Unnamed edges so the accepts_unnamed gate (65c684e) passes.

Resolution chain (Isaac): disk file -> (caller handles) deconfab -> carton queue/cache.
This script does the DETERMINISTIC disk resolution + (with --apply) the mutation.
DRY-RUN by default: prints a manifest, mutates NOTHING.

Mutation per resolved rule (idempotent, MERGE/DELETE):
  - create/My content node {n: <Rule>__Content, d: <disk body>}, status code
  - MERGE (rule)-[:HAS_CONTENT]->(content); DELETE (rule)-[:HAS_CONTENT]->(_Unnamed)
  - set has_name to the real slug node; DELETE has_name->_Unnamed
  - DELETE has_scope->_Unnamed (the real has_scope->Project edge already exists)
Backup of every touched (rule, rel, target) triple is written before any delete.
"""
import os, sys, re, json, glob, time
from neo4j import GraphDatabase

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://host.docker.internal:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "password")

PRIMARY_DIR = "/home/GOD/gnosys-plugin-v2/.claude/rules"
FALLBACK_DIRS = ["/home/GOD/.claude/rules"]
# Widened: these rules were colonized from OTHER repos (heaven-tree, sdna, sanctuary,
# opera, ...) whose real .claude/rules live in the dev-clone repos, NOT the monorepo.
ALL_REPO_RULE_DIRS = (
    glob.glob("/home/GOD/gnosys-plugin-v2/**/.claude/rules", recursive=True)
    + glob.glob("/home/GOD/*/.claude/rules")
    + glob.glob("/home/GOD/*/**/.claude/rules", recursive=True)
    + glob.glob("/tmp/*/.claude/rules")
    + glob.glob("/tmp/*/**/.claude/rules", recursive=True)
)
# de-dup, and skip the legacy /home/GOD/core tree (off-limits per home-god-core-is-legacy)
ALL_REPO_RULE_DIRS = sorted({d for d in ALL_REPO_RULE_DIRS if "/home/GOD/core/" not in d})

def slug_of(concept_name):
    s = concept_name
    if s.startswith("Claude_Code_Rule_"):
        s = s[len("Claude_Code_Rule_"):]
    return s.lower().replace("_", "-")

def _words(name):
    return set(w for w in re.split(r"[^a-z0-9]+", name.lower()) if w)

def resolve_file(concept_name):
    """Return (path, body, how) or (None, None, reason)."""
    slug = slug_of(concept_name)
    # 1. exact slug.md in primary then fallback dirs
    for d in [PRIMARY_DIR] + FALLBACK_DIRS:
        p = os.path.join(d, slug + ".md")
        if os.path.isfile(p):
            return p, open(p).read(), "exact"
    # 2. fuzzy: best word-overlap match across primary+fallback+all repo dirs
    target = _words(slug)
    best = None
    for d in [PRIMARY_DIR] + FALLBACK_DIRS + ALL_REPO_RULE_DIRS:
        for p in glob.glob(os.path.join(d, "*.md")):
            fw = _words(os.path.basename(p)[:-3])
            if not fw:
                continue
            inter = len(target & fw)
            union = len(target | fw)
            jac = inter / union if union else 0
            # require strong overlap: all target words present OR jaccard>=0.7
            if (target and target.issubset(fw)) or jac >= 0.7:
                score = (target.issubset(fw), jac, -abs(len(fw) - len(target)))
                if best is None or score > best[0]:
                    best = (score, p)
    if best:
        p = best[1]
        return p, open(p).read(), f"fuzzy({os.path.basename(p)})"
    return None, None, "UNRESOLVED_ON_DISK"

def get_hollow_rules(driver):
    q = """
    MATCH (r:Wiki)-[:IS_A]->(:Wiki {n:'Claude_Code_Rule'})
    MATCH (r)-[:HAS_CONTENT]->(c:Wiki) WHERE c.n='_Unnamed' OR c.n ENDS WITH '_Unnamed'
    RETURN DISTINCT r.n AS rule ORDER BY r.n
    """
    with driver.session() as s:
        return [rec["rule"] for rec in s.run(q)]

def backup_rule_edges(driver, rule_names, path):
    """Dump every (rule)-[rel]->(target.n) for the given rules to a JSON file
    so the mutation is fully reversible."""
    q = """
    UNWIND $names AS rn
    MATCH (r:Wiki {n: rn})-[rel]->(t:Wiki)
    RETURN rn AS rule, type(rel) AS rel, t.n AS target
    """
    with driver.session() as s:
        rows = [dict(rec) for rec in s.run(q, names=rule_names)]
    json.dump({"backed_up_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "edges": rows},
              open(path, "w"), indent=2)
    return len(rows)

def apply_repair(driver, rule_name, body, name_stem):
    """Fill the 3 required code args with REAL values + drop the _Unnamed edges.
    Idempotent (MERGE content/name node, DELETE only the _Unnamed-target edges).
    Returns a short status string."""
    content_node = rule_name + "__Content"
    with driver.session() as s:
        s.run(
            """
            MATCH (r:Wiki {n:$rule})
            // 1. content: real content node carries the body in n.d
            MERGE (c:Wiki {n:$content_node})
              ON CREATE SET c.d=$body, c.t=datetime()
              ON MATCH  SET c.d=$body
            MERGE (r)-[:HAS_CONTENT]->(c)
            // 2. name: real slug node
            MERGE (nm:Wiki {n:$name_stem})
              ON CREATE SET nm.d=$name_stem, nm.t=datetime()
            MERGE (r)-[:HAS_NAME]->(nm)
            // 3. drop EVERY _Unnamed-target edge from this rule (has_content/has_name/
            //    has_scope/etc.) so the accepts_unnamed gate sees ZERO _Unnamed value.
            //    The real has_scope->Project edge is kept (only the _Unnamed one drops).
            WITH r
            MATCH (r)-[bad]->(u:Wiki) WHERE u.n='_Unnamed' OR u.n ENDS WITH '_Unnamed'
            DELETE bad
            """,
            rule=rule_name, content_node=content_node, body=body, name_stem=name_stem,
        )
    return f"set has_content->{content_node} ({len(body)}B), has_name->{name_stem}, dropped _Unnamed edges"

def main():
    apply = "--apply" in sys.argv
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    rules = get_hollow_rules(driver)
    print(f"# {len(rules)} hollow rules to repair (mode={'APPLY' if apply else 'DRY-RUN'})\n")
    resolved, unresolved = [], []
    for rn in rules:
        path, body, how = resolve_file(rn)
        if path:
            resolved.append((rn, path, body, how))
            print(f"RESOLVED {rn}\n   -> {path}  [{how}, {len(body)}B]")
        else:
            unresolved.append(rn)
            print(f"UNRESOLVED {rn}  ({how})")
    print(f"\n# SUMMARY: resolved={len(resolved)} unresolved={len(unresolved)}")
    if apply and resolved:
        bpath = f"/tmp/hollow_rule_repair_backup_{time.strftime('%Y%m%d_%H%M%S')}.json"
        n = backup_rule_edges(driver, [r[0] for r in resolved], bpath)
        print(f"\n# BACKUP: {n} edges of {len(resolved)} rules -> {bpath}")
        for rn, path, body, how in resolved:
            stem = os.path.basename(path)[:-3]
            st = apply_repair(driver, rn, body, stem)
            print(f"APPLIED {rn}: {st}")
        print(f"\n# APPLIED repair to {len(resolved)} resolved rules.")
    if unresolved:
        print("# UNRESOLVED (need git-history / deconfab / carton-queue fallback):")
        for rn in unresolved:
            print(f"#   {rn}")
    driver.close()

if __name__ == "__main__":
    main()
