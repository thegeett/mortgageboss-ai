"""Documents section assembler (LP-206, ADR-243).

Reads each ACTIVE document's already-extracted facts (LP-201 confidence) and its
already-stored borrower links (LP-202) and reshapes them into the snapshot's
``documents`` section. It does NOT extract and does NOT run matching — it READS the
stored links. It touches no other section and does no MISMO↔document correlation.

For each active, current document → a :class:`DocumentEntry`:

* ``document_type`` — the document's stored slug (e.g. ``"pay_stub"``, ``"1099"``).
* ``belongs_to`` — the RESOLVED borrowers, read from ``document_borrower_links``
  (LP-202), as a tuple of ``{borrower_id, name}`` (option-2); ``None`` when no
  borrower resolved (appraisal / no-match / unprocessable). Joint documents →
  multiple refs. A link to a soft-deleted borrower is excluded **here**, by
  resolving ``borrower_id`` against ``_active_borrower_names`` — the stored rows
  are NOT soft-delete-safe on their own (``ondelete=CASCADE`` never fires on a soft
  delete, so the link survives the borrower's removal).
* ``fields`` — each extracted typed field → a ``Field`` (``source=extracted``)
  carrying LP-201's nullable confidence FAITHFULLY (null stays null — never
  fabricated). The RAW asserted name the document printed is surfaced here as
  ``asserted_name`` (distinct from ``belongs_to``'s resolved name).

## PII

Sensitive numbers are routed through ``PiiField`` (never a plain ``Field``) per an
explicit :data:`_PII_FIELDS` registry, so a raw value can't land as plaintext
``Field.value``. Two cases: a field the extractor stored **already masked**
(``account_number_masked`` / ``taxpayer_ssn_masked`` / ``id_number_masked``) →
``PiiField.pre_masked`` (canonical last-4 display, ``match_hash=None``); a field the
extractor stored **raw** ("as written" — W-2 ``employee_ssn`` / ``employer_ein``, 1099
``recipient_tin`` / ``payer_tin``) → ``PiiField.from_raw`` (masked here + a per-file
match-hash; the raw is discarded). ``social_security_wages`` / ``_tax_withheld`` are
dollar amounts, not ids, and stay ordinary fields. The institution tax ids
(``employer_ein`` / ``payer_tin``) are the employer/payer's id, not borrower PII, but
are masked anyway: a bare 9-digit tax id is exactly what the LP-209 at-rest guard flags
as a possible unmasked SSN, so masking keeps that guard strong (see the ``_PII_FIELDS``
note). The registry is drift-guarded by a test (any ``# SENSITIVE`` extractor field must
be routed here — the guard attributes the comment to its field even when ruff wraps the
field across lines).

## Absent ≠ empty

A field the extractor didn't produce (``value`` is null, or the field absent) is
omitted — distinct from a present empty string. Nothing is fabricated.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, TypedDict, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.parsing import coerce_optional_confidence
from app.models.borrower import Borrower
from app.models.document import Document
from app.models.document_borrower_link import DocumentBorrowerLink
from app.models.extraction import Extraction
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.services.borrower_name_matching import BORROWER_NAME_FIELDS
from app.verification.snapshot.content_id import (
    DOC_PREFIX,
    LIST_PREFIX,
    TXN_PREFIX,
    assign_content_ids,
    unordered_fingerprint,
)
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    ListRow,
    ScheduleCRecord,
    ScheduleEPropertyRecord,
    ScheduleERecord,
    SnapshotField,
    TransactionRecord,
)
from app.verification.snapshot.pii import PiiField, PiiKind

_EXTRACTED = FieldSource.EXTRACTED

# Document types that carry a nested transaction list (only bank statements today).
_TRANSACTION_DOC_TYPES = frozenset({"bank_statement"})
_TRANSACTIONS_KEY = "transactions"

# LP-421 — document types that carry nested tax-return schedules (only tax returns today).
_SCHEDULE_DOC_TYPES = frozenset({"tax_return"})
_SCHEDULE_C_KEY = "schedule_c"
_SCHEDULE_E_KEY = "schedule_e"

# Extraction transaction_type values → credit (money in) / debit (money out). The
# extractor's vocabulary is "deposit / withdrawal / fee / interest / transfer / ..."
# (bank_statement prompt) — open-ended, so an UNKNOWN or genuinely AMBIGUOUS type (bare
# ``transfer`` / ``ach`` / ``wire`` — could be either direction) is DELIBERATELY absent
# from both sets → :func:`_direction` returns None (unclassifiable), never a guessed
# direction. Only unambiguous types are listed.
_CREDIT_TYPES = frozenset(
    {
        "deposit",
        "credit",
        "interest",
        "refund",
        "transfer_in",
        "direct_deposit",
        "dividend",
        "ach_credit",
        "mobile_deposit",
        "reversal",
    }
)
_DEBIT_TYPES = frozenset(
    {
        "withdrawal",
        "debit",
        "fee",
        "payment",
        "transfer_out",
        "check",
        "ach_debit",
        "purchase",
        "pos",
        "atm_withdrawal",
        "service_charge",
        "wire_out",
        "bill_pay",
    }
)

# Redacted OUT of a transaction description so a surfaced description is never a raw
# account/SSN/id at rest (real descriptions carry payroll/confirmation/account ids that
# would trip the LP-209 at-rest guard). Catches a dashed SSN AND any 9+-digit identifier,
# INCLUDING accounts/cards written in space- or dash-separated groups
# ("1234 5678 9012 3456", "1234-5678-9012") that a bare ``\d{9,}`` misses. Kept: dates
# (≤8 digits — "2026-05-05"), short ids ("SAV 5683"), the sourcing signal (PAYROLL /
# TRANSFER / VENMO). See ADR-248. (Broader than the persistence guard by design — this
# scrubs adversarial free text; a shared PII-pattern module is a deferred follow-up.)
_DESC_REDACT = re.compile(r"\d(?:[\s-]?\d){8,}")
_REDACTED = "[redacted]"


def _scrub_untyped(value: Any) -> Any:
    """Scrub a Tier-3 free-extraction structure of any long identifier run (LP-463).

    The untyped section carries model-extracted free text (party names, contexts, a summary). The prompt is
    told not to quote full SSNs/account numbers, but this is the belt-and-braces backstop at the snapshot
    boundary — the SAME 9+-digit scrub (:data:`_DESC_REDACT`) the generic lists use — so a leaked identifier
    cannot land in the snapshot at rest (which ``_assert_no_raw_pii`` guards) or reach an AI reasoner. A
    masked last-4 / date / short id is kept (an honest signal); a long run becomes ``[redacted]``.

    Returns ``None`` for a falsy TOP-LEVEL input (no untyped read), so a typed document's entry stays
    ``untyped_extraction=None``. The empty-check is top-level ONLY: the recursion (:func:`_scrub_value`)
    preserves falsy LEAVES (``0`` / ``False`` / ``""`` / ``[]``) — collapsing those to ``None`` would silently
    distort the very facts this section surfaces.
    """
    if not value:
        return None
    return _scrub_value(value)


def _scrub_value(value: Any) -> Any:
    """Recurse a scrubbed structure, redacting long identifier runs in strings; falsy leaves are KEPT."""
    if isinstance(value, str):
        return _DESC_REDACT.sub(_REDACTED, value)
    if isinstance(value, dict):
        return {k: _scrub_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_value(v) for v in value]
    return value  # numbers / bools / None — cannot carry an identifier string


# The catch-all list key inside extracted_data (not a typed field).
_CATCH_ALL_KEY = "additional_sections"

# Extracted typed fields carrying borrower PII, and how to route each:
#   pre_masked=True  → the extractor already masked the value (display last-4, no hash);
#   pre_masked=False → the extractor stored it RAW ("as written") → mask + a per-file
#                      match-hash here so the raw never lands in the snapshot.
# Explicit (not pattern-matched) so a dollar amount like ``social_security_wages`` is
# never caught. Guarded against drift by test_documents_section: any extractor field
# annotated SENSITIVE must appear here. Institution tax ids (``employer_ein`` /
# ``payer_tin``) ARE routed too: though they are the employer/payer's id (not borrower
# PII), a 9-digit tax id is exactly what the LP-209 at-rest guard treats as a possible
# unmasked SSN — masking them keeps the strong guard intact rather than exempting them.
_PII_FIELDS: dict[str, tuple[PiiKind, bool]] = {
    "account_number_masked": (PiiKind.ACCOUNT, True),  # bank / investment / retirement
    "id_number_masked": (PiiKind.ACCOUNT, True),  # driver's-license number
    "taxpayer_ssn_masked": (PiiKind.SSN, True),  # tax return
    "employee_ssn": (PiiKind.SSN, False),  # W-2 — stored RAW ("SSN as written")
    "employee_ssn_masked": (
        PiiKind.SSN,
        True,
    ),  # LP-446 — pay stub, pre-masked (distinct from W-2's raw)
    # LP-446 diffs — typed-core PII of the 15 remaining diff types (dedup vs the existing registry).
    "spouse_ssn_masked": (PiiKind.SSN, True),  # tax_return
    "employee_number": (PiiKind.ACCOUNT, False),  # voe — stored RAW, masked + hashed
    "owner_account_number_masked": (PiiKind.ACCOUNT, True),  # hoa_statement
    "gift_source_account_last4": (PiiKind.ACCOUNT, True),  # gift_letter
    "recipient_or_escrow_account_last4": (PiiKind.ACCOUNT, True),  # gift_letter
    "account_number": (PiiKind.ACCOUNT, False),  # form_1099 — stored RAW
    "recipient_tin": (PiiKind.SSN, False),  # 1099 recipient — stored RAW ("TIN/SSN as written")
    "employer_ein": (PiiKind.ACCOUNT, False),  # W-2 employer tax id — masked ****NNNN
    "payer_tin": (PiiKind.ACCOUNT, False),  # 1099 payer tax id — masked ****NNNN
    # LP-509-C1 — the same reasoning as the two above, applied to the two W-2 fields it had missed.
    # `state_employer_id` is Box 15's state-issued employer tax id: literally the same kind of value
    # as `employer_ein`, routinely 9+ digits, and left unrouted. `control_number` is Box d, an
    # employer-internal payroll id, also commonly a long digit run. NEITHER IS BORROWER PII and
    # neither is read by any rule (both carry `"rules": []` in `schema_specs/008-w2.json`) — they are
    # routed for exactly the reason stated above for the tax ids: a 9+ digit run is what the LP-209
    # at-rest guard treats as a possible unmasked SSN, and masking the value keeps that guard strong
    # instead of punching an exemption through it. Unrouted, either one refuses the ENTIRE snapshot
    # persist for any file carrying a W-2 whose box is populated — losing every tag value on the
    # file, not just the field.
    # The same sweep found two more of the identical class, both also read by no rule:
    "state_employer_id": (PiiKind.ACCOUNT, False),  # W-2 Box 15 state tax id — masked ****NNNN
    "control_number": (PiiKind.ACCOUNT, False),  # W-2 Box d payroll control id — masked ****NNNN
    "lender_tin": (PiiKind.ACCOUNT, False),  # form_1098 lender tax id — masked ****NNNN
    "tax_bill_or_account_number": (PiiKind.ACCOUNT, False),  # property_tax_bill — masked ****NNNN
    # bug-001 — the SAME class again, found the same way: a real file lost its snapshot on every run
    # and the refusal named the field. Neither is borrower PII and neither is read by any rule
    # (`"rules":[]` in their schema specs); they are routed for the reason stated above, that a 9+
    # digit run is what the at-rest guard treats as a possible unmasked SSN.
    #
    "project_or_job_number": (PiiKind.ACCOUNT, False),  # survey — surveyor's job reference
    # LP-443 step 7 — typed-core PII of the first wired batch. NOTE (reported gap): only TOP-LEVEL
    # typed-core fields are routed here; PII inside a captured LIST row (e.g. a tradeline's
    # account_number_masked) is NOT routed — it relies on the prompt masking it, so list-row PII
    # masking is a follow-up (a per-list redact/route step), out of scope for the capture bridge.
    "borrower_ssn": (PiiKind.SSN, False),  # credit_report — stored RAW, masked + hashed here
    "co_borrower_ssn": (PiiKind.SSN, False),  # credit_report — stored RAW
    "social_security_number_masked": (PiiKind.SSN, True),  # certificate_of_eligibility — pre-masked
    "loan_number_masked": (PiiKind.ACCOUNT, True),  # verification_of_mortgage — pre-masked
    # LP-570 — THIS ENTRY IS RIGHT FOR ONE DOCUMENT TYPE AND WRONG FOR ANOTHER, and the registry
    # is keyed by field NAME alone so it cannot tell them apart. Four types declare
    # `policy_number`, and their prompts disagree: flood_insurance_policy says "Mask the policy
    # number" (pre-masked, correct), while homeowners_insurance asks for "the policy number" plain
    # — so a RAW number is routed through `PiiField.pre_masked`, which truncates it to last-4 with
    # match_hash=None. That is both a lossy display AND a non-joinable key: exactly the LP-461 bug
    # described on `loan_number` below. Left as-is deliberately: correcting it means doc-type-aware
    # routing, and flipping the flag globally would break the flood case in the other direction.
    "policy_number": (PiiKind.ACCOUNT, True),
    # LP-565 — an Assessor's Parcel Number is identifier-shaped (9+ digits) and was passing through
    # RAW, which is one of the values refusing every snapshot write on staging: 22 completed runs,
    # 0 persisted. It is a public-record identifier rather than borrower PII, but the at-rest guard
    # cannot tell one digit run from another and refuses the whole document — and the guard's own
    # message says to route the field here rather than relax it.
    "parcel_or_apn": (PiiKind.ACCOUNT, False),  # property_tax_bill — stored RAW
    # LP-443 Phase C — typed-core PII across the remaining generated extractors (all account/
    # SSN/TIN-like; no name conflicts). List-row PII still relies on prompt masking (reported gap).
    "account_case_or_reference_number": (PiiKind.ACCOUNT, False),
    "account_number_last4": (PiiKind.ACCOUNT, True),
    "account_or_case_number_masked": (PiiKind.ACCOUNT, True),
    "account_or_reference_number_masked": (PiiKind.ACCOUNT, True),
    "borrower_ssn_or_itin": (PiiKind.SSN, False),
    "borrower_ssn_or_itin_2": (PiiKind.SSN, False),
    "card_number_last4_or_token": (PiiKind.ACCOUNT, True),
    "card_or_account_last4": (PiiKind.ACCOUNT, True),
    "case_provider_or_account_number_masked": (PiiKind.ACCOUNT, True),
    "certificate_or_state_file_number": (PiiKind.ACCOUNT, False),
    "check_number_or_transaction_reference": (PiiKind.ACCOUNT, False),
    "claim_number_masked": (PiiKind.ACCOUNT, True),
    "claim_or_account_number_masked": (PiiKind.ACCOUNT, True),
    "deposit_account_last4": (PiiKind.ACCOUNT, True),
    "direct_deposit_account_last4": (PiiKind.ACCOUNT, True),
    # LP-461 review — the DL document discriminator is a unique per-card security identifier captured RAW
    # (not prompt-masked); mask + hash it (from_raw) like the sibling document_number rather than persist it plain.
    "document_discriminator": (PiiKind.ACCOUNT, False),
    # LP-472 review — the shared identity_document captures the primary document number (passport #, EAD /
    # green-card 'Card #', or the ID number) VERBATIM, so from_raw masks the display AND computes a per-file
    # match_hash; pre_masked=True would discard the raw to last-4 with match_hash=None. (The old per-type EAD /
    # PRC names document_or_card_number / card_number were consolidated onto this and removed from the registry.)
    "document_number": (PiiKind.ACCOUNT, False),
    "drawer_account_last4": (PiiKind.ACCOUNT, True),
    "ein": (PiiKind.ACCOUNT, False),
    "ein_masked": (PiiKind.ACCOUNT, True),
    "ein_or_state_entity_number_masked": (PiiKind.ACCOUNT, True),
    "entity_ein": (PiiKind.ACCOUNT, False),
    "entity_ein_masked": (PiiKind.ACCOUNT, True),
    "expiration_month_year": (PiiKind.ACCOUNT, False),
    "i94_admission_number": (PiiKind.ACCOUNT, True),
    # LP-461 review — stored RAW (every extractor's prompt captures the loan number verbatim; the
    # pre-masked variant is the separate "loan_number_masked" above). from_raw masks the DISPLAY and
    # computes a per-file match_hash, so it stays a usable cross-document join key; pre_masked=True would
    # discard the raw to last-4 with match_hash=None (non-joinable).
    "loan_number": (PiiKind.ACCOUNT, False),
    "local_file_or_registration_number": (PiiKind.ACCOUNT, False),
    "partner_or_shareholder_tin": (PiiKind.SSN, False),
    "passport_number": (PiiKind.ACCOUNT, True),
    "payer_account_last4": (PiiKind.ACCOUNT, True),
    "plan_claim_or_account_last4": (PiiKind.ACCOUNT, True),
    "plan_or_claim_number_masked": (PiiKind.ACCOUNT, True),
    "policy_number_masked": (PiiKind.ACCOUNT, True),
    # LP-465 review — stored RAW (appraisal_payment / work_visa_ead_card / uscis_notice_of_action all
    # capture it VERBATIM; the uscis prompt says so explicitly), so from_raw masks the display AND computes a
    # per-file match_hash — consistent with the sibling beneficiary_a_number / i94_number. pre_masked=True
    # would discard the raw to last-4 with match_hash=None (the LP-461 loan_number bug).
    "receipt_number": (PiiKind.ACCOUNT, False),
    "recipient_account_last4": (PiiKind.ACCOUNT, True),
    "recipient_tin_masked": (PiiKind.ACCOUNT, True),
    "shareholder_or_partner_tin_masked": (PiiKind.SSN, True),
    "social_security_number": (PiiKind.SSN, False),
    "social_security_number_2": (PiiKind.SSN, False),
    "source_account_last4": (PiiKind.ACCOUNT, True),
    "spouse_tin": (PiiKind.SSN, False),
    "spouse_tin_masked": (PiiKind.ACCOUNT, True),
    "ssn_or_itin_last4": (PiiKind.SSN, True),
    "ssn_or_itin_last4_2": (PiiKind.SSN, True),
    "tax_identification_number_masked": (PiiKind.ACCOUNT, True),
    "taxpayer_tin": (PiiKind.SSN, False),
    "taxpayer_tin_masked": (PiiKind.ACCOUNT, True),
    # LP-472 review — the shared identity_document captures the full A-Number / USCIS# VERBATIM, so from_raw
    # masks the display + computes a per-file match_hash (consistent with beneficiary_a_number; the future ID-8
    # cross-document identity match needs the hash). pre_masked=True gave last-4 with match_hash=None. The old
    # per-type name uscis_number_or_a_number (was from_raw) was consolidated onto this and removed.
    "uscis_or_a_number": (PiiKind.ACCOUNT, False),
    "visa_number": (PiiKind.ACCOUNT, True),
    "wire_ach_trace_number": (PiiKind.ACCOUNT, False),
    "wire_or_remittance_instructions": (PiiKind.ACCOUNT, False),
    # LP-465 — uscis_notice_of_action. Both carry 9+-digit runs that would otherwise trip the LP-209
    # at-rest guard; from_raw masks display to last-4 + a per-file match-hash (so the A-number can
    # correlate to an EAD card's). ``receipt_number`` is ALREADY routed above (existing entry); the
    # ``i94_number`` route is an addition found while reading 065 — the ticket flagged only the A-number.
    # ``beneficiary_name`` / ``beneficiary_date_of_birth`` stay UNMASKED (ID-8 matches on them).
    "beneficiary_a_number": (PiiKind.ACCOUNT, False),
    "i94_number": (PiiKind.ACCOUNT, False),
    # LP-466 — wire_instructions. A 9-digit ABA routing number is a bare contiguous run that trips the
    # LP-209 at-rest guard → mask + per-file hash (from_raw). ``account_number`` is already routed above
    # (form_1099, reused).
    "aba_routing_number": (PiiKind.ACCOUNT, False),
    # LP-466/467 review — whole-value NUMERIC identifiers that can arrive as a bare 9+-digit run: an
    # UNFORMATTED phone (5551234567) or a pure-numeric invoice/service number. Left plain, either would trip
    # the at-rest guard (``_LONG_DIGITS``) and REFUSE the whole loan file's snapshot. from_raw masks the
    # snapshot value (last-4 + per-file hash); the raw value stays in the document's extraction for the
    # processor's document view — so the wire callback number is still readable there, just not at rest.
    "verification_phone": (PiiKind.ACCOUNT, False),
    "invoice_number": (PiiKind.ACCOUNT, False),
    # LP-469 — form_1098. The borrower TIN is PRE-MASKED on the form (last-4 only, e.g. '*****7007') →
    # pre_masked display, no hash. ``account_number`` reuses the entry above (from_raw).
    "borrower_tin_masked": (PiiKind.SSN, True),
    # LP-469 review — ``lender_phone`` gets the same from_raw treatment as verification_phone: an UNFORMATTED
    # servicer phone (bare 9+-digit run) would otherwise trip the at-rest guard and refuse the whole loan
    # file's snapshot. Masked in the snapshot; the raw stays in the document extraction. ``lender_tin`` is
    # deliberately NOT registered — it is a business EIN meant to stay VISIBLE (from_raw would hide it, and a
    # scrub would over-redact the hyphenated form since _DESC_REDACT allows the separators the at-rest guard
    # does not); an IRS 1098 always hyphenates the EIN (26-1193089), so its residual is effectively zero.
    "lender_phone": (PiiKind.ACCOUNT, False),
}

# Free-text typed-core fields that are NOT whole-value PII (so not in ``_PII_FIELDS`` — masking the
# whole value would destroy the signal, e.g. "Requires Investigation") but that a misbehaving model
# could embed a raw SSN/account run into. Their value is passed through the same 9+-digit scrub the
# list-row backstop uses (``_DESC_REDACT``) at the snapshot boundary: a leaked 9-digit SSN becomes
# ``[redacted]`` while the alert wording survives (LP-445 review — the credit_report free-text alert
# fields sit beside a MASKED ``borrower_ssn``; without this they would store unmasked). Keyed by
# document_type; keep in sync with the spec's promoted free-text fields.
_SCRUB_FREE_TEXT_FIELDS: dict[str, frozenset[str]] = {
    "credit_report": frozenset({"ssn_alert_status", "address_usage_alert"}),
    # LP-566 — a STATUS and a YEAR carrying a 9+-digit run. Both are extraction defects rather than
    # PII (a policy status reads "Active"; a tax year reads "2025"), so `_PII_FIELDS` would be the
    # wrong home: masking the whole value to ****9012 destroys the signal AND hides the defect. This
    # scrub keeps the wording and redacts only the leaked run, which is what these fields need.
    # LP-569 — CLOSE THE CLASS, NOT THE INSTANCE. `policy_status` is the same free-text field on
    # FOUR policy types and `tax_year` the same year field on NINE document types; an extraction
    # defect on any one of them refuses the whole loan file's snapshot. Registering only the two
    # observed leaking on LF-WCHG would have left eleven loaded guns. `test_every_declaring_doc_type_is_registered`
    # fails if a new extractor declares either field without appearing here.
    "homeowners_insurance": frozenset({"policy_status"}),
    "flood_insurance_policy": frozenset({"policy_status"}),
    "life_insurance_policy": frozenset({"policy_status"}),
    "homeowner_s_insurance_quote": frozenset({"policy_status"}),
    "property_tax_bill": frozenset({"tax_year"}),
    "property_tax_bill_non_subject": frozenset({"tax_year"}),
    "form_1098": frozenset({"tax_year"}),
    "1099": frozenset({"tax_year"}),
    "transcripts_of_1099": frozenset({"tax_year"}),
    "k1_statement": frozenset({"tax_year"}),
    "k_1_shareholder_profit_and_loss_transcripts": frozenset({"tax_year"}),
    "tax_return": frozenset({"tax_year"}),
    "w2": frozenset({"tax_year"}),
    # LP-466 — a wire memo instructs "reference file/loan number …"; a bare ≥9-digit file number embedded
    # there would trip the at-rest guard. Scrub the 9+-digit run (the memo wording survives) as a backstop.
    "wire_instructions": frozenset({"reference_or_memo"}),
    # LP-467 — the ACORD 101 remarks print a bare loan number ("Loan: 4256229242") inside these free-text
    # fields, invisible to the field-name PII registry; an invoice's service_description could likewise embed
    # one. Same shape as the wire-memo scrub — redact the 9+-digit run, keep the wording.
    "certificate_of_liability_insurance": frozenset(
        {"description_of_operations", "project_or_property_reference"}
    ),
    "service_invoice": frozenset({"service_description"}),
}


def _scalar(value: Any) -> str | int | float | bool | None:
    """A JSON scalar, or None to skip a nested (list/dict) extracted value."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, str)):
        return value
    return None  # nested structures (e.g. bank-statement transactions) not surfaced here


def build_document_fields(
    extracted: dict[str, Any], document_type: str | None, *, loan_file_id: UUID
) -> dict[str, SnapshotField]:
    """Reshape one document's ``extracted_data`` into snapshot fields (pure).

    A field registered in :data:`_PII_FIELDS` is routed through ``PiiField`` — never a
    plain ``Field`` — so a raw SSN/TIN cannot land as plaintext ``Field.value``.
    ``loan_file_id`` salts the per-file match-hash for raw PII.
    """
    fields: dict[str, SnapshotField] = {}
    for key, entry in extracted.items():
        if key == _CATCH_ALL_KEY or not isinstance(entry, dict) or "value" not in entry:
            continue
        value = entry.get("value")
        if value is None:  # absent — omit
            continue
        confidence = coerce_optional_confidence(entry.get("confidence"))
        routing = _PII_FIELDS.get(key)
        if routing is not None:
            kind, pre_masked = routing
            if pre_masked:
                fields[key] = PiiField.pre_masked(
                    value, kind=kind, source=_EXTRACTED, confidence=confidence
                )
            else:  # raw value → mask + per-file match-hash; raw is discarded
                fields[key] = PiiField.from_raw(
                    value,
                    kind=kind,
                    loan_file_id=loan_file_id,
                    source=_EXTRACTED,
                    confidence=confidence,
                )
            continue
        scalar = _scalar(value)
        if scalar is None:  # nested/non-scalar — not surfaced here
            continue
        if key in _SCRUB_FREE_TEXT_FIELDS.get(document_type or "", frozenset()):
            # LP-569 — scrub the value's TEXT FORM, not just a `str` instance. The gate used to be
            # `isinstance(scalar, str)`, which made this a no-op for the field it was added for:
            # `property_tax_bill.tax_year` is `TypedField[int]` parsed with `coerce_int`, so a leaked
            # run arrives as the INT 202520261234 and walked straight past. The whole loan file then
            # lost its snapshot at the at-rest guard — the exact failure LP-566 set out to prevent,
            # surfacing further from its cause.
            #
            # Only REPLACE when the scrub actually changed something, so a clean numeric keeps
            # its declared type — tax_year 2025 stays the int 2025, while a 9+-digit run becomes
            # the redacted string. Losing the int on a value that was never a year is the correct
            # trade. (Do not open a line with "# type:" here: mypy reads that as a PEP 484 type
            # comment and fails the file with a syntax error, which is how this one was found.)
            as_text = scalar if isinstance(scalar, str) else str(scalar)
            redacted = _DESC_REDACT.sub(_REDACTED, as_text)  # embedded SSN/account run (LP-445)
            if redacted != as_text:
                scalar = redacted
        fields[key] = Field.present(scalar, source=_EXTRACTED, confidence=confidence)

    # ``asserted_name`` — a stable, doc-type-agnostic alias of the RAW borrower-name
    # field the document printed. Point it at the SAME already-built field (never a
    # re-parsed second copy that could normalize differently); don't clobber a real
    # extracted ``asserted_name``.
    if "asserted_name" not in fields:
        for name_key in BORROWER_NAME_FIELDS.get(document_type or "", ()):
            if name_key in fields:
                fields["asserted_name"] = fields[name_key]
                break
    return fields


def _direction(txn: dict[str, Any]) -> str | None:
    """credit (money in) / debit (money out) from transaction_type; None if unclassifiable.

    Classification is by ``transaction_type`` ONLY. The extractor stores ``amount``
    positive ("use transaction_type for direction", bank_statement prompt), so a positive
    amount carries NO direction signal — inferring "credit" from it would forge a deposit
    on every unlabelled withdrawal (a false AS-1 large-deposit). An unknown/ambiguous type
    therefore returns ``None`` (→ an absent ``direction`` Field), never a guess. Only an
    explicitly NEGATIVE / parenthesized amount (a signed export the prompt doesn't ask for,
    handled defensively) is read as a debit.
    """
    ttype = txn.get("transaction_type")
    if isinstance(ttype, str):
        key = ttype.strip().lower().replace(" ", "_")
        if key in _CREDIT_TYPES:
            return "credit"
        if key in _DEBIT_TYPES:
            return "debit"
    amount = txn.get("amount")
    if isinstance(amount, (int, float)) and amount < 0:
        return "debit"
    if isinstance(amount, str):
        stripped = amount.strip().replace(",", "").replace("$", "").replace(" ", "")
        if stripped.startswith("-") or (stripped.startswith("(") and stripped.endswith(")")):
            return "debit"
    return None  # unclassifiable — absent direction, never a fabricated "credit"


def _redact_description(value: Any) -> str | None:
    """The description with any 9+-digit identifier (bare or space/dash-grouped) redacted."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return _DESC_REDACT.sub(_REDACTED, text) if text else None


def _txn_field(value: Any, *, source: FieldSource = _EXTRACTED) -> Field:
    """A transaction attribute as a Field (no confidence), absent when null.

    ``source`` defaults to ``extracted`` (the value was read from the document); pass
    ``FieldSource.DERIVED`` for a COMPUTED attribute (``direction``) so its provenance is
    honest — a derived value is never tagged as if the extractor read it verbatim.
    """
    if value is None:
        return Field.missing()
    scalar = _scalar(value)  # date/amount/etc. already stringified by the extractor's JSON dump
    if scalar is None:
        return Field.missing()
    return Field.present(scalar, source=source)


def _txn_pii_field(value: Any, name: str, *, loan_file_id: UUID) -> SnapshotField:
    """A transaction attribute declared sensitive → a masked ``PiiField``, absent when null (bug-010).

    Mirrors :func:`_txn_field` for everything else — absent stays absent, so a row without the value
    is unchanged — and routes a present one through ``PiiField.from_raw``, which masks + hashes and
    discards the raw. ``_scalar`` first, because the extractor's JSON dump may hand back a number.
    """
    if value is None:
        return Field.missing()
    scalar = _scalar(value)
    if scalar is None:
        return Field.missing()
    kind, pre_masked = _TXN_PII_FIELDS[name]
    if pre_masked:
        return PiiField.pre_masked(scalar, kind=kind, source=_EXTRACTED)
    return PiiField.from_raw(scalar, kind=kind, loan_file_id=loan_file_id, source=_EXTRACTED)


# bug-010 — THE SENSITIVE FIELDS OF A TRANSACTION ROW, declared ONCE and read by both paths that
# build one. The same extracted rows populate the legacy ``entry.transactions`` (feeds AS-1) and the
# generic ``entry.lists["transactions"]``, so a field masked on one and raw on the other still
# reaches the at-rest guard raw — which is how this shipped: the refusals name the generic path and
# the legacy path carried the same value beside it.
#
# NOT in ``_PII_FIELDS``, and the reason is simpler than the first write-up claimed. That registry is
# read at ONE site — ``build_document_fields``, over a document's FLAT keys — so a name added to it
# would not route here at all: not in a list row, not in a transaction row, no effect on either. The
# first cut said a global entry "would route it in every list too, moving the row_ids of tradelines",
# which is false in both halves and was the stated justification for building this second registry.
# The true justification is the reverse: ``_PII_FIELDS`` CANNOT reach a row, which is exactly the gap
# LP-443 recorded and deferred.
#
# Declaring per list is still right, for a reason that survives: masking changes a field's serialized
# shape, which moves the ``row_id`` of every row in that list, and which lists can afford that is a
# per-list fact (see ``ListSpec.pii``).
_TXN_PII_FIELDS: dict[str, tuple[PiiKind, bool]] = {
    # The ACH originator ("PPD ID: 4760039224") — a bare 10-digit run, indistinguishable to a
    # shape-based guard from an account number, and it refused every staging snapshot for a week
    # (36 rows, none newer than 2026-08-25). Masking loses nothing it was captured for: bug-001
    # wanted it to tell two debts owed to ONE institution apart, and ``match_hash`` is per-file
    # salted, so equal originators still compare equal within a file while the raw never lands.
    # `False` = the extractor stores it RAW, so it is masked + hashed here rather than trusted as
    # already-masked. The same (kind, pre_masked) shape `_PII_FIELDS` carries, because the list-row
    # PII LP-443 deferred is mostly the PRE-masked kind (`account_number_masked` and friends) and a
    # route that could not express it would not be the route that gap needs.
    "originator_id": (PiiKind.ACCOUNT, False),
}


class TransactionFieldSet(TypedDict):
    """The Fields of one transaction row, keyed by their ``TransactionRecord`` attribute.

    bug-010 — A ``TypedDict``, NOT ``dict[str, SnapshotField]``, so the ONE masked key is declared at
    the type level rather than described in a comment. Under the loose mapping every value read as
    the union, which defeated the ``TransactionRecord(**fs)`` splat and needed an ``ignore`` to
    suppress — hiding, rather than expressing, the fact that exactly one attribute widened.
    """

    date: Field
    amount: Field
    direction: Field
    description: Field
    originator_id: SnapshotField


def transaction_field_sets(
    extracted: dict[str, Any], document_type: str | None, *, loan_file_id: UUID
) -> list[TransactionFieldSet] | None:
    """The bank-statement transaction rows reshaped to Fields (LP-302a), or ``None``.

    ``None`` = absent (a non-bank document, or a statement whose extraction carried no
    transaction list); an empty list = a statement present with zero transactions
    (present-empty). Pure read + reshape; no correlation. ``description`` is redacted so a
    raw account/id never lands at rest.

    ``loan_file_id`` salts the per-file match-hash for a row field declared in
    :data:`_TXN_PII_FIELDS` (bug-010). Required, not optional: a fallback would silently put the raw
    value back at rest on whichever caller forgot to pass it.

    This is the reshape half of transaction building. The stable per-row ``content_id``
    (LP-312) is applied by :func:`build_transactions` once the parent document's id is
    known — a transaction id is scoped under its document, so it cannot be assigned here.
    """
    if document_type not in _TRANSACTION_DOC_TYPES:
        return None
    raw = extracted.get(_TRANSACTIONS_KEY)
    if not isinstance(raw, list):
        return None  # statement present but no transaction list → absent, not empty
    # The statement's masked account is NOT copied onto every row — it lives once on the
    # DocumentEntry's ``fields["account_number_masked"]`` (built by build_document_fields).
    field_sets: list[TransactionFieldSet] = []
    for txn in raw:
        if not isinstance(txn, dict):
            continue
        field_sets.append(
            {
                "date": _txn_field(txn.get("date")),
                "amount": _txn_field(txn.get("amount")),
                "direction": _txn_field(_direction(txn), source=FieldSource.DERIVED),
                "description": _txn_field(_redact_description(txn.get("description"))),
                # bug-001 — the ACH originator, so two debts owed to ONE institution can be told
                # apart. A payee name cannot: a Chase card and a Chase auto loan are both "Chase",
                # and grouping on the name alone would merge them into one obligation and understate
                # the DTI. Not redacted — `_redact_description` scrubs free text, and this is a
                # company id printed beside the payee, the same class as the tax ids routed through
                # `_PII_FIELDS` rather than dropped.
                "originator_id": _txn_pii_field(
                    txn.get("originator_id"), "originator_id", loan_file_id=loan_file_id
                ),
            }
        )
    return field_sets


#: Fields that do NOT take part in a transaction's identity (bug-001).
#:
#: `originator_id` describes WHO the counterparty is, not WHICH ROW this is: within one statement,
#: date + amount + direction + description already separate every line, and two rows identical in
#: those four but differing in originator do not occur. Its value is GROUPING across statements.
#:
#: Excluded deliberately, because the content id is a FINDING'S IDENTITY. Folding a new field into it
#: re-keys every per-deposit finding on every file — they retire as `no_longer_applies` and mint
#: again, stranding any sign-off a processor had made on the old copy. That happened once already in
#: this ticket, when the borrower re-link changed six documents' ids and doubled the finding count on
#: a real file. A field that adds nothing to WHICH ROW THIS IS must not cost that.
_IDENTITY_EXCLUDED_TXN_FIELDS = frozenset({"originator_id"})


def _txn_content(field_set: TransactionFieldSet) -> dict[str, Any]:
    """The content a transaction's id is derived from, JSON-canonical.

    See :data:`_IDENTITY_EXCLUDED_TXN_FIELDS` for what is deliberately left out and why.
    """
    # bug-010 — the cast is a mypy limitation, not a claim. `.items()` on a TypedDict is typed
    # `ItemsView[str, object]`, because a TypedDict's value types are per-key; every value here is a
    # `SnapshotField` by that same declaration. Kept as a LOOP over
    # `_IDENTITY_EXCLUDED_TXN_FIELDS` rather than four hardcoded keys, so the exclusion stays
    # load-bearing — spelling the identity out inline would leave that constant, its comment and its
    # test asserting something the code no longer reads.
    fields = cast("Mapping[str, SnapshotField]", field_set)
    return {
        name: fld.model_dump(mode="json")
        for name, fld in fields.items()
        if name not in _IDENTITY_EXCLUDED_TXN_FIELDS
    }


def build_transactions(
    field_sets: list[TransactionFieldSet] | None,
    *,
    document_content_id: str,
    txn_contents: list[dict[str, Any]] | None = None,
) -> tuple[TransactionRecord, ...] | None:
    """Final :class:`TransactionRecord`\\s with stable content_ids, or ``None`` (absent).

    Each row's ``content_id`` is derived from the parent document's id + the row's own
    content, with a duplicate tiebreak (:func:`assign_content_ids`), so identical deposits
    in one statement still get distinct ids and no transaction id collides across documents.

    ``txn_contents`` (optional) is the ``_txn_content(fs)`` list the caller may have already
    computed for the document's transactions-fingerprint — passing it avoids serializing each
    row's Fields a second time. When omitted (external callers/tests) it is computed here.
    """
    if field_sets is None:
        return None
    contents = txn_contents if txn_contents is not None else [_txn_content(fs) for fs in field_sets]
    bases = [{"doc": document_content_id, **content} for content in contents]
    ids = assign_content_ids(TXN_PREFIX, bases)
    return tuple(
        TransactionRecord(content_id=cid, **fs) for cid, fs in zip(ids, field_sets, strict=True)
    )


# --------------------------------------------------------------------------- #
# LP-421 — tax-return Schedule C / Schedule E surfacing (the ADR-061 typed path).
# The extractor produces these as TYPED CORE, but build_document_fields drops them (a
# nested structure _scalar can't flatten). These reshape the stored extraction's typed
# schedule sub-structures into the snapshot's frozen record models — same coercion as the
# flat core (a {value, source, confidence} entry → a Field), so a producer can read the
# self-employment / rental signal FROM THE SNAPSHOT. Absent≠empty: nothing read → None
# (never a fabricated empty record). No content_id: a schedule is document-level, not a
# rule-enumerated subject (unlike a transaction), so it needs no id / fingerprint — which is
# also why _document_base is left untouched and every content_id stays byte-identical.
# --------------------------------------------------------------------------- #
def _typed_field(entry: Any) -> Field:
    """One extraction TypedField (``{value, source, confidence}``) → a snapshot ``Field``.

    Mirrors ``build_document_fields``' non-PII branch: an absent/None/uncoercible value → an
    absent ``Field`` (source/page dropped exactly as the flat core drops it, keeping only
    ``FieldSource.EXTRACTED``); a present scalar → a ``Field`` carrying the model's nullable
    per-field confidence FAITHFULLY. A schedule field is never PII (business name / amounts),
    so no ``PiiField`` routing is needed.
    """
    if not isinstance(entry, dict):
        return Field.missing()
    scalar = _scalar(entry.get("value"))
    if scalar is None:
        return Field.missing()
    return Field.present(
        scalar, source=_EXTRACTED, confidence=coerce_optional_confidence(entry.get("confidence"))
    )


def build_schedule_c(
    extracted: dict[str, Any], document_type: str | None
) -> tuple[ScheduleCRecord, ...] | None:
    """The tax return's Schedule C rows reshaped to :class:`ScheduleCRecord`\\s, or ``None``.

    ``None`` = absent (not a tax return, no ``schedule_c`` list, or every entry empty) — the
    self-employment signal is simply not present; NEVER a fabricated empty list. A non-empty
    tuple otherwise. A fully-empty entry is dropped (mirrors the extractor's own
    ``_parse_schedule_list`` — no hallucinated schedule)."""
    if document_type not in _SCHEDULE_DOC_TYPES:
        return None
    raw = extracted.get(_SCHEDULE_C_KEY)
    if not isinstance(raw, list):
        return None
    records: list[ScheduleCRecord] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        rec = ScheduleCRecord(
            business_name=_typed_field(entry.get("business_name")),
            gross_receipts=_typed_field(entry.get("gross_receipts")),
            total_expenses=_typed_field(entry.get("total_expenses")),
            net_profit=_typed_field(entry.get("net_profit")),
        )
        if not _all_absent(
            rec.business_name, rec.gross_receipts, rec.total_expenses, rec.net_profit
        ):
            records.append(rec)
    return tuple(records) or None  # empty → absent (None), never a fabricated empty tuple


def build_schedule_e(
    extracted: dict[str, Any], document_type: str | None
) -> ScheduleERecord | None:
    """The tax return's Schedule E reshaped to a :class:`ScheduleERecord`, or ``None``.

    The two-level shape: a ``properties`` tuple + scalar totals. ``None`` = absent (not a tax
    return, no ``schedule_e``, or nothing read) — NEVER a fabricated empty record. A present
    Schedule E with no per-property detail keeps ``properties=()`` (empty, distinct from the
    whole schedule being absent). A fully-empty property is dropped."""
    if document_type not in _SCHEDULE_DOC_TYPES:
        return None
    raw = extracted.get(_SCHEDULE_E_KEY)
    if not isinstance(raw, dict):
        return None
    properties: list[ScheduleEPropertyRecord] = []
    raw_props = raw.get("properties")
    if isinstance(raw_props, list):
        for prop in raw_props:
            if not isinstance(prop, dict):
                continue
            rec = ScheduleEPropertyRecord(
                address=_typed_field(prop.get("address")),
                rents_received=_typed_field(prop.get("rents_received")),
                total_expenses=_typed_field(prop.get("total_expenses")),
                net_income=_typed_field(prop.get("net_income")),
                fair_rental_days=_typed_field(prop.get("fair_rental_days")),  # bug-012
            )
            if not _all_absent(
                rec.address,
                rec.rents_received,
                rec.total_expenses,
                rec.net_income,
                rec.fair_rental_days,
            ):
                properties.append(rec)
    total = _typed_field(raw.get("total_net_rental_income"))
    depreciation = _typed_field(raw.get("depreciation"))
    if not properties and total.absent and depreciation.absent:
        return None  # nothing read anywhere → absent, not a fabricated empty record
    return ScheduleERecord(
        properties=tuple(properties),
        total_net_rental_income=total,
        depreciation=depreciation,
    )


def _all_absent(*fields: Field) -> bool:
    return all(f.absent for f in fields)


# --------------------------------------------------------------------------- #
# LP-437 — the GENERIC nested-list mechanism (one build for all 66 lists).
#
# The bespoke path (transactions / schedule_c / schedule_e) is a record class + a
# DocumentEntry attribute + a build_* reshaper PER list. This replaces that, for NEW
# lists only, with ONE converter driven by a per-document-type ListSpec: each row's
# fields are read with the SAME _typed_field the schedules use (the extractor already
# coerced them at extraction time), then three DECLARABLE helpers apply — redact /
# derived / stable_row_id. The three legacy attributes are untouched (live AS-1/IN-12/IN-13).
#
# The registry is EMPTY today: LP-438 (the generator + _FORMAT.md) emits the real
# ListSpecs. With no specs, build_list_rows returns {} for every document, so every
# DocumentEntry gets lists={} (present-empty) — additive, no rule/tag/extractor touched.
# --------------------------------------------------------------------------- #

_DERIVED = FieldSource.DERIVED


@dataclass(frozen=True)
class DerivedSpec:
    """A DECLARED derived row field: map ``from_field``'s value → a new ``field`` (LP-437).

    FAIL-CLOSED (D5): an UNMAPPED source value produces an ABSENT Field, never a fabricated
    value — copying ``_direction``'s absent-on-unknown discipline (the forged-deposit guard).
    """

    field: str
    from_field: str
    mapping: dict[str, str]


@dataclass(frozen=True)
class ListSpec:
    """One document type's declaration of a generic nested list (LP-437).

    ``fields`` are the row's declared field names (read via ``_typed_field``, already coerced at
    extraction time). ``derived`` adds computed fields (fail-closed). ``redact`` runs the shared
    ``_DESC_REDACT`` over named fields. ``stable_row_id`` assigns a content-derived ``row_id`` per row
    (only for a list whose rows a rule enumerates as subjects). Emitted by the generator (LP-438).

    ``pii`` names the row fields that are WHOLE-VALUE sensitive and the mask each takes — the
    deterministic per-list route LP-443 deferred, arriving in bug-010 because its absence cost
    staging every snapshot for a week. Distinct from ``redact``, which scrubs identifiers out of free
    text and leaves an ordinary ``Field``.

    DECLARED PER LIST, NOT GLOBALLY, AND THE REASON IS ``row_id``. A row's id is content-derived over
    the WHOLE row, so masking a field MOVES the ids of every row in that list. Whether that matters
    is not "does anything read this list" — ``source_document_by_subject`` reads every list on every
    run, putting each ``row_id`` into the parents map that attaches source documents to findings.
    It is whether anything ENUMERATES the list, because only then is a ``row_id`` a finding's
    ``subject_id``, and a moved subject id retires every finding on the old key and mints it again,
    stranding any sign-off a processor had made.

    Today only ``tradelines`` is enumerated (``all_list_rows`` is called with that name at all four
    production sites: ``enumerators.py`` 355 / 538, ``derived.py`` 2977 / 2990). **Adding an
    enumerator over a list that declares ``pii`` re-keys every finding on it.** ``stable_row_id``
    marks the lists where that applies.

    AND THE RE-KEY IS NOT A ONE-OFF. A masked field serializes its ``match_hash``, which is an HMAC
    under the application encryption key — so a row id now depends on that secret, not on extracted
    content alone. It moves again on an ``encryption_key`` rotation (ADR-051) and on a
    ``_HASH_VERSION`` bump, and identical data yields different ids in differently-keyed
    environments, which was not previously possible. Inert while nothing enumerates a ``pii`` list;
    load-bearing the moment one does, and the reason to weigh ``pii`` and ``stable_row_id`` together
    rather than each on its own.

    This registry exists because ``_PII_FIELDS`` cannot reach a row at all — it is read only by
    ``build_document_fields``, over a document's flat keys. Not, as the first write-up claimed,
    because a global entry would leak into every list; it would have no effect on any list.
    """

    name: str
    fields: tuple[str, ...]
    derived: tuple[DerivedSpec, ...] = ()
    redact: frozenset[str] = frozenset()
    stable_row_id: bool = False
    pii: Mapping[str, tuple[PiiKind, bool]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """A ``pii`` name that is not a field of this list is a silent no-op — refuse it (bug-010).

        ``_LIST_SPECS`` is emitted by the LP-438 generator from ``schema_specs/*.json``, so a
        regeneration that renames a field would leave this registry naming a key that no longer
        exists: masking would stop, the raw value would land in the row again, and the at-rest guard
        would resume refusing every snapshot on the file — the failure bug-010 fixed, reintroduced
        with no signal. Raised at IMPORT, the way a rule spec refuses an unknown key.
        """
        declared = set(self.fields) | {d.field for d in self.derived}
        if unknown := set(self.pii) - declared:
            raise ValueError(
                f"ListSpec {self.name!r} declares pii for undeclared field(s) {sorted(unknown)}"
            )


# LP-443 — the FIRST wired generic list: bank_statement's transactions. This proves the capture
# bridge end to end on a shipping extractor. It COEXISTS with the legacy bespoke transactions path
# (transaction_field_sets → build_transactions → entry.transactions) — the SAME extracted
# "transactions" rows populate BOTH entry.transactions (legacy, feeds live AS-1 — byte-unchanged)
# AND entry.lists["transactions"] (generic, read by no rule yet). Belt-and-braces, additive, never a
# migration (AS-1 must not move). NOTE (reported finding): the generic ``direction`` uses the minimal
# snippet mapping (deposit/withdrawal); the legacy ``_direction`` maps a richer vocabulary — a per-rule
# consumer of the generic list (a later step) must not read this ``direction`` as if it were AS-1's.
_TRANSACTIONS_LIST = ListSpec(
    name="transactions",
    fields=(
        "date",
        "description",
        "amount",
        "transaction_type",
        "running_balance",
        "originator_id",  # bug-001
    ),
    derived=(
        DerivedSpec(
            field="direction",
            from_field="transaction_type",
            mapping={"deposit": "credit", "withdrawal": "debit"},
        ),
    ),
    redact=frozenset({"description"}),
    stable_row_id=True,
    # bug-010 — the same declaration the legacy path reads, so the two cannot drift apart and mask
    # the value on one path while shipping it raw on the other.
    #
    # This moved every transactions ``row_id``, which is inert TODAY because nothing enumerates this
    # list — no finding's subject is a transactions row. It is not inert for a future enumerator over
    # it, and the ids now also move with the encryption key: see ``ListSpec.pii``. The declaration of
    # ``stable_row_id`` above anticipates exactly that enumerator, so this note sits beside it.
    pii=_TXN_PII_FIELDS,
)

# LP-443 step 7 — the first wired batch of GENERATED extractors' lists. Each ListSpec is emitted from
# its schema spec (fields only — no derived/redact/stable_row_id unless the spec declares them); the rows
# are captured bare by the generated extractor and read generically here. No rule reads these yet (a
# per-rule consumer is a separate step); they are additive facts on the snapshot.
_COMPARABLE_SALES_LIST = ListSpec(
    name="comparable_sales",
    fields=(
        "comp_number",
        "address",
        "sale_price",
        "sale_date",
        "gross_living_area",
        "distance_from_subject",
        "net_adjustment",
        "adjusted_value",
    ),
)
_TRADELINES_LIST = ListSpec(
    name="tradelines",
    fields=(
        "creditor_name",
        "account_type",
        "account_number_masked",
        "account_ownership",
        "date_opened",
        "balance",
        "credit_limit_or_high_credit",
        "monthly_payment",
        "past_due_amount",
        "account_status",
        "payment_status",
        "payment_history_24mo",
        "worst_delinquency",
        "is_disputed",
    ),
    # LP-479 — row ids, so LP-480's per-liability enumerator can anchor a per-row finding to a durable
    # subject. Content-derived over the WHOLE row (scoped by document id + list name), so it needs no
    # composite key and cannot collide unless two tradelines are byte-identical in all 14 fields — in
    # which case assign_content_ids' occurrence tiebreak still separates them.
    stable_row_id=True,
    # LP-443 review — a row-PII backstop: list-row PII is NOT _PII_FIELDS-routed, so if the (unvalidated,
    # starter) prompt fails to mask, the _DESC_REDACT 9+-digit scrub redacts a leaked full account number
    # (a genuinely-masked ****1234 is untouched). Not a full PiiField route — the deterministic per-list
    # route is the deferred step; this closes the worst case now that the extractor is wired live.
    redact=frozenset({"account_number_masked"}),
)
_PUBLIC_RECORDS_LIST = ListSpec(
    name="public_records",
    fields=(
        "record_type",
        "filing_date",
        "discharge_or_satisfied_date",
        "status",
        "amount",
        "court_or_jurisdiction",
    ),
)
_INQUIRIES_LIST = ListSpec(
    name="inquiries",
    fields=("inquiry_date", "creditor_name", "inquiry_type"),
)
_SCHEDULE_B_ITEMS_LIST = ListSpec(
    name="schedule_b_items",
    fields=(
        "schedule",
        "item_number",
        "item_type",
        "description",
        "recording_date",
        "recording_reference",
        "amount",
        "is_satisfied",
        "affected_party",
    ),
)
_CHAIN_OF_TITLE_LIST = ListSpec(
    name="chain_of_title",
    fields=("transfer_date", "grantor", "grantee", "consideration_amount", "recording_reference"),
)
_AUS_REQUIRED_CONDITIONS_LIST = ListSpec(
    name="aus_required_conditions",
    fields=("condition_number", "condition_category", "condition_text", "is_prior_to_close"),
)
_PRIOR_VA_LOAN_OR_ENTITLEMENT_CHARGES_LIST = ListSpec(
    name="prior_va_loan_or_entitlement_charges",
    fields=("prior_loan_reference", "entitlement_amount_charged", "prior_loan_status"),
)
_PAYMENT_HISTORY_MONTHS_LIST = ListSpec(
    name="payment_history_months",
    fields=("month", "payment_status", "amount_paid", "source"),
)
_MORTGAGEE_OR_LIENHOLDER_ENTRIES_LIST = ListSpec(
    name="mortgagee_or_lienholder_entries",
    fields=("lender_name", "loan_number", "clause_address"),
    redact=frozenset({"loan_number"}),  # LP-443 review — row-PII backstop (see _TRADELINES_LIST)
)
# LP-446 — the homeowners_insurance diff's list (forms/endorsements). A personal-property replacement-cost
# endorsement lands here as a row, kept DISTINCT from the dwelling's replacement_cost_or_coinsurance_basis
# typed field (the IH-1 anti-conflation). No PII in a form code/description.
_FORMS_AND_ENDORSEMENTS_LIST = ListSpec(
    name="forms_and_endorsements",
    fields=(
        "code_or_label",
        "description",
        "premium_or_amount",
    ),  # LP-460 — the endorsement Premium column
)
# LP-446 — the pay_stub diff's lists: the earnings split (base/OT/bonus — IN-10/IN-11) + deductions.
# Legacy pay-stub extraction has NO list attribute, so these are purely additive (no legacy to disturb).
_EARNINGS_LINES_LIST = ListSpec(
    name="earnings_lines",
    fields=("earning_type", "hours", "rate", "current_amount", "ytd_amount"),
)
_DEDUCTION_LINES_LIST = ListSpec(
    name="deduction_lines",
    fields=("label", "category", "current_amount", "ytd_amount"),
)

# LP-443 Phase C — ListSpec constants for the remaining generated list-bearing types (fields only,
# from each spec; collisions on a shared list name are type-prefixed).
_AFFILIATE_ENTRIES_LIST = ListSpec(
    name="affiliate_entries",
    fields=(
        "provider_name",
        "service_type",
        "nature_of_relationship",
        "estimated_charge_or_range",
        "source",
    ),
)
_PAYMENT_HISTORY_LIST = ListSpec(
    name="payment_history",
    fields=(
        "date",
        "amount",
        "status",
        "source",
    ),
)
_EVENT_CHRONOLOGY_LIST = ListSpec(
    name="event_chronology",
    fields=(
        "date",
        "event",
        "source",
    ),
)
_CHECK_ITEMS_LIST = ListSpec(
    name="check_items",
    fields=(
        "payer_or_drawer",
        "amount",
        "check_number",
        "source",
    ),
)
_SUPPORTING_DOCUMENTS_LIST = ListSpec(name="supporting_documents", fields=("document_name",))
_BOARDER_RENTAL_PAYMENTS__PAYMENT_HISTORY_LIST = ListSpec(
    name="payment_history",
    fields=(
        "date",
        "amount",
        "method",
        "status",
    ),
)
_INSPECTION_RESULTS_LIST = ListSpec(
    name="inspection_results",
    fields=(
        "type",
        "date",
        "result",
    ),
)
_OWNER_PARTNER_SHAREHOLDER_RECORDS_LIST = ListSpec(
    name="owner_partner_shareholder_records",
    fields=(
        "owner_name",
        "ownership_percentage",
        "distribution_or_k1_share",
    ),
)
_CHILD_SUPPORT_INCOME__PAYMENT_HISTORY_LIST = ListSpec(
    name="payment_history",
    fields=(
        "date",
        "amount",
        "status",
        "source",
    ),
)
_SUPPORT_AWARDS_LIST = ListSpec(
    name="support_awards",
    fields=(
        "award_type",
        "amount",
        "frequency",
        "start_date",
        "end_date",
        "payer",
        "payee",
        "escalation_or_conditions",
        "source",
    ),
)
_UNMAPPED_KEY_VALUE_PAIRS_LIST = ListSpec(
    name="unmapped_key_value_pairs",
    fields=(
        "label",
        "value",
    ),
    # LP-479 follow-up — the spec (064-custom.json) declared this redaction and the shipped module
    # dropped it. A "custom" document has no known schema, so ANY PII the model reads lands in this
    # passthrough unmasked (the spec's own pii_note says so). This is the drift in the direction the
    # parity test now forbids: spec-declares, module-omits.
    redact=frozenset({"value"}),
)
_DEDUCTIONS_OR_OFFSETS_LIST = ListSpec(
    name="deductions_or_offsets",
    fields=(
        "label",
        "amount",
        "source",
    ),
)
_EMPLOYMENT_CONTINGENCIES_LIST = ListSpec(name="employment_contingencies", fields=("contingency",))
_RECURRING_PAYMENT_HISTORY_LIST = ListSpec(
    name="recurring_payment_history",
    fields=(
        "date",
        "amount",
        "status",
        "source",
    ),
)
_ASSET_LINE_ITEMS_LIST = ListSpec(
    name="asset_line_items",
    fields=(
        "category",
        "description",
        "value",
        "source",
    ),
)
_MORTGAGEE_CLAUSE_ENTRIES_LIST = ListSpec(
    name="mortgagee_clause_entries",
    fields=(
        "mortgagee_name",
        "mortgagee_address",
        "loan_number",
        "capacity",
        "source",
    ),
    redact=frozenset({"loan_number"}),  # LP-443 review — row-PII backstop (see _TRADELINES_LIST)
)
_RETURN_LINE_ITEMS_LIST = ListSpec(
    name="return_line_items",
    fields=(
        "section",
        "line_label",
        "amount",
        "source",
    ),
)
_SCHEDULE_K_ITEMS_LIST = ListSpec(
    name="schedule_k_items",
    fields=(
        "line_label",
        "amount",
        "source",
    ),
)
_OFFICER_COMPENSATION_LIST = ListSpec(
    name="officer_compensation",
    fields=(
        "officer_name_or_label",
        "title",
        "percent_time_or_ownership",
        "compensation_amount",
        "source",
    ),
)
_FOSTER_CARE_VERIFICATION__PAYMENT_HISTORY_LIST = ListSpec(
    name="payment_history",
    fields=(
        "period",
        "amount",
        "date_paid",
        "source",
    ),
)
_SPECIAL_ASSESSMENTS_LIST = ListSpec(
    name="special_assessments",
    fields=(
        "description",
        "amount",
        "status",
        "date",
    ),
)
_K1_BOX_ITEMS_LIST = ListSpec(
    name="k1_box_items",
    fields=(
        "box_number",
        "box_label",
        "amount",
        "code",
        "source",
    ),
)
_TRANSCRIPT_LINE_ITEMS_LIST = ListSpec(
    name="transcript_line_items",
    fields=(
        "line_code",
        "description",
        "amount",
    ),
)
_TRANSFER_PATH_OR_CHRONOLOGY_LIST = ListSpec(
    name="transfer_path_or_chronology",
    fields=(
        "date",
        "from",
        "to",
        "amount",
    ),
)
_BUILDING_LIMITS_LIST = ListSpec(
    name="building_limits",
    fields=(
        "building_identifier_or_address",
        "coverage_limit",
        "deductible",
        "wind_hail_named_storm_deductible",
        "source",
    ),
)
_ENTITLEMENTS_LIST = ListSpec(
    name="entitlements",
    fields=(
        "label",
        "amount",
    ),
)
_KEY_VALUE_PAIRS_LIST = ListSpec(
    name="key_value_pairs",
    fields=(
        "key",
        "value",
    ),
)
_ORIGINATION_AND_BROKER_FEE_ITEMS_LIST = ListSpec(
    name="origination_and_broker_fee_items",
    fields=(
        "fee_name",
        "amount",
    ),
)
_PAYOFF_CONDITIONS_ORLIMITATIONS_LIST = ListSpec(
    name="payoff_conditions_orlimitations",
    fields=(
        "condition",
        "source",
    ),
)
_CLOSING_COST_LINE_ITEMS_LIST = ListSpec(
    name="closing_cost_line_items",
    fields=(
        "label",
        "section",
        "amount",
        "paid_by",
    ),
)
_INSTALLMENTS_AND_DUE_DATES_LIST = ListSpec(
    name="installments_and_due_dates",
    fields=(
        "installment_label",
        "amount",
        "due_date",
        "paid_indicator",
    ),
)
_SIGNATURES_AND_NOTARY_LIST = ListSpec(
    name="signatures_and_notary",
    fields=(
        "signer_name",
        "capacity",
        "signed_indicator",
        "notary_indicator",
        "date",
    ),
)
_MEDICARE_OR_OTHER_DEDUCTIONS_LIST = ListSpec(
    name="medicare_or_other_deductions",
    fields=(
        "label",
        "amount",
        "source",
    ),
)
_TRANSACTIONS_OR_ACTIVITY_LIST = ListSpec(
    name="transactions_or_activity",
    fields=(
        "date",
        "description",
        "amount",
        "type",
        "running_balance",
    ),
)
_ENCROACHMENTS_OR_OVERLAPS_LIST = ListSpec(
    name="encroachments_or_overlaps",
    fields=(
        "description",
        "affected_boundary",
        "location",
    ),
)
_TREATMENT_OR_REPAIR_ITEMS_COMPLETED_LIST = ListSpec(
    name="treatment_or_repair_items_completed",
    fields=(
        "item",
        "method_or_chemical",
        "area",
        "status",
    ),
)
_FINDINGS_LIST = ListSpec(
    name="findings",
    fields=(
        "category",
        "insect_or_damage_type",
        "location",
        "description",
    ),
)
_INFORMATION_RETURN_RECORDS_LIST = ListSpec(
    name="information_return_records",
    fields=(
        "form_type",
        "payer_name",
        "payer_tin_masked",
        "box_or_income_type",
        "amount",
        "account_number_masked",
    ),
    # LP-443 review — row-PII backstop (see _TRADELINES_LIST). Scrubs a leaked full TIN/account number.
    redact=frozenset({"payer_tin_masked", "account_number_masked"}),
)
_AUTHORIZED_SIGNER_NAMES_AND_CAPACITY_LIST = ListSpec(
    name="authorized_signer_names_and_capacity",
    fields=(
        "name",
        "capacity",
        "signature_present",
    ),
)
_BENEFICIARY_K1_RECORDS_LIST = ListSpec(
    name="beneficiary_k1_records",
    fields=(
        "beneficiary_name",
        "beneficiary_tin_masked",
        "distributive_share_amount",
        "income_type",
        "source",
    ),
    redact=frozenset(
        {"beneficiary_tin_masked"}
    ),  # LP-443 review — row-PII backstop (see _TRADELINES_LIST)
)
_UNSECURED_NOTE__PAYMENT_HISTORY_LIST = ListSpec(
    name="payment_history",
    fields=(
        "period",
        "payment_amount",
        "payment_status",
        "remaining_balance",
        "source",
    ),
)
_VERIFIED_ACCOUNTS_LIST = ListSpec(
    name="verified_accounts",
    fields=(
        "institution_name",
        "account_number_masked",
        "account_type",
        "account_holder_name",
        "current_balance",
        "available_balance",
        "average_balance",
        "source",
    ),
    redact=frozenset(
        {"account_number_masked"}
    ),  # LP-443 review — row-PII backstop (see _TRADELINES_LIST)
)
_DEPOSIT_ACCOUNTS_LIST = ListSpec(
    name="deposit_accounts",
    fields=(
        "account_type",
        "account_number_masked",
        "current_balance",
        "average_balance",
        "date_opened",
        "source",
    ),
    redact=frozenset(
        {"account_number_masked"}
    ),  # LP-443 review — row-PII backstop (see _TRADELINES_LIST)
)
_RENT_PAYMENT_HISTORY_LIST = ListSpec(
    name="rent_payment_history",
    fields=(
        "month",
        "amount_due",
        "amount_paid",
        "payment_status",
        "source",
    ),
)

# document_type → its declared generic lists. bank_statement + the LP-443 batch are wired; every OTHER
# document type still gets lists={} (present-empty) until its extractor's lists are wired. (condo_questionnaire
# and business_license are wired for extraction but are FLAT — no list, so they are not here.)
# LP-446 — the 6 remaining diff extractors' lists (voe / investment / purchase / property-tax / P&L / HOA).
_GROSS_EARNINGS_HISTORY_LIST = ListSpec(
    name="gross_earnings_history",
    fields=(
        "period",
        "base",
        "overtime",
        "commission",
        "bonus",
    ),
)
_SECURITY_POSITIONS_LIST = ListSpec(
    name="security_positions",
    fields=(
        "description",
        "ticker_or_cusip",
        "quantity",
        "market_value",
        "asset_class",
        "source",
    ),
)
_ADDENDA_LIST = ListSpec(
    name="addenda",
    fields=(
        "addendum_name",
        "addendum_type",
        "addendum_date",
        "is_signed",
        "is_attached",
    ),
)
_CONTINGENCIES_LIST = ListSpec(
    name="contingencies",
    fields=(
        "contingency_type",
        "deadline_date",
        "is_waived",
    ),
)
_PROPERTY_TAX_BILL__INSTALLMENTS_AND_DUE_DATES_LIST = ListSpec(
    name="installments_and_due_dates",
    fields=(
        "installment_label",
        "amount",
        "due_date",
        "paid_status",
        "paid_date",
        "source",
    ),
)
_FINANCIAL_LINE_ITEMS_LIST = ListSpec(
    name="financial_line_items",
    fields=(
        "section",
        "label",
        "amount",
        "source",
    ),
)
_SPECIAL_ASSESSMENT_ITEMS_LIST = ListSpec(
    name="special_assessment_items",
    fields=(
        "description",
        "amount",
        "duration",
    ),
)

# LP-460 — the six missing repeating-row lists (schema-gap phase 2). Each is a flat-row list the extractor
# now captures; no rule enumerates them yet, so no stable_row_id and no derived. Five carry no per-row
# account number (amounts/dates/descriptions/coverage names — those keep their masked typed-core scalars),
# so no redact. The ONE exception is the master cert's coverage_lines.policy_number: it IS a per-row account
# number whose masking rests only on the generated prompt, so it gets the same _DESC_REDACT backstop as
# _TRADELINES_LIST's account_number_masked — a full number the prompt fails to mask is scrubbed here.
_MORTGAGE_STATEMENT__TRANSACTION_ACTIVITY_LIST = ListSpec(
    name="transaction_activity",
    fields=("date", "description", "principal", "interest", "escrow", "fees_or_other", "total"),
)
_RETIREMENT_ACCOUNT__HOLDINGS_LIST = ListSpec(
    name="holdings",
    fields=(
        "symbol",
        "description",
        "quantity",
        "price",
        "market_value",
        "cost_basis",
        "unrealized_gain_loss",
    ),
)
_HOA_STATEMENT__PAYMENT_LEDGER_LIST = ListSpec(
    name="payment_ledger",
    fields=("date", "description", "charge", "paid", "running_balance"),
)
_PROPERTY_TAX_BILL__JURISDICTION_BREAKDOWN_LIST = ListSpec(
    name="jurisdiction_breakdown",
    fields=("taxing_unit", "tax_rate", "amount_billed", "adjusted_billed"),
)
_HOMEOWNERS_INSURANCE__COVERAGE_LINES_LIST = ListSpec(
    name="coverage_lines",
    fields=("coverage_name", "limit", "premium"),
)
_MASTER_INSURANCE__COVERAGE_LINES_LIST = ListSpec(
    name="coverage_lines",
    fields=("type_of_insurance", "policy_number", "limit", "deductible", "causes_of_loss"),
    # LP-460 review — a row-PII backstop mirroring _TRADELINES_LIST: policy_number is a per-row account
    # number masked only by the (generated, unvalidated-for-masking) master prompt, so if the model returns
    # a full number the _DESC_REDACT 9+-digit scrub redacts it here (a genuinely-masked ****4432 is untouched).
    redact=frozenset({"policy_number"}),
)
# LP-467 — the ACORD 25 certificate's coverage grid, ONE ROW PER COVERAGE SECTION (CGL / Auto / Umbrella /
# Workers Comp), the section's headline limit per row. policy_number redacted as a row-PII backstop (mirrors
# the master-policy list) though ACORD policy numbers are usually separator'd and clear the guard.
_CERTIFICATE_OF_LIABILITY_INSURANCE__COVERAGE_LINES_LIST = ListSpec(
    name="coverage_lines",
    fields=(
        "coverage_type",
        "insurer_name",
        "insurer_naic_number",
        "policy_number",
        "policy_effective_date",
        "policy_expiration_date",
        "limit_description",
        "limit_amount",
    ),
    redact=frozenset({"policy_number"}),
)

# LP-461 — the schema-gap phase-3 flat-row lists. No stable_row_id / derived (no rule enumerates them yet).
_W2__BOX_12_ITEMS_LIST = ListSpec(
    name="box_12_items",
    fields=("code", "amount"),
)
_TAX_RETURN__W2_FORMS_LIST = ListSpec(
    name="w2_forms",
    fields=("employer_name", "wages", "federal_withheld"),
)
_TAX_RETURN__CAPITAL_GAINS_LIST = ListSpec(
    name="capital_gains_transactions",
    fields=("description", "proceeds", "cost_basis", "gain_or_loss"),
)
_LETTER_OF_EXPLANATION__EXPLANATION_ITEMS_LIST = ListSpec(
    name="explanation_items",
    fields=("item_topic", "item_date_or_period", "item_explanation"),
)
_BANK_STATEMENT__ADDITIONAL_ACCOUNTS_LIST = ListSpec(
    name="additional_accounts",
    fields=("account_number_masked", "account_type", "beginning_balance", "ending_balance"),
    # row-PII backstop (mirrors _TRADELINES_LIST): the prompt masks account_number_masked to last 4; if a
    # full number leaks the _DESC_REDACT 9+-digit scrub redacts it here (a genuine ****6290 is untouched).
    redact=frozenset({"account_number_masked"}),
)

# LP-465 — the temporary buydown's per-period payment schedule (the substance of the type: reduced
# rate, borrower's reduced payment, and the monthly subsidy per year-range). No PII (rates/amounts/dates).
_PAYMENT_SCHEDULE_LIST = ListSpec(
    name="payment_schedule",
    fields=(
        "period_label",
        "period_start",
        "effective_rate",
        "borrower_payment",
        "monthly_subsidy",
        "source",
    ),
)

_LIST_SPECS: dict[str, tuple[ListSpec, ...]] = {
    "temporary_buydown_agreement": (_PAYMENT_SCHEDULE_LIST,),  # LP-465
    "certificate_of_liability_insurance": (
        _CERTIFICATE_OF_LIABILITY_INSURANCE__COVERAGE_LINES_LIST,
    ),  # LP-467
    "voe": (_GROSS_EARNINGS_HISTORY_LIST,),  # LP-446 diff (live extractor)
    "investment_account": (_SECURITY_POSITIONS_LIST,),  # LP-446 diff (live extractor)
    "purchase_agreement": (
        _ADDENDA_LIST,
        _CONTINGENCIES_LIST,
    ),  # LP-446 diff (live extractor)
    "property_tax_bill": (  # LP-446 diff + LP-460 jurisdiction_breakdown
        _PROPERTY_TAX_BILL__INSTALLMENTS_AND_DUE_DATES_LIST,
        _PROPERTY_TAX_BILL__JURISDICTION_BREAKDOWN_LIST,
    ),
    "profit_and_loss": (_FINANCIAL_LINE_ITEMS_LIST,),  # LP-446 diff (live extractor)
    "hoa_statement": (  # LP-446 diff + LP-460 payment_ledger
        _SPECIAL_ASSESSMENT_ITEMS_LIST,
        _HOA_STATEMENT__PAYMENT_LEDGER_LIST,
    ),
    "mortgage_statement": (_MORTGAGE_STATEMENT__TRANSACTION_ACTIVITY_LIST,),  # LP-460
    "retirement_account": (_RETIREMENT_ACCOUNT__HOLDINGS_LIST,),  # LP-460
    "bank_statement": (  # LP-461 + additional_accounts (combined-statement recovery)
        _TRANSACTIONS_LIST,
        _BANK_STATEMENT__ADDITIONAL_ACCOUNTS_LIST,
    ),
    "w2": (_W2__BOX_12_ITEMS_LIST,),  # LP-461
    "tax_return": (_TAX_RETURN__W2_FORMS_LIST, _TAX_RETURN__CAPITAL_GAINS_LIST),  # LP-461
    "letter_of_explanation": (_LETTER_OF_EXPLANATION__EXPLANATION_ITEMS_LIST,),  # LP-461
    "appraisal": (_COMPARABLE_SALES_LIST,),
    "credit_report": (_TRADELINES_LIST, _PUBLIC_RECORDS_LIST, _INQUIRIES_LIST),
    "title_commitment": (_SCHEDULE_B_ITEMS_LIST, _CHAIN_OF_TITLE_LIST),
    "aus_findings": (_AUS_REQUIRED_CONDITIONS_LIST,),
    "certificate_of_eligibility": (_PRIOR_VA_LOAN_OR_ENTITLEMENT_CHARGES_LIST,),
    "verification_of_mortgage": (_PAYMENT_HISTORY_MONTHS_LIST,),
    "homeowner_s_insurance_quote": (_MORTGAGEE_OR_LIENHOLDER_ENTRIES_LIST,),
    "homeowners_insurance": (  # LP-446 diff + LP-460 coverage_lines
        _FORMS_AND_ENDORSEMENTS_LIST,
        _HOMEOWNERS_INSURANCE__COVERAGE_LINES_LIST,
    ),
    "pay_stub": (_EARNINGS_LINES_LIST, _DEDUCTION_LINES_LIST),  # LP-446 diff (live extractor)
    # LP-443 Phase C — the remaining generated list-bearing types.
    "affiliated_business_disclosure": (_AFFILIATE_ENTRIES_LIST,),
    "alimony_income": (_PAYMENT_HISTORY_LIST,),
    "application_loe": (_EVENT_CHRONOLOGY_LIST,),
    "bank_deposit_slip": (_CHECK_ITEMS_LIST,),
    "boarder_proof_of_residency": (_SUPPORTING_DOCUMENTS_LIST,),
    "boarder_rental_payments": (_BOARDER_RENTAL_PAYMENTS__PAYMENT_HISTORY_LIST,),
    "building_permits": (_INSPECTION_RESULTS_LIST,),
    "business_tax_return": (_OWNER_PARTNER_SHAREHOLDER_RECORDS_LIST,),
    "child_support_income": (_CHILD_SUPPORT_INCOME__PAYMENT_HISTORY_LIST,),
    "court_order_documents": (_SUPPORT_AWARDS_LIST,),
    "custom": (_UNMAPPED_KEY_VALUE_PAIRS_LIST,),
    "disability_award_letter": (_DEDUCTIONS_OR_OFFSETS_LIST,),
    "employment_offer_letter": (_EMPLOYMENT_CONTINGENCIES_LIST,),
    "evidence_of_payment": (_RECURRING_PAYMENT_HISTORY_LIST,),
    "financial_statements": (_ASSET_LINE_ITEMS_LIST,),
    "flood_insurance_policy": (_MORTGAGEE_CLAUSE_ENTRIES_LIST,),
    "form_1040_personal_tax_transcripts": (_RETURN_LINE_ITEMS_LIST,),
    "form_1065_partnership_tax_transcripts": (_SCHEDULE_K_ITEMS_LIST,),
    "form_1120_corporate_tax_transcripts": (_OFFICER_COMPENSATION_LIST,),
    "foster_care_verification": (_FOSTER_CARE_VERIFICATION__PAYMENT_HISTORY_LIST,),
    "hoa_certification": (_SPECIAL_ASSESSMENTS_LIST,),
    "k1_statement": (_K1_BOX_ITEMS_LIST,),
    "k_1_shareholder_profit_and_loss_transcripts": (_TRANSCRIPT_LINE_ITEMS_LIST,),
    "letter_of_explanation_asset": (_TRANSFER_PATH_OR_CHRONOLOGY_LIST,),
    "master_insurance_policy_for_condominium": (
        _BUILDING_LIMITS_LIST,
        _MASTER_INSURANCE__COVERAGE_LINES_LIST,
    ),
    "military_leave_and_earning_statement_les": (_ENTITLEMENTS_LIST,),
    "miscellaneous_document": (_KEY_VALUE_PAIRS_LIST,),
    "mortgage_loan_origination_agreement": (_ORIGINATION_AND_BROKER_FEE_ITEMS_LIST,),
    "payoff_statement": (_PAYOFF_CONDITIONS_ORLIMITATIONS_LIST,),
    "prior_closing_disclosure_final_cd_from_purchase": (_CLOSING_COST_LINE_ITEMS_LIST,),
    "property_tax_bill_non_subject": (_INSTALLMENTS_AND_DUE_DATES_LIST,),
    "seller_signature_authority": (_SIGNATURES_AND_NOTARY_LIST,),
    "social_security_award_letter": (_MEDICARE_OR_OTHER_DEDUCTIONS_LIST,),
    "statement_of_account": (_TRANSACTIONS_OR_ACTIVITY_LIST,),
    "survey": (_ENCROACHMENTS_OR_OVERLAPS_LIST,),
    "termite_completion": (_TREATMENT_OR_REPAIR_ITEMS_COMPLETED_LIST,),
    "termite_report": (_FINDINGS_LIST,),
    "transcripts_of_1099": (_INFORMATION_RETURN_RECORDS_LIST,),
    "trust_documents": (_AUTHORIZED_SIGNER_NAMES_AND_CAPACITY_LIST,),
    "trust_federal_tax_returns": (_BENEFICIARY_K1_RECORDS_LIST,),
    "unsecured_note": (_UNSECURED_NOTE__PAYMENT_HISTORY_LIST,),
    "verification_of_assets": (_VERIFIED_ACCOUNTS_LIST,),
    "verification_of_deposit": (_DEPOSIT_ACCOUNTS_LIST,),
    "verification_of_rent": (_RENT_PAYMENT_HISTORY_LIST,),
}


def _raw_scalar(row: dict[str, Any], field: str) -> Any:
    """The raw stored value of a row field — the ``{"value": ...}`` inner value, or a bare value.

    A derived helper reads its SOURCE from the raw extraction row (like ``_direction`` reads
    ``transaction_type``), tolerant of both the typed ``{value, source, confidence}`` shape and a
    bare scalar the extractor may store for a non-typed-core row field.
    """
    entry = row.get(field)
    if isinstance(entry, dict):
        return entry.get("value")
    return entry


def _derive_field(row: dict[str, Any], spec: DerivedSpec) -> Field:
    """Map a source value to a new derived Field; ABSENT on an unmapped value (fail-closed, D5)."""
    raw = _raw_scalar(row, spec.from_field)
    if raw is None:
        return Field.missing()
    key = str(raw).strip().lower().replace(" ", "_")
    mapped = spec.mapping.get(key)
    if mapped is None:
        return Field.missing()  # unmapped → absent, NEVER fabricated (the _direction discipline)
    return Field.present(mapped, source=_DERIVED)


def _redact_field(field: Field) -> Field:
    """The field with any 9+-digit run redacted (the shared ``_DESC_REDACT``); non-str/absent unchanged."""
    if field.absent or not isinstance(field.value, str):
        return field
    return field.model_copy(update={"value": _DESC_REDACT.sub(_REDACTED, field.value)})


def _list_field(raw: Any) -> Field:
    """One generic-list row field → a ``Field`` (LP-443 — the capture bridge).

    A generic-list row is stored as BARE scalars + one ``source`` per row — the shipping
    ``bank_statement.transactions`` shape (D2), matched here so a single stored shape serves every
    list. A bare row therefore carries NO per-field confidence, so it is honestly ``None`` (D4 — the
    prompt supplies one page/snippet per row, never a per-field number; never fabricate one). A
    ``{value}``-wrapped value is unwrapped defensively (a hand-written extractor could store either),
    but confidence stays ``None`` — the wrapped shape carries none for list rows either. Mirrors
    ``_txn_field`` (values already stringified by the extractor's ``model_dump(mode="json")``)."""
    if isinstance(raw, dict):
        raw = raw.get("value")
    scalar = _scalar(raw)
    if scalar is None:
        return Field.missing()
    return Field.present(scalar, source=_EXTRACTED, confidence=None)


def _list_row_fields(
    row: dict[str, Any], spec: ListSpec, *, loan_file_id: UUID
) -> dict[str, SnapshotField]:
    """One raw extraction row → its ``{name: Field|PiiField}`` map (declared + derived + redacted).

    A name in ``spec.pii`` is routed through ``PiiField`` (bug-010) rather than landing as a plain
    ``Field.value`` — ``pre_masked`` selecting the same two constructors ``build_document_fields``
    picks between for a flat field.

    ROUTED FROM THE RAW VALUE, AND ``redact`` DOES NOT RUN ON IT. The first cut redacted first and
    masked second, which is silently destructive on the very combination this mechanism exists to
    replace: ``_TRADELINES_LIST`` already declares ``redact={"account_number_masked"}`` as LP-443's
    backstop, so declaring the same name in ``pii`` would have hashed the string ``"[redacted]"`` —
    giving every leaked account on the file the SAME match_hash, and making two unrelated accounts
    compare equal. A masked field needs no scrub: the mask is strictly stronger.
    """
    # ``source`` is the RESERVED per-row provenance key (the bare-row bridge stores {page,snippet} under
    # it), never a data field — yet 27 specs mistakenly declared a ``source`` field ("provenance wrapper")
    # that carries through to their ListSpecs. Skip it here so no list surfaces a junk ``source`` Field
    # regardless of the declaration (LP-446 review). A follow-up sweep should drop it from the specs +
    # regenerate so the extractors also stop suppressing real provenance.
    plain: dict[str, Field] = {
        name: _list_field(row.get(name)) for name in spec.fields if name != "source"
    }
    for dspec in spec.derived:
        plain[dspec.field] = _derive_field(row, dspec)

    fields: dict[str, SnapshotField] = {}
    for name, fld in plain.items():
        routing = spec.pii.get(name)
        if routing is None:
            fields[name] = _redact_field(fld) if name in spec.redact else fld
            continue
        if fld.absent or fld.value is None:
            fields[name] = fld  # absent stays absent — a masked display would fabricate a value
            continue
        kind, pre_masked = routing
        source = fld.source or _EXTRACTED
        fields[name] = (
            PiiField.pre_masked(fld.value, kind=kind, source=source, confidence=fld.confidence)
            if pre_masked
            else PiiField.from_raw(
                fld.value,
                kind=kind,
                loan_file_id=loan_file_id,
                source=source,
                confidence=fld.confidence,
            )
        )
    return fields


@dataclass(frozen=True)
class _ListDraft:
    """A list reshaped WITHOUT ids (pass 1) — rows' fields + content, plus whether row_ids are wanted."""

    rows: tuple[dict[str, SnapshotField], ...]
    contents: tuple[dict[str, Any], ...]
    stable_row_id: bool


def build_list_rows(
    extracted: dict[str, Any], document_type: str | None, *, loan_file_id: UUID
) -> dict[str, _ListDraft]:
    """Reshape every declared generic list for a document (pass 1 — no ids yet), or ``{}``.

    Mirrors ``transaction_field_sets``: pure read + reshape, ids assigned later once the parent
    document's id is known. A fully-absent row is dropped (no hallucinated empty row — the schedule_c
    discipline). ``{}`` when the document type declares no list (the common case today: the registry is
    empty, so EVERY document gets ``{}`` → ``lists={}``)."""
    specs = _LIST_SPECS.get(document_type or "", ())
    drafts: dict[str, _ListDraft] = {}
    for spec in specs:
        raw = extracted.get(spec.name)
        if not isinstance(raw, list):
            continue
        rows: list[dict[str, SnapshotField]] = []
        contents: list[dict[str, Any]] = []
        for row in raw:
            if not isinstance(row, dict):
                continue
            fields = _list_row_fields(row, spec, loan_file_id=loan_file_id)
            if all(f.absent for f in fields.values()):
                continue  # nothing read → drop, never a fabricated empty row
            rows.append(fields)
            contents.append({name: fld.model_dump(mode="json") for name, fld in fields.items()})
        if rows:
            drafts[spec.name] = _ListDraft(tuple(rows), tuple(contents), spec.stable_row_id)
    return drafts


def finalize_lists(
    drafts: dict[str, _ListDraft], *, document_content_id: str
) -> dict[str, tuple[ListRow, ...]]:
    """Assign stable ``row_id``s (pass 2, where the parent document id is known) → the final ``lists`` map.

    A list declaring ``stable_row_id`` gets a content-derived id per row (scoped under the document id +
    the list name, with the duplicate tiebreak — the ``build_transactions`` shape via the generic
    ``assign_content_ids``); a list that does not is left ``row_id=None`` (aggregate-only, no per-row id).
    """
    out: dict[str, tuple[ListRow, ...]] = {}
    for name, draft in drafts.items():
        if draft.stable_row_id:
            bases = [
                {"doc": document_content_id, "list": name, **content} for content in draft.contents
            ]
            ids = assign_content_ids(LIST_PREFIX, bases)
            out[name] = tuple(
                ListRow(fields=fields, row_id=cid)
                for fields, cid in zip(draft.rows, ids, strict=True)
            )
        else:
            out[name] = tuple(ListRow(fields=fields) for fields in draft.rows)
    return out


def _document_base(
    document_type: str | None,
    refs: tuple[BorrowerRef, ...],
    fields: dict[str, SnapshotField],
    field_sets: list[TransactionFieldSet] | None,
    *,
    txn_contents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The content a document's stable id is derived from (excluding the id itself).

    Includes an ORDER-INDEPENDENT fingerprint of the document's transaction contents, so two
    statements identical in type/borrowers/fields but differing in their transactions get
    distinct ids deterministically (not by positional luck). ``fields`` is the JSON-canonical
    field map (sorted).

    ``belongs_to`` is reduced to the resolved borrower ids+names and **sorted by borrower_id**,
    so the document id is independent of the order the borrower links happen to arrive in. The
    link query orders by ``confidence`` and equal-confidence borrowers (a joint document
    matched to both spouses) have no stable relative order — folding that incidental order into
    the id would make it change between rebuilds, breaking the run-independence guarantee.

    ``txn_contents`` (optional) is the precomputed ``_txn_content(fs)`` list; when omitted it is
    computed from ``field_sets`` (keeps the pure-in-test call sites simple).
    """
    contents = (
        txn_contents
        if txn_contents is not None
        else (None if field_sets is None else [_txn_content(fs) for fs in field_sets])
    )
    return {
        "document_type": document_type,
        "belongs_to": (
            [
                {"borrower_id": str(r.borrower_id), "name": r.name}
                for r in sorted(refs, key=lambda ref: str(ref.borrower_id))
            ]
            if refs
            else None
        ),
        "fields": {key: value.model_dump(mode="json") for key, value in sorted(fields.items())},
        "transactions_fingerprint": (None if contents is None else unordered_fingerprint(contents)),
    }


@dataclass(frozen=True)
class _ReshapedDoc:
    """One document reshaped for id assignment — content only, no id yet.

    ``txn_contents`` is the ``_txn_content(fs)`` list computed once here and reused by both the
    document-id fingerprint and :func:`build_transactions`, so a row's Fields are serialized
    once per build rather than twice.
    """

    document_type: str | None
    refs: tuple[BorrowerRef, ...]
    fields: dict[str, SnapshotField]
    field_sets: list[TransactionFieldSet] | None
    txn_contents: list[dict[str, Any]] | None
    # LP-421 — tax-return schedules (None for every other document type). They need no
    # content_id, so they are carried straight through to the DocumentEntry (not folded into
    # the id fingerprint — content_ids stay byte-identical).
    schedule_c: tuple[ScheduleCRecord, ...] | None
    schedule_e: ScheduleERecord | None
    # LP-437 — generic list drafts (pass-1, pre-id), finalized with row_ids in pass 2. NOT folded
    # into the document id fingerprint, so every existing document content_id stays byte-identical.
    list_drafts: dict[str, _ListDraft]


async def _reshape_and_assign_ids(
    db: AsyncSession, loan_file: LoanFile
) -> tuple[list[Document], list[_ReshapedDoc], list[str]]:
    """Load the file's current documents, reshape each (type / resolved borrowers / fields / transaction
    field sets), and assign the stable, content-derived document ids — returned as ALIGNED lists
    ``(documents, reshaped, content_ids)``.

    The ONE place the document content-ids are derived, so the snapshot's ``documents`` section and the
    read-time ``content_id -> filename`` map (LP-377-B) build from the SAME reshape+assign — a finding's
    ``subject_key`` (a document content-id) is guaranteed to match the id the map keys on. Duplicating
    this reshape would let the two drift and silently resolve to nothing.
    """
    documents = (
        (
            await db.execute(
                only_active(
                    select(Document).where(
                        Document.loan_file_id == loan_file.id,
                        Document.is_current.is_(True),
                    ),
                    Document,
                )
                # Only the CURRENT extraction is used (current_extraction); don't
                # over-fetch every historical version and its extracted_data JSON.
                .options(selectinload(Document.extractions.and_(Extraction.is_current.is_(True))))
                .order_by(Document.document_type, Document.created_at, Document.id)
            )
        )
        .scalars()
        .all()
    )

    borrower_names = await _active_borrower_names(db, loan_file.id)
    links_by_doc = await _links_by_document(db, [d.id for d in documents])

    # Pass 1: reshape each document's content (type / resolved borrowers / fields / transaction
    # field sets) WITHOUT ids — nothing here depends on array position.
    reshaped: list[_ReshapedDoc] = []
    for document in documents:
        extraction = document.current_extraction
        extracted = extraction.extracted_data if extraction and extraction.extracted_data else {}
        fields = build_document_fields(extracted, document.document_type, loan_file_id=loan_file.id)
        refs = tuple(
            BorrowerRef(borrower_id=link.borrower_id, name=borrower_names[link.borrower_id])
            for link in links_by_doc.get(document.id, ())
            if link.borrower_id in borrower_names  # excludes links to soft-deleted borrowers
        )
        field_sets = transaction_field_sets(
            extracted, document.document_type, loan_file_id=loan_file.id
        )
        txn_contents = None if field_sets is None else [_txn_content(fs) for fs in field_sets]
        reshaped.append(
            _ReshapedDoc(
                document.document_type,
                refs,
                fields,
                field_sets,
                txn_contents,
                build_schedule_c(extracted, document.document_type),
                build_schedule_e(extracted, document.document_type),
                build_list_rows(extracted, document.document_type, loan_file_id=loan_file.id),
            )
        )

    # Pass 2: assign stable, content-derived document ids (with a duplicate tiebreak), aligned to the
    # documents/reshaped lists by input order.
    doc_ids = assign_content_ids(
        DOC_PREFIX,
        [
            _document_base(
                d.document_type, d.refs, d.fields, d.field_sets, txn_contents=d.txn_contents
            )
            for d in reshaped
        ],
    )
    return list(documents), reshaped, doc_ids


async def document_id_by_content_id(db: AsyncSession, loan_file: LoanFile) -> dict[str, UUID]:
    """Map each snapshot ``content_id`` back to its ``documents.id`` (LP-617).

    The snapshot deliberately carries NO database ids — that is what makes a `DocumentEntry`
    content-addressed and run-independent, and it should stay that way. But a finding that wants to
    point a processor AT a document needs the real id, and the two are only known together HERE, where
    `_reshape_and_assign_ids` zips the `Document` rows with the ids it derives from their content.

    Deliberately a SECOND reshape rather than a value threaded out of `build_snapshot`: the snapshot is
    built once near the start of a run and the findings are written at the end, so threading it would
    put a document-id map through the whole pipeline for one consumer. The cost is one extra read of
    the file's documents + current extractions — real, and small beside a run that spends minutes on
    model calls.

    THE KEYS CAN DRIFT, and the claim that they cannot was wrong (LP-620). This map is built from LIVE
    DB state at the END of a run, while the content ids it resolves were derived at the START, minutes
    of model calls earlier. Two consequences, both mild and both worth naming rather than assuming
    away:

    * a document uploaded, re-extracted or soft-deleted in that window — or a borrower renamed, since
      `belongs_to` feeds the id — has a different content id here, and the finding silently gets no
      link. A missing link, not a wrong one.
    * `assign_content_ids` folds a POSITIONAL occurrence index into the hash for byte-identical
      payloads, so if one of two duplicate documents is deleted mid-run the survivor inherits the
      deleted twin's id, and a finding derived from the deleted document resolves to the survivor's
      row. A link to a byte-identical twin, which is the same document by content.

    Neither is worth threading the map through the pipeline to close. Both are worth knowing before
    treating a missing link as a bug in the resolver.
    """
    documents, _reshaped, doc_ids = await _reshape_and_assign_ids(db, loan_file)
    return {content_id: doc.id for doc, content_id in zip(documents, doc_ids, strict=True)}


async def build_documents_section(db: AsyncSession, loan_file: LoanFile) -> list[DocumentEntry]:
    """Assemble the ``documents`` section for a loan file (active documents only).

    Reads each active, current document's extraction + stored borrower links. No
    extraction, no matching — a pure read + reshape. Each entry (and each transaction) is
    stamped with a stable, run-independent ``content_id`` (LP-312): documents get ids first,
    then each statement's transactions are scoped under their document's id.
    """
    _documents, reshaped, doc_ids = await _reshape_and_assign_ids(db, loan_file)
    entries: list[DocumentEntry] = []
    for document, d, doc_id in zip(_documents, reshaped, doc_ids, strict=True):
        entries.append(
            DocumentEntry(
                content_id=doc_id,
                document_type=d.document_type,
                belongs_to=d.refs or None,  # None when no borrower resolved
                fields=d.fields,
                transactions=build_transactions(
                    d.field_sets, document_content_id=doc_id, txn_contents=d.txn_contents
                ),
                schedule_c=d.schedule_c,  # LP-421 — None for every non-tax-return document
                schedule_e=d.schedule_e,
                lists=finalize_lists(
                    d.list_drafts, document_content_id=doc_id
                ),  # LP-437 — {} today
                # LP-463 — the marked-untyped section: the Tier 3 scoped free-extraction output, scrubbed of
                # any long identifier run so no raw account/SSN reaches the snapshot at rest. None for a
                # typed/catalog document. NEVER read by a deterministic rule (see DocumentEntry docstring).
                untyped_extraction=_scrub_untyped(document.generic_analysis),
            )
        )
    return entries


async def document_filenames_by_content_id(db: AsyncSession, loan_file: LoanFile) -> dict[str, str]:
    """Map each current document's stable ``content_id`` → its ``original_filename`` (LP-377-B).

    The read path uses this to resolve a governed finding's document subject (its ``subject_key`` is a
    document content-id, LP-312) to a filename a processor recognises — never the raw hash. Reuses the
    EXACT reshape+assign the snapshot uses (:func:`_reshape_and_assign_ids`), so the keys match the
    findings' subject_keys. A document whose content changed since its run gets a DIFFERENT id now and is
    simply absent from the map (the read path then falls back honestly — the finding's subject is gone /
    no longer in this form). Documents with no stored filename are omitted (same honest fallback).
    """
    documents, _reshaped, doc_ids = await _reshape_and_assign_ids(db, loan_file)
    return {
        doc_id: document.original_filename
        for document, doc_id in zip(documents, doc_ids, strict=True)
        if document.original_filename
    }


async def _links_by_document(
    db: AsyncSession, document_ids: list[UUID]
) -> dict[UUID, list[DocumentBorrowerLink]]:
    """All borrower links for the given documents, grouped by document (ONE query).

    Replaces a per-document call (an N+1). No soft-delete joins are needed here: the
    caller passes only active documents and filters refs to active borrowers.
    """
    if not document_ids:
        return {}
    rows = (
        (
            await db.execute(
                select(DocumentBorrowerLink)
                .where(DocumentBorrowerLink.document_id.in_(document_ids))
                # borrower_id is a deterministic tiebreak: equal-confidence links (a joint
                # document matched to both spouses) otherwise return in an unstable order.
                .order_by(DocumentBorrowerLink.confidence.desc(), DocumentBorrowerLink.borrower_id)
            )
        )
        .scalars()
        .all()
    )
    by_doc: dict[UUID, list[DocumentBorrowerLink]] = defaultdict(list)
    for link in rows:
        by_doc[link.document_id].append(link)
    return by_doc


async def _active_borrower_names(db: AsyncSession, loan_file_id: UUID) -> dict[UUID, str]:
    """Map active borrower id → resolved full name (for belongs_to)."""
    borrowers = (
        (
            await db.execute(
                only_active(select(Borrower).where(Borrower.loan_file_id == loan_file_id), Borrower)
            )
        )
        .scalars()
        .all()
    )
    return {b.id: b.full_name for b in borrowers}
