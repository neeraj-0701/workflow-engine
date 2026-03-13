"""Test configuration and shared fixtures."""
import os

# Use in-memory SQLite for tests
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_workflow.db"
os.environ["CONFIGS_DIR"] = "configs"
