"""The two release-effect handlers that project a doc(M) and a doc(V) out to their RAG files.

Isaac 2026-09-13: "DOC V AND M ARE CARTON FUCKING CONCEPTS, THEY ARE NOT FILES" and "THE ONLY
REASON WE PROJECT THEM OUT AS FILES IS TO MAKE THE RAG FOR YOU". So the CONCEPT is the truth and
the file is its projection, fired off the concept by a d-chain rather than written by any hand.

THE RELEASE LAW, which is why these are plain functions taking one name: a d-chain conclusion
never py_calls business logic from inside Prolog. It surfaces release_effect(handler, C); the
carton observation-worker daemon imports the handler AFTER the d-chain phase and calls it with
the concept name, passing its own neo4j connection so the read happens on the connection the
write just landed on. Exemplars: substrate_projector.project_skill and flush_starlog_diary.

WHY THIS IS ITS OWN MODULE AND NOT substrate_projector, decided 2026-09-13 and not to be
re-litigated: substrate_projector is 3045 lines and is covered by NO sealed boundary, so editing
it would mean tracing and sealing 146KB first, while a new file needs only its own hop. It is
also the better architecture — doc-mirror is being retired into starsystem and its projector
should not be welded into carton's generic one.

⚠ THESE HANDLERS WRITE THEIR OWN PATHS AND ARE DELIBERATELY NOT ROUTED THROUGH
carton_pathguard.check_write, and the reason is a real incompatibility rather than an oversight.
The pathguard makes registered doc roots CREATE-ONLY: rewriting an existing file under a doc root
is refused, because rewriting tracked source IS the corruption it was built to stop (issue #206).
A doc(m) is RE-DERIVED on every projection, so an idempotent doc(m) projector rewrites its file by
definition and every update after the first would be refused. The pathguard's own rule already
records that the other projection handlers are unguarded lanes. What is done instead: the write is
confined to the doc-mirror layer by construction — only <root>/docs/mirror/ and <root>/docs/vision/
are ever touched, the relpath is rejected if it escapes upward, and the write is a DIFF-write so an
unchanged projection touches nothing.

⚠ THE TWO LANES ARE NOT SYMMETRIC, and the doc(v) lane REFUSES AN EXISTING FILE. A doc(m) file is
ONE derived render, so the concept's text IS the whole file and overwriting it is the design. A
doc(v) FILE is not: it is a header seeded verbatim from the paired doc(m), then a DELTA marker, then
EVERY id-tagged append, all written by the journal CLI — while ONE Doc_Mirror_Vision concept is ONE
entry. Projecting one entry over that file destroys the header and every other entry, measured here
at 34 lines replaced by 1 before the guard existed. So this lane writes only where no file stands
yet, and otherwise refuses by name. It becomes free to write when the journal write EXTRACTS into a
Doc_Mirror_Vision instead of appending (issue #669 act three) — replace-before-remove, the same
ordering the doc M half took when its concept write was added BESIDE the file write rather than in
place of it.
"""

import os
from pathlib import Path

MIRROR_DIR = "docs/mirror"
VISION_DIR = "docs/vision"
MODULE_TYPE = "Doc_Mirror_Module"
VISION_TYPE = "Doc_Mirror_Vision"

_SEARCH_DEPTH = 3


def _monorepo_root():
    """Read the root the repo axis name is resolved against.

    Returns:
        str: The DOCMIRROR_MONOREPO value, or the known monorepo path when unset.
    """
    return os.environ.get("DOCMIRROR_MONOREPO") or "/home/GOD/gnosys-plugin-v2"


def _title_segment(raw):
    """Title_Case one path segment the way the doc-mirror writers name a repo.

    Args:
        raw: A path segment.

    Returns:
        str: The segment with each non-alphanumeric run replaced by one underscore.
    """
    parts = [p for p in "".join(c if c.isalnum() else " " for c in (raw or "")).split() if p]
    return "_".join(p[:1].upper() + p[1:].lower() if p.isalpha() else p.capitalize()
                    for p in parts)


def repo_root(repo_name, root=None):
    """Find the project root on disk whose basename names this repo axis node.

    The concept carries the repo as a Title_Cased AXIS NAME, which is what the writers hang the
    instance on; the projection needs a DIRECTORY. The mapping is recovered by matching the
    basename rather than stored, so a moved repo does not strand its projections.

    Args:
        repo_name: The Title_Cased repo axis name, e.g. Doc_Mirror_System.
        root: The monorepo root to search, or None for the default.

    Returns:
        str | None: The absolute project root, or None when no directory matches.
    """
    base = Path(root or _monorepo_root())
    if not base.is_dir() or not repo_name:
        return None
    if _title_segment(base.name) == repo_name:
        return str(base)
    frontier = [base]
    for _ in range(_SEARCH_DEPTH):
        nxt = []
        for parent in frontier:
            try:
                children = sorted(p for p in parent.iterdir() if p.is_dir())
            except OSError:
                continue
            for child in children:
                if child.name.startswith(".") or child.name == "node_modules":
                    continue
                if _title_segment(child.name) == repo_name:
                    return str(child)
                nxt.append(child)
        frontier = nxt
    return None


def target_path(project, relpath, kind):
    """Build the doc-layer path a concept projects to, refusing anything outside that layer.

    Args:
        project: The project root on disk.
        relpath: The module relpath the concept mirrors or is a vision of.
        kind: MIRROR_DIR or VISION_DIR.

    Returns:
        Path | None: The absolute file path, or None when relpath escapes the layer.
    """
    if not relpath:
        return None
    layer = (Path(project) / kind).resolve()
    candidate = (layer / (str(relpath).strip("/") + ".md")).resolve()
    try:
        candidate.relative_to(layer)
    except ValueError:
        return None
    return candidate


def read_concept(concept_name, shared_connection=None):
    """Read one doc-layer concept, its type, its properties and its content text.

    Args:
        concept_name: The carton node name the release effect named.
        shared_connection: The daemon's neo4j connection, or None.

    Returns:
        dict | None: name, types, repo, module and content; None when the concept is absent.
    """
    from carton_mcp.carton_utils import CartOnUtils, verbatim_text

    utils = CartOnUtils(shared_connection=shared_connection)
    res = utils.query_verbatim(
        "MATCH (c:Wiki {n: $name}) "
        "OPTIONAL MATCH (c)-[:IS_A]->(t:Wiki) "
        "OPTIONAL MATCH (c)-[:HAS_CONTENT]->(k:Wiki) "
        "RETURN c.n AS name, collect(DISTINCT t.n) AS types, c.repo AS repo, "
        "c.module AS module, head(collect(DISTINCT k.d)) AS content, "
        "head(collect(k.linked)) AS linked",
        {"name": concept_name})
    if not (res.get("success") and res.get("data")):
        return None
    row = dict(res["data"][0])
    row["content"] = verbatim_text(row.get("content"), row.pop("linked", None))
    return row


def _project(concept_name, kind, expect_type, label, shared_connection=None):
    """Read one doc-layer concept and diff-write its projection.

    Args:
        concept_name: The carton node name the release effect named.
        kind: MIRROR_DIR or VISION_DIR.
        expect_type: The type the concept must claim for this lane.
        label: The lane name used in every returned sentence.
        shared_connection: The daemon's neo4j connection, or None.

    Returns:
        str: What happened, always naming the concept and never raising.
    """
    try:
        row = read_concept(concept_name, shared_connection=shared_connection)
    except Exception as exc:                      # noqa: BLE001 - a projector never raises
        return "%s skipped: %s could not be read: %s" % (label, concept_name, exc)
    if not row:
        return "%s skipped: %s not found" % (label, concept_name)
    if expect_type not in (row.get("types") or []):
        return "%s skipped: %s does not claim is_a %s" % (label, concept_name, expect_type)
    content = row.get("content")
    if not (content or "").strip():
        return "%s skipped: %s holds no content node text" % (label, concept_name)
    project = repo_root(row.get("repo"))
    if not project:
        return "%s skipped: %s names repo %r, which resolves to no directory" % (
            label, concept_name, row.get("repo"))
    path = target_path(project, row.get("module"), kind)
    if path is None:
        return "%s skipped: %s names module %r, which is not inside %s" % (
            label, concept_name, row.get("module"), kind)
    if kind == VISION_DIR and path.exists():
        return (
            "doc(v) refused: %s already exists and the JOURNAL CLI owns it. A vision FILE is a "
            "header seeded from the paired doc(m) plus a DELTA marker plus every id-tagged "
            "append, while ONE Doc_Mirror_Vision concept is ONE entry — so writing this concept "
            "over that file destroys the header and every other entry (measured: 34 lines "
            "replaced by 1). The concept becomes the truth, and this lane becomes free to write, "
            "only once the journal write EXTRACTS into Doc_Mirror_Vision instead of appending "
            "(issue #669 act three). Replace-before-remove: build the replacement, prove it, "
            "THEN demote the file." % path
        )
    try:
        if path.exists() and path.read_text(encoding="utf-8", errors="replace") == content:
            return "%s unchanged: %s" % (label, path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        return "%s skipped: %s could not be written: %s" % (label, path, exc)
    return "%s projected: %s -> %s" % (label, concept_name, path)


def project_doc_mirror_module(concept_name, shared_connection=None):
    """release_effect entrypoint for dchain_doc_mirror_module_project.

    Args:
        concept_name: The Doc_Mirror_Module node the effect fired on.
        shared_connection: The daemon's neo4j connection, or None.

    Returns:
        str: What happened, always naming the concept and never raising.
    """
    return _project(concept_name, MIRROR_DIR, MODULE_TYPE, "doc(m)",
                    shared_connection=shared_connection)


def project_doc_mirror_vision(concept_name, shared_connection=None):
    """release_effect entrypoint for dchain_doc_mirror_vision_project.

    Args:
        concept_name: The Doc_Mirror_Vision node the effect fired on.
        shared_connection: The daemon's neo4j connection, or None.

    Returns:
        str: What happened, always naming the concept and never raising.
    """
    return _project(concept_name, VISION_DIR, VISION_TYPE, "doc(v)",
                    shared_connection=shared_connection)
