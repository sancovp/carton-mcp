# status_probe

## THE PROBE HAS A TRIGGER
Something CALLS the probe on a cadence. A frozen status value is never rendered as current.
A d-chain runs the probe on every `get_concept` of `Gnosys_System` and refreshes its status lane.

## A TIMEOUT IS NOT A DIAGNOSIS
A slow answer is reported as SLOW, never as DOWN.

## THE PROBE ASKS THE ENDPOINT THE SYSTEM ITSELF USES
The probe calls the route the real callers call.

## A LIGHT CALL IS REPRESENTATIVE
It fails when real writes fail and never reports healthy while they are failing, so it costs no real workload to ask.

## LIVENESS IS NOT READINESS
The verdict comes from a TIMED CALL TO THE SERVING ENDPOINT. A running process is not evidence that it
serves: a probe reading a pid reports healthy through an outage in which the endpoint answers nothing.
The deadline allows for warm-up, so a restart is not read as an outage.

## THE WRITER AND THE READER AGREE ON ONE RECORD
The tick WRITES and the surface READS one record shape: the verdict, the time the reading was taken, the
latency, the endpoint that was asked, the recent readings, and the error text when the verdict is bad.
Neither side redesigns it.

## COULD-NOT-TELL IS DECIDED BEFORE THE VERDICT IS READ
A reading that is MISSING, UNREADABLE, UNSTAMPED or STALE answers UNKNOWN, and each of those is settled
BEFORE the stored verdict field is ever consulted.
UNKNOWN is first-class and collapses into neither of the others, so a stale healthy reading can never
render as healthy.

## A READING CARRIES ITS AGE AND ITS TREND
The AGE of the reading is a FIELD beside the verdict, never a footnote, because this verdict is always
from the past.
Recent readings are carried as a TREND and REPORTED rather than judged. A single slow reading is warm-up,
not an outage.
EACH READING IN THE TREND CARRIES ITS OWN TIME, so the onset of a degradation is readable from the trend
rather than bounded by the probe interval.
There is deliberately NO process field, since a process reads healthy straight through this outage.

## A REGISTRY NAMES WHAT MUST BE UP
A declared registry names every system expected online — process, port, daemon, and a freshness signal
such as the newest ingested message — and the probe reports each UP or DOWN with when it last produced
output.

## NOTHING RUNNING IS STALE
Every running daemon and MCP is checked for staleness, its process start against its installed module's
mtime, and a stale one is restarted at once, an MCP by reconnect.

## DISK HEADROOM IS A STATUS LINE AND A REAPER KEEPS IT
Disk headroom is a status line that warns before the filesystem fills.
A reaper outside the agent's permission surface — a daemon or a SessionStart actuator — removes abandoned
agent worktrees and read-once caches.

## THE VERDICT HAS THREE OUTCOMES
DOWN, LIVE, and DEGRADED. DEGRADED means UP BUT NOT SERVING, and it is never DEAD. Each outcome routes separately and no two of them collapse into one value.
