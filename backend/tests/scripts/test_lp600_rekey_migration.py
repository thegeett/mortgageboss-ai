"""LP-600's re-keying migration, pinned to its OWN contract rather than to the app.

WHAT IT DID. LP-598 stopped hashing the model's free-text `kind`, which would have re-keyed every
stored row and thrown away every dismissal. This migration recomputed the keys so the transition kept
them.

WHY THIS TEST CHANGED. It used to assert the migration's frozen copy matched
`app.ai.snapshot_cross_source` exactly, to catch drift BEFORE the migration ran. It has run. Then
LP-604 changed identity again — to the snapshot ADDRESSES a finding cites — so the app and this
migration now legitimately disagree, and asserting equality would fail forever on a migration whose
behaviour is correct and finished.

A migration is history: it must keep meaning what it meant on the day it ran, whatever the app does
next. So it is pinned to fixed expected values computed from its own code, which still catches an
edit to the migration while letting the app move on.

(LP-604's own migration then DELETES these rows, because its key needs paths that no stored row has —
so on a fresh database this migration's output is superseded rather than relied upon.)
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

#: Key prefixes this migration produced on the day it was written. Hex, so detect-secrets flags them.
_CITIZENSHIP = "6a8eaf5ce03df949"  # pragma: allowlist secret
_TAX_BILL = "5669a77f0191f329"  # pragma: allowlist secret

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic/versions/20260820_1900_b7c4e91f2d38_lp600_rekey_snapshot_findings.py"
)


def _module():
    spec = importlib.util.spec_from_file_location("lp600_migration", _MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_frozen_derivation_still_produces_what_it_produced() -> None:
    """Fixed values, computed from the migration on the day it was written. An edit that changes what
    it means fails here; the app changing does not."""
    migration = _module()
    expected = [
        (
            "citizenship_documentation",
            [{"label": "citizenship status", "value": "Non-permanent"}],
            _CITIZENSHIP,
        ),
        ("Value-Mismatch", [{"label": "Tax Bill,", "value": "551,923"}], _TAX_BILL),
        ("value_mismatch", [{"label": "tax bill", "value": "551923"}], _TAX_BILL),
    ]
    for kind, sources, want in expected:
        assert migration._finding_key(kind, sources)[:16] == want, kind


def test_formatting_and_case_did_not_change_the_key() -> None:
    """The two rows above are the SAME facts written two ways — a formatted amount against a raw one,
    a capitalised label against a lowercase one. They had to land on one key or the dismissal was lost
    anyway, which is the failure the whole ticket existed to prevent."""
    migration = _module()

    assert migration._finding_key(
        "Value-Mismatch", [{"label": "Tax Bill,", "value": "551,923"}]
    ) == (migration._finding_key("value_mismatch", [{"label": "tax bill", "value": "551923"}]))


def test_an_off_vocabulary_kind_collapsed_to_other() -> None:
    """The transformation this migration performed on every stored row: the invented slugs the model
    had been producing all became `other`, because none of them was in the new vocabulary."""
    migration = _module()

    assert migration._normalised_kind("citizenship_documentation") == "other"
    assert migration._normalised_kind("credit_report_absent") == "other"
    assert migration._normalised_kind("value_mismatch") == "value_mismatch"
