"""LP-378 — the dormant tag-layer smoke test: the probe is OFF-path, persists nothing, uses real reasoners.

These pin the INVARIANTS (the probe cannot leak into a normal run, writes nothing of record, and calls the
real model unless a stub is injected). The real-data REPORT — what the dormant groups actually produce — is a
one-off run on LF-6T3N recorded in docs/tickets/LP-378.md, not a CI test (it costs a real AI call).
"""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.ai.client import AIClientError
from app.services.verification_run import _required_ai_groups
from app.verification.eval import dormant_probe
from app.verification.eval.dormant_probe import (
    dormant_ai_groups,
    probe_dormant_groups_on_snapshot,
)
from app.verification.snapshot.model import (
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
    TagsSection,
)
from app.verification.tag_materialization.ai import (
    AiGroupResult,
    AiSubjectJudgment,
    AiTagJudgment,
    Reasoner,
)
from app.verification.tag_materialization.declarations import load_ai_groups

pytestmark = pytest.mark.anyio

# LP-389 activated IN-1 (needs income_amounts, via the derived shortfall its bar declares) and IN-5 (needs
# income_employer) — both moved from dormant to live; ID-5 is no-AI and pulls no group. LP-393-6 activated
# IN-7/IN-10/IN-11 (income_stability) and AS-11 (asset_facts) — both groups moved from dormant to live.
_DORMANT_EXPECTED = frozenset(
    {
        # LP-418 — the producer batch declared two AI groups whose rules are not yet written/live, so they
        # are the dormant set: txn_nsf (AS-7's producer, transaction-subject) and occupancy_rental (IN-14's
        # producer, loan-subject). They activate with their OWN later tickets; until then they are dormant.
        # (income_docs left in LP-428, stmt_facts in LP-429 — as their rules went live.)
        "txn_nsf",
        "occupancy_rental",
        # LP-444 — credit_profile (CR-4's producer, borrower-subject) is declared but CR-4 is inert, so it is
        # dormant until CR-4 activates (its own calibration ticket).
        "credit_profile",
        # LP-490 — the credit AI cohort's four groups. Every rule reading them (CR-5/CR-6/CR-8/CR-10) is
        # INERT (not-calibratable-yet → is_eligible False, LP-484), so all four are dormant by design.
        # They activate with their own calibration ticket, exactly as credit_profile will.
        "credit_inquiries",
        "credit_derogatory",
        "credit_mortgage_history",
        "credit_collections",
    }
)
_LIVE_EXPECTED = frozenset(
    {
        "id_address",
        "id_name",
        "id_poa",
        "id_title",
        "income_amounts",
        "income_employer",
        "income_stability",
        "income_docs",  # LP-428 — now LIVE: IN-8 (voe_present) + IN-9 (offer_letter_present) activated
        "stmt_facts",  # LP-429 — now LIVE: AS-6 (account ownership) activated
        "asset_facts",
        "occupancy",
        "txn_stage_a",
    }
)


# --------------------------------------------------------------------------- #
# The dormant set is exactly the complement of the live set (single source of truth)
# --------------------------------------------------------------------------- #
def test_dormant_set_is_all_declared_groups_minus_the_live_ones() -> None:
    all_groups = frozenset(load_ai_groups())
    dormant = dormant_ai_groups()
    assert (
        dormant == _DORMANT_EXPECTED
    )  # income_docs + stmt_facts, plus LP-418's two new producer groups (txn_nsf, occupancy_rental)
    assert (
        _required_ai_groups() == _LIVE_EXPECTED
    )  # the normal run's set is unchanged (byte-identical)
    assert dormant.isdisjoint(_required_ai_groups())  # a live run can never run a dormant group
    assert dormant | _required_ai_groups() == all_groups  # together they cover every declared group


def test_probe_module_is_never_imported_by_the_normal_run() -> None:
    # The orchestrator must not reference the probe — the ONLY way the probe stays off the normal path.
    import app.services.verification_run as vr

    assert "dormant_probe" not in inspect.getsource(vr)


# --------------------------------------------------------------------------- #
# The probe runs the dormant groups over a snapshot and reports what they produce (no DB, no writes)
# --------------------------------------------------------------------------- #
def _snapshot(entries: list[DocumentEntry]) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 18, tzinfo=UTC),
        documents=DocumentsSection.present(entries),
        mismo=MismoSection.present({}),
        tags=TagsSection.present({}),
    )


class _AiStub:
    """A deterministic reasoner — supplies the given short-name values per subject."""

    def __init__(self, by_short: dict[str, str]) -> None:
        self.by_short = by_short
        self.calls = 0

    async def __call__(self, context_json: str) -> AiGroupResult:
        self.calls += 1
        subjects = json.loads(context_json)["subjects"]
        judgments = [
            AiSubjectJudgment(
                index=int(s["index"]),
                tags={k: AiTagJudgment(v, 0.9, "stub reasoning") for k, v in self.by_short.items()},
            )
            for s in subjects
        ]
        return AiGroupResult(judgments, 1, 1, "stub", False)


async def _failing_reasoner(_context_json: str) -> AiGroupResult:
    """A reasoner whose AI call fails — materialize_tags catches AIClientError and degrades to unknown."""
    raise AIClientError("AI provider down")


def _all_dormant_stubs(**overrides: Reasoner) -> dict[str, Reasoner]:
    """A reasoner for EVERY dormant group — so a unit test never falls through to the real model for an
    un-stubbed group (the remaining dormant groups are loan- and transaction-subject; an un-overridden one
    abstains — empty tags → fail-closed unknown — and produces nothing without its subjects present)."""
    return {group: overrides.get(group, _AiStub({})) for group in _DORMANT_EXPECTED}


async def test_probe_reports_what_a_dormant_group_produced_per_subject() -> None:
    # stmt_facts is now LIVE (AS-6, LP-429); the last document-subject dormant group is gone, so this probes a
    # STILL-dormant LOAN-subject group — occupancy_rental (IN-14's producer). The probe machinery is
    # subject-agnostic (document_type is None for a non-document subject); a real value still reports as usable.
    snap = _snapshot([DocumentEntry(content_id="stmt1", document_type="bank_statement", fields={})])
    stub = _AiStub({"rental_support": "adequate"})  # a real (non-unknown) value on the loan subject
    report = await probe_dormant_groups_on_snapshot(
        snap, ai_reasoners=_all_dormant_stubs(occupancy_rental=stub)
    )

    assert stub.calls == 1  # the injected reasoner was actually invoked
    grp = next(g for g in report.groups if g.key == "occupancy_rental")
    values = {(o.tag_id, o.value) for o in grp.observations}
    assert ("occupancy.rental_support", "adequate") in values  # produced a real value
    assert grp.verdict == "produces_usable"
    assert grp.doctypes_with_real_value == {None}  # a loan subject carries no document_type
    # The probe covers the WHOLE dormant set, not just the stubbed one.
    assert {g.key for g in report.groups} == _DORMANT_EXPECTED


async def test_uniform_unknown_is_reported_as_a_finding_not_a_pass() -> None:
    # stmt_facts is now LIVE (LP-429); probe the still-dormant occupancy_rental group.
    snap = _snapshot([DocumentEntry(content_id="stmt1", document_type="bank_statement", fields={})])
    # The stub abstains — the LP-368 pattern. This must NOT read as "produces_usable".
    stub = _AiStub({"rental_support": "unknown"})
    report = await probe_dormant_groups_on_snapshot(
        snap, ai_reasoners=_all_dormant_stubs(occupancy_rental=stub)
    )
    grp = next(g for g in report.groups if g.key == "occupancy_rental")
    assert grp.real == []  # nothing usable
    assert grp.verdict == "mostly_abstains"  # honest — an abstention is a finding, not a pass
    assert grp.ai_failures == []  # a genuine model abstention is NOT an AI-call failure


async def test_ai_call_failure_reads_as_ai_failed_not_an_abstention() -> None:
    # materialize_tags degrades a failed AI call to `unknown` (it catches AIClientError), so a transient
    # outage looks like uniform-unknown. The probe MUST surface that as `ai_failed`, never read it as "the
    # producer abstains" (a false producer/applicability gap — the misdiagnosis this probe exists to prevent).
    snap = _snapshot([DocumentEntry(content_id="stmt1", document_type="bank_statement", fields={})])
    report = await probe_dormant_groups_on_snapshot(
        snap, ai_reasoners=_all_dormant_stubs(occupancy_rental=_failing_reasoner)
    )
    grp = next(g for g in report.groups if g.key == "occupancy_rental")
    assert grp.real == []
    assert grp.ai_failures  # the failure is surfaced, distinct from an abstention
    assert grp.abstentions == []  # a call failure is not counted as a genuine abstention
    assert grp.verdict == "ai_failed"  # NOT "mostly_abstains"


# --------------------------------------------------------------------------- #
# Persists nothing of record + passes reasoners straight through (real when None)
# --------------------------------------------------------------------------- #
def test_probe_module_has_no_persistence_call_sites() -> None:
    # The "persists nothing of record" proof: match CALL forms (a trailing "(" or a persist function name)
    # so the module's own docstring — which mentions "no reconcile" as prose — does not false-positive. The
    # only DB touch in the whole module is ``build_snapshot`` (a READ); there is no write path to leak through.
    src = inspect.getsource(dormant_probe)
    for forbidden in ("db.add(", ".commit(", "persist_snapshot(", "reconcile_", "session.add("):
        assert forbidden not in src, f"the probe must persist nothing, found {forbidden!r}"
    assert "build_snapshot(" in src  # the sole DB call — a read


async def test_probe_passes_reasoners_through_defaulting_to_real(monkeypatch) -> None:
    # The probe must not silently force a stub: ai_reasoners=None reaches materialize_tags as None (which
    # resolves each group to the REAL reason_ai_group), and an injected dict passes through unchanged.
    captured: dict[str, object] = {}

    async def _fake_materialize(snapshot, **kwargs):
        captured["ai_reasoners"] = kwargs.get("ai_reasoners")
        return snapshot  # a snapshot with an empty tags layer → an empty report

    monkeypatch.setattr(dormant_probe, "materialize_tags", _fake_materialize)
    snap = _snapshot([])

    await probe_dormant_groups_on_snapshot(snap)
    assert captured["ai_reasoners"] is None  # None → the real model runs (no forced stub)

    stubs = {"income_docs": _AiStub({})}
    await probe_dormant_groups_on_snapshot(snap, ai_reasoners=stubs)
    assert captured["ai_reasoners"] is stubs  # an injected reasoner is honoured
