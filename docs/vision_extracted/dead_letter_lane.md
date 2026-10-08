# dead_letter_lane

## THE DEAD-LETTER PILE HAS A READER
The count of the condemned pile stands on a surface an operator looks at.
The readout counts the concepts still absent from the graph, never the payload files.

## A DEAD-LETTERED WRITE IS A FAILURE TO ITS WRITER
A write the graph dead-letters is reported to its writer as a failure, never as a success printed from its
flat-file destination.

## THE CONDEMNED PAYLOAD HAS A VERB THAT SHOWS IT
The reason a payload was condemned is readable through a verb naming that payload. A surface that COUNTS
the condemned set without showing one leaves opening the file by hand as the only way to read the reason
it already recorded.

## A PAYLOAD THE LANE ITSELF CALLS RETRYABLE IS RETRIED
A failure whose own recorded reason says it clears once another write lands is re-run when that write has landed, rather than waiting on a field a hand must flip. A retry that picks up only payloads someone marked fixed turns a TRANSIENT ORDERING failure into permanent loss of what the payload carried.

## NEVER-ATTEMPTED PAYLOADS ARE RE-QUEUED BY THEIR RECORDED REASON
The payloads in the failed pile that were never attempted are re-queued in bounded batches, selected by
their recorded reason string.
A failed population whose reason is unexplained is never bulk-retried.
Each historical dead-letter payload is examined and either replayed or condemned with a recorded reason.

## A DEAD LETTER IS REPLAYED ONCE PER CONCEPT, ONLY WHEN ITS CONCEPT IS ABSENT
The replay unit is the concept NAME, never the file: a name queued in several files is replayed once.
A payload is replayed only after checking that its concept is absent, so a replay never appends twice
onto an existing node.
The lost conversation-timeline payloads are recovered this way.
