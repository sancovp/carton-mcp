"""Release-effect handlers for the doc-mirror task board.

The observation worker dispatches these by name after the d-chain phase: a handler is named in a
d-chain's conclusion as `carton_mcp.doc_mirror_kanban_effects:<func>` and resolved by
`handler.split(":", 1)` + `import_module`. Each handler takes the CartON node name the chain fired
on plus the worker's graph connection, never raises, and returns a line for the dispatch log.
"""

import importlib.util
import logging
import os
import traceback
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_MONOREPO = "/home/GOD/gnosys-plugin-v2"
PLUGIN_LIB = "doc-mirror-system/plugin/lib"
KANBAN_MODULE = "docmirror_kanban"

_kanban = None


def kanban_lib():
    """Load the doc-mirror board library by path and cache it.

    The board library is a doc-mirror plugin lib rather than an installed package, so it is loaded
    from its file instead of imported by name. Loading it through a file-location spec leaves the
    interpreter's module search path untouched, so a long-lived worker's import namespace is never
    mutated.

    Returns:
        module: The loaded docmirror_kanban module.

    Raises:
        ImportError: When the library is not at the expected path. The path is checked before the
        spec is built, because a spec is returned for a nonexistent file and the failure would
        otherwise surface as a FileNotFoundError from exec_module.
    """
    global _kanban
    if _kanban is not None:
        return _kanban
    root = os.environ.get("DOCMIRROR_MONOREPO", DEFAULT_MONOREPO)
    path = Path(root) / PLUGIN_LIB / f"{KANBAN_MODULE}.py"
    if not path.is_file():
        raise ImportError(f"no doc-mirror board library at {path}")
    spec = importlib.util.spec_from_file_location(KANBAN_MODULE, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load the doc-mirror board library at {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _kanban = module
    return module


def board_of(concept_name, shared_connection):
    """The board a lane transition happened on, read from the transition's own board field.

    The transition IS a BoardLaneChange, whose `board` field means exactly this, so the field is
    read first and the card traversal is only a fallback. The traversal alone was not enough: a
    relationship target is name-normalized on write and the card's endeavor id is hex, so
    `HAS_CARD` points at an upper-cased name that matches no card and the board came back None for
    every real card on the board (issue #723). A property value is not name-normalized, so the
    field survived intact while the edge did not.

    Args:
        concept_name: The Doc_Mirror_Board_Lane_Change node name.
        shared_connection: The worker's graph connection.

    Returns:
        str | None: The endeavor, or None when the transition names neither a board nor a card.
    """
    if shared_connection is None:
        return None
    rows = shared_connection.execute_query(
        "MATCH (t:Wiki {n:$n}) "
        "OPTIONAL MATCH (t)-[:HAS_CARD]->(c:Wiki) "
        "RETURN coalesce(t.board, c.endeavor, c.session) AS board LIMIT 1",
        {"n": concept_name})
    records = rows[0] if isinstance(rows, tuple) else rows
    if not records:
        return None
    rec = records[0]
    return rec.get("board") if isinstance(rec, dict) else rec["board"]


def ratchet_on_build_freed(concept_name, shared_connection=None):
    """Pull the next sprint into build after a card left the build lane.

    Args:
        concept_name: The Doc_Mirror_Lane_Transition node the d-chain fired on.
        shared_connection: The worker's graph connection.

    Returns:
        str: What happened, for the daemon's dispatch log. A failure is returned, never raised,
        and its traceback is logged.
    """
    try:
        board = board_of(concept_name, shared_connection)
        if not board:
            return f"{concept_name}: no card on a board; nothing pulled"
        pulled = kanban_lib().ratchet(board)
        if not pulled:
            return f"{board}: build not empty, or plan holds no sprint; nothing pulled"
        return (f"{board}: sprint {pulled['sprint']} -> build, "
                f"{len(pulled['moved'])} moved, {len(pulled['skipped'])} skipped")
    except Exception as e:
        logger.error("ratchet_on_build_freed(%s) failed:\n%s", concept_name, traceback.format_exc())
        return f"{concept_name}: ratchet failed, {type(e).__name__}: {e}"
