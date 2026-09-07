"""The outbound template library (LP-817) — the five templates, versioned and rendered.

Spec 4.1 names five: initial documentation request, reminder / follow-up, status update, condition
response request, custom. None existed, and the gap had a sharp edge: **LP-810's compliance scanner
falls back to "the plain template", and nothing defined one.**

WHAT "THE PLAIN TEMPLATE" IS, stated here because no other ticket does. It is not a sixth file. It
is this module: a deterministic render of the template the draft names, from structured data, with
no model involved. LP-810's AI drafting ships behind a flag that is OFF by default, so until that
flag flips this is not the fallback path — it is the ONLY path, and every borrower-facing email M1
sends comes out of these five files.

**Templates are content, not code**, and live as files under ``templates/`` for the same reason
prompts do (LP-38): they are iterated on by a person who should not have to touch Python, and they
diff cleanly in review. The Python here is the registry, the version pin, and the renderer.

**Versioning is enforced, not documented.** ``phase4.md`` §6 requires the audit record to capture
*template + version*, and that record is evidence. A version pin that only appears in a comment
would let someone edit a template's wording, leave the version at ``v1``, and silently make every
historical audit row claim that an email said something it did not. Each version therefore carries a
SHA-256 of the file as shipped, and a test refuses a file whose content no longer matches its pin.
Changing the words means adding a version.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from pathlib import Path
from string import Template

from app.documents.catalog import ResponsibleParty, get_guidance
from app.models.upload_link import DEFAULT_TTL_HOURS
from app.verification.rule_engine.reasons import document_label

_TEMPLATES_DIR = (Path(__file__).parent / "templates").resolve()

#: The security line every template carries, verbatim. The protocol's fixed decisions require
#: borrowers to be told email is not secure; a test asserts all five contain this exact string.
#:
#: It CAUTIONS and offers a route out; it does not tell the borrower to use an upload link, because
#: no upload link exists until LP-815. Telling someone not to email documents while giving them an
#: email address to send them to would be the incoherence ADR-398 warns about, and pointing at a
#: link that resolves to nothing would be worse than saying nothing.
#: The caution itself — a fixed decision in the execution protocol: borrowers are told email is not
#: secure. Every template carries it, asking or not.
SECURITY_CAUTION = "Email is not a fully secure channel."

#: LP-824 — THE CAUTION PLUS A ROUTE THAT EXISTS.
#:
#: v1 read "...reply and tell us and we will arrange another route", and a processor reported the
#: result: the same email says "reply to this message with them attached, or send them to
#: $inbox_address" four lines earlier. A borrower read *send it by email, but email is not safe, but
#: tell us if you would rather not and we will think of something.* The instruction and the caveat
#: cancelled out, and the offer named nothing anybody could act on.
#:
#: The alternative it was gesturing at ALREADY EXISTS. LP-815 built the secure upload link and the
#: panel that mints one. So the caveat can name it, and the message stops arguing with itself: it
#: gives an instruction and a real choice.
#:
#: NAMED, NOT LINKED, and that is deliberate. The plaintext token exists only in `MintedLink` at the
#: moment of minting — the row holds a hash — so no URL can be rebuilt for an email composed later,
#: and a URL that resolved to nothing would be worse in a borrower's inbox than no URL at all. That
#: was the reasoning of `test_the_security_notice_does_not_promise_a_link_that_does_not_exist`, and
#: it still holds for the URL. It no longer holds for the WORD: a processor can mint a link from the
#: communication page today, so "reply and ask" is an instruction we can honour.
SECURITY_NOTICE = (
    f"{SECURITY_CAUTION} If you would rather not send documents this way, reply and ask — "
    "we will send you a secure upload link instead."
)


#: How long a minted link lasts, in days, for the sentence a borrower reads. Derived from the one
#: constant rather than typed again — LP-827 pinned the panel's copy to it for the same reason, and a
#: duplicated number is wrong the first time somebody changes the original.
_LINK_DAYS = DEFAULT_TTL_HOURS // 24


def secure_upload_block(url: str | None) -> str:
    """The security caution, and the route out of email — a live link where there is one (LP-834).

    ONE SLOT, TWO SENTENCES, AND NEITHER IS OPTIONAL. `SECURITY_CAUTION` is a fixed decision in the
    execution protocol: borrowers are told email is not secure. What follows it is what the file can
    actually offer — a link the processor has minted, or LP-824's offer to send one on request, which
    is a promise a person can keep.

    THE URL IS PASSED IN, NEVER READ BACK. `MintedLink`'s token "exists HERE AND NOWHERE ELSE — the
    row holds a hash", so there is no rebuilding this for an email composed later. That is why the
    draft has to remember its own link rather than the renderer looking one up.
    """
    if url is None:
        return SECURITY_NOTICE
    return (
        f"{SECURITY_CAUTION} If you would rather not send documents by email, you can upload them "
        f"securely here instead:\n\n  {url}\n\n"
        f"That link works for {_LINK_DAYS} days."
    )


class TemplateKey(StrEnum):
    """The five templates spec 4.1 names. The value is also the filename stem."""

    INITIAL_DOCUMENTATION_REQUEST = "initial_documentation_request"
    REMINDER_FOLLOW_UP = "reminder_follow_up"
    STATUS_UPDATE = "status_update"
    CONDITION_RESPONSE_REQUEST = "condition_response_request"
    CUSTOM = "custom"


@dataclass(frozen=True)
class TemplateSpec:
    """One template at one version — what the audit record names, and what render needs."""

    key: TemplateKey
    version: str
    #: Exactly the placeholders the file uses. Declared rather than derived so the two can be
    #: compared: a placeholder added to the file without being declared here, or the reverse, is a
    #: caller rendering with the wrong context, and a test refuses either direction.
    variables: frozenset[str]


@dataclass(frozen=True)
class RenderedTemplate:
    """A rendered email, carrying the identity of what rendered it.

    Subject, body, key and version travel TOGETHER deliberately. The audit record has to name the
    template and version that produced the body it stores; handing back a bare string would let a
    caller record one template's identity against another's words, and nothing downstream could tell.
    """

    template_key: TemplateKey
    version: str
    subject: str
    body: str


_COMMON = frozenset({"borrower_first_name", "processor_name"})

#: The registry. One entry per key; the newest version is the one rendered.
TEMPLATES: dict[TemplateKey, TemplateSpec] = {
    TemplateKey.INITIAL_DOCUMENTATION_REQUEST: TemplateSpec(
        key=TemplateKey.INITIAL_DOCUMENTATION_REQUEST,
        # v2 (LP-810) — v1's three framing sentences became `$opening`, `$bridge` and `$closing` so
        # the drafting engine can replace them without touching the address line, the security notice
        # or the document list. The plain path fills them from `framing.plain.v1.txt`, which carries
        # v1's exact sentences: with the flag off, a reader sees what v1 produced.
        #
        # A VERSION BUMP RATHER THAN AN EDIT, which is what ADR-401 is for. v1's fingerprint stays
        # pinned below and its file stays on disk, so an audit row naming v1 still resolves to the
        # words it named.
        # v3 (LP-824) — THE CONTRADICTION A PROCESSOR REPORTED. v2 asked the borrower to reply with
        # documents attached or send them to the file address, and then said email is not a fully
        # secure channel and to "reply and tell us and we will arrange another route". Instruction
        # and caveat cancelled out, and the route named nothing. v3 carries the rewritten
        # `SECURITY_NOTICE`, which names the secure upload link LP-815 already built.
        #
        # A VERSION BUMP RATHER THAN AN EDIT, which is what ADR-401 is for. v2's fingerprint stays
        # pinned below and its file stays on disk, so an audit row naming v2 still resolves to the
        # words it named.
        # v4 (LP-834) — the security sentence becomes `$secure_upload_block`, so a draft can carry a
        # live upload link where the processor has minted one, and LP-824's wording where they have
        # not. The words are unchanged in the second case; the slot is what is new.
        version="v4",
        variables=_COMMON
        | {
            "loan_reference",
            "document_list",
            "inbox_address",
            "opening",
            "bridge",
            "closing",
            "secure_upload_block",
        },
    ),
    TemplateKey.REMINDER_FOLLOW_UP: TemplateSpec(
        key=TemplateKey.REMINDER_FOLLOW_UP,
        # v2 (LP-824) — THE SAME CONTRADICTION, in a template nothing renders yet. It asks "reply
        # with them attached, or send them to $inbox_address" and carried the old notice verbatim.
        # Bumped with the reported one because an asymmetry is a class: leaving it would ship the
        # defect on the day somebody wires this template up, with nothing to say it was known.
        version="v2",
        variables=_COMMON | {"loan_reference", "document_list", "inbox_address"},
    ),
    TemplateKey.STATUS_UPDATE: TemplateSpec(
        key=TemplateKey.STATUS_UPDATE,
        version="v1",
        variables=_COMMON | {"loan_reference", "status_summary", "next_step"},
    ),
    TemplateKey.CONDITION_RESPONSE_REQUEST: TemplateSpec(
        key=TemplateKey.CONDITION_RESPONSE_REQUEST,
        # v2 (LP-824) — the third member of the class, same words, also unrendered today.
        version="v2",
        variables=_COMMON | {"loan_reference", "condition_list", "inbox_address"},
    ),
    TemplateKey.CUSTOM: TemplateSpec(
        key=TemplateKey.CUSTOM,
        version="v1",
        variables=_COMMON | {"subject_line", "message_body"},
    ),
}

#: The `allowlist secret` pragmas below are because detect-secrets flags any 64-character hex string
#: on entropy alone. These are digests OF the template text, which sits in the repo beside them, so
#: they reveal nothing that reading the file does not.
#:
#: The pinned content hashes, by (key, version). Separate from TEMPLATES so a NEW version is an
#: added row rather than an edit to an existing one — the old hash stays readable, which is what
#: makes a historical audit row checkable against the words that were actually sent.
VERSION_FINGERPRINTS: dict[tuple[TemplateKey, str], str] = {
    (
        TemplateKey.INITIAL_DOCUMENTATION_REQUEST,
        "v4",
    ): "c14a7dbc4588095a0a898e2fb68868e845be7b1aa38f89a4c0c9a85ab46b5c1c",  # pragma: allowlist secret
    (
        TemplateKey.INITIAL_DOCUMENTATION_REQUEST,
        "v3",
    ): "26c5c4682896d4d6218cb14f64f71b7a45ba8fb25f550e25a38091ff3cf03537",  # pragma: allowlist secret
    (
        TemplateKey.REMINDER_FOLLOW_UP,
        "v2",
    ): "daa0a07f05c38830c6bb062489df29e6b3e7455b4e0adaef4dda4dea5eae004b",  # pragma: allowlist secret
    (
        TemplateKey.CONDITION_RESPONSE_REQUEST,
        "v2",
    ): "de475c7e87225435a13238a47afae70bf4a542261033eb50d19c6d96740b17cd",  # pragma: allowlist secret
    (
        TemplateKey.INITIAL_DOCUMENTATION_REQUEST,
        "v2",
    ): "6835d09dbbe811e766c52bae1effe365943ee8c049e54ae8724ce1568d3f4ad3",  # pragma: allowlist secret
    (
        TemplateKey.INITIAL_DOCUMENTATION_REQUEST,
        "v1",
    ): "e90926229ef0223b380540d4bf4807851355947af818deca21bc0230727640cb",  # pragma: allowlist secret
    (
        TemplateKey.REMINDER_FOLLOW_UP,
        "v1",
    ): "6803f6303a8228964cee1d601a4507563ae5e470b9a204ef6f940ace7eb50974",  # pragma: allowlist secret
    (
        TemplateKey.STATUS_UPDATE,
        "v1",
    ): "834ac0d27a2270230c18d512457001029cb4d21325bee1a3bf5c9df0ff16688f",  # pragma: allowlist secret
    (
        TemplateKey.CONDITION_RESPONSE_REQUEST,
        "v1",
    ): "22bbebc98fcd9f57ea358bf49a4e750bb9de03365318e3e4b73c5f039945d166",  # pragma: allowlist secret
    (
        TemplateKey.CUSTOM,
        "v1",
    ): "b2a700f1ecf8450e825b4d2be1f9c0a0ed00bbfcfb2bea1e3c9366fc69ccef39",  # pragma: allowlist secret
}


class TemplateError(Exception):
    """A template could not be loaded or rendered. Always a programmer error, never a user one."""


@cache
def _load(key: TemplateKey, version: str) -> tuple[str, str]:
    """The template file's ``(subject, body)``, cached — files do not change at runtime.

    The file format is an email: a ``Subject:`` line, a blank line, then the body. It reads as the
    artefact it becomes, so a reviewer of a template edit sees what a borrower will see.
    """
    path = (_TEMPLATES_DIR / f"{key.value}.{version}.txt").resolve()
    if _TEMPLATES_DIR not in path.parents:
        raise TemplateError(f"template path escapes the templates dir: {key.value}.{version}")
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise TemplateError(f"no template file for {key.value} {version}") from exc
    head, separator, body = raw.partition("\n\n")
    if not separator or not head.startswith("Subject: "):
        raise TemplateError(
            f"{key.value} {version}: expected a 'Subject: ' line, a blank line, then the body"
        )
    return head.removeprefix("Subject: ").strip(), body.strip()


def file_fingerprint(key: TemplateKey, version: str) -> str:
    """SHA-256 of the template file as it stands on disk — what the pin is compared against."""
    path = _TEMPLATES_DIR / f"{key.value}.{version}.txt"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def placeholders(key: TemplateKey, version: str) -> frozenset[str]:
    """Every ``$name`` the file actually uses, subject and body together."""
    subject, body = _load(key, version)
    found: set[str] = set()
    for text in (subject, body):
        for match in Template.pattern.finditer(text):
            name = match.group("named") or match.group("braced")
            if name:
                found.add(name)
    return frozenset(found)


def render(key: TemplateKey, context: dict[str, str]) -> RenderedTemplate:
    """Render ``key`` at its current version. Deterministic, no model, no I/O beyond the file.

    Raises :class:`TemplateError` when the context does not supply exactly what the template needs.
    FAILING IS THE POINT: ``string.Template.safe_substitute`` would leave ``$inbox_address`` sitting
    in the body of a real email to a borrower, and nothing downstream inspects a rendered body for
    leftover placeholders. A missing variable is a bug in the caller, and it should surface before a
    send, not after.
    """
    spec = TEMPLATES[key]
    missing = spec.variables - context.keys()
    if missing:
        raise TemplateError(f"{key.value} {spec.version}: missing context {sorted(missing)}")
    subject, body = _load(key, spec.version)
    scoped = {name: context[name] for name in spec.variables}
    try:
        return RenderedTemplate(
            template_key=key,
            version=spec.version,
            subject=Template(subject).substitute(scoped),
            body=Template(body).substitute(scoped),
        )
    except (KeyError, ValueError) as exc:
        raise TemplateError(f"{key.value} {spec.version}: {exc}") from exc


#: The plain framing file, and the version its sentences came from. It is CONTENT, like the templates
#: beside it, and pinned like them — the sentences a borrower reads with the drafting flag off must be
#: as unable to change silently as the template that frames them.
PLAIN_FRAMING_FILE = "framing.plain.v1.txt"
PLAIN_FRAMING_FINGERPRINT = (
    "d77edec4103b2270155492ef85f3d1246523b07021732e8ac1ad3b3ff15d03f3"  # pragma: allowlist secret
)


@dataclass(frozen=True)
class Framing:
    """The three sentences a draft's structure wraps around: why we are writing, what follows, what next."""

    opening: str
    bridge: str
    closing: str


@cache
def plain_framing() -> Framing:
    """v1's own three sentences, unchanged — what a reader sees with the drafting flag off.

    Kept in a file rather than as string constants for the reason every template is: they are words a
    person will edit, and they diff cleanly in review. Kept SEPARATE from the template because the
    template is the structure and these are one interchangeable part of it — LP-810 substitutes a
    composed set into the same three slots.
    """
    path = (_TEMPLATES_DIR / PLAIN_FRAMING_FILE).resolve()
    if _TEMPLATES_DIR not in path.parents:
        raise TemplateError("plain framing path escapes the templates dir")
    parts = [
        block.strip() for block in path.read_text(encoding="utf-8").split("\n\n") if block.strip()
    ]
    if len(parts) != 3:
        raise TemplateError(
            f"{PLAIN_FRAMING_FILE}: expected three paragraphs (opening, bridge, closing), got {len(parts)}"
        )
    return Framing(*parts)


def plain_framing_fingerprint() -> str:
    """SHA-256 of the plain framing file as it stands on disk."""
    return hashlib.sha256((_TEMPLATES_DIR / PLAIN_FRAMING_FILE).read_bytes()).hexdigest()


def render_document_block(document_types: tuple[str, ...]) -> str:
    """LP-800's guidance, formatted as the ``$document_list`` a borrower reads.

    THIS IS WHERE LP-800 STOPS BEING A DATA STRUCTURE. The catalog knows what to call each type, how
    to obtain it, what "all of it" means and how it usually arrives wrong; none of that reaches
    anyone until something renders it. A type with no full entry still gets a line — its English
    name, never its slug, which is the one thing that must never appear in a borrower's inbox.

    Ordered as given: the caller decides what to ask for first, and shuffling that here would put
    the drafter's judgement out of its reach.

    REFUSES ANY TYPE THE BORROWER DOES NOT HOLD, and the guard is scoped to exactly that: LP-800
    assigns every catalog type a responsible party, and this block is only ever interpolated into a
    template addressed to a borrower. Every type it turns away is one the borrower cannot obtain —
    a lender-ordered appraisal, a title commitment, an employer's VOE — so asking for it wastes a
    round trip and costs their confidence in the rest of the list. An uncataloged type is refused
    too, by the same rule: LP-800 defaults it to the processor, and a document nobody has classified
    is not one to ask a borrower for. LP-820 owns the non-borrower request paths and will want its
    own block; this one cannot quietly become it.
    """
    blocks: list[str] = []
    for document_type in document_types:
        guidance = get_guidance(document_type)
        if guidance.responsible_party is not ResponsibleParty.BORROWER:
            raise TemplateError(
                f"{document_type!r} is held by {guidance.responsible_party.value}, not the "
                "borrower — it cannot go in a borrower-facing document list"
            )
        lines = [f"- {guidance.borrower_label or document_label(document_type)}"]
        if guidance.how_to_obtain:
            lines.append(f"    Where to get it: {guidance.how_to_obtain}")
        if guidance.completeness_rule:
            lines.append(f"    What we need to see: {guidance.completeness_rule}")
        if guidance.common_rejects:
            rejects = "; ".join(guidance.common_rejects)
            lines.append(f"    What we cannot accept: {rejects}.")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
