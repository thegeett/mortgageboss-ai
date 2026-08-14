"""The generator CLI (LP-434).

    python -m app.ai.extraction.generator.cli validate  app/schema_specs/*.json
    python -m app.ai.extraction.generator.cli generate  app/schema_specs/008-w2.json --out-dir /tmp/gen

``validate`` reports pass/refuse per spec and emits nothing. ``generate`` writes ONLY
under ``--out-dir`` — it never modifies an existing file. For a spec with a shipping
extractor it writes a diff-mode REPORT (what to add), never a module; for a passing new
type it writes the module, prompt, and test, and prints the registration snippet. A
spec that fails a stop condition is refused loudly and nothing is written.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.ai.extraction.generator.emitters import (
    emit_count_crosschecks,
    emit_diff_report,
    emit_list_specs,
    emit_module,
    emit_prompt,
    emit_registration,
    emit_test,
)
from app.ai.extraction.generator.spec import Spec, SpecError, load_spec
from app.ai.extraction.generator.validator import validate


def _cmd_validate(paths: list[str]) -> int:
    any_refused = False
    for path in paths:
        try:
            spec = load_spec(path)
        except SpecError as exc:
            print(f"ERROR  {path}: {exc}")
            any_refused = True
            continue
        refusals = validate(spec)
        mode = "diff-mode" if spec.is_diff_mode else "new-type"
        if refusals:
            any_refused = True
            print(f"REFUSE {spec.document_type} ({mode}) — {len(refusals)} reason(s):")
            for r in refusals:
                print(f"         {r}")
        else:
            print(f"PASS   {spec.document_type} ({mode})")
    return 1 if any_refused else 0


def _write(out_dir: Path, name: str, content: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / name
    target.write_text(content, encoding="utf-8")
    return target


def _generate_new_type(spec: Spec, out_dir: Path) -> int:
    refusals = validate(spec)
    if refusals:
        print(f"REFUSE {spec.document_type} — {len(refusals)} reason(s), nothing written:")
        for r in refusals:
            print(f"         {r}")
        return 2
    dt = spec.document_type
    written = [
        _write(out_dir, f"{dt}.py", emit_module(spec)),
        _write(out_dir, f"{dt}.txt", emit_prompt(spec)),
        _write(out_dir, f"test_{dt}_extraction.py", emit_test(spec)),
    ]
    print(f"GENERATED {dt} ({len(spec.typed_core)} typed-core fields):")
    for p in written:
        print(f"  wrote {p}")
    print("\n--- registration (add by hand; the generator never patches __init__.py) ---")
    print(emit_registration(spec))
    if spec.nested_lists:
        list_specs = _write(out_dir, f"{dt}.lists.py", emit_list_specs(spec))
        print(f"\n--- generic nested lists (LP-437/438) — wrote {list_specs} ---")
        print(emit_list_specs(spec))
        crosschecks = emit_count_crosschecks(spec)
        if crosschecks:
            print("--- count cross-check(s) (guide §8) — drop into the extractor's parse ---")
            print(crosschecks)
    return 0


def _generate_diff(spec: Spec, out_dir: Path) -> int:
    report = emit_diff_report(spec)
    target = _write(out_dir, f"{spec.document_type}.diff.md", report)
    print(f"DIFF-MODE {spec.document_type} — shipping extractor exists; a REPORT, not a module.")
    print(f"  wrote {target}\n")
    print(report)
    return 0


def _cmd_generate(path: str, out_dir: str) -> int:
    try:
        spec = load_spec(path)
    except SpecError as exc:
        print(f"ERROR  {path}: {exc}")
        return 2
    out = Path(out_dir)
    if spec.is_diff_mode:
        return _generate_diff(spec, out)
    return _generate_new_type(spec, out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="extractor-generator", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="report pass/refuse per spec; emit nothing")
    p_validate.add_argument("specs", nargs="+", help="one or more NNN-<slug>.json spec files")

    p_generate = sub.add_parser("generate", help="generate one spec into --out-dir")
    p_generate.add_argument("spec", help="a single NNN-<slug>.json spec file")
    p_generate.add_argument("--out-dir", required=True, help="target directory (only writes here)")

    args = parser.parse_args(argv)
    if args.command == "validate":
        return _cmd_validate(args.specs)
    return _cmd_generate(args.spec, args.out_dir)


if __name__ == "__main__":
    sys.exit(main())
