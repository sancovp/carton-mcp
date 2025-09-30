# Auto-Carton Timeline System Vision

## Overview

A real-time knowledge wikification system that automatically captures, synthesizes, and curates concepts from Claude Code conversations into a living knowledge graph.

## Core Architecture

### 1. Timeline Capture Layer

Every Claude Code session becomes a timeline entry in Carton:

```
MainAgentSessionsTimeline (root)
├── Daily_Timeline_2025_01_15
│   ├── Session_abc123_morning_coding
│   │   ├── UserPrompt_001
│   │   ├── ToolCall_002
│   │   └── AIResponse_003
│   └── Session_def456_afternoon_debug
└── Daily_Timeline_2025_01_16
```

Each session concept contains:
- Full conversation content
- Tool usage patterns
- Timestamp and duration
- **mentions** relationships to detected patterns

### 2. Pattern Detection & Quarantine

**Detection Process:**
1. PreCompact hook triggers after conversation
2. Scan for repeated phrases/concepts across timeline
3. Track frequency with fuzzy matching
4. When threshold hit (10+ mentions) → Quarantine

**Quarantine Structure:**
```json
{
  "concept": "debugging_startup_issues",
  "mentions": ["session_abc123", "session_def456"],
  "frequency": 12,
  "contexts": [...],
  "status": "pending_synthesis"
}
```

### 3. Brain Agent Synthesis

**Automatic Concept Definition:**
- Brain Agent receives all mention contexts
- Accesses existing wiki for relationship discovery  
- Synthesizes coherent definition from usage patterns
- Uses cheap LLM (gpt-5-mini) for cost efficiency

**Synthesis Query:**
```
Context: [all timeline mentions]
Pattern: "debugging_startup_issues"

Tasks:
1. Is this a coherent concept?
2. Define based on actual usage
3. Identify relationships from context
4. Create description for future reference
```

### 4. Approval Gate & Blacklist

**Quality Control:**
- Approval agent reviews quarantine queue
- Accept → Create real Carton concept
- Reject → Add to permanent blacklist

**Blacklist prevents:**
- Generic phrases ("the thing", "this stuff")
- Noise patterns
- False positives from casual language

### 5. Continuous Evolution

**Update Mechanism:**
- Track which mentions already processed per concept
- New mentions trigger re-synthesis
- Concepts evolve with expanded context
- Timeline provides full provenance

## Implementation Strategy

### Phase 1: Hook Integration
- Extend `conversation_intelligence.py` PreCompact hook
- Create timeline concepts for each session
- Add **mentions** relationships

### Phase 2: Pattern Detection
- Implement frequency counting with fuzzy matching
- Create quarantine directory structure
- Build detection thresholds

### Phase 3: Brain Agent Pipeline
- Configure Brain for concept synthesis
- Set up cheap LLM for processing
- Create approval agent workflow

### Phase 4: Sidecar Architecture
```
Claude Code → Hook → HTTP POST → Auto-Carton Sidecar
                                    ├── Pattern Detection
                                    ├── Brain Synthesis
                                    ├── Quarantine/Approval
                                    └── Concept Creation
```

## Why This Architecture?

### Intelligence vs Information
- **NOT RAG**: We don't want "everything mentioning X"
- **Graph Intelligence**: Meaningful relationships between concepts
- **Synthesis**: Brain Agent creates coherent definitions from usage
- **Provenance**: Every concept traces back to originating conversations

### Key Insights

1. **Graph > Embeddings** for structured knowledge
   - Explicit relationships are more valuable than similarity scores
   - Auto-linking creates natural connectivity
   - Neo4j queries give precise relationship traversal

2. **Whole Concepts as Units**
   - No chunking - entire `_itself.md` files as atomic units
   - Preserves semantic coherence
   - Clean retrieval of complete concepts

3. **Timeline as Foundation**
   - Every mention has full context
   - Pattern emergence from actual usage
   - Natural evolution of knowledge

4. **Quarantine for Quality**
   - Not everything deserves to be a concept
   - Human-in-the-loop for curation
   - Blacklist prevents noise accumulation

## Expected Outcomes

### Automatic Wiki Growth
- Conversations naturally build knowledge graph
- Concepts emerge from real usage patterns
- Definitions synthesized from actual context

### Zero Manual Curation
- Brain Agent handles synthesis
- Approval agent maintains quality
- Timeline provides automatic organization

### Complete Provenance
- Every concept links to originating sessions
- Full audit trail of knowledge creation
- Pattern evolution tracked over time

## Technical Requirements

### Dependencies
- Carton MCP with auto-linking
- Brain Agent for synthesis
- Neo4j for graph storage
- Conversation Intelligence hooks
- HTTP sidecar service

### Configuration
```python
AUTO_CARTON_CONFIG = {
    "frequency_threshold": 10,
    "synthesis_model": "gpt-5-mini",
    "approval_model": "gpt-4",
    "quarantine_path": "/tmp/carton_quarantine",
    "blacklist_path": "/tmp/carton_blacklist.json",
    "timeline_root": "MainAgentSessionsTimeline"
}
```

## Future Extensions

### Possible Enhancements
- Relationship type inference from usage patterns
- Concept clustering for domain detection
- Cross-user pattern aggregation
- Automatic concept deprecation for outdated patterns

### Explicitly Not Doing
- RAG/embeddings (graph is sufficient)
- Chunking (whole concepts only)
- Automatic acceptance (quarantine gate required)
- Real-time processing (batch via hooks is fine)

## Summary

This system creates a self-organizing knowledge graph that:
- Captures everything meaningful from conversations
- Synthesizes concepts from actual usage
- Maintains quality through approval gates
- Provides complete provenance and evolution tracking

The result: Your conversations automatically build a living, intelligent wiki without manual intervention, but with quality control to prevent noise.

## Isaac's Original Vision (Verbatim Messages)

### Initial Hook Concept
"im thinking about how to maybe add some claude code hooks for carton, so that we have everything making a timeline in carton. Hm... im thinking every user prompt, every tool call and result, every ai message by timestamp and session id... im wondering how to do this. can you read the claude code documentation? i think it would be that we would need to carton.add_concept for each thing obviously... and maybe we would have a schema for each one... im not sure..."

### Compact Hook Alternative
"ok the other thing we could do is potentially we could just add it thru the compact hook. Hmmmm... we made some claude code utils that turn a claude code conversation into a heaven format. Can you find that? i think it's in conversation intelligence. conversation intelligence is a dir in .claude/ or somewhere else im not sure"

### Timeline Hierarchy
"right, and then add the session to a MainAgentSessionsTimeline concept or something like that and start building out the automated logic so that carton automatically makes day by day timeline and stores everything in the timeline ultimately."

### Emergent Concept Detection
"QUESTION: How do we identify carton concepts emergently? i think we would need a fuzzy matcher and check for frequency and set threshold to like 10 mentions in the timeline == makes a concept automatically? so we run all entries thru the fuzzy matcher... wait carton already has auto linking but it lacks this fuzzy matching i think"

### Auto-Creation Capability
"no i think it WILL auto make Debugging_startup_issues if you say the sequence debugging startup issues a certain number of times in any one thing it scans. let's check the code at /home/GOD/carton_mcp"

### Provenance Insight
"ok but if we know which conversation parts are making these concepts then we have full references back to every mention. So this changes things i think"

### Real-Time Wikification Vision
"im thinking about like... what if we could somehow wiki-fy the entire conversation as it happens, smartly, and have it be right? we could pinpoint 'here are all the maybe references of this thing' and then 'here are all the real references of this thing' and then get the actual entry... we could actually use brain agent to do this filtering... hmmmm so some kind of auto-carton hooks plus automatic brain agent synthesizing the real concept entry and then updating the concept. Then you and I never have to add anything... and we can have it auto-updating as we go... it would just run as needed in a sidecar and we would ping the sidecar through http..."

### Complete Auto-Curation Pipeline
"ok so i think it would work like this. It would run the hooks, it would detect occurrences, it would auto-make concepts, and then mentions becomes a relationship we auto tag in the timeline convo part instance concepts. Then, the brain agent gets made with the aggregate, all the files that mention the thing we havent defined yet (we dont have a way to lift the definition, just what mentioned it) and then this AI also can access the rest of the wiki if needed to contextualize more. Then we log which mentions have already been used for that concept, and we update it whenever we get more. This just continually runs using a cheap LLM... BUT CRUCIALLY, after the hook runs, it has to enter the concepts to quarantine and then run an agent that reads thru the list and accepts or rejects concepts (and if it rejects, it blacklists them forever ie adds to blacklist)"

### Triple Knowledge Architecture
"Ok... this is starting to get good... i wonder also what it would be like to take the whole wiki and turn it into embeddings for RAG, so then we have RAG, the neo4j graph, and the actual files which all have links and relationships in them anyway"

### Whole-Concept Embeddings
"It would be like this. We would not want chunking -- we would want it to just take the entire _itself file as chunk length. Is that even possible?"

### Graph vs RAG Realization
"so wait let me think about what we would get from this. we would just get an injection of related files? but then that's very similar to just querying the graph for what's in network and then reading the files lol"

### Final RAG Rejection
"how would it work? if you said 'something about debugging' it owuld then pull everything which mentions debugging? that sounds awful for what we are talking about actually"