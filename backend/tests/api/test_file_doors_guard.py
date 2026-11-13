"""No route can be added unclassified (LP-MB-Admin-06).

Every route in `app/api/*.py` is either a door in `file_doors.DOORS` (sent by `test_file_doors.py`)
or in `file_doors.EXEMPT` with a reason; every route the survey names is one of the two; and the
survey's per-router counts for group A are the doors this file holds for that router. Routes are
read with `ast`, the way the survey was taken (`LP-MB-Admin-05-survey.md`, "Method").
"""

import ast
import re
from collections import Counter
from pathlib import Path

from tests.api.file_doors import DOORS, EXEMPT

_BACKEND = Path(__file__).resolve().parents[2]
_API = _BACKEND / "app" / "api"
_SURVEY = _BACKEND.parent / "docs" / "tickets" / "LP-MB-Admin-05-survey.md"
_VERBS = {"get", "post", "put", "patch", "delete"}
#: `main.py` mounts the dev router under `/dev` on top of its own (empty) prefix.
_MOUNT = {"dev.py": "/api/v1/dev"}


def _routes() -> dict[tuple[str, str], str]:
    """(METHOD, full path) → the router file, for every decorated route in `app/api/*.py`."""
    found: dict[tuple[str, str], str] = {}
    for source in sorted(_API.glob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        prefixes: dict[str, str] = {}
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "APIRouter"
                and isinstance(node.targets[0], ast.Name)
            ):
                prefix = next(
                    (ast.literal_eval(k.value) for k in node.value.keywords if k.arg == "prefix"),
                    "",
                )
                prefixes[node.targets[0].id] = prefix
        for node in tree.body:
            if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
                continue
            for decorator in node.decorator_list:
                if (
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr in _VERBS
                    and isinstance(decorator.func.value, ast.Name)
                    and decorator.func.value.id in prefixes
                ):
                    path = ast.literal_eval(decorator.args[0]) if decorator.args else ""
                    mount = _MOUNT.get(source.name, "/api/v1")
                    key = (
                        decorator.func.attr.upper(),
                        mount + prefixes[decorator.func.value.id] + path,
                    )
                    found[key] = source.name
    return found


_ROW = re.compile(r"^\| `?(GET|POST|PUT|PATCH|DELETE) (/api/v1\S*?)(?:\?\S*)?`? \|", re.M)
_ADDENDUM_ROW = re.compile(r"^\| [ABC] \| `(GET|POST|PUT|PATCH|DELETE) (/api/v1\S*?)` \|", re.M)
_GROUP_A_ROW = re.compile(r"^\| api/(\w+\.py) \| (\d+) \|", re.M)


def _survey_routes() -> set[tuple[str, str]]:
    text = _SURVEY.read_text(encoding="utf-8")
    return {(m, p) for m, p in _ROW.findall(text)} | {
        (m, p) for m, p in _ADDENDUM_ROW.findall(text)
    }


def test_every_route_in_the_app_is_a_door_or_exempt() -> None:
    routes = _routes()
    classified = {door.key for door in DOORS} | set(EXEMPT)
    missing = sorted(set(routes) - classified)
    assert not missing, f"routes not in file_doors.DOORS or EXEMPT: {missing}"


def test_nothing_in_the_list_is_stale() -> None:
    routes = _routes()
    stale = sorted(({door.key for door in DOORS} | set(EXEMPT)) - set(routes))
    assert not stale, f"in file_doors but not a route in app/api: {stale}"


def test_a_route_is_a_door_or_exempt_not_both() -> None:
    keys = [door.key for door in DOORS]
    assert len(keys) == len(set(keys)), [k for k, n in Counter(keys).items() if n > 1]
    assert not set(keys) & set(EXEMPT)


def test_every_route_the_survey_names_is_classified() -> None:
    named = _survey_routes()
    # A positive control: the survey's tables parse (B, C and the addendum list 137 + 6 rows).
    assert len(named) >= 140, len(named)
    classified = {door.key for door in DOORS} | set(EXEMPT)
    missing = sorted(named - classified)
    assert not missing, f"named in the survey but not in file_doors: {missing}"


def test_group_a_holds_the_survey_count_for_each_router() -> None:
    """Group A is listed in the survey by router file and count; the doors must match it."""
    text = _SURVEY.read_text(encoding="utf-8")
    expected = {name: int(count) for name, count in _GROUP_A_ROW.findall(text)}
    expected["loan_teams.py"] = 4  # the Part 1 addendum
    routes = _routes()
    held = Counter(routes[door.key] for door in DOORS if door.group == "A")
    assert dict(held) == expected
