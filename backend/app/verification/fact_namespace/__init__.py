"""The fact namespace (LP-118.6) — the engine's assembled per-run typed fact object.

Public surface:

* :func:`assemble_fact_namespace` — build the immutable, entity-addressable :class:`FactNamespace`
  from a loan file (enum columns + stated rows + materialized extraction JSON + compute-once
  calculators + build-time canonicalization). Reads only; executes no rule.
* :func:`save_fact_snapshot` / :func:`load_fact_snapshot` — persist/reload the namespace as the
  run's immutable ``fact_snapshot`` (typed JSON round-trip: Decimal stays Decimal, enums stay enums).
* :func:`project_cross_source_facts` — derive the legacy CrossSourceFacts (the 5 live rules' input)
  from the namespace, proven byte-identical to the legacy builder.
* :class:`Canonicalizer` — the map + AI-fallback-seam + learn category canonicalizer.

Nothing here is wired into the live verification runner (that is LP-121); this is the foundation
LP-119 (applicability) and LP-120 (evaluators) read from.
"""

from app.models.verification import Verification
from app.verification.fact_namespace.builder import assemble_fact_namespace
from app.verification.fact_namespace.canonicalize import (
    CanonicalizationFallback,
    Canonicalizer,
    FallbackAnswer,
    NoFallback,
)
from app.verification.fact_namespace.projection import project_cross_source_facts
from app.verification.fact_namespace.snapshot import FactNamespace


def save_fact_snapshot(run: Verification, namespace: FactNamespace) -> None:
    """Persist the assembled namespace onto the run as its immutable ``fact_snapshot`` (JSON).

    ``mode="json"`` gives a portable, typed-round-trippable payload (Decimal → string, date → ISO,
    enums → value). ``flush``/``commit`` is the caller's; this only sets the attribute.
    """
    run.fact_snapshot = namespace.model_dump(mode="json")


def load_fact_snapshot(run: Verification) -> FactNamespace | None:
    """Reload the run's fact namespace with types intact, or ``None`` if none was stored."""
    if run.fact_snapshot is None:
        return None
    return FactNamespace.model_validate(run.fact_snapshot)


__all__ = [
    "CanonicalizationFallback",
    "Canonicalizer",
    "FactNamespace",
    "FallbackAnswer",
    "NoFallback",
    "assemble_fact_namespace",
    "load_fact_snapshot",
    "project_cross_source_facts",
    "save_fact_snapshot",
]
