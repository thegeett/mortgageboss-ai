"""Tests for the prompt loader (LP-38)."""

import os
from pathlib import Path

import pytest
from app.ai.prompt_loader import load_prompt


def test_loads_the_classifier_prompt() -> None:
    text = load_prompt("classification/document_classifier.txt")
    # The LP-59 template carries the catalog-injection placeholder + the JSON shape.
    assert "{document_type_catalog}" in text  # filled by render_classification_prompt
    assert "document_type" in text  # instructs the JSON shape


def test_is_cwd_independent(tmp_path: Path) -> None:
    """The path resolves relative to the prompts dir, not the process CWD."""
    original = Path.cwd()
    load_prompt.cache_clear()
    os.chdir(tmp_path)
    try:
        text = load_prompt("classification/document_classifier.txt")
        assert "document_type" in text
    finally:
        os.chdir(original)


def test_rejects_path_traversal() -> None:
    with pytest.raises(ValueError, match="escapes the prompts dir"):
        load_prompt("../../core/config.py")


def test_missing_prompt_raises() -> None:
    with pytest.raises(FileNotFoundError):
        load_prompt("classification/does_not_exist.txt")
