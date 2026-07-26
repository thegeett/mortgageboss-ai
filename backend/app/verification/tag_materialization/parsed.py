"""The generic PARSED producer (LP-326) — map an already-parsed extraction field to a tag.

``parsed`` tags carry a fact that already exists in an extraction field; the producer MAPS it, it is
NEVER AI-re-typed (LP-313's discipline — re-typing invites hallucinated values). ``produced_by`` is
``parsed``, ``confidence`` is ``None`` (a deterministic passthrough, not a judgment), and the tag
cites its subject's stable ``content_id``.

**Absent ≠ unknown ≠ empty.** A field NO source supplied (absent) → the tag is ABSENT (not emitted,
never a fabricated "unknown"). A ``:hash`` field whose value is non-matchable (a blank/too-short SSN)
is likewise treated as absent — so a cross-source gather (LP-325) EXCLUDES it rather than comparing a
null hash. A present, matchable/valued field → a tag carrying that value verbatim.
"""

from __future__ import annotations

from pydantic import JsonValue

from app.verification.snapshot.pii import PiiField
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.tag_materialization.declarations import TagDeclaration
from app.verification.tag_materialization.subjects import RawField

_HASH_SUFFIX = ":hash"


def produce_parsed_tag(decl: TagDeclaration, subject_id: str, field: RawField | None) -> Tag | None:
    """Map the declared field to a parsed tag, or ``None`` when the field is absent / non-matchable."""
    if field is None or not field.is_present:
        return None  # absent — never a fabricated value

    value: JsonValue
    if decl.data.endswith(_HASH_SUFFIX):
        # A match_hash tag: the tag's value IS the salted hash. A present-but-non-matchable field
        # (blank/too-short → match_hash None) is treated as ABSENT so a gather excludes it.
        if not isinstance(field, PiiField) or field.match_hash is None:
            return None
        value = field.match_hash
    elif isinstance(field, PiiField):
        # A non-hash PII field carries only a masked display (its raw value never reached us).
        value = field.display
    else:
        value = field.value

    return Tag(
        value=value,
        confidence=None,  # a parsed passthrough — never a fabricated confidence
        reasoning=None,
        source_facts=(subject_id,),
        produced_by=TagProducedBy.PARSED,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


__all__ = ["produce_parsed_tag"]
