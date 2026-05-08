# tests/test_isolation_abstraction/conftest.py
import pytest
from pathlib import Path


@pytest.fixture(scope="session", autouse=True)
def ensure_data_dir():
    """Ensure data/ directory exists for any test that creates DBs."""
    Path("data").mkdir(exist_ok=True)


@pytest.fixture
def temp_db(tmp_path):
    """Provides a fresh SQLite DB path for each test."""
    return tmp_path / "test.db"
