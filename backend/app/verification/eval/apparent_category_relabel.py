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

from collections.abc import Iterable, Mapping
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


@dataclass(frozen=True)
class HeldGolden:
    """LP-390-5a — one apparent_category golden that is NOT scored (a generic memo, an uncertain note, or a
    typo). Reported separately as the redacted-memo / memo-richness limit, never counted as a wrong score."""

    subject_id: str
    free_text: str
    description: str
    enum: str | None  # 'unknown' for an uncertain note; None for a generic memo / typo
    rationale: str


def _description_of(context: str) -> str:
    """Pull the transaction DESCRIPTION out of a worksheet context cell (``...; description=CARD PURCHASE``)."""
    return context.split("description=", 1)[1].strip() if "description=" in context else ""


def map_apparent_category_goldens(
    rows: Iterable[Mapping[str, str]],
) -> tuple[dict[tuple[str, str], str], list[HeldGolden]]:
    """LP-390-5a — apply the LP-379-F free-text->enum mapping to Priya's ``txn.apparent_category`` goldens at
    SCORING TIME (never mutating her committed free text). Returns ``(confirmed, held)``: ``confirmed`` is a
    ``{(tag_id, subject_id): enum}`` golden dict ready for ``score_snapshot_against_golden`` — ONLY the
    description-supported labels; ``held`` is every ambiguous / uncertain / typo row, reported not scored. The
    24.5% byte-compare artifact (LP-390-5) came from scoring the free text directly; this scores the mapped,
    confirmed subset (n=17) and holds the rest (the 30 payee-less memos + uncertain/typo)."""
    confirmed: dict[tuple[str, str], str] = {}
    held: list[HeldGolden] = []
    for r in rows:
        if r.get("tag_id") != "txn.apparent_category":
            continue
        free_text = (r.get("golden_label") or "").strip()
        if not free_text:
            continue
        desc = _description_of(r.get("context", ""))
        note = (r.get("Note") or "").strip()
        rl = relabel(free_text, desc, note)
        key = (str(r["tag_id"]), str(r["subject_id"]))
        if rl.confirmed and rl.enum is not None:
            confirmed[key] = rl.enum
        else:
            held.append(HeldGolden(str(r["subject_id"]), free_text, desc, rl.enum, rl.rationale))
    return confirmed, held


__all__ = ["HeldGolden", "Relabel", "map_apparent_category_goldens", "relabel"]
