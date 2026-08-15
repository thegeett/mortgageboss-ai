"""LP-509-E1 — every MISMO fact key a consumer READS must be one the emitter can PRODUCE.

THE DEFECT THIS EXISTS TO CATCH (LP-509-A2, live in staging and on every loan file in the system):
``derived.py`` required the fact keys ``borrower.1.name`` and ``property.address``. The snapshot's
MISMO section emits ``borrower.{n}.first_name`` / ``.middle_name`` / ``.last_name`` and
``property.address_line`` / ``.address_line_2``. Neither required key was emitted by anything, so
ID-6's completeness recipe counted both as missing on every file and the rule fired a RED
"the application is incomplete" — naming two fields that were, in fact, present under their real
names. It had been that way since the recipe was written.

NOTHING CAUGHT IT, and the reason is worth stating: the unit tests around the recipe built their
"complete" fixture from a LOCAL COPY of the same two wrong names, so the recipe and its test agreed
with each other and disagreed with reality. A test that restates the contract cannot detect that the
contract is wrong. This one does not restate it — it reads BOTH SIDES from source.

The fact keys are a string-keyed interface between two modules with no shared type. That is exactly
the shape a compiler would catch elsewhere and cannot catch here, so it is checked here instead.

STATIC, not runtime: it asks whether the emitter could EVER emit the key, so a fixture that happens
not to populate an optional field cannot make it fail, and a field absent from a particular loan
file is not confused with a field name that does not exist.

WHAT IT DOES NOT COVER, stated so the green is not read as more than it is: a key whose final
segment is built at runtime (``subjects._borrower_read_field`` composes
``f"borrower.{index}.{field}"`` from a caller-supplied field name) is skipped — there is no static
key to check. Those field names come from the recipe declarations, so a guard for them belongs with
the declarations, not here.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_APP = Path(__file__).resolve().parents[3] / "app"
_EMITTER = _APP / "verification" / "snapshot" / "mismo_section.py"

#: Modules that read MISMO fact keys by name. Sourced from `grep -rl "mismo.facts\|_mismo_str" app/`;
#: `model.py` defines the section rather than reading it, and `app/scripts/*` are smoke scripts.
_CONSUMERS = (
    _APP / "verification" / "tag_materialization" / "derived.py",
    _APP / "verification" / "tag_materialization" / "subjects.py",
    _APP / "verification" / "rule_engine" / "enumerators.py",
)

#: Rendered in place of an f-string's interpolated part, on both sides.
_HOLE = "\x00"


def _render(node: ast.expr, env: dict[str, str]) -> str | None:
    """The literal key, with ``_HOLE`` for each interpolated part; ``None`` if not a static string."""
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                # A name we already resolved (`base` -> "borrower.<hole>") expands; anything else
                # (a loop index, a computed slug) becomes a hole.
                inner = value.value
                parts.append(
                    env[inner.id] if isinstance(inner, ast.Name) and inner.id in env else _HOLE
                )
            else:
                return None
        return "".join(parts)
    return None


def _emitted_templates() -> set[str]:
    """Every key template the MISMO section's ``put(...)`` calls can produce."""
    tree = ast.parse(_EMITTER.read_text())

    # Prefix locals (`base = f"borrower.{n}"`, `ikey = f"{base}.income.{m}"`) resolved to a fixed
    # point, because they chain: `ikey` cannot render until `base` has.
    assigns: dict[str, ast.expr] = {
        node.targets[0].id: node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    }
    env: dict[str, str] = {}
    for _ in range(len(assigns) + 1):
        before = dict(env)
        for name, value in assigns.items():
            rendered = _render(value, env)
            if rendered is not None:
                env[name] = rendered
        if env == before:
            break

    return {
        rendered
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "put"
        and node.args
        and (rendered := _render(node.args[0], env)) is not None
    }


def _is_mismo_facts(node: ast.expr) -> bool:
    """``<anything>.mismo.facts``."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "facts"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "mismo"
    )


def _consumed_keys(path: Path) -> set[tuple[str, int]]:
    """``{(key_template, lineno)}`` read from the MISMO facts by name in ``path``."""
    tree = ast.parse(path.read_text())
    found: set[tuple[str, int]] = set()

    def take(node: ast.expr, lineno: int) -> None:
        rendered = _render(node, {})
        if rendered is not None:
            found.add((rendered, lineno))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            # _mismo_str(snapshot, "property.occupancy")
            if isinstance(func, ast.Name) and func.id == "_mismo_str" and len(node.args) >= 2:
                take(node.args[1], node.lineno)
            # snapshot.mismo.facts.get("loan.amount")
            elif (
                isinstance(func, ast.Attribute)
                and func.attr == "get"
                and _is_mismo_facts(func.value)
                and node.args
            ):
                take(node.args[0], node.lineno)
        # snapshot.mismo.facts["loan.amount"]
        elif isinstance(node, ast.Subscript) and _is_mismo_facts(node.value):
            take(node.slice, node.lineno)
        # the declared required-field sets, whose members are fact keys by construction
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id.endswith("_FIELDS")
            and isinstance(node.value, ast.Tuple | ast.List)
        ):
            for element in node.value.elts:
                # A fact key is always namespaced. Bare words in a `*_FIELDS` tuple are SUFFIXES
                # joined onto a prefix elsewhere (enumerators' `_MISMO_LIABILITY_FIELDS` is
                # ("type", "monthly_payment", …), read off an already-grouped row dict), not keys.
                if isinstance(element, ast.Constant) and "." in str(element.value):
                    take(element, node.lineno)

    # A key whose LAST segment is entirely interpolated (`f"borrower.{index}.{field}"`, where
    # `field` is a runtime parameter) names nothing statically — every emitted borrower key would
    # match it. Dropped rather than checked, so the assertion stays honest about its coverage.
    return {(key, line) for key, line in found if key.split(".")[-1] != _HOLE}


def _matcher(template: str) -> re.Pattern[str]:
    """A template to a regex: each hole is one-or-more characters."""
    return re.compile(".+".join(re.escape(part) for part in template.split(_HOLE)) + r"\Z")


def test_every_consumed_mismo_fact_key_is_emitted() -> None:
    emitted = _emitted_templates()
    # A sanity floor: if the emitter parse ever silently yields nothing, every consumed key would
    # "fail" for the wrong reason — or, with the assertion inverted, everything would pass.
    assert len(emitted) > 30, f"parsed only {len(emitted)} put() templates from {_EMITTER.name}"
    assert "property.address_line" in emitted
    assert f"borrower.{_HOLE}.first_name" in emitted

    matchers = [_matcher(t) for t in emitted]
    orphans: list[str] = []
    for consumer in _CONSUMERS:
        for key, lineno in sorted(_consumed_keys(consumer)):
            probe = key.replace(_HOLE, "1")  # a hole stands for an index; any value would do
            if not any(m.match(probe) for m in matchers):
                orphans.append(f"{consumer.name}:{lineno} reads {key.replace(_HOLE, '{}')!r}")

    assert not orphans, (
        "MISMO fact keys read by a consumer that "
        f"{_EMITTER.name} never emits:\n  " + "\n  ".join(orphans)
    )


def test_the_guard_would_have_caught_lp509_a2() -> None:
    """The two names that were live in `_APP_REQUIRED_FIELDS` must not match any emitted template.

    Without this, a regression in the matcher (a hole becoming `.*`, an accidental `search` for a
    `match`) would silently turn the test above into one that always passes.
    """
    matchers = [_matcher(t) for t in _emitted_templates()]
    for dead_key in ("borrower.1.name", "property.address"):
        assert not any(m.match(dead_key) for m in matchers), (
            f"{dead_key!r} matched an emitted template — the matcher is too permissive and "
            "test_every_consumed_mismo_fact_key_is_emitted can no longer fail"
        )
