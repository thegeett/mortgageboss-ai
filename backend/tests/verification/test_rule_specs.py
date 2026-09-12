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
