"""The words Stage 3 plans conditions in (LP-918): who acts, what she does next, what evidence must pass.

Enums only, no tables. They live under `app.models` because later tickets STORE them (LP-920's items
and actions, LP-923's check results) as `VARCHAR` + `CHECK` columns (ADR-037), and a model never imports
from `app.conditions`. The condition library (`app/conditions/library`) is written in these words too,
so the library and the database cannot disagree about what "title" or "ask_borrower" means.
"""

from enum import StrEnum


class Performer(StrEnum):
    """Who acts on one item of a condition (plan §5 LP-918, §6).

    WIDER THAN `OwnerHint`, AND DELIBERATELY SEPARATE. `OwnerHint` is Stage 1's guess at who a whole
    condition is waiting on, with seven values and a CHECK already in production. A condition's ITEMS
    are acted on by people the hint never named — the LO, an attorney, an HOA, an employer, the appraiser
    — and 0132 alone has three of them. Widening `OwnerHint` would change a shipped CHECK to add values
    the Stage 2 owner chip would then have to render.
    """

    BORROWER = "borrower"
    LO = "lo"
    PROCESSOR = "processor"
    LENDER = "lender"
    TITLE = "title"
    ATTORNEY = "attorney"
    INSURANCE = "insurance"
    HOA = "hoa"
    EMPLOYER = "employer"
    APPRAISER = "appraiser"
    OTHER_PARTY = "other_party"


class PlanOption(StrEnum):
    """The next step proposed for an item or a condition (plan §5 LP-921's table).

    `LENDER_DOING_IT` AND `INFORMATION_ONLY` ARE OPTIONS, NOT STATUSES (plan §4a change 12). Choosing
    one leaves `prep_status` at `to_do` and changes only how the condition is displayed.
    """

    ASK_BORROWER = "ask_borrower"
    ASK_THIRD_PARTY = "ask_third_party"
    I_WILL_DO_IT = "i_will_do_it"
    ALREADY_IN_FILE = "already_in_file"
    ASK_UNDERWRITER = "ask_underwriter"
    PUSH_BACK = "push_back"
    LENDER_DOING_IT = "lender_doing_it"
    INFORMATION_ONLY = "information_only"


class EvidenceCheck(StrEnum):
    """A check code runs on a document that arrives for an item (plan §5 LP-923). Never the AI's.

    The library names which checks an item's evidence must pass; LP-923 implements them. A check whose
    inputs the file does not have is reported as not run, never as passed.
    """

    ALL_PAGES = "all_pages"
    RIGHT_ACCOUNT = "right_account"
    RIGHT_BORROWER = "right_borrower"
    RIGHT_PERIOD = "right_period"
    INSIDE_LENDER_DATES = "inside_lender_dates"
    AMOUNT_MATCHES = "amount_matches"
    COVERS_REQUIRED_FUNDS = "covers_required_funds"
    SIGNED_AND_DATED = "signed_and_dated"
    MORTGAGEE_CLAUSE_MATCHES = "mortgagee_clause_matches"
    EFFECTIVE_BY_CLOSING = "effective_by_closing"
    INSIDE_VOE_WINDOW = "inside_voe_window"
    NOT_EXPIRED = "not_expired"


class ConditionItemStatus(StrEnum):
    """Where one item stands (LP-920). Our side only; the lender's track is the condition's.

    `requested` is set when the email carrying the item is marked sent (LP-922); `received` when
    evidence is linked (LP-923); `done` when every check passed, the task was marked done, or the file
    already held it; `not_needed` when the plan drops it (6178's push-back, an item she removes).
    """

    OPEN = "open"
    REQUESTED = "requested"
    RECEIVED = "received"
    DONE = "done"
    NOT_NEEDED = "not_needed"


class ConditionItemOrigin(StrEnum):
    """Where an item came from: the reading, her own "Add an item", or a replaced condition's plan."""

    READING = "reading"
    MANUAL = "manual"
    CARRIED = "carried"
