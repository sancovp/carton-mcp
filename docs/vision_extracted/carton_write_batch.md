# carton_write_batch

## Every doc-mirror graph WRITE goes through carton
IT MUST NOT CALL INTO NEO4J. Every doc-mirror graph write goes through the carton write functions — `add_concept`, `set_properties`, `remove_relationship`, `add_to_collection` — and the neo4j driver import leaves doc-mirror entirely. `docmirror-cohere.grader.bak` is deleted. ONLY A WRITE THAT WOULD OTHERWISE BE PROCESSED TWICE TAKES THE QUEUE. A write DERIVED from records already graded takes it; a PRIMARY record, with nothing upstream of it already processed, takes the front door.

## The facade accepts a write
The carton facade carries the write verbs, so MERGE, CREATE, SET and DELETE have a carton route and no doc-mirror module keeps a bare driver for them.

## An unreachable store says NOTHING WAS WRITTEN
An unreachable store raises, prefixed with the calling CLI's name and saying nothing was written. THE CATCH NAMES EVERY CLASS OBJECT THE LANE CAN RAISE.

## THE REMAINING SET IS PINNED BY NAME IN THE GATE
The same suite asserts that every doc-mirror graph write reaches a carton write function: `add_concept`, `set_properties`, `remove_relationship`, `add_to_collection`, `create_collection`, or the write batch.

## A HARNESS CARRIES A FAKE FOR EVERY LANE A CONVERTED MODULE CAN REACH
A converted module stops touching the lane the harness was faking, so a probe the old lane made safe
becomes a live write against the real store.
Which fake a write lands on is what says whether that module converted.
