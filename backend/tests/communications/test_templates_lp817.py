"""LP-817 — the five templates, their version pins, and what a borrower actually receives.

Until LP-810's drafting flag flips, this module is not a fallback — it is the only path every
borrower-facing email in M1 takes. So the tests are about what reaches a person's inbox:

* a placeholder that never got substituted, sitting in the body as `$inbox_address`;
* a template edited in place while the audit record still names version v1, so every historical row
  claims an email said something it did not;
* a document list asking the borrower for an appraisal the lender ordered;
* a catalog slug where an English name should be.

None of those raise on their own, and none are visible in a diff of the sending code.
"""

from __future__ import annotations

import re

import pytest
from app.communications.templates import (
    _TEMPLATES_DIR,
    PLAIN_FRAMING_FINGERPRINT,
    SECURITY_CAUTION,
    SECURITY_NOTICE,
    TEMPLATES,
    VERSION_FINGERPRINTS,
    TemplateError,
    TemplateKey,
    _load,
    file_fingerprint,
    placeholders,
    plain_framing,
    plain_framing_fingerprint,
    render,
    render_document_block,
)

#: A context supplying every variable any template declares, so one fixture renders all five.
_CONTEXT = {
    "borrower_first_name": "Akash",
    "processor_name": "Priya",
    "loan_reference": "LF-6T3N",
    "document_list": "- Bank statements",
    "inbox_address": "lf-token@inbox.example.com",
    "status_summary": "The appraisal came back on Tuesday.",
    "next_step": "We expect the underwriter's decision this week.",
    "condition_list": "- A letter of explanation",
    # LP-810 — the initial request's three framing slots. Supplied here rather than defaulted, so the
    # declared-variables test still compares the file against the spec in both directions.
    "opening": "We are working through your file.",
    "bridge": "Here is what we still need:",
    "closing": "Ask us if anything is unclear.",
    "subject_line": "About your loan",
    "message_body": "Just a note.",
}

#: The templates that hand the borrower somewhere to send documents. M3's routing depends on the
#: address appearing in the initial request; the others are asks, so they carry it for the same
#: reason. `status_update` and `custom` are excluded — neither asks for anything.
#:
#: LP-824 REVIEW — DERIVED FROM THE SPEC, NOT LISTED. This was a hand-maintained set of three, and
#: the build flagged the risk itself: a template that starts asking for documents without being
#: added here does not inherit the requirement, and nothing says so. It does not have to be a list.
#: A template that asks for documents by email is exactly one that declares `inbox_address` among
#: its variables — that is what "hands the borrower somewhere to send documents" MEANS — and the
#: spec already states it. Measured: this picks out the same three today, and a fourth inherits the
#: requirement the moment it declares the slot.
_ADDRESS_BEARING = {key for key, spec in TEMPLATES.items() if "inbox_address" in spec.variables}


# --------------------------------------------------------------------------------------------- #
# The registry
# --------------------------------------------------------------------------------------------- #
def _raw(stem: str, version: str) -> str:
    """The template file's raw text, for tests that compare words across versions."""
    return (_TEMPLATES_DIR / f"{stem}.{version}.txt").read_text(encoding="utf-8")


def _raw_framing(stem: str, version: str) -> str:
    return (_TEMPLATES_DIR / f"framing.{stem}.{version}.txt").read_text(encoding="utf-8")


def test_all_five_templates_are_registered() -> None:
    """Spec 4.1 names five. A key with no spec is a draft that cannot render at all."""
    assert set(TEMPLATES) == set(TemplateKey)
    assert len(TemplateKey) == 5


def test_declared_variables_match_the_files_exactly() -> None:
    """Both directions. A placeholder in the file that the spec does not declare is never supplied,
    so it survives into the sent body; a declared variable the file does not use makes callers
    assemble context for nothing and hides that the template stopped using it."""
    for key, spec in TEMPLATES.items():
        in_file = placeholders(key, spec.version)
        assert in_file == spec.variables, (
            f"{key.value}: file uses {sorted(in_file)}, spec declares {sorted(spec.variables)}"
        )


# --------------------------------------------------------------------------------------------- #
# Versioning — enforced, not documented
# --------------------------------------------------------------------------------------------- #
def test_every_template_file_matches_its_version_pin() -> None:
    """The audit record stores template + version and is evidence. Editing a template's wording
    while leaving the version at v1 would make every historical row claim an email said something it
    did not — and nothing else in the system would notice. Changing the words means adding a version."""
    for key, spec in TEMPLATES.items():
        pinned = VERSION_FINGERPRINTS.get((key, spec.version))
        assert pinned is not None, f"{key.value} {spec.version} has no pinned fingerprint"
        assert file_fingerprint(key, spec.version) == pinned, (
            f"{key.value} {spec.version} was edited without a version bump"
        )


def test_no_fingerprint_is_pinned_twice() -> None:
    """Two versions with the same hash means one of them was never really a new version — the pin
    was copied forward and the words did not change, so the audit record's distinction is fiction."""
    assert len(set(VERSION_FINGERPRINTS.values())) == len(VERSION_FINGERPRINTS)


# --------------------------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("key", list(TemplateKey))
def test_rendering_leaves_no_placeholder_behind(key: TemplateKey) -> None:
    """The failure this file exists for. `safe_substitute` would put `$inbox_address` in a real
    email and nothing downstream inspects a rendered body."""
    rendered = render(key, _CONTEXT)
    assert "$" not in rendered.subject
    assert "$" not in rendered.body
    assert rendered.subject.strip()
    assert rendered.body.strip()


@pytest.mark.parametrize("key", list(TemplateKey))
def test_the_rendered_result_names_what_rendered_it(key: TemplateKey) -> None:
    """Subject, body, key and version travel together so an audit row cannot record one template's
    identity against another's words."""
    rendered = render(key, _CONTEXT)
    assert rendered.template_key is key
    assert rendered.version == TEMPLATES[key].version


def test_a_missing_variable_refuses_rather_than_rendering_a_gap() -> None:
    """A bug in the caller should surface before the send, not after — and `$loan_reference` in a
    borrower's subject line is not something an apology fixes."""
    context = dict(_CONTEXT)
    del context["loan_reference"]
    with pytest.raises(TemplateError, match="loan_reference"):
        render(TemplateKey.INITIAL_DOCUMENTATION_REQUEST, context)


def test_rendering_is_deterministic() -> None:
    """The plain path is plain: same inputs, same bytes, no model, nothing to vary between the
    preview a processor approves and the message that goes out."""
    first = render(TemplateKey.REMINDER_FOLLOW_UP, _CONTEXT)
    second = render(TemplateKey.REMINDER_FOLLOW_UP, _CONTEXT)
    assert first == second


# --------------------------------------------------------------------------------------------- #
# What every template must say
# --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("key", list(TemplateKey))
def test_every_template_carries_the_security_caution(key: TemplateKey) -> None:
    """A fixed decision in the execution protocol: borrowers are told email is not secure. Asserted
    on the RENDERED body, not the file, because that is what the borrower reads.

    LP-824 SPLIT THE CONSTANT. The caution is universal; the sentence that follows it is not. A
    template that asks for documents has to offer a route out of email, and one that asks for
    nothing has nothing to offer a route out of — `test_the_status_update_does_not_ask_and_then_
    offer_a_route_out` already said so about placement, and the wording follows the same line.
    """
    assert SECURITY_CAUTION in render(key, _CONTEXT).body


@pytest.mark.parametrize("key", sorted(_ADDRESS_BEARING))
def test_every_asking_template_offers_a_route_that_names_something(key: TemplateKey) -> None:
    """LP-824 — THE DEFECT, AS A CLASS RATHER THAN AS THE ONE THAT WAS REPORTED.

    A processor reported the initial request: it says "reply to this message with them attached, or
    send them to $inbox_address" and then, four lines later, that email is not a fully secure channel
    and to "reply and tell us and we will arrange another route". The instruction and the caveat
    cancel out, and the route named nothing anybody could act on.

    THE SAME WORDS WERE IN TWO MORE TEMPLATES — the reminder and the condition request — neither of
    which anything renders yet. Bumped with the reported one, because leaving them would ship this
    on the day somebody wires them up, with nothing to say it was known.

    Parametrized over `_ADDRESS_BEARING` rather than listed, so a fourth asking template inherits
    the requirement instead of quietly not having it.
    """
    assert SECURITY_NOTICE in render(key, _CONTEXT).body


def test_the_notice_names_the_route_but_never_a_url() -> None:
    """WHY IT NAMES THE LINK BUT DOES NOT CARRY ONE, which is the whole reason this is a wording
    change and not a plumbing one.

    The plaintext token exists only in `MintedLink` at the moment of minting — the row holds a hash
    — so no URL can be rebuilt for an email composed later. A URL in a stored template would have to
    be a live credential sitting in `communications.body`, and a URL that resolved to nothing would
    be worse in a borrower's inbox than no URL at all.

    That second half was this test's original reasoning, when it also asserted the word "link" was
    absent because "steering to an upload link is LP-815's". LP-815 has since shipped: a processor
    can mint one from the communication page, so "reply and ask" is now an instruction we can
    honour. The URL half of the rule is unchanged and is what is asserted here.
    """
    assert "http" not in SECURITY_NOTICE
    assert "upload link" in SECURITY_NOTICE.lower(), "the route has to name something"
    # The vague form it replaced, kept as a literal so a revert reads as a failure rather than as a
    # rewording nobody notices.
    assert "arrange another route" not in SECURITY_NOTICE


@pytest.mark.parametrize("key", sorted(_ADDRESS_BEARING))
def test_the_asking_templates_give_the_inbox_address(key: TemplateKey) -> None:
    """M3's routing depends on the borrower having been given the address. A template that asks for
    documents without saying where to send them is an ask with no answer."""
    assert _CONTEXT["inbox_address"] in render(key, _CONTEXT).body


@pytest.mark.parametrize("key", sorted(set(TemplateKey) - _ADDRESS_BEARING))
def test_the_non_asking_templates_do_not(key: TemplateKey) -> None:
    """The control for the test above — without it, an address in all five would pass that one and
    say nothing about whether the distinction is real."""
    assert "inbox_address" not in TEMPLATES[key].variables


# --------------------------------------------------------------------------------------------- #
# The plain framing, and the version that introduced its slots (LP-810)
# --------------------------------------------------------------------------------------------- #
def test_the_initial_request_is_at_v3_and_the_older_versions_still_resolve() -> None:
    """ADR-401's mechanism doing its job. LP-810 needed three framing slots, so the file changed —
    which means a NEW VERSION, not an edit. v1's fingerprint stays pinned and its file stays on disk,
    so an audit row naming v1 still resolves to the words it named.

    This is the first bump, and it is the case the pin exists for: an in-place edit here would have
    left every v1 audit row describing an email that no longer exists in that form."""
    assert TEMPLATES[TemplateKey.INITIAL_DOCUMENTATION_REQUEST].version == "v3"
    assert (TemplateKey.INITIAL_DOCUMENTATION_REQUEST, "v1") in VERSION_FINGERPRINTS
    assert (TemplateKey.INITIAL_DOCUMENTATION_REQUEST, "v2") in VERSION_FINGERPRINTS


@pytest.mark.parametrize(("key", "version"), sorted((k.value, v) for k, v in VERSION_FINGERPRINTS))
def test_every_pinned_version_still_resolves_to_the_words_it_names(key: str, version: str) -> None:
    """LP-824 REVIEW — ADR-401's GUARANTEE, FOR EVERY VERSION RATHER THAN FOR ONE TEMPLATE.

    `test_every_template_file_matches_its_version_pin` checks each template's CURRENT version only,
    and the superseded ones were covered by a hand-written loop over the initial request's `("v1",
    "v2")`. So LP-824, which superseded `reminder_follow_up.v1` and `condition_response_request.v1`,
    created two historical versions that nothing protected.

    Measured before this test existed: rewriting `reminder_follow_up.v1`'s security sentence to
    "Email is perfectly safe." left the whole suite green, while the identical edit to
    `initial_documentation_request.v1` failed — one template guarded, two not.

    That is the exact failure ADR-401 exists to prevent, and it is worse for a superseded version
    than for a current one: a live template that drifts is visible in the next email somebody reads,
    where a v1 audit row is old, unread until an auditor asks, and has nothing else to speak for it.

    Parametrized over the pin table itself, so the next bump is covered by having been pinned rather
    than by somebody remembering to widen a tuple.
    """
    template_key = TemplateKey(key)
    assert (
        file_fingerprint(template_key, version) == VERSION_FINGERPRINTS[(template_key, version)]
    ), (
        f"{key} {version} was edited under its own pin — an audit row naming it now describes words that no longer exist"
    )


def test_the_plain_framing_file_matches_its_pin() -> None:
    """The sentences a borrower reads with the drafting flag OFF. Pinned like a template, because
    they are exactly as borrower-facing as one and must be as unable to change silently."""
    assert plain_framing_fingerprint() == PLAIN_FRAMING_FINGERPRINT


def test_the_plain_framing_is_v1s_own_wording() -> None:
    """The claim the version bump rests on: with the flag off, a reader sees what v1 sent. Asserted
    against v1's FILE rather than against a copy of the sentences, so it cannot drift into agreeing
    with itself."""
    v1_body = _load(TemplateKey.INITIAL_DOCUMENTATION_REQUEST, "v1")[1]
    framing = plain_framing()
    for sentence in (framing.opening, framing.bridge, framing.closing):
        assert sentence in v1_body, f"not in v1: {sentence!r}"


def test_the_plain_render_still_reads_like_v1() -> None:
    """End to end: the plain path produces v1's sentences in v1's order, around the same list."""
    body = render(TemplateKey.INITIAL_DOCUMENTATION_REQUEST, {**_CONTEXT, **_plain_slots()}).body
    framing = plain_framing()
    assert body.index(framing.opening) < body.index(framing.bridge) < body.index(framing.closing)


def _plain_slots() -> dict[str, str]:
    framing = plain_framing()
    return {"opening": framing.opening, "bridge": framing.bridge, "closing": framing.closing}


# --------------------------------------------------------------------------------------------- #
# The document block — where LP-800 stops being a data structure
# --------------------------------------------------------------------------------------------- #
def test_the_block_renders_the_full_guidance() -> None:
    block = render_document_block(("bank_statement",))
    assert "Bank statements — the two most recent months" in block
    assert "Where to get it:" in block
    assert "What we need to see:" in block
    assert "page 1 of 5" in block


def test_a_party_only_type_still_gets_an_english_name() -> None:
    """Most of the 166 types have no full entry. They must still render as words — the slug is an
    internal identifier and reads as a system leak in a borrower's inbox."""
    block = render_document_block(("proof_of_occupancy",))
    assert "proof of occupancy" in block
    assert "proof_of_occupancy" not in block


def test_no_slug_survives_into_the_block() -> None:
    """Across every borrower-held type, not just the one above. An underscore in this output is a
    slug that escaped."""
    from app.documents.catalog import GUIDANCE, ResponsibleParty

    borrower_types = tuple(
        slug
        for slug, guidance in GUIDANCE.items()
        if guidance.responsible_party is ResponsibleParty.BORROWER
    )
    assert len(borrower_types) > 100  # the fixture is the catalog, so pin that it is populated
    assert "_" not in render_document_block(borrower_types)


@pytest.mark.parametrize(
    ("document_type", "holder"),
    [("appraisal", "lender"), ("title_commitment", "title"), ("voe", "employer")],
)
def test_the_block_refuses_a_document_the_borrower_does_not_hold(
    document_type: str, holder: str
) -> None:
    """LP-800's party field earning its keep. Each of these is ordered by somebody else; asking the
    borrower wastes a round trip and costs their confidence in the rest of the list."""
    with pytest.raises(TemplateError, match=holder):
        render_document_block((document_type,))


def test_an_uncataloged_type_is_refused_too() -> None:
    """By the same rule rather than a special case: LP-800 defaults an unknown type to the processor,
    and a document nobody has classified is not one to ask a borrower for."""
    with pytest.raises(TemplateError, match="processor"):
        render_document_block(("something_nobody_catalogued",))


def test_the_block_keeps_the_callers_order() -> None:
    """The drafter decides what to ask for first; sorting here would put that judgement out of reach."""
    block = render_document_block(("passport", "bank_statement"))
    assert block.index("Passport") < block.index("Bank statements")


def test_an_empty_list_renders_empty_rather_than_raising() -> None:
    """A draft with nothing outstanding is a caller bug, but it is LP-810's to catch — failing here
    would turn it into a 500 in the middle of a send."""
    assert render_document_block(()) == ""


# --------------------------------------------------------------------------------------------- #
# Nothing scans this text — so the deny-list lives here (review finding)
# --------------------------------------------------------------------------------------------- #
#: Language a borrower-facing email must not carry. LP-810 builds a deterministic compliance scanner
#: over MODEL output, and "the plain template" is what that scanner falls back TO — so template text
#: is the one borrower-facing path nothing ever scans. With the drafting flag off by default it is
#: also the only path M1 sends on. These are the phrase classes the scanner exists to stop, checked
#: at the layer that would otherwise skip it.
_MUST_NOT_APPEAR = (
    # Statements about the application's standing — Reg B territory, and not a processor's to make.
    "approved",
    "denied",
    "guaranteed",
    # Both directions of the same claim. The phrasing that prompted this was "they are not a sign
    # that anything is WRONG WITH YOUR application" — a reassurance about the borrower's own file,
    # which is not a processor's to give and may not survive underwriting.
    "wrong with your",
    "nothing is wrong",
    "no problem with your",
    "on track",
    "will close on",
    # Claims about what the system does with what they send. An emailed document is TRIAGED by a
    # person (`auto_accept_inbound` defaults to false, LP-806), so "automatically" overpromises.
    "automatically",
    "instantly",
)


@pytest.mark.parametrize("key", list(TemplateKey))
def test_no_template_makes_a_claim_nothing_scans(key: TemplateKey) -> None:
    """A borrower reads these verbatim and no guardrail sits between the file and their inbox."""
    subject, body = _load(key, TEMPLATES[key].version)
    text = f"{subject}\n{body}".lower()
    hits = [phrase for phrase in _MUST_NOT_APPEAR if phrase in text]
    assert not hits, f"{key.value} carries language nothing downstream will catch: {hits}"


def test_the_status_update_does_not_ask_and_then_offer_a_route_out() -> None:
    """It opens by saying nothing is needed. The security notice has to attach to the one thing it
    DOES invite — a reply — or it reads as a request the borrower cannot find."""
    _, body = _load(TemplateKey.STATUS_UPDATE, TEMPLATES[TemplateKey.STATUS_UPDATE].version)

    assert "nothing is needed from you" in body
    assert body.index("just reply here") < body.index(SECURITY_CAUTION)


# --------------------------------------------------------------------------------------------- #
# A version bump must not lose words (LP-810 review finding)
# --------------------------------------------------------------------------------------------- #
def _prose_sentences(text: str) -> list[str]:
    """Sentences of a template body, with placeholders stripped — the words a borrower reads.

    PARAGRAPH-AWARE, and it has to be: the greeting line ends in a comma, so splitting the whole
    body on sentence terminators glues "Hello ," onto whatever follows and reports a false loss.
    Splitting paragraphs first keeps each sentence the unit it actually is.
    """
    body = text.split("\n\n", 1)[1] if "\n\n" in text else text
    out: list[str] = []
    for paragraph in body.split("\n\n"):
        stripped = re.sub(r"\$\w+", "", paragraph).replace("\n", " ").strip()
        out.extend(s.strip() for s in re.split(r"(?<=[.:])\s+", stripped) if len(s.strip()) > 25)
    return out


def test_v2_plus_the_plain_framing_loses_nothing_from_v1() -> None:
    """The OTHER direction, and the one that was unchecked.

    `test_the_plain_framing_is_v1s_own_words` asserts each framing sentence appears in v1 — which
    catches a framing sentence that drifted, and cannot catch a v1 sentence that was dropped. Both
    are needed, because the version bump's whole promise is that the words are accounted for.

    Measured when this test was written: the v2 bump had silently lost "Anything sent to that
    address reaches your loan file directly…" — the sentence LP-817's own review rewrote after
    finding it made a false automatic-filing claim. With the drafting flag off, v2 plus the plain
    framing IS the email, so a sentence missing from both is a sentence no borrower ever sees.
    """
    v1 = _prose_sentences(_raw("initial_documentation_request", "v1"))
    covered = " ".join(
        _prose_sentences(_raw("initial_documentation_request", "v2"))
        + _prose_sentences("Subject: x\n\n" + _raw_framing("plain", "v1"))
    )

    lost = [s for s in v1 if s not in covered]
    assert not lost, f"v1 sentences absent from v2 + the plain framing: {lost}"
