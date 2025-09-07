"""
CartOn Utils - Core business logic for concept management
"""
import logging
from typing import Dict, List, Optional
from pathlib import Path

# Setup logging
logger = logging.getLogger(__name__)

class CartOnUtils:
    """
    CartOn utilities for concept management
    """
    
    def __init__(self):
        pass
    
    
    def _validate_query_safety(self, cypher_query: str) -> dict:
        """Validate query is safe (read-only, :Wiki namespace)"""
        query_upper = cypher_query.upper().strip()
        
        if 'CREATE' in query_upper or 'MERGE' in query_upper:
            return {"success": False, "error": "Write operations (CREATE/MERGE) not allowed. Use add_concept tool instead."}
        
        if ':Wiki' not in cypher_query:
            return {"success": False, "error": "Query must target :Wiki namespace (e.g., MATCH (c:Wiki))"}
        
        return {"success": True}

    def _get_neo4j_config(self):
        """Get Neo4j configuration from environment"""
        import os
        from concept_config import ConceptConfig
        
        return ConceptConfig(
            github_pat=os.getenv('GITHUB_PAT', 'dummy'),
            repo_url=os.getenv('REPO_URL', 'dummy'),
            neo4j_url=os.getenv('NEO4J_URI', 'bolt://host.docker.internal:7687'),
            neo4j_username=os.getenv('NEO4J_USER', 'neo4j'),
            neo4j_password=os.getenv('NEO4J_PASSWORD', 'password'),
            base_path=None  # Will use HEAVEN_DATA_DIR (default /tmp/heaven_data) if None
        )

    def _serialize_node(self, node):
        """Serialize Neo4j Node to dict"""
        return dict(node)
    
    def _serialize_relationship(self, rel):
        """Serialize Neo4j Relationship to dict"""
        return {
            'type': type(rel).__name__,
            'relationship_type': rel.type,
            'properties': dict(rel)
        }
    
    def _serialize_path(self, path):
        """Serialize Neo4j Path to dict"""
        return {
            'nodes': [self._serialize_neo4j_value(n) for n in path.nodes],
            'relationships': [self._serialize_neo4j_value(r) for r in path.relationships]
        }
    
    def _serialize_collection(self, collection):
        """Serialize list/tuple items"""
        return [self._serialize_neo4j_value(item) for item in collection]
    
    def _serialize_dict(self, d):
        """Serialize dict values"""
        return {k: self._serialize_neo4j_value(v) for k, v in d.items()}
    
    def _serialize_neo4j_value(self, value):
        """Convert Neo4j types to JSON-serializable formats"""
        try:
            from neo4j.graph import Node, Relationship, Path
            
            if isinstance(value, Node):
                return self._serialize_node(value)
            elif isinstance(value, Relationship):
                return self._serialize_relationship(value)
            elif isinstance(value, Path):
                return self._serialize_path(value)
            elif isinstance(value, dict):
                return self._serialize_dict(value)
            elif isinstance(value, (list, tuple)):
                return self._serialize_collection(value)
            else:
                return value
        except ImportError:
            return value

    def _create_graph_connection(self):
        """Create and return a Neo4j graph connection"""
        from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder
        
        config = self._get_neo4j_config()
        graph = KnowledgeGraphBuilder(
            uri=config.neo4j_url,
            user=config.neo4j_username,
            password=config.neo4j_password
        )
        graph._ensure_connection()
        return graph
    
    def _serialize_record(self, record):
        """Serialize a single Neo4j record"""
        serialized = {}
        for key in record.keys():
            serialized[key] = self._serialize_neo4j_value(record[key])
        return serialized
    
    def _execute_neo4j_query(self, cypher_query: str, parameters: dict):
        """Execute query against Neo4j"""
        graph = self._create_graph_connection()
        
        try:
            with graph.driver.session() as session:
                result = session.run(cypher_query, parameters or {})
                serialized_results = [self._serialize_record(record) for record in result]
        finally:
            graph.close()
        
        return serialized_results

    def _handle_query_errors(self, e: Exception) -> dict:
        """Handle query execution errors"""
        if isinstance(e, ImportError):
            logger.error("Neo4j driver not available")
            return {"success": False, "error": "Neo4j driver not available"}
        else:
            logger.error(f"Query execution failed: {str(e)}")
            return {"success": False, "error": str(e)}

    def query_wiki_graph(self, cypher_query: str, parameters: dict = None) -> dict:
        """Execute arbitrary Cypher query on :Wiki namespace (read-only)"""
        logger.info(f"Executing wiki graph query: {cypher_query[:100]}...")
        try:
            validation = self._validate_query_safety(cypher_query)
            if not validation["success"]:
                logger.warning(f"Query validation failed: {validation['error']}")
                return validation
            
            result = self._execute_neo4j_query(cypher_query, parameters or {})
            logger.info(f"Query executed successfully, returned {len(result) if isinstance(result, list) else 'N/A'} records")
            
            return {
                "success": True,
                "cypher_query": cypher_query,
                "parameters": parameters or {},
                "data": result
            }
            
        except Exception as e:
            return self._handle_query_errors(e)

    def _validate_depth(self, depth: int) -> dict:
        """Validate depth parameter"""
        if depth < 1 or depth > 3:
            return {"success": False, "error": "Depth must be between 1 and 3"}
        return {"success": True}

    def _build_network_query(self, depth: int) -> str:
        """Build Cypher query for network traversal"""
        return f"""
        MATCH (start:Wiki {{n: $concept_name}})
        CALL {{
            WITH start
            MATCH (start)-[r*1..{depth}]-(connected:Wiki)
            RETURN start, r, connected
        }}
        RETURN start.n as start_concept, 
               [rel in r | type(rel)] as relationship_path,
               connected.n as connected_concept,
               connected.d as connected_description
        """

    def get_concept_network(self, concept_name: str, depth: int = 1) -> dict:
        """Get concept network with specified relationship depth (1-3 hops)"""
        logger.info(f"Getting concept network for '{concept_name}' with depth {depth}")
        
        validation = self._validate_depth(depth)
        if not validation["success"]:
            return validation
        
        cypher_query = self._build_network_query(depth)
        
        try:
            result = self._execute_neo4j_query(cypher_query, {"concept_name": concept_name})
            logger.info(f"Retrieved network for '{concept_name}' with {len(result) if isinstance(result, list) else 0} connections")
            
            return {
                "success": True,
                "concept_name": concept_name,
                "depth": depth,
                "network": result
            }
            
        except Exception as e:
            return self._handle_query_errors(e)
    
    def list_missing_concepts(self) -> dict:
        """List all missing concepts with inferred relationships and suggestions"""
        logger.info("Listing missing concepts...")
        try:
            missing_file = self._get_missing_concepts_file()
            if not missing_file.exists():
                return self._return_no_missing_concepts()
            
            content = missing_file.read_text(encoding="utf-8")
            missing_concepts = self._parse_missing_concepts_content(content)
            
            logger.info(f"Found {len(missing_concepts)} missing concepts")
            return {
                "success": True,
                "missing_concepts": missing_concepts,
                "total_count": len(missing_concepts)
            }
            
        except Exception as e:
            logger.error(f"Error listing missing concepts: {str(e)}")
            return {"success": False, "error": f"Failed to list missing concepts: {str(e)}"}
    
    def _get_missing_concepts_file(self):
        """Get the path to missing concepts file"""
        from pathlib import Path
        config = self._get_neo4j_config()
        return Path(config.base_path) / "missing_concepts.md"
    
    def _return_no_missing_concepts(self) -> dict:
        """Return response when no missing concepts file exists"""
        return {
            "success": True,
            "missing_concepts": [],
            "message": "No missing concepts file found - all concepts exist or none have been created yet"
        }
    
    def _parse_missing_concepts_content(self, content: str) -> list:
        """Parse missing concepts from markdown content"""
        import re
        missing_concepts = []
        current_concept = None
        current_relationships = []
        current_similar = []
        
        for line in content.split('\n'):
            line = line.strip()
            
            if line.startswith('## ') and line != '## Missing Concepts':
                if current_concept:
                    missing_concepts.append(self._build_concept_data(current_concept, current_relationships, current_similar))
                
                current_concept = line[3:].strip()
                current_relationships = []
                current_similar = []
                
            elif line.startswith('- ') and current_concept:
                rel_data = self._parse_relationship_line(line)
                if rel_data:
                    current_relationships.append(rel_data)
                    
            elif line.startswith('**Similar existing concepts:**') and current_concept:
                current_similar = self._parse_similar_concepts_line(line)
        
        if current_concept:
            missing_concepts.append(self._build_concept_data(current_concept, current_relationships, current_similar))
        
        return missing_concepts
    
    def _parse_relationship_line(self, line: str):
        """Parse a relationship line from missing concepts"""
        import re
        rel_match = re.match(r'- ([^:]+): (.+)', line)
        if rel_match:
            rel_type, related = rel_match.groups()
            return {
                "type": rel_type.strip(),
                "related": [c.strip() for c in related.split(',')]
            }
        return None
    
    def _parse_similar_concepts_line(self, line: str) -> list:
        """Parse similar concepts line from missing concepts"""
        similar_text = line.replace('**Similar existing concepts:**', '').strip()
        if similar_text and similar_text != "None":
            return [c.strip() for c in similar_text.split(',')]
        return []
    
    def _build_concept_data(self, name: str, relationships: list, similar: list) -> dict:
        """Build concept data structure"""
        return {
            "name": name,
            "inferred_relationships": relationships,
            "similar_concepts": similar
        }
    
    def calculate_missing_concepts(self) -> dict:
        """Scan all concepts, update missing_concepts.md, and commit to GitHub"""
        logger.info("Calculating missing concepts across all existing concepts...")
        try:
            from add_concept_tool import check_missing_concepts_and_manage_file, setup_git_repo, commit_and_push
            
            # Get config and setup repo
            config = self._get_neo4j_config()
            base_dir = config.base_path
            
            # Setup git repo (clone latest)
            result = setup_git_repo(config, base_dir)
            if "error" in result:
                return {"success": False, "error": f"Git setup failed: {result['error']}"}
            
            # Run missing concepts check (this scans all existing concepts)
            file_updates = check_missing_concepts_and_manage_file(base_dir, "")  # Empty concept name for full scan
            
            # If file was updated, commit and push
            if file_updates and any("Updated missing_concepts.md" in update for update in file_updates):
                commit_result = commit_and_push(config, base_dir, "Update missing concepts tracking")
                if "error" in commit_result:
                    return {"success": False, "error": f"Git commit failed: {commit_result['error']}"}
                
                # Now read the updated file
                missing_file = self._get_missing_concepts_file()
                if missing_file.exists():
                    content = missing_file.read_text(encoding="utf-8")
                    missing_concepts = self._parse_missing_concepts_content(content)
                    
                    return {
                        "success": True,
                        "message": "Missing concepts calculated and synced to GitHub",
                        "missing_concepts": missing_concepts,
                        "total_count": len(missing_concepts),
                        "file_updates": file_updates
                    }
                else:
                    return {
                        "success": True, 
                        "message": "No missing concepts found",
                        "missing_concepts": [],
                        "total_count": 0,
                        "file_updates": file_updates
                    }
            else:
                return {
                    "success": True,
                    "message": "No changes to missing concepts",
                    "missing_concepts": [],
                    "total_count": 0,
                    "file_updates": file_updates or ["No updates needed"]
                }
                
        except Exception as e:
            logger.error(f"Error calculating missing concepts: {str(e)}")
            return {"success": False, "error": f"Failed to calculate missing concepts: {str(e)}"}

    def create_missing_concepts(self, concepts_data: list) -> dict:
        """Create multiple missing concepts with AI-generated descriptions"""
        logger.info(f"Creating {len(concepts_data)} missing concepts...")
        
        try:
            from add_concept_tool import add_concept_tool_func
            
            created_concepts = []
            failed_concepts = []
            
            for concept_data in concepts_data:
                concept_name = concept_data.get("concept_name")
                if not concept_name:
                    failed_concepts.append({
                        "error": "Missing concept_name",
                        "data": concept_data
                    })
                    continue
                
                description = concept_data.get("description")
                if not description:
                    # AI-generate description based on name and relationships
                    description = self._generate_concept_description(concept_name, concept_data.get("relationships", []))
                
                relationships = concept_data.get("relationships")
                if not relationships:
                    # Create a minimal WIP relationship
                    relationships = [{"relationship": "is_a", "related": ["Work_In_Progress"]}]
                
                try:
                    result = add_concept_tool_func(concept_name, description, relationships)
                    created_concepts.append({
                        "name": concept_name,
                        "result": result
                    })
                    logger.info(f"Created concept: {concept_name}")
                    
                except Exception as e:
                    failed_concepts.append({
                        "name": concept_name,
                        "error": str(e),
                        "data": concept_data
                    })
                    logger.error(f"Failed to create concept {concept_name}: {str(e)}")
            
            return {
                "success": True,
                "created_count": len(created_concepts),
                "failed_count": len(failed_concepts),
                "created_concepts": created_concepts,
                "failed_concepts": failed_concepts
            }
            
        except Exception as e:
            logger.error(f"Error creating missing concepts: {str(e)}")
            return {"success": False, "error": f"Failed to create missing concepts: {str(e)}"}
    
    def _generate_concept_description(self, concept_name: str, relationships: list) -> str:
        """Generate AI description for a concept based on name and relationships"""
        # Simple description generation based on concept name patterns
        name_parts = concept_name.replace('_', ' ').replace('-', ' ').lower()
        
        if any(word in name_parts for word in ['tool', 'system', 'framework']):
            base = f"{concept_name.replace('_', ' ')} is a system or tool that provides specific functionality."
        elif any(word in name_parts for word in ['protocol', 'standard', 'format']):
            base = f"{concept_name.replace('_', ' ')} is a protocol or standard for data exchange and communication."
        elif any(word in name_parts for word in ['agent', 'intelligence', 'ai']):
            base = f"{concept_name.replace('_', ' ')} is an intelligent agent or AI system with specific capabilities."
        elif any(word in name_parts for word in ['integration', 'bridge', 'adapter']):
            base = f"{concept_name.replace('_', ' ')} is an integration layer or bridge between different systems."
        else:
            base = f"{concept_name.replace('_', ' ')} is a concept that requires further definition and exploration."
        
        # Add relationship context
        if relationships:
            rel_context = []
            for rel in relationships:
                rel_type = rel.get("relationship", "relates_to")
                related = rel.get("related", [])
                if related:
                    rel_context.append(f"It {rel_type} {', '.join(related[:2])}")
            
            if rel_context:
                base += " " + ". ".join(rel_context) + "."
        
        return base
    
    def deduplicate_concepts(self, similarity_threshold: float = 0.8) -> dict:
        """Find and analyze duplicate or similar concepts"""
        logger.info(f"Finding duplicate concepts with similarity threshold {similarity_threshold}...")
        
        try:
            # Get all concepts from Neo4j
            query = "MATCH (c:Wiki) RETURN c.n as name, c.d as description ORDER BY c.n"
            result = self._execute_neo4j_query(query, {})
            
            if not result:
                return {
                    "success": True,
                    "duplicates": [],
                    "message": "No concepts found in database"
                }
            
            concepts = [(record["name"], record.get("description", "")) for record in result]
            duplicates = []
            processed = set()
            
            from difflib import SequenceMatcher
            
            # Find similar concept names
            for i, (name1, desc1) in enumerate(concepts):
                if name1 in processed:
                    continue
                    
                similar_group = [{"name": name1, "description": desc1}]
                
                for j, (name2, desc2) in enumerate(concepts[i+1:], i+1):
                    if name2 in processed:
                        continue
                    
                    # Calculate name similarity
                    name_similarity = SequenceMatcher(None, name1.lower(), name2.lower()).ratio()
                    
                    # Also check for obvious patterns
                    name1_clean = name1.lower().replace('_', '').replace('-', '')
                    name2_clean = name2.lower().replace('_', '').replace('-', '')
                    
                    if (name_similarity >= similarity_threshold or 
                        name1_clean == name2_clean or
                        name1.lower().replace('_', ' ') == name2.lower().replace('_', ' ')):
                        
                        similar_group.append({"name": name2, "description": desc2})
                        processed.add(name2)
                
                if len(similar_group) > 1:
                    duplicates.append({
                        "group": similar_group,
                        "similarity_reasons": self._analyze_similarity(similar_group)
                    })
                    processed.add(name1)
            
            logger.info(f"Found {len(duplicates)} potential duplicate groups")
            
            return {
                "success": True,
                "duplicate_groups": duplicates,
                "total_groups": len(duplicates),
                "similarity_threshold": similarity_threshold,
                "analysis": f"Found {len(duplicates)} groups of similar concepts that may need manual review"
            }
            
        except Exception as e:
            logger.error(f"Error finding duplicates: {str(e)}")
            return {"success": False, "error": f"Failed to find duplicates: {str(e)}"}
    
    def _analyze_similarity(self, similar_group: list) -> list:
        """Analyze why concepts are considered similar"""
        reasons = []
        names = [item["name"] for item in similar_group]
        
        # Check for case variations
        if len(set(name.lower() for name in names)) < len(names):
            reasons.append("Case variations of the same concept")
        
        # Check for underscore/space variations  
        normalized = [name.lower().replace('_', ' ').replace('-', ' ') for name in names]
        if len(set(normalized)) < len(names):
            reasons.append("Different formatting (underscores, spaces, hyphens)")
        
        # Check for obvious duplicates
        if len(set(names)) != len(names):
            reasons.append("Exact duplicates")
        
        if not reasons:
            reasons.append("High textual similarity")
            
        return reasons

    def retroactive_autolink_all_concepts(self) -> dict:
        """Apply auto-linking to all existing concept descriptions retroactively"""
        logger.info("Starting retroactive auto-linking of all concepts...")
        
        try:
            from add_concept_tool import auto_link_description, setup_git_repo, commit_and_push
            
            config = self._get_neo4j_config()
            base_dir = config.base_path
            
            # Setup fresh git repo
            setup_result = setup_git_repo(config, base_dir)
            if "error" in setup_result:
                return {"success": False, "error": setup_result["error"]}
            
            concepts_dir = Path(base_dir) / "concepts"
            if not concepts_dir.exists():
                return {"success": False, "error": "Concepts directory not found"}
            
            updated_concepts = []
            
            # Process each concept directory
            for concept_dir in concepts_dir.iterdir():
                if not concept_dir.is_dir():
                    continue
                    
                concept_name = concept_dir.name
                logger.info(f"Processing concept: {concept_name}")
                
                # Process description.md
                desc_file = concept_dir / "components" / "description.md"
                if desc_file.exists():
                    original_content = desc_file.read_text(encoding="utf-8")
                    linked_content = auto_link_description(original_content, base_dir, concept_name)
                    
                    if original_content != linked_content:
                        desc_file.write_text(linked_content)
                        logger.info(f"Updated description for {concept_name}")
                
                # Process main concept file
                main_file = concept_dir / f"{concept_name}.md" 
                if main_file.exists():
                    content = main_file.read_text(encoding="utf-8")
                    lines = content.split('\n')
                    
                    # Find and update the overview section
                    for i, line in enumerate(lines):
                        if "## Overview" in line and i + 1 < len(lines):
                            overview_text = lines[i + 1]
                            linked_overview = auto_link_description(overview_text, base_dir, concept_name)
                            if overview_text != linked_overview:
                                lines[i + 1] = linked_overview
                                main_file.write_text('\n'.join(lines))
                                break
                
                # Process _itself.md file
                itself_file = concept_dir / f"{concept_name}_itself.md"
                if itself_file.exists():
                    content = itself_file.read_text(encoding="utf-8")
                    lines = content.split('\n')
                    
                    # Find and update the overview section
                    for i, line in enumerate(lines):
                        if "## Overview" in line and i + 1 < len(lines):
                            overview_text = lines[i + 1]
                            linked_overview = auto_link_description(overview_text, base_dir, concept_name)
                            if overview_text != linked_overview:
                                lines[i + 1] = linked_overview
                                itself_file.write_text('\n'.join(lines))
                                updated_concepts.append(concept_name)
                                break
            
            # Commit changes
            if updated_concepts:
                commit_msg = f"Retroactive auto-linking: Updated {len(updated_concepts)} concepts"
                commit_result = commit_and_push(config, base_dir, commit_msg)
                if "error" in commit_result:
                    return {"success": False, "error": commit_result["error"]}
            
            return {
                "success": True,
                "message": f"Retroactive auto-linking completed",
                "updated_concepts": updated_concepts,
                "total_updated": len(updated_concepts)
            }
            
        except Exception as e:
            logger.error(f"Error during retroactive auto-linking: {str(e)}")
            return {"success": False, "error": f"Failed to apply retroactive auto-linking: {str(e)}"}