"""Synthetic MISMO variants for parser/import hardening (LP-57).

LP-51..56 were validated against ONE real file (``MISMO16940192.xml``). A parser
proven on a single example is fragile, so this builds **synthetic variants** of
that file — an FHA loan, a genuine second (distinct) borrower, missing optional
sections, an unsupported mortgage type, a zero-income deal, and HTML-wrapped XML —
to exercise the parser's tolerance against structural variation.

**Honest limitation:** these are *derived* from the one real file, not additional
real LOS exports. They confirm tolerance to the specific variations applied; they
do **not** exercise real-world variation a different LOS would produce (different
element ordering/namespaces, FHA-specific sections like UFMIP/MIP/case-number,
true co-borrower layouts). Real files — especially a real FHA file and a real
multi-borrower file — are still needed to fully harden. See ``docs/tickets/LP-57.md``.

Each helper takes the base fixture bytes and returns transformed bytes, so tests
stay anchored on the real file's shape while varying one thing at a time.
"""

from __future__ import annotations

import copy
from pathlib import Path

from app.mismo.parser import NS
from lxml import etree

FIXTURE = Path(__file__).parent.parent / "fixtures" / "mismo" / "MISMO16940192.xml"


def base_bytes() -> bytes:
    """The one real fixture, as bytes."""
    return FIXTURE.read_bytes()


def _root(raw: bytes) -> etree._Element:
    return etree.fromstring(raw)


def _borrower_party(root: etree._Element) -> etree._Element:
    parties = root.find(".//m:PARTIES", NS)
    assert parties is not None
    return next(
        p
        for p in parties.findall("m:PARTY", NS)
        if any(r.text == "Borrower" for r in p.findall(".//m:PartyRoleType", NS))
    )


def with_mortgage_type(raw: bytes, mortgage_type: str) -> bytes:
    """Set ``TERMS_OF_LOAN/MortgageType`` (e.g. ``"FHA"``, ``"VA"``)."""
    root = _root(raw)
    el = root.find(".//m:TERMS_OF_LOAN/m:MortgageType", NS)
    assert el is not None
    el.text = mortgage_type
    return etree.tostring(root)


def fha_variant(raw: bytes) -> bytes:
    """An FHA loan (MortgageType=FHA). Note: does NOT add FHA-specific sections."""
    return with_mortgage_type(raw, "FHA")


def multi_borrower_variant(raw: bytes) -> bytes:
    """Add a genuine SECOND borrower — distinct name, income, and classification.

    The co-borrower's name/income differ from the primary so a test can prove the
    parser attributes income/employers to the correct borrower (no cross-bleed).
    """
    root = _root(raw)
    parties = root.find(".//m:PARTIES", NS)
    assert parties is not None
    co = copy.deepcopy(_borrower_party(root))
    co.find(".//m:INDIVIDUAL/m:NAME/m:FirstName", NS).text = "Asha"
    co.find(".//m:INDIVIDUAL/m:NAME/m:LastName", NS).text = "Patel"
    co.find(".//m:INDIVIDUAL/m:NAME/m:FullName", NS).text = "Asha Patel"
    for amt in co.findall(".//m:CurrentIncomeMonthlyTotalAmount", NS):
        amt.text = "3333.00"
    cls = co.find(".//m:BORROWER_DETAIL/m:BorrowerClassificationType", NS)
    if cls is not None:
        cls.text = "Secondary"
    parties.append(co)
    return etree.tostring(root)


def missing_sections_variant(raw: bytes) -> bytes:
    """Drop optional sections (liabilities, assets, the property value) entirely."""
    root = _root(raw)
    for path in (".//m:LIABILITIES", ".//m:ASSETS"):
        el = root.find(path, NS)
        if el is not None:
            el.getparent().remove(el)
    val = root.find(".//m:SUBJECT_PROPERTY//m:PropertyEstimatedValueAmount", NS)
    if val is not None:
        val.getparent().remove(val)
    return etree.tostring(root)


def zero_income_variant(raw: bytes) -> bytes:
    """Remove all income items so the deal has zero stated income (a likely gap)."""
    root = _root(raw)
    for item in root.findall(".//m:CURRENT_INCOME_ITEM", NS):
        item.getparent().remove(item)
    return etree.tostring(root)


def html_wrapped(raw: bytes) -> bytes:
    """Wrap the XML in HTML (an email/LOS export island), as a real export might."""
    return b"<html><body><pre>" + raw + b"</pre></body></html>"
