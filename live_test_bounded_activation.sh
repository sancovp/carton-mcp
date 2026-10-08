#!/usr/bin/env bash
# live_test_bounded_activation.sh — issue #203 integrator live test (WRITTEN, deliberately NOT run
# by the worktree build; run this AFTER integrating the branch).
#
# WHAT THIS PROVES, per the issue's TEST SURFACE + ruling G4:
#   1. The coordinate-collection check: activate_collection on a known coordinate collection
#      returns the thread WITHOUT importing an axis/collection subtree (the stop is REPORTED).
#   2. REQUIRED REGRESSION (G4): the two DMN conversation-ladder shapes —
#      activate_collection("Conversation_<ts>") and
#      activate_collection("Raw_Conversation_Timeline_<date>") — return their FULL ladders,
#      byte-compatible pre/post.
#
# PRE-CONDITIONS (integrator):
#   - Branch merged into the working tree you deploy from.
#   - BASELINE FIRST: run PHASE 0 *BEFORE* pip install (it renders through the INSTALLED old
#     code), then install, then run PHASE 1-3. If you already installed, the committed
#     pre-change behavior is recoverable via `git stash` / checking out the pre-merge SHA.
#   - Install per the repo law: pip install --no-deps /home/GOD/gnosys-plugin-v2/knowledge/carton-mcp
#     then reconnect_mcp carton (never pkill the MCP).
#   - NO daemon restart is needed: this change is read-path only.
#
# Everything here is READ-ONLY against the graph. Timeouts obey no-short-timeouts (none set).

set -u
WORKDIR="$(mktemp -d /tmp/heaven_data/issue203_live.XXXX 2>/dev/null || mktemp -d)"
echo "workdir: $WORKDIR"

# The two live DMN ladder shapes. Re-derive fresh ones at run time (yesterday's timeline is a
# fixed target; conversations keep growing, so pin a CLOSED day/conversation):
LADDER_CONV="${LADDER_CONV:-Conversation_2026_08_26T20_36_08}"
LADDER_TL="${LADDER_TL:-Raw_Conversation_Timeline_2026_08_27}"
# A coordinate collection (journal-minted {Repo}_{Domain}_{Subdomain}). Find one that has an
# axis/collection member with:
#   MATCH (c:Wiki)-[:IS_A]->(:Wiki {n:'Carton_Collection'})
#   MATCH (c)-[:HAS_PART]->(m:Wiki)-[:IS_A]->(bt:Wiki)
#   WHERE bt.n IN ['Carton_Collection','Local_Collection','Identity_Collection','Global_Collection',
#                  'Hypercluster','Doc_Mirror_Repo','Doc_Mirror_Domain','Doc_Mirror_Subdomain']
#   RETURN c.n, m.n, bt.n LIMIT 5
# Measured 2026-08-28 (read-only, worktree build): Global_Collection -> Carton_History_Graph_Agent_Collection
# (IS_A Carton_Collection); old walk 32 members, bounded walk 1 member + 1 reported stop.
COORD_COLL="${COORD_COLL:-Global_Collection}"

render() {
  # Renders activate_collection's exact payload (library + _fmt — the same bytes the MCP tool
  # returns) for a collection, via the INSTALLED carton_mcp package. $1=collection $2=outfile
  python3 - "$1" "$2" <<'PYEOF'
import sys
name, out = sys.argv[1], sys.argv[2]
from carton_mcp.carton_utils import CartOnUtils
from carton_mcp.server_fastmcp import _fmt
utils = CartOnUtils()
result = utils.get_collection_concepts(name)
if not result.get("success"):
    print(f"QUERY FAILED: {result.get('error')}"); sys.exit(1)
text = _fmt(result)
# _fmt overflows >10k chars to a pointer file whose PATH is timestamped — byte-compare the
# FULL text, not the pointer line. Recover it when overflowed.
if "... Full results (" in text:
    overflow_path = text.rsplit(" at: ", 1)[1].strip()
    text = open(overflow_path).read()
open(out, "w").write(text)
print(f"{name}: {len(text)} chars -> {out}")
PYEOF
}

case "${1:-}" in
  phase0)
    echo "== PHASE 0 (RUN BEFORE pip install — baseline through the OLD installed code) =="
    python3 -c "import carton_mcp; print('carton_mcp at:', carton_mcp.__file__)"
    render "$LADDER_CONV" "$WORKDIR/pre_conv.txt"
    render "$LADDER_TL"   "$WORKDIR/pre_tl.txt"
    echo "BASELINE_DIR=$WORKDIR  # export this before phase 1"
    ;;
  phase1)
    echo "== PHASE 1 (AFTER pip install --no-deps + reconnect_mcp carton) =="
    echo "-- import-path law (verify-import-path-after-pip-install):"
    python3 -c "import carton_mcp.carton_bounded_walk as m; print('bounded walk at:', m.__file__)"
    : "${BASELINE_DIR:?export BASELINE_DIR=<the phase0 workdir> first}"
    render "$LADDER_CONV" "$WORKDIR/post_conv.txt"
    render "$LADDER_TL"   "$WORKDIR/post_tl.txt"
    echo "-- G4 BYTE-COMPAT (must print IDENTICAL twice):"
    cmp -s "$BASELINE_DIR/pre_conv.txt" "$WORKDIR/post_conv.txt" && echo "IDENTICAL: $LADDER_CONV" || { echo "FAIL: $LADDER_CONV DIFFERS"; diff "$BASELINE_DIR/pre_conv.txt" "$WORKDIR/post_conv.txt" | head -30; }
    cmp -s "$BASELINE_DIR/pre_tl.txt" "$WORKDIR/post_tl.txt" && echo "IDENTICAL: $LADDER_TL" || { echo "FAIL: $LADDER_TL DIFFERS"; diff "$BASELINE_DIR/pre_tl.txt" "$WORKDIR/post_tl.txt" | head -30; }
    ;;
  phase2)
    echo "== PHASE 2 — the coordinate/boundary check (the issue's headline case) =="
    render "$COORD_COLL" "$WORKDIR/coord.txt"
    echo "-- the stop-report must LEAD the payload (G10) and name the boundary member:"
    head -5 "$WORKDIR/coord.txt"
    grep -q "BOUNDED-WALK TRUNCATION" "$WORKDIR/coord.txt" && echo "PASS: truncation reported" || echo "FAIL: no truncation report (either the collection has no boundary member — pick another via the Cypher above — or the stop logic did not fire)"
    ;;
  phase3)
    cat <<'EOT'
== PHASE 3 — the LITERAL USER SURFACE (verify-via-user-surface: run these AS MCP TOOL CALLS
   in a Claude session with the reconnected carton MCP; a python render is NOT this surface) ==

  1. mcp__carton__activate_collection {"collection_name": "<LADDER_CONV>"}
       EXPECT: the full conversation ladder, NO "BOUNDED-WALK TRUNCATION" line, same content
       as before the change.
  2. mcp__carton__activate_collection {"collection_name": "<LADDER_TL>"}
       EXPECT: the full day timeline ladder, NO truncation line.
  3. mcp__carton__activate_collection {"collection_name": "<COORD_COLL>"}
       EXPECT: the FIRST lines of the payload are the truncation_report naming each stopped
       member with its reason; each stopped member still present in concepts as a leaf.
  4. mcp__carton__activate_collection {"collection_name": "<COORD_COLL>", "depth": 2}
       EXPECT: depth is LIVE — members deeper than 2 hops absent; members at depth 2 with
       children below reported as depth-stopped.
  5. mcp__carton__activate_collection {"collection_name": "<COORD_COLL>", "hub_cap": 1}
       EXPECT: cap tunable — UNTYPED members with any HAS_PART*1..4 subtree > 1 become
       reported stops. (Typed members are never hub-capped — the G4 reconciliation.)
EOT
    ;;
  *)
    echo "usage: $0 {phase0|phase1|phase2|phase3}"
    echo "  phase0  BEFORE pip install — baseline renders (old code)"
    echo "  phase1  AFTER pip install + reconnect — byte-compat diff (G4)"
    echo "  phase2  boundary fires on a hub/coordinate collection"
    echo "  phase3  print the exact MCP-surface tool calls (the literal user surface)"
    ;;
esac
