"""LP-600 — the re-keying migration must agree with the app, or it fixes nothing.

LP-598 stopped hashing the model's free-text `kind`. Correct going forward, and destructive once:
every stored row was keyed with its raw slug, none of which is in the new vocabulary, so on the first
run after deploy no stored row matches its draft. Every `signed_off` / `not_an_issue` row would be
retained under a key nothing produces again while the same finding re-opens beside it UN-DISMISSED —
a processor's decisions discarded, which is precisely what `finding_key` exists to protect.

The migration carries a FROZEN copy of the derivation, because a migration must keep meaning the same
thing forever and importing app code would let a later refactor rewrite history. The risk of freezing
is drift BEFORE it runs — which would leave every key mismatched and the bug fully intact. This file
is the guard on that risk.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from app.ai.snapshot_cross_source import SnapshotFindingDraft

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


#: The real slugs and sources observed on LF-3CVT, plus the shapes that broke earlier versions of the
#: normaliser (a formatted amount, a currency symbol, mixed case, punctuation).
_CASES = [
    ("citizenship_documentation", [{"label": "citizenship status", "value": "Non-permanent"}]),
    ("credit_report_absent", [{"label": "Stated liabilities", "value": "$4,895.00"}]),
    ("existing_mortgage_payoff_balance", [{"label": "application", "value": "451829.00"}]),
    ("Value-Mismatch", [{"label": "Tax Bill,", "value": "551,923"}]),
    ("value_mismatch", [{"label": "tax bill", "value": "551923"}]),
    ("some_invented_slug", [{"label": "a", "value": "1"}, {"label": "b", "value": "2"}]),
    ("other", []),
]


def test_the_migration_derives_exactly_what_the_app_derives() -> None:
    """THE GUARD ON FREEZING. If these disagree, the migration rewrites every key to a value the app
    never produces — leaving the dismissal loss it exists to prevent, and silently."""
    migration = _module()

    for kind, sources in _CASES:
        draft = SnapshotFindingDraft(kind=kind, title="t", detail="d", sources=sources)

        assert migration._finding_key(kind, sources) == draft.finding_key, (
            f"the migration and the app disagree on {kind!r} — the re-key would not match"
        )
        assert migration._normalised_kind(kind) == draft.normalised_kind


def test_the_frozen_vocabulary_matches_the_app() -> None:
    from app.ai.snapshot_cross_source import _KINDS

    assert _module()._KINDS == _KINDS


def test_a_dismissed_finding_keeps_its_key_across_the_rename() -> None:
    """THE POINT, stated as the behaviour a processor experiences: the two slugs the model used on
    consecutive runs must land on ONE key, so a dismissal made under the first survives the second."""
    migration = _module()

    sources = [{"label": "citizenship status", "value": "Non-permanent resident alien"}]
    before = migration._finding_key("citizenship_documentation", sources)
    after = migration._finding_key("citizenship_status_no_supporting_documents", sources)

    assert before == after
