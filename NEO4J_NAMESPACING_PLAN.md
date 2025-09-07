# Neo4j Namespacing Plan for Concept MCP

## Current State Analysis

### Existing Neo4j Schema (from concept_neo4j_utils.py)
The heaven-framework currently uses these node types:
- `ConceptTag` - For conversation analysis concepts
- `Conversation` - For conversation tracking
- `Phase` - For conversation phases  
- `Iteration` - For conversation iterations
- `TotalSummary` / `PhaseSummary` / `IterationSummary` - For conversation summaries

### Problem
Our simple wiki concepts will conflict with the existing conversation analysis system. We need clear separation.

## Proposed Namespacing Strategy

### 1. Namespace Existing Conversation System
**Change existing nodes to use `conversations` namespace:**
- `ConceptTag` → `ConceptTag:Conversations`
- `Conversation` → `Conversation:Conversations`  
- `Phase` → `Phase:Conversations`
- `Iteration` → `Iteration:Conversations`
- `*Summary` → `*Summary:Conversations`

### 2. Create New Concepts Namespace
**Our wiki concepts use `Wiki` namespace:**
- `Concept:Wiki` - Simple concept nodes
- `File:Wiki` - Markdown files  
- `Relationship:Wiki` - Explicit relationships

### 3. User Namespacing (Future)
**For multi-tenant support:**
- `Concept:Wiki:User123`
- `File:Wiki:User123`
- Or separate databases per user

## Proposed Schema for Wiki Concepts

### Core Nodes
```cypher
// Simple concept node
CREATE (c:Concept:Wiki {
    name: "Meta_Frontend",
    description: "Multi-tenant orchestration layer...",
    filename: "Meta_Frontend.md",
    created_at: datetime(),
    updated_at: datetime(),
    github_url: "https://github.com/user/repo/blob/main/concepts/Meta_Frontend/Meta_Frontend.md"
})

// Markdown file node  
CREATE (f:File:Wiki {
    path: "concepts/Meta_Frontend/Meta_Frontend.md",
    content_hash: "abc123...",
    last_sync: datetime()
})

// Explicit relationship
CREATE (r:Relationship:Wiki {
    type: "relates_to",
    strength: 1.0,
    auto_discovered: true,
    created_at: datetime()
})
```

### Relationships
```cypher
// Concept to concept relationships
(c1:Concept:Wiki)-[r:RELATES_TO]->(c2:Concept:Wiki)

// Concept to file relationships  
(c:Concept:Wiki)-[:DEFINED_IN]->(f:File:Wiki)

// Auto-discovered vs manual relationships
(c1)-[r:RELATES_TO {auto_discovered: true}]->(c2)
(c1)-[r:DEPENDS_ON {auto_discovered: false}]->(c2)
```

## Migration Plan

### Step 1: Check Current Database State
```cypher
// See what node types exist
CALL db.labels() YIELD label
RETURN label ORDER BY label

// Count nodes by type
MATCH (n)
RETURN labels(n) as node_types, count(*) as count
ORDER BY count DESC
```

### Step 2: Backup Existing Data
```cypher
// Export existing conversation data
MATCH (n)
WHERE any(label IN labels(n) WHERE label IN ['ConceptTag', 'Conversation', 'Phase', 'Iteration'])
RETURN n
```

### Step 3: Migrate Conversation System
- Update `concept_neo4j_utils.py` to use `:Conversations` namespace
- Run migration script to add namespace to existing nodes
- Test conversation analysis still works

### Step 4: Implement Wiki Concepts
- Create new schema with `:WikiConcepts` namespace
- Implement MCP tools for concept management
- Test isolation between systems

## MCP Tool Design

### Required Tools
1. **sync_github_to_neo4j** - Pull markdown, build graph
2. **query_related_concepts** - Find connected concepts
3. **search_concepts** - Search by content/name
4. **get_concept_graph** - Get subgraph around concept
5. **add_relationship** - Manual relationship creation
6. **get_concept_details** - Full concept information

### Example Queries
```cypher
// Find concepts related to "Meta_Frontend"
MATCH (c1:Concept:WikiConcepts {name: "Meta_Frontend"})-[r:RELATES_TO]->(c2:Concept:WikiConcepts)
RETURN c2.name, c2.description, r.type

// Search concepts by content
MATCH (c:Concept:WikiConcepts)
WHERE toLower(c.description) CONTAINS toLower($search_term)
   OR toLower(c.name) CONTAINS toLower($search_term)
RETURN c.name, c.description

// Get concept neighborhood
MATCH path = (c:Concept:WikiConcepts {name: $concept_name})-[*1..2]-()
RETURN path
```

## Configuration Changes Needed

### 1. Update ConceptConfig
```python
class ConceptConfig:
    def __init__(self, 
                 github_pat: str, 
                 repo_url: str, 
                 neo4j_url: str,
                 neo4j_username: str,
                 neo4j_password: str,
                 user_namespace: str = None,  # For multi-tenant
                 branch: str = "main", 
                 base_path: str = "/tmp/concepts"):
        # ... existing config ...
        self.user_namespace = user_namespace
    
    @property
    def concept_labels(self) -> List[str]:
        """Get labels for concept nodes."""
        labels = ["Concept", "WikiConcepts"]
        if self.user_namespace:
            labels.append(self.user_namespace)
        return labels
```

### 2. Update heaven-framework
- Modify `concept_neo4j_utils.py` to use `:Conversations` namespace
- Ensure backward compatibility during migration
- Add namespace support to `KnowledgeGraphBuilder`

## Testing Strategy

### 1. Isolation Testing
- Create concepts in `:WikiConcepts` namespace
- Ensure no interference with `:Conversations` data
- Verify queries only return appropriate namespace data

### 2. Performance Testing  
- Measure query performance with namespaces
- Test with realistic data volumes
- Optimize indexes for namespaced queries

### 3. Multi-tenant Testing
- Test user namespace isolation
- Verify no data leakage between users
- Performance with multiple user namespaces

## Rollout Plan

### Phase 1: Single User, Local Testing
- Implement wiki concepts with `:WikiConcepts` namespace
- Test with local Neo4j instance
- Validate auto-linking and relationship discovery

### Phase 2: Migration of Existing System
- Add `:Conversations` namespace to existing conversation data
- Update all conversation analysis code
- Ensure no breaking changes

### Phase 3: Multi-User Support
- Add user namespacing capability
- Test isolation and performance
- Deploy to production

## Benefits of This Approach

1. **Clean Separation**: Wiki concepts don't interfere with conversation analysis
2. **Future-Proof**: Easy to add more namespaces (tasks, projects, etc.)
3. **Multi-Tenant Ready**: User namespaces enable isolation
4. **Backward Compatible**: Existing system continues working
5. **Scalable**: Namespaces improve query performance

---

*This plan ensures our simple concept wiki coexists peacefully with the sophisticated conversation analysis system while preparing for future multi-tenant deployment.*