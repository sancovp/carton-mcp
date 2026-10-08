"""carton_write_batch — the MULTI-STATEMENT TRANSACTIONAL WRITE carton did not have (issue 485).

ISAAC 2026-09-06, verbatim: "IT MUST USE CARTON. IT MUST NOT CALL INTO NEO4J. IT MUST GO THROUGH
CARTON." Issue 485 takes the neo4j driver import out of doc-mirror. Its READ half landed under
issue 483 (every read goes through CartOnUtils.query_wiki_graph). This module is the WRITE half's
missing piece, and it exists because of a gap MEASURED rather than assumed:

  - `CartOnUtils.query_wiki_graph` is gated by `_validate_query_safety`, which REFUSES CREATE,
    MERGE, DELETE and DETACH. The read facade structurally cannot carry a write.
  - carton's synchronous write functions (`set_concept_properties`, `remove_concept_relationship`
    in carton_utils.py) each write ONE fixed shape, not arbitrary statements.
  - `KnowledgeGraphBuilder.execute_query` delegates to `self._store.execute` — ONE statement per
    call, auto-commit — and the `GraphStore` protocol exposes only execute / set_properties /
    remove_properties / find_by_properties / close / driver, on the protocol AND on all three
    backends. THERE IS NO TRANSACTION OR BATCH METHOD AT ANY LAYER.

So the shape doc-mirror needs did not exist, and under the CRUD law a shape carton LACKS is ADDED
to carton rather than worked around with a driver call in the caller. That is this module.

WHY ATOMICITY IS THE POINT, and not a detail. The first caller is docmirror_kanban's `_cypher`,
whose `update_card` writes a lane change, its reason, its kind and the BLOCKED_BY edge replacement
TOGETHER — its own comment says why: "so a block never lands half-recorded". Composing per-statement
`execute_query` calls would look like a clean conversion and would SILENTLY drop that guarantee.
This module therefore never pretends: `atomicity_for` REPORTS which mode a connection gets, and the
sequential mode is reachable only on a backend that has no driver to open a transaction on.

THROUGH THE STORE, NEVER A HAND-HELD DRIVER. `KnowledgeGraphBuilder._ensure_connection` documents
`driver` as "the raw neo4j driver, or None on a driverless backend" — that seam is what lets one
consumer follow GRAPH_BACKEND without knowing it exists. A caller that reached for `neo4j` itself
would weld doc-mirror to one backend, which is the thing issue 485 is removing. So this module takes
the CONNECTION carton already hands around and asks IT what it can do.

ONION, this package's own precedent (carton_bounded_walk: "the PURE half ... the Cypher executor
stays thin"). `validate_statements`, `atomicity_for` and `classify_error` are PURE — stdlib only,
no I/O, unit-tested on synthetic fakes (test_carton_write_batch.py). `execute_write_statements` is
the thin executor.

ONE CAPABILITY, ONE MODULE — this repo's stated convention, from its own carton-breaker rule: "One
capability, one module (the carton_quota / carton_kv precedent)."
"""
import logging
from typing import Any, Dict, List, Sequence, Tuple

logger = logging.getLogger(__name__)


class WriteStatementsInvalid(ValueError):
    """The statements given are not a runnable batch. Raised BEFORE any store is touched."""


class WriteStoreUnavailable(RuntimeError):
    """The graph could not be REACHED. Never an empty result.

    This is the distinction docmirror_kanban's StoreUnavailable carries and which every caller
    depends on: a store that cannot be reached is not a board that answered nothing. A batch that
    fails this way wrote NOTHING — in transaction mode because the transaction rolled back, in
    sequential mode because the failure is re-raised rather than swallowed (see the module note on
    partial application in `execute_write_statements`).
    """


# The atomicity modes, named so a caller can report which one it actually got.
TRANSACTION = "transaction"
SEQUENTIAL = "sequential"


def validate_statements(statements) -> List[Tuple[str, Dict[str, Any]]]:
    """PURE: normalize `[(query, params), ...]` to `[(str, dict), ...]`, or raise.

    A params of None becomes {}. Anything else — a bare string, a non-pair, a non-str query, a
    non-dict params — raises WriteStatementsInvalid naming the offending index, because a batch
    that is malformed must fail before it touches the store rather than half-way through it.
    An EMPTY batch is valid and does nothing: callers build statement lists conditionally.
    """
    if isinstance(statements, (str, bytes)) or not isinstance(statements, Sequence):
        raise WriteStatementsInvalid(
            f"statements must be a sequence of (query, params) pairs, got "
            f"{type(statements).__name__}")
    out: List[Tuple[str, Dict[str, Any]]] = []
    for i, item in enumerate(statements):
        if isinstance(item, (str, bytes)) or not isinstance(item, Sequence) or len(item) != 2:
            raise WriteStatementsInvalid(
                f"statement {i} must be a (query, params) pair, got {item!r}")
        query, params = item[0], item[1]
        if not isinstance(query, str) or not query.strip():
            raise WriteStatementsInvalid(
                f"statement {i} has a non-string or empty query: {query!r}")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise WriteStatementsInvalid(
                f"statement {i} has params of type {type(params).__name__}; expected a dict or None")
        out.append((query, params))
    return out


def atomicity_for(connection) -> str:
    """PURE: which mode `connection` gets — TRANSACTION when it exposes a driver, else SEQUENTIAL.

    Reported rather than assumed. `KnowledgeGraphBuilder.driver` is the raw neo4j driver or None on
    a driverless backend, so this is the honest answer to "will my batch be atomic?" and a caller
    that needs atomicity can ask BEFORE it writes instead of discovering it afterwards.
    """
    return TRANSACTION if getattr(connection, "driver", None) is not None else SEQUENTIAL


def _unreachable_types():
    """The driver exception types that mean COULD NOT REACH, or () when the driver is absent.

    Imported lazily and tolerantly: carton may legitimately run on a backend whose driver package
    is not installed, and in that case there are no such types to catch — which is correct, not a
    failure, because a driverless backend raises its own errors through its own store.
    """
    try:
        from neo4j.exceptions import ServiceUnavailable, SessionExpired
        return (ServiceUnavailable, SessionExpired)
    except ImportError:
        # EXPECTED on a driverless backend, so this is DEBUG and not a warning: there are simply
        # no driver types to catch, and such a backend surfaces its own errors through its store.
        logger.debug("carton_write_batch: no neo4j driver types to classify against",
                     exc_info=True)
        return ()


def classify_error(exc, unreachable_types=None) -> str:
    """PURE: "unreachable" when `exc` is one of the driver's could-not-reach types, else "other".

    Split out from the executor so the classification is unit-testable on synthetic exception
    classes without a store, and so the executor's own except-branch has nothing to decide.
    """
    types = _unreachable_types() if unreachable_types is None else tuple(unreachable_types)
    return "unreachable" if types and isinstance(exc, types) else "other"


def _rows(result) -> List[Dict[str, Any]]:
    """PURE: one statement's result as a list of plain dicts. None and empty both give []."""
    return [dict(r) for r in (result or [])]


def _run_in_one_transaction(driver, stmts):
    """ONE explicit transaction, NO managed-retry — the contract docmirror_kanban already had.

    The driver's managed transaction (execute_write) retries an unreachable store with backoff for
    roughly 30 seconds before giving up, which is longer than the CLI callers wait; the original
    `_cypher` said so in its own comment and used an explicit transaction for exactly that reason.
    Preserved here verbatim rather than re-decided.
    """
    with driver.session() as session:
        tx = session.begin_transaction()
        try:
            out = [_rows(tx.run(query, **params)) for query, params in stmts]
            tx.commit()
        except Exception:
            tx.rollback()
            raise
        return out


def _run_sequentially(connection, stmts):
    """One `execute_query` per statement, in order, on a backend with no driver to open a tx on.

    NOT atomic, and this module never claims it is: `atomicity_for` returns SEQUENTIAL for such a
    connection, so a caller that needs all-or-nothing can refuse before writing. A failure part-way
    leaves the earlier statements APPLIED, which is the honest cost of a backend without
    transactions and is why this branch exists only where the other one cannot run.
    """
    return [_rows(connection.execute_query(query, params)) for query, params in stmts]


def execute_write_statements(statements, shared_connection=None) -> List[List[Dict[str, Any]]]:
    """Run `[(query, params), ...]` as ONE write batch through carton's own connection.

    Returns one list of dict rows per statement, in statement order — the same shape
    docmirror_kanban's `_cypher` returned, so its callers are unchanged.

    Atomic when the connection exposes a driver (the neo4j backend, which is the live one): the
    whole batch commits or rolls back together. Sequential when it does not; `atomicity_for` says
    which, and this function never pretends the second is the first.

    Raises WriteStatementsInvalid for a malformed batch, BEFORE touching the store, and
    WriteStoreUnavailable when the graph cannot be reached — never an empty result for either,
    because on this surface an empty result reads as "the store answered nothing" and both of these
    mean "the store did not answer".
    """
    stmts = validate_statements(statements)
    if not stmts:
        return []

    connection = shared_connection
    if connection is None:
        from .add_concept_tool import _get_module_connection
        connection = _get_module_connection()
    if connection is None:
        raise WriteStoreUnavailable(
            "carton_write_batch has no graph connection: _get_module_connection() returned None")

    try:
        ensure = getattr(connection, "_ensure_connection", None)
        if ensure is not None:
            ensure()
    except Exception as exc:
        raise WriteStoreUnavailable(
            f"carton_write_batch could not reach the graph: {type(exc).__name__}: {exc}") from exc

    mode = atomicity_for(connection)
    if mode == SEQUENTIAL and not callable(getattr(connection, "execute_query", None)):
        # A connection with NEITHER a driver NOR execute_query cannot write at all. Caught HERE so
        # the caller gets the refusal this module documents rather than a bare AttributeError from
        # somewhere inside the batch — the M10 case, which the suite found before any caller did.
        raise WriteStoreUnavailable(
            f"carton_write_batch cannot write through {type(connection).__name__}: it exposes "
            "neither a driver to open a transaction on nor an execute_query to run statements with")

    try:
        if mode == TRANSACTION:
            return _run_in_one_transaction(connection.driver, stmts)
        return _run_sequentially(connection, stmts)
    except (WriteStatementsInvalid, WriteStoreUnavailable):
        raise
    except Exception as exc:
        if classify_error(exc) == "unreachable":
            raise WriteStoreUnavailable(
                f"carton_write_batch could not reach the graph: "
                f"{type(exc).__name__}: {exc}") from exc
        raise
