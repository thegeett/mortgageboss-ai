"""The extraction-bench engine — walk, preview+cost, and the per-document run.

⚠️ MEASURES COVERAGE, NOT ACCURACY. Every fill-rate/value it reports is "was this field POPULATED",
never "is the value CORRECT". Nothing is persisted (JSON output only). It changes nothing about the
system under test — it drives the LIVE classifier and the LIVE registered extractors, read-only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.ai.classification import classify_document
from app.ai.cost import estimate_cost
from app.ai.extraction import EXTRACTORS
from app.core.config import resolve_model, settings
from app.dev.bench.prompt import bench_pii_prompt
from app.dev.bench.redact import redact_string, redact_tree

# The document formats the pipeline can read natively (LP-37 content block). Anything else is
# "unreadable" for the bench and reported, not sent.
_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}

# A ROUGH per-document cost estimate for the PREVIEW only (count x this). Midpoint of the two real
# Haiku-4.5 measurements in the ticket: a credit report ~$0.074, a pay stub ~$0.021. The ACTUAL cost is
# reported per document after the run, from real token counts — this is only to avoid a surprise-spend.
PER_DOC_COST_ESTIMATE = 0.05


@dataclass
class DiscoveredFile:
    path: Path
    size: int
    media_type: str | None  # None = unreadable/unsupported
    unreadable_reason: str | None = None


def walk_documents(root: Path) -> list[DiscoveredFile]:
    """Recursively find every file under ``root`` (nested directories expected), classifying each as a
    readable document or an unreadable one (zero bytes, unsupported extension, or a PDF that isn't one)."""
    found: list[DiscoveredFile] = []
    for dirpath, _dirs, files in os.walk(root):
        for name in sorted(files):
            if name.startswith("."):
                continue  # skip .DS_Store etc.
            p = Path(dirpath) / name
            try:
                size = p.stat().st_size
            except OSError:
                continue
            media = _MEDIA_TYPES.get(p.suffix.lower())
            reason: str | None = None
            if size == 0:
                media, reason = None, "zero bytes"
            elif media is None:
                reason = f"unsupported extension {p.suffix or '(none)'!r}"
            elif media == "application/pdf" and not _looks_like_pdf(p):
                media, reason = None, "not a valid PDF (bad header)"
            found.append(DiscoveredFile(p, size, media, reason))
    return found


def _looks_like_pdf(p: Path) -> bool:
    try:
        with p.open("rb") as fh:
            return fh.read(5).startswith(b"%PDF-")
    except OSError:
        return False


@dataclass
class Preview:
    root: str
    total: int
    readable: int
    by_extension: dict[str, int]
    unreadable: list[dict[str, str]]
    per_doc_estimate: float
    estimated_cost: float
    provider: str
    extraction_model: str
    note: str = (
        "Estimated cost is count x a rough per-document figure; actual cost is measured per document "
        "after the run. This bench measures COVERAGE (was a field populated), NOT accuracy."
    )


def preview(root: Path) -> Preview:
    """The PREVIEW shown BEFORE anything runs: counts, breakdown, unreadable files, and an estimated
    cost. Nothing is sent to a model here."""
    files = walk_documents(root)
    readable = [f for f in files if f.media_type is not None]
    by_ext: dict[str, int] = {}
    for f in files:
        by_ext[f.path.suffix.lower() or "(none)"] = (
            by_ext.get(f.path.suffix.lower() or "(none)", 0) + 1
        )
    unreadable = [
        {"file": str(f.path.relative_to(root)), "reason": f.unreadable_reason or "unreadable"}
        for f in files
        if f.media_type is None
    ]
    return Preview(
        root=str(root),
        total=len(files),
        readable=len(readable),
        by_extension=dict(sorted(by_ext.items())),
        unreadable=unreadable,
        per_doc_estimate=PER_DOC_COST_ESTIMATE,
        estimated_cost=round(len(readable) * PER_DOC_COST_ESTIMATE, 2),
        provider=settings.ai_provider,
        extraction_model=resolve_model(settings.anthropic_model_extraction),
    )


def _result_to_record(data: Any) -> dict[str, Any]:
    """Generic view of any ``*Extraction`` model: typed-core field values, list row-dicts, and the
    catch-all — independent of the concrete result class."""
    typed_core: dict[str, Any] = {}
    lists: dict[str, list[dict[str, Any]]] = {}
    for name in type(data).model_fields:
        if name == "additional_sections":
            continue
        val = getattr(data, name)
        if hasattr(val, "value"):  # a TypedField
            typed_core[name] = val.value
        elif isinstance(val, list):  # a nested list (generic rows or a bespoke record model)
            rows: list[dict[str, Any]] = []
            for row in val:
                if hasattr(row, "model_dump"):
                    rows.append(row.model_dump(mode="json"))
                elif isinstance(row, dict):
                    rows.append(row)
            lists[name] = rows
    catch_all = [
        {"section": s.section, "fields": [{"label": f.label, "value": f.value} for f in s.fields]}
        for s in getattr(data, "additional_sections", []) or []
    ]
    return {"typed_core": typed_core, "lists": lists, "catch_all": catch_all}


async def run_one(f: DiscoveredFile) -> dict[str, Any]:
    """Classify one document, then extract it with the LIVE registered extractor under the bench PII
    prompt, then belt-and-braces redact every string. Returns the per-document record (no persistence).
    ``f.media_type`` must be non-None (a readable file)."""
    assert f.media_type is not None
    content = f.path.read_bytes()

    classification = await classify_document(content, f.media_type)
    dtype = classification.document_type
    record: dict[str, Any] = {
        "source_filename": f.path.name,
        "classified_type": dtype,
        "classification_confidence": round(classification.confidence, 4),
        # the classifier's short reason can echo a snippet → belt-and-braces redact it too
        "classification_reasoning": redact_string(classification.reasoning)[0],
        "size_bytes": f.size,
    }

    extractor = EXTRACTORS.get(dtype)
    if extractor is None:
        record["extraction"] = {
            "status": "no_extractor",
            "note": f"no registered extractor for {dtype!r}",
        }
        record["findings"] = _per_document_findings(dtype, None)
        return record

    with bench_pii_prompt():  # layer 1: the model returns [NAME]/[SSN]/… placeholders
        result = await extractor(content, f.media_type)

    extraction: dict[str, Any] = {
        "status": result.status.value,
        "failure_reason": getattr(result, "failure_reason", None),
        "input_tokens": getattr(result, "input_tokens", None),
        "output_tokens": getattr(result, "output_tokens", None),
    }
    body = _result_to_record(result.data)
    # layer 2: sweep every string value for missed identity shapes (digit runs, emails, phones)
    scrubbed, redactions = redact_tree(body)
    extraction.update(scrubbed)
    extraction["belt_and_braces_redactions"] = redactions
    extraction["extraction_model"] = resolve_model(settings.anthropic_model_extraction)
    it, ot = extraction["input_tokens"], extraction["output_tokens"]
    extraction["cost_estimate"] = (
        round(
            estimate_cost(model=extraction["extraction_model"], input_tokens=it, output_tokens=ot),
            5,
        )
        if it is not None and ot is not None
        else None
    )
    record["extraction"] = extraction
    record["findings"] = _per_document_findings(dtype, body)
    return record


def _per_document_findings(dtype: str, body: dict[str, Any] | None) -> dict[str, Any]:
    """The per-document slice of the five findings (aggregated across documents in findings.py)."""
    if body is None:
        return {"typed_present": 0, "typed_null": 0, "list_row_counts": {}, "catch_all_count": 0}
    typed = body["typed_core"]
    present = [
        k for k, v in typed.items() if v is not None and (not isinstance(v, str) or v.strip())
    ]
    return {
        "typed_present": len(present),
        "typed_null": len(typed) - len(present),
        "list_row_counts": {name: len(rows) for name, rows in body["lists"].items()},
        "catch_all_count": sum(len(s["fields"]) for s in body["catch_all"]),
    }


@dataclass
class RunProgress:
    total: int
    done: int = 0
    current: str | None = None
    records: list[dict[str, Any]] = field(default_factory=list)
    cost_so_far: float = 0.0
    cancelled: bool = False
