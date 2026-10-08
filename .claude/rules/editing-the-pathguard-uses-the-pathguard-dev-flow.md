When you are about to edit `carton_pathguard.py` (`check_write` / `sanctioned_roots` / `wiki_root` /
`detect_path_artifacts` / `CartonPathRefused`), any of its three guarded call sites
(`substrate_projector.project_to_file`, `server_fastmcp.add_document_concept`,
`observation_worker_daemon.create_wiki_files_for_concepts`), `test_carton_pathguard.py`, or the
`$CARTON_DOC_ROOTS` and wiki-root semantics — you MUST FIRST read the `carton-pathguard` rule in this
directory and do its COMPLETE dev-flow edit-set, then its gate: 5 markers, the breaker regression floor,
install, daemon restart. NEVER edit one place only.

Why it exists, the laws and the states: `.claude/rules/carton-pathguard.md` (issue #206).
