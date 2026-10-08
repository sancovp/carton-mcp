# carton_linker

## THE LINKER NEVER LINKS ITS OWN OUTPUT
A description that has already been linked is not linked again. A match falling INSIDE an existing link
target is never wrapped a second time.
A node's stored description stays its WORDS, and link markup never becomes the bulk of its bytes.
THE SKIP FLAG IS WRITTEN AT CREATION, WHERE IT PREVENTS THE PASS. A flag written after the linking pass
records only that linking happened and gates nothing. One flag never carries both meanings.
A search predicate over a stored description matches the words it holds, never markup a pass left behind.

## THE LINKER NEVER SPLITS A TOKEN AT A CLOSING PARENTHESIS
A token ending in a closing parenthesis is linked whole or not at all: `doc(v)` stays `doc(v)`, and no
link is cut through the middle of a token.

## A journal entry is stamped within seconds of its write
The linker stamps a newly written journal entry regardless of what else is being written at the same
time. A continuously-writing lane does not starve entries of an older write time.

## The unlinked backlog is visible on a status readout
The count of nodes written and not yet stamped is readable on a status surface.
