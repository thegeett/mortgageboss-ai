"""Which findings may become a borrower-facing document request, and what a request records (LP-801).

Two things live here because they are the two halves of one contract, and Phase 4's drafting engine
is the caller that needs both to agree:

* :func:`requestable` — the predicate. Not every finding a processor sees is something a *borrower*
  can be asked for.
* :func:`docs_requested_marker` — the ONE shape ``Finding.details["docs_requested"]`` takes, whichever
  path wrote it.

Before LP-801 the two request paths disagreed on that shape: the per-finding path
(:func:`~app.services.finding_resolution.request_docs_for_finding`) wrote ``{by, at, needs_item_id}``
and the bulk path wrote a bare ``True``. Both render the same in the UI — ``Boolean(...)`` is true for
either — so the divergence was invisible on screen while the bulk path silently dropped the
finding -> needs-item link. Phase 4 drafts an email FROM that link, so "invisible" stops being
survivable there.
"""

from __future__ import annotations

from uuid import UUID

from app.models.base import utcnow
from app.models.finding import Finding
from app.verification.rule_engine.result import UNIDENTIFIED_DOCUMENTS_RULE_ID

__all__ = [
    "NotRequestable",
    "docs_requested_marker",
    "requestable",
]


class NotRequestable(Exception):
    """Raised when a caller asks for documents from a finding that cannot produce a request."""


def requestable(finding: Finding) -> bool:
    """Whether documents may be requested FROM this finding — false for the unidentified-document row.

    THE ONE EXCLUSION, AND WHY IT IS THE ONLY ONE TODAY. LP-640 collapses every "we do not know what
    that document is" abstention into a single loan-level finding under
    ``UNIDENTIFIED_DOCUMENTS_RULE_ID``. That row is real work, but it is the *processor's* work:
    "identify these files" is answered by typing documents already sitting in the file, not by asking
    a borrower to send anything. A request generated from it would ask the borrower to re-send
    documents they have already sent, in words that name nothing they could act on.

    WHY A RULE ID AND NOT A COLUMN. ``RuleEvaluation.unidentified_document`` is an in-run flag with no
    persisted counterpart, so the obvious move is to add one. It would be dead weight: the per-rule
    abstentions carrying the flag are *replaced* by the consolidated evaluation before any write, so a
    column would be written ``True`` on exactly one row per file — the row this id already names, on an
    identity LP-640 made stable so the reconciler carries it across runs. Two spellings of one fact can
    drift; one cannot. ADR-399 records the decision.

    THE PREDICATE EXISTS EVEN THOUGH THE READ PATH HAPPENS TO AGREE. The consolidated finding carries
    no spec, so ``_missing_documents`` returns ``[]`` for it and the UI offers no button — the correct
    outcome reached by two accidents (a missing spec file, and a ``couldnt_check`` filter in the row
    component). Neither is a statement that this finding must not be requested, and neither would
    survive someone giving the synthetic id a spec. This is the statement.
    """
    return finding.rule_id != UNIDENTIFIED_DOCUMENTS_RULE_ID


def docs_requested_marker(*, actor_user_id: UUID, needs_item_id: UUID) -> dict[str, str]:
    """The value both request paths write to ``Finding.details["docs_requested"]``.

    ``needs_item_id`` is the forward link a draft follows from a finding to the thing the borrower was
    actually asked for. It is singular because the per-finding path is 1:1 and the frontend's declared
    type (``{ needs_item_id?: string } | null``) is singular; the bulk path can produce more than one
    item for one finding, and links the first — see the note in
    :func:`~app.services.finding_resolution.request_documents_in_bulk`.
    """
    return {
        "by": str(actor_user_id),
        "at": utcnow().isoformat(),
        "needs_item_id": str(needs_item_id),
    }
