# Sequential Pattern Concept Mining with N-gram Analysis

## Overview

Advanced extension to word-level concept mining that detects meaningful sequences (n-grams) and builds hierarchical concept relationships through recursive composition analysis.

## N-gram Detection Algorithm

### Multi-level Pattern Extraction
```python
def extract_sequential_patterns(content: str, max_n: int = 5) -> Dict[str, int]:
    """Extract all n-gram patterns from content with frequency counts."""
    
    tokens = tokenize(content)  # Handle hyphenated words properly
    patterns = {}
    
    for n in range(1, max_n + 1):
        for i in range(len(tokens) - n + 1):
            ngram = " ".join(tokens[i:i+n])
            patterns[ngram] = patterns.get(ngram, 0) + 1
    
    return patterns

# Example output:
{
    "word": 12,
    "concept": 45, 
    "mining": 8,
    "word-level": 8,
    "concept mining": 15,
    "word-level concept": 6,
    "word-level concept mining": 3,
    "concept mining system": 2
}
```

### Frequency Threshold Filtering
- **Minimum occurrence**: N-grams must appear at least 3 times
- **Length weighting**: Longer sequences need lower frequency thresholds
- **Significance ratio**: Compare expected vs actual frequency

## Hierarchical Concept Construction

### Compositional Relationships
```python
def build_concept_hierarchy(patterns: Dict[str, int]) -> ConceptHierarchy:
    """Build hierarchical relationships between atomic and compound concepts."""
    
    concepts = {}
    
    for pattern, frequency in patterns.items():
        if frequency >= threshold_for_length(len(pattern.split())):
            # Create compound concept
            compound = create_concept(pattern)
            
            # Find component concepts
            components = pattern.split()
            for component in components:
                if component in concepts:
                    # Create composition relationship
                    add_relationship(
                        compound, 
                        "composed_of", 
                        concepts[component]
                    )
            
            concepts[pattern] = compound
    
    return concepts
```

### Example Hierarchy
```
Concept_Mining (parent concept)
├── Word_Level_Concept_Mining (specific implementation)
│   ├── composed_of: Word_Level
│   ├── composed_of: Concept  
│   └── composed_of: Mining
├── Automatic_Concept_Mining (another implementation)
│   ├── composed_of: Automatic
│   ├── composed_of: Concept
│   └── composed_of: Mining
└── is_a: Mining (general category)
```

## AI Refinement Agent

### Semantic Validation Pipeline
```python
async def refine_sequential_concepts(raw_patterns: Dict[str, int]) -> List[ValidatedConcept]:
    """AI agent that validates and refines detected patterns."""
    
    validated_concepts = []
    
    for pattern, frequency in raw_patterns.items():
        # Get all usage contexts
        contexts = find_usage_contexts(pattern)
        
        # AI semantic analysis
        analysis = await llm_analyze_pattern(
            pattern=pattern,
            frequency=frequency,
            contexts=contexts,
            prompt=f"""
            Analyze this text pattern for concept validity:
            
            Pattern: "{pattern}"
            Frequency: {frequency} occurrences
            Contexts: {contexts[:5]}  # Top 5 contexts
            
            Determine:
            1. Is this a meaningful concept or just word coincidence?
            2. What semantic category does it belong to?
            3. How should it relate to component words?
            4. Is this a technical term, proper noun, or general concept?
            5. Should this be defined or is it compositional from parts?
            
            Return structured analysis.
            """
        )
        
        if analysis.is_valid_concept:
            validated_concepts.append(
                ValidatedConcept(
                    pattern=pattern,
                    category=analysis.category,
                    definition_needed=analysis.needs_definition,
                    relationships=analysis.suggested_relationships
                )
            )
    
    return validated_concepts
```

### Disambiguation Logic
```python
def disambiguate_pattern(pattern: str, contexts: List[str]) -> DisambiguationResult:
    """Handle cases where same pattern has different meanings."""
    
    # Example: "mining system" could be:
    # - Data mining system (technical)
    # - Physical mining system (industrial) 
    # - Concept mining system (our domain)
    
    context_clusters = cluster_contexts_by_meaning(contexts)
    
    if len(context_clusters) > 1:
        # Multiple meanings detected
        return DisambiguationResult(
            base_pattern=pattern,
            variants=[
                f"{pattern}_{cluster.domain}" 
                for cluster in context_clusters
            ]
        )
    else:
        # Single coherent meaning
        return DisambiguationResult(
            base_pattern=pattern,
            variants=[pattern]
        )
```

## Integration with Existing Systems

### Enhanced Word-Level Mining
```python
def enhanced_concept_mining(content: str) -> ConceptMiningResult:
    """Combine individual word mining with sequential pattern detection."""
    
    # Traditional word-level mining
    individual_words = extract_words(content)
    
    # Sequential pattern mining  
    patterns = extract_sequential_patterns(content)
    validated_patterns = await refine_sequential_concepts(patterns)
    
    # Build hierarchical relationships
    hierarchy = build_concept_hierarchy(validated_patterns)
    
    # Merge results with precedence for longer patterns
    final_concepts = merge_with_precedence(individual_words, validated_patterns)
    
    return ConceptMiningResult(
        atomic_concepts=individual_words,
        compound_concepts=validated_patterns,
        hierarchy=hierarchy,
        relationships=extract_all_relationships(hierarchy)
    )
```

### Auto-Definition Integration
The Auto-Definition Agent would handle sequential patterns with special logic:

```python
def triage_sequential_pattern(pattern: str, components: List[str]) -> TriageDecision:
    """Special triage logic for compound patterns."""
    
    # Check if all components are already defined
    component_definitions = [get_definition(comp) for comp in components]
    
    if all(component_definitions):
        # All parts defined - check if compound meaning is compositional
        if is_compositional_meaning(pattern, component_definitions):
            return TriageDecision.COMPOSITIONAL  # Don't define separately
        else:
            return TriageDecision.DEFINE_COMPOUND  # Has non-compositional meaning
    else:
        # Some components undefined - define components first
        return TriageDecision.DEFINE_COMPONENTS_FIRST
```

## Advanced Features

### Temporal Pattern Evolution
Track how patterns emerge and evolve over time:
```python
# Pattern lifecycle tracking
pattern_timeline = {
    "concept mining": {
        "first_appearance": "2025-01-15",
        "frequency_over_time": [(date, count), ...],
        "definition_evolution": [(date, definition_version), ...]
    }
}
```

### Cross-Reference Validation
Validate patterns against existing knowledge:
```python
def validate_against_external_sources(pattern: str) -> ValidationResult:
    """Check if pattern is established term vs our invention."""
    
    # Check academic databases, technical dictionaries, etc.
    external_matches = search_external_sources(pattern)
    
    if external_matches:
        return ValidationResult.ESTABLISHED_TERM
    else:
        return ValidationResult.DOMAIN_SPECIFIC_TERM
```

## Benefits

### Compositional Understanding
- **Hierarchical knowledge**: Understand both atomic and compound concepts
- **Semantic inheritance**: Compound concepts inherit properties from components  
- **Efficient storage**: Avoid redundant definitions for compositional meanings

### Enhanced Precision
- **Context-aware**: Same words in different sequences have different meanings
- **Technical accuracy**: Properly identify domain-specific terminology
- **Relationship richness**: Build complex semantic networks

### Scalable Intelligence
- **Pattern recognition**: Automatically discover emerging terminology
- **Knowledge evolution**: Track how concepts compound and evolve
- **Predictive capability**: Anticipate related concepts from patterns

This system would create truly sophisticated semantic understanding that goes far beyond simple word matching to capture the compositional nature of human knowledge and terminology.