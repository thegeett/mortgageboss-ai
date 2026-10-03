"""A MOCKED model for LP-919's reading of `uwm_round1` — fictional, and keyed by lender code.

Stage 3's tests never call a real model: the plan's acceptance test runs "with the AI MOCKED". This is
the one mock, shared by the tests, the Stage 3A acceptance test and the visual-check seed, so the
screens and the assertions read the same answers.

It answers the way a well-behaved model would under `read_v1.txt`: items by the library's keys,
specifics copied from the lender's text, a confidence per condition. The confidences are S3-02's:
0132 at 0.64 is the one below the 0.75 bar. `fake_complete` parses the real request the service builds,
so a request that stopped carrying a condition would get no answer for it.

Deliberately NOT perfect in one place, so the tests prove code's checks: 7086's entry offers a
shortfall amount the lender never wrote (`$27,148.22`), which `_checked_specifics` must drop — the
figure the screen shows comes from code.
"""

from __future__ import annotations

import json
from typing import Any

from app.ai.client import AICompletion

#: code → what the mocked model says about it.
CANNED: dict[str, dict[str, Any]] = {
    "1228": {
        "summary": "Final inspection must confirm construction is complete",
        "explanation": "The lender needs a final inspection confirming the new construction was "
        "completed to the plans and specs.",
        "items": [
            {"key": "inspection", "performers": ["appraiser"], "specifics": {}},
            # LP-954 — the conditional clause the library's PA-03 does not cover.
            {
                "key": "change_of_circumstance",
                "name": "Change of Circumstance re-disclosure",
                "performers": ["lo"],
                "specifics": {},
            },
        ],
        "clauses": [
            {"text": "Final inspection is required", "item_key": "inspection", "note": None},
            {
                "text": "possibly a Change of Circumstance",
                "item_key": "change_of_circumstance",
                "note": None,
            },
            {
                "text": "On new construction transactions this condition can be moved to closing at "
                "the request of the client.",
                "item_key": None,
                "note": "A timing rule; asks for nothing.",
            },
        ],
        "confidence": 0.88,
    },
    "7086": {
        "summary": "Show more in assets to cover closing",
        "explanation": "The lender needs two months of statements showing enough funds to close; "
        "$38,210.40 is required and $11,062.18 is verified.",
        "items": [
            {
                "key": "statements",
                "performers": ["borrower"],
                "specifics": {"amounts": ["$38,210.40", "$11,062.18", "$27,148.22"]},
            },
            {"key": "other_accounts", "performers": ["borrower"], "specifics": {}},
        ],
        "clauses": [
            {
                "text": "Short funds to close and/or reserves.",
                "item_key": "statements",
                "note": None,
            },
        ],
        "confidence": 0.95,
    },
    "6132": {
        "summary": "One more consecutive month, Capital One ··9912",
        "explanation": "The lender needs one more consecutive monthly statement for the Capital One "
        "account ending 9912, so it has two full months.",
        "items": [
            {
                "key": "statement",
                "performers": ["borrower"],
                "specifics": {
                    "account_bank": "Capital One",
                    "account_last4": "9912",
                    "month": "2026-08",
                },
            }
        ],
        "confidence": 0.97,
    },
    "6637": {
        "summary": "Earnest money $2,850: source, receipt, clearance",
        "explanation": "The lender wants proof of where the $2,850 earnest money came from, that the "
        "title company received it, and that the check cleared.",
        "items": [
            {
                "key": "source",
                "performers": ["borrower"],
                "specifics": {"amounts": ["$2,850.00"], "month": "2026-07"},
            },
            {"key": "receipt", "performers": ["title"], "specifics": {"amounts": ["$2,850.00"]}},
            {"key": "clearance", "performers": ["borrower"], "specifics": {"month": "2026-08"}},
        ],
        "confidence": 0.93,
    },
    "6178": {
        "summary": "Insurance starts 09/30; current policy only if closing earlier",
        "explanation": "The lender needs updated insurance declarations; the policy starts 09/30/2026, "
        "and the current policy is needed only if closing happens earlier.",
        "items": [{"key": "declarations", "performers": ["insurance"], "specifics": {}}],
        "confidence": 0.86,
    },
    "0132": {
        "summary": "SC attorney disclosure with an approved attorney, matching wire instructions",
        "explanation": "The lender needs the SC attorney disclosure re-signed with an approved "
        "attorney, and wire instructions that match that attorney.",
        "items": [
            {"key": "disclosure", "performers": ["borrower", "lo"], "specifics": {}},
            {"key": "attorney", "performers": ["lo"], "specifics": {}},
            {"key": "wire_instructions", "performers": ["attorney"], "specifics": {}},
        ],
        "confidence": 0.64,
    },
    "1947": {
        "summary": "Title: final seller CD with the closing package",
        "explanation": "Title must provide the final seller Closing Disclosure with the closing package.",
        "items": [{"key": "seller_cd", "performers": ["title"], "specifics": {}}],
        "confidence": 0.96,
    },
    "1582": {
        "summary": "Third-party processing invoice",
        "explanation": "The lender needs a copy of the third-party processing invoice.",
        "items": [{"key": "invoice", "performers": ["processor"], "specifics": {}}],
        "confidence": 0.99,
    },
    "0006": {
        "summary": "Credit report invoice",
        "explanation": "The lender needs a copy of the credit report invoice.",
        "items": [{"key": "invoice", "performers": ["processor"], "specifics": {}}],
        "confidence": 0.99,
    },
    "0007": {
        "summary": "Final inspection invoice",
        "explanation": "The lender needs a copy of the final inspection invoice.",
        "items": [{"key": "invoice", "performers": ["processor"], "specifics": {}}],
        "confidence": 0.97,
    },
    "6378": {
        "summary": "Title: loan number on every check to the lender",
        "explanation": "Title must put the lender's loan number on every check sent to the lender.",
        "items": [{"key": "instruction", "performers": ["title"], "specifics": {}}],
        "confidence": 0.95,
    },
}


def canned_response(request_json: str) -> str:
    """The JSON a model would return for this request, answering only the refs it was sent."""
    request = json.loads(request_json)
    out = []
    for entry in request["conditions"]:
        canned = CANNED.get(entry.get("code") or "")
        if canned is None:
            continue
        out.append({"ref": entry["ref"], "information_only": False, **canned})
    return json.dumps({"conditions": out})


def fake_complete(calls: list[str] | None = None):  # type: ignore[no-untyped-def]
    """A drop-in for `app.ai.client.complete`; records each request's user content in `calls`."""

    async def _complete(**kwargs: Any) -> AICompletion:
        content = kwargs["messages"][0]["content"]
        if calls is not None:
            calls.append(content)
        return AICompletion(
            text=canned_response(content),
            input_tokens=1200,
            output_tokens=900,
            model=kwargs["model"],
            stop_reason="end_turn",
            cache_read_tokens=0,
            cache_write_tokens=0,
        )

    return _complete
