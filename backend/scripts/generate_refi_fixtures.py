"""Generate the synthetic refinance MISMO fixtures (LP-101) from the purchase fixture.

The only real MISMO file is a Conventional PURCHASE (``MISMO16940192.xml``). This derives two
DE-IDENTIFIED refinance fixtures from it — a RATE/TERM and a CASH-OUT variant — so the refi path
can be tested end-to-end without a real refi export (which we don't have) and without any real PII.

The transform, applied deterministically (no randomness/dates — reproducible):

1. **De-identify** — every personal-identifier element (names, SSN, DOB, street address, email,
   phone) is overwritten with an obviously-synthetic value. Bank/employer names, city/state/zip,
   and account numbers are left as-is (not personal PII; realistic for the parser to chew on).
2. **Flip the purpose** — the subject loan's ``LoanPurposeType`` Purchase → Refinance.
3. **Drop purchase-specifics** — remove ``SalesContractAmount`` (a refinance has no sales contract);
   the appraised/valuation amount stays (the refi LTV basis).
4. **Add the refi cash-out determination** — a ``REFINANCE`` element under the subject LOAN carrying
   ``RefinanceCashOutDeterminationType`` (+ amount for cash-out) — exactly what LP-99 parses.
5. **Set the loan amount per variant** so each meaningfully exercises its LTV limit:
   - rate/term: 1,104,000 / 1,380,000 = **80% LTV** (passes the 97% purchase/rate-term cap);
   - cash-out:  1,173,000 / 1,380,000 = **85% LTV** (OVER the stricter 80% cash-out cap — proving
     LP-99's populated ``refinance_type`` drives the stricter limit; it would PASS the 97% cap).

**Grounded-starter test artifacts (validate-with-Priya):** a real refi LOS export may order/name
elements differently, carry FHA-specific refi sections, or mark the existing lien with a payoff
indicator we don't yet parse (see LP-101's surfaced DTI gap). Re-run: ``uv run python
scripts/generate_refi_fixtures.py``.
"""

from __future__ import annotations

from pathlib import Path

from lxml import etree

_M = "http://www.mismo.org/residential/2009/schemas"
_NS = {"m": _M}
_FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "mismo"
_SOURCE = _FIXTURES / "MISMO16940192.xml"

# Personal-identifier element local-names → their synthetic replacement. Everything here is
# obviously fake; nothing traces to a real person. Non-personal values (banks, employers, city/
# state/zip, account numbers) are intentionally NOT scrubbed — realistic parser input.
_PII_REPLACEMENTS: dict[str, str] = {
    "FirstName": "Robin",
    "MiddleName": "Q",
    "LastName": "Sample",
    "FullName": "Robin Q Sample",
    "TaxpayerIdentifierValue": "000000000",  # pragma: allowlist secret
    "BorrowerBirthDate": "1980-01-01",
    "AddressLineText": "742 Evergreen Terrace",
    "ContactPointEmailValue": "borrower@example.com",
    "ContactPointTelephoneValue": "5555550100",
}


def _localname(tag: object) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _deidentify(root: etree._Element) -> None:
    """Overwrite every personal-identifier element's text with a synthetic value (in place)."""
    for el in root.iter():
        replacement = _PII_REPLACEMENTS.get(_localname(el.tag))
        if replacement is not None and el.text is not None:
            el.text = replacement


def _subject_loan(root: etree._Element) -> etree._Element:
    loan = root.find(".//m:LOANS/m:LOAN", _NS)
    if loan is None:  # pragma: no cover - the fixture always has a subject loan
        raise SystemExit("no subject LOAN found in the source fixture")
    return loan


def _make_refi(*, cash_out: bool, base_loan_amount: str, cash_out_amount: str | None) -> bytes:
    """Build one refinance variant's XML bytes from the purchase fixture."""
    root = etree.fromstring(_SOURCE.read_bytes())
    _deidentify(root)

    loan = _subject_loan(root)

    # 2) Purpose → Refinance.
    purpose = loan.find(".//m:TERMS_OF_LOAN/m:LoanPurposeType", _NS)
    if purpose is None:  # pragma: no cover
        raise SystemExit("no LoanPurposeType in the subject loan")
    purpose.text = "Refinance"

    # 5) The variant's loan amount (drives the LTV against the 1,380,000 valuation). Keep the
    # NoteAmount in step with the base so the DTI's P&I and the LTV agree on one loan figure.
    for path in (".//m:TERMS_OF_LOAN/m:BaseLoanAmount", ".//m:TERMS_OF_LOAN/m:NoteAmount"):
        el = loan.find(path, _NS)
        if el is not None:
            el.text = base_loan_amount

    # 3) A refinance has no sales contract — drop it (the appraised/valuation amount stays).
    prop = root.find(".//m:COLLATERALS/m:COLLATERAL/m:SUBJECT_PROPERTY", _NS)
    if prop is not None:
        sca = prop.find(".//m:SalesContractAmount", _NS)
        if sca is not None:
            sca.getparent().remove(sca)

    # 4) The REFINANCE cash-out determination LP-99 parses (child of the subject LOAN).
    refinance = etree.SubElement(loan, f"{{{_M}}}REFINANCE")
    etree.SubElement(refinance, f"{{{_M}}}RefinanceCashOutDeterminationType").text = (
        "CashOut" if cash_out else "NoCashOut"
    )
    if cash_out_amount is not None:
        etree.SubElement(refinance, f"{{{_M}}}RefinanceCashOutAmount").text = cash_out_amount

    return bytes(etree.tostring(root, xml_declaration=True, encoding="UTF-8"))


def main() -> None:
    variants = {
        # rate/term: 80% LTV — passes the 97% purchase/rate-term cap.
        "refi_rate_term.xml": _make_refi(
            cash_out=False, base_loan_amount="1104000.00", cash_out_amount=None
        ),
        # cash-out: 85% LTV — OVER the stricter 80% cash-out cap (would pass the 97% cap).
        "refi_cash_out.xml": _make_refi(
            cash_out=True, base_loan_amount="1173000.00", cash_out_amount="150000.00"
        ),
    }
    for name, content in variants.items():
        # Trailing newline so the file is POSIX-clean (matches the end-of-file-fixer pre-commit
        # hook, keeping regeneration idempotent).
        (_FIXTURES / name).write_bytes(content + b"\n")
        print(f"wrote {name} ({len(content) + 1} bytes)")


if __name__ == "__main__":
    main()
