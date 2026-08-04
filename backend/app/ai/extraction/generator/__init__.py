"""Extractor generator (LP-434) — JSON schema spec → working extractor artifacts.

``docs/schema-specs/NNN-<slug>.json`` describes a document type's extraction schema.
``docs/schema-specs/_GENERATION_GUIDE.md`` is the authoritative contract for how a
spec becomes code; this package implements it.

The load-bearing part is the **validator** (:mod:`.validator`): it applies the
guide's five §0 stop conditions and refuses a spec — loudly, with reasons — rather
than emitting partial or guessed code. Only a spec that passes every condition is
emitted. The emitters (:mod:`.emitters`) then produce the extractor module, the
prompt scaffold, the ``EXTRACTORS`` registration snippet, and the test skeleton,
each a verbatim mirror of the shipping flat extractors (``property_tax_bill`` is the
reference). Everything downstream — the CLI, the round-trip proof — is built on
those two.

A generated extractor is **structurally correct and mechanically tested, accuracy
unvalidated** — exactly the position the 18 hand-written extractors ship in. It is
not tuned; that comes from a human prompt pass and Priya's review of real
extractions (guide §11).
"""

from app.ai.extraction.generator.spec import Spec, SpecField, load_spec
from app.ai.extraction.generator.validator import Refusal, validate

__all__ = ["Refusal", "Spec", "SpecField", "load_spec", "validate"]
