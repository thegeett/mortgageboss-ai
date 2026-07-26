"""Generate the machine-source fact-tag files from the vocabulary xlsx (LP-311).

The tag vocabulary is authored by a human (with Priya) in
``docs/snapshot-fact-tags.xlsx`` — the two sheets ``Fact-Tag Vocabulary`` and
``Rule -> Tags``. That xlsx is the *authoring* form; it is NOT read at runtime.
This script converts it, once, into the committed machine-source files the loader
reads:

* ``backend/app/verification/rules/fact_tags.csv``        — the tag vocabulary
* ``backend/app/verification/rules/rule_tags.csv``        — rule -> tag edges
* ``backend/app/verification/rules/tag_dependencies.csv`` — the tag DAG (edges)

This mirrors LP-301 exactly: the human rule-classification xlsx was converted into
the committed ``rule_kinds.csv`` that ``kinds.py`` reads. The xlsx stays upstream;
the CSVs are the version-controlled source of truth the DB projects (LP-311). The
DB is a projection of these CSVs and is never hand-edited.

Parsing is stdlib-only (zip + regex over the sheet XML) — no ``openpyxl`` runtime
dependency. The workbook stores strings inline (no ``sharedStrings.xml``); this
reader handles that. Re-run after editing the xlsx and commit the regenerated CSVs.

Note (LP-311 Phase 0): the current xlsx has NO ``depends_on`` / ``tag_role`` /
``tag_version`` columns, so ``tag_dependencies.csv`` is emitted header-only (empty
DAG) and those tag fields are left unset. Populate them by adding columns to the
xlsx and re-running — no loader change needed.

Usage::

    uv run python -m app.scripts.generate_fact_tags          # write the CSVs
    uv run python -m app.scripts.generate_fact_tags --check   # verify up-to-date
"""

from __future__ import annotations

import argparse
import csv
import html
import io
import json
import re
import sys
import zipfile
from pathlib import Path

# docs/snapshot-fact-tags.xlsx relative to the repo root (…/backend/app/scripts).
_REPO_ROOT = Path(__file__).resolve().parents[3]
_XLSX = _REPO_ROOT / "docs" / "snapshot-fact-tags.xlsx"

_RULES_DIR = Path(__file__).resolve().parents[1] / "verification" / "rules"
_FACT_TAGS_CSV = _RULES_DIR / "fact_tags.csv"
_RULE_TAGS_CSV = _RULES_DIR / "rule_tags.csv"
_TAG_DEPS_CSV = _RULES_DIR / "tag_dependencies.csv"

_VOCAB_SHEET = "Fact-Tag Vocabulary"
_RULE_TAGS_SHEET = "Rule → Tags"  # "Rule -> Tags"

_FACT_TAGS_HEADER = [
    "tag_id",
    "entity",
    "value_type",
    "allowed_values",
    "description",
    "produced_by",
    "decision",
    "used_by_rules",
    "type_raw",
]
_RULE_TAGS_HEADER = ["rule_id", "tag_id"]
_TAG_DEPS_HEADER = ["tag_id", "depends_on_tag_id"]


def _sheet_paths(z: zipfile.ZipFile) -> dict[str, str]:
    """Map each sheet's display name to its ``xl/worksheets/sheetN.xml`` path."""
    rels = z.read("xl/_rels/workbook.xml.rels").decode("utf-8", "ignore")
    rel_target: dict[str, str] = {}
    for m in re.finditer(r"<Relationship\b[^>]*>", rels):
        rid = re.search(r'Id="([^"]*)"', m.group(0))
        tgt = re.search(r'Target="([^"]*)"', m.group(0))
        if rid and tgt:
            rel_target[rid.group(1)] = tgt.group(1)
    wb = z.read("xl/workbook.xml").decode("utf-8", "ignore")
    out: dict[str, str] = {}
    for m in re.finditer(r"<sheet\b[^>]*>", wb):
        name = re.search(r'name="([^"]*)"', m.group(0))
        rid = re.search(r'r:id="([^"]*)"', m.group(0))
        if name and rid and rid.group(1) in rel_target:
            out[html.unescape(name.group(1))] = rel_target[rid.group(1)].lstrip("/")
    return out


def _read_rows(z: zipfile.ZipFile, sheet_path: str) -> list[dict[str, str]]:
    """Return each worksheet row as a ``{column-letter: text}`` dict, in order."""
    xml = z.read(sheet_path if sheet_path.startswith("xl/") else f"xl/{sheet_path}")
    text = xml.decode("utf-8", "ignore")
    rows: list[dict[str, str]] = []
    for row_m in re.finditer(r"<row[^>]*>(.*?)</row>", text, re.S):
        cells: dict[str, str] = {}
        for cm in re.finditer(r"<c\b([^>]*)>(.*?)</c>", row_m.group(1), re.S):
            ref = re.search(r'r="([A-Z]+)\d+"', cm.group(1))
            col = ref.group(1) if ref else "?"
            value = "".join(re.findall(r"<t[^>]*>(.*?)</t>", cm.group(2), re.S))
            if not value:
                vm = re.search(r"<v>(.*?)</v>", cm.group(2), re.S)
                value = vm.group(1) if vm else ""
            cells[col] = html.unescape(value).strip()
        rows.append(cells)
    return rows


def _parse_value_type(raw: str) -> tuple[str, list[str]]:
    """Split a ``Type / values`` cell into (value_type, allowed_values).

    ``enum: a | b | c`` -> ("enum", ["a", "b", "c"]); ``object: {…}`` -> ("object", []);
    everything else keeps its leading token (``number | unknown`` -> "number").
    The full raw string is preserved separately in ``type_raw`` for fidelity.
    """
    raw = raw.strip()
    if raw.lower().startswith("enum:"):
        body = raw.split(":", 1)[1]
        values = [v.strip() for v in body.split("|") if v.strip()]
        return "enum", values
    if raw.lower().startswith("object:"):
        return "object", []
    base = re.split(r"[|(]", raw, maxsplit=1)[0].strip()
    return base or raw, []


def _expand_rule_id(rule_id: str) -> list[str]:
    """Expand a range pseudo-row (``CO-1..5``) into concrete ids (CO-1…CO-5)."""
    m = re.match(r"^([A-Za-z]+)-(\d+)\.\.(\d+)$", rule_id)
    if m:
        prefix, start, end = m.group(1), int(m.group(2)), int(m.group(3))
        return [f"{prefix}-{i}" for i in range(start, end + 1)]
    return [rule_id]


def _is_tag_row(cells: dict[str, str]) -> bool:
    """A real vocabulary row has a dotted tag key (col A) and an entity (col B).

    Section headers ("TRANSACTION …") and separators ("— ADDED …") have an empty
    col B, so they are skipped.
    """
    return "." in cells.get("A", "") and bool(cells.get("B", "").strip())


def build_fact_tags(z: zipfile.ZipFile, sheet_path: str) -> list[list[str]]:
    """Vocabulary sheet -> fact_tags.csv rows (xlsx row order preserved)."""
    out: list[list[str]] = []
    for cells in _read_rows(z, sheet_path):
        if not _is_tag_row(cells):
            continue
        tag_id = cells["A"].strip()
        entity = cells.get("B", "").strip()
        type_raw = cells.get("C", "").strip()
        value_type, allowed = _parse_value_type(type_raw)
        out.append(
            [
                tag_id,
                entity,
                value_type,
                json.dumps(allowed) if allowed else "",
                cells.get("D", "").strip(),
                cells.get("E", "").strip(),
                cells.get("F", "").strip(),
                cells.get("G", "").strip(),
                type_raw,
            ]
        )
    return out


def build_rule_tags(z: zipfile.ZipFile, sheet_path: str) -> list[list[str]]:
    """Rule -> Tags sheet -> rule_tags.csv edges (ranges expanded, deduped, sorted)."""
    edges: set[tuple[str, str]] = set()
    for cells in _read_rows(z, sheet_path):
        rule_cell = cells.get("A", "").strip()
        tag_cell = cells.get("C", "").strip()
        # Skip the title row and the header row (no comma-listed tags with dots).
        if not rule_cell or "." not in tag_cell:
            continue
        for rule_id in _expand_rule_id(rule_cell):
            for tag_id in (t.strip() for t in tag_cell.split(",")):
                if tag_id:
                    edges.add((rule_id, tag_id))
    return [[r, t] for r, t in sorted(edges)]


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue()


def generate() -> dict[str, str]:
    """Return ``{path: content}`` for each machine-source file (does not write)."""
    if not _XLSX.exists():
        raise FileNotFoundError(f"vocabulary xlsx not found: {_XLSX}")
    with zipfile.ZipFile(_XLSX) as z:
        sheets = _sheet_paths(z)
        for required in (_VOCAB_SHEET, _RULE_TAGS_SHEET):
            if required not in sheets:
                raise ValueError(f"missing sheet {required!r} in {_XLSX.name}")
        fact_tags = build_fact_tags(z, sheets[_VOCAB_SHEET])
        rule_tags = build_rule_tags(z, sheets[_RULE_TAGS_SHEET])
    return {
        str(_FACT_TAGS_CSV): _write_csv(_FACT_TAGS_CSV, _FACT_TAGS_HEADER, fact_tags),
        str(_RULE_TAGS_CSV): _write_csv(_RULE_TAGS_CSV, _RULE_TAGS_HEADER, rule_tags),
        str(_TAG_DEPS_CSV): _write_csv(_TAG_DEPS_CSV, _TAG_DEPS_HEADER, []),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate fact-tag machine-source CSVs.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed CSVs match the xlsx; exit 1 if stale.",
    )
    args = parser.parse_args(argv)

    generated = generate()
    if args.check:
        stale = [p for p, content in generated.items() if _read_or_empty(p) != content]
        if stale:
            for p in stale:
                print(f"STALE: {p} (re-run generate_fact_tags)", file=sys.stderr)
            return 1
        print("fact-tag CSVs are up to date.")
        return 0

    for path_str, content in generated.items():
        Path(path_str).write_text(content, encoding="utf-8")
        line_count = content.count("\n") - 1  # minus header
        print(f"wrote {Path(path_str).name}: {line_count} rows")
    return 0


def _read_or_empty(path_str: str) -> str:
    p = Path(path_str)
    return p.read_text(encoding="utf-8") if p.exists() else ""


if __name__ == "__main__":
    raise SystemExit(main())
