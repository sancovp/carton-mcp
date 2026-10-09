The node quota is the OPERATOR'S, never the package's: `application/carton-saas/metering/carton_quota.py`
(`check_quota` · `quota_limit` · the TTL-cached count) and `call_gate.py` (`gate(operation, params)`), reached by
CartON's API through `CARTON_CALL_GATE=call_gate:gate` in the box's worker env. Nothing in this package meters; a
limit a tenant can read, unset or edit is not a limit.

NO-OP UNLESS `CARTON_MAX_NODES` IS SET. Unset means no gate, no import, zero queries. A quota never appears uninvited.

THE LIMIT IS READ ONCE, FROM THE ENVIRONMENT THE BOX STARTED WITH. `call_gate` snapshots `os.environ` at load and
counts with that snapshot; a write into the worker's live environment — from the wire or from any operation — lifts
nothing (`substrate_projector` type `env` refuses in the serving process besides). A limit a tenant can write is not a
limit.

REFUSE GROWTH, NOT REFINEMENT. The gate fires on `add_concept` only. At or over quota, an `add_concept` of an
EXISTING concept still passes — `add_concept` is also the update path — and `set_properties` and every read pass at
any size; only a NEW concept raises `QuotaExceeded`, answered as 402 with the limit, the count and the upgrade path.

THE LIVE PATH IS THE ENFORCED PATH. The refusal fires at the door, before the operation runs, so it provably never
reaches the queue or the graph. Never enforce on a derived view.

ENFORCEMENT READS THE LIVE COUNT; BLACKBOX ONLY OBSERVES. Never conflate the two lanes.

BE LOUD ON GARBAGE. A non-integer or negative `CARTON_MAX_NODES` raises; a broken limit must never silently mean
unlimited. The count reads `query_wiki_graph`'s envelope and FAILS LOUD on a failed query: a meter that cannot count
must never fail open into "unlimited".

⚠ NEVER set `CARTON_MAX_NODES` on the owner's own carton. The live graph exceeds any test limit and it would start
refusing real writes.

Dev-flow, and NEVER edit one place only. Touching `check_quota` / `quota_limit` / the TTL cache (default 60s,
`CARTON_QUOTA_TTL_S`), or `call_gate.gate` → edit the metering module and the gate coherently, then the gate:
`python3 application/carton-saas/metering/test_carton_quota.py` all green AND `python3
application/carton-saas/metering/test_call_gate.py` (9/9 — the API refuses a new concept 402 at the limit, passes an
existing one and every other operation, and passes everything with no limit set) AND `py_compile` on both files.

Installed-package law: the metering ships in the box image (`box/Dockerfile` COPYs it to `/opt/metering`); a source
edit reaches a box only through `box/build-carton-box.sh` and a redeploy.

Known bound, named and accepted: the observation queue's own writers (`add_observation_batch`,
`observe_from_identity_pov`) reach the graph through `add_observation`, not through `add_concept`, so concepts
written that way are not metered at the door; a tier's limit means nothing for them until that path is gated too
(CartON SaaS's board, § THE BUILD).
