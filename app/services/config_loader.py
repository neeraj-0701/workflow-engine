"""
Configuration loader for workflow YAML definitions.
Supports hot reload - configs can be updated without restarting the server.
"""

import os
import glob
import logging
import threading
from pathlib import Path
from typing import Any, Optional
import yaml

logger = logging.getLogger(__name__)

CONFIGS_DIR = Path(os.getenv("CONFIGS_DIR", "configs"))


class ConfigLoader:
    """
    Loads and caches workflow configurations from YAML files.
    Supports hot reload via file watching.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """Singleton pattern for shared config state."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._configs = {}
                    cls._instance._initialized = False
        return cls._instance

    def load_all(self) -> dict[str, Any]:
        """Load all YAML config files from the configs directory."""
        configs = {}
        
        if not CONFIGS_DIR.exists():
            logger.warning(f"Configs directory not found: {CONFIGS_DIR}")
            return configs

        yaml_files = list(CONFIGS_DIR.glob("*.yaml")) + list(CONFIGS_DIR.glob("*.yml"))
        
        for filepath in yaml_files:
            try:
                with open(filepath, "r") as f:
                    data = yaml.safe_load(f)
                if data:
                    for workflow_name, workflow_config in data.items():
                        configs[workflow_name] = workflow_config
                        logger.info(f"  📋 Loaded workflow: {workflow_name} from {filepath.name}")
            except Exception as e:
                logger.error(f"Failed to load config {filepath}: {e}")

        self._configs = configs
        self._initialized = True
        return configs

    def get_workflow(self, workflow_type: str) -> Optional[dict]:
        """Get a specific workflow config by name."""
        if not self._initialized:
            self.load_all()
        
        config = self._configs.get(workflow_type)
        if not config:
            # Try hot reload
            self.load_all()
            config = self._configs.get(workflow_type)
        
        return config

    def list_workflows(self) -> list[dict]:
        """List all available workflows with metadata."""
        if not self._initialized:
            self.load_all()
        
        result = []
        for name, config in self._configs.items():
            steps = config.get("steps", [])
            result.append({
                "name": name,
                "description": config.get("description", ""),
                "steps": [s.get("name", s) if isinstance(s, dict) else s for s in steps],
                "step_count": len(steps),
                "rules_count": len(config.get("rules", [])),
                "timeout_seconds": config.get("timeout_seconds", 30),
                "max_retries": config.get("max_retries", 3),
            })
        return result

    def reload(self) -> dict[str, Any]:
        """Force reload all configs (hot reload endpoint)."""
        logger.info("🔄 Hot reloading workflow configurations...")
        self._initialized = False
        return self.load_all()

    def get_all(self) -> dict[str, Any]:
        if not self._initialized:
            self.load_all()
        return self._configs
