# Auto-Definition Agent for Word-Level Concept Mining

## Overview

An AI agent that automatically processes the definition queue from word-level concept mining, making intelligent decisions about which words to define, blacklist, or research further.

## Agent Decision Tree

```
New Word Discovered → Auto-Definition Agent
    ├─ Is this a common/obvious word?
    │   └─ YES → Add to blacklist, remove concept
    ├─ Is this a standard dictionary word used normally?
    │   └─ YES → Simple definition + blacklist future instances  
    ├─ Is this a custom/domain-specific term?
    │   ├─ Search all content for usage patterns
    │   ├─ Analyze context and meaning
    │   └─ Generate definition from usage examples
    └─ Is this a proper noun/name/reference?
        └─ Research and define or blacklist if not relevant
```

## Agent Processing Logic

### Phase 1: Triage Decision
```python
def triage_word(word: str, usage_contexts: List[str]) -> TriageDecision:
    """Determine if word needs definition, blacklisting, or research."""
    
    # Check against common word databases
    if is_common_word(word):
        return TriageDecision.BLACKLIST
    
    # Check if it's used in domain-specific ways
    contexts = analyze_usage_contexts(word, usage_contexts)
    if is_standard_usage(word, contexts):
        return TriageDecision.SIMPLE_DEFINE_AND_BLACKLIST
    
    # Custom/technical term that needs research
    if appears_domain_specific(word, contexts):
        return TriageDecision.RESEARCH_AND_DEFINE
    
    return TriageDecision.BLACKLIST
```

### Phase 2: Definition Generation
```python
def generate_definition(word: str, contexts: List[str]) -> ConceptDefinition:
    """Generate definition by analyzing usage patterns."""
    
    # Collect all usage examples
    usage_examples = extract_usage_examples(word, contexts)
    
    # Use LLM to analyze patterns and generate definition
    definition = llm_analyze_usage(
        word=word,
        examples=usage_examples,
        prompt=f"""
        Analyze how '{word}' is used in these contexts and provide:
        1. A concise definition based on actual usage
        2. Whether this is a standard term or custom terminology
        3. Key relationships to other concepts mentioned nearby
        
        Usage examples: {usage_examples}
        """
    )
    
    return ConceptDefinition(
        word=word,
        definition=definition.text,
        confidence=definition.confidence,
        relationships=definition.relationships,
        examples=usage_examples[:3]  # Keep top 3 examples
    )
```

## Automation Workflow

### Batch Processing
```python
async def process_definition_queue():
    """Process all words requiring definition."""
    
    undefined_words = get_undefined_concepts()
    
    for word_concept in undefined_words:
        # Get all contexts where word appears
        contexts = find_all_usage_contexts(word_concept.name)
        
        # Triage decision
        decision = triage_word(word_concept.name, contexts)
        
        if decision == TriageDecision.BLACKLIST:
            blacklist_and_remove_concept(word_concept)
            
        elif decision == TriageDecision.SIMPLE_DEFINE_AND_BLACKLIST:
            simple_def = get_dictionary_definition(word_concept.name)
            update_concept_definition(word_concept, simple_def)
            add_to_blacklist(word_concept.name)
            
        elif decision == TriageDecision.RESEARCH_AND_DEFINE:
            definition = generate_definition(word_concept.name, contexts)
            update_concept_definition(word_concept, definition)
            mark_as_defined(word_concept)
```

### Prioritization Strategy
1. **Frequency-based**: Most mentioned words get priority
2. **Context richness**: Words with varied usage contexts get attention  
3. **Co-occurrence importance**: Words that appear with already-defined concepts
4. **Recency weighting**: Recently mentioned words get slight priority boost

## Quality Controls

### Definition Validation
- **Consistency checking**: Ensure definition matches all usage contexts
- **Relationship validation**: Verify auto-generated relationships make sense
- **Human review queue**: Flag uncertain definitions for manual review

### Feedback Loop
- **Usage tracking**: Monitor how defined concepts get used in future content
- **Definition refinement**: Update definitions when usage patterns change
- **Blacklist adjustment**: Move incorrectly blacklisted terms back to definition queue

## Integration with SEED Publishing

### Real-time Processing
- **During QA ingestion**: Run auto-definition on newly discovered words
- **Background processing**: Batch process definition queue during downtime
- **Publishing preparation**: Ensure all concepts in content are properly defined

### Content Enhancement
- **Link generation**: Replace undefined words with proper concept links
- **Context tooltips**: Show brief definitions on hover in published content
- **Related concepts**: Surface related terms for exploration

## Example Agent Decisions

### Common Word → Blacklist
```
Word: "the"
Usage: [everywhere]
Decision: BLACKLIST - common article, no semantic value
Action: Remove concept, add to global blacklist
```

### Standard Term → Simple Define + Blacklist
```
Word: "algorithm" 
Usage: "used the algorithm to process data"
Decision: SIMPLE_DEFINE_AND_BLACKLIST - standard CS term used normally
Action: Add dictionary definition, blacklist future instances
```

### Custom Term → Research and Define
```
Word: "GIINT"
Usage: "GIINT provides multi-fire intelligence", "the GIINT system enables..."
Decision: RESEARCH_AND_DEFINE - domain-specific acronym with special meaning
Action: Analyze contexts, generate custom definition, create relationships
```

### Proper Noun → Context-Dependent
```
Word: "Isaac"
Usage: "Isaac's compound intelligence system", "Isaac said..."
Decision: RESEARCH_AND_DEFINE - important person in our context
Action: Create person concept with role and relationships
```

## Implementation Challenges

### Balancing Act
- **Over-blacklisting**: Risk removing valuable terms
- **Over-defining**: Risk cluttering with obvious definitions
- **Context sensitivity**: Same word might need different treatment in different domains

### Performance Considerations
- **LLM usage costs**: Batch processing to minimize API calls
- **Processing time**: Balance thoroughness with speed
- **Queue management**: Prevent queue from growing unbounded

### Quality Assurance
- **Definition accuracy**: Ensure AI-generated definitions are correct
- **Relationship validity**: Verify auto-generated concept relationships
- **Blacklist precision**: Avoid removing terms that become important later

## Configuration Options

```json
{
  "processing_mode": "conservative|aggressive|balanced",
  "batch_size": 50,
  "min_usage_frequency": 3,
  "confidence_threshold": 0.8,
  "human_review_threshold": 0.6,
  "max_queue_size": 1000,
  "blacklist_confidence": 0.9
}
```

This agent would dramatically reduce the manual overhead of maintaining a comprehensive concept dictionary while ensuring quality through intelligent triage and validation.