"""LP-336 — the per_account enumerator + the fail-closed account-identity resolution.

THE DANGER (mirrors LP-332's borrower_id resolution): the masked account number is display-only /
non-matchable — ****1234 at Chase and ****1234 at Wells Fargo look IDENTICAL. A GUESSED grouping would
MIS-GROUP two accounts (fabricating a chaining break) or OVER-SPLIT one (hiding a real break). The
resolution therefore identifies by (INSTITUTION, masked-number) — both deterministic extraction fields —
and a statement missing EITHER is UNRESOLVABLE: surfaced (never grouped, never dropped) so a per_account
rule couldnt_checks it, never a guess.

These tests assert both failure directions + the consequence (a mis-group/over-split is prevented at the
grouping level, since AS-8's evaluator is a deferred shape).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.verification.rule_engine.enumerators import (
    ACCOUNT_UNRESOLVED_TAG,
    enumerate_subjects,
    is_known_enumerator,
    resolve_accounts,
)
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.pii import PiiField, PiiKind
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage

_LF = uuid4()


def _bank(v: str) -> Field:
    return Field.present(v, source=FieldSource.EXTRACTED)


def _acct(v: str) -> PiiField:
    return PiiField.from_raw(
        v, kind=PiiKind.ACCOUNT, loan_file_id=_LF, source=FieldSource.EXTRACTED
    )


def _stmt(
    cid: str, *, bank: str | None, num: str | None, dtype: str = "bank_statement"
) -> DocumentEntry:
    fields: dict = {}
    if bank is not None:
        fields["bank_name"] = _bank(bank)
    if num is not None:
        fields["account_number_masked"] = _acct(num)
    return DocumentEntry(content_id=cid, document_type=dtype, fields=fields)


def _tag(value: str) -> Tag:
    return Tag(
        value=value,
        confidence=0.9,
        reasoning="fixture",
        source_facts=("raw",),
        produced_by=TagProducedBy.PARSED,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _snap(docs, by_subject=None) -> Snapshot:
    return Snapshot(
        loan_file_id=_LF,
        run_id=uuid4(),
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
        documents=DocumentsSection.present(list(docs)),
        mismo=MismoSection.present({}),
        tags=TagsSection.present(by_subject or {}),
    )


def test_per_account_is_registered() -> None:
    assert is_known_enumerator("per_account")


# --------------------------------------------------------------------------- #
# THE RESOLUTION — both failure directions
# --------------------------------------------------------------------------- #
def test_same_institution_and_masked_number_is_ONE_account() -> None:
    resolved, unresolvable = resolve_accounts(
        _snap(
            [_stmt("s1", bank="Chase", num="123456789"), _stmt("s2", bank="Chase", num="123456789")]
        )
    )
    assert (
        list(resolved.values()) == [["s1", "s2"]] and unresolvable == []
    )  # grouped, in first-seen order


def test_same_masked_but_DIFFERENT_institution_is_TWO_accounts() -> None:
    # THE COLLISION TRAP: ****1234 at Chase vs ****1234 at Wells Fargo — NOT merged (the institution
    # distinguishes them). A masked-number-only match would have mis-grouped them.
    resolved, unresolvable = resolve_accounts(
        _snap([_stmt("a", bank="Chase", num="1234"), _stmt("b", bank="Wells Fargo", num="1234")])
    )
    assert len(resolved) == 2 and unresolvable == []
    assert all(len(cids) == 1 for cids in resolved.values())  # never a silent merge


def test_missing_institution_is_UNRESOLVABLE_not_grouped() -> None:
    resolved, unresolvable = resolve_accounts(_snap([_stmt("x", bank=None, num="1234")]))
    assert resolved == {} and unresolvable == ["x"]  # couldnt_check, never a guessed grouping


def test_missing_masked_number_is_UNRESOLVABLE_not_grouped() -> None:
    resolved, unresolvable = resolve_accounts(_snap([_stmt("y", bank="Chase", num=None)]))
    assert resolved == {} and unresolvable == ["y"]


def test_single_account_file_resolves_cleanly() -> None:
    resolved, unresolvable = resolve_accounts(_snap([_stmt("only", bank="Chase", num="9999")]))
    assert (
        list(resolved.values()) == [["only"]] and unresolvable == []
    )  # the common case still works


def test_non_statement_documents_are_ignored_not_unresolvable() -> None:
    # A non-bank-statement doc has no account identity — it is simply NOT an account (not a failed one).
    resolved, unresolvable = resolve_accounts(
        _snap(
            [
                _stmt("dl", bank=None, num=None, dtype="drivers_license"),
                _stmt("bs", bank="Chase", num="1"),
            ]
        )
    )
    assert list(resolved.values()) == [["bs"]] and unresolvable == []


# --------------------------------------------------------------------------- #
# THE CONSEQUENCE — a mis-group would fabricate a break; an over-split would hide one
# --------------------------------------------------------------------------- #
def test_a_partial_identity_file_does_not_mis_group_or_over_split() -> None:
    # One resolvable account (2 statements) + one unidentifiable statement. The resolvable pair groups
    # correctly (no over-split); the unidentifiable one is surfaced separately (not merged into the pair,
    # which would MIS-GROUP → a fabricated chaining break). Both dangers avoided.
    resolved, unresolvable = resolve_accounts(
        _snap(
            [
                _stmt("jan", bank="Chase", num="1234"),
                _stmt("feb", bank="Chase", num="1234"),
                _stmt(
                    "ghost", bank=None, num="1234"
                ),  # same masked, NO institution — must not merge
            ]
        )
    )
    assert list(resolved.values()) == [["jan", "feb"]]  # the real account is intact (no over-split)
    assert unresolvable == ["ghost"]  # not merged into Chase-1234 (no fabricated break)


# --------------------------------------------------------------------------- #
# THE ENUMERATOR — N accounts → N subjects; unresolvable surfaced with a reason
# --------------------------------------------------------------------------- #
def test_enumerator_yields_a_subject_per_account_with_merged_tags() -> None:
    snap = _snap(
        [_stmt("s1", bank="Chase", num="12345678"), _stmt("s2", bank="Chase", num="12345678")],
        by_subject={
            "s1": {"stmt.ending_balance": _tag("100")},
            "s2": {"stmt.beginning_balance": _tag("100")},
        },
    )
    subjects = enumerate_subjects("per_account", snap)
    assert len(subjects) == 1
    account_key, tags = subjects[0]
    assert (
        account_key == "account:chase:****5678"  # pragma: allowlist secret
        and "stmt.ending_balance" in tags
        and "stmt.beginning_balance" in tags
    )


def test_enumerator_surfaces_an_unresolvable_statement_with_the_marker() -> None:
    subjects = enumerate_subjects("per_account", _snap([_stmt("ghost", bank=None, num="1234")]))
    assert len(subjects) == 1  # surfaced, NOT dropped (absent≠empty)
    subject_id, tags = subjects[0]
    assert subject_id == "ghost" and ACCOUNT_UNRESOLVED_TAG in tags
    assert (
        "not grouped" in tags[ACCOUNT_UNRESOLVED_TAG].reasoning
    )  # names WHY → the rule couldnt_checks


def test_stable_account_key_across_runs() -> None:
    # The key is derived from the identity (LP-312 spirit) → stable, so LP-322 reconciliation matches.
    (r1, _), (r2, _) = (
        resolve_accounts(_snap([_stmt("a", bank="CHASE", num="12345678")])),
        resolve_accounts(_snap([_stmt("z", bank="chase", num="12345678")])),
    )
    assert list(r1) == list(r2) == ["account:chase:****5678"]  # pragma: allowlist secret


def test_institution_name_variance_groups_as_ONE_account() -> None:
    # Punctuation / whitespace / case variance in the bank name must NOT over-split one account (an
    # over-split fabricates or hides a chaining break). 'Chase Bank, N.A.' and 'Chase Bank NA' normalize
    # to a single key (casefold + drop_punct + collapse_ws), the LP-336-review over-split fix.
    resolved, unresolvable = resolve_accounts(
        _snap(
            [
                _stmt("jan", bank="Chase Bank, N.A.", num="12345678"),
                _stmt("feb", bank="Chase Bank NA", num="12345678"),
            ]
        )
    )
    assert list(resolved.values()) == [["jan", "feb"]] and unresolvable == []


def test_conflicting_per_statement_tag_is_dropped_not_last_wins() -> None:
    # Each statement carries its OWN ending_balance (different values). The account subject must NOT keep
    # an arbitrary last-wins value — the conflicting tag is DROPPED so a rule couldnt_checks (fail-closed).
    # A tag that AGREES across the statements (account_type) is kept.
    snap = _snap(
        [_stmt("s1", bank="Chase", num="12345678"), _stmt("s2", bank="Chase", num="12345678")],
        by_subject={
            "s1": {"stmt.ending_balance": _tag("100"), "stmt.account_type": _tag("checking")},
            "s2": {"stmt.ending_balance": _tag("250"), "stmt.account_type": _tag("checking")},
        },
    )
    ((_key, tags),) = enumerate_subjects("per_account", snap)
    assert (
        "stmt.ending_balance" not in tags
    )  # conflicting per-statement values → dropped, not 100/250
    assert tags["stmt.account_type"].value == "checking"  # agrees across statements → kept


def test_resolution_keys_identically_on_the_pre_masked_production_field_path() -> None:
    # Production builds account_number_masked via PiiField.pre_masked (an already-masked capture), NOT
    # from_raw — assert the resolution keys identically on the real path, not only the test-helper path.
    stmt = DocumentEntry(
        content_id="p",
        document_type="bank_statement",
        fields={
            "bank_name": _bank("Chase"),
            "account_number_masked": PiiField.pre_masked(
                "****5678",  # pragma: allowlist secret
                kind=PiiKind.ACCOUNT,
                source=FieldSource.EXTRACTED,
            ),
        },
    )
    resolved, unresolvable = resolve_accounts(_snap([stmt]))
    assert list(resolved) == ["account:chase:****5678"]  # pragma: allowlist secret
    assert unresolvable == []
