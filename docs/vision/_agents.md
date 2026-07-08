# vision: hud-writer (topic — auto-created by `journal`)

<!-- ===VISION DELTA: id-tagged appends below = the gap (`vision diff <m>`); `doc-mirror-commit --realizes <ids>` drops them on build === -->
- [v1]  2026-06-10T16:59:14  FINDING: Narrate-then-stop RECURRED on the server_fastmcp doc(m) re-derivation writer even though its prompt explicitly said 'Do NOT end your turn before the Write succeeds' — agent ended with 'Now I'll write the updated doc(m)' and never wrote (file mtime + git status prove it). SendMessage kick issued to resume it. This confirms the queued hud-writer agent-definition fix is needed: the instruction-in-prompt mitigation is NOT reliable; the fix must live in the agent definition itself.  tags:[hud-writer, doc-mirror, agents]
