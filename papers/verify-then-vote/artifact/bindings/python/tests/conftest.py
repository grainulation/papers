"""Use the repository's release binary when no other reducer is configured."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_BIN = Path(__file__).resolve().parents[3] / "overturn" / "target" / "release" / "overturn"


def pytest_configure(config: pytest.Config) -> None:
    if os.environ.get("OVERTURN_TEST_INSTALLED") == "1":
        from overturn_arbiter import find_binary
        import overturn_arbiter
        expected = Path(overturn_arbiter.__file__).parent / "_bin" / "overturn"
        assert Path(find_binary()).resolve() == expected.resolve(), "installed tests must use the bundled reducer"
        assert "site-packages" in str(expected), "installed tests must import the installed wheel"
    elif "OVERTURN_BIN" not in os.environ and REPO_BIN.is_file():
        os.environ["OVERTURN_BIN"] = str(REPO_BIN)
