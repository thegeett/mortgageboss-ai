"""LP-606 — an AI group must not be asked about a subject it has no data for.

WHAT HAPPENED. `credit_derogatory` asks, per liability, "does this account carry ANY derogatory
mark?". It was asked about all four of LF-3CVT's MISMO-STATED liabilities — rows carrying a type, a
holder, a monthly payment and a balance, and no credit history whatsoever, on a file with no credit
report. It answered "no" for every one:

    "APPLE CARD/GS BANK USA revolving account with $36 balance and $25 monthly payment.
     No indicators of derogatory status. Account appears current..."

Absence of a derogatory field is not absence of derogatory history. Its own prompt says "when you
cannot determine a value, return unknown. Never guess." — it read silence as evidence instead.

THE COST. `liab.is_derogatory = "no"` makes CR-6's applicability false, so all four subjects resolved
`not_applicable`, which is not persisted, so the four HONEST couldnt_checks from the previous run were
retired as "no longer applies". A processor was shown four debts cleared of derogatory credit on the
strength of an application row.
"""

from __future__ import annotations

from app.verification.rule_engine.enumerators import _SOURCE_CREDIT_REPORT, _SOURCE_MISMO
from app.verification.tag_materialization.ai import _gate_subjects
from app.verification.tag_materialization.declarations import load_ai_groups


class _Row:
    def __init__(self, source: str) -> None:
        self.source = source


def test_credit_derogatory_is_scoped_to_credit_report_tradelines() -> None:
    """The declaration itself, so the scoping cannot be lost in a refactor of the gate."""
    assert load_ai_groups()["credit_derogatory"].subject_source == _SOURCE_CREDIT_REPORT


def test_a_stated_liability_is_never_asked_about_derogatory_credit() -> None:
    """THE FIX. A MISMO row is dropped before the model sees it, so the tag stays absent and CR-6
    couldnt_checks — the honest answer — instead of being told "no"."""
    group = load_ai_groups()["credit_derogatory"]
    subjects = [
        ("lia_mismo_1", _Row(_SOURCE_MISMO)),
        ("lia_mismo_2", _Row(_SOURCE_MISMO)),
        ("tradeline_1", _Row(_SOURCE_CREDIT_REPORT)),
    ]

    kept = _gate_subjects(group, subjects)

    assert [sid for sid, _ in kept] == ["tradeline_1"]


def test_a_group_that_declares_no_source_is_untouched() -> None:
    """Additive: every other group must enumerate exactly as before."""
    unscoped = next(g for g in load_ai_groups().values() if g.subject_source is None)
    subjects = [("a", _Row(_SOURCE_MISMO)), ("b", _Row(_SOURCE_CREDIT_REPORT))]

    assert len(_gate_subjects(unscoped, subjects)) == 2


def test_the_source_gate_is_not_behind_the_reversibility_flag(monkeypatch) -> None:
    """`gate_ai_groups` exists to make the DOCUMENT gate reversible — that gate only skips a redundant
    call, and the prompt's own abstention is the backstop. This is a different thing: a group asked
    about a subject it has no data for does NOT abstain, it answers. Leaving this switchable would
    leave the false all-clear switchable with it."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "gate_ai_groups", False)
    group = load_ai_groups()["credit_derogatory"]

    kept = _gate_subjects(group, [("m", _Row(_SOURCE_MISMO)), ("t", _Row(_SOURCE_CREDIT_REPORT))])

    assert [sid for sid, _ in kept] == ["t"]
