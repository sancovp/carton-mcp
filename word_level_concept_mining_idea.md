# Word-Level Concept Mining for Carton

## Overview

Automatic word-level concept mining system that creates a comprehensive semantic dictionary from all ingested content, with blacklist management and concept ablation capabilities.

## Core Algorithm

### Auto-Ingestion Process
1. **Tokenize all content** → split on spaces, extract meaningful words
2. **Match against existing concepts** → check each word against Carton concept database  
3. **Create word concepts** → auto-generate concept for each unique word
4. **Build relationships** → create `contains_word` and `mentioned_in` relationships
5. **Flag for definition** → mark new word concepts as `requires_definition`

### Relationship Structure
```
IO_Pair_001 --contains_word--> "SEED"
IO_Pair_001 --contains_word--> "parser" 
IO_Pair_001 --contains_word--> "ingestion"

"SEED" --mentioned_in--> [IO_Pair_001, IO_Pair_047, IO_Pair_203]
"parser" --co_occurs_with--> ["SEED", "JSON", "metadata"]
```

## Blacklist System

### Purpose
Prevent noise concepts from overwhelming the knowledge graph with common, non-meaningful words.

### Implementation
- **Common words blacklist**: `the`, `and`, `a`, `is`, `to`, `of`, etc.
- **Dynamic blacklisting**: ability to add words that prove non-valuable over time
- **Context-aware filtering**: same word might be blacklisted in some contexts but not others

### Blacklist Storage
```json
{
  "global_blacklist": ["the", "and", "a", "is", "to", "of", "for", "with"],
  "domain_blacklist": {
    "technical": ["like", "just", "really", "pretty"],
    "conversational": ["um", "uh", "well", "actually"]
  },
  "user_blacklist": ["custom", "words", "to", "ignore"]
}
```

## Concept Ablation (The Hard Part)

### Challenge
Removing concept nodes from both the file system and Neo4j while maintaining graph integrity.

### Required Operations
1. **Cascade deletion** → remove all relationships involving the concept
2. **Reference updating** → update markdown links that pointed to deleted concept
3. **Git operations** → remove concept files and commit changes
4. **Neo4j cleanup** → remove nodes and relationships from graph database
5. **Integrity checking** → ensure no orphaned references remain

### Implementation Complexity
- **File system sync** → keeping Git repo and Neo4j in sync during deletions
- **Relationship cascading** → handling complex relationship networks
- **Rollback capability** → ability to undo ablation if needed
- **Batch operations** → efficiently removing multiple concepts at once

### Proposed Function Signature
```python
def ablate_concepts_by_keyword(
    keyword: str, 
    cascade: bool = True,
    dry_run: bool = False,
    backup: bool = True
) -> AblationResult:
    """Remove all concepts containing keyword from Carton system."""
```

## Benefits

### Automatic Semantic Discovery
- **No manual relationship definition** required
- **Emergent concept networks** through co-occurrence patterns
- **Timeline tracking** of concept evolution
- **Content discovery** capabilities

### Observable Intelligence Development
- **Vocabulary growth tracking** → see which terms emerge in thinking
- **Knowledge gap identification** → undefined words highlight learning opportunities
- **Semantic consistency** → ensure concepts have consistent meaning
- **Definition refinement** → iteratively improve concept clarity

### Query Capabilities
```cypher
// Find all concepts related to "content"
MATCH (content:Wiki {n: "content"})-[r]-(related:Wiki)
RETURN content, type(r), related

// Most frequently mentioned concepts
MATCH (w:Wiki)-[r:MENTIONED_IN]->(io:Wiki)
RETURN w.n, count(r) as mentions
ORDER BY mentions DESC

// Concept co-occurrence patterns
MATCH (a:Wiki)-[:MENTIONED_IN]->(same_io)<-[:MENTIONED_IN]-(b:Wiki)
WHERE a.n < b.n  // avoid duplicates
RETURN a.n, b.n, count(same_io) as co_occurrence
ORDER BY co_occurrence DESC
```

## Implementation Priority

**Phase 1** (Skip for now): Core word mining algorithm
**Phase 2** (Complex): Blacklist management system  
**Phase 3** (Very Hard): Concept ablation with cascade deletion

## Why Skip For Now

The ablation system requires:
- Complex file system and database synchronization
- Sophisticated relationship cascade logic
- Robust error handling and rollback mechanisms
- Extensive testing to avoid data corruption

This level of complexity warrants dedicated development time when the core SEED publishing platform is complete.

## Future Integration

This system would integrate with SEED publishing by:
1. **Auto-mining words** during QA ingestion
2. **Queuing definitions** for high-frequency undefined words
3. **Enhancing search** through semantic relationships
4. **Building timeline** of concept emergence and evolution

The result: a self-expanding dictionary of compound intelligence vocabulary with automatic relationship discovery and definition prioritization.