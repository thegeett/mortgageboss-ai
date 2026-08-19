"""LP-527 — the composition PASS: enrich persisted findings, cache by facts, never break a verdict.

Runs AFTER the findings are written. It reads them, asks a model to rewrite the text of each, and
writes back only `message` and `how_to_fix`. Nothing else is touched: not the verdict, not the outcome,
not the tags, not the reconcile identity. A total failure of this pass leaves a fully correct run whose
findings read exactly as the templates wrote them.

⚠️ PER FINDING, NOT PER RULE, AND NOT ONE BATCHED CALL. Batching is cheaper on a cold cache and worse
everywhere else: a single changed finding would invalidate a whole batch (defeating the cache, which is
the point), one malformed response would cost every finding its prose instead of one, and item 17 of 25
gets less of the model's attention than item 1 — the position degradation this codebase already avoids
in the judgment evaluator. Concurrency is bounded the same way that evaluator bounds it.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.finding_prose import IDENTIFIER, Composition, FactSummary, compose
from app.core.logging import get_logger
from app.models.finding import Finding
from app.models.finding_prose import FindingProse
from app.models.loan_file import LoanFile
from app.services.rule_subject_label import resolve_subject_label
from app.verification.rule_engine.reasons import document_label, fact_label
from app.verification.rules.specs import RuleSpecNotFound, load_rule_spec
from app.verification.snapshot.documents_section import document_filenames_by_content_id

logger = get_logger(__name__)

_SPEC_DIR = Path(__file__).resolve().parents[1] / "verification/rules/specs"

# The same bound the judgment evaluator uses: enough to keep the pass short, low enough that a large
# file cannot burst into a hundred simultaneous calls and trip a rate limit.
_MAX_CONCURRENT = 8


# A tag's reasoning is a paragraph, and a finding can rest on six of them (AS-12). Capped so a verbose
# tag cannot crowd the rest of the prompt out; cut at a sentence boundary where one is near the limit,
# because a mid-enumeration cut ("(i) … (ii) … (iii") reads as if the check only looked at three things.
_EVIDENCE_LIMIT = 600


def _evidence(reasoning: str) -> str | None:
    """One tag's reasoning, made fit for a processor: identifiers stripped, length capped.

    TRANSLATED, NOT DELETED, and the first attempt got this wrong. Several tag prompts REQUIRE the
    model to cite the tags it used by id ("cite the SPECIFIC tags you relied on (by their tag id)"), so
    this text reliably contains `occupancy.consistent_with_signals` and MISMO paths like
    `declaration.intenttooccupytype`. That is right for a tag's own provenance and wrong in front of a
    processor (LP-377-B), and a composer handed one copies it faithfully — LP-528's content-id leak in
    a new place.

    Deleting them mangled the sentence: OC-2's "The single borrower's `declaration.intenttooccupytype`
    is 'Yes'" became "The single borrower's is 'Yes'", which loses the subject — and the subject was
    the whole point, because it shows the model corroborated the stated occupancy with the borrower's
    OWN declaration of it. Erasing the identifier erased the thing a ratifier most needs to see.
    `fact_label` already renders a known tag in a processor's words and degrades an unknown path to its
    humanised last segment, so it is a substitution, never a hole.
    """
    text = " ".join(IDENTIFIER.sub(lambda m: fact_label(m.group()), reasoning).split())
    if not text:
        return None
    if len(text) <= _EVIDENCE_LIMIT:
        return text
    window = text[:_EVIDENCE_LIMIT]
    sentence_end = window.rfind(". ")
    if sentence_end > _EVIDENCE_LIMIT // 2:
        return window[: sentence_end + 1]
    return window[: window.rfind(" ")] + "…"


def summarize(
    finding: Finding,
    *,
    rule_name: str,
    borrower_names: Mapping[str, str] | None = None,
    document_filenames: Mapping[str, str] | None = None,
) -> FactSummary:
    """The ONLY input a composition may draw on — assembled from the finding, never from the snapshot.

    Deliberately narrow. A composer that could reach the whole snapshot would be free to mention facts
    the rule never considered, and a processor reading a finding is entitled to assume the sentence
    describes what the check actually looked at.

    ⚠️ THE SUBJECT IS THE RESOLVED LABEL, NEVER `subject_key`. A first version passed the key, and the
    model faithfully wrote it into user-facing text: "the retained property on doc7031677534131285",
    "for liability lia7a033a46ec70cc10". LP-377-B exists to keep that hash away from a processor, and
    the read path already had `resolve_subject_label` for it — the composer just has to use the same
    resolver, with the same maps, so a finding cannot read one way in the list and another in its text.
    """
    facts = {
        fact_label(str(tag.get("tag_id", ""))): str(tag.get("value", ""))
        for tag in (finding.load_bearing_tags or [])
        if tag.get("tag_id") and tag.get("value") not in (None, "")
    }
    evidence = {}
    for tag in finding.load_bearing_tags or []:
        reasoning = tag.get("reasoning")
        if tag.get("tag_id") and isinstance(reasoning, str) and reasoning.strip():
            trimmed = _evidence(reasoning)
            if trimmed:
                evidence[fact_label(str(tag["tag_id"]))] = trimmed
    details = finding.details or {}
    return FactSummary(
        rule_name=rule_name,
        subject=resolve_subject_label(
            finding.subject_key,
            finding.load_bearing_tags or [],
            document_filenames=document_filenames,
        ),
        evidence=evidence,
        # LP-552 — a satisfied finding is a PASS, and must not be rewritten into a task.
        settled=finding.evaluation_outcome is not None
        and finding.evaluation_outcome.value == "satisfied",
        problem=finding.message,
        fix=details.get("how_to_fix") if isinstance(details.get("how_to_fix"), str) else None,
        facts=facts,
    )


# Every document type any rule declares, as the readable label a composition would print. Bounded to
# what rules actually ask for (about 40 of the catalog's 163), which keeps this from matching ordinary
# words — the catalog also contains "custom" and "survey".
def _declared_document_labels() -> dict[str, str]:
    labels: dict[str, str] = {}
    for spec_path in sorted(_SPEC_DIR.glob("*.yaml")):
        try:
            spec = load_rule_spec(spec_path.stem)
        except RuleSpecNotFound:  # pragma: no cover - the glob came from the directory
            continue
        for group in spec.requires_documents or ():
            for slug in group:
                labels[slug] = document_label(slug).lower()
    return labels


# What a MODEL calls these documents, where that differs from the catalog slug. Small and targeted on
# purpose: the guard's job is to catch a composition asking for something the rule never asked for, and
# "purchase contract" for `purchase_agreement` is exactly the miss that let OC-2's impossible ask
# through on the first attempt. Aliases only make the guard see MORE, never less — a rule whose own
# template names the document still passes, because the template is parsed with the same aliases.
_ALIASES: dict[str, tuple[str, ...]] = {
    "purchase_agreement": ("purchase contract", "sales contract", "purchase and sale agreement"),
    "credit_report": ("tri-merge report", "tri merge report"),
    "voe": ("verification of employment",),
    "appraisal": ("appraisal report",),
    "rate_lock_agreement": ("rate lock", "rate-lock", "rate lock confirmation"),
    "title_commitment": ("title report",),
    "uniform_residential_loan_application": ("1003",),
}


@lru_cache(maxsize=1)
def _document_patterns() -> tuple[tuple[str, re.Pattern[str]], ...]:
    return tuple(
        (slug, re.compile("|".join(rf"\b{re.escape(name)}\b" for name in names)))
        for slug, names in (
            (slug, (label, *_ALIASES.get(slug, ())))
            for slug, label in _declared_document_labels().items()
        )
    )


def documents_named(text: str) -> set[str]:
    """Which declared document types this text asks for, by their readable names."""
    lowered = text.lower()
    return {slug for slug, pattern in _document_patterns() if pattern.search(lowered)}


def unrequested_documents(finding: Finding, summary: FactSummary, action: str) -> set[str]:
    """Documents the ACTION asks for that neither the rule nor its own template ever asked for.

    FOUND ON A REAL FILE, AND IT WAS UNACHIEVABLE. OC-2's template fix says "Confirm the stated
    occupancy is what the borrower intends". After LP-537 gave the composer the tag reasoning — which
    included "no purchase contract states a property address" — it rewrote the action as "Obtain a
    purchase contract that states the property address". LF-WCHG is a REFINANCE. There is no purchase
    contract and there never will be, so a processor was sent after a document that cannot exist.

    The `why` was right to name that gap; the ACTION is what must stay inside the request the rule
    actually makes. Evidence is context, not a shopping list.

    Allowed: what the rule DECLARES it reads, plus anything its own template problem/fix already names
    (IN-4's fix offers a verification of employment that IN-4 does not declare, and saying so is
    faithful). Deliberately NOT the evidence text — that is the leak this closes.
    """
    try:
        spec = load_rule_spec(finding.rule_id)
    except RuleSpecNotFound:
        return set()  # a retired rule declares nothing; do not invent a constraint for it
    declared = {slug for group in spec.requires_documents or () for slug in group}
    template = documents_named(f"{summary.problem} {summary.fix or ''}")
    return documents_named(action) - declared - template


async def _cached(db: AsyncSession, keys: list[str]) -> dict[str, Composition]:
    if not keys:
        return {}
    rows = (
        (await db.execute(select(FindingProse).where(FindingProse.fact_hash.in_(keys))))
        .scalars()
        .all()
    )
    return {row.fact_hash: Composition(row.action, row.why) for row in rows}


async def _store(db: AsyncSession, key: str, composition: Composition) -> None:
    """Upsert — two loan files can compose the same facts concurrently, and neither should fail."""
    await db.execute(
        insert(FindingProse)
        .values(fact_hash=key, action=composition.action, why=composition.why)
        .on_conflict_do_nothing(index_elements=["fact_hash"])
    )


def _with_derivation(message: str, finding: Finding) -> str:
    """Re-attach the materiality arithmetic the template carried, if the composition lost it.

    NOT LEFT TO THE MODEL, and the first composed run is why. The derivation is an auditability
    requirement — a processor who sees "$2,000.00 is above the $1,316.67 (10% of $13,166.70 monthly
    qualifying income) materiality floor" can argue with the threshold; one who sees "exceeds the
    materiality threshold" cannot. Of five AS-12 findings, the model dropped the clause entirely from
    four and kept only the bare number in the fifth.

    That is not a prompt failure to fix by asking harder. A composer whose job is to shorten will keep
    shortening, and a requirement that survives only when a generation happens to honour it is not a
    requirement. Appended rather than enforced-by-rejection so the improved prose is kept too.
    """
    details = finding.details or {}
    derivation = details.get("derivation")
    if not isinstance(derivation, str) or not derivation:
        return message
    # Already stated in full (the fraction AND the basis, not just the resulting floor) → leave it.
    fraction_and_basis = re.search(r"\d+% of ", derivation)
    if fraction_and_basis and fraction_and_basis.group() in message:
        return message
    # Its own sentence, NOT parenthesised: the derivation already contains a bracketed clause
    # ("the $1,316.67 (10% of $13,166.67 qualifying income) materiality floor"), and wrapping it
    # produced nested parentheses on every AS-12 finding of the run that introduced this.
    return f"{message} Threshold: {derivation}."


async def compose_findings(
    db: AsyncSession,
    findings: list[Finding],
    *,
    rule_names: dict[str, str],
    loan_file_id: UUID,
) -> int:
    """Rewrite what can be rewritten; leave the rest exactly as the templates wrote it.

    Returns how many findings were changed. Never raises: a composition pass that fails must not fail a
    verification run whose verdicts are already correct and already persisted.
    """
    # The SAME map the read path builds, so a finding cannot name its subject one way in the list and
    # another inside its own text. Only loaded when a document-subject finding exists — most files have
    # none, and this is a reshape of every document.
    document_filenames: Mapping[str, str] = {}
    if any((finding.subject_key or "").startswith("doc") for finding in findings):
        loan_file = await db.get(LoanFile, loan_file_id)
        if loan_file is not None:
            document_filenames = await document_filenames_by_content_id(db, loan_file)

    summaries = {
        finding.id: summarize(
            finding,
            rule_name=rule_names.get(finding.rule_id, finding.rule_id),
            document_filenames=document_filenames,
        )
        for finding in findings
        if finding.message
    }
    by_id = {finding.id: finding for finding in findings}
    keys = {fid: summary.cache_key() for fid, summary in summaries.items()}
    cache = await _cached(db, list(dict.fromkeys(keys.values())))

    misses = [fid for fid, key in keys.items() if key not in cache]
    if misses:
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT)

        async def _one(finding_id: UUID) -> tuple[UUID, Composition | None]:
            async with semaphore:
                return finding_id, await compose(summaries[finding_id])

        for finding_id, composition in await asyncio.gather(*(_one(fid) for fid in misses)):
            if composition is None:
                continue
            finding = by_id[finding_id]
            if unrequested := unrequested_documents(
                finding, summaries[finding_id], composition.action
            ):
                # The template stands — it asks for something achievable.
                logger.warning(
                    "finding_prose_rejected_unrequested_document",
                    rule_id=finding.rule_id,
                    documents=sorted(unrequested),
                )
                continue
            cache[keys[finding_id]] = composition
            await _store(db, keys[finding_id], composition)

    changed = 0
    for finding in findings:
        composition = cache.get(keys.get(finding.id, ""))
        if composition is None:
            continue  # rejected, failed, or not summarizable — the template stands
        finding.message = _with_derivation(composition.message, finding)
        changed += 1

    logger.info(
        "finding_prose_pass_done",
        findings=len(findings),
        composed=changed,
        cache_hits=len(summaries) - len(misses),
    )
    return changed


__all__ = ["compose_findings", "summarize"]
