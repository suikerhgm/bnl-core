# tests/test_architect/conftest.py
import pytest
from pathlib import Path


@pytest.fixture(scope="session", autouse=True)
def ensure_data_dir():
    Path("data").mkdir(exist_ok=True)
