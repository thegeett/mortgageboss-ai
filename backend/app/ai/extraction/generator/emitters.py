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

Nested lists are GENERIC since LP-437/438 (no longer refused): :func:`emit_list_specs` emits a
``ListSpec`` + registration snippet per list, and the count cross-check (guide §8,
:func:`count_crosscheck_pairs` / :func:`emit_count_crosscheck`) fires where a ``<list>_count`` field
sits beside a matching list.
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
    NestedListField,
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


def _list_row_coercer(field: NestedListField) -> str:
    """The coercer for a nested-list row field. A list-row value is stringified at
    ``model_dump(mode="json")`` regardless, so an unknown/absent type coerces as ``coerce_str``
    (never dropped for want of a coercer — the list capture is deliberately permissive)."""
    return TYPE_TO_COERCER.get(field.type or "str", "coerce_str")


def _needed_coercers(spec: Spec) -> list[str]:
    """The coercer names the module imports, sorted — typed core AND every nested-list row field
    (LP-443: the list capture coerces each declared row field, mirroring bank_statement)."""
    core = {TYPE_TO_COERCER[f.type] for f in spec.typed_core if f.type in TYPE_TO_COERCER}
    rows = {_list_row_coercer(f) for nl in spec.nested_lists for f in nl.fields}
    return sorted(core | rows)


def _parsing_import(spec: Spec) -> str:
    names = [
        "CoreSpec",
        *_needed_coercers(spec),
        "derive_status",
        "parse_catch_all",
        "parse_typed_core",
    ]
    if spec.nested_lists:  # LP-443 — the list capture keeps a per-row page/snippet source
        names.append("source_payload")
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


def max_tokens_for(spec: Spec) -> int:
    """Derive ``_MAX_TOKENS`` from output shape (guide §7; D3), respecting the CI budget guard.

    A list-bearing spec is NOT a 4096 document — the model emits the whole list in its response, so the
    OUTPUT is large even though the module is flat. Sizing:
      * no nested list → 4096 (bounded fixed-form, the scaffold budget);
      * one nested list → 8192 (an unbounded "capture every X" — bank_statement / investment shape);
      * two or more nested lists → 16384 (the densest — the tax-return / credit-report shape).
    """
    n = len(spec.nested_lists)
    if n == 0:
        return 4096
    return 8192 if n == 1 else 16384


def _list_row_const(list_name: str) -> str:
    return f"_{list_name.upper()}_ROW"


def _list_capture_decls(spec: Spec) -> str:
    """The capture field for each nested list — a bare-row ``list[dict]`` (LP-443).

    Stored as ``list[dict[str, Any]]`` (bare scalars + a per-row source), the SAME shape the shipping
    ``bank_statement.transactions`` stores and the generic snapshot reader expects — so a single stored
    shape serves every list. Empty string for a flat spec."""
    if not spec.nested_lists:
        return ""
    decls = "\n".join(
        f"    {nl.name}: list[dict[str, Any]] = Field(default_factory=list)"
        for nl in spec.nested_lists
    )
    return (
        "\n\n    # --- Captured nested lists (LP-443) — bare rows, snapshot-read generically ------- #\n"
        + decls
    )


def _list_parsers(spec: Spec) -> str:
    """A row coerce-spec + a ``_parse_<list>`` helper per nested list (LP-443).

    Mirrors ``bank_statement._parse_transactions``: each declared field is coerced, a per-row
    page/snippet ``source`` is kept, and a fully-empty row is dropped (no hallucinated rows). Empty
    string for a flat spec."""
    if not spec.nested_lists:
        return ""
    blocks: list[str] = []
    for nl in spec.nested_lists:
        const = _list_row_const(nl.name)
        rows = "\n".join(f'    ("{f.name}", {_list_row_coercer(f)}),' for f in nl.fields)
        blocks.append(
            f"""{const}: CoreSpec = (
{rows}
)


def _parse_{nl.name}(raw: Any) -> list[dict[str, Any]]:
    \"\"\"Coerce the {nl.name} rows — bare scalars + a per-row page/snippet source (LP-443 capture).

    Mirrors bank_statement's transactions parse: each declared field is coerced, a per-row source is
    kept, and a fully-empty row is dropped (no hallucinated rows).\"\"\"
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        row: dict[str, Any] = {{name: coerce(entry.get(name)) for name, coerce in {const}}}
        if "source" not in row:  # never clobber a declared 'source' data field; else keep provenance
            row["source"] = source_payload(entry)
        if any(row[name] is not None for name, _ in {const}):
            rows.append(row)
    return rows"""
        )
    return "\n\n\n" + "\n\n\n".join(blocks)


def _list_parse_calls(spec: Spec) -> str:
    """The ``<list> = _parse_<list>(payload.get("<list>"))`` lines inside the JSON parser."""
    return "".join(
        f'    {nl.name} = _parse_{nl.name}(payload.get("{nl.name}"))\n' for nl in spec.nested_lists
    )


def _list_validate_kwargs(spec: Spec) -> str:
    """The ``"<list>": <list>,`` entries spliced into ``model_validate({...})``."""
    return "".join(f'"{nl.name}": {nl.name}, ' for nl in spec.nested_lists)


def _list_status_addend(spec: Spec) -> str:
    """``+ len(<list>) ...`` — list rows count as extracted content (a doc may be mostly its list),
    mirroring bank_statement's ``non_null + len(transactions)``."""
    return "".join(f" + len({nl.name})" for nl in spec.nested_lists)


def _list_count_crosschecks(spec: Spec) -> str:
    """Inlined count cross-check(s): a declared ``*_count`` that disagrees with the captured row
    count downgrades a SUCCEEDED extraction to PARTIAL (guide §8) — never a silent success when the
    model dropped rows the API did not truncate. Only downgrades SUCCEEDED (a FAILED stays FAILED)."""
    pairs = count_crosscheck_pairs(spec)
    if not pairs:
        return ""
    lines = [
        "\n    # Count cross-check (guide §8, LP-443): a declared count that disagrees with the"
    ]
    lines.append(
        "    # captured row count means rows were dropped WITHOUT the API truncating → PARTIAL."
    )
    for count_field, list_name in pairs:
        lines.append(
            f"    if (\n"
            f"        status is ExtractionStatus.SUCCEEDED\n"
            f"        and data.{count_field}.value is not None\n"
            f"        and data.{count_field}.value != len(data.{list_name})\n"
            f"    ):\n"
            f"        status = ExtractionStatus.PARTIAL"
        )
    return "\n".join(lines) + "\n"


def _list_log_kwargs(spec: Spec) -> str:
    """``list_rows_total=...`` for the done-log (metadata only — counts, never values)."""
    if not spec.nested_lists:
        return ""
    total = " + ".join(f"len(result.data.{nl.name})" for nl in spec.nested_lists)
    return f"\n        list_rows_total={total},"


def emit_module(spec: Spec) -> str:
    """Generate the extractor module source for a validated spec (flat or list-bearing, LP-443)."""
    _require_identifier(spec.document_type)
    dt = spec.document_type
    prefix = class_prefix(dt)
    ttl = title(dt)
    extraction = f"{prefix}Extraction"
    result = f"{prefix}ExtractionResult"
    max_tokens = max_tokens_for(spec)
    budget_note = (
        "Bounded fixed-form output → the 4096 scaffold budget (guide §7)."
        if max_tokens == 4096
        else f"Unbounded list output → {max_tokens} (guide §7 sizing rule; {len(spec.nested_lists)} nested "
        "list(s))."
    )

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
# {budget_note}
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = {max_tokens}


class {extraction}(BaseModel):
    """A {ttl.lower()} in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
{field_decls}{_list_capture_decls(spec)}

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
){_list_parsers(spec)}


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
{_list_parse_calls(spec)}    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = {extraction}.model_validate(
            {{**core_payload, {_list_validate_kwargs(spec)}"additional_sections": sections}}
        )
    except ValidationError:
        return None

    status = derive_status(non_null{_list_status_addend(spec)}, coercion_lost)
{_list_count_crosschecks(spec)}    confidence = coerce_confidence(payload.get("confidence"))
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
        catch_all_sections=len(result.data.additional_sections),{_list_log_kwargs(spec)}
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

    # Nested lists (LP-438) — the flat_row shape: one bare row per item + a page/snippet source.
    nested_block = ""
    nested_contract = ""
    if spec.nested_lists:
        blk = [
            "",
            "3. NESTED LISTS — one FLAT ROW per repeating item (bare values + a page/snippet):",
        ]
        for nl in spec.nested_lists:
            blk.append(f"     {nl.name} — each row: " + ", ".join(f.name for f in nl.fields))
        if count_crosscheck_pairs(spec):
            blk.append(
                "   Read the TOTAL COUNT from the document's summary FIRST, then list every item "
                "(a count that disagrees with the rows marks the extraction PARTIAL)."
            )
        nested_block = "\n".join(blk) + "\n"
        for nl in spec.nested_lists:
            row = ", ".join(
                f'"{f.name}": <{TYPE_TO_JSON.get(f.type or "str", "string")}|null>'
                for f in nl.fields
            )
            nested_contract += (
                f',\n  "{nl.name}": [{{{row}, "page": <int|null>, "snippet": <string|null>}}]'
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
{nested_block}
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
  ]{nested_contract},
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


def emit_pii_registration(spec: Spec) -> str:
    """The ``_PII_FIELDS`` snippet for this spec's PII typed-core fields (step 7 wires it), or ``""``.

    ``pii.kind`` (already remapped to the live enum by LP-439 → ``SSN`` / ``ACCOUNT``) → a
    ``documents_section._PII_FIELDS`` entry ``field → (PiiKind.X, pre_masked)``. A snippet, never a patch.
    """
    lines = [
        f'    "{f.name}": (PiiKind.{f.pii_kind}, {f.pii_pre_masked}),'
        for f in spec.typed_core
        if f.pii_kind in VALID_PII_KINDS
    ]
    if not lines:
        return ""
    return (
        "# Add to app/verification/snapshot/documents_section.py::_PII_FIELDS "
        "(a snippet, never a patch):\n" + "\n".join(lines) + "\n"
    )


# --------------------------------------------------------------------------- #
# The test skeleton
# --------------------------------------------------------------------------- #


def _sample_for_type(type_name: str | None) -> str:
    return {
        "str": '"SAMPLE"',
        "Decimal": '"1234.56"',
        "date": '"2024-01-15"',
        "int": "2024",
    }.get(type_name or "str", '"SAMPLE"')


def _sample_value(field: SpecField) -> str:
    return _sample_for_type(field.type)


def emit_test(spec: Spec) -> str:
    """Generate the shape/mechanism test skeleton — the AI wrapper mocked (guide §10)."""
    _require_identifier(spec.document_type)
    dt = spec.document_type
    prefix = class_prefix(dt)
    extraction = f"{prefix}Extraction"
    result = f"{prefix}ExtractionResult"
    fields = [f for f in spec.typed_core if f.type in TYPE_TO_ANNOTATION]
    first = fields[0]

    # A ``*_count`` field with a matching list gets the SAME value as the sample-row count so the
    # happy-path payload does not trip the count cross-check (LP-443) → the test still asserts SUCCEEDED.
    crosscheck_counts = {cf for cf, _ in count_crosscheck_pairs(spec)}
    n_sample_rows = 1

    def _payload_sample(f: SpecField) -> str:
        return str(n_sample_rows) if f.name in crosscheck_counts else _sample_value(f)

    payload_lines = "\n".join(f'        "{f.name}": _core({_payload_sample(f)}),' for f in fields)

    # One sample row per nested list (LP-443) — so the capture is exercised and any count matches.
    list_lines = ""
    for nl in spec.nested_lists:
        row = ", ".join(f'"{lf.name}": {_sample_for_type(lf.type)}' for lf in nl.fields)
        list_lines += f'    "{nl.name}": [{{{row}, "page": 1, "snippet": "s"}}],\n'

    # ``Decimal`` is referenced only in the first-field assertion below.
    decimal_import = "from decimal import Decimal\n" if first.type == "Decimal" else ""
    # A representative typed-core assertion on the first field.
    if first.name in crosscheck_counts:
        first_assert = f"assert d.{first.name}.value == {n_sample_rows}"
    elif first.type == "Decimal":
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
{list_lines}    "confidence": 0.9,
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
# Generic nested lists (LP-437/438) — emit a ListSpec + its registration per list
# --------------------------------------------------------------------------- #


def _list_const(list_name: str) -> str:
    return f"_{list_name.upper()}_LIST"


def emit_list_specs(spec: Spec) -> str:
    """Per ``nested_lists`` entry, the LP-437 ``ListSpec`` construction + its ``_LIST_SPECS`` registration.

    The generic mechanism (LP-437) makes a nested list a DECLARATION, not ~5 bespoke files: the emitted
    ``ListSpec`` names the row fields and the three declarable helpers (``derived`` fail-closed on an
    unmapped value, ``redact`` over named fields, ``stable_row_id``). Returns ``""`` for a flat spec.

    The registration is emitted as a SNIPPET (like the ``EXTRACTORS`` registration) — never a patch to the
    shared ``documents_section._LIST_SPECS`` file (a merge-conflict factory, D2). Wiring is a later step.
    """
    if not spec.nested_lists:
        return ""
    blocks: list[str] = []
    consts: list[str] = []
    for nl in spec.nested_lists:
        const = _list_const(nl.name)
        consts.append(const)
        names = ", ".join(f'"{f.name}"' for f in nl.fields)
        parts = [
            f'    name="{nl.name}",',
            f"    fields=({names},)," if nl.fields else "    fields=(),",
        ]
        if nl.derived:
            dl = []
            for d in nl.derived:
                mp = ", ".join(f'"{k}": "{v}"' for k, v in d.mapping.items())
                dl.append(
                    f'        DerivedSpec(field="{d.field}", from_field="{d.from_field}", '
                    f"mapping={{{mp}}}),"
                )
            parts.append("    derived=(\n" + "\n".join(dl) + "\n    ),")
        if nl.redact:
            parts.append("    redact=frozenset({" + ", ".join(f'"{r}"' for r in nl.redact) + "}),")
        if nl.stable_row_id:
            parts.append("    stable_row_id=True,")
        blocks.append(f"{const} = ListSpec(\n" + "\n".join(parts) + "\n)")
    reg = f'    "{spec.document_type}": ({", ".join(consts)},),'
    return (
        "# Generic nested lists (LP-437/438) — the ListSpec(s) + registration for this document type.\n"
        "# from app.verification.snapshot.documents_section import ListSpec, DerivedSpec\n\n"
        + "\n\n".join(blocks)
        + "\n\n# Register in app/verification/snapshot/documents_section.py::_LIST_SPECS (a snippet, "
        "never a patch — D2):\n" + reg + "\n"
    )


def emit_count_crosschecks(spec: Spec) -> str:
    """The count cross-check(s) for every ``<list>_count`` field beside a matching list (guide §8).

    Now reachable (nested lists are generatable — LP-438): each closes the model-self-truncation gap the
    API truncation guard cannot see. ``""`` when the spec has no matching ``*_count`` + list pair.
    """
    pairs = count_crosscheck_pairs(spec)
    if not pairs:
        return ""
    return "\n".join(emit_count_crosscheck(cf, ln) for cf, ln in pairs)


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
        lines.append(
            f"## Nested lists ({len(spec.nested_lists)}) — GENERIC (LP-437): a declaration, not ~5 files"
        )
        for nested in spec.nested_lists:
            extras = []
            if nested.derived:
                extras.append(f"derived={[d.field for d in nested.derived]}")
            if nested.redact:
                extras.append(f"redact={list(nested.redact)}")
            if nested.stable_row_id:
                extras.append("stable_row_id")
            tail = f" [{', '.join(extras)}]" if extras else ""
            lines.append(
                f"- ADD      {nested.name}: {len(nested.fields)} row fields{tail} "
                "(+ a per-rule consumer — enumerator or derived recipe — as separate follow-up)"
            )
        lines.append("")
        lines.append(emit_list_specs(spec).rstrip())
        crosschecks = emit_count_crosschecks(spec)
        if crosschecks:
            lines.append("")
            lines.append("## Count cross-check(s) (guide §8) — count ≠ row count → PARTIAL")
            lines.append(crosschecks.rstrip())
    return "\n".join(lines) + "\n"
