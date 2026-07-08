# AI Workflow Rules — carton-mcp (pointers)

## The KV dev-flow (mandatory for any CartonObj/KV edit)

- **Skill:** `.claude/skills/edit-carton-kv/` — the development-flow for the CartON KV / CartonObj capability: the COMPLETE distributed edit-set (carton_kv lib ↔ carton_utils wrappers ↔ server_fastmcp MCP tools ↔ the auto_link_description fence-opacity ↔ the daemon's two parse paths ↔ the is_schema schema graph), the deploy step, and the only valid E2E test.
- **Use-rule (enforcement):** `.claude/rules/editing-carton-kv-uses-the-dev-flow.md` — when touching `carton_kv.py`, the `edit_carton_obj`/`validate_carton_obj`/`get_concept`-expand tools, the linker masking, the daemon fence/desc-mode parse paths, or the schema registry: use the skill FIRST, do its Part-2 coherence set, then its Part-3 E2E gate. NEVER edit one place only.

## Managed docs are CLI-only

- `docs/mirror/**` (doc(m) = IMPL), `docs/vision/**` (vision(m) = VISION), `context/journal/**` (thinklog), `context/progress-tracker.md` are doc-mirror MANAGED files — read freely, but write ONLY through the doc-mirror CLIs; the `docmirror_readonly_guard` hook blocks hand-edits. A doc(m) is re-derived on module change and committed atomically with the code via `doc-mirror-commit <module> "<what>" ["<why>"] ["<origin>"]` (refuses a code change whose doc(m) was not re-derived; refuses code changes with no vision/bug origin).

## The journal CLI (the thinklog)

- Record every decision/finding/open fork the moment it happens: `journal -t <TYPE> --domain <D> --subdomain <SD> --tags <a,b> "<msg>"` (TYPES: INTENT / DECISION / OPEN / FINDING / HYPOTHESIS / VISION). It appends to `context/journal/YYYY-MM.md`, projects vision-types into `docs/vision/`, and dual-writes CartON SOUP nodes. `journal --where` prints targets. Full reference: `~/.claude/rules/use-the-journal.md`.

## Other repo-scoped rules (in `.claude/rules/`)

- `carton-mcp-transport.md` — stdio only; never SSE; no blocking import-level queries.
- `daemon-needs-env-vars.md` — the exact daemon restart command (env does not inherit).
- `mcp-reconnect-is-user-only.md` — after pip install: `reconnect_mcp carton`, never pkill.
