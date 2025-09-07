# add_concept_tool.py


### HEAVEN CONVERSION
from heaven_base import BaseHeavenTool, ToolArgsSchema, ToolResult
from pathlib import Path
from typing import Optional, Dict, Any, List
import subprocess
import shutil
import json
import re
import os
import traceback
from difflib import get_close_matches

# Import the concept config helpers locally  
from concept_config import ConceptConfig


def run_git_command(cmd: list[str], cwd: str) -> Dict[str, str]:
    """Run a git command synchronously."""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True
        )
        return {"output": result.stdout.strip()}
    except subprocess.CalledProcessError as e:
        traceback.print_exc()
        return {"error": e.stderr.strip()}

def setup_git_repo(config: ConceptConfig, base_path: str) -> Dict[str, str]:
    """ALWAYS start fresh by deleting and cloning the remote repo to base_path."""
    # 1. Remove the current local wiki directory completely
    shutil.rmtree(base_path, ignore_errors=True)

    # 2. Set up git credentials BEFORE cloning
    auth_url = f"https://{config.github_pat}@github.com"
    credentials_path = Path.home() / ".git-credentials"
    credentials_path.write_text(auth_url + "\n")

    # 3. Prepare the clean remote URL (no PAT in URL since we use credential helper)
    repo_url = config.private_wiki_url
    if not repo_url.endswith(".git"):
        repo_url += ".git"

    # 4. Clone the latest remote repo into base_path
    result = run_git_command(["git", "clone", repo_url, base_path], ".")
    if "error" in result:
        return {"error": f"Git clone failed: {result['error']}"}

    # 5. Configure identity for future commits
    commands = [
        ["git", "config", "user.email", "bot@example.com"],
        ["git", "config", "user.name", "Concept Bot"],
        ["git", "config", "credential.helper", "store"],
    ]
    for cmd in commands:
        r = run_git_command(cmd, base_path)
        if "error" in r:
            return {"error": f"Git config failed: {r['error']}"}

    return {"output": "Git repo setup successful"}

def sync_with_remote(config: ConceptConfig, base_path: str) -> Dict[str, str]:
    """Synchronize local repository with remote."""
    auth_url = f"https://{config.github_pat}@github.com"
    credentials_path = Path.home() / ".git-credentials"
    credentials_path.write_text(auth_url + "\n")

    result = run_git_command(["git", "fetch", "origin"], base_path)
    if "error" in result:
        return {"error": f"Git fetch failed: {result['error']}"}

    result = run_git_command(
        ["git", "pull", "--no-rebase", "origin", config.private_wiki_branch], base_path
    )
    if "error" in result:
        return {"error": f"Git pull failed: {result['error']}"}

    return {"output": "Sync successful"}


def auto_link_description(description: str, base_path: str, current_concept: str) -> str:
    """Convert concept name mentions in description to markdown links with conservative fuzzy matching."""
    concepts_dir = Path(base_path) / "concepts"
    if not concepts_dir.exists():
        return description
    
    # Get all existing concept directory names
    existing_concepts = [d.name for d in concepts_dir.iterdir() if d.is_dir() and d.name != current_concept]
    
    # Sort by length (longest first) to avoid partial matches
    existing_concepts.sort(key=len, reverse=True)
    
    linked_description = description
    for concept in existing_concepts:
        # Check if this concept is already linked
        if f"[{concept}]" in linked_description:
            continue
            
        # Generate conservative formatting variations of the exact concept name
        variations = set()
        
        # 1. Exact concept name
        variations.add(concept)
        
        # 2. Convert underscores to spaces  
        concept_with_spaces = concept.replace('_', ' ')
        variations.add(concept_with_spaces)
        
        # 3. Title case version with spaces
        concept_title = concept_with_spaces.title()
        variations.add(concept_title)
        
        # 4. All caps version (for acronyms)
        concept_upper = concept.upper()
        variations.add(concept_upper)
        concept_upper_spaces = concept_with_spaces.upper()
        variations.add(concept_upper_spaces)
        
        # 5. All lowercase version
        concept_lower = concept.lower()
        variations.add(concept_lower)
        concept_lower_spaces = concept_with_spaces.lower()
        variations.add(concept_lower_spaces)
        
        # Try each variation as a whole-word match
        import re
        for variation in variations:
            pattern = r'\b' + re.escape(variation) + r'\b'
            
            if re.search(pattern, linked_description, re.IGNORECASE):
                # Replace first match with markdown link
                replacement = f"[{variation}](../{concept}/{concept}_itself.md)"
                linked_description = re.sub(pattern, replacement, linked_description, count=1, flags=re.IGNORECASE)
                break  # Only link first occurrence per concept
    
    return linked_description

def find_auto_relationships(content: str, base_path: str, current_concept: str) -> List[str]:
    """Find ALL concept mentions in content using the same fuzzy matching as auto-linking."""
    concepts_dir = Path(base_path) / "concepts"
    if not concepts_dir.exists():
        return []
    
    # Get all existing concept directory names
    existing_concepts = [d.name for d in concepts_dir.iterdir() if d.is_dir() and d.name != current_concept]
    
    mentioned_concepts = []
    for concept in existing_concepts:
        # Generate the same formatting variations as auto-linking
        variations = set()
        variations.add(concept)
        concept_with_spaces = concept.replace('_', ' ')
        variations.add(concept_with_spaces)
        variations.add(concept_with_spaces.title())
        variations.add(concept.upper())
        variations.add(concept_with_spaces.upper())
        variations.add(concept.lower())
        variations.add(concept_with_spaces.lower())
        
        # Check if any variation appears in content
        import re
        for variation in variations:
            pattern = r'\b' + re.escape(variation) + r'\b'
            if re.search(pattern, content, re.IGNORECASE):
                mentioned_concepts.append(concept)
                break  # Found this concept, don't need to check other variations
    
    return mentioned_concepts


def infer_relationships_for_missing_concept(missing_concept: str, concepts_dir: Path) -> Dict[str, List[str]]:
    """Infer what relationships a missing concept should have based on existing references to it."""
    relationship_inverses = {
        'is_a': 'has_instances',
        'part_of': 'has_parts', 
        'depends_on': 'supports',
        'instantiates': 'has_instances',
        'relates_to': 'relates_to'  # bidirectional
    }
    
    inferred_relationships = {}
    
    # Scan all existing concept relationship files
    for concept_dir in concepts_dir.iterdir():
        if not concept_dir.is_dir():
            continue
            
        components_dir = concept_dir / "components"
        if not components_dir.exists():
            continue
            
        # Check each relationship type directory
        for rel_dir in components_dir.iterdir():
            if not rel_dir.is_dir() or rel_dir.name == "description":
                continue
                
            rel_type = rel_dir.name
            if rel_type not in relationship_inverses:
                continue
                
            # Check relationship files for references to missing concept
            for rel_file in rel_dir.glob("*.md"):
                content = rel_file.read_text(encoding="utf-8")
                
                # Look for links to the missing concept
                link_pattern = re.compile(rf"\[{re.escape(missing_concept)}\]\(wiki/concepts/{re.escape(missing_concept)}\)")
                if link_pattern.search(content):
                    # Found a reference! Infer the inverse relationship
                    inverse_rel = relationship_inverses[rel_type]
                    if inverse_rel not in inferred_relationships:
                        inferred_relationships[inverse_rel] = []
                    inferred_relationships[inverse_rel].append(concept_dir.name)
    
    return inferred_relationships


def check_missing_concepts_and_manage_file(base_path: str, current_concept: str) -> List[str]:
    """Check for missing concepts and manage missing_concepts.md file with relationship inference."""
    concepts_dir = Path(base_path) / "concepts"
    if not concepts_dir.exists():
        return []
    
    # Get all existing concept names
    existing_concepts = {d.name.lower(): d.name for d in concepts_dir.iterdir() if d.is_dir()}
    
    # Find broken links in markdown files - look for relative path format ../concept_name/
    link_pattern = re.compile(r"\[.*?\]\(\.\./([^/]+)/[^)]*\)")
    missing_concepts = set()
    
    for md_file in concepts_dir.rglob("*.md"):
        content = md_file.read_text(encoding="utf-8")
        for match in link_pattern.findall(content):
            concept_name = match  # match is just the concept_name
            if concept_name.lower() not in existing_concepts:
                missing_concepts.add(concept_name)
    
    # Remove the current concept if it was just created
    if current_concept:
        missing_concepts.discard(current_concept)
        # Also remove case variations
        missing_concepts = {c for c in missing_concepts if c.lower() != current_concept.lower()}
    
    # Path to missing concepts file
    missing_file = Path(base_path) / "missing_concepts.md"
    
    processed = []
    
    if missing_concepts:
        # Create content with relationship inference
        content = ["# Missing Concepts", ""]
        content.append("The following concepts are referenced but don't exist yet.")
        content.append("Relationships are inferred from existing references:")
        content.append("")
        
        for concept_name in sorted(missing_concepts):
            # Infer relationships for this missing concept
            inferred_rels = infer_relationships_for_missing_concept(concept_name, concepts_dir)
            
            # Find similar concepts for suggestions
            suggestions = get_close_matches(
                concept_name.lower(), 
                existing_concepts.keys(), 
                n=3, 
                cutoff=0.6
            )
            suggestion_names = [existing_concepts[s] for s in suggestions]
            
            content.append(f"## {concept_name}")
            
            if inferred_rels:
                content.append("**Inferred relationships:**")
                for rel_type, related_concepts in inferred_rels.items():
                    content.append(f"- {rel_type}: {', '.join(related_concepts)}")
                content.append("")
            
            if suggestion_names:
                content.append(f"**Similar existing concepts:** {', '.join(suggestion_names)}")
            else:
                content.append("**Similar existing concepts:** None")
            content.append("")
        
        missing_file.write_text("\n".join(content))
        processed.append(f"Updated missing_concepts.md with {len(missing_concepts)} missing concepts and inferred relationships")
    else:
        # Remove file if no missing concepts
        if missing_file.exists():
            missing_file.unlink()
            processed.append("Removed missing_concepts.md - all concepts now exist")
        else:
            processed.append("No missing concepts found")
    
    return processed

def commit_and_push(config: ConceptConfig, base_path: str, commit_msg: str) -> Dict[str, str]:
    """Commit and push changes to the remote repository."""
    commands = [
        ["git", "add", "."],
        ["git", "commit", "-m", commit_msg],
        ["git", "push", "origin", config.private_wiki_branch],
    ]

    for cmd in commands:
        result = run_git_command(cmd, base_path)
        if "error" in result:
            return {"error": f"Git command failed: {result['error']}"}
    return {"output": "Changes pushed successfully"}


def create_concept_in_neo4j(config: ConceptConfig, concept_name: str, description: str, relationships: Dict[str, List[str]]) -> str:
    """Create concept in Neo4j with :Wiki namespace using minimal tokens."""
    try:
        from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder
        
        graph = KnowledgeGraphBuilder(
            uri=config.neo4j_url,
            user=config.neo4j_username,
            password=config.neo4j_password
        )
        
        # Create indexes for Wiki namespace
        index_queries = [
            "CREATE INDEX wiki_concept_name IF NOT EXISTS FOR (c:Wiki) ON (c.n)",
            "CREATE INDEX wiki_concept_canonical IF NOT EXISTS FOR (c:Wiki) ON (c.c)",
        ]
        
        for query in index_queries:
            graph.execute_query(query)
        
        # Create concept node
        concept_query = """
        MERGE (c:Wiki {n: $name, c: $canonical_form})
        SET c.d = $description
        SET c.t = datetime($timestamp)
        RETURN c.n as node_id
        """
        
        from datetime import datetime
        params = {
            'name': concept_name,
            'canonical_form': concept_name.lower().replace(' ', '_'),
            'description': description or f"No description available for {concept_name}.",
            'timestamp': datetime.now().isoformat()
        }
        
        result = graph.execute_query(concept_query, params)
        
        # Create relationships
        for rel_type, related_concepts in relationships.items():
            for related_concept in related_concepts:
                rel_query = f"""
                MATCH (c1:Wiki {{n: $from_concept}})
                MERGE (c2:Wiki {{n: $to_concept, c: $to_canonical}})
                MERGE (c1)-[r:{rel_type.upper()}]->(c2)
                SET r.ts = datetime($timestamp)
                """
                
                rel_params = {
                    'from_concept': concept_name,
                    'to_concept': related_concept,
                    'to_canonical': related_concept.lower().replace(' ', '_'),
                    'timestamp': datetime.now().isoformat()
                }
                
                graph.execute_query(rel_query, rel_params)
        
        graph.close()
        return f"Neo4j: Created concept '{concept_name}' with {sum(len(items) for items in relationships.values())} relationships"
        
    except ImportError:
        traceback.print_exc()
        return "Neo4j: Driver not available, skipping graph storage"
    except Exception as e:
        traceback.print_exc()
        return f"Neo4j: Failed to create concept - {str(e)}"


def add_concept_tool_func(
    concept_name: str,
    description: Optional[str] = None,
    relationships: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Create a new concept with its component files.

    Raises:
        Exception: if any git command or file operation fails.
    """
    # Get config from environment variables
    import os
    github_pat = os.getenv('GITHUB_PAT')
    repo_url = os.getenv('REPO_URL')
    branch = os.getenv('BRANCH', 'main')
    
    if not github_pat or not repo_url:
        raise Exception("GITHUB_PAT and REPO_URL environment variables must be set")
    
    if not relationships or len(relationships) == 0:
        raise Exception("ERROR: There is no reason you cannot put a WIP is_a, part_of, or has_type. Relationships cannot be empty or none.")
    
    # Only use BASE_PATH if explicitly set, otherwise let ConceptConfig use HEAVEN_DATA_DIR
    base_path_override = os.getenv('BASE_PATH')
    
    config = ConceptConfig(
        github_pat=github_pat,
        repo_url=repo_url,
        neo4j_url=os.getenv('NEO4J_URI', 'bolt://host.docker.internal:7687'),
        neo4j_username=os.getenv('NEO4J_USER', 'neo4j'),
        neo4j_password=os.getenv('NEO4J_PASSWORD', 'password'),
        branch=branch,
        base_path=base_path_override  # Only override if explicitly set
    )
    base_dir = config.base_path

    result = setup_git_repo(config, base_dir)
    if "error" in result:
        raise Exception(result["error"])

    result = sync_with_remote(config, base_dir)
    if "error" in result:
        raise Exception(result["error"])

    # Normalize concept name for directory names
    concept_name = concept_name.replace(" ", "_").capitalize()
    concept_path = Path(base_dir) / "concepts" / concept_name
    components_path = concept_path / "components"

    concept_path.mkdir(parents=True, exist_ok=True)
    components_path.mkdir(exist_ok=True)

    # Auto-link the description to create proper Zettelkasten connections
    if description:
        linked_description = auto_link_description(description, base_dir, concept_name)
    else:
        linked_description = f"No description available for {concept_name}."
    
    # Build full concept content first to scan for auto-relationships
    full_content = f"{concept_name}\n{linked_description}"
    
    # Find auto-relationships by scanning content for existing concept names
    auto_mentioned = find_auto_relationships(full_content, base_dir, concept_name)
    
    relationship_dict = {}
    if relationships:
        for rel in relationships:
            rel_type = rel["relationship"]
            rel_items = rel["related"]
            relationship_dict[rel_type] = rel_items
    
    # Add auto-discovered relationships as "auto_related_to"
    if auto_mentioned:
        if "auto_related_to" not in relationship_dict:
            relationship_dict["auto_related_to"] = []
        relationship_dict["auto_related_to"].extend(auto_mentioned)

    for rel_type, rel_items in relationship_dict.items():
        rel_dir = components_path / rel_type
        rel_dir.mkdir(exist_ok=True)

        rel_file = rel_dir / f"{concept_name}_{rel_type}.md"
        content = [
            f"# {rel_type.title()} Relationships for {concept_name}",
            "",
        ]
        for item in rel_items:
            # Normalize the target concept name to match directory structure
            normalized_item = item.replace(" ", "_").capitalize()
            item_url = f"../{normalized_item}/{normalized_item}_itself.md"
            content.append(f"- {concept_name} {rel_type} [{item}]({item_url})")
        rel_file.write_text("\n".join(content))

    description_file = components_path / "description.md"
    description_file.write_text(linked_description)

    main_file = concept_path / f"{concept_name}.md"
    main_content = [
        f"# {concept_name}",
        "",
        "## Overview",
        linked_description,
        "",
        "## Relationships",
    ]

    for rel_type, items in relationship_dict.items():
        main_content.append(f"### {rel_type.title()} Relationships")
        for item in items:
            main_content.append(f"- {item}")
    main_file.write_text("\n".join(main_content))

    # Generate the _itself.md file by combining description and relationships
    itself_file = concept_path / f"{concept_name}_itself.md"
    itself_content = [
        f"# {concept_name}",
        "",
        "## Overview",
        linked_description,
        "",
        "## Relationships"
    ]
    
    # Add relationships from component files (extract just the - lines)
    for rel_type, items in relationship_dict.items():
        itself_content.extend(["", f"### {rel_type.title()} Relationships", ""])
        for item in items:
            # Normalize the target concept name to match directory structure
            normalized_item = item.replace(" ", "_").capitalize()
            item_url = f"../{normalized_item}/{normalized_item}_itself.md"
            itself_content.append(f"- {concept_name} {rel_type} [{item}]({item_url})")
    
    itself_file.write_text("\n".join(itself_content))

    # Check for missing concepts and update file BEFORE committing
    try:
        file_updates = check_missing_concepts_and_manage_file(base_dir, concept_name)
        file_summary = "; ".join(file_updates) if file_updates else "No file updates needed"
    except Exception as e:
        traceback.print_exc()
        file_summary = f"Missing concept file update failed: {e}"

    result = commit_and_push(config, base_dir, f"Add {concept_name} concept")
    if "error" in result:
        raise Exception(result["error"])

    # Store concept in Neo4j :Wiki namespace
    neo4j_result = create_concept_in_neo4j(config, concept_name, description, relationship_dict)

    return f"Concept '{concept_name}' created successfully at {concept_path}. {neo4j_result}. Missing concepts: {file_summary}"


class AddConceptToolArgsSchema(ToolArgsSchema):
    arguments: Dict[str, Dict[str, Any]] = {
        "concept_name": {
            "name": "concept_name",
            "type": "str",
            "description": "Name of the concept to be created"
        },
        "description": {
            "name": "description",
            "type": "str",
            "description": "Description of the concept",
            "default": "No description available."
        },
        "relationships": {
            "name": "relationships",
            "type": "list",
            "description": "List of relationship objects",
            "items": {
                "type": "dict",
                "properties": {
                    "relationship": {
                        "type": "str",
                        "description": "Type of relationship"
                    },
                    "related": {
                        "type": "list",
                        "description": "Related items for the relationship",
                        "items": {"type": "str"}
                    }
                }
            },
            "default": []
        }
    }


class AddConceptTool(BaseHeavenTool):
    name = "AddConceptTool"
    description = "Creates a new concept with its component files in the wiki repository"
    func = add_concept_tool_func
    args_schema = AddConceptToolArgsSchema
    is_async = False

