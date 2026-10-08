# webbing_agent — status
source: doc-mirror-system/docs/vision_extracted/webbing_agent.md
sealed boundary: webbing_agent (hand-mapped by Claude 2026-09-25, MiniMax Token Plan spent for the week)
code read: knowledge/carton-mcp/webbing_agent.py (whole, 515); knowledge/carton-mcp/webbing_agent_worker.py (whole, 275); doc-mirror-system/sophia/docmirror-cohere (whole, 566); sophia-status run 2026-09-25 23:14 (webber lane LIVE, 12300 pending). Not read: carton_utils.set_concept_properties, observation_worker_daemon CHAT_SOURCES and compute_description_score, Daemon_Webbing_Agent_Design., 275)

## THE WEBBER IS THE ENCAPSULATION ENGINE
| # | requirement | cases followed | where each is decided (path:line) | what happens to each case | verdict |
|---|---|---|---|---|---|
| 1 | The webber sees that a final contextual thing closing a fiat boundary was added, REIFIES that fiat boundary as a concept, and that concept becomes the highest-level thing pulled during rehydration. | what the webber serves and does | webbing_agent.py:280-302 _next_batch serves linked, chat-sourced, un-webbed concepts that are under-developed; 160-198 the goal asks for is_a, part_of, instantiates, produces and child concepts | the webber atomizes under-developed concepts; nothing detects a fiat boundary closing or reifies one | REMAINING |

## A FIAT BOUNDARY CLOSES WHEN THE LAST THING THAT COMPLETES IT ARRIVES
| # | requirement | cases followed | where each is decided (path:line) | what happens to each case | verdict |
|---|---|---|---|---|---|
| 2 | A fiat boundary is one we DRAW rather than one reality supplies: a sprint, a thread, an arc, a phase. | any notion of a drawn boundary (sprint, thread, arc, phase) | webbing_agent.py:1-515 and webbing_agent_worker.py:1-275 | neither file models a fiat boundary | REMAINING |
| 3 | Nothing physical closes them, so their closure is a fact about the GRAPH. | where a boundary's closure would be recorded | webbing_agent.py:374-401 the only graph fact the webber computes is whether a served concept improved | no closure fact is computed over the graph | REMAINING |

## DETECTION IS PROGRAMMATIC, NEVER A JUDGMENT
| # | requirement | cases followed | where each is decided (path:line) | what happens to each case | verdict |
|---|---|---|---|---|---|
| 4 | Closure is COMPUTED from the inheritance graph: when everything that must be `part_of` X exists and is itself closed, X is closed. | computing closure from part_of | webbing_agent.py:289-302 and 389-395 the predicates read score and outgoing edge counts, never part_of completeness | no inheritance-graph closure computation exists | REMAINING |
| 5 | The webber does not decide that a sprint ended. | who decides a boundary ended | no closure mechanism exists (rows 3-4) | the programmatic closure this row constrains is not built | REMAINING |
| 6 | It is an absorber, not a procedure an agent has to remember. | how the lane runs | webbing_agent_worker.py:202-218 a PID-locked daemon ticks catch_up_once every interval; 221-231 ensure_running launches it; the sophia daemon ensures it (sealed boundary user action) | the webber runs as a daemon, not as a procedure an agent must remember | BUILT |

## The loop
| # | requirement | cases followed | where each is decided (path:line) | what happens to each case | verdict |
|---|---|---|---|---|---|
| 7 | Work is webbed AS IT HAPPENS. | (a) the daemon cadence; (b) which concepts it takes first | webbing_agent_worker.py:202-218 ticks every 60s by default (42); webbing_agent.py:298 ORDER BY c.t ASC takes the oldest first; sophia-status 23:14 showed 12300 pending | the lane runs continuously, but new work waits behind the oldest backlog rather than being webbed as it happens | PARTIAL |
| 8 | The webber watches the webbing. | how the webber tracks webbing state | webbing_agent.py:293-300 and 348-354 select and count on linked, source, webbed, score and outgoing edge count; 374-401 re-check after a run | the webber watches each concept's webbing state on every tick | BUILT |
| 9 | On the write that completes a fiat boundary, it recognizes the closure and reifies the containment. | the write that completes a boundary | no closure recognition exists (rows 1-4) | nothing recognizes closure or reifies containment | REMAINING |
| 10 | The containment is the highest-level abstraction for that set, and that is what rehydration pulls. | what rehydration pulls | the webber writes no containment concept (rows 1, 9) | no webber-made containment exists for rehydration to pull | REMAINING |

## THE HYGIENE HALF IS THE INPUT TO THE ENCAPSULATION HALF
| # | requirement | cases followed | where each is decided (path:line) | what happens to each case | verdict |
|---|---|---|---|---|---|
| 11 | Referent-completeness — every referent an entry names is a real node, every path it cites resolves — is what makes closure computable over the inheritance graph. | (a) referent completeness; (b) closure computed from it | the webbing gate lives in doc-mirror-system/plugin/bin/docmirror-webbing (the forced_webbing boundary), not in the webber; the webber computes no closure | referent completeness exists as a separate gate, and nothing computes closure from it | PARTIAL |
| 12 | They are one mechanism, not two concerns. | whether hygiene and encapsulation are one mechanism | webbing_agent.py imports nothing from docmirror-webbing and docmirror-webbing is a separate CLI | they are two separate programs | REMAINING |

## The webber WRITES
| # | requirement | cases followed | where each is decided (path:line) | what happens to each case | verdict |
|---|---|---|---|---|---|
| 13 | The encapsulation engine writes rather than running dry. | dry vs live | webbing_agent_worker.py:141-144 live when live.flag exists or WEBBING_AGENT_LIVE is set; 158-161 dry otherwise; sophia-status 23:14 reported the lane LIVE | the webber writes when live, and the live flag is on | BUILT |

## A BOOKKEEPING FLAG TAKES THE SCRATCH LANE
| # | requirement | cases followed | where each is decided (path:line) | what happens to each case | verdict |
|---|---|---|---|---|---|
| 14 | Marking a concept examined-and-sufficient records the webber's own pass over it and claims nothing about the ontology, so it takes the direct property write and emits no per-concept validator trail. | how webbed is written | webbing_agent.py:328 and 398 set_concept_properties(name, webbed True, merge); set_concept_properties itself was not read | the flag goes through the property writer; whether that writer emits a validator trail for an ontology-bearing concept is decided in carton_utils, not read here | UNKNOWN |
| 15 | A tick that marks many concepts writes them as ONE batch, never as one event each. | marking many concepts in one tick | webbing_agent.py:396-400 one set_concept_properties call per concept; 326-332 the same in _mark_examined_and_sufficient | each concept is its own write, never one batch | REMAINING |

## A COUNT THE LANE REPORTS IS MEASURED ON THE CALL THAT REPORTS IT
| # | requirement | cases followed | where each is decided (path:line) | what happens to each case | verdict |
|---|---|---|---|---|---|
| 16 | A caught-up return states the real pending count, never a constant. | a caught-up or empty-batch return | webbing_agent.py:423-435 an empty batch returns _pending_count measured on that call; 444-445 and 478-479 the other returns also call _pending_count | every return states the count measured on the call | BUILT |
| 17 | A pending count that fails to compute is reported as UNKNOWN pending, never as a lane failure. | (a) the count raising; (b) the count query failing | webbing_agent_worker.py:132-138 an exception returns -1 and 155-157 writes error pending dry-run failed with caught_up False; webbing_agent.py:109-111 _q returns an empty list on a failed query, so 355 returns 0 | (a) is reported as a lane error, not UNKNOWN pending; (b) reads as 0 pending and the worker writes caught_up True (152-154) | REMAINING |
| 18 | The model the webber is invoked with is the model the webber's own spec names. | the model the webber runs with | webbing_agent.py:77 DEFAULT_MODEL MiniMax-M2.7-highspeed; webbing_agent_worker.py:254 the same default; the webber's own spec concept was not read | the model is fixed in code; whether it matches the model the webber's spec names is not decided here | UNKNOWN |
| 19 | The record a tick writes REPLACES the record of the tick before it, or each key carries the time it was taken. | how a tick record is written | webbing_agent_worker.py:94-102 _write_state reads the old state and update()s it, stamping one heartbeat; 180-182 a successful tick never clears an error key an earlier tick wrote | keys from earlier ticks survive beside new ones, and no key carries its own time | REMAINING |
| 20 | A healthy pair from an early tick never stands beside an error from a later one. | a later tick failing after an earlier healthy one | webbing_agent_worker.py:175 the error path writes caught_up False and error but leaves mode, processed_total and pending from the earlier tick | an earlier healthy pending and mode stand beside the later error | REMAINING |

## THE LANE CALLS ITS FUNCTION AND DOES NOT LAUNCH A PROCESS TO REACH IT
| # | requirement | cases followed | where each is decided (path:line) | what happens to each case | verdict |
|---|---|---|---|---|---|
| 21 | A worker reaching a function in its own package calls it directly, with no subprocess and no timeout on that path. | (a) the pending count; (b) the work run | webbing_agent_worker.py:132-134 imports _pending_count and calls it directly; 165-168 runs the webbing agent through subprocess.run with a timeout of cap times TICK_TIMEOUT_S | the count path calls the function; the work path still launches a process with a timeout | PARTIAL |
| 22 | A DRAIN REPORTS WHETHER IT CONVERGES, never only its depth: a lane completing fewer items than arrive reports LOSING. | whether a drain says it converges | webbing_agent.py:448-479 loop reports batches, webbed and pending; webbing_agent_worker.py:180-183 records pending_after | depth is reported, but no verdict compares completions against arrivals or says LOSING | REMAINING |

## THE WEBBER ONLY ADDS
| # | requirement | cases followed | where each is decided (path:line) | what happens to each case | verdict |
|---|---|---|---|---|---|
| 23 | The webbing agent writes only new nodes and new triples and never edits one. | (a) served descriptions; (b) deletion; (c) the flag on served concepts; (d) the tool surface | (a) webbing_agent.py:183-189 and 216-221 omit the concept argument on a served concept; (b) 190 and 222-223 forbid deletion in the prompt; (c) 398 sets webbed on existing nodes; (d) 265-274 passes no mcp_tool_allowlist, unlike SOPHIA's fence | descriptions are kept and deletion is forbidden by prompt, but existing nodes are edited with a flag and no fence withholds any carton mutator | PARTIAL |
| 24 | A wrong node gains `is_a WrongThing` and a `wrong_because` edge pointing at its evidence. | a wrong node | webbing_agent.py:160-232 the goal and prompt name no WrongThing type and no wrong_because edge | wrong nodes are not typed or evidenced | REMAINING |
| 25 | Its edge vocabulary is fixed and typed: `about`, `relates_to`, `wrong_because`, `cause_category`, `supersedes`, `depends_on`, `evidence_for`. | the edge vocabulary | webbing_agent.py:176-182 and 211-214 ask for is_a, part_of, instantiates, produces and child concepts | the fixed vocabulary about, relates_to, wrong_because, cause_category, supersedes, depends_on, evidence_for is not named anywhere | REMAINING |

## THE WEBBER FINDS TWO KINDS OF REFERENT
| # | requirement | cases followed | where each is decided (path:line) | what happens to each case | verdict |
|---|---|---|---|---|---|
| 26 | THINGS are named nouns, named as `this_qua_that`. | how things are named | webbing_agent.py:160-232 | no this_qua_that naming is asked for | REMAINING |
| 27 | HAPPENINGS are a relation among several named things occurring in the text with NO node — a hyperedge that is not reified. | a relation among several named things with no node | webbing_agent.py:160-232 | happenings are not identified | REMAINING |
| 28 | A happening is REIFIED as a concept whose node is an object referring to that morphism. | reifying a happening | webbing_agent.py:160-232 | happenings are not reified | REMAINING |
| 29 | The webber loops over a description until it names nothing unreified. | when the webber stops on a concept | webbing_agent.py:229-231 the prompt bounds it by its own turns; 389-395 a concept is marked webbed once its score and edge count clear the thresholds | it stops on a score threshold and turn bound, not when the description names nothing unreified | REMAINING |
| 30 | A concept's webbing score is derived from its description. | where the webbing score comes from | webbing_agent.py:130-148 _is_underdeveloped calls compute_description_score(description, concept_cache); 339-346 the selection reads c.score, the same score D2 stores at write time | the score is derived from the description | BUILT |

## THE WEBBING REACHES THE TASK QUEUE
| # | requirement | cases followed | where each is decided (path:line) | what happens to each case | verdict |
|---|---|---|---|---|---|
| 31 | Cards and the types they carry are webbed until what the agent is doing is clear. | cards and their types | webbing_agent.py:291-294 selection requires c.source IN CHAT_SOURCES; the source a card is written with and CHAT_SOURCES itself were not read | whether cards are ever served is not decided in the files read | UNKNOWN |

## WEBBING A CONCEPT AUTHORS ITS RETRIEVAL STATE MACHINE
| # | requirement | cases followed | where each is decided (path:line) | what happens to each case | verdict |
|---|---|---|---|---|---|
| 32 | When the webber webs a concept it authors a retrieval state machine for understanding that concept. | a retrieval state machine for a webbed concept | webbing_agent.py:160-232 | no state machine is authored | REMAINING |

## THE EMBEDDING TEXT IS VARIED PROSE
| # | requirement | cases followed | where each is decided (path:line) | what happens to each case | verdict |
|---|---|---|---|---|---|
| 33 | The coherer generates varied natural-language prose from a concept's relationships for the chroma embedding, never a deterministic template. | the text sent to the chroma embedding | neither webbing_agent.py nor docmirror-cohere builds embedding text; the chroma embedding writer was not read | not decided in the files read | UNKNOWN |

## SOPHIA IS NEVER CHANGED TO DO THE WEBBING, AND THE TWO RUN CONCURRENTLY
| # | requirement | cases followed | where each is decided (path:line) | what happens to each case | verdict |
|---|---|---|---|---|---|
| 34 | SOPHIA keeps her ONE write, the momentum observation, and connects entities by `contextualized_by` to EXISTING nodes. | SOPHIA's writes and her edges | docmirror-cohere:311-316 her only add_concept is her own observation; 351-369 the fence withholds every other mutator; 270-283 contextualized_by points at existing nodes | SOPHIA keeps her one write and edges only to existing nodes | BUILT |
| 35 | CONCEPTUALIZING WHAT A DESCRIPTION NAMES IS THE WEBBER'S WORK AND NEVER HERS. | who conceptualizes what a description names | docmirror-cohere:311-316 and 351-369 forbid and fence SOPHIA from minting; webbing_agent.py:202-232 the webber creates the structure and children | conceptualizing is the webber's and never SOPHIA's | BUILT |
| 36 | Both run concurrently, each on demand or by a daemon called whenever its condition holds. | (a) how each runs; (b) on demand | sophia-status 23:14 showed the sophia daemon pid 17058 and the webber worker pid 95654 both running; webbing_agent_worker.py:202-218 and 257-262 daemon or --catch-up; docmirror-cohere:553-561 --once, --loop, --prompt-file | both run concurrently from daemons and each can be run on demand | BUILT |

## THE WEBBER SAYS WHAT A THING IS AND NEVER INVENTS A PARENT OR A CHILD
| # | requirement | cases followed | where each is decided (path:line) | what happens to each case | verdict |
|---|---|---|---|---|---|
| 37 | INVENTING CHILD CONCEPTS OR PARENT CONCEPTS IS RELATIVE. | what the webber is asked to create | webbing_agent.py:178-179 and 211-212 identify the structure and any CHILD concepts the prose describes that do not exist yet | it creates children, bounded to what the prose describes | PARTIAL |
| 38 | What matters is making the graph TRAVERSABLE by adding everything to it and relating it properly. | what the webber adds | webbing_agent.py:176-189 add is_a, part_of, instantiates, produces as lists and child concepts for every served concept | it adds structure and relates each concept | BUILT |
| 39 | It does not make things up. | what bounds the webber's additions | webbing_agent.py:178 structure the prose IMPLIES; 229-231 atomize what the served prose genuinely implies | the prompt bounds it to the served prose | BUILT |
| 40 | It says what the thing IS, in the form THIS_QUA_THAT, and a `this_qua_that` changes over time. | the name form | webbing_agent.py:160-232 | no this_qua_that form is asked for and nothing tracks a name changing over time | REMAINING |
| 41 | A name carrying two senses resolves as two qua-named things rather than one colliding stub. | a name carrying two senses | webbing_agent.py:160-232 | nothing splits a name into two qua-named things | REMAINING |
| 42 | A STUB WHOSE CONTENT ALREADY STANDS SOMEWHERE IS FILLED FROM THAT PLACE, NEVER DESCRIBED AFRESH. | a stub whose content stands elsewhere | webbing_agent.py:183-189 a new child gets a fresh description written by the agent; nothing looks up where its content already stands | stubs are described afresh, never filled from their source | REMAINING |
| 43 | An auto-created node that an entry names while carrying its full statement is promoted by webbing that statement onto it. | an auto-created node an entry names with its full statement | webbing_agent.py:291-294 only linked, chat-sourced concepts are served; nothing reads the entry that names a stub | no path promotes such a node by webbing the entry's statement onto it | REMAINING |

counts: BUILT 10 · PARTIAL 5 · REMAINING 24 · UNKNOWN 4
<!-- map 10e03c1ce0dc -->
