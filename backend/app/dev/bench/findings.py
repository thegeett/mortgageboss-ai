"""The five findings + the cross-document report writers.

Everything here is EVIDENCE for a human. It reports numbers; it never diagnoses which of several causes
produced a null field, and it never proposes or applies a change. And every "populated" count is
COVERAGE (was the field filled), never accuracy (is the value right) — the report says so.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

# A COARSE rule -> expected-document-type map for finding 5, by rule-id prefix (the category). It is
# deliberately coarse (a rule may read several documents); the report labels it as such. It answers
# "did a document this family of rules needs even appear in the corpus", not the full LP-451 gate.
_RULE_PREFIX_DOC_TYPES: dict[str, list[str]] = {
    "AS": ["bank_statement", "verification_of_assets", "investment_account", "retirement_account"],
    "CR": ["credit_report"],
    "IN": ["pay_stub", "w2", "voe", "1099", "tax_return"],
    "DT": ["pay_stub", "w2", "credit_report"],
    "IH": [
        "homeowners_insurance",
        "flood_insurance_policy",
        "master_insurance_policy_for_condominium",
    ],
    "PC": ["purchase_agreement"],
    "PR": ["appraisal"],
    "TI": ["title_commitment"],
    "AU": ["aus_findings"],
    "CO": ["condo_questionnaire", "master_insurance_policy_for_condominium"],
    "MI": ["mortgage_insurance_certificate"],
    "PE": ["aus_findings", "uniform_residential_loan_application"],
    "CL": ["rate_lock_confirmation"],
    "LO": ["letter_of_explanation"],
    "FR": ["bank_statement", "purchase_agreement", "credit_report"],
    "OC": ["uniform_residential_loan_application"],
    "RE": ["mortgage_statement", "property_tax_bill"],
    "ID": ["drivers_license", "uniform_residential_loan_application"],
}

_VOCAB_TOP = 25  # cap distinct values shown per field
_OPEN_ENDED_RATIO = (
    0.6  # distinct/populated above this ⇒ flag the field as open-ended (rule-unbackable)
)


def _by_type(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        out[r["classified_type"]].append(r)
    return out


def coverage(type_records: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Finding 1 — per typed-core field, populated on N of M documents of this type (COVERAGE)."""
    m = 0
    populated: Counter[str] = Counter()
    fields_seen: set[str] = set()
    for r in type_records:
        body = r.get("extraction") or {}
        typed = body.get("typed_core")
        if typed is None:
            continue
        m += 1
        for k, v in typed.items():
            fields_seen.add(k)
            if v is not None and (not isinstance(v, str) or v.strip()):
                populated[k] += 1
    return {k: {"populated": populated.get(k, 0), "of": m} for k in sorted(fields_seen)}


def value_vocabulary(type_records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Finding 2 (the most valuable) — every distinct value each typed field returned, with counts, and a
    flag for fields whose values look OPEN-ENDED (free text / issuer codes) — those cannot back a
    deterministic rule."""
    values: dict[str, Counter[str]] = defaultdict(Counter)
    for r in type_records:
        typed = (r.get("extraction") or {}).get("typed_core") or {}
        for k, v in typed.items():
            if v is not None and (not isinstance(v, str) or v.strip()):
                values[k][str(v)] += 1
    out: dict[str, dict[str, Any]] = {}
    for k, counter in sorted(values.items()):
        populated = sum(counter.values())
        distinct = len(counter)
        open_ended = populated >= 4 and distinct / populated >= _OPEN_ENDED_RATIO
        out[k] = {
            "distinct": distinct,
            "populated": populated,
            "open_ended_flag": open_ended,
            "top_values": counter.most_common(_VOCAB_TOP),
        }
    return out


def stranded_data(type_records: list[dict[str, Any]]) -> dict[str, Any]:
    """Finding 3 — the catch-all for this type, grouped by label, with counts. A label recurring across
    many documents is a schema gap (something valuable captured but not typed)."""
    labels: Counter[str] = Counter()
    docs_with_catchall = 0
    for r in type_records:
        catch = (r.get("extraction") or {}).get("catch_all") or []
        if catch:
            docs_with_catchall += 1
        for section in catch:
            for f in section.get("fields", []):
                labels[f"{section['section']} :: {f['label']}"] += 1
    return {
        "docs_with_catch_all": docs_with_catchall,
        "of": len(type_records),
        "labels_by_frequency": labels.most_common(50),
    }


def classification(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Finding 4 — confidence distribution, low-confidence documents, and confusable type pairs (watched:
    termite_report/termite_completion, property_tax_bill/_non_subject, the letter_of_explanation_* variants,
    trust_documents/trust_agreement)."""
    confs = [r["classification_confidence"] for r in records]
    buckets = {"<0.5": 0, "0.5-0.7": 0, "0.7-0.9": 0, ">=0.9": 0}
    for c in confs:
        if c < 0.5:
            buckets["<0.5"] += 1
        elif c < 0.7:
            buckets["0.5-0.7"] += 1
        elif c < 0.9:
            buckets["0.7-0.9"] += 1
        else:
            buckets[">=0.9"] += 1
    low = sorted(
        (
            {
                "file": r["source_filename"],
                "type": r["classified_type"],
                "confidence": r["classification_confidence"],
            }
            for r in records
            if r["classification_confidence"] < 0.7
        ),
        key=lambda x: x["confidence"],
    )
    return {
        "confidence_buckets": buckets,
        "low_confidence": low,
        "types_seen": dict(Counter(r["classified_type"] for r in records)),
    }


def rule_readiness(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Finding 5 — per rule prefix (category), did a needed document type appear, and (if so) its coverage.
    COARSE (a rule may read several documents); reported as a family-level readiness table, not the full gate."""
    types_present = {
        r["classified_type"] for r in records if (r.get("extraction") or {}).get("typed_core")
    }
    cov_by_type = {t: coverage(recs) for t, recs in _by_type(records).items()}
    out: list[dict[str, Any]] = []
    for prefix, doc_types in sorted(_RULE_PREFIX_DOC_TYPES.items()):
        appeared = [t for t in doc_types if t in types_present]
        avg_fill = None
        if appeared:
            fills = []
            for t in appeared:
                cov = cov_by_type.get(t, {})
                if cov:
                    fills.append(
                        sum(f["populated"] for f in cov.values())
                        / max(sum(f["of"] for f in cov.values()), 1)
                    )
            avg_fill = round(sum(fills) / len(fills), 3) if fills else None
        out.append(
            {
                "rule_family": prefix,
                "expected_doc_types": doc_types,
                "appeared_in_corpus": appeared,
                "any_appeared": bool(appeared),
                "avg_typed_fill_rate": avg_fill,
            }
        )
    return out


def write_output(root: Path, records: list[dict[str, Any]], out_dir: Path) -> dict[str, Any]:
    """Write per-document JSON (output/<type>/<n>-<file>.json), _SUMMARY.md, and _FINDINGS.csv. No DB."""
    out_dir.mkdir(parents=True, exist_ok=True)
    per_type = _by_type(records)
    # per-document JSON, foldered by type
    for dtype, recs in per_type.items():
        type_dir = out_dir / dtype
        type_dir.mkdir(parents=True, exist_ok=True)
        for i, r in enumerate(recs, 1):
            safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in r["source_filename"])[
                :80
            ]
            (type_dir / f"{i}-{safe}.json").write_text(
                json.dumps(r, indent=1, default=str), encoding="utf-8"
            )

    findings_by_type = {
        dtype: {
            "documents": len(recs),
            "coverage": coverage(recs),
            "value_vocabulary": value_vocabulary(recs),
            "stranded_data": stranded_data(recs),
        }
        for dtype, recs in sorted(per_type.items())
    }
    cls = classification(records)
    readiness = rule_readiness(records)

    _write_findings_csv(out_dir / "_FINDINGS.csv", findings_by_type)
    summary = _render_summary(root, records, findings_by_type, cls, readiness)
    (out_dir / "_SUMMARY.md").write_text(summary, encoding="utf-8")
    return {"types": findings_by_type, "classification": cls, "rule_readiness": readiness}


def _write_findings_csv(path: Path, findings_by_type: dict[str, Any]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["document_type", "finding", "field_or_label", "detail", "count", "of", "flag"])
        for dtype, f in findings_by_type.items():
            for field_name, c in f["coverage"].items():
                w.writerow(
                    [dtype, "coverage", field_name, "populated", c["populated"], c["of"], ""]
                )
            for field_name, v in f["value_vocabulary"].items():
                w.writerow(
                    [
                        dtype,
                        "value_vocabulary",
                        field_name,
                        f"{v['distinct']} distinct",
                        v["populated"],
                        "",
                        "OPEN-ENDED" if v["open_ended_flag"] else "",
                    ]
                )
            for label, n in f["stranded_data"]["labels_by_frequency"]:
                w.writerow(
                    [
                        dtype,
                        "stranded_data",
                        label,
                        "catch-all label",
                        n,
                        f["stranded_data"]["of"],
                        "",
                    ]
                )


def _render_summary(
    root: Path,
    records: list[dict[str, Any]],
    findings_by_type: dict[str, Any],
    cls: dict[str, Any],
    readiness: list[dict[str, Any]],
) -> str:
    total_cost = round(
        sum((r.get("extraction") or {}).get("cost_estimate") or 0 for r in records), 4
    )
    lines = [
        "# Extraction bench — cross-document report",
        "",
        "> ⚠️ This measures **COVERAGE** (was a field POPULATED), **NOT accuracy** (whether the value is correct).",
        "> A high fill rate is NOT evidence the extractor reads the field correctly. **PII is placeheld**"
        " (`[NAME]`/`[SSN]`/… by the model, plus a digit/email regex backstop) — so a `borrower_name` fill"
        " rate is not evidence names are read. Nothing here was persisted to the database.",
        "",
        f"- Root: `{root}`  ·  documents: **{len(records)}**  ·  types: **{len(findings_by_type)}**",
        f"- Estimated total cost (from real tokens): **${total_cost}**",
        "",
        "## Finding 4 — classification",
        f"- confidence buckets: `{cls['confidence_buckets']}`",
        f"- types seen: `{cls['types_seen']}`",
        f"- low-confidence (<0.7): **{len(cls['low_confidence'])}** documents"
        + ("" if not cls["low_confidence"] else " — see _FINDINGS / the per-doc JSON"),
        "",
        "## Findings 1-3 — per document type",
    ]
    for dtype, f in findings_by_type.items():
        open_ended = [k for k, v in f["value_vocabulary"].items() if v["open_ended_flag"]]
        stranded = f["stranded_data"]["labels_by_frequency"][:5]
        lines += [
            f"### {dtype} ({f['documents']} docs)",
            "- **Coverage**: "
            + ", ".join(
                f"{k} {c['populated']}/{c['of']}" for k, c in list(f["coverage"].items())[:12]
            )
            + (" …" if len(f["coverage"]) > 12 else ""),
            "- ⚠️ **Open-ended fields (cannot back a deterministic rule)**: "
            + (", ".join(open_ended) if open_ended else "none flagged"),
            "- **Stranded (catch-all) top labels**: "
            + (", ".join(f"{lbl} x{n}" for lbl, n in stranded) if stranded else "none"),
            "",
        ]
    lines += ["## Finding 5 — rule readiness (COARSE: rule-family → needed doc type appeared)", ""]
    lines += ["| family | needed doc types | appeared | avg typed fill |", "|---|---|---|---|"]
    for r in readiness:
        lines.append(
            f"| {r['rule_family']} | {', '.join(r['expected_doc_types'])} | {', '.join(r['appeared_in_corpus']) or '—'} | {r['avg_typed_fill_rate'] if r['avg_typed_fill_rate'] is not None else '—'} |"
        )
    lines += [
        "",
        "*(Finding 5 is a family-level readiness signal, not the full LP-451 gate — a rule may need more than one document.)*",
    ]
    return "\n".join(lines) + "\n"
