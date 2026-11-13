"""Every route that reaches a loan file, as data: the list of record (LP-MB-Admin-06).

Taken from the survey (`docs/tickets/LP-MB-Admin-05-survey.md`, groups A, B and C and the Part 1
addendum). `test_file_doors.py` sends each door, under "restrict loan files to their team", as a
processor who is not on the file's team (it must look exactly like a missing id, and write nothing)
and as four callers who may see it (who must get past the gate). `test_every_route_is_classified`
compares this list with the routes in `app/api/*.py` and with the survey, so a route cannot be added
without being put here or in `EXEMPT` with a reason.

A door's `path` is the route's own path template; `{name}` segments are filled from the fixture's
substitutions (`file_door_fixtures.py`) or the door's `params`. A body value that is exactly
`"{name}"` is filled the same way.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

#: What a door needs on the file besides the file itself. One factory each in `file_door_fixtures`.
Fixture = Literal[
    "file",
    "borrower",
    "document",
    "versioned_document",
    "condition",
    "condition_item",
    "evidence",
    "round",
    "condition_draft",
    "package",
    "outbound_draft",
    "message",
    "needs_item",
    "received_need",
    "property",
    "finding",
    "snapshot_finding",
    "upload_link",
    "attachment",
    "participant",
    "dti_line",
    "stated_liability",
    "stated_asset",
    "stated_income",
    "stated_employer",
    "team_member",
    "unrouted_message",
    "routed_message",
    "reminder",
    "saved_view",
]

#: How a list or count door shows nothing to a caller who may not see the file.
Empty = Literal["page", "list", "counts"]

#: A multipart upload the door sends instead of JSON: the form field and which bytes.
Upload = tuple[str, Literal["pdf", "mismo"]]


@dataclass(frozen=True)
class Door:
    group: Literal["A", "B", "C"]
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str
    fixture: Fixture = "file"
    body: dict[str, Any] | list[Any] | None = None
    upload: Upload | None = None
    params: dict[str, str] = field(default_factory=dict)
    query: dict[str, str] = field(default_factory=dict)
    #: A list or count route: the hidden caller gets an empty answer instead of a 404.
    empty: Empty | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.method, self.path)

    @property
    def id(self) -> str:
        return f"{self.method} {self.path.removeprefix('/api/v1')}"


V = "/api/v1"
F = f"{V}/loan-files/{{file_identifier}}"
I = f"{V}/loan-files/{{identifier}}"  # noqa: E741 - the routes' own segment name
C = f"{V}/loan-files/{{loan_file_id}}"
RD = f"{V}/condition-rounds/{{round_id}}"
CD = f"{V}/conditions/{{condition_id}}"
TODAY = "2026-11-13"

DOORS: tuple[Door, ...] = (
    # ---------------------------------------------------------- Group A (ScopedLoanFile)
    Door("A", "GET", f"{F}/activity"),
    Door("A", "GET", f"{F}/borrowers"),
    Door("A", "POST", f"{F}/borrowers", body={"first_name": "Dee", "last_name": "Door"}),
    Door("A", "GET", f"{F}/borrowers/{{borrower_id}}", "borrower"),
    Door("A", "PATCH", f"{F}/borrowers/{{borrower_id}}", "borrower", body={"first_name": "Dee"}),
    Door("A", "DELETE", f"{F}/borrowers/{{borrower_id}}", "borrower"),
    Door("A", "GET", f"{F}/outbound/draft", "outbound_draft"),
    Door("A", "POST", f"{F}/outbound/compose", body={"document_types": ["bank_statement"]}),
    Door("A", "DELETE", f"{F}/outbound/draft/{{draft_id}}", "outbound_draft"),
    Door(
        "A", "PUT", f"{F}/outbound/draft/{{draft_id}}/body", "outbound_draft", body={"body": "Hi"}
    ),
    Door(
        "A",
        "POST",
        f"{F}/outbound/draft/{{draft_id}}/polish",
        "outbound_draft",
        body={"body": "Hi"},
    ),
    Door(
        "A", "POST", f"{F}/outbound/draft/{{draft_id}}/send", "outbound_draft", body={"body": "Hi"}
    ),
    Door("A", "POST", f"{F}/messages/{{communication_id}}/upload-link", "message"),
    Door("A", "GET", f"{F}/messages/{{communication_id}}", "message"),
    Door("A", "GET", f"{F}/messages/{{communication_id}}/reply-context", "message"),
    Door("A", "POST", f"{F}/messages/{{communication_id}}/reply", "message", body={"body": "Hi"}),
    Door("A", "POST", f"{F}/messages", body={}),
    Door(
        "A",
        "POST",
        f"{F}/messages/{{communication_id}}/important",
        "message",
        body={"important": True},
    ),
    Door("A", "POST", f"{F}/messages/{{communication_id}}/read", "message", body={}),
    Door("A", "POST", f"{F}/messages/{{communication_id}}/follow-up/start", "message", body={}),
    Door("A", "POST", f"{F}/messages/{{communication_id}}/follow-up/stop", "message"),
    Door("A", "POST", f"{F}/messages/{{communication_id}}/follow-up/resume", "message"),
    Door("A", "PATCH", f"{F}/messages/{{communication_id}}/follow-up", "message", body={}),
    Door("A", "POST", f"{F}/messages/{{communication_id}}/follow-up/send-now", "message"),
    Door("A", "GET", f"{F}/follow-ups"),
    Door("A", "GET", f"{F}/findings"),
    Door("A", "POST", f"{F}/documents", upload=("files", "pdf")),
    Door("A", "GET", f"{F}/documents"),
    Door("A", "POST", f"{F}/documents/reprocess", body={}),
    Door("A", "GET", f"{F}/evidence"),
    Door("A", "GET", f"{F}/legal-hold"),
    Door("A", "POST", f"{F}/legal-hold", body={"reason": "Litigation"}),
    Door("A", "DELETE", f"{F}/legal-hold"),
    Door("A", "GET", f"{F}/inbound/messages"),
    Door("A", "GET", f"{F}/inbound/attachments/{{attachment_id}}/preview", "attachment"),
    Door("A", "POST", f"{F}/inbound/attachments/{{attachment_id}}/accept", "attachment", body={}),
    Door(
        "A",
        "POST",
        f"{F}/inbound/attachments/{{attachment_id}}/condition-round",
        "attachment",
        body={},
    ),
    Door("A", "POST", f"{F}/inbound/attachments/{{attachment_id}}/reject", "attachment"),
    Door("A", "PUT", f"{V}/loan-files/{{file_identifier}}/underwriter", body={}),
    Door("A", "GET", f"{F}/needs"),
    Door("A", "POST", f"{F}/needs", body={"title": "Two months of statements"}),
    Door("A", "POST", f"{F}/needs/{{needs_item_id}}/confirm", "needs_item"),
    Door("A", "POST", f"{F}/needs/{{needs_item_id}}/confirm-coverage", "received_need"),
    Door("A", "POST", f"{F}/needs/{{needs_item_id}}/merge-duplicate", "needs_item"),
    Door("A", "POST", f"{F}/needs/{{needs_item_id}}/not-duplicate", "needs_item"),
    Door("A", "POST", f"{F}/needs/{{needs_item_id}}/not-covered", "needs_item"),
    Door("A", "PATCH", f"{F}/needs/{{needs_item_id}}", "needs_item", body={}),
    Door("A", "POST", f"{F}/needs/{{needs_item_id}}/dismiss", "needs_item", body={}),
    Door("A", "POST", f"{F}/needs/{{needs_item_id}}/waive", "needs_item", body={}),
    Door("A", "GET", f"{F}/party-requests"),
    Door(
        "A",
        "POST",
        f"{F}/party-requests/addresses",
        body={"role": "agent", "email": "agent@example.com"},
    ),
    Door("A", "DELETE", f"{F}/party-requests/addresses/{{participant_id}}", "participant"),
    Door("A", "POST", f"{F}/party-requests/draft", body={"party": "borrower"}),
    Door("A", "GET", f"{F}/property", "property"),
    Door("A", "POST", f"{F}/property", body={}),
    Door("A", "PATCH", f"{F}/property", "property", body={}),
    Door("A", "DELETE", f"{F}/property", "property"),
    Door("A", "GET", f"{F}/reminders"),
    Door("A", "POST", f"{F}/reminders/snooze", body={"kind": "file_untouched"}),
    Door("A", "POST", f"{F}/reminders/unsnooze", body={"kind": "file_untouched"}),
    Door("A", "GET", f"{F}/timeline"),
    Door("A", "GET", f"{F}/upload-links"),
    Door("A", "POST", f"{F}/upload-links", body={}),
    Door("A", "DELETE", f"{F}/upload-links/{{link_id}}", "upload_link"),
    # Part 1 addendum
    Door("A", "GET", f"{F}/team"),
    Door("A", "PUT", f"{F}/team/loan-officer", body={"user_id": None}),
    Door("A", "POST", f"{F}/team/members", body={"user_id": "{processor_2}"}),
    Door("A", "DELETE", f"{F}/team/members/{{member_id}}", "team_member"),
    # ---------------------------------------------------------- Group B1 (ScopedLoanFileById)
    Door("B", "POST", f"{C}/condition-rounds/uploads", upload=("file", "pdf")),
    Door("B", "GET", f"{C}/condition-rounds"),
    Door("B", "PUT", f"{C}/lender-processing", body={"on": True}),
    Door("B", "GET", f"{C}/conditions"),
    Door("B", "GET", f"{C}/conditions/summary"),
    Door(
        "B",
        "POST",
        f"{C}/condition-rounds/paste",
        body={"text": "1. Provide a bank statement.", "completeness": "full"},
    ),
    Door("B", "GET", f"{C}/conditions/lender"),
    Door("B", "PUT", f"{C}/conditions/lender", body={"lender_id": "{lender_id}"}),
    Door("B", "POST", f"{C}/conditions/lender/decline", "round", body={"round_id": "{round_id}"}),
    Door("B", "POST", f"{C}/conditions", body={"verbatim_text": "Provide the gift letter."}),
    Door(
        "B",
        "POST",
        f"{C}/conditions/bulk",
        "condition",
        body={"condition_ids": ["{condition_id}"], "action": "owner", "owner": "processor"},
    ),
    Door("B", "GET", f"{C}/condition-drafts"),
    Door("B", "GET", f"{C}/condition-drafts/{{draft_id}}", "condition_draft"),
    Door("B", "POST", f"{C}/condition-drafts/{{draft_id}}/mark-sent", "condition_draft"),
    Door("B", "DELETE", f"{C}/condition-drafts/{{draft_id}}", "condition_draft"),
    Door(
        "B",
        "PUT",
        f"{C}/condition-drafts/{{draft_id}}/address",
        "condition_draft",
        body={"email": "borrower@example.com"},
    ),
    Door(
        "B",
        "PUT",
        f"{C}/condition-drafts/{{draft_id}}/due-date",
        "condition_draft",
        body={"due_date": TODAY},
    ),
    Door("B", "POST", f"{C}/condition-drafts/{{draft_id}}/polish", "condition_draft"),
    Door(
        "B",
        "PUT",
        f"{C}/condition-drafts/{{draft_id}}/body",
        "condition_draft",
        body={"body_html": "<p>Hi</p>"},
    ),
    Door("B", "GET", f"{C}/figures-check"),
    Door(
        "B",
        "POST",
        f"{C}/figures-check/apply",
        body={"changes": [{"key": "loan_amount", "from_evidence": "x"}]},
    ),
    Door("B", "GET", f"{C}/condition-package"),
    Door("B", "POST", f"{C}/condition-package/build"),
    Door(
        "B",
        "PATCH",
        f"{C}/condition-package/rows/{{condition_id}}",
        "package",
        body={"note": "Attached."},
    ),
    Door("B", "POST", f"{C}/condition-package/du-rerun-done", "package"),
    Door("B", "POST", f"{C}/condition-package/submit", "package"),
    Door("B", "GET", f"{C}/condition-package/download", "package"),
    Door("B", "POST", f"{C}/conditions/{{condition_id}}/restore", "condition"),
    Door("B", "GET", f"{C}/withdrawn-conditions"),
    # ---------------------------------------------------------- Group B2 (loan files)
    Door("B", "GET", f"{V}/loan-files", empty="page"),
    Door("B", "GET", I),
    Door("B", "GET", f"{I}/stated-financials"),
    Door("B", "PATCH", I, body={}),
    Door("B", "DELETE", I),
    Door("B", "GET", f"{I}/reconciliation"),
    # ---------------------------------------------------------- Group B3 (calculators, DTI, LTV)
    Door("B", "GET", f"{I}/calculators/{{calculator}}", params={"calculator": "reserves"}),
    Door(
        "B",
        "PUT",
        f"{I}/calculators/{{calculator}}/overrides/{{field_key}}",
        body={"amount": "1000"},
        params={"calculator": "reserves", "field_key": "reserves.closing_costs"},
    ),
    Door(
        "B",
        "DELETE",
        f"{I}/calculators/{{calculator}}/overrides/{{field_key}}",
        params={"calculator": "reserves", "field_key": "reserves.closing_costs"},
    ),
    Door("B", "GET", f"{I}/dti"),
    Door(
        "B",
        "POST",
        f"{I}/dti/lines",
        body={"section": "debt", "label": "Car loan", "amount": "300"},
    ),
    Door("B", "DELETE", f"{I}/dti/lines/{{line_id}}", "dti_line"),
    Door("B", "GET", f"{I}/dti/ungate"),
    Door("B", "POST", f"{I}/dti/ungate", body={"amount": "100"}),
    Door(
        "B",
        "PUT",
        f"{I}/dti/overrides/{{field_key}}",
        body={"amount": "2000"},
        params={"field_key": "rental.gross_subject"},
    ),
    Door(
        "B",
        "DELETE",
        f"{I}/dti/overrides/{{field_key}}",
        params={"field_key": "rental.gross_subject"},
    ),
    Door("B", "GET", f"{I}/ltv"),
    Door(
        "B",
        "PUT",
        f"{I}/ltv/overrides/{{field_key}}",
        body={"amount": "1000"},
        params={"field_key": "ltv.second_loan"},
    ),
    Door(
        "B", "DELETE", f"{I}/ltv/overrides/{{field_key}}", params={"field_key": "ltv.second_loan"}
    ),
    # ---------------------------------------------------------- Group B4 (verification)
    Door("B", "POST", f"{I}/verification/run"),
    Door("B", "GET", f"{I}/verification"),
    Door("B", "PUT", f"{I}/verification/aggression", body={"level": "balanced"}),
    Door("B", "GET", f"{I}/findings/{{finding_id}}/apply-preview", "finding"),
    Door("B", "GET", f"{I}/snapshot-findings"),
    Door(
        "B",
        "POST",
        f"{I}/snapshot-findings/{{finding_id}}/disposition",
        "snapshot_finding",
        body={"disposition": "not_an_issue"},
    ),
    Door("B", "POST", f"{I}/findings/{{finding_id}}/apply", "finding"),
    Door(
        "B", "POST", f"{I}/findings/request-docs", "finding", body={"finding_ids": ["{finding_id}"]}
    ),
    Door("B", "POST", f"{I}/findings/{{finding_id}}/ratify", "finding", body={}),
    Door("B", "POST", f"{I}/findings/{{finding_id}}/undo", "finding"),
    Door("B", "POST", f"{I}/findings/{{finding_id}}/override", "finding", body={"reason": "Fine"}),
    Door("B", "POST", f"{I}/findings/{{finding_id}}/note", "finding", body={"note": "Checked"}),
    Door("B", "POST", f"{I}/findings/{{finding_id}}/accept-risk", "finding", body={}),
    Door("B", "POST", f"{I}/findings/{{finding_id}}/request-docs", "finding", body={}),
    Door("B", "GET", f"{I}/verification/runs"),
    # ---------------------------------------------------------- Group B5 (stated, add)
    Door("B", "POST", f"{F}/stated-liabilities", body={}),
    Door("B", "POST", f"{F}/stated-assets", body={}),
    Door("B", "POST", f"{F}/borrowers/{{borrower_id}}/stated-income", "borrower", body={}),
    Door("B", "POST", f"{F}/borrowers/{{borrower_id}}/stated-employers", "borrower", body={}),
    # ---------------------------------------------------------- Group C1 (rounds by id)
    Door("C", "GET", f"{RD}/plan", "round"),
    Door("C", "POST", f"{RD}/plan/confirm", "round"),
    Door("C", "GET", RD, "round"),
    Door("C", "POST", f"{RD}/attach-pdf", "round", upload=("file", "pdf")),
    Door("C", "GET", f"{RD}/reading", "round"),
    Door("C", "POST", f"{RD}/read", "round"),
    Door("C", "GET", f"{RD}/wrong-file", "round"),
    Door("C", "POST", f"{RD}/import", "round"),
    Door("C", "POST", f"{RD}/discard", "round"),
    Door("C", "GET", f"{RD}/events", "round"),
    Door("C", "POST", f"{RD}/reparse", "round"),
    Door("C", "PUT", f"{RD}/draft", "round", body={"draft_rows": []}),
    Door(
        "C",
        "POST",
        f"{RD}/confirm-cleared",
        "condition",
        body={"condition_ids": ["{condition_id}"]},
    ),
    Door(
        "C",
        "POST",
        f"{RD}/reworded",
        "round",
        body={"old_id": "{round_id}", "new_id": "{round_id}", "same": True},
    ),
    Door("C", "PUT", f"{RD}/completeness", "round", body={"completeness": "partial"}),
    # ---------------------------------------------------------- Group C2 (conditions by id)
    Door("C", "PUT", f"{CD}/next-step", "condition", body={"next_step": "ask_borrower"}),
    Door("C", "PUT", f"{CD}/route", "condition", body={"route": "borrower"}),
    Door("C", "GET", f"{CD}/items/{{item_id}}/link-candidates", "condition_item"),
    Door(
        "C",
        "POST",
        f"{CD}/items/{{item_id}}/links",
        "condition_item",
        body={"document_id": "{document_id}"},
    ),
    Door("C", "DELETE", f"{CD}/items/{{item_id}}/links/{{document_id}}", "evidence"),
    Door(
        "C", "POST", f"{CD}/items", "condition", body={"name": "Letter", "performers": ["borrower"]}
    ),
    Door(
        "C",
        "POST",
        f"{CD}/calls",
        "condition",
        body={"with_whom": "borrower", "on": TODAY, "agreed": "Sends it Friday"},
    ),
    Door("C", "PATCH", f"{CD}/items/{{item_id}}", "condition_item", body={}),
    Door("C", "DELETE", f"{CD}/items/{{item_id}}", "condition_item"),
    Door(
        "C",
        "POST",
        f"{CD}/reading/confirm",
        "condition",
        body={"items": [{"name": "Letter", "performers": ["borrower"]}]},
    ),
    Door("C", "POST", f"{CD}/reading/library-default", "condition"),
    Door("C", "POST", f"{CD}/plan/revert", "condition"),
    Door("C", "POST", f"{CD}/plan/describe", "condition", body={"text": "Ask for the letter"}),
    Door("C", "POST", f"{CD}/plan/own-way", "condition"),
    Door("C", "POST", f"{CD}/prep-status", "condition", body={"to": "waiting"}),
    Door(
        "C",
        "POST",
        f"{CD}/verdict",
        "condition",
        body={"status": "cleared", "source_kind": "portal", "source_date": TODAY},
    ),
    Door("C", "POST", f"{CD}/reopen", "condition", body={"reason": "Lender asked again"}),
    Door("C", "PUT", f"{CD}/owner", "condition", body={}),
    Door("C", "GET", CD, "condition"),
    Door("C", "GET", f"{CD}/events", "condition"),
    Door("C", "POST", f"{CD}/evidence/{{evidence_id}}/accept", "evidence", body={"reason": "Fine"}),
    Door("C", "POST", f"{CD}/evidence/{{evidence_id}}/reask", "evidence"),
    Door(
        "C",
        "POST",
        f"{CD}/evidence/{{evidence_id}}/finding",
        "evidence",
        body={"index": 0, "answer": "explained"},
    ),
    Door("C", "POST", f"{CD}/withdraw", "condition", body={"reason": "Entered in error"}),
    # ---------------------------------------------------------- Group C3 (documents by id)
    Door("C", "GET", f"{V}/documents/{{document_id}}", "document"),
    Door("C", "GET", f"{V}/documents/{{document_id}}/versions", "versioned_document"),
    Door(
        "C",
        "PATCH",
        f"{V}/documents/{{document_id}}",
        "document",
        body={"document_type": "bank_statement"},
    ),
    Door("C", "POST", f"{V}/documents/{{document_id}}/reprocess", "document", body={}),
    Door("C", "POST", f"{V}/documents/{{document_id}}/replace", "document", upload=("file", "pdf")),
    Door(
        "C",
        "POST",
        f"{V}/documents/{{document_id}}/resolve-staleness",
        "document",
        body={"action": "waive"},
    ),
    Door("C", "GET", f"{V}/documents/{{document_id}}/reviews", "document"),
    Door(
        "C",
        "PUT",
        f"{V}/documents/{{document_id}}/reviews",
        "document",
        body={"field_key": "account_holder", "verdict": "accepted"},
    ),
    Door(
        "C",
        "DELETE",
        f"{V}/documents/{{document_id}}/reviews/{{field_key}}",
        "document",
        params={"field_key": "account_holder"},
    ),
    Door("C", "GET", f"{V}/documents/{{document_id}}/boxes", "document"),
    Door(
        "C",
        "GET",
        f"{V}/documents/{{document_id}}/page/{{page_number}}",
        "document",
        params={"page_number": "1"},
    ),
    Door("C", "GET", f"{V}/documents/{{document_id}}/download", "document"),
    Door("C", "DELETE", f"{V}/documents/{{document_id}}", "document"),
    # ---------------------------------------------------------- Group C4 (stated by item id)
    Door("C", "PATCH", f"{V}/stated-liabilities/{{item_id}}", "stated_liability", body={}),
    Door("C", "DELETE", f"{V}/stated-liabilities/{{item_id}}", "stated_liability"),
    Door("C", "PATCH", f"{V}/stated-assets/{{item_id}}", "stated_asset", body={}),
    Door("C", "DELETE", f"{V}/stated-assets/{{item_id}}", "stated_asset"),
    Door("C", "PATCH", f"{V}/stated-income-items/{{item_id}}", "stated_income", body={}),
    Door("C", "DELETE", f"{V}/stated-income-items/{{item_id}}", "stated_income"),
    Door("C", "PATCH", f"{V}/stated-employers/{{item_id}}", "stated_employer", body={}),
    Door("C", "DELETE", f"{V}/stated-employers/{{item_id}}", "stated_employer"),
    # ---------------------------------------------------------- Group C5 (company-wide)
    Door("C", "GET", f"{V}/inbound/queue", "routed_message", empty="list"),
    Door(
        "C",
        "POST",
        f"{V}/inbound/messages/{{message_id}}/move",
        "unrouted_message",
        body={"file_identifier": "{file_identifier}"},
    ),
    Door("C", "GET", f"{V}/reminders", "reminder", empty="list"),
    Door(
        "C", "GET", f"{V}/saved-views", "saved_view", query={"with_counts": "true"}, empty="counts"
    ),
    # ---------------------------------------------------------- Group C6 (dev)
    Door("C", "POST", f"{V}/dev/documents/{{document_id}}/extract-text-layer", "document"),
)

#: Routes that reach no loan file, or reach one by a credential that is not a staff user's, or are
#: covered elsewhere, each with why. From the survey's "Not file reads" and the exceptions it names.
EXEMPT: dict[tuple[str, str], str] = {
    # Creating a file: no file to hide yet; the creator rule is tested in test_file_scope.py.
    ("POST", f"{V}/loan-files"): "creates a file (create-path tests, Decided 4)",
    ("POST", f"{V}/loan-files/import-mismo"): "creates a file (create-path tests, Decided 4)",
    # C5 / addendum, unchanged by decision (ticket point 12).
    (
        "POST",
        f"{V}/admin/lenders/{{lender_id}}/overlay/blast-radius",
    ): "overlays.manage: admins only",
    ("GET", f"{V}/users/assignable"): "a count of files, not a file (point 12)",
    ("POST", f"{V}/users/{{user_id}}/reassign-loans"): "users.manage: admins only",
    # C6: the borrower's upload link. The token is the credential; no staff user is involved.
    ("GET", f"{V}/upload/{{token}}"): "token is the credential (out of scope)",
    ("POST", f"{V}/upload/{{token}}"): "token is the credential (out of scope)",
    # Not file reads (survey).
    ("POST", f"{V}/auth/login"): "not a file read",
    ("POST", f"{V}/auth/refresh"): "not a file read",
    ("POST", f"{V}/auth/logout"): "not a file read",
    ("GET", f"{V}/auth/me"): "not a file read",
    ("GET", f"{V}/users"): "not a file read",
    ("GET", f"{V}/users/{{user_id}}"): "not a file read",
    ("PATCH", f"{V}/users/{{user_id}}"): "not a file read",
    ("PUT", f"{V}/users/{{user_id}}/roles"): "not a file read",
    ("POST", f"{V}/users/{{user_id}}/deactivate"): "not a file read",
    ("POST", f"{V}/users/{{user_id}}/reactivate"): "not a file read",
    ("GET", f"{V}/company/settings"): "not a file read",
    ("PATCH", f"{V}/company/settings"): "not a file read",
    ("GET", f"{V}/invites"): "not a file read",
    ("POST", f"{V}/invites"): "not a file read",
    ("POST", f"{V}/invites/{{invite_id}}/resend"): "not a file read",
    ("POST", f"{V}/invites/accept"): "not a file read",
    ("GET", f"{V}/audit-log"): "not a file read",
    ("GET", f"{V}/lenders"): "not a file read",
    ("POST", f"{V}/lenders"): "not a file read",
    ("GET", f"{V}/lenders/{{lender_id}}"): "not a file read",
    ("PATCH", f"{V}/lenders/{{lender_id}}"): "not a file read",
    ("GET", f"{V}/lenders/{{lender_id}}/contacts"): "not a file read",
    ("POST", f"{V}/lenders/{{lender_id}}/contacts"): "not a file read",
    ("PATCH", f"{V}/lenders/contacts/{{contact_id}}"): "not a file read",
    ("DELETE", f"{V}/lenders/contacts/{{contact_id}}"): "not a file read",
    ("GET", f"{V}/lenders/{{lender_id}}/condition-settings"): "not a file read",
    ("PUT", f"{V}/lenders/{{lender_id}}/condition-settings"): "not a file read",
    ("GET", f"{V}/admin/lenders"): "not a file read",
    ("GET", f"{V}/admin/lenders/{{lender_id}}/overlay"): "not a file read",
    ("PUT", f"{V}/admin/lenders/{{lender_id}}/overlay"): "not a file read",
    ("GET", f"{V}/mailbox-connections"): "not a file read",
    ("POST", f"{V}/mailbox-connections"): "not a file read",
    ("DELETE", f"{V}/mailbox-connections/{{connection_id}}"): "not a file read",
    ("GET", f"{V}/capabilities"): "not a file read",
    ("GET", f"{V}/users/me/preferences"): "not a file read",
    ("PUT", f"{V}/users/me/preferences"): "not a file read",
    ("POST", f"{V}/invites/lookup"): "not a file read",
    ("POST", f"{V}/invites/{{invite_id}}/revoke"): "not a file read",
    ("GET", f"{V}/mailbox-connections/{{connection_id}}/steps"): "not a file read",
    ("POST", f"{V}/mailbox-connections/{{connection_id}}/email-steps"): "not a file read",
    ("GET", f"{V}/admin/validation/inventory"): "not a file read",
    ("POST", f"{V}/admin/validation/verdicts"): "not a file read",
    ("POST", f"{V}/dev/extraction-bench/preview"): "not a file read (dev only)",
    ("POST", f"{V}/dev/extraction-bench/start"): "not a file read (dev only)",
    ("GET", f"{V}/dev/extraction-bench/status/{{run_id}}"): "not a file read (dev only)",
    ("POST", f"{V}/dev/extraction-bench/cancel/{{run_id}}"): "not a file read (dev only)",
    ("POST", f"{V}/dev/inbound/inject"): "not a file read (dev only)",
    ("GET", f"{V}/documents/types/catalog"): "not a file read",
    ("POST", f"{V}/inbound/messages/{{message_id}}/dismiss"): "unrouted mail only (ADR-421)",
    ("POST", f"{V}/saved-views"): "saved view rows only",
    ("PATCH", f"{V}/saved-views/{{view_id}}"): "saved view rows only",
    ("DELETE", f"{V}/saved-views/{{view_id}}"): "saved view rows only",
}
