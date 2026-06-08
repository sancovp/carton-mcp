# Simplified config for MCP - no JSON file dependencies
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class ConceptConfig:
    """Simple config class for Idea Concepts MCP."""
    
    def __init__(self,
                 github_pat: str = None,
                 repo_url: str = None,
                 neo4j_url: str = None,
                 neo4j_username: str = None,
                 neo4j_password: str = None,
                 branch: str = "main",
                 base_path: str = None,
                 neo4j_database: str = "neo4j"):
        # Env var fallbacks for cross-MCP usage
        github_pat = github_pat or os.getenv("GITHUB_PAT", "")
        repo_url = repo_url or os.getenv("CARTON_REPO_URL", "")
        neo4j_url = neo4j_url or os.getenv("NEO4J_URI", "bolt://host.docker.internal:7687")
        neo4j_username = neo4j_username or os.getenv("NEO4J_USER", "neo4j")
        neo4j_password = neo4j_password or os.getenv("NEO4J_PASSWORD", "password")
        # GitHub config
        self.github_pat = github_pat
        self.repo_url = repo_url
        self.branch = branch
        self.base_path = self._get_base_path(base_path)
        
        # Neo4j config
        self.neo4j_url = neo4j_url
        self.neo4j_username = neo4j_username
        self.neo4j_password = neo4j_password
        self.neo4j_database = neo4j_database
    
    def _get_base_path(self, base_path: str = None) -> str:
        """Get base path for concepts, defaulting to HEAVEN_DATA_DIR/wiki/concepts/"""
        if base_path:
            logger.info(f"Using provided base_path: {base_path}")
            return base_path
        
        heaven_data_dir = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
        logger.info(f"Using HEAVEN_DATA_DIR: {heaven_data_dir}")
        
        heaven_path = Path(heaven_data_dir)
        if not heaven_path.exists():
            heaven_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created HEAVEN_DATA_DIR path: {heaven_data_dir}")
        
        # Return the wiki root directory, not the concepts subdirectory
        # The add_concept_tool will clone the repo here and work with concepts/ inside it
        wiki_path = heaven_path / "wiki"
        logger.info(f"Using wiki path: {wiki_path}")
        
        return str(wiki_path)
    
    @property
    def private_wiki_url(self) -> str:
        return self.repo_url
    
    @property
    def private_wiki_branch(self) -> str:
        return self.branch