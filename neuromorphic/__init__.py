"""carton neuromorphic computing SDK — the computer the reframe named.

"A knowledge graph represents; this thing RUNS." Core = computer.py over the
substrate port (substrate.py): InMemorySubstrate in the lab (a third
substrate — a real run), CartonSubstrate on the host (neo4j; never the lab).
SOMA side: soma_prolog/foundation/computer.py vaults these classes;
soma_prolog/computer_projector.py renders architecture-grain Prolog.
"""
from .substrate import Substrate, InMemorySubstrate, CartonSubstrate
from .computer import NeuromorphicComputer, Inhibited
from .dto import design_brain, Brain, APEX_PARTS
from .loops import (LearningMachine, SoftmaxBandit, argmax_weight,
                    Refusal, MockWarrantRefused)

__all__ = ["Substrate", "InMemorySubstrate", "CartonSubstrate",
           "NeuromorphicComputer", "Inhibited",
           "design_brain", "Brain", "APEX_PARTS",
           "LearningMachine", "SoftmaxBandit", "argmax_weight",
           "Refusal", "MockWarrantRefused"]
