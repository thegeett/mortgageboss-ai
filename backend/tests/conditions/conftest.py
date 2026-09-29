"""Shared for every condition test.

THE READING'S MODEL IS ALWAYS MOCKED HERE (LP-923 review). The stub used to be an autouse fixture in
each test module, and helpers like `_asked` are imported across modules — a new file that imported one
and forgot the stub reached the real Anthropic API on a machine with a key. One autouse stub here covers
every file in the directory; a module's own stub still runs after it and wins.
"""

from __future__ import annotations

import pytest
from app.services import condition_reading
from tests.conditions.reading_fixture import fake_complete


@pytest.fixture(autouse=True)
def _reading_model_is_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(condition_reading, "complete", fake_complete())
