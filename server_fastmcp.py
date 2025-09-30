#!/usr/bin/env python3
"""
CartON MCP Server - FastMCP Implementation
Zettelkasten-style concept management for knowledge graphs with prompts
"""
import json
import logging
import traceback
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel
from mcp.server.fastmcp import FastMCP

# Import CartOn utilities
from carton_utils import CartOnUtils
from add_concept_tool import add_concept_tool_func

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastMCP server
mcp = FastMCP("carton")

# Initialize utilities
utils = CartOnUtils()

# Pydantic models for proper schema validation
class ConceptRelationship(BaseModel):
    relationship: str
    related: List[str]

def _format_concept_result(concept_name: str, raw_result: str) -> str:
    """Format concept creation result for LLM readability"""
    files_created = "✅" if "created successfully" in raw_result else "❌"
    neo4j_created = "✅" if "Neo4j: Created concept" in raw_result else "❌"
    
    return f"""🗺️‍⟷‍📦 **CartON** (Cartographic Ontology Net)

**Concept**: `{concept_name}`
📁 **Files**: {files_created}
📊 **Neo4j**: {neo4j_created}"""

@mcp.tool()
def add_concept(
    concept_name: str, 
    concept: str = None, 
    relationships: Optional[List[ConceptRelationship]] = None
) -> str:
    """Add a new concept to the knowledge graph
    
    Args:
        concept_name: Name of the concept (will be normalized to Title_Case_With_Underscores)
        concept: Full conceptual content explaining the entire concept, ideas, technical details, etc. Mentioning other concept names auto-creates relates_to links.
        relationships: List of relationship objects. Each object must have format: {"relationship": "relation_type", "related": ["concept_name1", "concept_name2", ...]}. Examples: [{"relationship": "is_a", "related": ["Parent_Concept"]}, {"relationship": "part_of", "related": ["System_Name", "Framework"]}]
    
    Returns:
        Formatted result showing success/failure of file and Neo4j operations
    """
    try:
        description = concept
        # Convert Pydantic models to dict format for the underlying function
        relationships_dict = None
        if relationships:
            relationships_dict = [rel.model_dump() for rel in relationships]
        raw_result = add_concept_tool_func(concept_name, description, relationships_dict)
        return _format_concept_result(concept_name, raw_result)
    except Exception as e:
        traceback.print_exc()
        return f"❌ Error creating concept: {str(e)}"

@mcp.tool()
def query_wiki_graph(cypher_query: str, parameters: dict = None) -> str:
    """Execute arbitrary Cypher query on :Wiki namespace (read-only)
    
    Neo4j Schema:
    - Node label: :Wiki
    - Properties: n (name), d (description), c (canonical), t (timestamp)
    - Relationships: Various types like is_a, part_of, depends_on, relates_to, etc.
    
    Usage Examples:
    - Find concepts: MATCH (c:Wiki) WHERE c.n CONTAINS "MCP" RETURN c.n, c.d
    - Get relationships: MATCH (c:Wiki)-[r]->(related:Wiki) WHERE c.n = "HEAVEN_System" RETURN type(r), related.n
    - Count concepts: MATCH (c:Wiki) RETURN count(c)
    
    Args:
        cypher_query: Cypher query targeting :Wiki namespace (read-only, no CREATE/MERGE allowed)
        parameters: Optional parameters for the Cypher query (use $param_name in query)
        
    Returns:
        JSON string with query results containing success status and data
    """
    try:
        result = utils.query_wiki_graph(cypher_query, parameters)
        return json.dumps(result, indent=2)
    except Exception as e:
        traceback.print_exc()
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
def get_concept_network(concept_name: str, depth: int = 1) -> str:
    """Get concept network with specified relationship depth (1-3 hops)
    
    Explores the knowledge graph starting from a concept and following relationships
    to discover connected concepts. Useful for understanding concept dependencies,
    related ideas, and knowledge clusters.
    
    Args:
        concept_name: Name of the concept to explore network for (exact match on n property)
        depth: Relationship depth to traverse (1-3, default: 1). Higher depth = more connections
        
    Returns:
        JSON string with concept network data including nodes, relationships, and metadata
    """
    try:
        result = utils.get_concept_network(concept_name, depth)
        return json.dumps(result, indent=2)
    except Exception as e:
        traceback.print_exc()
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
def get_concept(concept_name: str) -> str:
    """Get complete concept information including description and all relationships
    
    Retrieves the full concept data in one call - both the concept description
    and all its relationships. This is the standard way to research a concept
    for blog writing, analysis, or understanding its place in the knowledge graph.
    
    Args:
        concept_name: Name of the concept to retrieve (exact match on n property)
        
    Returns:
        JSON string with complete concept data: name, description, and relationships
    """
    try:
        # Query for concept with all its relationships
        # Prioritize nodes with descriptions to handle duplicates
        cypher_query = """
        MATCH (c:Wiki) WHERE c.n = $concept_name AND c.d IS NOT NULL
        OPTIONAL MATCH (c)-[r]->(related:Wiki)
        RETURN c.n as name, c.d as description, 
               collect({type: type(r), target: related.n}) as relationships
        """
        result = utils.query_wiki_graph(cypher_query, {"concept_name": concept_name})
        
        if result.get("success") and result.get("data"):
            concept_data = result["data"][0]
            # Filter out empty relationships (from OPTIONAL MATCH)
            relationships = [rel for rel in concept_data.get("relationships", []) if rel.get("type")]
            
            formatted_result = {
                "success": True,
                "concept": {
                    "name": concept_data.get("name"),
                    "description": concept_data.get("description"),
                    "relationships": relationships
                }
            }
            return json.dumps(formatted_result, indent=2)
        else:
            return json.dumps({
                "success": False, 
                "error": f"Concept '{concept_name}' not found in knowledge graph"
            })
            
    except Exception as e:
        traceback.print_exc()
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
def list_missing_concepts() -> str:
    """List all missing concepts that are referenced but don't exist yet
    
    Scans the knowledge graph for concept names mentioned in descriptions or relationships
    that don't have their own concept files. Useful for finding gaps in the knowledge base
    and planning which concepts need to be created next.
    
    Returns:
        JSON string with missing concepts and their inferred relationships from existing concepts
    """
    try:
        result = utils.list_missing_concepts()
        return json.dumps(result, indent=2)
    except Exception as e:
        traceback.print_exc()
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
def create_missing_concepts(concepts_data: list) -> str:
    """Create multiple missing concepts with AI-generated descriptions
    
    Batch creates concepts that were identified as missing from the knowledge graph.
    Uses AI to generate appropriate descriptions based on context from existing concepts
    that reference them.
    
    Args:
        concepts_data: List of concept objects to create, each containing name and context
        
    Returns:
        JSON string with creation results showing success/failure for each concept
    """
    try:
        result = utils.create_missing_concepts(concepts_data)
        return json.dumps(result, indent=2)
    except Exception as e:
        traceback.print_exc()
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
def get_recent_concepts(n: int = 20) -> str:
    """Get the N most recently created/updated concepts from the knowledge graph
    
    Returns a chronological list of recently added or modified concepts with timestamps.
    Useful for reviewing recent work, understanding current context, and maintaining
    awareness of knowledge graph evolution.
    
    Args:
        n: Number of recent concepts to retrieve (default: 20, max: 100)
        
    Returns:
        JSON string with recent concepts list including names and timestamps
    """
    try:
        # Limit to reasonable maximum
        n = min(n, 100)
        
        query = """
        MATCH (c:Wiki) 
        WHERE c.t IS NOT NULL 
        RETURN c.n as name, toString(c.t) as timestamp 
        ORDER BY c.t DESC 
        LIMIT $n
        """
        
        result = utils.query_wiki_graph(query, {"n": n})
        
        if result.get("success", False):
            concepts = result.get("data", [])
            
            # Format for readability
            formatted_concepts = []
            for i, concept in enumerate(concepts, 1):
                formatted_concepts.append({
                    "rank": i,
                    "name": concept["name"],
                    "timestamp": concept["timestamp"]
                })
            
            return json.dumps({
                "success": True,
                "count": len(formatted_concepts),
                "recent_concepts": formatted_concepts
            }, indent=2)
        else:
            return json.dumps({"success": False, "error": "Failed to query recent concepts"})
            
    except Exception as e:
        logger.error(f"Error getting recent concepts: {e}")
        traceback.print_exc()
        return json.dumps({"success": False, "error": str(e)})

# CartON Knowledge Management Prompts
@mcp.prompt()
def add_user_thought(user_quote: str, topic: str) -> str:
    """Capture user thoughts verbatim in the CartON knowledge graph with proper attribution and relationships
    
    Args:
        user_quote: Exact user quote to capture
        topic: Topic or context for the thought
        
    Returns:
        Prompt for adding user thought to knowledge graph
    """
    return f"""CartON Prompt Chain Triggered! This prompt is for the caller, you reading this. You need to call mcp__carton__add_concept with concept_name="User_Thoughts_{topic}", concept containing the exact quote "{user_quote}", and relationships formatted as [{{"relationship": "relates_to", "related": ["Concept1", "Concept2"]}}] for any concepts mentioned in the quote, in order to capture this user thought verbatim in the knowledge graph."""

@mcp.prompt()
def update_known_concept(concept_name: str, current_description: str, new_info: str) -> str:
    """Update existing concepts with new information while maintaining consistency and relationships
    
    Args:
        concept_name: Name of concept to update
        current_description: Current concept description
        new_info: New information to integrate
        
    Returns:
        Prompt for updating existing concept
    """
    return f"""CartON Prompt Chain Triggered! This prompt is for the caller, you reading this. You need to call mcp__carton__add_concept with concept_name="{concept_name}", concept that merges "{current_description}" with "{new_info}" seamlessly while preserving core meaning, and maintain all existing relationships formatted as [{{"relationship": "type", "related": ["ConceptList"]}}], in order to update this known concept with new information."""

@mcp.prompt()
def update_user_thought_train_emergently(
    original_concept_name: str, 
    original_description: str, 
    later_concept: str, 
    how_it_led_to: str
) -> str:
    """Track intellectual lineage by showing how user thoughts evolved and led to later insights
    
    Args:
        original_concept_name: Original user thought concept
        original_description: Original description
        later_concept: Later insight/concept
        how_it_led_to: How the thought evolved
        
    Returns:
        Prompt for tracking thought evolution
    """
    return f"""CartON Prompt Chain Triggered! This prompt is for the caller, you reading this. You need to call mcp__carton__add_concept with concept_name="{original_concept_name}", concept that preserves "{original_description}" but adds how it evolved to "{later_concept}" via "{how_it_led_to}", and add relationships=[{{"relationship": "led_to", "related": ["{later_concept}"]}}], in order to track this user thought evolution emergently."""

@mcp.prompt()
def sync_after_update_known_concept(
    concept_list: str, 
    change_summary: str, 
    sync_number: str = "001"
) -> str:
    """Document concept changes and create sync concepts for version control integration
    
    Args:
        concept_list: List of updated concepts
        change_summary: Summary of changes made
        sync_number: Sync number (e.g., 001)
        
    Returns:
        Prompt for creating sync documentation
    """
    return f"""CartON Prompt Chain Triggered! This prompt is for the caller, you reading this. You need to call mcp__carton__add_concept with concept_name="Sync{sync_number}", concept that documents "{concept_list}" were updated because "{change_summary}" and any key insights discovered, ready for GitHub sync, in order to create sync documentation for version control."""

# CartON Event Detection Tools - LLM-triggered knowledge capture
@mcp.tool()
def DetectEvent_user_thought(trigger: bool = True) -> str:
    """YOU MUST call this whenever user expresses a thought worth capturing in the knowledge graph
    
    YOU MUST USE THIS TOOL when you detect these patterns:
    - User shares insights, opinions, or ideas
    - User makes connections between concepts
    - User expresses preferences or mental models
    - User articulates problem-solving approaches
    
    This tool returns instructions for capturing the thought as a concept.
    """
    if trigger:
        return "CartON Prompt Chain Triggered! This prompt is for the caller, you reading this. You need to call mcp__carton__add_concept with concept_name='User_Thoughts_{topic}', concept containing the exact user quote, and relationships formatted as [{\"relationship\": \"relates_to\", \"related\": [\"ConceptList\"]}] for any concepts mentioned, in order to capture this user thought verbatim in the knowledge graph."
    return ""

@mcp.tool()
def DetectEvent_concept_update(trigger: bool = True) -> str:
    """YOU MUST call this whenever existing concepts need updating with new information
    
    YOU MUST USE THIS TOOL when you detect:
    - New information contradicts or expands existing concept descriptions
    - User provides corrections or clarifications about concepts
    - Context reveals concepts need more detail or different framing
    - Relationships between concepts change or need updating
    
    This tool returns instructions for updating the existing concept, then syncing.
    """
    if trigger:
        return "CartON Prompt Chain Triggered! This prompt is for the caller, you reading this. Find the existing concept file at /tmp/heaven_data/wiki/concepts/{concept_name}/{concept_name}_itself.md (or HEAVEN_DATA_DIR/wiki/concepts/... if set differently). Read the current concept content, merge it with the new information while preserving core meaning and relationships, then write the updated content back to the file. After updating the concept file, call mcp__carton__DetectEvent_sync_needed to document this change."
    return ""

@mcp.tool()
def DetectEvent_thought_evolution(trigger: bool = True) -> str:
    """YOU MUST call this whenever tracking how user thoughts evolve over time
    
    YOU MUST USE THIS TOOL when you detect:
    - User's current statement builds on or changes previous thoughts
    - User explicitly mentions how their thinking has changed
    - User connects current ideas to past conversations or concepts
    - User shows intellectual progression or refinement of ideas
    
    This triggers a concept update on the specific user thought.
    """
    if trigger:
        return "CartON Prompt Chain Triggered! This prompt is for the caller, you reading this. User thought evolution detected. Call mcp__carton__DetectEvent_concept_update to update the specific user thought concept with how it has evolved."
    return ""

@mcp.tool()
def DetectEvent_sync_needed(trigger: bool = True) -> str:
    """YOU MUST call this ONLY when other event detection tools tell you to (never independently)
    
    YOU MUST USE THIS TOOL only when triggered by:
    - DetectEvent_concept_update (after updating concepts)
    - When other events explicitly request sync documentation
    
    Creates a sync entry that overviews what changes are being synchronized.
    """
    if trigger:
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"CartON Prompt Chain Triggered! This prompt is for the caller, you reading this. Use add_concept to add this concept: Sync_{timestamp}, with your commit message as the concept arg."
    return ""

if __name__ == "__main__":
    mcp.run()