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
from app.verification.snapshot.fields import Field, FieldSource
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
# income_employer) — both moved from dormant to live; ID-5 is no-AI and pulls no group.
_DORMANT_EXPECTED = frozenset(
    {
        "income_docs",
        "income_stability",
        "stmt_facts",
        "asset_facts",
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
    )  # the 4 remaining income/asset groups (2 went live with LP-389)
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
    un-stubbed group (they are all document-subject and run on the same fixture doc). Un-overridden groups
    abstain (empty tags → fail-closed unknown)."""
    return {group: overrides.get(group, _AiStub({})) for group in _DORMANT_EXPECTED}


async def test_probe_reports_what_a_dormant_group_produced_per_document() -> None:
    # income_amounts is now LIVE (IN-1); this probes a STILL-dormant group — income_docs on a VOE.
    snap = _snapshot(
        [
            DocumentEntry(
                content_id="voe1",
                document_type="voe",
                fields={"employer_name": Field.present("Acme", source=FieldSource.EXTRACTED)},
            )
        ]
    )
    stub = _AiStub({"voe_present": "yes", "future_employment": "no", "offer_letter_present": "no"})
    report = await probe_dormant_groups_on_snapshot(
        snap, ai_reasoners=_all_dormant_stubs(income_docs=stub)
    )

    assert stub.calls == 1  # the injected reasoner was actually invoked
    grp = next(g for g in report.groups if g.key == "income_docs")
    values = {(o.tag_id, o.value, o.document_type) for o in grp.observations}
    assert (
        "income.voe_present",
        "yes",
        "voe",
    ) in values  # produced a real value on the VOE
    assert grp.verdict == "produces_usable"
    assert grp.doctypes_with_real_value == {"voe"}  # LP-377-D's gating input
    # The probe covers the WHOLE dormant set, not just the stubbed one.
    assert {g.key for g in report.groups} == _DORMANT_EXPECTED


async def test_uniform_unknown_is_reported_as_a_finding_not_a_pass() -> None:
    # income_amounts is now LIVE (IN-1); probe the still-dormant income_docs group.
    snap = _snapshot([DocumentEntry(content_id="voe1", document_type="voe", fields={})])
    # The stub abstains on every tag — the LP-368 pattern. This must NOT read as "produces_usable".
    stub = _AiStub(
        {
            "voe_present": "unknown",
            "future_employment": "unknown",
            "offer_letter_present": "unknown",
        }
    )
    report = await probe_dormant_groups_on_snapshot(
        snap, ai_reasoners=_all_dormant_stubs(income_docs=stub)
    )
    grp = next(g for g in report.groups if g.key == "income_docs")
    assert grp.real == []  # nothing usable
    assert grp.verdict == "mostly_abstains"  # honest — an abstention is a finding, not a pass
    assert grp.ai_failures == []  # a genuine model abstention is NOT an AI-call failure


async def test_ai_call_failure_reads_as_ai_failed_not_an_abstention() -> None:
    # materialize_tags degrades a failed AI call to `unknown` (it catches AIClientError), so a transient
    # outage looks like uniform-unknown. The probe MUST surface that as `ai_failed`, never read it as "the
    # producer abstains" (a false producer/applicability gap — the misdiagnosis this probe exists to prevent).
    snap = _snapshot([DocumentEntry(content_id="voe1", document_type="voe", fields={})])
    report = await probe_dormant_groups_on_snapshot(
        snap, ai_reasoners=_all_dormant_stubs(income_docs=_failing_reasoner)
    )
    grp = next(g for g in report.groups if g.key == "income_docs")
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
