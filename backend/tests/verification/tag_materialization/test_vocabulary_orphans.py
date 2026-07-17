"""The vocabulary orphan guard (LP-373) — fail loud when the vocabulary promises a tag nobody produces.

THE BUG CLASS (found THREE times, each by accident after a LIVE rule was already dead, every test green):
a tag declared in ``fact_tags.csv`` WITH a producer named, but with NO declaration in
``tag_production.yaml`` and nothing in ``app/`` writing it → the tag is ABSENT → the rule reading it
couldnt_checks on EVERY file, structurally, silently, forever.
  * ``dti.qualifying_income_monthly`` (LP-366-A) — AS-1 had no loan-level income to read → it read the DTI
    calc instead → AS-1 never evaluated a deposit.
  * ``housing.insurance_monthly`` (LP-367, STILL OPEN) — a required gating input to the DTI calculator with
    no producer → the DTI can never compute on ANY file → the UI renders a fabricated $0.00.
  * ``occupancy.stated`` + ``occupancy.consistent_with_signals`` (LP-371) — OC-2 was dead since the
    beginning; occupancy fraud never assessed on any file.

THE ROOT: the loader validates declarations that EXIST; it never checks that a vocabulary tag with a
producer HAS one. ABSENT is indistinguishable from "the document genuinely doesn't have this" — so it is
silent.

THE SEVERITY MODEL (D2 — a guard that fires on every authored-ahead tag is noise and gets muted within a
week; a guard that misses a live rule's orphan is worthless). ~21 rules are authored-but-inert (LP-333),
and their vocabulary tags are LEGITIMATELY declared ahead of their producers. So an unproduced tag is a
BUILD FAILURE only when a LIVE consumer HARD-reads it:
  * a LIVE rule (``ACTIVE_RULE_IDS``) reads it as a GATED input — load-bearing / operand / gather /
    applicability / when-tag — the reads whose absence → couldnt_check (all three instances were this
    shape or the calc one), OR
  * it is a REQUIRED input to the always-computed DTI calculator (``_REQUIRED_DTI_TAGS``; the only
    tag-gated calc, built on every real run by ``builder.py`` and rendered in the UI — LP-367's shape).
An unproduced tag read only by INERT rules, by NO rule, or SOFTLY (a judgment rule's ``reasoned_over``,
which is not gated — absence degrades the AI's context but never couldnt_checks) is REPORTED by the census
(docs/tickets/LP-373.md), not failed here.

WHERE IT LIVES (D3): a TEST, not a load-time check — mirroring LP-369. The guard needs ``ACTIVE_RULE_IDS``,
the rule specs, and the calc layer. Making the tag-vocabulary loader import the rule engine + specs +
calculations to run this at load would INVERT the dependency (the vocabulary is read BY the rule engine,
not vice versa). A CI test fails just as loudly without that coupling.

WHAT THIS GUARD DOES NOT COVER (D4 — the seam map; this is ONE seam of several):
  * a declared producer that EXISTS but never RUNS (the ``_required_ai_groups`` never-requested case,
    LP-333/368) — a different seam, unguarded.
  * a declaration pointing at a nonexistent FIELD — LP-369's parsed guard (document/transaction only).
  * a tag that materializes but is WRONG — calibration (LP-379).
  * a SOFT ``reasoned_over`` orphan on a live rule (``property.address_normalized_match`` on OC-2 — LP-371's
    documented address follow-up): reported, not failed (not gated → no couldnt_check).
  * a tag produced + consumed but ABSENT FROM THE VOCABULARY (``txn.source_strength`` — read by live AS-1,
    produced by Stage B, not in fact_tags.csv): this guard scans the vocabulary, so it cannot see it.
"""

from __future__ import annotations

import csv

from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.rules.specs import Operand, RuleSpec, load_rule_spec
from app.verification.snapshot.calculations_section import _REQUIRED_DTI_TAGS
from app.verification.tag_materialization import declarations as _decl
from app.verification.tag_materialization.declarations import load_declarations, load_vocab_extra

# --------------------------------------------------------------------------- #
# Producers OUTSIDE tag_production.yaml (D1). The transaction Stage-A/Stage-B path is a HARDCODED producer
# (services/tag_production.py + services/tag_correlation.py) — the live orchestrator leaves the txn subject
# to it (producer.py docstring). Without this, the live-read ``txn.has_identified_source`` (Stage B, read by
# LIVE AS-1) would read as an orphan — D1's trap. The Stage-A tags (amount/date/is_money_in/apparent_
# category) are ALSO declared in tag_production.yaml, but listing the full path's output keeps the guard
# honest if a declaration is later removed.
_PRODUCED_OUTSIDE_DECLARATIONS: frozenset[str] = frozenset(
    {
        "txn.amount",  # Stage A (services/tag_production.py) — parsed passthrough
        "txn.date",  # Stage A — parsed passthrough
        "txn.is_money_in",  # Stage A — AI
        "txn.apparent_category",  # Stage A — AI
        "txn.has_identified_source",  # Stage B (services/tag_correlation.py) — the sourcing judge
    }
)

# LOUD exemptions (D2) — a KNOWN live orphan whose fix is a named ticket, NOT a silent allow-list. Each is
# a genuine orphan TODAY (asserted below, so the exemption cannot rot into hiding a resolved tag). Removing
# a tag's producer gap is what clears it from here.
_KNOWN_LIVE_ORPHANS: dict[str, str] = {
    # The DTI calculator gates on BOTH required inputs; neither has a producer, so the DTI can never compute
    # on any file (LP-367, open — no binder/tax extractor wires them; the UI renders a fabricated $0.00).
    "housing.insurance_monthly": "LP-367 (open) — the DTI calc's required insurance input has no producer",
    # The SECOND half of the same DTI-calc gap, surfaced by this ticket's full scan (LP-367 named only
    # insurance). Same shape, same fix ticket.
    "housing.taxes_monthly": "LP-367 (open) — the DTI calc's required property-tax input has no producer",
}


# --------------------------------------------------------------------------- #
# The vocabulary + the producers
# --------------------------------------------------------------------------- #
def _vocabulary() -> dict[str, str]:
    """Every vocabulary tag → its ``produced_by`` column, from the generated ``fact_tags.csv`` AND the
    hand-editable overlay (``vocabulary_extra.yaml``, whose tags default to ``derived``)."""
    vocab: dict[str, str] = {}
    with _decl._FACT_TAGS_CSV.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            vocab[row["tag_id"].strip()] = (row.get("produced_by") or "").strip()
    for tag_id, body in load_vocab_extra().items():
        vocab.setdefault(tag_id, str(body.get("produced_by", "derived")))
    return vocab


def _produced() -> set[str]:
    """Every tag SOMETHING produces: a declaration in ``tag_production.yaml``, the hardcoded transaction
    path, or a LIVE judgment rule's ``output_tag`` (produced by the judgment evaluator at rule time)."""
    produced = set(load_declarations()) | set(_PRODUCED_OUTSIDE_DECLARATIONS)
    for rule_id in ACTIVE_RULE_IDS:
        spec = load_rule_spec(rule_id)
        if spec.judgment is not None:
            produced.add(spec.judgment.output_tag)
    return produced


def _operand_tags(operand: Operand) -> set[str]:
    """The tags an operand resolves — a ``tag`` / ``loan_tag`` value, or every factor of a ``product``."""
    tags: set[str] = set()
    if operand.tag is not None:
        tags.add(operand.tag)
    if operand.loan_tag is not None:
        tags.add(operand.loan_tag)
    if operand.product is not None:
        for factor in operand.product:
            tags |= _operand_tags(factor)
    return tags


def _hard_reads(spec: RuleSpec) -> set[str]:
    """The tags a rule reads whose ABSENCE degrades it to couldnt_check — the GATED reads (load-bearing,
    operand, gather, applicability, when-tag). Excludes a judgment rule's ``reasoned_over`` (SOFT — absence
    only thins the AI's context, never couldnt_checks) and its ``output_tag`` (which the rule PRODUCES)."""
    tags: set[str] = set()
    if spec.consistency is not None:
        tags.add(spec.consistency.gather_tag)
        if spec.consistency.gather_filter is not None:
            tags.add(spec.consistency.gather_filter.tag)
    if spec.deterministic is not None:
        det = spec.deterministic
        tags |= set(det.load_bearing_tags)
        if det.applicability is not None:
            tags.add(det.applicability.tag)
        for operand in det.operands.values():
            tags |= _operand_tags(operand)
        for outcome in det.outcomes:
            for cond in outcome.when_tags:
                tags.add(cond.tag)
    if spec.judgment is not None:
        tags |= set(spec.judgment.load_bearing_tags)
        if spec.judgment.applicability is not None:
            tags.add(spec.judgment.applicability.tag)
    return tags


def _live_hard_reads() -> set[str]:
    """Every tag any LIVE rule HARD-reads (see ``_hard_reads``)."""
    reads: set[str] = set()
    for rule_id in ACTIVE_RULE_IDS:
        reads |= _hard_reads(load_rule_spec(rule_id))
    return reads


def _live_hard_consumers(tag: str) -> list[str]:
    """Which LIVE rules HARD-read ``tag`` — for the guard's actionable message."""
    return sorted(
        rule_id for rule_id in ACTIVE_RULE_IDS if tag in _hard_reads(load_rule_spec(rule_id))
    )


# --------------------------------------------------------------------------- #
# THE GUARD — a pure function so it can be run on the REAL vocabulary and on a SYNTHETIC one
# --------------------------------------------------------------------------- #
def _fatal_orphans(
    vocab: set[str],
    produced: set[str],
    live_hard: set[str],
    dti_required: set[str],
    *,
    exempt: set[str],
) -> dict[str, str]:
    """Every unproduced vocabulary tag a LIVE consumer HARD-reads → its reason. Exempt tags are dropped.

    A LIVE consumer is a live RULE (``live_hard``) or the always-computed DTI calculator (``dti_required``).
    An unproduced tag read only by inert rules / no rule / softly is NOT fatal (it is not returned)."""
    out: dict[str, str] = {}
    for tag in vocab:
        if tag in produced or tag in exempt:
            continue
        if tag in live_hard:
            out[tag] = "read (load-bearing/operand/gather) by LIVE rule(s) — the tag is ABSENT"
        elif tag in dti_required:
            out[tag] = "a REQUIRED input to the always-computed DTI calculator — the tag is ABSENT"
    return out


def test_no_live_consumer_reads_an_unproduced_vocabulary_tag() -> None:
    """THE GUARD. A vocabulary tag a live rule (or the DTI calc) reads MUST have a producer — else it is
    ABSENT and its consumer couldnt_checks silently on every file, forever (the LP-366-A/367/371 class)."""
    fatal = _fatal_orphans(
        set(_vocabulary()),
        _produced(),
        _live_hard_reads(),
        set(_REQUIRED_DTI_TAGS),
        exempt=set(_KNOWN_LIVE_ORPHANS),
    )
    lines = [
        f"{tag}: {why}; live consumers={_live_hard_consumers(tag) or 'DTI calc'} — declared in the "
        f"vocabulary with a producer but NO declaration in tag_production.yaml and nothing in app/ writes "
        f"it. FIX: declare its producer (tag_production.yaml) or wire it, OR — if intentional — add it to "
        f"_KNOWN_LIVE_ORPHANS with a fix ticket."
        for tag, why in sorted(fatal.items())
    ]
    assert not fatal, (
        "the vocabulary promises a tag nobody produces, and a LIVE consumer reads it (LP-373 bug class — "
        "the rule/calc couldnt_checks silently on every file):\n  " + "\n  ".join(lines)
    )


# --------------------------------------------------------------------------- #
# The guard actually FIRES — a guard that cannot fail is not a guard
# --------------------------------------------------------------------------- #
def test_guard_fires_on_a_synthetic_live_rule_orphan() -> None:
    # A live rule hard-reads 'fake.tag'; nothing produces it → fatal.
    fatal = _fatal_orphans(
        {"fake.tag"}, produced=set(), live_hard={"fake.tag"}, dti_required=set(), exempt=set()
    )
    assert fatal == {
        "fake.tag": "read (load-bearing/operand/gather) by LIVE rule(s) — the tag is ABSENT"
    }


def test_guard_fires_on_a_synthetic_dti_calc_orphan() -> None:
    fatal = _fatal_orphans(
        {"fake.calc_input"},
        produced=set(),
        live_hard=set(),
        dti_required={"fake.calc_input"},
        exempt=set(),
    )
    assert fatal == {
        "fake.calc_input": "a REQUIRED input to the always-computed DTI calculator — the tag is ABSENT"
    }


def test_guard_catches_the_dti_calc_orphans_when_not_exempted() -> None:
    # Proof the guard FIRES on the real open orphans — without the exemption, both DTI inputs are caught.
    fatal = _fatal_orphans(
        set(_vocabulary()),
        _produced(),
        _live_hard_reads(),
        set(_REQUIRED_DTI_TAGS),
        exempt=set(),
    )
    assert set(fatal) == {"housing.insurance_monthly", "housing.taxes_monthly"}


# --------------------------------------------------------------------------- #
# The three known instances are FIXED → the guard recognises a correct declaration
# --------------------------------------------------------------------------- #
def test_three_known_instances_are_now_produced() -> None:
    produced = _produced()
    for tag in (
        "dti.qualifying_income_monthly",  # LP-366-A — declared derived
        "occupancy.stated",  # LP-371 — declared derived
        "occupancy.consistent_with_signals",  # LP-371 — declared ai
    ):
        assert tag in produced, (
            f"{tag} should be produced (its fix declared it) — the guard regressed"
        )


# --------------------------------------------------------------------------- #
# The exemptions are genuine — the allow-list cannot rot into hiding a fixable tag (LP-369's pattern)
# --------------------------------------------------------------------------- #
def test_exemptions_are_still_genuine_live_orphans() -> None:
    produced = _produced()
    live_hard = _live_hard_reads()
    dti_required = set(_REQUIRED_DTI_TAGS)
    for tag in _KNOWN_LIVE_ORPHANS:
        assert tag not in produced, (
            f"{tag} is exempted but now HAS a producer — remove it from _KNOWN_LIVE_ORPHANS "
            "(the exemption is masking a healthy tag)"
        )
        assert tag in live_hard or tag in dti_required, (
            f"{tag} is exempted but no live consumer reads it — it is no longer a LIVE orphan; "
            "remove the exemption (a non-fatal orphan does not belong here)"
        )


# --------------------------------------------------------------------------- #
# NO false positives on legitimate authoring, and the hardcoded producer is recognised
# --------------------------------------------------------------------------- #
def test_inert_and_no_rule_orphans_do_not_fail_the_build() -> None:
    # Tags read only by INERT rules (or no rule) are authored-ahead-of-producer — LEGITIMATE, not failures.
    fatal = _fatal_orphans(
        set(_vocabulary()),
        _produced(),
        _live_hard_reads(),
        set(_REQUIRED_DTI_TAGS),
        exempt=set(),  # even WITHOUT exemptions, these must not appear
    )
    for legit in (
        "liab.balance",
        "title.parties_match",
        "property.type",
        "income.job_change_acceptable",
    ):
        assert legit not in fatal, (
            f"{legit} is authored-ahead (inert/no-rule) — it must NOT fail the build"
        )


def test_hardcoded_transaction_producer_tags_are_not_orphans() -> None:
    # txn.has_identified_source is read by LIVE AS-1 and produced by Stage B (NOT tag_production.yaml) —
    # the guard must recognise the hardcoded producer, else it false-positives (D1's trap).
    produced = _produced()
    assert "txn.has_identified_source" in produced
    assert "txn.has_identified_source" in _live_hard_reads()  # it IS live-read, so this matters
