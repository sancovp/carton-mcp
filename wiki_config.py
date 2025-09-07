# wiki_config.py

import json
from pathlib import Path
from typing import Dict, Any

class WikiConfig:
    """Handle wiki configuration and GitHub settings."""

    def __init__(self, config_path: str = "/home/GOD/core/computer_use_demo/tools/base/utils/zk_config.json"):
        self.config_path = Path(config_path)
        self._config: Dict[str, Any] = {}
        self.load_config()

    def load_config(self) -> None:
        """Load configuration from JSON file."""
        try:
            with open(self.config_path, 'r') as f:
                self._config = json.load(f)
        except Exception as e:
            raise Exception(f"Failed to load config from {self.config_path}: {str(e)}")

    @property
    def private_wiki_url(self) -> str:
        """Get private wiki repository URL."""
        return self._config["wiki"]["private_repo"]["url"]

    @property
    def private_wiki_branch(self) -> str:
        """Get private wiki branch name."""
        return self._config["wiki"]["private_repo"]["branch"]

    @property
    def github_pat(self) -> str:
        """Get GitHub Personal Access Token."""
        return self._config["wiki"]["private_repo"]["pat"]

    @property
    def base_path(self) -> str:
        """Get wiki base path."""
        return self._config["wiki"]["base_path"]

def get_wiki_config() -> WikiConfig:
    """Get wiki configuration singleton."""
    if not hasattr(get_wiki_config, '_instance'):
        get_wiki_config._instance = WikiConfig()
    return get_wiki_config._instance
