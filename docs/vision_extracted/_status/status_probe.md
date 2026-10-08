# status_probe — status
source: doc-mirror-system/docs/vision_extracted/status_probe.md
sealed boundary: status_probe (hand-mapped by Claude 2026-09-25, MiniMax Token Plan spent for the week)
code read: knowledge/carton-mcp/gnosys_status_probe.py (whole, 249); knowledge/carton-mcp/test_gnosys_status_probe.py (whole, 113); seem show status_probe

## THE PROBE HAS A TRIGGER
| # | requirement | cases followed | where each is decided (path:line) | what happens to each case | verdict |
|---|---|---|---|---|---|
| 1 | Something CALLS the probe on a cadence. | what invokes the probe | gnosys_status_probe.py:222-245 main runs once per invocation; the sealed boundary's user action is an operator or the agent running the script | nothing calls the probe on a cadence; it runs only when someone runs it | REMAINING |
| 2 | A frozen status value is never rendered as current. | a written status value read later | gnosys_status_probe.py:203-219 write_back sets the values plus status_measured_at on Gnosys_System; nothing in the probe or its boundary reads them back or compares the stamp to now | the lane holds the last written values with no age check, so an old value reads the same as a fresh one | REMAINING |
| 3 | A d-chain runs the probe on every `get_concept` of `Gnosys_System` and refreshes its status lane. | a get_concept of Gnosys_System | gnosys_status_probe.py:199-200 probe is called only from main (230) | no d-chain runs the probe; a get_concept reads whatever was last written | REMAINING |

## A TIMEOUT IS NOT A DIAGNOSIS
| # | requirement | cases followed | where each is decided (path:line) | what happens to each case | verdict |
|---|---|---|---|---|---|
| 4 | The probe's deadline accommodates the time the real surface actually takes to answer. | (a) SOMA /event; (b) chroma /health; (c) neo4j | gnosys_status_probe.py:48 SOMA_EVENT_TIMEOUT_S default 60s, passed at 107-108; 116 chroma uses the 4s _http default on a health route; 124-137 neo4j a 3s port check then a count query with the driver's own timeout | each deadline covers the time its route takes to answer | BUILT |
| 5 | A slow answer is reported as SLOW, never as DOWN. | (a) SOMA answering late; (b) chroma answering late | gnosys_status_probe.py:109-111 SOMA with the port open and no answer in budget returns degraded, UP but not serving, NOT dead; 116-118 chroma with no answer inside 4s returns down | SOMA reports slowness as degraded, chroma reports the same slowness as down | PARTIAL |

## THE PROBE ASKS THE ENDPOINT THE SYSTEM ITSELF USES
| # | requirement | cases followed | where each is decided (path:line) | what happens to each case | verdict |
|---|---|---|---|---|---|
| 6 | The probe calls the route the real callers call. | the route each check asks | gnosys_status_probe.py:107 SOMA POST /event, the route carton posts to; 116 chroma GET /health, the route the sophia daemon probes; 133 neo4j a real Cypher query over bolt; 140-142 the observation daemon is asked by pgrep, not by any route | three checks ask a route the system itself uses; the observation daemon check asks for a process | PARTIAL |
| 7 | A path no caller uses is not a route, and what it returns — an answer, a 404, or nothing at all — says nothing about whether the thing is serving. | the HTTP paths the probe calls | gnosys_status_probe.py:107 and 116 | both paths are routes a caller in the system already uses; the probe calls no unused path | BUILT |

## A LIGHT CALL IS REPRESENTATIVE
| # | requirement | cases followed | where each is decided (path:line) | what happens to each case | verdict |
|---|---|---|---|---|---|
| 8 | The probe carries an EMPTY BODY. | the SOMA call's body | gnosys_status_probe.py:107-108 posts source status_probe with an empty observations list | the probe carries an empty body | BUILT |
| 9 | It fails when real writes fail and never reports healthy while they are failing, so it costs no real workload to ask. | SOMA answering an empty event while real writes fail | gnosys_status_probe.py:66-67 any HTTP error code is returned as answered; 112 any code reads live | an answering /event reads live whatever its status, and nothing in the probe exercises a write, so it can report live while writes fail | REMAINING |

## AN ANSWER IS UP, WHATEVER ITS STATUS
| # | requirement | cases followed | where each is decided (path:line) | what happens to each case | verdict |
|---|---|---|---|---|---|
| 10 | Any reply, including an error status, means the socket is live and the route is reachable. | a 4xx or 5xx reply | gnosys_status_probe.py:66-67 HTTPError returns the code with reason answered; 112 and 119 any code reads live | any reply counts as the service up and the route reachable | BUILT |
| 11 | Only the absence of a reply is not an answer. | no reply | gnosys_status_probe.py:68-69 any other exception returns code None with its reason; 109-111 and 117-118 None becomes degraded or down | only the absence of a reply is treated as no answer | BUILT |

## LIVENESS IS NOT READINESS
| # | requirement | cases followed | where each is decided (path:line) | what happens to each case | verdict |
|---|---|---|---|---|---|
| 12 | The verdict comes from a TIMED CALL TO THE SERVING ENDPOINT. | how each verdict is reached | gnosys_status_probe.py:104-112 SOMA, 115-119 chroma and 122-137 neo4j make timed calls; 140-142 the observation daemon verdict comes from pgrep | three verdicts come from timed calls; one comes from a process listing | PARTIAL |
| 13 | A running process is not evidence that it serves: a probe reading a pid reports healthy through an outage in which the endpoint answers nothing. | a process that runs but does not serve | gnosys_status_probe.py:140-142 check_observation_daemon returns live when a process matches; 81-88 _pgrep | the observation daemon check reports live on a running process, which is exactly the pid evidence the row rules out | PARTIAL |
| 14 | The deadline allows for warm-up, so a restart is not read as an outage. | (a) SOMA warming up with its port open; (b) SOMA mid-restart with its port closed | gnosys_status_probe.py:109-111 port open without an answer reads degraded; 104-106 port closed reads down | warm-up with the port open is not read as an outage; a restart window with the port closed is read as down | PARTIAL |

## THE WRITER AND THE READER AGREE ON ONE RECORD
| # | requirement | cases followed | where each is decided (path:line) | what happens to each case | verdict |
|---|---|---|---|---|---|
| 15 | The tick WRITES and the surface READS one record shape: the verdict, the time the reading was taken, the latency, the endpoint that was asked, the recent readings, and the error text when the verdict is bad. | what the write records | gnosys_status_probe.py:209 keeps only the verdict value of each (value, detail) pair; 210-212 add status_measured_at, status_measured_by and status_unprobed | no latency, no endpoint, no recent readings and no error text are written, and there is no tick writing on a schedule | REMAINING |
| 16 | Neither side redesigns it. | a shared record contract between a writer and a reader | gnosys_status_probe.py:203-219 is the only writer in the boundary and no reader is part of it | no agreed record shape exists for either side to keep | REMAINING |

## COULD-NOT-TELL IS DECIDED BEFORE THE VERDICT IS READ
| # | requirement | cases followed | where each is decided (path:line) | what happens to each case | verdict |
|---|---|---|---|---|---|
| 17 | A reading that is MISSING, UNREADABLE, UNSTAMPED or STALE answers UNKNOWN, and each of those is settled BEFORE the stored verdict field is ever consulted. | a missing, unreadable, unstamped or stale reading | no reader in gnosys_status_probe.py; the boundary releases at write_back and main (199-249) | nothing decides UNKNOWN before consulting a stored verdict | REMAINING |
| 18 | UNKNOWN is first-class and collapses into neither of the others, so a stale healthy reading can never render as healthy. | the verdict vocabulary | gnosys_status_probe.py:106-173 each check returns live, down, degraded, enforced, absent, disabled or enabled; unprobed appears only when the uniqueness check cannot reach the graph (172) and in UNPROBED (192-196) | there is no UNKNOWN verdict for a reading that could not be trusted | REMAINING |

## A READING CARRIES ITS AGE AND ITS TREND
| # | requirement | cases followed | where each is decided (path:line) | what happens to each case | verdict |
|---|---|---|---|---|---|
| 19 | The AGE of the reading is a FIELD beside the verdict, never a footnote, because this verdict is always from the past. | where the reading's time lives | gnosys_status_probe.py:210 one status_measured_at for the whole run | one run stamp exists, but no age field sits beside each verdict | PARTIAL |
| 20 | Recent readings are carried as a TREND and REPORTED rather than judged. | recent readings | gnosys_status_probe.py:199-219 each run overwrites the lane with one reading | no trend is kept | REMAINING |
| 21 | A single slow reading is warm-up, not an outage. | (a) one slow SOMA reading; (b) a trend of readings | gnosys_status_probe.py:109-111 a slow SOMA reads degraded, not down; no trend exists (row 20) | a single slow reading is not called an outage, but there is no trend to read it against | PARTIAL |
| 22 | EACH READING IN THE TREND CARRIES ITS OWN TIME, so the onset of a degradation is readable from the trend rather than bounded by the probe interval. | the time of each reading in a trend | no trend exists (row 20) | nothing carries per-reading times | REMAINING |
| 23 | There is deliberately NO process field, since a process reads healthy straight through this outage. | a process field | gnosys_status_probe.py:140-142 and 179 observation_daemon is a process check in CHECKS | the record carries a process field | REMAINING |

## A REGISTRY NAMES WHAT MUST BE UP
| # | requirement | cases followed | where each is decided (path:line) | what happens to each case | verdict |
|---|---|---|---|---|---|
| 24 | A declared registry names every system expected online — process, port, daemon, and a freshness signal such as the newest ingested message — and the probe reports each UP or DOWN with when it last produced output. | the registry of what must be up | gnosys_status_probe.py:175-182 CHECKS names six checks; 192-196 UNPROBED names three it cannot perform | a declared registry exists, but no entry carries a freshness signal such as the newest ingested message, and no verdict carries when the thing last produced output | PARTIAL |

## NOTHING RUNNING IS STALE
| # | requirement | cases followed | where each is decided (path:line) | what happens to each case | verdict |
|---|---|---|---|---|---|
| 25 | Every running daemon and MCP is checked for staleness, its process start against its installed module's mtime, and a stale one is restarted at once, an MCP by reconnect. | a running daemon or MCP older than its installed module | nothing in gnosys_status_probe.py compares process start to module mtime or restarts anything | no staleness check exists | REMAINING |

## DISK HEADROOM IS A STATUS LINE AND A REAPER KEEPS IT
| # | requirement | cases followed | where each is decided (path:line) | what happens to each case | verdict |
|---|---|---|---|---|---|
| 26 | Disk headroom is a status line that warns before the filesystem fills. | disk headroom | gnosys_status_probe.py:175-182 CHECKS has no disk entry | no disk line exists | REMAINING |
| 27 | A reaper outside the agent's permission surface — a daemon or a SessionStart actuator — removes abandoned agent worktrees and read-once caches. | abandoned worktrees and read-once caches | nothing in gnosys_status_probe.py removes files; docmirror_session_start.py (read whole 2026-09-25) runs no reaper | no reaper exists in the probe or the SessionStart hook | REMAINING |

## THE VERDICT HAS THREE OUTCOMES
| # | requirement | cases followed | where each is decided (path:line) | what happens to each case | verdict |
|---|---|---|---|---|---|
| 28 | DOWN, LIVE, and DEGRADED. | the outcomes per check | gnosys_status_probe.py:104-112 SOMA and 122-137 neo4j return down, degraded or live; 115-119 chroma returns only live or down | two checks carry all three outcomes, chroma carries two | PARTIAL |
| 29 | DEGRADED means UP BUT NOT SERVING, and it is never DEAD. | what degraded means per check | gnosys_status_probe.py:110-111 SOMA degraded is listening but not serving, NOT dead; 137 neo4j degraded is port open but query failed; 168-169 uniqueness degraded is the constraint present with duplicated names | degraded means up but not serving for SOMA and neo4j, and a data-quality state for the uniqueness check | PARTIAL |
| 30 | Each outcome routes separately and no two of them collapse into one value. | the outcomes after the write | gnosys_status_probe.py:209 writes each verdict string unchanged, so the three stay distinct values; nothing in the boundary reads or routes on them | the values never collapse, but nothing routes each one anywhere | PARTIAL |
| 31 | `check_soma` reports a closed port as DOWN, an answering route as LIVE, and an open port whose route misses its budget as DEGRADED. | (a) port closed; (b) route answers; (c) port open and route misses its budget | gnosys_status_probe.py:104-106 down; 112 live; 109-111 degraded; test_gnosys_status_probe.py:42-65 pins all three | each case yields its stated outcome and the suite pins it | BUILT |
| 32 | That budget is `check_soma`'s own constant. | the budget check_soma uses | gnosys_status_probe.py:48 SOMA_EVENT_TIMEOUT_S, passed at 108; test_gnosys_status_probe.py:68-83 pins that check_soma passes that constant | the budget is check_soma's own constant | BUILT |

counts: BUILT 7 · PARTIAL 11 · REMAINING 14 · UNKNOWN 0
<!-- map 10e03c1ce0dc -->
