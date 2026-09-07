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

import pytest
from app.communications.templates import (
    SECURITY_NOTICE,
    TEMPLATES,
    VERSION_FINGERPRINTS,
    TemplateError,
    TemplateKey,
    _load,
    file_fingerprint,
    placeholders,
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
    "subject_line": "About your loan",
    "message_body": "Just a note.",
}

#: The templates that hand the borrower somewhere to send documents. M3's routing depends on the
#: address appearing in the initial request; the other two are asks, so they carry it for the same
#: reason. `status_update` and `custom` are excluded deliberately — neither asks for anything.
_ADDRESS_BEARING = {
    TemplateKey.INITIAL_DOCUMENTATION_REQUEST,
    TemplateKey.REMINDER_FOLLOW_UP,
    TemplateKey.CONDITION_RESPONSE_REQUEST,
}


# --------------------------------------------------------------------------------------------- #
# The registry
# --------------------------------------------------------------------------------------------- #
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
def test_every_template_carries_the_security_notice(key: TemplateKey) -> None:
    """A fixed decision in the execution protocol: borrowers are told email is not secure. Asserted
    on the RENDERED body, not the file, because that is what the borrower reads."""
    assert SECURITY_NOTICE in render(key, _CONTEXT).body


def test_the_security_notice_does_not_promise_a_link_that_does_not_exist() -> None:
    """It cautions and offers a route out. Steering to an upload link is LP-815's, and a link that
    resolves to nothing would be worse in an email than no link at all."""
    assert "http" not in SECURITY_NOTICE
    assert "link" not in SECURITY_NOTICE.lower()


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
    assert body.index("just reply here") < body.index(SECURITY_NOTICE)
