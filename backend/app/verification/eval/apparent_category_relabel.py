"""LP-379-F — map Priya's free-text apparent_category labels onto the LP-379-E enum (PROPOSED; Priya confirms).

Her 50 held `txn.apparent_category` labels are free text ("transfer to some one", "Credit card payment") the
OLD enum could not hold. LP-379-E widened the enum; this translates her words to enum values so the held
labels can score — **but only where the transaction DESCRIPTION supports the category**. The AI sees the
(PII-redacted, AS-1) memo, NOT Priya's amount-based judgment or the un-redacted file she opened via LP-379-C's
real filenames.

THE GATE-OF-RECORD FINDING: 30 of the 50 labels sit on the SAME memo — "CARD PURCHASE / PAYMENT" — which
carries no payee. Priya gave those 30 eight different categories (credit-card payment, mortgage, a transfer to
a friend, an At&t bill, a fee…) from the AMOUNTS + the real file. LP-379-E's prompt CORRECTLY tells the AI to
categorize from the payee in the description, NOT the amount — so the AI cannot (and should not) reproduce her
call. Scoring those would measure the model against a judgment the prompt forbids: they are HELD (needs Priya
+ a descriptive memo), never guessed. Only description-supported labels (payroll / interest / own-account
transfers / a named inbound) are CONFIRMED and scored. Uncertainty in ("not sure it's own transfer") →
`unknown` out, held — a golden never more certain than the labeler was.
"""

from __future__ import annotations

from dataclasses import dataclass

# The LP-379-E enum values this maps onto (the mapping never emits an off-enum value).
_ENUM = frozenset(
    {
        "payroll",
        "transfer_own",
        "transfer_third_party_in",
        "transfer_third_party_out",
        "debt_payment",
        "gift",
        "loan_proceeds",
        "refund",
        "interest",
        "fee",
        "vendor",
        "unknown",
    }
)


@dataclass(frozen=True)
class Relabel:
    """One proposed free-text → enum mapping. ``enum`` is the proposed golden (or None when there is nothing
    scorable); ``confirmed`` marks a description-supported, obvious mapping (scored) vs a NEEDS-PRIYA hold."""

    enum: str | None
    confirmed: bool
    rationale: str


def relabel(free_text: str, description: str, note: str) -> Relabel:
    """PROPOSE the enum golden for one label from its free text + the DESCRIPTION the AI sees + Priya's note.
    Confirmed only when the description itself supports the category; otherwise HELD (needs Priya), never
    guessed. Uncertainty in the note → ``unknown``, held (the golden is never more certain than the labeler)."""
    desc = description.strip().upper()
    n = (note or "").strip().lower()
    ft = free_text.strip().lower()

    if desc == "PAYROLL DIRECT DEPOSIT":
        return Relabel("payroll", True, "description states PAYROLL")
    if desc == "INTEREST EARNED":
        return Relabel("interest", True, "description states INTEREST")
    if desc == "INBOUND PAYMENT RECEIVED":
        return Relabel(
            "transfer_third_party_in", True, "an inbound transfer from a named third party (note)"
        )
    if "OWN ACCOUNT" in desc:
        if "not sure" in n or "whether" in n:
            return Relabel(
                "unknown",
                False,
                "labeler uncertain own-vs-third (note) — unknown is the honest golden, held",
            )
        if "paymrny" in ft or "big pay" in ft:
            return Relabel(None, False, "ambiguous typo'd label ('big paymrny out') — do NOT guess")
        return Relabel("transfer_own", True, "description states an OWN-ACCOUNT transfer")
    # "CARD PURCHASE / PAYMENT" and any other generic memo: no payee in the description. Priya's category came
    # from the AMOUNT + the un-redacted file — which the prompt forbids the AI from using. HELD, never guessed.
    return Relabel(
        None,
        False,
        "generic memo carries no payee — the category is the labeler's amount/judgment call, "
        "unscorable against a description-only AI (needs Priya + a descriptive memo)",
    )


__all__ = ["Relabel", "relabel"]
