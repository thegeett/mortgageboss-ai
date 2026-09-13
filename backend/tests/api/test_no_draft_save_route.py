"""A draft body is written by the template, by a save, or by the send — and by nothing else.

LP-849 wrote this file to forbid a save outright. THE BAN WAS CORRECT FOR ITS PREMISE and the
premise is gone, so the file now guards the condition the ban was really about.

WHAT IT WAS PROTECTING. Three mechanisms rewrite a stored draft body without being asked to:
`refresh_if_stale` re-renders a stale one on READ, `_regenerate` re-renders on every add and
remove, and `attach_upload_link` re-renders to put a link in it. All three were safe for exactly
one reason — before a send the stored body was always template-generated, so there was no human
edit to destroy. LP-849's own words: "A rich editor whose output survives until the next page load
is worse than no editor at all."

WHAT LP-853 CHANGED. `Communication.body_format` records that a person wrote this body, and all
three mechanisms now REFUSE such a row. `refresh_if_stale`'s docstring named this exact condition —
the heal "becomes destructive and must move behind an explicit action" — and LP-853 is that action.

So the ban becomes two tests instead of one:

* the SCAN below still fails the build on any route that writes a draft body other than the two
  that have earned it, because the next convenience route is still the hazard;
* and `tests/services/test_authored_body_lp853.py` asserts the three refusals BEHAVIOURALLY, with
  positive controls — a scan that permits a route proves nothing about whether the thing that made
  it safe still works.

THE SCOPE IS DERIVED FROM THE IMPORT GRAPH, NOT TYPED OUT. Three times now this guard was scoped by
a NAME and three times a door was left open: first by allow-listing a route name, then by matching
"draft" in the decorator path (defeated by an `APIRouter(prefix="/draft")`), then by matching the
router prefix too (defeated by a `PATCH /{identifier}` in `communications.py`). The third fix was a
literal set of two filenames, which a save route in a new module walks straight past.

What actually identifies the hazard is reaching code that can WRITE a Communication body. That is
computable: find the modules in `app/` that assign to a body on a Communication, then take every
api module that imports one of them, directly or transitively. A new module is in scope the moment
it can do the thing, which is the property rather than a spelling of it.
"""

from __future__ import annotations

import re
from pathlib import Path

_APP = Path(__file__).resolve().parents[2] / "app"

#: The ROUTES that legitimately write a draft body. Matched EXACTLY, against the decorator path.
#:
#: THE ROUTE, NOT THE MODEL, and that distinction is load-bearing. LP-849's first version
#: allow-listed `SendDraftRequest`, and the mutant that proves this test works — a `PATCH /draft/{id}`
#: convenience route — passed, because it reused that model. Of course it did: the obvious way to
#: write a save is to take the same payload the send takes. The permission belongs to the endpoint
#: that earned it, and `SaveDraftBodyRequest` is a second payload with `body` on it for anybody who
#: forgets.
#:
#: EXACT STRINGS, NOT A PATTERN. `/send/?$` would also permit `/anything/send`, and a pattern that
#: grows to cover a second route grows to cover routes nobody has written yet.
#: PAIRED WITH THE MODULE, so a permission cannot be borrowed. A new module gets none of these: an
#: entry names one route in one file, and narrowing a permission by name is safe in a way that
#: SCOPING A SCAN by name is not — the failure mode of a too-narrow permission is a build that
#: fails until somebody looks.
_ALLOWED_ROUTES = frozenset(
    {
        # LP-811a — the processor's edit becomes the record of what went out. After this the row is
        # SENT, and every rewrite mechanism returns early on anything that is not a DRAFT.
        ("communications.py", "/draft/{draft_id}/send"),
        # LP-853 — the save. Safe only because `body_format` makes the row refuse the three
        # rewrites; see the module docstring and the behavioural tests it names.
        ("communications.py", "/draft/{draft_id}/body"),
        # LP-818 — compose and reply CREATE a message from words a processor typed. They are not
        # this guard's hazard, which is overwriting a body somebody else generated: there is no
        # prior body, no template, and nothing for `_regenerate` to have produced. Listed rather
        # than pattern-matched because "creates" and "overwrites" is a distinction no regex can see.
        ("communications.py", ""),
        ("communications.py", "/{communication_id}/reply"),
    }
)


def _request_models_with_body() -> set[str]:
    """Pydantic models in `app/` that carry a `body` field a client can set."""
    found: set[str] = set()
    for path in sorted(_APP.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r"class (\w+)\(BaseModel\):((?:\n(?:[ \t]+.*)?)+)", source):
            name, block = match.group(1), match.group(2)
            if re.search(r"^\s+body\s*:", block, re.M):
                found.add(name)
    return found


def _routes(path: Path) -> list[tuple[str, str, str]]:
    """Every mutating route in `path`, as (verb, decorator path, the handler's FULL signature).

    THE WHOLE SIGNATURE, NOT THE FIRST PARAMETER — the fourth escape this guard has had, and the
    one LP-853's own save route walked through. Every previous version matched
    ``def NAME(FIRST: TYPE)`` and read the model off parameter ONE, so a handler
    written `(draft_id: UUID, payload: SaveDraftBodyRequest, ...)` — which is how FastAPI handlers
    with a path parameter are always written — reported its model as `UUID` and passed. `reply`
    has been invisible to this file since LP-818 for the same reason.

    ANY ROUTER VARIABLE, not one called `router`. `communications.py` declares `message_router`
    beside `router`, and half its routes hang off it.
    """
    source = path.read_text(encoding="utf-8")
    found: list[tuple[str, str, str]] = []
    for match in re.finditer(
        r"@\w*(?:router)\.(post|put|patch)\(\s*\n?\s*[\"']([^\"']*)[\"']", source
    ):
        verb, route = match.group(1), match.group(2)
        opened = source.find("(", source.find("def ", match.end()))
        if opened == -1:
            continue
        depth, index = 0, opened
        while index < len(source):
            if source[index] == "(":
                depth += 1
            elif source[index] == ")":
                depth -= 1
                if depth == 0:
                    break
            index += 1
        found.append((verb, route, source[opened : index + 1]))
    return found


def _annotations(signature: str) -> set[str]:
    """Every type name mentioned in a handler signature."""
    return set(re.findall(r"[:\[]\s*(\w+)", signature))


def _module_name(path: Path) -> str:
    """`app/services/email_draft.py` -> `app.services.email_draft`."""
    return ".".join(("app", *path.relative_to(_APP).with_suffix("").parts))


def _body_writers() -> set[str]:
    """Modules that can assign a body onto a Communication.

    The two halves together, because either alone is far too wide: `\\.body\\s*=` matches an HTTP
    response body and a parsed email part, and naming `Communication` is what almost every module in
    `app/services` does.
    """
    found: set[str] = set()
    for path in sorted(_APP.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "Communication" not in source:
            continue
        if re.search(r"^\s*\w+\.body\s*=\s*[^=]", source, re.M):
            found.add(_module_name(path))
    return found


def _imports(path: Path) -> set[str]:
    """The `app.*` modules this file imports, however the import is written."""
    source = path.read_text(encoding="utf-8")
    return {match.group(1) for match in re.finditer(r"(?:from|import)\s+(app(?:\.\w+)+)", source)}


def _reaches_a_body_writer() -> set[Path]:
    """Api modules that can reach a body writer, directly or through anything they import."""
    writers = _body_writers()
    graph = {_module_name(p): _imports(p) for p in sorted(_APP.rglob("*.py"))}

    def reaches(module: str, seen: set[str]) -> bool:
        for target in graph.get(module, set()):
            if target in seen:
                continue
            seen.add(target)
            if target in writers or reaches(target, seen):
                return True
        return False

    return {
        path
        for path in sorted((_APP / "api").glob("*.py"))
        if _module_name(path) in writers or reaches(_module_name(path), set())
    }


def test_the_scan_can_see_the_modules_that_own_draft_bodies() -> None:
    """THE POSITIVE CONTROL FOR THE DERIVATION, and it is the point of the rewrite.

    Everything below is satisfied by a scan whose scope is empty. Three versions of this guard were
    defeated by a scope that silently did not include the file the route was in, and every one of
    them printed green — a scan that does not look somewhere looks exactly like a clean scan.
    """
    writers = _body_writers()
    assert "app.services.email_draft" in writers, writers
    assert "app.services.email_send" in writers, writers

    in_scope = {path.name for path in _reaches_a_body_writer()}
    # The two modules the previous version named by hand — now reached, not typed.
    assert "communications.py" in in_scope, in_scope
    assert "party_requests.py" in in_scope, in_scope


def test_no_route_writes_a_draft_body_except_the_save_and_the_send() -> None:
    """Any route whose module can reach a body writer, and whose payload carries `body`."""
    carriers = _request_models_with_body()
    assert carriers, "the scan found no request model with a body field; it proved nothing"

    offenders: list[str] = []
    seen_routes: set[tuple[str, str]] = set()
    for path in sorted(_reaches_a_body_writer()):
        for verb, route, signature in _routes(path):
            seen_routes.add((path.name, route))
            taken = sorted(carriers & _annotations(signature))
            if taken and (path.name, route) not in _ALLOWED_ROUTES:
                offenders.append(f"{path.name}: {verb.upper()} {route} takes {', '.join(taken)}")

    assert not offenders, (
        "these routes write draft body text without being the save or the send: "
        + ", ".join(offenders)
        + ". `refresh_if_stale`, `_regenerate` and `attach_upload_link` all rewrite a stored draft "
        "body on their own; LP-853 makes them refuse an edited one, and a route that writes a body "
        "without setting `body_format` puts a human edit back in reach of all three."
    )
    # AND THE SCAN ACTUALLY REACHED THE ROUTES UNDER TEST. A scan that matched nothing, or matched
    # only unrelated routes, is positive and blind at the same time.
    for allowed in _ALLOWED_ROUTES:
        assert allowed in seen_routes, (
            f"the scan never saw {allowed!r}; its matcher or its scope has drifted"
        )


def test_the_allowed_routes_all_still_exist() -> None:
    """An allow-list entry naming a route that is gone is stale, and stale means it is hiding one.

    Checked against the running app rather than the source, so a route that was renamed cannot
    leave a permission behind for a path that no longer resolves.
    """
    from app.main import app

    paths = {getattr(route, "path", "") for route in app.routes}
    for allowed in _ALLOWED_ROUTES:
        assert any(path.endswith(allowed) for path in paths), (
            f"{allowed!r} is allow-listed and no route has that path"
        )


def test_the_send_and_the_save_are_still_the_routes_that_take_the_words() -> None:
    """THE OTHER POSITIVE HALF. Everything above is satisfied by a codebase with no draft routes at
    all, or by payloads that stopped carrying a body — which would mean the processor's words never
    reach the record."""
    carriers = _request_models_with_body()
    assert "SendDraftRequest" in carriers
    assert "SaveDraftBodyRequest" in carriers
