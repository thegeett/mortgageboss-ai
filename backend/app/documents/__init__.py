"""Document-handling domain package (Phase 2).

Houses the cross-cutting document-handling knowledge that the AI pipeline and the
API consult — starting with the document-type :mod:`~app.documents.catalog` (the
single source of truth for a type's tier + category, LP-58). The per-type
extractors themselves live under :mod:`app.ai.extraction`; this package holds the
routing/classification *knowledge*, not the extraction implementations.
"""
