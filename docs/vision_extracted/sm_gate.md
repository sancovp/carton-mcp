# sm_gate

## A BRANCH WEIGHT IS REINFORCED ON A GOOD OUTCOME
A branch weight is reinforced when the branch leads to a good outcome, beyond the reinforcement on take.
The source of the good-outcome signal is a declared input of the state machine.

## A D-CHAIN TRIGGERS THE STATE MACHINE
A handler derives the state-machine steps from the verdict's fill list, one step per missing part, each step's required_pattern being the write that fills the part or the retrieval that informs it.
