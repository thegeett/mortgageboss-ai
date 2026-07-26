"""AS-1 rule spec + load_rule_spec interface (LP-303).

Guards the first Stage-2 rule artifact: load_rule_spec("AS-1") returns a spec with
every prompt-spine slot populated; the spec's kind + validation gate agree with
rule_kinds.csv (LP-301) and a deliberately mismatched spec raises; reference_values
carry the 50%-of-income threshold as DATA with the honest (not-yet-validated) status;
required_inputs point at REAL post-LP-302a snapshot paths; and a malformed/incomplete
spec fails loudly at load, not at evaluation time. No AI / no evaluation here.
"""

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml
from app.verification.rules.kinds import RuleKindName, kind_for
from app.verification.rules.specs import (
    _SPECS_DIR,
    RuleSpec,
    RuleSpecInconsistent,
    RuleSpecInvalid,
    RuleSpecNotFound,
    _load_spec_from,
    load_rule_spec,
)
from app.verification.snapshot.documents_section import _PII_FIELDS
from app.verification.snapshot.model import DocumentEntry, TransactionRecord

# The prompt-spine slots every spec must fill (docs/stage2-evaluator-prompts.md:55-62)
# plus the calculative-body extras discovered from AS-1.
_SPINE_SLOTS = (
    "rule_id",
    "name",
    "category",
    "kind",
    "numeric_check",
    "criteria",
    "applicability",
    "required_inputs",
    "reference_values",
    "evidence_required",
    "guideline_reference",
)


@pytest.fixture
def as1_raw() -> dict[str, Any]:
    """The real AS-1 spec as a plain dict (base for mutate-one-thing negative tests)."""
    return yaml.safe_load((_SPECS_DIR / "AS-1.yaml").read_text())


def _write_spec(tmp_path: Path, rule_id: str, data: dict[str, Any]) -> Path:
    (tmp_path / f"{rule_id}.yaml").write_text(yaml.safe_dump(data, sort_keys=False))
    return tmp_path


# --------------------------------------------------------------------------- #
# The happy path — AS-1 loads with every slot populated
# --------------------------------------------------------------------------- #


def test_load_rule_spec_as1_populates_all_spine_slots() -> None:
    spec = load_rule_spec("AS-1")
    assert isinstance(spec, RuleSpec)
    for slot in _SPINE_SLOTS:
        assert getattr(spec, slot) not in (None, "", (), [])
    # Calculative-body + finding-identity extras discovered from AS-1.
    assert spec.subject_enumeration == "per_deposit"
    assert spec.subject_key_fields == ("account", "date", "amount")
    assert spec.spec_version >= 1
    assert spec.applicability.scope and spec.applicability.trigger


def test_as1_kind_matches_rule_kinds_csv() -> None:
    spec = load_rule_spec("AS-1")
    rk = kind_for("AS-1")
    assert rk is not None
    assert spec.kind is RuleKindName.CALCULATIVE
    assert spec.kind is rk.kind  # spec ⟺ CSV
    assert spec.numeric_check is True and spec.numeric_check == rk.numeric_check


def test_reference_values_carry_threshold_as_data_with_honest_validation_status() -> None:
    spec = load_rule_spec("AS-1")
    rv = spec.reference_values
    # The threshold is DATA in the spec (not in the AI's memory / not hardcoded in code).
    assert "50%" in rv.large_deposit_threshold
    assert "income" in rv.large_deposit_threshold.lower()
    # Honest gate status — mirrors rule_kinds.csv (AS-1 is NOT yet Priya-validated).
    rk = kind_for("AS-1")
    assert rk is not None
    assert rv.priya_validated is False and rv.priya_validated == rk.priya_validated
    assert (
        rv.threshold_needs_signoff is True
        and rv.threshold_needs_signoff == rk.threshold_needs_signoff
    )


def test_threshold_lives_in_the_spec_not_hardcoded_in_verification_code() -> None:
    """The 50%-of-income threshold is DATA in the spec — no .py under app/verification
    hardcodes the threshold prose (guards against the value drifting into code)."""
    threshold = load_rule_spec("AS-1").reference_values.large_deposit_threshold
    verification_dir = Path(__file__).resolve().parents[3] / "app" / "verification"
    offenders = [
        py.relative_to(verification_dir)
        for py in verification_dir.rglob("*.py")
        if threshold in py.read_text()
    ]
    assert not offenders, f"threshold prose hardcoded in code, not spec-data: {offenders}"


# --------------------------------------------------------------------------- #
# required_inputs point at REAL post-LP-302a snapshot paths
# --------------------------------------------------------------------------- #


def test_required_inputs_reference_real_snapshot_paths() -> None:
    spec = load_rule_spec("AS-1")
    by_name = {ri.name: ri for ri in spec.required_inputs}

    # Deposits + amount/description live on the snapshot's TransactionRecord (LP-302a).
    assert "transactions" in DocumentEntry.model_fields
    assert {"amount", "date", "direction", "description"} <= set(TransactionRecord.model_fields)
    assert "transactions" in by_name["deposit_transactions"].snapshot_path
    assert "transactions" in by_name["deposit_amount"].snapshot_path

    # Account is on the PARENT entry's fields (NOT the transaction — LP-302a review 70fac7c):
    # the path must reference account_number_masked, a real routed PII field.
    assert "account_number_masked" in _PII_FIELDS
    assert "account_number_masked" in by_name["deposit_account"].snapshot_path

    # Qualifying income is a mismo per-item monthly_amount fact.
    income_path = by_name["monthly_qualifying_income"].snapshot_path
    assert income_path.startswith("mismo.facts")
    assert "income" in income_path and "monthly_amount" in income_path


def test_required_input_source_is_snapshot_not_raw_extraction() -> None:
    """RESOLVED (LP-302 Option A): every input points at the frozen snapshot, never at
    raw extraction / extracted_data."""
    spec = load_rule_spec("AS-1")
    for ri in spec.required_inputs:
        assert ri.snapshot_path.startswith(("documents.", "mismo.", "calculations."))
        assert "extracted_data" not in ri.snapshot_path
        assert "extraction" not in ri.snapshot_path.lower()


# --------------------------------------------------------------------------- #
# Consistency with rule_kinds.csv — a mismatched spec raises
# --------------------------------------------------------------------------- #


def test_kind_mismatch_with_csv_raises(tmp_path: Path, as1_raw: dict[str, Any]) -> None:
    bad = deepcopy(as1_raw)
    bad["kind"] = "judgmental"  # rule_kinds.csv says AS-1 is calculative
    _write_spec(tmp_path, "AS-1", bad)
    with pytest.raises(RuleSpecInconsistent, match="kind"):
        _load_spec_from(tmp_path, "AS-1")


def test_validation_gate_mismatch_with_csv_raises(tmp_path: Path, as1_raw: dict[str, Any]) -> None:
    bad = deepcopy(as1_raw)
    # Marking it validated when the CSV says it is NOT must fail loud (honesty gate).
    bad["reference_values"]["priya_validated"] = True
    _write_spec(tmp_path, "AS-1", bad)
    with pytest.raises(RuleSpecInconsistent, match="priya_validated"):
        _load_spec_from(tmp_path, "AS-1")


def test_numeric_check_mismatch_with_csv_raises(tmp_path: Path, as1_raw: dict[str, Any]) -> None:
    bad = deepcopy(as1_raw)
    bad["numeric_check"] = False  # calculative ⟺ numeric_check in the CSV
    _write_spec(tmp_path, "AS-1", bad)
    with pytest.raises(RuleSpecInconsistent, match="numeric_check"):
        _load_spec_from(tmp_path, "AS-1")


# --------------------------------------------------------------------------- #
# Malformed / missing / unknown — fail loud at LOAD, not at evaluation
# --------------------------------------------------------------------------- #


def test_missing_required_slot_raises_invalid(tmp_path: Path, as1_raw: dict[str, Any]) -> None:
    bad = deepcopy(as1_raw)
    del bad["criteria"]  # drop a spine slot
    _write_spec(tmp_path, "AS-1", bad)
    with pytest.raises(RuleSpecInvalid):
        _load_spec_from(tmp_path, "AS-1")


def test_empty_required_inputs_raises_invalid(tmp_path: Path, as1_raw: dict[str, Any]) -> None:
    bad = deepcopy(as1_raw)
    bad["required_inputs"] = []  # a spec that names no inputs is malformed
    _write_spec(tmp_path, "AS-1", bad)
    with pytest.raises(RuleSpecInvalid):
        _load_spec_from(tmp_path, "AS-1")


def test_unknown_key_raises_invalid(tmp_path: Path, as1_raw: dict[str, Any]) -> None:
    bad = deepcopy(as1_raw)
    bad["surprise"] = "not a slot"  # extra="forbid" — a typo'd/unknown slot fails loud
    _write_spec(tmp_path, "AS-1", bad)
    with pytest.raises(RuleSpecInvalid):
        _load_spec_from(tmp_path, "AS-1")


def test_rule_id_filename_mismatch_raises_invalid(tmp_path: Path, as1_raw: dict[str, Any]) -> None:
    # File named AS-2.yaml but rule_id inside is AS-1 → loud mismatch.
    _write_spec(tmp_path, "AS-2", as1_raw)
    with pytest.raises(RuleSpecInvalid, match="does not match filename"):
        _load_spec_from(tmp_path, "AS-2")


def test_spec_without_kinds_row_raises_invalid(tmp_path: Path, as1_raw: dict[str, Any]) -> None:
    orphan = deepcopy(as1_raw)
    orphan["rule_id"] = "ZZ-999"  # not in rule_kinds.csv → cannot be gate-checked
    _write_spec(tmp_path, "ZZ-999", orphan)
    with pytest.raises(RuleSpecInvalid, match="no row in rule_kinds"):
        _load_spec_from(tmp_path, "ZZ-999")


def test_unparseable_yaml_raises_invalid(tmp_path: Path) -> None:
    (tmp_path / "AS-1.yaml").write_text("rule_id: AS-1\n  bad: : indent")
    with pytest.raises(RuleSpecInvalid):
        _load_spec_from(tmp_path, "AS-1")


def test_missing_file_raises_not_found(tmp_path: Path) -> None:
    with pytest.raises(RuleSpecNotFound):
        _load_spec_from(tmp_path, "AS-1")
    with pytest.raises(RuleSpecNotFound):
        load_rule_spec("NOPE-404")


def test_rule_spec_is_frozen() -> None:
    spec = load_rule_spec("AS-1")
    with pytest.raises(Exception):  # noqa: B017 - pydantic frozen ValidationError
        spec.rule_id = "AS-2"


# --------------------------------------------------------------------------- #
# Deterministic-outcome load-time validation (LP-324 review)
#
# The generic evaluator's outcome list drives every verdict; a spec with a hole
# in it (no catch-all, a shadowing default, a dangling operand reference, a
# malformed reasoning template) must fail LOUD at load — not crash mid-run or
# silently drop a subject to a false green.
# --------------------------------------------------------------------------- #


def test_outcomes_without_a_default_catchall_raise_invalid(
    tmp_path: Path, as1_raw: dict[str, Any]
) -> None:
    # Drop the trailing catch-all's `default: true` → a subject that matches no branch would be
    # silently dropped (no finding = false green). Must fail at load.
    bad = deepcopy(as1_raw)
    bad["deterministic"]["outcomes"][-1]["default"] = False
    _write_spec(tmp_path, "AS-1", bad)
    with pytest.raises(RuleSpecInvalid, match="default"):
        _load_spec_from(tmp_path, "AS-1")


def test_only_the_last_outcome_may_be_default(tmp_path: Path, as1_raw: dict[str, Any]) -> None:
    # A default earlier than last shadows every branch after it (first match wins) → loud at load.
    bad = deepcopy(as1_raw)
    bad["deterministic"]["outcomes"][0]["default"] = True  # last stays default too
    _write_spec(tmp_path, "AS-1", bad)
    with pytest.raises(RuleSpecInvalid, match="only the LAST outcome"):
        _load_spec_from(tmp_path, "AS-1")


def test_when_compare_referencing_unknown_operand_raises(
    tmp_path: Path, as1_raw: dict[str, Any]
) -> None:
    # A comparison against an operand that does not exist would never resolve at eval time → loud.
    bad = deepcopy(as1_raw)
    bad["deterministic"]["outcomes"][0]["when_compare"]["left"] = "nonexistent_operand"
    _write_spec(tmp_path, "AS-1", bad)
    with pytest.raises(RuleSpecInvalid, match="when_compare references unknown operand"):
        _load_spec_from(tmp_path, "AS-1")


def test_reasoning_template_referencing_unknown_operand_raises(
    tmp_path: Path, as1_raw: dict[str, Any]
) -> None:
    # reasoning is `str.format(**operands)` at eval time — an unknown placeholder would KeyError the
    # run. Caught at load instead.
    bad = deepcopy(as1_raw)
    bad["deterministic"]["outcomes"][0]["reasoning"] = "deposit {no_such_operand} exceeds it"
    _write_spec(tmp_path, "AS-1", bad)
    with pytest.raises(RuleSpecInvalid, match="reasoning references unknown operand"):
        _load_spec_from(tmp_path, "AS-1")


def test_malformed_reasoning_template_raises(tmp_path: Path, as1_raw: dict[str, Any]) -> None:
    # A stray unclosed brace would raise ValueError from str.format at eval time → caught at load.
    bad = deepcopy(as1_raw)
    bad["deterministic"]["outcomes"][0]["reasoning"] = "deposit {observed exceeds it"
    _write_spec(tmp_path, "AS-1", bad)
    with pytest.raises(RuleSpecInvalid, match="reasoning template is malformed"):
        _load_spec_from(tmp_path, "AS-1")


def test_real_as1_spec_passes_outcome_validation() -> None:
    # The shipped AS-1 spec satisfies every new outcome rule (catch-all last, real operand refs,
    # valid reasoning templates) — the validators are not over-strict.
    spec = load_rule_spec("AS-1")
    assert spec.deterministic is not None
    assert spec.deterministic.outcomes[-1].default is True
