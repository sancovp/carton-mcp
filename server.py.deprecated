"""
Idea Concepts MCP Server - Zettelkasten-style concept management for knowledge graphs
"""
import json
import logging
import traceback
from enum import Enum
from typing import Sequence
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, Prompt, PromptMessage, TextPromptContent
from mcp.shared.exceptions import McpError

# Import CartOn utilities
from carton_utils import CartOnUtils

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ConceptTools(str, Enum):
    """Available concept management tools"""
    ADD_CONCEPT = "add_concept"
    QUERY_WIKI_GRAPH = "query_wiki_graph"
    GET_CONCEPT_NETWORK = "get_concept_network"
    LIST_MISSING_CONCEPTS = "list_missing_concepts"
    CALCULATE_MISSING_CONCEPTS = "calculate_missing_concepts"
    CREATE_MISSING_CONCEPTS = "create_missing_concepts"
    DEDUPLICATE_CONCEPTS = "deduplicate_concepts"


class ConceptPrompts(str, Enum):
    """Available CartON knowledge management prompts"""
    ADD_USER_THOUGHT = "add_user_thought"
    UPDATE_KNOWN_CONCEPT = "update_known_concept"
    UPDATE_USER_THOUGHT_TRAIN_EMERGENTLY = "update_user_thought_train_emergently"
    SYNC_AFTER_UPDATE_KNOWN_CONCEPT = "sync_after_update_known_concept"


class ConceptServer:
    """
    HEAVEN Idea Concepts Server for Zettelkasten Knowledge Management
    
    This server provides AI agents with sophisticated concept management using:
    
    📚 ZETTELKASTEN CONCEPTS:
    - Hierarchical concept organization with auto-linking
    - Automatic relationship inference from descriptions
    - Missing concept detection and tracking
    - Neo4j graph storage with :Wiki namespace
    
    🔗 RELATIONSHIP INFERENCE:
    - Auto-discovers concept mentions in descriptions
    - Infers inverse relationships (is_a ↔ has_instances)
    - Creates bidirectional links (relates_to)
    - Generates starter templates for missing concepts
    
    🗄️ DUAL STORAGE:
    - GitHub: Markdown files with wiki/concepts structure
    - Neo4j: Graph database with minimal token usage
    
    🤖 OPERATIONS:
    Use add_concept to create new concepts with relationships.
    System auto-discovers links and manages missing concepts.
    """
    
    def __init__(self):
        self.utils = CartOnUtils()
    
    def _format_concept_result(self, concept_name: str, raw_result: str) -> str:
        """Format concept creation result for LLM readability"""
        # Check if operations succeeded based on raw_result content
        files_created = "✅" if "created successfully" in raw_result else "❌"
        neo4j_created = "✅" if "Neo4j: Created concept" in raw_result else "❌"
        
        return f"""🗺️‍⟷‍📦 **CartON** (Cartographic Ontology Net)

**Concept**: `{concept_name}`
📁 **Files**: {files_created}
📊 **Neo4j**: {neo4j_created}"""

    def add_concept(self, concept_name: str, description: str = None, relationships: list = None) -> dict:
        """Add a new concept to the knowledge graph"""
        from add_concept_tool import add_concept_tool_func
        try:
            raw_result = add_concept_tool_func(concept_name, description, relationships)
            formatted_result = self._format_concept_result(concept_name, raw_result)
            return {"success": True, "message": formatted_result}
        except Exception as e:
            traceback.print_exc()
            return {"success": False, "error": str(e)}
    
    def query_wiki_graph(self, cypher_query: str, parameters: dict = None) -> dict:
        """Execute arbitrary Cypher query on :Wiki namespace (read-only)"""
        return self.utils.query_wiki_graph(cypher_query, parameters)

    def get_concept_network(self, concept_name: str, depth: int = 1) -> dict:
        """Get concept network with specified relationship depth (1-3 hops)"""
        return self.utils.get_concept_network(concept_name, depth)
    
    def list_missing_concepts(self) -> dict:
        """List all missing concepts with inferred relationships and suggestions"""
        return self.utils.list_missing_concepts()
    
    def calculate_missing_concepts(self) -> dict:
        """Scan all concepts, update missing_concepts.md, and commit to GitHub"""
        return self.utils.calculate_missing_concepts()
    
    def create_missing_concepts(self, concepts_data: list) -> dict:
        """Create multiple missing concepts with AI-generated descriptions"""
        return self.utils.create_missing_concepts(concepts_data)
    
    def deduplicate_concepts(self, similarity_threshold: float = 0.8) -> dict:
        """Find and optionally merge duplicate/similar concepts"""
        return self.utils.deduplicate_concepts(similarity_threshold)


async def serve() -> None:
    """Main MCP server function"""
    server = Server("idea-concepts", capabilities={"prompts": {}})
    concept_server = ConceptServer()
    
    @server.list_tools()
    async def list_tools() -> list[Tool]:
        """List available concept management tools"""
        return [
            Tool(
                name=ConceptTools.ADD_CONCEPT.value,
                description=(
                    "Create a new concept in the Zettelkasten knowledge graph. "
                    "Auto-discovers relationships from description text, manages missing concepts, "
                    "and stores in both GitHub (wiki/concepts/) and Neo4j (:Wiki namespace). "
                    "Relationships can be: is_a, part_of, depends_on, instantiates, relates_to, or custom types."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "concept_name": {
                            "type": "string",
                            "description": "Name of the concept (will be normalized to Title_Case_With_Underscores)",
                        },
                        "description": {
                            "type": "string",
                            "description": "Description of the concept. Mentioning other concept names auto-creates relates_to links.",
                        },
                        "relationships": {
                            "type": "array",
                            "description": "List of relationship objects defining connections to other concepts",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "relationship": {
                                        "type": "string",
                                        "description": "Type of relationship (e.g., is_a, part_of, depends_on, instantiates, relates_to, or custom)",
                                    },
                                    "related": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "description": "List of related concept names",
                                    }
                                },
                                "required": ["relationship", "related"]
                            }
                        }
                    },
                    "required": ["concept_name"],
                },
            ),
            Tool(
                name=ConceptTools.QUERY_WIKI_GRAPH.value,
                description=(
                    "Execute arbitrary read-only Cypher queries on the :Wiki namespace in Neo4j. "
                    "Must target :Wiki namespace. No CREATE/MERGE allowed (read-only). "
                    "Use properties: n (name), d (description), c (canonical), t (timestamp). "
                    "Example: MATCH (c:Wiki) WHERE c.n CONTAINS $keyword RETURN c.n, c.d"
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "cypher_query": {
                            "type": "string",
                            "description": "Cypher query targeting :Wiki namespace (read-only, no CREATE/MERGE)",
                        },
                        "parameters": {
                            "type": "object",
                            "description": "Optional parameters for the Cypher query",
                        }
                    },
                    "required": ["cypher_query"],
                },
            ),
            Tool(
                name=ConceptTools.GET_CONCEPT_NETWORK.value,
                description=(
                    "Get a concept network with specified relationship depth (1-3 hops). "
                    "Returns the target concept and all connected concepts within the specified depth, "
                    "showing relationship paths. Depth 1 = direct connections, Depth 2 = connections + their connections, etc."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "concept_name": {
                            "type": "string",
                            "description": "Name of the concept to explore network for",
                        },
                        "depth": {
                            "type": "integer",
                            "description": "Relationship depth to traverse (1-3, default: 1)",
                            "minimum": 1,
                            "maximum": 3,
                        }
                    },
                    "required": ["concept_name"],
                },
            ),
            Tool(
                name=ConceptTools.LIST_MISSING_CONCEPTS.value,
                description=(
                    "List all missing concepts that are referenced but don't exist yet. "
                    "Shows inferred relationships based on existing references and suggests similar concepts."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            ),
            Tool(
                name=ConceptTools.CALCULATE_MISSING_CONCEPTS.value,
                description=(
                    "Scan all existing concepts for missing references, update missing_concepts.md file, "
                    "and commit changes to GitHub. This performs a full refresh of missing concept tracking."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            ),
            Tool(
                name=ConceptTools.CREATE_MISSING_CONCEPTS.value,
                description=(
                    "Create multiple missing concepts with AI-generated descriptions. "
                    "Takes a list of concept data objects with names and optional descriptions/relationships."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "concepts_data": {
                            "type": "array",
                            "description": "List of concept objects to create",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "concept_name": {
                                        "type": "string",
                                        "description": "Name of the concept to create",
                                    },
                                    "description": {
                                        "type": "string",
                                        "description": "Optional description (will be AI-generated if not provided)",
                                    },
                                    "relationships": {
                                        "type": "array",
                                        "description": "Optional relationship list",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "relationship": {"type": "string"},
                                                "related": {"type": "array", "items": {"type": "string"}}
                                            },
                                            "required": ["relationship", "related"]
                                        }
                                    }
                                },
                                "required": ["concept_name"]
                            }
                        }
                    },
                    "required": ["concepts_data"],
                },
            ),
            Tool(
                name=ConceptTools.DEDUPLICATE_CONCEPTS.value,
                description=(
                    "Find and analyze duplicate or similar concepts in the knowledge graph. "
                    "Uses similarity analysis to identify potential duplicates for manual review."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "similarity_threshold": {
                            "type": "number",
                            "description": "Similarity threshold (0.0-1.0, default: 0.8)",
                            "minimum": 0.0,
                            "maximum": 1.0,
                        }
                    },
                    "required": [],
                },
            ),
        ]
    
    @server.list_prompts()
    async def list_prompts() -> dict:
        """List available CartON knowledge management prompts"""
        return {
            "prompts": [
                {
                    "name": ConceptPrompts.ADD_USER_THOUGHT.value,
                    "description": "Capture user thoughts verbatim in the CartON knowledge graph with proper attribution and relationships",
                    "arguments": [
                        {"name": "user_quote", "description": "Exact user quote to capture", "required": True},
                        {"name": "topic", "description": "Topic or context for the thought", "required": True}
                    ]
                },
                {
                    "name": ConceptPrompts.UPDATE_KNOWN_CONCEPT.value,
                    "description": "Update existing concepts with new information while maintaining consistency and relationships",
                    "arguments": [
                        {"name": "concept_name", "description": "Name of concept to update", "required": True},
                        {"name": "current_description", "description": "Current concept description", "required": True},
                        {"name": "new_info", "description": "New information to integrate", "required": True}
                    ]
                },
                {
                    "name": ConceptPrompts.UPDATE_USER_THOUGHT_TRAIN_EMERGENTLY.value,
                    "description": "Track intellectual lineage by showing how user thoughts evolved and led to later insights",
                    "arguments": [
                        {"name": "original_concept_name", "description": "Original user thought concept", "required": True},
                        {"name": "original_description", "description": "Original description", "required": True},
                        {"name": "later_concept", "description": "Later insight/concept", "required": True},
                        {"name": "how_it_led_to", "description": "How the thought evolved", "required": True}
                    ]
                },
                {
                    "name": ConceptPrompts.SYNC_AFTER_UPDATE_KNOWN_CONCEPT.value,
                    "description": "Document concept changes and create sync concepts for version control integration",
                    "arguments": [
                        {"name": "concept_list", "description": "List of updated concepts", "required": True},
                        {"name": "change_summary", "description": "Summary of changes made", "required": True},
                        {"name": "sync_number", "description": "Sync number (e.g., 001)", "required": False}
                    ]
                },
            ]
        }
    
    @server.get_prompt()
    async def get_prompt(name: str, arguments: dict) -> dict:
        """Get CartON knowledge management prompts with arguments"""
        
        if name == ConceptPrompts.ADD_USER_THOUGHT.value:
            user_quote = arguments.get("user_quote", "{user_quote}")
            topic = arguments.get("topic", "{topic}")
            
            prompt_text = f"""You are adding a user thought to the CartON knowledge graph.

User Quote: "{user_quote}"
Topic/Context: "{topic}"

Create a concept named "User_Thoughts_{topic}" with:
- Exact verbatim quote in description
- Proper relationships to existing concepts mentioned
- Preserve the user's exact words and tone
- Use add_concept tool to create the concept"""
            
            return {
                "description": "Add user thought to CartON knowledge graph",
                "messages": [
                    {
                        "role": "user", 
                        "content": {
                            "type": "text",
                            "text": prompt_text
                        }
                    }
                ]
            }
        
        elif name == ConceptPrompts.UPDATE_KNOWN_CONCEPT.value:
            concept_name = arguments.get("concept_name", "{concept_name}")
            current_description = arguments.get("current_description", "{current_description}")
            new_info = arguments.get("new_info", "{new_info}")
            
            prompt_text = f"""You are updating an existing concept in CartON.

Concept: "{concept_name}"
Current Description: "{current_description}"
New Information: "{new_info}"

Update the concept description to:
- Integrate new information seamlessly
- Maintain existing relationships
- Preserve core meaning while expanding detail
- Use add_concept tool to update the concept"""
            
            return {
                "description": "Update existing concept in CartON",
                "messages": [
                    {
                        "role": "user",
                        "content": {
                            "type": "text", 
                            "text": prompt_text
                        }
                    }
                ]
            }
        
        elif name == ConceptPrompts.UPDATE_USER_THOUGHT_TRAIN_EMERGENTLY.value:
            original_concept_name = arguments.get("original_concept_name", "{original_concept_name}")
            original_description = arguments.get("original_description", "{original_description}")
            later_concept = arguments.get("later_concept", "{later_concept}")
            how_it_led_to = arguments.get("how_it_led_to", "{how_it_led_to}")
            
            prompt_text = f"""You are updating a user thought concept to show how it led to later insights.

Original User Thought: "{original_concept_name}"
Original Description: "{original_description}"
Later Insight/Concept: "{later_concept}"
Connection Type: "{how_it_led_to}"

Update the original user thought to:
- Preserve the exact original quote
- Add a section showing how this thought evolved
- Create/update "led_to" relationships to later concepts
- Show the emergent train of thought progression
- Maintain the original context while showing its intellectual trajectory
- Use add_concept tool to update the concept with led_to relationship"""
            
            return {
                "description": "Track intellectual lineage of user thoughts",
                "messages": [
                    {
                        "role": "user",
                        "content": {
                            "type": "text",
                            "text": prompt_text
                        }
                    }
                ]
            }
        
        elif name == ConceptPrompts.SYNC_AFTER_UPDATE_KNOWN_CONCEPT.value:
            concept_list = arguments.get("concept_list", "{concept_list}")
            change_summary = arguments.get("change_summary", "{change_summary}")
            sync_number = arguments.get("sync_number", "001")
            
            prompt_text = f"""You have updated concept(s) in CartON. Create a sync concept.

Updated Concepts: "{concept_list}"
Changes Made: "{change_summary}"

Create a "Sync{sync_number}" concept describing:
- What concepts were updated and why
- Key insights or connections discovered
- Ready for GitHub sync with this description as commit message
- Use add_concept tool to create the sync concept"""
            
            return {
                "description": "Create sync concept for version control",
                "messages": [
                    {
                        "role": "user",
                        "content": {
                            "type": "text",
                            "text": prompt_text
                        }
                    }
                ]
            }
        
        else:
            raise ValueError(f"Unknown prompt: {name}")
    
    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict
    ) -> Sequence[TextContent]:
        """Handle tool calls for concept operations"""
        try:
            match name:
                case ConceptTools.ADD_CONCEPT.value:
                    concept_name = arguments.get("concept_name")
                    if not concept_name:
                        raise ValueError("Missing required argument: concept_name")
                    
                    result = concept_server.add_concept(
                        concept_name=concept_name,
                        description=arguments.get("description"),
                        relationships=arguments.get("relationships")
                    )
                
                case ConceptTools.QUERY_WIKI_GRAPH.value:
                    cypher_query = arguments.get("cypher_query")
                    if not cypher_query:
                        raise ValueError("Missing required argument: cypher_query")
                    
                    result = concept_server.query_wiki_graph(
                        cypher_query=cypher_query,
                        parameters=arguments.get("parameters")
                    )
                
                case ConceptTools.GET_CONCEPT_NETWORK.value:
                    concept_name = arguments.get("concept_name")
                    if not concept_name:
                        raise ValueError("Missing required argument: concept_name")
                    
                    result = concept_server.get_concept_network(
                        concept_name=concept_name,
                        depth=arguments.get("depth", 1)
                    )
                
                case ConceptTools.LIST_MISSING_CONCEPTS.value:
                    result = concept_server.list_missing_concepts()
                
                case ConceptTools.CALCULATE_MISSING_CONCEPTS.value:
                    result = concept_server.calculate_missing_concepts()
                
                case ConceptTools.CREATE_MISSING_CONCEPTS.value:
                    concepts_data = arguments.get("concepts_data")
                    if not concepts_data:
                        raise ValueError("Missing required argument: concepts_data")
                    
                    result = concept_server.create_missing_concepts(concepts_data)
                
                case ConceptTools.DEDUPLICATE_CONCEPTS.value:
                    similarity_threshold = arguments.get("similarity_threshold", 0.8)
                    result = concept_server.deduplicate_concepts(similarity_threshold)
                
                case _:
                    raise ValueError(f"Unknown tool: {name}")
            
            return [
                TextContent(type="text", text=json.dumps(result, indent=2))
            ]
        
        except Exception as e:
            traceback.print_exc()
            raise ValueError(f"Error processing concept operation: {str(e)}")
    
    # Initialize server and run
    options = server.create_initialization_options()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, options)


if __name__ == "__main__":
    import asyncio
    asyncio.run(serve())