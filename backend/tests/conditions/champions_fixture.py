"""The Champions synthetic condition sheet, built as a real PDF (LP-906 section 3, spec §7.4).

⚠️ THIS FIXTURE IS AUTHORED, NOT EXTRACTED — the opposite of §7.1-7.3. Those were cut from the spec
with `sed` and `diff`-verified, so no transcription error was possible. §7.4 instead gives a TABLE of
28 section/number pairs with a structural note each ("the long one, ~9 lines", "five numbered items",
"one line: Subject to Condo Approval."), and full prose for only rows 71 and 268 — which appear in
the §6 centre-rule example and are copied here exactly.

The other 26 texts are written to match each stated property. So `assert verbatim_text == "…"`
compares this module's prose against itself: it proves the centre rule reassembled SOMETHING, not
that it reassembled it correctly. What genuinely tests the algorithm is structural — 28 rows in the
spec's order, the right section per row, 206 reassembled across the page break with `crossed_page`,
no page furniture in any row, no unassigned lines — and those are the assertions that carry weight.

⚠️ WHY A REAL PDF AND NOT TEXT. Champions prints each condition's number VERTICALLY CENTRED on its
row, so the number lands on the first line, a middle line, or a line of its own depending only on how
many lines the text wrapped to. The reader recovers a row's extent from `2 * number.y - bottom`. Only
real word boxes carry that geometry, so a text fixture would exercise a different path from the one
that runs in production.

Built with pymupdf — already a runtime dependency, and seven existing test modules build PDFs the
same way (`tests/services/test_field_boxes.py` places text at computed `(x, y)` exactly like this).
Nothing new is added, so the spec's "STOP AND ASK if it would be a new runtime dependency" does not
fire.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass

import pymupdf

# --------------------------------------------------------------------------- #
# Page geometry — US Letter, in points
# --------------------------------------------------------------------------- #

PAGE_WIDTH = 612.0
PAGE_HEIGHT = 792.0

#: The number column and the text column. The gap between them is what makes a row number's `x0`
#: separable from body text, which is how the reader recognises a number at all.
NUMBER_X = 54.0
TEXT_X = 108.0
#: Second column of the header block's label/value pairs.
RIGHT_LABEL_X = 320.0
VALUE_OFFSET = 132.0

BODY_TOP_FIRST = 300.0
BODY_TOP_CONTINUED = 96.0
BODY_BOTTOM = 720.0

LINE_HEIGHT = 12.0
FONT_SIZE = 8.5
WRAP_AT = 100

#: §7.4 REQUIRES row 206 to split across the page break. Two lines stay on the first page, so the
#: remainder is unambiguously a continuation rather than a stray line.
SPLIT_ROW_NUMBER = "206"
SPLIT_ROW_LINES_BEFORE_BREAK = 2


# --------------------------------------------------------------------------- #
# Page furniture — repeated on EVERY page, and none of it may reach a row
# --------------------------------------------------------------------------- #

TITLE = "Conditional Approval Certificate"
LOAN_LINE = "Date: 9/11/26        Loan #: 4400123456"
FOOTER_LEFT = "Example Funding, LLC 100 Sample Rd Suite 1        Date: 9/11/26 6:27:45 PM"
FOOTER_RIGHT = "Mesa AZ 85201 | NMLS #0000001"

#: Page 1's header. A bare string is a section title on its own line; a 4-tuple is two label/value
#: pairs side by side, which is how Champions prints them.
#:
#: ⚠️ `Title Commitment Exp` / `Date:` IS DELIBERATELY SPLIT ACROSS TWO LINES. Spec rule 2 calls out
#: exactly this wrapped label as something the reader must join, so the fixture has to contain it —
#: a fixture that printed it on one line would leave that rule asserted by nothing.
HEADER_BLOCK: tuple[str | tuple[str, str, str, str], ...] = (
    "Approval Information",
    ("Approval Exp Date:", "01/07/2027", "Rate Lock Exp:", "12/10/2026"),
    ("Credit Exp Date:", "01/07/2027", "Appraisal Exp Date:", "12/27/2026"),
    ("Asset Exp Date:", "11/30/2026", "Title Exp Date:", "12/15/2026"),
    ("CPL Exp Date:", "12/15/2026", "", ""),
    "Title Commitment Exp",
    ("Date:", "12/15/2026", "", ""),
    "Account Executive",
    ("Name:", "Omar Example", "Phone:", "(555) 010-0144"),
    ("Email:", "omar.example@example-funding.test", "", ""),
    "Underwriter",
    ("Name:", "Uma Writer", "Phone:", "(555) 010-0155"),
    ("Email:", "uma.writer@example-funding.test", "", ""),
    "Account Manager",
    ("Name:", "Ada Manager", "Phone:", "(555) 010-0166"),
    ("Email:", "ada.manager@example-funding.test", "", ""),
)

#: What the reader must produce from the block above (spec rule 3's key names).
EXPECTED_EXPIRY: dict[str, str] = {
    "approval": "2027-01-07",
    "rate_lock": "2026-12-10",
    "credit": "2027-01-07",
    "appraisal": "2026-12-27",
    "asset": "2026-11-30",
    "title": "2026-12-15",
    "cpl": "2026-12-15",
    "title_commitment": "2026-12-15",
}

EXPECTED_TEAM: tuple[tuple[str, str], ...] = (
    ("Account Executive", "Omar Example"),
    ("Underwriter", "Uma Writer"),
    ("Account Manager", "Ada Manager"),
)


# --------------------------------------------------------------------------- #
# The 28 rows, in the spec's order
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Section:
    heading: str
    rows: tuple[tuple[str, str], ...]


#: ⚠️ 71 AND 268 ARE THE SPEC'S OWN WORDS, copied from the §6 centre-rule example. Every other text
#: is authored here to the structural note §7.4 gives for that row.
SECTIONS: tuple[Section, ...] = (
    Section(
        "Prior to Docs - Assets",
        (
            (
                "71",
                "Earnest money deposit verification in the amount of $3,000 is required with proof "
                "of receipt from settlement agent. (1) Provide copy of check/ACH with bank "
                "statement showing check clearing account -AND- (2) proof of receipt from escrow.",
            ),
            (
                "268",
                "Provide most recent bank statements with all pages to meet reserves and cash to "
                "close. Loan requires estimated assets of $115,367.50 (cash to close $100,390.72 & "
                "reserves $14,976.78).",
            ),
            (
                "414",
                "Account Manager to order a written Verification of Deposit for the account ending "
                "4417 and provide the completed form prior to docs.",
            ),
        ),
    ),
    Section(
        "Prior to Docs - Borrower",
        (
            (
                "34",
                "Provide evidence of completed homeownership counseling for all borrowers. The $75 "
                "counseling fee must appear on the final settlement statement and be paid outside "
                "of closing if not financed.",
            ),
            (
                "245",
                "The residence history reflects a rent-free living arrangement that conflicts with "
                "the documentation in file. The initial application lists the borrower at 14 Sample "
                "Court for the most recent twenty-four months, while the credit report reflects a "
                "mortgage tradeline for a property at 88 Example Crossing Lane over the same "
                "period. Provide a written letter of explanation signed by all borrowers addressing "
                "the discrepancy, together with either (a) a rent-free letter from the property "
                "owner confirming the arrangement and the period covered, or (b) twelve months of "
                "cancelled cheques or bank debits evidencing housing payments. If the borrower "
                "retained the departing residence, provide the current mortgage statement, the "
                "homeowner's insurance declarations page and evidence that taxes and insurance are "
                "escrowed.",
            ),
        ),
    ),
    Section(
        "Prior to Docs - Closing",
        (
            (
                "38",
                "Provide the following prior to document preparation: 1 Final signed and dated loan "
                "application for all borrowers reflecting the current terms. 2. Evidence that the "
                "settlement agent is approved and appears on the current approved closing agent "
                "list.",
            ),
        ),
    ),
    Section(
        "Prior to Docs - Collateral",
        (
            (
                "54",
                "Provide the full appraisal report with all addenda, photographs and the completed "
                "1004MC market conditions addendum.",
            ),
            ("55", "Subject to Condo Approval."),
            (
                "179",
                "The appraisal reflects an unpermitted addition to the rear of the subject "
                "property. Provide evidence that the addition was completed with the appropriate "
                "municipal permits, or an appraiser's addendum confirming that the addition "
                "conforms to local building standards and that no adverse effect on marketability "
                "results. If permits cannot be produced, the appraised value must be supported "
                "without the addition.",
            ),
            (
                "193",
                "Provide a copy of the recorded plat map and confirmation that the subject parcel "
                "has legal access to a publicly maintained road.",
            ),
            ("261", "Provide evidence of flood zone determination for the subject property."),
        ),
    ),
    Section(
        "Prior to Docs - Compliance",
        (("133", "Provide the signed and dated Affiliated Business Arrangement disclosure."),),
    ),
    Section(
        "Prior to Docs - Identification",
        (
            (
                "286",
                "Provide a legible copy of an unexpired government-issued photo identification.",
            ),
        ),
    ),
    Section(
        "Prior to Docs - Insurance",
        (
            (
                "206",
                "Provide an updated homeowner's insurance declarations page reflecting the correct "
                "mortgagee clause, the full replacement cost coverage amount, and a policy "
                "effective date on or before the anticipated closing date. The deductible may not "
                "exceed the greater of $2,500 or one percent of the dwelling coverage amount, and "
                "the policy must remain in force for a minimum of twelve months from the date of "
                "closing with the first year's premium paid in full at or before settlement.",
            ),
            (
                "209",
                "If the subject property is located within a special flood hazard area, provide a "
                "flood insurance policy or application with paid receipt meeting minimum coverage "
                "requirements.",
            ),
        ),
    ),
    Section(
        "Prior to Docs - Loan",
        (
            (
                "171",
                "**AM to pull SSN Verification. Provide the completed verification in file prior to "
                "document preparation.",
            ),
            (
                "292",
                "Provide a written letter of explanation for all credit inquiries appearing on the "
                "credit report within the ninety days preceding the application date, confirming "
                "whether any new debt was obtained.",
            ),
        ),
    ),
    Section(
        "Prior to Docs - Title",
        (
            (
                "284",
                "Provide an updated title commitment reflecting the following: 1. The vesting "
                "matches the loan application exactly. 2. All prior liens are shown as satisfied or "
                "scheduled for payoff at closing. 3. The legal description matches the appraisal. "
                "4. The twenty-four month chain of title is disclosed. 5. Any exceptions affecting "
                "marketability are removed or affirmatively insured.",
            ),
            (
                "285",
                "Provide the Closing Protection Letter naming the lender and covering the "
                "settlement agent for this transaction.",
            ),
        ),
    ),
    Section(
        "Prior to Funding - Closing",
        (
            (
                "45",
                "Provide the final executed Closing Disclosure reflecting the terms of the note and "
                "signed by all borrowers.",
            ),
            (
                "94",
                "Provide the final settlement statement signed by the settlement agent and all "
                "parties to the transaction.",
            ),
            (
                "291",
                "Provide evidence that the wire instructions were verified directly with the "
                "settlement agent by telephone using an independently sourced number.",
            ),
            (
                "301",
                "Provide the fully executed note and security instrument with all riders applicable "
                "to the subject property.",
            ),
            (
                "379",
                "Provide the funding authorisation signed by the closer confirming that all prior "
                "to funding conditions have been satisfied.",
            ),
            (
                "380",
                "Provide evidence that the borrower's funds to close were received by the "
                "settlement agent in cleared funds prior to disbursement.",
            ),
        ),
    ),
    Section(
        "Prior to Funding - Credit",
        (
            (
                "637",
                "Provide a refreshed credit report or gap credit supplement dated within ten days "
                "of funding confirming no new debt has been obtained since application.",
            ),
        ),
    ),
    Section(
        "Prior to Funding - Disclosure",
        (
            (
                "260",
                "Provide the signed and dated Right of Rescission notice for all parties with an "
                "ownership interest in the subject property.",
            ),
        ),
    ),
    Section(
        "Prior to Funding - Loan",
        (
            (
                "66",
                "Document expiration date: Housing History: TBD; Income NA; Credit Report: "
                "01/07/2027; Assets: 11/30/2026; Appraisal: 12/27/2026; Title: 12/15/2026.",
            ),
        ),
    ),
)


def all_rows() -> tuple[tuple[str, str, str], ...]:
    """Every row as `(section heading, number, full text)`, in the spec's order.

    This IS the mapping a reviewer checks against §7.4's table: 28 entries, the section each belongs
    to, and the order they must come back in.
    """
    return tuple(
        (section.heading, number, text) for section in SECTIONS for number, text in section.rows
    )


# --------------------------------------------------------------------------- #
# Building the PDF
# --------------------------------------------------------------------------- #


def _draw_furniture(page: pymupdf.Page) -> None:
    """Title/loan header and both footer lines, on EVERY page.

    Rule 1's page-furniture filter is only genuinely exercised because this repeats — a fixture that
    printed it once would leave the filter asserted by a single page nobody re-checked.
    """
    page.insert_text((NUMBER_X, 48.0), TITLE, fontsize=11)
    page.insert_text((NUMBER_X, 64.0), LOAN_LINE, fontsize=FONT_SIZE)
    page.insert_text((NUMBER_X, PAGE_HEIGHT - 48.0), FOOTER_LEFT, fontsize=7.5)
    page.insert_text((NUMBER_X, PAGE_HEIGHT - 36.0), FOOTER_RIGHT, fontsize=7.5)


def _draw_header_block(page: pymupdf.Page) -> None:
    """Page 1's approval information and the three contacts, in two columns."""
    y = 96.0
    for entry in HEADER_BLOCK:
        if isinstance(entry, str):
            page.insert_text((NUMBER_X, y), entry, fontsize=9)
        else:
            left_label, left_value, right_label, right_value = entry
            page.insert_text((NUMBER_X, y), left_label, fontsize=FONT_SIZE)
            if left_value:
                page.insert_text((NUMBER_X + VALUE_OFFSET, y), left_value, fontsize=FONT_SIZE)
            if right_label:
                page.insert_text((RIGHT_LABEL_X, y), right_label, fontsize=FONT_SIZE)
            if right_value:
                page.insert_text((RIGHT_LABEL_X + VALUE_OFFSET, y), right_value, fontsize=FONT_SIZE)
        y += LINE_HEIGHT


def build_champions_pdf() -> bytes:
    """The §7.4 sheet: 28 rows, numbers vertically centred, row 206 split across the page break."""
    document = pymupdf.open()
    page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    _draw_furniture(page)
    _draw_header_block(page)
    y = BODY_TOP_FIRST

    def new_page() -> float:
        nonlocal page
        page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        _draw_furniture(page)
        return BODY_TOP_CONTINUED

    def place(number: str, lines: list[str], top: float) -> float:
        """Text lines at the text column, with the number centred on them (the centre rule's input)."""
        cursor = top
        for line in lines:
            page.insert_text((TEXT_X, cursor), line, fontsize=FONT_SIZE)
            cursor += LINE_HEIGHT
        page.insert_text((NUMBER_X, (top + cursor - LINE_HEIGHT) / 2.0), number, fontsize=FONT_SIZE)
        return cursor

    for section in SECTIONS:
        if y + LINE_HEIGHT * 4 > BODY_BOTTOM:
            y = new_page()
        page.insert_text((NUMBER_X + 6.0, y), section.heading, fontsize=9)
        y += LINE_HEIGHT * 1.5

        for number, text in section.rows:
            lines = textwrap.wrap(text, WRAP_AT)

            if number == SPLIT_ROW_NUMBER:
                # ⚠️ THE SPLIT HAPPENS AT THE PAGE BOTTOM, as a real page break does. An earlier
                # version broke mid-page, which produced a "page break" with 400pt of blank space
                # above the footer — the reader would still have coped, but the fixture would have
                # been testing a shape no renderer emits.
                y = max(y, BODY_BOTTOM - LINE_HEIGHT * SPLIT_ROW_LINES_BEFORE_BREAK)
                head = lines[:SPLIT_ROW_LINES_BEFORE_BREAK]
                tail = lines[SPLIT_ROW_LINES_BEFORE_BREAK:]
                # The number centres on the lines that remain on THIS page, which is what a renderer
                # producing a split row actually does.
                place(number, head, y)
                y = new_page()
                for line in tail:
                    page.insert_text((TEXT_X, y), line, fontsize=FONT_SIZE)
                    y += LINE_HEIGHT
                y += LINE_HEIGHT * 0.5
                continue

            if y + LINE_HEIGHT * len(lines) > BODY_BOTTOM:
                y = new_page()
            y = place(number, lines, y) + LINE_HEIGHT * 0.5

    return bytes(document.tobytes())
