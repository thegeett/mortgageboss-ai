"""C7 — the read-only query path: the redaction, and the guards that keep it honest.

Three things are worth pinning here, and one thing deliberately is not.

WHAT IS TESTED
    1. ``readonly.scrub`` — the security-critical SQL. Run against a real PostgreSQL,
       because a regex that behaves in Python's engine and not in Postgres's would pass a
       pure-unit test and fail in production. The cases that matter are the two the key-
       based approach misses: a value under a key in NO registry, and a value nested
       inside a list row.
    2. Column drift — every column of every model is either exposed by its view or named
       in this file's exclusion set. A new column on a model fails this test until someone
       decides which it is. Without it, views rot quietly and the pressure is to "just
       grant the base table".
    3. Sensitive columns never appear in a view at all.

WHAT IS NOT TESTED HERE, AND WHY
    The role's privileges. ``mbai_readonly`` is a PostgreSQL ROLE, which is CLUSTER-scoped,
    not database-scoped — creating or dropping it from a test would reach outside the test
    database and race any other connection to the same cluster. The privilege boundary
    (``REVOKE ALL ON SCHEMA public``) is verified manually against the local database and
    recorded in ``docs/tickets/C7-query-stage-result.md``; the drift guards below are what
    keep the *view definitions* honest between those runs.
"""

from __future__ import annotations

import re
from importlib import import_module
from pathlib import Path

import app.models as app_models
import pytest
import sqlalchemy as sa
from app.models.base import Base
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


def _view_module(revision: str):
    """Import a migration module by revision id, to reach its view DDL constants."""
    from importlib.util import module_from_spec, spec_from_file_location

    root = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    (path,) = [p for p in root.glob("*.py") if f"_{revision}_" in p.name]
    spec = spec_from_file_location(f"_mig_{revision}", path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20260814_2300_d4e8a1c05b73_c7_readonly_query_schema.py"
)


def _migration_source() -> str:
    return _MIGRATION.read_text(encoding="utf-8")


def _migration_module() -> object:
    """Import the migration module so the tests read the SHIPPED SQL, not a copy."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("c7_migration", _MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# 1. The scrub, against a real PostgreSQL
# --------------------------------------------------------------------------- #

# (label, input, expected-to-survive?) — `False` means the value must be redacted.
_SCRUB_CASES: tuple[tuple[str, str, bool], ...] = (
    ("dashed SSN", "123-45-6789", False),
    ("spaced SSN", "123 45 6789", False),
    ("bare 9-digit TIN", "987654321", False),
    ("16-digit card/account", "4111111111111111", False),
    ("10-digit account", "0123456789", False),
    # Survivors: the debugging signal. An amount with cents must not be eaten by the
    # 9+ digit rule — that is what the negative lookahead is for.
    ("dollar amount", "6028.02", True),
    ("large amount with cents", "123456789.01", True),
    ("ISO date", "2025-04-04", True),
    ("percentage", "6.125", True),
    ("8-digit run (below the bar)", "12345678", True),
    ("uuid", "c6047d32-8b38-4ecc-b1ab-0abd0351c851", True),
)


@pytest.mark.asyncio
async def test_scrub_redacts_identifier_shapes_and_keeps_the_rest(
    test_engine: AsyncEngine,
) -> None:
    """The scrub function, exercised in PostgreSQL exactly as shipped."""
    module = _migration_module()
    async with test_engine.begin() as conn:
        await conn.execute(sa.text("CREATE SCHEMA IF NOT EXISTS readonly"))
        await conn.execute(sa.text(module._SCRUB_FN))  # type: ignore[attr-defined]
        await conn.execute(sa.text(module._SCRUB_JSON_FN))  # type: ignore[attr-defined]

        for label, value, should_survive in _SCRUB_CASES:
            got = await conn.scalar(sa.text("SELECT readonly.scrub(:v)"), {"v": value})
            if should_survive:
                assert got == value, f"{label}: {value!r} was redacted but should survive"
            else:
                assert value not in (got or ""), f"{label}: {value!r} survived the scrub"
                assert "[REDACTED-ID]" in (got or ""), f"{label}: no redaction marker"


@pytest.mark.asyncio
async def test_the_saved_views_view_actually_scrubs_its_filter_payload(
    db_session: AsyncSession,
) -> None:
    """`readonly.saved_views` runs `scrub_json` over `filters`, not merely selects it.

    Every other assertion about a view checks that a column is MENTIONED before
    the FROM. An unscrubbed `SELECT filters` mentions it too, so "exposed" and
    "safe" are different claims and only one was being made. A saved view's
    filter payload is user-authored — a search string is whatever someone typed,
    which is exactly where an identifier ends up.

    Built end to end against the real table and the shipped view SQL, rather than
    against an extracted fragment: a test of a restatement proves nothing about
    what runs.
    """
    from app.core.security import hash_password
    from app.models import Company, User, UserRole
    from app.models.saved_view import SavedView

    module = _migration_module()
    company = Company(name="Acme", slug="acme-scrub")
    db_session.add(company)
    await db_session.flush()
    user = User(
        company_id=company.id,
        email="scrub@acme.com",
        hashed_password=hash_password("x"),  # pragma: allowlist secret
        first_name="T",
        last_name="U",
        role=UserRole.PROCESSOR,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        SavedView(
            company_id=company.id,
            owner_user_id=user.id,
            name="Scrub probe",
            filters={"search": "SSN 123-45-6789"},
        )
    )
    await db_session.flush()

    await db_session.execute(sa.text("CREATE SCHEMA IF NOT EXISTS readonly"))
    await db_session.execute(sa.text(module._SCRUB_FN))  # type: ignore[attr-defined]
    await db_session.execute(sa.text(module._SCRUB_JSON_FN))  # type: ignore[attr-defined]
    await db_session.execute(sa.text("DROP VIEW IF EXISTS readonly.saved_views"))
    # `_view_bodies` returns the SELECT BODY of the shipped view, read from the
    # migration as text — so the schema is still a literal placeholder, and there
    # is no CREATE around it. Both are why the drift guard can read migrations
    # without importing `alembic.op`. Restored here so what runs is the shipped
    # projection rather than a restatement of it.
    body = _view_bodies()["saved_views"].replace("{_SCHEMA}", "readonly")
    await db_session.execute(sa.text(f"CREATE VIEW readonly.saved_views AS {body}"))

    seen = await db_session.scalar(
        sa.text("SELECT filters::text FROM readonly.saved_views WHERE name = 'Scrub probe'")
    )

    assert "123-45-6789" not in (seen or ""), "the filter payload reached the view unscrubbed"
    assert "[REDACTED-ID]" in (seen or "")


@pytest.mark.asyncio
async def test_scrub_reaches_unregistered_keys_and_nested_list_rows(
    test_engine: AsyncEngine,
) -> None:
    """The two cases a key-denylist cannot cover.

    ``_PII_FIELDS`` documents its own gap — PII inside a captured LIST row is not routed
    through it — and no key list can cover a field that does not exist yet. Shape matching
    covers both, which is the entire reason the scrub works on serialized text.
    """
    module = _migration_module()
    payload = (
        '{"brand_new_field_in_no_registry": {"value": "555443333"},'
        ' "tradelines": [{"creditor": "CITI", "account_number": "4111111111111111"}],'
        ' "gross_pay": {"value": "6028.02"}}'
    )
    async with test_engine.begin() as conn:
        await conn.execute(sa.text("CREATE SCHEMA IF NOT EXISTS readonly"))
        await conn.execute(sa.text(module._SCRUB_FN))  # type: ignore[attr-defined]
        await conn.execute(sa.text(module._SCRUB_JSON_FN))  # type: ignore[attr-defined]
        got = await conn.scalar(
            sa.text("SELECT readonly.scrub_json(CAST(:v AS json))::text"), {"v": payload}
        )

    assert got is not None
    assert "555443333" not in got, "a field in no registry leaked"
    assert "4111111111111111" not in got, "PII inside a nested list row leaked"
    assert "6028.02" in got, "the debugging signal was destroyed"
    assert "CITI" in got, "a non-identifier value was redacted"


#: JSON documents whose NUMBERS previously took the whole view down. ``scrub(v::text)::json``
#: rewrote a 9+ digit run inside a number to a bare ``[REDACTED-ID]`` token and the cast back
#: raised — for the SELECT, not the cell — so one such row anywhere returned nothing at all.
#: The second element is the value that must still be readable afterwards.
_JSON_NUMBER_CASES: tuple[tuple[str, str], ...] = (
    ("a big integer", '{"tokens_used": 123456789}'),
    ("an epoch-millisecond timestamp", '{"epoch_ms": 1755212345678}'),
    ("a float repr with 16 fraction digits", '{"confidence": 0.8500000000000001}'),
    ("a round hundred million", '{"n": 100000000}'),
    ("a negative identifier-length integer", '{"delta": -123456789}'),
)


@pytest.mark.asyncio
@pytest.mark.parametrize(("label", "payload"), _JSON_NUMBER_CASES)
async def test_scrub_json_survives_numbers(
    test_engine: AsyncEngine, label: str, payload: str
) -> None:
    """A number in the document must not make the JSON unparseable."""
    module = _migration_module()
    async with test_engine.begin() as conn:
        await conn.execute(sa.text("CREATE SCHEMA IF NOT EXISTS readonly"))
        await conn.execute(sa.text(module._SCRUB_FN))  # type: ignore[attr-defined]
        await conn.execute(sa.text(module._SCRUB_JSON_FN))  # type: ignore[attr-defined]
        await conn.execute(sa.text(module._SCRUB_JSONB_FN))  # type: ignore[attr-defined]

        for fn, cast in (("scrub_json", "json"), ("scrub_jsonb", "jsonb")):
            got = await conn.scalar(
                sa.text(f"SELECT readonly.{fn}(CAST(:v AS {cast}))::text"), {"v": payload}
            )
            assert got is not None, f"{label}: {fn} returned NULL"


@pytest.mark.asyncio
async def test_scrub_json_keeps_debugging_numbers_and_redacts_numeric_identifiers(
    test_engine: AsyncEngine,
) -> None:
    """Numbers are kept, EXCEPT an identifier-shaped integer.

    A number cannot hold the marker and stay a number, so a 9+ digit integer becomes the
    string marker — the redaction the text-based version intended, without the broken JSON.
    Fractional values are left alone: no identifier is fractional, and the digit-run pattern
    would otherwise eat the fraction digits of an ordinary float.
    """
    module = _migration_module()
    payload = (
        '{"cost": 0.02, "confidence": 0.8500000000000001, "tokens": 12345,'
        ' "tin_as_number": 123456789, "amount": 350000.00}'
    )
    async with test_engine.begin() as conn:
        await conn.execute(sa.text("CREATE SCHEMA IF NOT EXISTS readonly"))
        await conn.execute(sa.text(module._SCRUB_FN))  # type: ignore[attr-defined]
        await conn.execute(sa.text(module._SCRUB_JSON_FN))  # type: ignore[attr-defined]
        got = await conn.scalar(
            sa.text("SELECT readonly.scrub_json(CAST(:v AS json))::text"), {"v": payload}
        )

    assert got is not None
    assert "0.8500000000000001" in got, "a float repr was mangled"
    assert "0.02" in got and "12345" in got, "ordinary numbers must survive"
    assert "350000.00" in got, "an amount was redacted"
    assert "123456789" not in got, "a numeric identifier leaked"
    assert "[REDACTED-ID]" in got


def test_scrub_patterns_match_the_at_rest_guard() -> None:
    """The scrub and the LP-209 at-rest guard must agree by construction.

    They defend the same property from two sides — the guard refuses to WRITE an
    unmasked identifier, the scrub refuses to RETURN one. If the guard's patterns are
    tightened and the scrub's are not, the query path becomes the weaker of the two
    silently. Pinning them together makes that a failing test instead.
    """
    from app.verification.snapshot import persistence

    source = _migration_source()
    assert persistence._RAW_SSN.pattern == r"\b\d{3}-\d{2}-\d{4}\b"
    assert persistence._LONG_DIGITS.pattern == r"\b\d{9,}\b(?!\.\d)"
    # Postgres spells the word boundary \m ... \M; the digit classes must still match.
    assert r"\\d{{3}}-\\d{{2}}-\\d{{4}}" in source or r"\d{3}-\d{2}-\d{4}" in source
    assert r"\\d{{9,}}" in source or r"\d{9,}" in source


# --------------------------------------------------------------------------- #
# 2 + 3. Drift guards over the view definitions
# --------------------------------------------------------------------------- #

#: Columns deliberately kept out of the readonly views, per table. Adding a column to a
#: model and NOT listing it here (or in its view) fails ``test_no_model_column_drifts``.
#: The reason for each is in the migration next to the view.
EXCLUDED: dict[str, frozenset[str]] = {
    # LP-813 — `underwriter_contact_id` joins straight back to a named person at a lender, so the
    # view answers the analytic question as a boolean (`has_named_underwriter`) instead. Which
    # LENDER a file is with stays exposed; which PERSON does not.
    # LP-821 adds `legal_hold_reason`: free prose a processor typed about a legal matter on one
    # borrower's file, which is where a name arrives in a shape no scrubber predicts. The FLAG and
    # the TIME are exposed — "how many files are held, and since when" is a question about how a
    # company works and names nobody.
    "loan_files": frozenset(
        {
            "inbox_token",
            "loan_officer_name",
            "loan_officer_email",
            "underwriter_contact_id",
            "legal_hold_reason",
        }
    ),
    # LP-808 — `token` is a BEARER CAPABILITY, stored in the clear because an admin types it into a
    # routing rule and must be able to read it back. Anyone who can send to `co-<token>@` gets mail
    # into this company's triage queue, which is exactly why `loan_files.inbox_token` is excluded and
    # this is the company-level analogue. `source_address` is a real mailbox at a customer's domain.
    # `encrypted_refresh_token` and `cursor` are Route C's and are excluded now rather than when they
    # first hold something.
    "mailbox_connections": frozenset(
        {"token", "source_address", "encrypted_refresh_token", "cursor", "watch_expires_at"}
    ),
    # LP-815 — `token_hash` is the VERIFIER of a capability, and exposing it through the analytics
    # path is the opposite of the reason it is hashed. `recipient_email` names a borrower, and
    # `purpose` is prose that ends up naming one. What is left answers how many links were minted,
    # how fast they are used and how many expire unused, which is the analytic question.
    "upload_links": frozenset({"token_hash", "recipient_email", "purpose"}),
    # LP-813 — a lender contact is a person. The name, address and phone identify them outright,
    # and `notes` is free prose an admin typed about them, which is where a name ends up in a shape
    # no scrubber predicts. What is left — the lender, the role, whether they are active — answers
    # "how many files have a named underwriter" without naming anybody.
    "lender_contacts": frozenset({"name", "email", "phone", "notes"}),
    # A correction is whatever a processor typed, on whatever field they were correcting —
    # correct an SSN field and the correction IS an SSN. The note is free prose about one
    # borrower's document. Both are dropped rather than scrubbed: scrubbing catches the
    # shapes it knows, and a hand-typed value is the one place a raw identifier arrives in
    # a shape nobody predicted. The view answers "was there a correction?" with a boolean.
    #
    # `replaced_value` (LP-703) is the EXTRACTED value a correction overruled, kept so a
    # re-extraction can ask whether the model still says the same thing. It is the value
    # from the SSN field the processor was correcting, so it is exactly as sensitive as
    # the correction and is excluded for the same reason, not a weaker one.
    "field_reviews": frozenset({"corrected_value", "note", "replaced_value"}),
    # LP-814 — free prose a processor typed about one borrower's file, which is where a name arrives
    # in a shape no scrubber predicts. Everything else on the row — the rule, the subject id, the two
    # timestamps — is exposed, and answers "how often is this suggestion put off" without naming
    # anybody. Same argument as `dti_custom_lines.note` immediately below.
    "reminder_snoozes": frozenset({"note"}),
    # LP-643 — a processor's own DTI line. The label and the note are typed by hand about one
    # borrower's file, which is where an identifier arrives in a shape no scrubber predicts. The
    # view answers which section, how much and how often, and reports the two as booleans.
    "dti_custom_lines": frozenset({"label", "note"}),
    # LP-644 — the AI tag cache. `cache_key` fingerprints raw transaction fields and `value` is
    # the model's judgment about one transaction. The operational question is whether the cache
    # is earning its keep, which `cache_kind` and `hit_count` answer without either.
    "tag_cache_entries": frozenset({"cache_key", "value"}),
    "borrowers": frozenset(
        {
            "first_name",
            "middle_name",
            "last_name",
            "ssn",
            "date_of_birth",
            "email",
            "phone",
            "declarations",
        }
    ),
    "properties": frozenset({"address_line", "address_line_2", "postal_code"}),
    # document_name (LP-636) joins summary/generic_analysis for the same reason: model
    # prose over the document, and the scrub matches identifier shapes, not names.
    "documents": frozenset(
        {"full_text", "generic_analysis", "summary", "storage_path", "document_name"}
    ),
    "mismo_imports": frozenset({"catch_all", "raw_file_path"}),
    "findings": frozenset({"source_snippet"}),
    "companies": frozenset({"settings"}),
    # `reviewer_pane_split` is a UI preference, not data anyone queries staging for
    # (LP-UI-030) — kept out for noise, not for privacy. Reason in that migration.
    "users": frozenset(
        {"hashed_password", "email", "first_name", "last_name", "reviewer_pane_split"}
    ),
    "lenders": frozenset({"contact_email", "contact_phone"}),
    # LP-821 — the evidence table holds a SECOND COPY of exactly the four columns
    # `readonly.communications` already drops, plus the composed draft, plus a manifest of filenames
    # a sender chose. Excluded on identical reasoning: an audit record is not a reason to reproduce
    # a borrower's mail in the analytics path. What IS exposed answers "how much was sent, under
    # which template, with what firing, and was it edited" — the last as a boolean derived in the
    # view, so "was it edited" is answerable without either body.
    "communication_evidence": frozenset(
        {"sender", "recipient", "subject", "body_as_sent", "body_composed", "attachment_manifest"}
    ),
    # LP-818 adds `in_reply_to_message_id`: a sender-written `Message-ID`, which identifies one
    # message from one person. `external_message_id` beside it is already exposed for dedup
    # analysis, and a second copy of the same class of identifier buys nothing. `is_important` and
    # `read_at` are NOT here — they are exposed, because how much a company flags and how long mail
    # sits unread are facts about how it works and name nobody.
    # LP-834 adds `upload_link_url`: the plaintext upload token, a bearer credential, and the same
    # secret already inside `body` one entry along.
    "communications": frozenset(
        {
            "sender",
            "recipient",
            "subject",
            "body",
            "in_reply_to_message_id",
            "upload_link_url",
        }
    ),
    # LP-822 — a processor's writing voice. `greeting`, `closing` and `signature_block` are typed by
    # hand, which is where an identifier arrives in a form no scrubber predicts — the same reason
    # `dti_custom_lines.label` is excluded. `exemplars` is stronger than that: they are excerpts of
    # real borrower-request emails, so a borrower's NAME is the likeliest thing left in one, and a
    # name is not digit-shaped, so it would cross a scrubbing view intact. The view answers how many
    # people have set up a voice and when it last changed — NOT how many exemplars they gave.
    # `cardinality(exemplars)` would trip the NEVER_EXPOSED text check below, so the migration
    # chose the guarantee over the metric; its docstring explains the trade.
    "style_profiles": frozenset({"greeting", "closing", "signature_block", "exemplars"}),
    # LP-810 — the composed draft body. DROPPED, not scrubbed, and stricter than `needs_prose.why`
    # on purpose: a composed need reason is a sentence about one document, a composed draft body is a
    # whole borrower-facing email. `readonly.communications` already drops `body` for that reason and
    # this table holds the same content one step earlier. Scrubbing matches identifier shapes; an
    # email is prose, and a name has no shape.
    "email_draft_prose": frozenset({"body"}),
    # LP-803 — a borrower's inbound message. `subject` is prose they wrote about their own loan;
    # `from_address` and `to_addresses` identify people; `raw_storage_path` points at the whole
    # message. Dropped rather than scrubbed, matching `communications`, whose subject/sender/
    # recipient/body C7 dropped for the outbound direction with the same reasoning. The dedup and
    # threading identifiers go too: `message_id` and `ingest_key` are per-message identifiers, and
    # `ses_message_id` names one delivery to one person.
    # LP-804a — both filenames and the storage paths. `filename_original` is attacker-controlled
    # text a stranger wrote; the NORMALISED form still carries whatever the sender called their own
    # document, which on a mortgage file is routinely a name and a date. `sha256` is exposed: it is a
    # content address with no preimage, and it is how a scan verdict is matched back to an object.
    # LP-819 — `address` identifies one borrower's mailbox, and `diagnostic` is the provider's own
    # words, which routinely quote that address back in free text no scrub matches. What is left —
    # the reason, the status code, when — makes "how many hard bounces, and of what kind" answerable
    # without naming anybody.
    "suppressed_addresses": frozenset({"address", "diagnostic"}),
    # LP-805 — a participant list is a list of PEOPLE. Both columns identify one; what is left, the
    # role and whether they are trusted, answers "how many files have a trusted sender" without
    # naming anybody.
    "loan_file_participants": frozenset({"email", "name"}),
    # LP-805 — `participants` is a list of addresses and `subject_normalized` is prose a borrower
    # wrote. `root_message_id` identifies one conversation on one file.
    "email_threads": frozenset({"participants", "subject_normalized", "root_message_id"}),
    "inbound_attachments": frozenset(
        {"filename_original", "filename_normalized", "derived_storage_path"}
    ),
    "inbound_messages": frozenset(
        {
            "subject",
            "from_address",
            "to_addresses",
            "raw_storage_path",
            "ingest_key",
            "ses_message_id",
            "message_id",
            "in_reply_to",
            "references",
        }
    ),
}

#: Columns that must NEVER appear in any view, whatever else changes. A belt-and-braces
#: assertion over the whole migration text rather than per table.
NEVER_EXPOSED: tuple[tuple[str, str], ...] = (
    ("documents", "full_text"),
    # LP-636. Listing it in EXCLUDED only RECORDS the decision: a later migration that adds
    # it to a view would pass both drift tests and silently turn that entry into a stale
    # comment. This asserts absence from every view, so the decision cannot be undone
    # quietly. It is here rather than only in EXCLUDED because the argument for excluding it
    # is the strong form — the scrub matches identifier SHAPES, and a person's name is not
    # digit-shaped, so a name in this column would cross a view intact.
    ("documents", "document_name"),
    ("mismo_imports", "catch_all"),
    ("borrowers", "ssn"),
    ("users", "hashed_password"),
    ("loan_files", "inbox_token"),
    ("findings", "source_snippet"),
    ("communications", "body"),
    # LP-834, strong form and the same reason one line up: this column holds the plaintext upload
    # token, which is a BEARER CREDENTIAL. It is the same secret already inside `body` — the draft
    # remembers it so regeneration is lossless — and a scrub cannot help, because a scrubbed token is
    # either still usable or is not a token.
    ("communications", "upload_link_url"),
    # LP-810 — the same content one step earlier, and here for the same strong-form reason: an email
    # body is prose about a named person, which no scrub matches.
    ("email_draft_prose", "body"),
    # LP-803, strong form: a subject line is free prose a borrower wrote, and a name has no shape a
    # scrub can match. Same argument as `documents.document_name`.
    ("inbound_messages", "subject"),
    ("inbound_messages", "from_address"),
    # LP-804a, strong form: a filename a stranger chose is free text, and "Akash Patel W2 2025.pdf"
    # is exactly the shape no scrub matches.
    ("inbound_attachments", "filename_original"),
    # LP-819, strong form: a bounce diagnostic is a provider's free text that quotes the recipient's
    # address back — a mailbox and often a name, in a shape no scrub matches.
    ("suppressed_addresses", "diagnostic"),
    # LP-805, strong form: a participant's email IS the identifier the trust decision matches on,
    # and a name has no shape a scrub matches.
    ("loan_file_participants", "email"),
    # LP-822, and here for the strong-form reason rather than only to record the decision: an
    # exemplar is an excerpt of a real email to a real borrower, so what it most likely still
    # carries is a person's name — which no scrub matches, because a name has no shape. Exposing it
    # even scrubbed would put one borrower's details in an analytics view.
    ("style_profiles", "exemplars"),
    # LP-815, and the strongest form of all: `token_hash` is the VERIFIER of a bearer capability.
    # `loan_files.inbox_token` is already here for the same reason, and this one is worse in one
    # respect — the whole point of hashing it is that the database cannot be used to reach a loan
    # file, and a readonly view would put the verifier on the analytics path where the raw token
    # never was. Absence asserted rather than only recorded, because a later migration adding it
    # would pass both drift tests and turn an EXCLUDED entry into a stale comment.
    ("upload_links", "token_hash"),
    # LP-808, strong form and for the same reason as `loan_files.inbox_token` beside it: this token
    # IS the company's ingest address, so a view carrying it hands the capability to the analytics
    # path. Absence asserted rather than only recorded, because a later migration adding it would
    # pass both drift tests and turn the EXCLUDED entry into a stale comment.
    ("mailbox_connections", "token"),
)


def _later_view_redefinitions() -> dict[str, str]:
    """``{table: view text}`` for views a migration AFTER C7 recreates (LP-509-B1).

    A view is not frozen at C7. A later migration that adds a column has to rebuild the view to
    expose it, and reading only C7 would then check the drift guard against a definition the
    database no longer has — reporting the new column as unexposed when it is exposed, or worse,
    passing while a rebuilt view quietly dropped one.

    Scanned as TEXT across the versions directory rather than by importing: these modules import
    `alembic.op`, which is only bound inside a migration run. Later revisions win, and among them
    the last by filename — the versions are date-prefixed, so filename order is apply order.
    """
    bodies: dict[str, str] = {}
    for path in sorted(_MIGRATION.parent.glob("*.py")):
        if path.name <= _MIGRATION.name:
            continue
        # The schema is written either literally or as the `{_SCHEMA}` placeholder of an f-string —
        # C7 uses the placeholder and so do its successors, and this reads the file as TEXT, so the
        # placeholder is never substituted. Both spellings are accepted rather than requiring one,
        # so a migration that follows C7's own style is not silently skipped by this scan.
        # Only the UPGRADE body describes the live database. A downgrade that recreates the
        # previous shape is also a `CREATE ... VIEW` in the same file, and reading the whole file
        # let the ROLLBACK definition win — reporting a freshly exposed column as unexposed.
        text = path.read_text(encoding="utf-8")
        # ANCHORED TO THE START OF A LINE. Splitting on the bare substring let a DOCSTRING that
        # quoted the marker truncate the slice above the file's own SQL — the migration then
        # contributed nothing and the guard silently kept checking C7's definition. A function
        # definition is at column 0 and a docstring mention is indented, so anchoring removes that
        # trap at the root rather than detecting it afterwards.
        upgrade_body = re.split(r"^def downgrade\(", text, maxsplit=1, flags=re.MULTILINE)[0]
        seen_here: set[str] = set()
        for view in re.findall(
            # LP-568: `CREATE OR REPLACE VIEW` counts too. Appending a column is the one view
            # change Postgres allows without a drop, so it is the natural way to expose a new
            # column — and matching only the bare `CREATE VIEW` spelling made those rebuilds
            # INVISIBLE here. That is the failure this scanner exists to prevent, in reverse: a
            # replace that quietly dropped a column would have passed the guard unnoticed.
            r"CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+(?:readonly|\{_SCHEMA\})\.\w+\s+AS\s+"
            r"(SELECT.*?FROM\s+public\.\w+)",
            upgrade_body,
            re.DOTALL | re.IGNORECASE,
        ):
            match = re.search(r"FROM\s+public\.(\w+)", view)
            assert match, f"view without a public.<table> source in {path.name}"
            table = match.group(1)
            # THE OTHER TRAP, caught precisely. Hoisting both statements to module constants puts
            # the ROLLBACK one above the split too, where it overwrites the live definition and the
            # guard reports a freshly scrubbed column as bare. A legitimate upgrade never defines
            # one view twice above the split, so a repeat is unambiguous — unlike a whole-file
            # search, which also fires on a migration that only recreates a view in its DOWNGRADE
            # and on prose that merely quotes the SQL.
            if table in seen_here:
                raise AssertionError(
                    f"{path.name} defines readonly.{table} twice above its rollback function. "
                    "That is usually view SQL hoisted to module constants: the rollback statement "
                    "lands in the slice this scan reads as live and wins, so the drift guard "
                    "checks a definition the database does not have. Keep each statement inside "
                    "the function that runs it."
                )
            seen_here.add(table)
            bodies[table] = view

    return bodies


def _view_bodies() -> dict[str, str]:
    """``{table: the SELECT ... FROM public.<table> text}`` as the database has it TODAY.

    C7 defines the 32 views; a later migration may recreate one, and that later definition is the
    live one (see :func:`_later_view_redefinitions`).
    """
    module = _migration_module()
    bodies: dict[str, str] = {}
    for view in module._VIEWS:  # type: ignore[attr-defined]
        match = re.search(r"FROM\s+public\.(\w+)", view)
        assert match, f"view without a public.<table> source: {view[:80]}"
        bodies[match.group(1)] = view
    bodies.update(_later_view_redefinitions())
    return bodies


def test_every_view_targets_a_real_table() -> None:
    # `_all_tables()`, not `Base.metadata.tables`: the latter knows only the
    # models something has imported, so this test's answer depended on what else
    # was in the session — it would have called a perfectly real table unknown.
    tables = _all_tables()
    for table in _view_bodies():
        assert table in tables, f"readonly view over unknown table {table!r}"


# A table may legitimately have no readonly view; each one needs a reason here.
# Empty today, and that is the point: every application table is exposed. Alembic's
# own bookkeeping table is not in `Base.metadata`, so it never reaches this check.
EXCLUDED_TABLES: dict[str, str] = {}


def _all_tables() -> set[str]:
    """Every mapped table, with every model module imported first.

    `Base.metadata` only knows the models something has imported, and
    `app.models.__init__` does not export all of them — `finding_prose` is
    registered only when a test that uses it runs. So this check silently
    under-reported depending on what else was in the session: green alone, red in
    the full suite. Importing the package's modules makes the answer the same
    either way, which a guard has to be to be worth anything.
    """
    for path in sorted(Path(app_models.__file__).parent.glob("*.py")):
        if path.stem != "__init__":
            import_module(f"app.models.{path.stem}")
    return set(Base.metadata.tables)


def test_every_table_has_a_view_or_is_excluded() -> None:
    """A whole TABLE must be exposed or excluded — never simply forgotten.

    The column check below walks views and asks what they are missing, which
    cannot see a table that has no view at all. Two shipped that way —
    `needs_prose` and `finding_prose` — and `saved_views` would have been the
    third. Same decide-it-while-it-is-cheap discipline, one level up.
    """
    missing = sorted(_all_tables() - set(_view_bodies()) - set(EXCLUDED_TABLES))
    assert not missing, (
        "These tables have no readonly view and are not listed in EXCLUDED_TABLES. "
        "Decide for each: add a view (scrubbing any free text), or exclude it and "
        "say why.\n  " + "\n  ".join(missing)
    )


def test_excluded_tables_are_real() -> None:
    """An entry that names a table that no longer exists is a stale excuse."""
    unknown = sorted(set(EXCLUDED_TABLES) - _all_tables())
    assert not unknown, f"EXCLUDED_TABLES names tables that do not exist: {unknown}"


def _output_columns(view_sql: str) -> set[str]:
    """The names a view actually RETURNS, not the names that appear in its text.

    Substring-matching the select list is not the same question, and LP-UI-033's
    view is where the difference showed: `(corrected_value IS NOT NULL) AS
    has_corrected_value` contains the string `corrected_value`, so a `\bname\b`
    search called that column exposed while the view deliberately drops its VALUE
    and returns only a boolean. The check meant to force a decision was satisfied
    by a column being *mentioned in a predicate about itself*.

    So each select item is reduced to the name it comes out as: its alias if it has
    one, otherwise the bare column name. `scrub(x) AS x` still counts as exposing
    `x` — scrubbed is exposed, just not in the raw.

    DEPTH-AWARE, AND IT HAS TO BE. This used to take the text before the FIRST ``FROM`` and then
    the LAST ``SELECT`` in it. A nested select inside the select list — ``cardinality(ARRAY(SELECT
    jsonb_array_elements_text(x)))``, ordinary SQL for counting a jsonb array — moved both anchors:
    the inner ``SELECT`` won the ``rindex``, and everything before it was discarded. Measured on
    exactly that shape, the parser returned an EMPTY set, so every column in the table read as
    unexposed.

    That direction fails loudly only while the columns are absent from ``EXCLUDED``. List them and
    the guard passes while parsing nothing — and a column deliberately excluded but actually
    exposed would go unseen, which is the failure this whole file exists to prevent. LP-803 found
    it by writing such a view and rewriting it; the parser is fixed here so the next one does not
    have to.
    """
    upper = view_sql.upper()
    start = upper.index("SELECT") + len("SELECT")

    # Walk to the FROM that belongs to THIS select, ignoring any inside parentheses.
    depth, end = 0, len(view_sql)
    i = start
    while i < len(view_sql):
        char = view_sql[i]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif (
            depth == 0
            and upper.startswith("FROM", i)
            # A WORD BOUNDARY ON BOTH SIDES. `from_outcome` is a real column on
            # `finding_events`, and checking only the character BEFORE the keyword matched it —
            # truncating that view's select list at the very column it was meant to read. Found by
            # running the suite after the first version of this fix, not by re-reading it.
            and (i == 0 or not (view_sql[i - 1].isalnum() or view_sql[i - 1] == "_"))
            and (
                i + 4 >= len(view_sql) or not (view_sql[i + 4].isalnum() or view_sql[i + 4] == "_")
            )
        ):
            end = i
            break
        i += 1
    select_part = view_sql[start:end]

    items, depth, current = [], 0, ""
    for char in select_part:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            items.append(current)
            current = ""
        else:
            current += char
    items.append(current)

    names: set[str] = set()
    for item in items:
        item = " ".join(item.split())
        if not item:
            continue
        alias = re.search(r"\bAS\s+(\w+)$", item, re.IGNORECASE)
        if alias:
            names.add(alias.group(1))
        elif re.fullmatch(r"\w+", item):
            names.add(item)
    return names


def test_no_model_column_drifts() -> None:
    """A model column must be exposed by its view or explicitly excluded — never neither.

    This is the test that stops silent rot. When someone adds a column, it fails here
    until they decide, which is exactly when the decision is cheap and reviewable.
    """
    bodies = _view_bodies()
    problems: list[str] = []

    for table_name, view_sql in bodies.items():
        table = Base.metadata.tables[table_name]
        excluded = EXCLUDED.get(table_name, frozenset())
        exposed = _output_columns(view_sql)
        for column in table.columns:
            name = column.name
            if name not in exposed and name not in excluded:
                problems.append(f"{table_name}.{name}")

    assert not problems, (
        "These model columns are neither exposed by a readonly view nor listed in "
        "EXCLUDED. Decide for each: expose it, or exclude it and say why in the "
        "migration.\n  " + "\n  ".join(sorted(problems))
    )


def test_excluded_columns_are_real() -> None:
    """An exclusion naming a column that no longer exists is stale — and hides drift."""
    stale: list[str] = []
    for table_name, columns in EXCLUDED.items():
        table = Base.metadata.tables.get(table_name)
        assert table is not None, f"EXCLUDED names unknown table {table_name!r}"
        for name in columns:
            if name not in table.columns:
                stale.append(f"{table_name}.{name}")
    assert not stale, f"EXCLUDED names columns that do not exist: {sorted(stale)}"


@pytest.mark.parametrize(("table", "column"), NEVER_EXPOSED)
def test_never_exposed_columns_are_absent_from_every_view(table: str, column: str) -> None:
    """The highest-consequence columns, asserted against EVERY view.

    Every one, not just the view sourced from that table: a column reaches a result set
    through whichever view selects it, so a join, a renamed table or a second view over
    the same base table would carry it past a per-table check.
    """
    bodies = _view_bodies()
    assert table in bodies, f"no readonly view for {table}"

    exposed_by = [
        source
        for source, body in bodies.items()
        if re.search(rf"\b{re.escape(column)}\b", body.split("FROM")[0]) is not None
    ]
    assert not exposed_by, (
        f"{table}.{column} is exposed by the readonly view(s) for {sorted(exposed_by)}. "
        "This column can carry a raw identifier; it must never be selectable."
    )


# --------------------------------------------------------------------------- #
# 4. The connection URL — the IAM token must reach asyncpg intact
# --------------------------------------------------------------------------- #

#: The shape of a real RDS IAM auth token: a host, then a signed query string carrying
#: `%2F`, `=`, `+` and `/`. Every one of those is a character a URL round trip can re-quote.
_FAKE_TOKEN = (
    "mbai-staging.c45amqau4ov5.us-east-1.rds.amazonaws.com:5432/?Action=connect"
    "&DBUser=mbai_readonly&X-Amz-Algorithm=AWS4-HMAC-SHA256"
    "&X-Amz-Credential=ASIA123%2F20260815%2Fus-east-1%2Frds-db%2Faws4_request"
    "&X-Amz-Signature=ab+cd/ef=gh"
)


def test_readonly_url_carries_the_token_verbatim(monkeypatch: pytest.MonkeyPatch) -> None:
    """The token must survive as the password, uncensored and unmangled.

    This is the regression that made the query stage unusable: the function ended with
    ``str(url.set(password=token))``, and ``URL.__str__`` hides the password by default —
    so asyncpg was handed the literal ``***``. PostgreSQL answered ``PAM authentication
    failed``, which looks exactly like a rejected token or a missing ``rds-db:connect``
    grant, and cost an investigation to tell apart (docs/findings/query-stage-auth.md).
    """
    from app.scripts import run_query

    monkeypatch.delenv("QUERY_DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://mbai_admin:secret@db.example.com:5432/mortgageboss"  # pragma: allowlist secret
        "?ssl=verify-full",
    )
    monkeypatch.setattr(run_query, "_iam_auth_token", lambda **_: _FAKE_TOKEN)

    url = run_query._readonly_database_url()

    assert url.password == _FAKE_TOKEN, "the IAM token was altered on the way to asyncpg"
    assert url.password != "***", "the token was replaced by the hidden-password marker"
    assert url.username == "mbai_readonly"
    assert url.host == "db.example.com", "the token is signed over the host — it must match"
    assert url.port == 5432
    assert dict(url.query) == {"ssl": "verify-full"}, "IAM auth requires SSL"

    # And it survives a render/parse cycle, so passing it on as a string stays safe.
    from sqlalchemy.engine import make_url

    assert make_url(url.render_as_string(hide_password=False)).password == _FAKE_TOKEN


def test_readonly_url_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """QUERY_DATABASE_URL is the escape hatch; it must not go near the IAM path."""
    from app.scripts import run_query

    monkeypatch.setenv(
        "QUERY_DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/d"
    )  # pragma: allowlist secret
    monkeypatch.setattr(
        run_query,
        "_iam_auth_token",
        lambda **_: pytest.fail("the override must not generate an IAM token"),
    )

    url = run_query._readonly_database_url()
    assert url.username == "u"
    assert url.password == "p"  # pragma: allowlist secret
    assert url.host == "h"


# --------------------------------------------------------------------------- #
# 5. run_query's statement guard (defence in depth, not the control)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "sql",
    [
        "select 1",
        "SELECT count(*) FROM loan_files",
        # The regression that motivated these tests: an unanchored strip collapsed
        # `select status` to `selectstatus` and refused a valid query.
        "select status, count(*) from verifications group by status order by 2 desc",
        "  \n  select 1",
        "-- why is IN-3 firing?\nselect count(*) from findings",
        "/* a block comment */ select 1",
        "with x as (select 1 as n) select n from x",
        "select 1;",  # one trailing semicolon is fine
        # A ';' inside a string literal or a comment is not a second statement. Reading
        # the raw text refused these, and the operator had to work around the guard.
        "select id from findings where message like '%;%'",
        "-- count things; fast\nselect 1",
        "select 1 /* a; b */",
        "select 'it''s here; really' as quoted",
        # Write VERBS inside a literal or an identifier are equally not writes.
        "select id from rules where rule_id like '%delete%'",
        # ...and a column whose name merely starts with one is untouched by \\b.
        "select created_at, updated_at, deleted_at from findings",
    ],
)
def test_validate_sql_accepts_a_single_select(sql: str) -> None:
    from app.scripts.run_query import validate_sql

    assert validate_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "",
        "   ",
        "update loan_files set status = 'x'",
        "delete from findings",
        "insert into findings (id) values (gen_random_uuid())",
        "drop view readonly.findings",
        "create table x (i int)",
        "grant select on all tables in schema public to mbai_readonly",
        "select 1; drop table findings",  # a second statement
        "truncate findings",
        # A data-modifying CTE starts with a legal `with`, so only the verb scan catches it.
        "with x as (delete from findings returning 1) select * from x",
        "with x as (insert into findings (id) values (gen_random_uuid()) returning id)"
        " select * from x",
        "with x as (update loan_files set status = 'x' returning id) select * from x",
    ],
)
def test_validate_sql_refuses_everything_else(sql: str) -> None:
    from app.scripts.run_query import QueryRefused, validate_sql

    with pytest.raises(QueryRefused):
        validate_sql(sql)


# --------------------------------------------------------------------------- #
# LP-635 — a run's failure reason is scrubbed like every other free-text column
# --------------------------------------------------------------------------- #
def test_a_runs_error_detail_is_scrubbed() -> None:
    """C7 scrubs `error_detail` on `readonly.communications` and selected the identically-named
    column BARE on `readonly.verifications`.

    That was defensible while only this repo's own composed strings reached it. LP-635 widened who
    writes it: `_failure_detail` asks an exception to explain itself through `user_detail` and writes
    the result verbatim, so the column's safety became a promise about every exception that might
    ever define that attribute — the shape we removed from `AiBackendUnavailable`'s constructor,
    reappearing one level up at the protocol.
    """
    view = _view_bodies()["verifications"]
    assert re.search(r"scrub\(\s*error_detail\s*\)", view), (
        "verifications.error_detail is selected bare; a reason written from an exception would "
        "reach a transcript unredacted"
    )


def test_scrubbing_does_not_damage_the_reasons_a_processor_reads() -> None:
    """The other half, and why this was close to free: `scrub` redacts identifier SHAPES, so the
    failure messages LP-635 composes pass through untouched.

    READ FROM THE SHIPPED VALUES, not from copies. The first version of this test hand-copied the
    three strings, and one had already drifted — a third sentence was added to the timeout message
    in a later round and the copy never grew it. So the untested tail could acquire something
    scrub-shaped ("raise it with support (ref 8005551234)") and be redacted in the one field a
    processor reads, while this test went on passing. A test that names a mechanism has to exercise
    the real thing.
    """
    from app.tasks.verification_rules import _FAILURE_DETAIL, _failure_detail
    from app.verification.tag_materialization.breaker import AiBackendUnavailable

    messages = (
        *_FAILURE_DETAIL.values(),
        str(AiBackendUnavailable(consecutive=5)),
        _failure_detail(RuntimeError("anything")),  # the generic fallback line
    )
    assert len(messages) >= 3, "the failure messages moved — this test is no longer reading them"

    ssn_like = re.compile(r"\b\d{3}[- ]\d{2}[- ]\d{4}\b|\b\d{9,}\b")
    for message in messages:
        assert not ssn_like.search(message), f"scrub would redact part of: {message!r}"


def test_an_extractions_error_detail_is_scrubbed() -> None:
    """THE SIBLING OF THE COLUMN ABOVE, and the one carrying the most sensitive text of the three.

    There are three `error_detail` columns in the readonly schema. C7 scrubbed exactly one
    (`communications`); round 4 fixed `verifications`; this is `extractions`, and it is written from
    `failure_detail(status, reasoning)` — the model's FREE TEXT for why an extraction failed.

    The codebase already knows what that can contain. `document_processing.py` refuses to put it in
    the document's `processing_error` because "for an all-null-parse FAILED it is the model's
    free-text reasoning and can quote document details", and sends it here instead as "THE
    ACCESS-CONTROLLED PLACE FOR IT". That reasoning only holds if it is actually access-controlled;
    through this view it was not, and the query stage returns rows into a terminal and a transcript.
    """
    view = _view_bodies()["extractions"]
    assert re.search(r"scrub\(\s*error_detail\s*\)", view), (
        "extractions.error_detail is selected bare — it holds model prose the pipeline deliberately "
        "keeps out of the UI-shown column, so it must not reach a transcript unredacted"
    )


def test_every_error_detail_in_the_readonly_schema_is_scrubbed() -> None:
    """The property, so the next one is not found one at a time.

    Three columns share this name and three separate migrations decided about them independently —
    which is how two ended up bare while the third was scrubbed. A fourth table with an
    `error_detail` should fail here rather than wait to be noticed.
    """
    unscrubbed = []
    for table, body in _view_bodies().items():
        select_part = body.split("FROM")[0]
        if not re.search(r"\berror_detail\b", select_part):
            continue
        if not re.search(r"scrub\(\s*error_detail\s*\)", select_part):
            unscrubbed.append(table)

    assert not unscrubbed, (
        f"these views select error_detail without scrubbing it: {sorted(unscrubbed)}. It is a "
        "free-text column and free text is where identifiers hide."
    )


# --------------------------------------------------------------------------------------------- #
# Two things LP-822's review found were unguarded
# --------------------------------------------------------------------------------------------- #
def test_every_model_module_is_reachable_from_app_models() -> None:
    """A model that `app.models` does not import is invisible to `Base.metadata`, and `env.py`
    builds `target_metadata` from exactly that.

    The consequence is not cosmetic. Autogenerate compares the live database against
    `target_metadata`; a table that exists in one and not the other is a table autogenerate
    proposes to DROP. Measured on LP-822 before this test existed: `style_profiles` was missing
    from `app/models/__init__.py`, and `Base.metadata` held 42 tables with it absent, so the next
    `--autogenerate` would have written a migration dropping a table that had just been created.

    The suite did not notice because `create_all` builds the schema from whatever the test session
    happened to import, and the LP-822 tests import the model directly.
    """
    import app.models as models_pkg

    for path in sorted(Path(models_pkg.__file__).parent.glob("*.py")):
        if path.stem in {"__init__", "base", "types", "mixins"}:
            continue
        module = import_module(f"app.models.{path.stem}")
        for name, obj in vars(module).items():
            if (
                isinstance(obj, type)
                and issubclass(obj, Base)
                and obj is not Base
                and obj.__module__ == module.__name__
                and hasattr(obj, "__tablename__")
            ):
                assert getattr(models_pkg, name, None) is obj, (
                    f"{name} ({path.name}) is not importable from app.models — "
                    f"alembic's target_metadata will not contain {obj.__tablename__}, and "
                    f"--autogenerate will propose dropping that table"
                )


async def test_the_lp809_views_are_valid_sql(db_session: AsyncSession) -> None:
    """LP-809's two views, executed rather than only string-matched — the same gap LP-822's review
    found, in the migration that comes after it.

    One is NEW (`communication_needs_items`) and one is a REBUILD (`communications`, gaining
    `template_key` and `template_version`). The rebuild is the more dangerous of the two: it drops a
    view that already exists and recreates it, so a mistake does not merely fail to add a view, it
    leaves the deploy with none — and the checks above would still pass, because they read the
    migration's text and the text is syntactically fine.

    The rebuilt view calls `readonly.scrub`, so the function is installed first; without it the
    failure would be "no such function" rather than anything about this migration.
    """
    c7 = _migration_module()
    module = _view_module("b8d5e0a17c42")
    await db_session.execute(sa.text("CREATE SCHEMA IF NOT EXISTS readonly"))
    await db_session.execute(sa.text(c7._SCRUB_FN))  # type: ignore[attr-defined]
    await db_session.execute(sa.text("DROP VIEW IF EXISTS readonly.communications"))
    await db_session.execute(sa.text("DROP VIEW IF EXISTS readonly.communication_needs_items"))
    await db_session.execute(sa.text(module._COMMUNICATIONS_VIEW))  # type: ignore[attr-defined]
    await db_session.execute(sa.text(module._JOIN_VIEW))  # type: ignore[attr-defined]

    exposed = {
        (row.table_name, row.column_name)
        for row in (
            await db_session.execute(
                sa.text(
                    "SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema = 'readonly' "
                    "AND table_name IN ('communications', 'communication_needs_items')"
                )
            )
        ).all()
    }
    # The two columns the rebuild exists to add.
    assert ("communications", "template_key") in exposed
    assert ("communications", "template_version") in exposed
    # And the content C7 dropped is still dropped. A rebuild is exactly where that comes back by
    # accident, because the new view is written fresh rather than altered.
    for column in ("body", "subject", "sender", "recipient"):
        assert ("communications", column) not in exposed


async def test_the_style_profiles_view_is_valid_sql(db_session: AsyncSession) -> None:
    """LP-822's review — the view's DDL had nothing that ever RAN it.

    `EXCLUDED` and `NEVER_EXPOSED` above match against the migration's TEXT, which catches a column
    that should not be exposed but cannot catch a view that does not compile: a mistyped column or a
    bad expression passes every check here and fails at `alembic upgrade head` on deploy. The
    `readonly.saved_views` test above already executes its view for this reason; this does the same
    for the view LP-822 added.
    """
    module = _view_module("e4a1c7d90b3f")
    await db_session.execute(sa.text("CREATE SCHEMA IF NOT EXISTS readonly"))
    await db_session.execute(sa.text("DROP VIEW IF EXISTS readonly.style_profiles"))
    await db_session.execute(sa.text(module._VIEW))  # type: ignore[attr-defined]

    columns = (
        await db_session.execute(
            sa.text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'readonly' AND table_name = 'style_profiles'"
            )
        )
    ).scalars()
    exposed = set(columns)

    # It compiles, and it exposes what it claims to: identity and shape, no content.
    assert exposed == {"id", "user_id", "has_signature_block", "created_at", "updated_at"}
    for hidden in EXCLUDED["style_profiles"]:
        assert hidden not in exposed


# --------------------------------------------------------------------------------------------- #
# The guard's own parser (LP-803 review finding)
# --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("view_sql", "expected"),
    [
        # The ordinary case.
        ("SELECT id, company_id, created_at FROM public.t", {"id", "company_id", "created_at"}),
        # A NESTED SELECT in the select list. `cardinality(ARRAY(SELECT ...))` is ordinary SQL for
        # counting a jsonb array, and it used to return an EMPTY set — every column of the table
        # then read as unexposed, which fails loudly only while those columns are absent from
        # EXCLUDED. List them and the guard passes while parsing nothing.
        (
            "SELECT id, cardinality(ARRAY(SELECT jsonb_array_elements_text(x))) AS n, created_at "
            "FROM public.t",
            {"id", "n", "created_at"},
        ),
        # A COLUMN WHOSE NAME BEGINS WITH THE `FROM` KEYWORD. `finding_events.from_outcome` is real,
        # and the first version of the fix above truncated that view's select list on it.
        (
            "SELECT id, from_outcome, to_outcome, readonly.scrub_jsonb(detail) AS detail, "
            "occurred_at FROM public.finding_events",
            {"id", "from_outcome", "to_outcome", "detail", "occurred_at"},
        ),
        # A function call containing a comma, which the depth-aware comma split must not break on.
        (
            "SELECT id, coalesce(a, b) AS merged FROM public.t",
            {"id", "merged"},
        ),
    ],
)
def test_the_select_list_parser_reads_the_columns_a_view_returns(
    view_sql: str, expected: set[str]
) -> None:
    """`_output_columns` decides what every other check in this file is checking.

    It is worth its own test because it fails SILENTLY: a mis-parse does not raise, it returns a
    smaller set, and a smaller set means "not exposed" — which is indistinguishable from a view that
    genuinely drops the column. The two cases in the middle are both taken from views in this repo.
    """
    assert _output_columns(view_sql) == expected


def test_every_migration_that_recreates_a_readonly_view_regrants_it() -> None:
    """LP-842 — DROPPING A VIEW DROPS ITS GRANTS, and nothing else here notices.

    `CREATE OR REPLACE VIEW` cannot change a column list, so adding a column means `DROP VIEW` then
    `CREATE VIEW` — and Postgres takes the privileges with the old view. The rebuilt view exists, has
    the right columns, passes `test_no_model_column_drifts`, and `mbai_readonly` can no longer read
    it. The whole staging query path returns "permission denied for view" and the drift guard that
    exists to police these rebuilds says nothing, because a grant is not a column.

    Found by writing exactly that bug: this ticket's first rebuild of `readonly.needs_items` dropped
    both the grant AND three columns a later migration had added, because it was copied from C7
    rather than from the current definition. The columns were caught. The grant would have reached
    staging.

    A RULE OVER THE TREE, not a list of migrations, for the reason b7's field-name guard gives: a
    list goes stale exactly when someone adds the migration it needed to cover.
    """
    import re

    offenders = []
    checked = 0
    for path in sorted(_MIGRATION.parent.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        # THE FUNCTION BODY, not everything above `downgrade`. The first version sliced from the
        # top of the file, so a module-level `_GRANT = """… GRANT SELECT …"""` constant satisfied
        # the check whether or not `upgrade()` ever executed it — and the mutant that deleted the
        # `op.execute(_GRANT)` call passed. The constant's EXISTENCE is not the property; running it
        # is.
        if "\ndef upgrade" not in text:
            continue
        upgrade = text.split("\ndef upgrade", 1)[1].split("\ndef downgrade", 1)[0]
        # Only migrations that RECREATE one — C7 creates them all and grants in its own block.
        if path.name == _MIGRATION.name:
            continue
        views = set(re.findall(r"CREATE VIEW\s+(?:\{_SCHEMA\}|readonly)\.(\w+)", upgrade))
        if not views:
            continue
        checked += 1
        if "GRANT SELECT" not in upgrade and "_GRANT" not in upgrade:
            offenders.append(f"{path.name} recreates {sorted(views)} and never re-grants")

    assert not offenders, "\n".join(offenders)
    # THE CONTROL: a tree where no migration recreates a view satisfies the line above.
    assert checked > 0, "no migration recreates a readonly view; this test proved nothing"
