"""A draft body is written by the template or by the send — never by a save (LP-849).

WHY THIS IS A TEST AND NOT A NOTE. Two mechanisms rewrite a stored draft body without being asked
to: `refresh_if_stale` re-renders a stale one on READ, and `_regenerate` re-renders on every
add/remove. Both are safe for exactly one reason — before a send the stored body is always
template-generated, so there is no human edit to destroy.

LP-849 gives a processor a rich editor, which is plausibly the endpoint that breaks that. The moment
an edited body can be saved without sending, all three become destructive at once: the next GET
rewrites their work, and so does the next document they request. A rich editor whose output survives
until the next page load is worse than no editor at all.

So LP-849 keeps the edit in memory until "Mark as sent", and this is what stops that decision being
quietly reversed by somebody adding the obvious convenience route. The heal's own docstring says it
must move behind an explicit action first; this fails the build rather than trusting that anybody
reads it.

THE PROPERTY IS "ACCEPTS BODY TEXT", NOT A ROUTE NAME. The first version allow-listed `send` by the
last path segment and flagged `POST /draft` — `party_requests.draft_for_party`, which takes only a
`party` and renders from the template, exactly as `_regenerate` does. Keying on the name would have
meant maintaining a list of blessed names, and a list like that turns every new legitimate route
into a false failure and every unfamiliar one into a judgement call. What actually distinguishes a
save from a build is whether the CLIENT supplies the words.
"""

from __future__ import annotations

import re
from pathlib import Path

_APP = Path(__file__).resolve().parents[2] / "app"

#: The one ROUTE that legitimately takes body text for a draft. `send_draft` stores the processor's
#: edit AT the moment of sending — the single point at which their words become the record of what
#: went out, and after which nothing regenerates them, because the heal returns early on anything
#: that is not a DRAFT.
#:
#: THE ROUTE, NOT THE MODEL. The first version allow-listed `SendDraftRequest`, and the mutant that
#: proves this test works — a `PATCH /draft/{id}` convenience route — passed, because it reused that
#: model. Of course it did: the obvious way to write a save is to take the same payload the send
#: takes. The permission has to belong to the endpoint that has earned it.
_ALLOWED_ROUTE = re.compile(r"/send/?$")


def _request_models_with_body() -> set[str]:
    """Pydantic models in `app/` that carry a `body` field a client can set."""
    found: set[str] = set()
    for path in sorted((_APP).rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r"class (\w+)\(BaseModel\):((?:\n(?:[ \t]+.*)?)+)", source):
            name, block = match.group(1), match.group(2)
            if re.search(r"^\s+body\s*:", block, re.M):
                found.add(name)
    return found


def test_no_route_takes_draft_body_text_except_the_send() -> None:
    """Any draft route whose request model carries `body` is a save, whatever it is called."""
    carriers = _request_models_with_body()
    assert carriers, "the scan found no request model with a body field; it proved nothing"

    offenders: list[str] = []
    scanned = 0
    for path in sorted((_APP / "api").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(
            r"@router\.(post|put|patch)\(\s*\n?\s*[\"']([^\"']*)[\"'][\s\S]{0,400}?"
            r"\n(?:async )?def \w+\(\s*\n?\s*(\w+)\s*:\s*(\w+)",
            source,
        ):
            verb, route, _arg, model = match.groups()
            if "draft" not in route:
                continue
            scanned += 1
            if model in carriers and not _ALLOWED_ROUTE.search(route):
                offenders.append(f"{path.name}: {verb.upper()} {route} takes {model}")

    assert not offenders, (
        "these routes accept draft body text without sending: "
        + ", ".join(offenders)
        + ". `refresh_if_stale` and `_regenerate` both rewrite a stored draft body on their own, so "
        "a saved edit is destroyed on the next read or the next document requested. Move the heal "
        "behind an explicit action before adding one."
    )
    assert scanned > 0, "the scan matched no draft routes; it proved nothing"


def test_the_send_is_still_the_route_that_takes_the_words() -> None:
    """THE POSITIVE HALF. Everything above is satisfied by a codebase with no draft routes at all,
    or by a `SendDraftRequest` that stopped carrying a body — which would mean the processor's edit
    never reaches the record of what went out."""
    assert "SendDraftRequest" in _request_models_with_body()
