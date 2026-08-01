"""The emitters (LP-434) — a validated :class:`Spec` → the four artifacts.

Each emitter returns TEXT (the caller writes it to a target path); nothing here
touches an existing file. The output is a verbatim mirror of the hand-written flat
extractors — ``app/ai/extraction/property_tax_bill.py`` is the reference — so the
generated module is byte-clean, ruff- and mypy-passing, and behaviourally identical
to a hand-written one for the same field set.

What is generated (guide §1): the module (field list + ``_CORE_SPEC`` + the identical
boilerplate), the prompt scaffold, the ``EXTRACTORS`` registration snippet, and the
test skeleton. What is NEVER emitted: review metadata (``why`` / ``reason_class`` /
``rejected`` / ``open_questions`` / ``rule_floor`` / ``plumbing_sites`` …), a coercer,
a ``PiiKind``, or a nested list.

The count cross-check (guide §8) is built here too — :func:`count_crosscheck_pairs`
and :func:`emit_count_crosscheck` — ready for the day a nested list is implemented,
even though nested specs are refused today.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from app.ai.extraction.generator.spec import (
    TYPE_TO_ANNOTATION,
    TYPE_TO_COERCER,
    TYPE_TO_JSON,
    TYPE_TO_PROMPT_LABEL,
    Spec,
    SpecField,
)
from app.ai.extraction.generator.validator import VALID_PII_KINDS


class GenerationError(ValueError):
    """The spec passed validation but cannot be turned into code (e.g. a non-identifier name)."""


# The backend root (…/backend), so ruff runs with the project config + first-party
# ``app`` detection. emitters.py lives at app/ai/extraction/generator/emitters.py.
_BACKEND_ROOT = Path(__file__).resolve().parents[4]


def _ruff_normalize(source: str, stdin_filename: str) -> str:
    """Pipe generated Python through ``ruff check --fix --select I`` then ``ruff format``.

    D2: the simplest way to guarantee byte-clean, import-sorted, ruff-passing output is to
    let ruff itself produce it — the emitter writes readable f-string templates and ruff
    normalizes line-wrapping and import order. ``--stdin-filename`` is set to the field's
    intended home under ``app/`` so ruff's first-party detection places ``app`` correctly.
    """
    ruff = shutil.which("ruff")
    if ruff is None:  # pragma: no cover - ruff is a dev dependency, always present in-repo
        raise GenerationError("ruff is required to normalize generated code but was not found")
    current = source
    for extra in (["check", "--fix", "--select", "I"], ["format"]):
        proc = subprocess.run(
            [ruff, *extra, "--stdin-filename", stdin_filename, "-"],
            input=current,
            capture_output=True,
            text=True,
            cwd=_BACKEND_ROOT,
            check=False,
        )
        if proc.stdout:
            current = proc.stdout
        elif proc.returncode not in (0, 1):
            raise GenerationError(f"ruff normalization failed: {proc.stderr.strip()}")
    return current


# --------------------------------------------------------------------------- #
# Naming — everything the module needs is derived from ``document_type``
# --------------------------------------------------------------------------- #


def class_prefix(document_type: str) -> str:
    """``"property_tax_bill"`` → ``"PropertyTaxBill"``; ``"w2"`` → ``"W2"``."""
    return "".join(part.capitalize() for part in document_type.split("_"))


def title(document_type: str) -> str:
    """``"property_tax_bill"`` → ``"Property Tax Bill"``."""
    return document_type.replace("_", " ").title()


def _require_identifier(document_type: str) -> None:
    if not document_type.isidentifier():
        raise GenerationError(
            f"document_type {document_type!r} is not a valid Python identifier — the class name "
            "and function names cannot be derived. A leading-digit type (e.g. '1099') is a known "
            "generator limitation; hand-write it."
        )


# --------------------------------------------------------------------------- #
# The module
# --------------------------------------------------------------------------- #

# The first-party import block is identical for every flat extractor except the
# ``parsing`` line (which depends on the coercers used).
_APP_IMPORTS_HEAD = "from app.ai.client import build_document_message\n"
_APP_IMPORTS_TAIL = (
    "from app.ai.extraction.shape import CatchAllSection, TypedField\n"
    "from app.ai.parsing import coerce_confidence, extract_json_object\n"
    "from app.ai.prompt_loader import load_prompt\n"
    "from app.models.extraction import ExtractionStatus\n"
)


def _needed_coercers(spec: Spec) -> list[str]:
    """The coercer names the module imports, sorted (``coerce_decimal`` < ``coerce_int`` …)."""
    return sorted({TYPE_TO_COERCER[f.type] for f in spec.typed_core if f.type in TYPE_TO_COERCER})


def _parsing_import(spec: Spec) -> str:
    names = [
        "CoreSpec",
        *_needed_coercers(spec),
        "derive_status",
        "parse_catch_all",
        "parse_typed_core",
    ]
    inner = ",\n".join(f"    {n}" for n in names)
    return f"from app.ai.extraction.parsing import (\n{inner},\n)\n"


def _stdlib_imports(spec: Spec) -> str:
    lines = ["import json"]
    types = {f.type for f in spec.typed_core}
    if "date" in types:
        lines.append("from datetime import date")
    if "Decimal" in types:
        lines.append("from decimal import Decimal")
    lines.append("from typing import Any")
    return "\n".join(lines) + "\n"


def emit_module(spec: Spec) -> str:
    """Generate the extractor module source for a flat, validated spec."""
    _require_identifier(spec.document_type)
    dt = spec.document_type
    prefix = class_prefix(dt)
    ttl = title(dt)
    extraction = f"{prefix}Extraction"
    result = f"{prefix}ExtractionResult"

    field_decls = "\n".join(
        f"    {f.name}: TypedField[{TYPE_TO_ANNOTATION[f.type]}] = Field(default_factory=TypedField)"
        for f in spec.typed_core
        if f.type in TYPE_TO_ANNOTATION
    )
    core_spec = "\n".join(
        f'    ("{f.name}", {TYPE_TO_COERCER[f.type]}),'
        for f in spec.typed_core
        if f.type in TYPE_TO_COERCER
    )

    source = f'''"""{ttl} extraction — GENERATED from a schema spec by the LP-434 generator.

The LP-39a shape: a typed core (each field a ``TypedField`` with source) + a grouped
catch-all (``additional_sections``). Honest nulls, graceful ``.failed()``, and
metadata-only logging — a verbatim mirror of the hand-written flat extractors
(``property_tax_bill`` is the reference).

**GENERATED STARTER — accuracy is UNVALIDATED.** The field set comes from the spec and
the prompt is a scaffold; both need a human pass and Priya's review of real extractions
before they are trusted (guide §11). Structurally correct and mechanically tested is not
the same as tuned.
"""

{_stdlib_imports(spec)}
import structlog
from pydantic import BaseModel, Field, ValidationError

{_APP_IMPORTS_HEAD}from app.ai.extraction.model_call import run_extraction_completion
{_parsing_import(spec)}{_APP_IMPORTS_TAIL}
logger = structlog.get_logger(__name__)

_PROMPT_PATH = "extraction/{dt}.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({{"application/pdf", "image/jpeg", "image/png", "image/jpg"}})
# Bounded fixed-form output → the 4096 scaffold budget (guide §7). Tune per the sizing
# rule; the test_extraction_budget_sizing CI guard enforces consistency.
_MAX_TOKENS = 4096


class {extraction}(BaseModel):
    """A {ttl.lower()} in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
{field_decls}

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class {result}(BaseModel):
    """A {ttl.lower()} extraction plus its outcome (mirrors the other extractor results)."""

    data: {extraction}
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "{result}":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data={extraction}(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
{core_spec}
)


def _parse_{dt}_json(text: str) -> {result} | None:
    """Defensively parse a model response into a {ttl.lower()} result. Never raises."""
    snippet = extract_json_object(text)
    if snippet is None:
        return None
    try:
        payload: Any = json.loads(snippet)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None

    core_payload, non_null, coercion_lost = parse_typed_core(payload, _CORE_SPEC)
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = {extraction}.model_validate({{**core_payload, "additional_sections": sections}})
    except ValidationError:
        return None

    status = derive_status(non_null, coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return {result}(data=data, status=status, confidence=confidence, reasoning=reasoning)


async def extract_{dt}(content: bytes, media_type: str) -> {result}:
    """Extract {ttl.lower()} values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return {result}.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return {result}.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="{dt}",
    )
    if call.text is None:
        return {result}.failed(call.failure_reason or "AI call failed")

    result = _parse_{dt}_json(call.text)
    if result is None:
        logger.warning("{dt}_extraction_parse_failed")  # no raw response logged
        return {result}.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "{dt}_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
'''
    return _ruff_normalize(source, f"app/ai/extraction/{dt}.py")


# --------------------------------------------------------------------------- #
# The prompt scaffold
# --------------------------------------------------------------------------- #

_PROMPT_CONFIDENCE_BLOCK = """PER-FIELD CONFIDENCE — in addition to the per-document "confidence" below, return a
"field_confidence" object mapping EACH typed-core field name to your certainty
(a number 0.0-1.0) that THAT field's value is correct. Use null for any field you
cannot assess (absent, illegible, or uncertain). Rate each field independently and
never inflate. Example: "field_confidence": {"<field_a>": 0.95, "<field_b>": 0.7}."""


def emit_prompt(spec: Spec) -> str:
    """Generate the prompt scaffold — the byte-identical framing + this spec's field block."""
    ttl_upper = title(spec.document_type).upper()
    fields = [f for f in spec.typed_core if f.type in TYPE_TO_PROMPT_LABEL]
    pad = max((len(f.name) for f in fields), default=0)

    core_lines = []
    for f in fields:
        label = TYPE_TO_PROMPT_LABEL[f.type or "str"]
        hint = f" {f.prompt_hint}" if f.prompt_hint else ""
        core_lines.append(f"     {f.name.ljust(pad)}  ({label}){hint}")

    contract_lines = []
    for f in fields:
        json_type = TYPE_TO_JSON[f.type or "str"]
        contract_lines.append(
            f'    "{f.name}": {{"value": <{json_type}|null>, '
            '"page": <int|null>, "snippet": <string|null>}'
        )

    has_ssn = any(f.pii_kind == "SSN" for f in fields)
    has_pii = any(f.pii_kind in VALID_PII_KINDS for f in fields)
    has_pre_masked = any(f.pii_pre_masked for f in fields)

    pii_rules = []
    if has_pii:
        pii_rules.append(
            "  - NEVER place an SSN or account number in additional_sections — catch-all "
            "values are stored unmasked; keep every identifier in its named typed-core slot."
        )
    if has_pre_masked:
        pii_rules.append(
            "  - For any masked field, output the LAST 4 CHARACTERS ONLY — never the full value."
        )
    pii_block = ("\n" + "\n".join(pii_rules)) if pii_rules else ""

    reasoning_hint = (
        "<one short sentence; do NOT quote the full SSN>"
        if has_ssn
        else "<one short sentence describing the document>"
    )

    return f"""GENERATED STARTER PROMPT (LP-434) — REPLACE WITH / MERGE INTO THE TUNED {ttl_upper}
PROMPT. A scaffold so the module works end-to-end; keep the JSON contract below. The
typed-core field set comes from the schema spec — refine the wording with Priya.
----------------------------------------------------------------------

You are a data extraction assistant for a US residential mortgage loan processor.
You are given a single {ttl_upper}. Read it faithfully and return structured data.

CAPTURE EVERYTHING ON THE DOCUMENT — lose nothing. There are two buckets:

1. TYPED CORE — put these into their named slots:
{chr(10).join(core_lines)}

2. ADDITIONAL SECTIONS — EVERYTHING ELSE, grouped by section (e.g. "Other"). Do not
   force these into the typed core — capture them here so nothing is lost.

FOR EVERY FIELD include WHERE you read it:
  - "page"    (integer)  the 1-based page the value appears on
  - "snippet" (string)   the verbatim text you read the value from

CRITICAL RULES:
  - If a value is NOT present or NOT legible, use null — NEVER guess or invent.
  - Money may include "$"/commas (they will be parsed); dates in any common format.{pii_block}

{_PROMPT_CONFIDENCE_BLOCK}

Respond with ONLY a single JSON object, no markdown fences and no prose, exactly:
{{
  "typed_core": {{
{",\n".join(contract_lines)}
  }},
  "additional_sections": [
    {{"section": "<section name>", "fields": [
      {{"label": "<field label>", "value": <string|null>, "page": <int|null>, "snippet": <string|null>}}
    ]}}
  ],
  "field_confidence": {{"<typed_core field name>": <0.0-1.0|null>, "...": <0.0-1.0|null>}},
  "confidence": <number 0.0-1.0>,
  "reasoning": "{reasoning_hint}"
}}
"""


# --------------------------------------------------------------------------- #
# The EXTRACTORS registration snippet (guide §2, site 4) — reported, never patched
# --------------------------------------------------------------------------- #


def emit_registration(spec: Spec) -> str:
    """The two lines to add to ``app/ai/extraction/__init__.py`` (import + EXTRACTORS entry)."""
    dt = spec.document_type
    return (
        f"# Add to app/ai/extraction/__init__.py:\n"
        f"from app.ai.extraction.{dt} import extract_{dt}\n"
        f"# ... and inside the EXTRACTORS dict:\n"
        f'    "{dt}": extract_{dt},\n'
    )


# --------------------------------------------------------------------------- #
# The test skeleton
# --------------------------------------------------------------------------- #


def _sample_value(field: SpecField) -> str:
    return {
        "str": '"SAMPLE"',
        "Decimal": '"1234.56"',
        "date": '"2024-01-15"',
        "int": "2024",
    }.get(field.type or "str", '"SAMPLE"')


def emit_test(spec: Spec) -> str:
    """Generate the shape/mechanism test skeleton — the AI wrapper mocked (guide §10)."""
    _require_identifier(spec.document_type)
    dt = spec.document_type
    prefix = class_prefix(dt)
    extraction = f"{prefix}Extraction"
    result = f"{prefix}ExtractionResult"
    fields = [f for f in spec.typed_core if f.type in TYPE_TO_ANNOTATION]
    first = fields[0]

    payload_lines = "\n".join(f'        "{f.name}": _core({_sample_value(f)}),' for f in fields)
    # ``Decimal`` is referenced only in the first-field assertion below.
    decimal_import = "from decimal import Decimal\n" if first.type == "Decimal" else ""
    # A representative typed-core assertion on the first field.
    if first.type == "Decimal":
        first_assert = f'assert d.{first.name}.value == Decimal("1234.56")'
    elif first.type == "int":
        first_assert = f"assert d.{first.name}.value == 2024"
    elif first.type == "date":
        first_assert = f'assert str(d.{first.name}.value) == "2024-01-15"'
    else:
        first_assert = f'assert d.{first.name}.value == "SAMPLE"'

    source = f'''"""Tests for {title(dt).lower()} extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

Shape/mechanism, not accuracy (guide §10): the typed core is coerced with source, an
all-null core is FAILED, unparseable JSON returns None, and the ``.failed()`` factory
holds. No real samples exist — accuracy is validated as real documents flow through.
"""

import json
{decimal_import}from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.ai.client import AIClientError
from app.ai.extraction import model_call
from app.ai.extraction.{dt} import (
    {extraction},
    {result},
    _parse_{dt}_json,
    extract_{dt},
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy {dt}"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {{"value": value, "page": page, "snippet": snippet}}


FULL_PAYLOAD = {{
    "typed_core": {{
{payload_lines}
    }},
    "additional_sections": [
        {{"section": "Other", "fields": [{{"label": "Note", "value": "x"}}]}}
    ],
    "confidence": 0.9,
    "reasoning": "generated test fixture.",
}}
FULL_JSON = json.dumps(FULL_PAYLOAD)


def _mock_complete(monkeypatch: pytest.MonkeyPatch, *, text: str | None = None,
                   exc: Exception | None = None) -> AsyncMock:
    if exc is not None:
        mock = AsyncMock(side_effect=exc)
    else:
        mock = AsyncMock(
            return_value=SimpleNamespace(
                text=text, input_tokens=150, output_tokens=60, model="m", stop_reason="end_turn"
            )
        )
    monkeypatch.setattr(model_call, "complete", mock)
    return mock


def test_typed_core_coerced_with_source() -> None:
    d = _parse_{dt}_json(FULL_JSON).data  # type: ignore[union-attr]
    {first_assert}
    assert d.{first.name}.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {{"typed_core": {{"{first.name}": _core(None)}}}}
    parsed = _parse_{dt}_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_{dt}_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_{dt}(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_{dt}(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = {result}.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == {extraction}()
'''
    return _ruff_normalize(source, f"tests/ai/test_{dt}_extraction.py")


# --------------------------------------------------------------------------- #
# The count cross-check (guide §8) — built ready, though nested specs are refused
# --------------------------------------------------------------------------- #


def count_crosscheck_pairs(spec: Spec) -> list[tuple[str, str]]:
    """``(count_field, list_name)`` pairs where a ``*_count`` field matches a nested list.

    A ``foo_count`` field matches a list named ``foos`` / ``foo`` / any list whose name
    contains the ``foo`` stem (``tradeline_count`` → ``tradelines``; ``comparable_count``
    → ``comparable_sales``; ``condition_count`` → ``aus_required_conditions``).
    """
    pairs: list[tuple[str, str]] = []
    for f in spec.typed_core:
        if not f.name.endswith("_count"):
            continue
        stem = f.name[: -len("_count")]
        for nested in spec.nested_lists:
            if nested.name in (f"{stem}s", stem) or stem in nested.name:
                pairs.append((f.name, nested.name))
                break
    return pairs


def emit_count_crosscheck(count_field: str, list_name: str) -> str:
    """Code text comparing a declared ``*_count`` to the actual row count → PARTIAL on mismatch.

    This closes the model-self-truncation gap the API truncation guard cannot see (guide
    §8): if the model emits fewer rows than it declared WITHOUT the API truncating, the
    extraction must never report success. Emitted for a nested-list implementation to drop
    into its parser (nested lists are otherwise their own ticket)."""
    return (
        f"# Count cross-check (guide §8, LP-434): the model's own declared {count_field} vs the\n"
        f"# actual number of {list_name} rows. A mismatch means rows were dropped or summarised\n"
        "# WITHOUT the API truncating (the truncation guard cannot see this) → never succeed.\n"
        f"declared = data.{count_field}.value\n"
        f"actual = len(data.{list_name})\n"
        "if declared is not None and declared != actual:\n"
        "    status = ExtractionStatus.PARTIAL\n"
    )


# --------------------------------------------------------------------------- #
# Diff mode (guide §6, D6) — a REPORT of what to add, never a patch
# --------------------------------------------------------------------------- #


def emit_diff_report(spec: Spec) -> str:
    """For a spec with a shipping extractor: a report of the ``exists_today: false`` additions.

    Never rewrites or patches the module (a bad patch to a shipping extractor is worse than
    a manual edit — D6). Each addition is annotated ADD (mechanical) or BLOCKED (needs a
    human: an absent PII kind, or a nested list)."""
    lines = [
        f"# Diff-mode report — {spec.document_type} (existing: {spec.existing_extractor})",
        "#",
        "# A shipping extractor exists. This is a REPORT of what the spec adds, NOT a patch",
        "# (guide §6 / D6). Apply the ADD items by hand; each BLOCKED item is its own ticket.",
        "",
    ]
    new_fields = spec.new_fields
    if not new_fields and not spec.nested_lists:
        lines.append("No exists_today:false fields and no nested lists — nothing to add.")
        return "\n".join(lines) + "\n"

    lines.append(f"## Typed-core additions ({len(new_fields)})")
    for f in new_fields:
        if not f.reason_class:
            lines.append(f"- BLOCKED  {f.name}: no reason_class (spec incomplete)")
        elif f.type not in TYPE_TO_ANNOTATION:
            lines.append(f"- BLOCKED  {f.name}: type {f.type!r} has no coercer")
        elif f.pii_kind is not None and f.pii_kind not in VALID_PII_KINDS:
            lines.append(
                f"- BLOCKED  {f.name}: pii.kind {f.pii_kind!r} not in PiiKind "
                f"{sorted(VALID_PII_KINDS)} — needs a mask strategy (its own ticket)"
            )
        else:
            coercer = TYPE_TO_COERCER[f.type]
            pii = (
                f" + _PII_FIELDS[{f.pii_kind}, pre_masked={f.pii_pre_masked}]" if f.pii_kind else ""
            )
            lines.append(f"- ADD      {f.name}: TypedField[{f.type}] / {coercer}{pii}")

    if spec.nested_lists:
        lines.append("")
        lines.append(f"## Nested lists ({len(spec.nested_lists)}) — each a bespoke ~5-file ticket")
        for nested in spec.nested_lists:
            lines.append(
                f"- BLOCKED  {nested.name} (guide §4): parser + snapshot Record + reshaper + consumer"
            )
    return "\n".join(lines) + "\n"
