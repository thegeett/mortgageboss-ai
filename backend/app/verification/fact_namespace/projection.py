"""CrossSourceFacts projection (LP-118.6) — derive the legacy fact object from the namespace.

The 5 live deterministic cross-source rules (LP-115) read a :class:`CrossSourceFacts`. This
projects one from the new :class:`FactNamespace`, reproducing
:func:`app.services.cross_source_deterministic.build_cross_source_facts` **exactly** — the SAME 11
fields it populates, and (critically) leaving every other CrossSourceFacts field at its empty
default. The namespace is richer, but the projection is deliberately NARROW: populating a
currently-empty field (e.g. documented income, credit-report liabilities) would hand a **dormant**
rule its inputs and make it fire — which this ticket must not do. So the projection is byte-for-byte
the legacy shape; a regression test asserts equality.

Scope note (LP-118.6): the live cross-source path is intentionally left on the legacy builder this
ticket — this projection is the proven-equivalent seam LP-121 will switch the runner to, with no
change to live output.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from app.verification.cross_source.facts import CrossSourceFacts, ObligationRef, SourcedValue
from app.verification.fact_namespace.snapshot import FactNamespace

# The legacy key sets (identical to build_cross_source_facts).
_NAME_KEYS = ("full_name", "employee_name", "borrower_name", "name")
_ADDRESS_KEYS = ("address", "current_address", "residence_address")
_EMPLOYER_KEYS = ("employer_name", "employer")
_GIFT_LETTER_TYPES = ("gift_letter", "gift_funds")


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _first(fields: dict[str, str], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = fields.get(key)
        if value not in (None, ""):
            return value
    return None


def project_cross_source_facts(ns: FactNamespace) -> CrossSourceFacts:
    """Reproduce the legacy CrossSourceFacts from the namespace (identical 11-field shape)."""
    # Names: each borrower (application) + the first name-like field on each document.
    names: list[SourcedValue] = [
        SourcedValue(b.full_name, "application") for b in ns.borrowers if b.full_name
    ]
    # The legacy builder reads only VERIFIED documents (a current extraction with non-empty typed
    # fields) — i.e. services/cross_source._verified_documents. Match that subset exactly.
    verified = [doc for doc in ns.documents if doc.present and doc.fields]

    dl_address: SourcedValue | None = None
    documented_employers: list[str] = []
    for doc in verified:
        doc_type = doc.document_type or "document"
        name = _first(doc.fields, _NAME_KEYS)
        if name is not None:
            names.append(SourcedValue(name, doc_type))
        if doc_type == "drivers_license":
            addr = _first(doc.fields, _ADDRESS_KEYS)
            if addr is not None:
                dl_address = SourcedValue(addr, doc_type)  # last DL doc wins (legacy behaviour)
        emp = _first(doc.fields, _EMPLOYER_KEYS)
        if emp is not None:
            documented_employers.append(emp)

    # Stated income + employers (employment items only).
    stated_income = Decimal(0)
    income_item_count = 0
    stated_employers: list[str] = []
    for b in ns.borrowers:
        for item in b.income_items:
            if item.employment_income:
                income_item_count += 1
                amount = _to_decimal(item.monthly_amount.value)
                if amount is not None:
                    stated_income += amount
        stated_employers.extend(e.name for e in b.employers if e.name)

    stated_liabilities = tuple(
        ObligationRef(
            key=(li.holder_name or li.liability_type_raw or ""),
            amount=_to_decimal(li.monthly_payment.value),
            source="application",
        )
        for li in ns.liabilities
        if (li.holder_name or li.liability_type_raw)
    )

    gift_amount, gift_letter_present = _gift_facts(ns, verified)

    subject_address = ns.property.address.value if ns.property is not None else None

    return CrossSourceFacts(
        names=tuple(names),
        subject_property_address=subject_address,
        dl_address=dl_address,
        stated_income_monthly=stated_income if income_item_count else None,
        stated_employers=tuple(stated_employers),
        documented_employers=tuple(documented_employers),
        stated_employer_count=len(stated_employers) or None,
        income_item_count=income_item_count or None,
        stated_liabilities=stated_liabilities,
        gift_amount=gift_amount,
        gift_letter_present=gift_letter_present,
    )


def _gift_facts(ns: FactNamespace, verified: list[Any]) -> tuple[Decimal | None, bool | None]:
    """A stated gift's total + whether a gift-letter document is present (legacy ``_gift_facts``),
    checking the same VERIFIED-document subset the legacy builder used."""
    gift_total = Decimal(0)
    for asset in ns.assets:
        if asset.is_gift:
            amount = _to_decimal(asset.value.value)
            if amount is not None:
                gift_total += amount
    if gift_total <= 0:
        return None, None
    has_letter = any(doc.document_type in _GIFT_LETTER_TYPES for doc in verified)
    return gift_total, has_letter
