"""Deterministic MISMO 3.4 parser (LP-51) — lxml/XPath, tolerant + exact.

MISMO is a standardized, machine-parseable schema and the stated financial data
is the **source-of-truth baseline** (the stated side of stated-vs-verified), so
it is parsed **deterministically** (not by AI — an AI misread would corrupt the
baseline). Values are read **exactly** (``Decimal`` for money/rates, ``date`` for
dates, the SSN verbatim).

The parser is **tolerant**: any missing/optional element becomes ``None`` (or an
empty list) with a ``parse_warning`` for needed-now fields — it never crashes on
structural variation. It accepts both raw XML and HTML-wrapped XML (the embedded
``MESSAGE`` island is extracted first). Validation failures (not XML / not MISMO)
raise :class:`MismoParseError` with a safe message.

Output is :class:`~app.mismo.schema.ParsedMismo` — a **typed core** plus a
**catch-all** of every other leaf in the deal (grouped by section), so nothing is
lost. AI-fallback for non-compliant files is a **documented future option**, not
built here.

**Logging is metadata-only**: counts + source format + warning count, never the
SSN, names, amounts, or the raw content.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

import structlog
from lxml import etree

from app.mismo.schema import (
    CatchAllField,
    CatchAllSection,
    ParsedAsset,
    ParsedBorrower,
    ParsedIncomeItem,
    ParsedLiability,
    ParsedLoan,
    ParsedMismo,
    ParsedProperty,
)

logger = structlog.get_logger(__name__)

# Namespaces declared in the real file (MISMO default + the DU/ULAD/xlink exts).
NS: dict[str, str] = {
    "m": "http://www.mismo.org/residential/2009/schemas",
    "DU": "http://www.datamodelextension.org/Schema/DU",
    "ULAD": "http://www.datamodelextension.org/Schema/ULAD",
    "xlink": "http://www.w3.org/1999/xlink",
}

# A generous cap so a hostile/huge file can't exhaust memory before we reject it.
_MAX_BYTES = 25 * 1024 * 1024


class MismoParseError(Exception):
    """Content can't be parsed as MISMO. Carries a safe, user-facing message."""


# --------------------------------------------------------------------------- #
# Tolerant coercion (a bad/missing value → None, never a crash)
# --------------------------------------------------------------------------- #


def _to_decimal(value: str | None) -> Decimal | None:
    if value is None or not value.strip():
        return None
    try:
        return Decimal(value.strip())
    except (InvalidOperation, ValueError):
        return None


def _to_date(value: str | None) -> date | None:
    if value is None or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _to_int(value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    try:
        return int(value.strip())
    except ValueError:
        return None


def _to_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    v = value.strip().lower()
    if v in {"true", "y", "yes", "1"}:
        return True
    if v in {"false", "n", "no", "0"}:
        return False
    return None


# --------------------------------------------------------------------------- #
# Parse context — tracks which leaves the typed core consumed, so the catch-all
# can capture exactly "everything else" (nothing dropped, no double-count).
# --------------------------------------------------------------------------- #


class _Ctx:
    def __init__(self, tree: etree._ElementTree) -> None:
        self._tree = tree
        self.consumed: set[str] = set()
        self.warnings: list[str] = []

    def consume(self, el: etree._Element | None) -> None:
        """Mark an element's stable path as consumed (kept out of the catch-all)."""
        if el is not None:
            self.consumed.add(self._tree.getpath(el))

    def text(self, el: etree._Element, xpath: str) -> str | None:
        """First text match for ``xpath`` under ``el`` (consumed). ``None`` if absent."""
        found = el.find(xpath, NS)
        if found is None:
            return None
        self.consume(found)
        return found.text.strip() if found.text else None


# --------------------------------------------------------------------------- #
# HTML-wrapped extraction
# --------------------------------------------------------------------------- #


def _extract_xml(raw: bytes) -> tuple[bytes, str]:
    """Return ``(xml_bytes, source_format)``.

    Raw XML is returned as-is (``"xml"``). If the content is HTML wrapping the
    MISMO XML, the embedded ``<MESSAGE …>…</MESSAGE>`` island is sliced out
    (deterministic, namespace-agnostic) and returned (``"html"``).
    """
    head = raw[:512].lstrip().lower()
    if head.startswith(b"<?xml") or head.startswith(b"<message"):
        return raw, "xml"

    # HTML-wrapped: locate the MESSAGE element by byte offsets. We match the
    # opening tag (with or without attributes) and the matching close tag.
    lowered = raw.lower()
    start = lowered.find(b"<message")
    end = lowered.rfind(b"</message>")
    if start == -1 or end == -1 or end <= start:
        raise MismoParseError("File is not a MISMO message")
    end += len(b"</message>")
    return raw[start:end], "html"


# --------------------------------------------------------------------------- #
# Typed-core parsers (all tolerant)
# --------------------------------------------------------------------------- #


def _is_borrower(party: etree._Element) -> bool:
    return any(role.text == "Borrower" for role in party.findall(".//m:PartyRoleType", NS))


def _parse_borrower(party: etree._Element, ctx: _Ctx) -> ParsedBorrower:
    detail = "m:ROLES/m:ROLE/m:BORROWER/m:BORROWER_DETAIL"

    # SSN: TAXPAYER_IDENTIFIER where the type is SocialSecurityNumber. Consume the
    # value element so the (sensitive) SSN never lands in the catch-all.
    ssn: str | None = None
    for tid in party.findall(".//m:TAXPAYER_IDENTIFIER", NS):
        tid_type = tid.find("m:TaxpayerIdentifierType", NS)
        tid_value = tid.find("m:TaxpayerIdentifierValue", NS)
        if tid_type is not None and tid_type.text == "SocialSecurityNumber":
            ctx.consume(tid_type)
            ctx.consume(tid_value)
            ssn = tid_value.text.strip() if (tid_value is not None and tid_value.text) else None
            break

    income_items: list[ParsedIncomeItem] = []
    for item in party.findall(".//m:CURRENT_INCOME_ITEM/m:CURRENT_INCOME_ITEM_DETAIL", NS):
        income_items.append(
            ParsedIncomeItem(
                monthly_amount=_to_decimal(ctx.text(item, "m:CurrentIncomeMonthlyTotalAmount")),
                income_type=ctx.text(item, "m:IncomeType"),
                employment_income=_to_bool(ctx.text(item, "m:EmploymentIncomeIndicator")),
            )
        )

    employers: list[str] = []
    for emp in party.findall(".//m:EMPLOYERS/m:EMPLOYER", NS):
        name = ctx.text(emp, ".//m:FullName")
        if name:
            employers.append(name)

    declarations: dict[str, str] = {}
    decl_detail = party.find(".//m:DECLARATION/m:DECLARATION_DETAIL", NS)
    if decl_detail is not None:
        for child in decl_detail:
            local = etree.QName(child).localname
            if child.text and child.text.strip():
                declarations[local] = child.text.strip()
                ctx.consume(child)

    return ParsedBorrower(
        first_name=ctx.text(party, ".//m:INDIVIDUAL/m:NAME/m:FirstName"),
        last_name=ctx.text(party, ".//m:INDIVIDUAL/m:NAME/m:LastName"),
        full_name=ctx.text(party, ".//m:INDIVIDUAL/m:NAME/m:FullName"),
        ssn=ssn,
        birth_date=_to_date(ctx.text(party, f"{detail}/m:BorrowerBirthDate")),
        marital_status=ctx.text(party, f"{detail}/m:MaritalStatusType"),
        dependent_count=_to_int(ctx.text(party, f"{detail}/m:DependentCount")),
        classification=ctx.text(party, f"{detail}/m:BorrowerClassificationType"),
        email=ctx.text(party, ".//m:CONTACT_POINT_EMAIL/m:ContactPointEmailValue"),
        phone=ctx.text(party, ".//m:CONTACT_POINT_TELEPHONE/m:ContactPointTelephoneValue"),
        address_line=ctx.text(party, ".//m:ADDRESSES/m:ADDRESS/m:AddressLineText"),
        city=ctx.text(party, ".//m:ADDRESSES/m:ADDRESS/m:CityName"),
        state=ctx.text(party, ".//m:ADDRESSES/m:ADDRESS/m:StateCode"),
        postal_code=ctx.text(party, ".//m:ADDRESSES/m:ADDRESS/m:PostalCode"),
        address_type=ctx.text(party, ".//m:ADDRESSES/m:ADDRESS/m:AddressType"),
        citizenship=ctx.text(party, ".//m:DECLARATION_DETAIL/m:CitizenshipResidencyType"),
        income_items=income_items,
        employers=employers,
        declarations=declarations,
    )


def _parse_borrowers(deal: etree._Element, ctx: _Ctx) -> list[ParsedBorrower]:
    borrowers = [_parse_borrower(p, ctx) for p in deal.findall(".//m:PARTY", NS) if _is_borrower(p)]
    if not borrowers:
        ctx.warnings.append("No borrower party found (PartyRoleType == Borrower).")
    for i, b in enumerate(borrowers):
        if not (b.full_name or b.last_name):
            ctx.warnings.append(f"Borrower #{i + 1} is missing a name.")
    return borrowers


def _parse_loan(deal: etree._Element, ctx: _Ctx) -> ParsedLoan | None:
    loan = deal.find(".//m:LOANS/m:LOAN", NS)
    if loan is None:
        ctx.warnings.append("No LOAN found.")
        return None
    parsed = ParsedLoan(
        base_loan_amount=_to_decimal(ctx.text(loan, ".//m:TERMS_OF_LOAN/m:BaseLoanAmount")),
        note_amount=_to_decimal(ctx.text(loan, ".//m:TERMS_OF_LOAN/m:NoteAmount")),
        note_rate_percent=_to_decimal(ctx.text(loan, ".//m:TERMS_OF_LOAN/m:NoteRatePercent")),
        loan_purpose=ctx.text(loan, ".//m:TERMS_OF_LOAN/m:LoanPurposeType"),
        mortgage_type=ctx.text(loan, ".//m:TERMS_OF_LOAN/m:MortgageType"),
        lien_priority=ctx.text(loan, ".//m:TERMS_OF_LOAN/m:LienPriorityType"),
        amortization_type=ctx.text(
            loan, ".//m:AMORTIZATION/m:AMORTIZATION_RULE/m:AmortizationType"
        ),
        amortization_months=_to_int(ctx.text(loan, ".//m:LoanAmortizationPeriodCount")),
        application_received_date=_to_date(
            ctx.text(loan, ".//m:LOAN_DETAIL/m:ApplicationReceivedDate")
        ),
    )
    if parsed.base_loan_amount is None:
        ctx.warnings.append("Loan is missing a base loan amount.")
    return parsed


def _parse_property(deal: etree._Element, ctx: _Ctx) -> ParsedProperty | None:
    prop = deal.find(".//m:COLLATERALS/m:COLLATERAL/m:SUBJECT_PROPERTY", NS)
    if prop is None:
        ctx.warnings.append("No SUBJECT_PROPERTY found.")
        return None
    parsed = ParsedProperty(
        address_line=ctx.text(prop, ".//m:ADDRESS/m:AddressLineText"),
        city=ctx.text(prop, ".//m:ADDRESS/m:CityName"),
        state=ctx.text(prop, ".//m:ADDRESS/m:StateCode"),
        postal_code=ctx.text(prop, ".//m:ADDRESS/m:PostalCode"),
        county=ctx.text(prop, ".//m:ADDRESS/m:CountyName"),
        estimated_value=_to_decimal(ctx.text(prop, ".//m:PropertyEstimatedValueAmount")),
        valuation_amount=_to_decimal(ctx.text(prop, ".//m:PropertyValuationAmount")),
        sales_contract_amount=_to_decimal(ctx.text(prop, ".//m:SalesContractAmount")),
        usage_type=ctx.text(prop, ".//m:PropertyUsageType"),
        attachment_type=ctx.text(prop, ".//m:AttachmentType"),
        construction_method=ctx.text(prop, ".//m:ConstructionMethodType"),
        financed_unit_count=_to_int(ctx.text(prop, ".//m:FinancedUnitCount")),
    )
    if parsed.estimated_value is None:
        ctx.warnings.append("Subject property is missing an estimated value.")
    return parsed


def _parse_liabilities(deal: etree._Element, ctx: _Ctx) -> list[ParsedLiability]:
    out: list[ParsedLiability] = []
    for liab in deal.findall(".//m:LIABILITIES/m:LIABILITY", NS):
        out.append(
            ParsedLiability(
                liability_type=ctx.text(liab, ".//m:LIABILITY_DETAIL/m:LiabilityType"),
                monthly_payment=_to_decimal(
                    ctx.text(liab, ".//m:LIABILITY_DETAIL/m:LiabilityMonthlyPaymentAmount")
                ),
                unpaid_balance=_to_decimal(
                    ctx.text(liab, ".//m:LIABILITY_DETAIL/m:LiabilityUnpaidBalanceAmount")
                ),
                holder_name=ctx.text(liab, ".//m:LIABILITY_HOLDER//m:FullName"),
            )
        )
    return out


def _parse_assets(deal: etree._Element, ctx: _Ctx) -> list[ParsedAsset]:
    out: list[ParsedAsset] = []
    for asset in deal.findall(".//m:ASSETS/m:ASSET", NS):
        out.append(
            ParsedAsset(
                asset_type=ctx.text(asset, ".//m:ASSET_DETAIL/m:AssetType"),
                value=_to_decimal(
                    ctx.text(asset, ".//m:ASSET_DETAIL/m:AssetCashOrMarketValueAmount")
                ),
                holder_name=ctx.text(asset, ".//m:ASSET_HOLDER//m:FullName"),
            )
        )
    return out


# --------------------------------------------------------------------------- #
# Catch-all — every other leaf in the deal, grouped by section. Nothing dropped.
# --------------------------------------------------------------------------- #


def _section_label(tree: etree._ElementTree, parent: etree._Element, deal: etree._Element) -> str:
    """A readable section key: the local-names from DEAL down to ``parent``."""
    parts: list[str] = []
    node: etree._Element | None = parent
    while node is not None and node is not deal:
        parts.append(etree.QName(node).localname)
        node = node.getparent()
    parts.reverse()
    return "/".join(parts) if parts else "DEAL"


def _parse_catch_all(
    deal: etree._Element, tree: etree._ElementTree, consumed: set[str]
) -> list[CatchAllSection]:
    """Capture every non-consumed leaf under the deal, grouped by its section."""
    grouped: dict[str, list[CatchAllField]] = {}
    order: list[str] = []
    for el in deal.iter():
        if len(el):  # not a leaf (has element children)
            continue
        if not (el.text and el.text.strip()):
            continue
        if tree.getpath(el) in consumed:
            continue
        parent = el.getparent()
        if parent is None:
            continue
        section = _section_label(tree, parent, deal)
        if section not in grouped:
            grouped[section] = []
            order.append(section)
        grouped[section].append(
            CatchAllField(label=etree.QName(el).localname, value=el.text.strip())
        )
    return [CatchAllSection(section=s, fields=grouped[s]) for s in order]


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def parse_mismo(content: bytes | str) -> ParsedMismo:
    """Parse MISMO 3.4 XML (or HTML-wrapped XML) into a :class:`ParsedMismo`.

    Raises :class:`MismoParseError` (safe message) when the content is not valid
    XML or not a MISMO message. Missing optional/required data does **not** raise:
    a partial parse is returned with ``parse_warnings`` listing what's missing.
    """
    raw = content.encode("utf-8") if isinstance(content, str) else content
    if len(raw) > _MAX_BYTES:
        raise MismoParseError("File is too large to parse")

    xml_bytes, source_format = _extract_xml(raw)

    # Disable entity resolution / network access (XXE-safe); recover=False so
    # genuinely malformed XML is rejected, not silently "fixed".
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
    try:
        root = etree.fromstring(xml_bytes, parser=parser)
    except etree.XMLSyntaxError as exc:
        raise MismoParseError("File is not valid XML") from exc

    if etree.QName(root).localname != "MESSAGE":
        raise MismoParseError("File is not a MISMO message")
    deal = root.find(".//m:DEAL", NS)
    if deal is None:
        raise MismoParseError("MISMO file has no DEAL")

    tree = root.getroottree()
    ctx = _Ctx(tree)

    borrowers = _parse_borrowers(deal, ctx)
    loan = _parse_loan(deal, ctx)
    prop = _parse_property(deal, ctx)
    liabilities = _parse_liabilities(deal, ctx)
    assets = _parse_assets(deal, ctx)
    catch_all = _parse_catch_all(deal, tree, ctx.consumed)

    # Metadata-only logging — NEVER the SSN, names, amounts, or raw content.
    logger.info(
        "mismo_parsed",
        source_format=source_format,
        borrowers=len(borrowers),
        liabilities=len(liabilities),
        assets=len(assets),
        catch_all_sections=len(catch_all),
        warnings=len(ctx.warnings),
    )

    return ParsedMismo(
        borrowers=borrowers,
        loan=loan,
        property=prop,
        liabilities=liabilities,
        assets=assets,
        catch_all=catch_all,
        parse_warnings=ctx.warnings,
        source_format=source_format,
    )
