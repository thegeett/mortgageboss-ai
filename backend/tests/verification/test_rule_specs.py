def test_no_rule_reuses_its_processor_how_to_fix_as_its_outbound_ask() -> None:
    """LP-842 — THE FIELD THAT MUST NOT LEAVE THE BUILDING.

    Every one of the 84 specs declares `how_to_fix`, and on IH-1 it says exactly the right thing:
    "obtain a policy or endorsement that settles the dwelling on a replacement-cost basis". The
    temptation to route it outward is the whole reason this test exists.

    It is written for a PROCESSOR, on the assumption that only a processor reads it. Measured across
    the 84: ID-1, ID-2 and ID-3 each say a mismatch "may indicate identity fraud and must be
    escalated"; CO-5, CR-6 and IH-7 say "ineligible"; PR-6 says "decline". Sent to a borrower that
    accuses them of fraud. Sent to a lender it discloses an internal posture about their file.

    SO THE TWO FIELDS MUST NOT BE THE SAME STRING, even where copying one today would be harmless.
    An author who copies a safe one establishes the habit, and the next copy is ID-3.

    This is an ALLOW-LIST by construction — a rule is silent until somebody writes an ask and means
    it — and this test defends the one way that property gets lost.
    """
    from pathlib import Path
    from typing import Any

    import yaml

    specs_dir = Path(__file__).resolve().parents[2] / "app" / "verification" / "rules" / "specs"
    files = sorted(specs_dir.glob("*.yaml"))
    assert len(files) > 50, "the scan read no specs"

    def blocks(doc: Any, field: str) -> set[str]:
        """Every value stored under `field`, at any depth.

        PARSED, NOT PATTERN-MATCHED. The first version of this scanned the file text for
        `field:\\s*>-` and captured the YAML FOLD INDICATOR itself, so every rule's `outbound_ask`
        came back as the string ">-" — which of course also appeared among its `how_to_fix` values,
        and all 17 authored rules were reported as copying a field they do not copy. The test failed
        loudly for a reason unrelated to the one it names, which is the same defect as passing for
        one. `how_to_fix` nests at several depths (per verdict, per explain case), so a recursive
        walk over parsed YAML is both the correct reader and the simpler one.
        """
        found: set[str] = set()
        if isinstance(doc, dict):
            for key, value in doc.items():
                if key == field and isinstance(value, str) and value.strip():
                    found.add(" ".join(value.split()))
                else:
                    found |= blocks(value, field)
        elif isinstance(doc, list):
            for entry in doc:
                found |= blocks(entry, field)
        return found

    offenders = []
    checked = 0
    for path in files:
        doc = yaml.safe_load(path.read_text())
        asks = blocks(doc, "outbound_ask")
        fixes = blocks(doc, "how_to_fix")
        checked += len(asks)
        for ask in asks:
            if ask in fixes:
                offenders.append(path.stem)

    assert not offenders, (
        f"{sorted(set(offenders))} reuse a processor-facing `how_to_fix` verbatim as the sentence "
        "sent to a borrower or a third party. Write the outward one separately."
    )
    # THE POSITIVE CONTROL. Every assertion above is satisfied by a tree where no spec declares an
    # `outbound_ask` at all — which is the feature switched off, reading as green.
    assert checked > 0, "no spec declares an `outbound_ask`; this test proved nothing"


#: Rules whose `outbound_ask` can never be rendered, each with the reason (LP-842 review).
#:
#: A RECORD OF DEVIATIONS, not an allow-list. `NO_RECIPIENT` is `ResponsibleParty.PROCESSOR`, and
#: `add_needs_to_draft` gives that party a `PartyDraft` with `draft=None` — so a need routed there is
#: real work on the needs list and never an email. An ask on one is written and unreachable.
#:
#: Neither of these is wrong: if a processor-facing surface ever renders the ask they become correct
#: without being rewritten. They are recorded so a THIRD does not arrive silently.
_ASKS_THAT_REACH_NOBODY = {
    "CO-1",  # condo questionnaire — the processor orders it
    "ID-6",  # the 1003 — the processor completes it
}


def _authored_asks() -> dict[str, object]:
    """`{rule_id: spec}` for every rule that declares an `outbound_ask`."""
    from pathlib import Path

    from app.verification.rules.specs import load_rule_spec

    specs_dir = Path(__file__).resolve().parents[2] / "app" / "verification" / "rules" / "specs"
    files = sorted(specs_dir.glob("*.yaml"))
    assert len(files) > 50, "the scan read no specs"
    found = {}
    for path in files:
        spec = load_rule_spec(path.stem)
        if getattr(spec, "outbound_ask", None):
            found[path.stem] = spec
    assert found, "no rule declares an outbound_ask — the scan found nothing to check"
    return found


def test_every_outbound_ask_can_actually_be_rendered() -> None:
    """LP-842 REVIEW — an ask rides its need to whichever party holds the document.

    `_document_line` renders `need.outbound_ask` with NO party awareness, and LP-841 routes each need
    by `party_for`. So an ask goes wherever its document goes, and an ask on a document routed to
    `NO_RECIPIENT` is never rendered at all.

    Measured when this was reviewed: of 21 authored asks, 2 land in the processor bucket and can never
    be seen. That is fine and recorded; a third arriving without a reason is what this fails on.

    This is also the guard for the three asks the review DELETED — CR-8, CR-12 and IH-7 each named or
    asked for something their routed party could not supply. That mismatch is a judgement a test
    cannot make, but the reachability half of it is checkable, and it is the half that catches an ask
    pointed at a party with no draft at all.
    """
    from app.documents.catalog import get_guidance
    from app.services.email_draft import NO_RECIPIENT

    unreachable = set()
    for rule_id, spec in _authored_asks().items():
        parties = {
            get_guidance(group[0]).responsible_party
            for group in (spec.requires_documents or ())
            if group
        }
        if parties and parties <= {NO_RECIPIENT}:
            unreachable.add(rule_id)

    assert unreachable == _ASKS_THAT_REACH_NOBODY, (
        f"rules whose ask can never be rendered changed: {sorted(unreachable)} vs recorded "
        f"{sorted(_ASKS_THAT_REACH_NOBODY)}. An ask on a document routed to the processor is written "
        "and unreachable — either route it, or record it here with the reason."
    )


def test_no_outbound_ask_sits_on_a_rule_that_declares_no_document() -> None:
    """THE OTHER WAY AN ASK REACHES NOBODY, and the control for the test above.

    An ask is rendered per NEED, and a need comes through a declared document — so a rule with no
    `requires_documents` creates nothing for its ask to ride on. Without this, the test above passes
    on a codebase where every ask is attached to a rule that declares no documents at all, because
    `parties` would be empty for all of them.
    """
    orphans = sorted(
        rule_id for rule_id, spec in _authored_asks().items() if not (spec.requires_documents or ())
    )

    assert orphans == [], (
        f"{orphans} declare an outbound_ask and no document for it to ride on — LP-624's channel "
        "creates an untyped need from a sentence, and nothing attaches a spec's ask to one."
    )


#: Documents that more than one ask-carrying rule declares, and how many (LP-842 review).
#:
#: `_outbound_ask` returns an ask only when the contributing rules AGREE — a set of size one — so two
#: rules co-firing on one document silences it. Measured, and the distribution is the point:
_ASKS_PER_SHARED_DOCUMENT = {
    "bank_statement": 6,  # AS-1, AS-2, AS-8, AS-9, AS-10, AS-12
    "closing_disclosure": 4,  # CL-1, CR-13, ID-5, IH-3
    "homeowners_insurance": 3,  # IH-1, IH-3, IH-9
}


def test_how_many_asks_compete_for_one_document() -> None:
    """LP-842 REVIEW — the silence-on-disagreement rule costs most on the commonest document.

    The build asked whether co-firing makes the feature "never appear, with nothing saying why". It
    does, and it is concentrated rather than spread: SIX ask-carrying rules declare `bank_statement`,
    which is among the most requested documents in the product. Two asset rules firing together — an
    incomplete statement set trips AS-2, AS-8 and AS-9 at once — suppresses all six.

    AND THOSE SIX ARE CUMULATIVE, NOT CONTRADICTORY. "Send every page", "send consecutive months" and
    "show where each large deposit came from" are all true at the same time. Silence is right for a
    contradiction and lossy here, which is a design decision this ticket did not make and this test
    does not make either: suppressed renders exactly as before LP-842, so nothing regressed.

    What this pins is the NUMBER, so the cost is a recorded quantity rather than a thing somebody
    rediscovers, and a seventh ask on `bank_statement` is a decision rather than a drift.
    """
    import collections

    competing: dict[str, int] = collections.Counter()
    for spec in _authored_asks().values():
        for group in spec.requires_documents or ():
            if group:
                competing[group[0]] += 1
    shared = {doc: n for doc, n in competing.items() if n > 1}

    assert shared == _ASKS_PER_SHARED_DOCUMENT, (
        f"asks competing for one document changed: {sorted(shared.items())} vs recorded "
        f"{sorted(_ASKS_PER_SHARED_DOCUMENT.items())}. Two rules agreeing is what `_outbound_ask` "
        "requires, so each of these is a document where the ask is suppressed when they co-fire."
    )
    # The control: single-document asks exist too, or the rule above is about an empty set.
    assert any(n == 1 for n in competing.values())
