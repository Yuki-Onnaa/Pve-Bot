import os
import sys
import tempfile

import pytest

# Make the project root importable when pytest runs from the repo root in CI.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Point data_store at a throwaway JSON file for each test."""
    import data_store

    path = tmp_path / "vouches.json"
    monkeypatch.setattr(data_store, "DATA_FILE", str(path))
    return data_store
