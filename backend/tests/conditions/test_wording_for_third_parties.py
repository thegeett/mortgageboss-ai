"""LP-945: the expert's two wording questions, answered by the product owner.

1. In anything a borrower or third party reads, "VOE" is spelled out ("Verbal verification of
   employment", "Written verification of employment"). It may stay in her own UI and tasks (IE-03 and
   IE-06 are her tasks, their playbooks hers).
2. Business existence has its own type, IE-08: the ask is "Business existence verification (CPA
   letter, business licence, or regulator listing)", within 120 calendar days before the note date per
   Fannie Mae B3-3.1-04, and a lender setting makes it "Lender is doing it".
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.conditions.library.loader import load_library
from app.documents.catalog import CATALOG
from app.documents.display_names import display_name
from app.models.condition_vocabulary import PlanOption
from app.services.condition_plan import LenderConditionSettings, _step_and_reason

_ASKS = (PlanOption.ASK_BORROWER, PlanOption.ASK_THIRD_PARTY)


def _outward_text() -> list[tuple[str, str]]:
    """Every library string a borrower or third party reads: an ASK item's own wording, and every type's
    name, short and why (emails, and the underwriter question)."""
    out: list[tuple[str, str]] = []
    for kind in load_library().types.values():
        asked = [item for item in kind.items if item.option in _ASKS]
        for item in asked:
            for field in ("name", "name_with_amount", "acceptable", "label", "email", "why"):
                value = getattr(item, field, None)
                if value:
                    out.append((f"{kind.id}.{item.key}.{field}", value))
        # EVERY type's name, short and why, not only those with an asked item (LP-945 review): the
        # underwriter question renders a type's short-or-name for any condition, and an underwriter
        # at the lender is outside her company.
        for field in ("name", "short", "why"):
            value = getattr(kind, field, None)
            if value:
                out.append((f"{kind.id}.{field}", value))
    return out


def test_no_outward_text_says_voe() -> None:
    texts = _outward_text()
    assert len(texts) > 50  # the positive control: the sweep sees the library's asks
    assert [where for where, text in texts if "VOE" in text] == []


def test_no_display_name_says_voe() -> None:
    """Display names go into re-asks and package notes, which third parties read."""
    assert [t for t in CATALOG if "VOE" in display_name(t)] == []
    assert display_name("verbal_voe") == "Verbal verification of employment"
    assert display_name("voe") == "Written verification of employment"


def test_voe_may_stay_in_her_own_tasks() -> None:
    """The rule is about who READS it: her own task still says VOE, and that is allowed."""
    library = load_library()
    (call,) = library.types["IE-03"].items
    assert call.option is PlanOption.I_WILL_DO_IT and "VOE" in call.name


def test_business_existence_has_its_own_type() -> None:
    kind = load_library().types["IE-08"]
    (item,) = kind.items
    assert item.name == (
        "Business existence verification (CPA letter, business licence, or regulator listing)"
    )
    assert item.option is PlanOption.ASK_BORROWER
    assert (kind.rule.citation, kind.rule.note) == (
        "Fannie Mae B3-3.1-04",
        "Within 120 calendar days before the note date.",
    )


def test_the_lender_setting_makes_it_lender_is_doing_it() -> None:
    kind = load_library().types["IE-08"]
    condition: Any = SimpleNamespace(bucket_kind=None, info_only=False)
    loan_file: Any = SimpleNamespace(lender_processing=False)

    def step(setting: bool) -> PlanOption | None:
        settings = LenderConditionSettings(lender_verifies_business_existence=setting)
        return _step_and_reason(condition, kind, {}, settings, loan_file)[0]

    assert step(False) is None  # its item asks the borrower
    assert step(True) is PlanOption.LENDER_DOING_IT
