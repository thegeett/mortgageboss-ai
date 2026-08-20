"""LP-589 — the parser, which shipped inert and which nothing exercised.

`extract_json_object` returns the JSON SUBSTRING, not a parsed object — as its own docstring says,
and as every other caller in the repo treats it. The first version of `_parse` checked
`isinstance(payload, dict)` on that string, which is never true, so EVERY response was discarded.

The pass produced nothing on every file, the model was called and paid for on every run, and the tab
reported "the last run found nothing to reconcile" — telling a processor something false. mypy was
satisfied (it narrows to an impossible intersection rather than erroring) and every service test
injected a stub reasoner, so nothing in CI touched this function.

That is the whole reason these tests exist: they exercise `_parse` against the shapes a model
actually returns, rather than a stub that skips it.
"""

from __future__ import annotations

from app.ai.snapshot_cross_source import SnapshotFindingDraft, _normalise, _parse

_GOOD = (
    '{"findings":[{"kind":"valuation_vs_assessment","title":"Assessed below stated",'
    '"detail":"The tax bill assesses lower than the application states.",'
    '"sources":[{"label":"application","value":"578000"},'
    '{"label":"property tax bill","value":"551923"}]}]}'
)


def test_a_well_formed_response_yields_a_finding() -> None:
    """The case that returned [] for every response the model could produce."""
    (draft,) = _parse(_GOOD)

    assert draft.kind == "valuation_vs_assessment"
    assert len(draft.sources) == 2


def test_prose_and_a_markdown_fence_are_tolerated() -> None:
    """What models actually send. `extract_json_object` exists for this; the bug was downstream."""
    (draft,) = _parse(f"Here is what I found:\n```json\n{_GOOD}\n```\nHope that helps.")

    assert draft.title == "Assessed below stated"


def test_malformed_json_yields_nothing_rather_than_raising() -> None:
    """Defensive, and it must stay so: a bad response degrades the tab, never the run."""
    assert _parse("not json at all") == []
    assert _parse('{"findings": [ {"kind": "x", ') == []  # truncated at max_tokens
    assert _parse('{"findings": "not a list"}') == []


def test_a_single_source_finding_is_rejected() -> None:
    """One source is not CROSS-source — it is an observation about one value, which the rules
    already cover and the prompt explicitly forbids."""
    single = (
        '{"findings":[{"kind":"k","title":"t","detail":"d",'
        '"sources":[{"label":"only","value":"1"}]}]}'
    )

    assert _parse(single) == []


# --------------------------------------------------------------------------------------------- #
# Identity — the sources are model-authored too
# --------------------------------------------------------------------------------------------- #


def _draft(sources: list[dict[str, str]], title: str = "t") -> SnapshotFindingDraft:
    return SnapshotFindingDraft(kind="valuation", title=title, detail="d", sources=sources)


def test_identity_survives_the_models_wording_of_its_own_evidence() -> None:
    """THE FAILURE THE FIRST VERSION STILL HAD after excluding the title. The SOURCE strings are
    model-authored as well, so "551,923" and "551923" — the same figure, punctuated differently —
    produced different keys, orphaning the processor's dismissal exactly as a reworded title would
    have. The earlier test only varied the title, which the key already ignored, so it proved
    nothing about this."""
    a = _draft(
        [{"label": "Tax Bill,", "value": "$551,923.00"}, {"label": "app", "value": "578000"}]
    )
    b = _draft([{"label": "tax bill", "value": "551923"}, {"label": "app", "value": "578,000"}])

    assert a.finding_key == b.finding_key


def test_a_genuinely_different_source_still_differs() -> None:
    """Normalisation must not collapse distinct claims. "property tax bill" and "tax bill" are
    different statements about provenance and stay different findings."""
    a = _draft([{"label": "tax bill", "value": "551923"}, {"label": "app", "value": "578000"}])
    b = _draft([{"label": "appraisal", "value": "551923"}, {"label": "app", "value": "578000"}])

    assert a.finding_key != b.finding_key


def test_the_normaliser_parses_numbers_rather_than_keeping_digits() -> None:
    """Keeping digits made "$578,000.00" normalise to 57800000 while "578000" gave 578000 — the same
    amount, two keys. The value is parsed as a decimal instead."""
    assert _normalise("$578,000.00") == _normalise("578000")
    assert _normalise("551,923") == _normalise("551923")
    assert _normalise("Tax Bill,") == _normalise("tax bill")
