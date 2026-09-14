"""Minting and redeeming the borrower's upload link (LP-815).

THE SECOND TENANCY INVERSION, and the last one Phase 4 gets. LP-805's `resolve_loan_file_by_address`
starts from an address a stranger typed and derives a company from the loan file it resolves;
:func:`resolve_link` does the same from a token in a URL. Both are here rather than spread around
for one reason: every other read in the codebase starts from an authenticated user, and the two that
do not have to be countable.

The difference from LP-805's is what makes this one safer, and it is worth stating because the two
look alike:

* **The stored form cannot be used to reach anything.** `inbox_token` is stored in the clear,
  because a borrower types the address into their mail client and it has to be recognised. This
  token is stored as a SHA-256, so a database read — a backup, a readonly view, a dump — is not a
  way in.
* **It expires, it is revocable, and it is spent.** An inbox address never expires (ADR-397). This
  one is a capability handed outside the company over a channel we do not control, into a mailbox we
  cannot clean.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from ipaddress import ip_address
from urllib.parse import urlparse
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.base import utcnow
from app.models.document import Document, UploadSource
from app.models.helpers import only_active
from app.models.inbound_attachment import AttachmentSafetyState
from app.models.loan_file import LoanFile
from app.models.upload_link import (
    DEFAULT_MAX_USES,
    DEFAULT_TTL_HOURS,
    UploadLink,
    hash_token,
    mint_token,
)
from app.services.attachment_safety import assess
from app.services.documents import DuplicateDocumentError, create_document
from app.storage import get_storage_backend

logger = get_logger(__name__)

#: The largest file the link accepts. Smaller than nothing at all, which is what an unauthenticated
#: endpoint has by default — and the point is the ENDPOINT rather than the file: a route anybody can
#: reach with no size bound is a way to fill a bucket.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class UploadLinkError(Exception):
    """The link cannot be used. Always says which rule stopped it, in the borrower's words."""


class LinkOriginNotConfigured(RuntimeError):
    """This environment cannot build a usable link. An OPERATOR's error, not a borrower's.

    Separate from `UploadLinkError` on purpose: that one is written in the borrower's words and
    reaches their screen, and none of this is anything they can act on.
    """


def usable_link_origin() -> str:
    """The origin a borrower's link is built from, or a refusal naming the variable (LP-827).

    REPORTED FROM STAGING: the secure link did not open. `UPLOAD_LINK_BASE_URL` was assigned in no
    `.tf`, `.tfvars`, `.yml`, `.env` or script in this repository, so staging ran on the development
    default and every minted link pointed at `http://localhost:3000/upload/<token>` — the reader's
    own machine. The default itself is right and stays: a wrong upload URL should fail visibly
    rather than send a staging test email at a real borrower's production link.

    CHECKED HERE, WHERE THE VALUE IS READ, and not in a `Settings` validator. A validator refuses to
    build the settings object, so it fires in every process — including `alembic upgrade head`,
    which `scripts/deploy` runs on the NEW image under the CURRENTLY DEPLOYED task definition, one
    step BEFORE the apply that sets the variable. Measured by running the real migration command
    under that environment: it dies. The deploy that introduces the requirement could not complete,
    and the apply that satisfies it would never run. A guard that blocks its own rollout is not a
    guard. This is the only place the setting is read, and its two callers — the API response and
    the auto-reply nudge — are both "a link about to reach a person", which is exactly the moment to
    refuse.

    WHAT IT REFUSES, AND WHY THAT SET. A URL with no scheme or no host cannot be clicked from an
    email at all: `urlparse("localhost:3000").hostname` is None, so the most natural way to write
    the reported misconfiguration into a tfvars file passed the first version of this check
    untouched. Loopback comes from `ipaddress`, not from a list of spellings — `127.0.0.1`,
    `127.0.0.53`, `::1` and `::ffff:127.0.0.1` are all one rule, and a definition cannot miss a
    member the way an enumeration can.

    IT STILL DOES NOT JUDGE REACHABILITY. A wrong domain, a typo, an http/https mix-up are values
    somebody chose, and config cannot tell a chosen mistake from a chosen intention.
    """
    origin = settings.upload_link_base_url.strip().rstrip("/")
    parsed = urlparse(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise LinkOriginNotConfigured(
            f"UPLOAD_LINK_BASE_URL={settings.upload_link_base_url!r} is not an absolute http(s) "
            "origin, so no link built from it can be opened from an email. Set it to this "
            "environment's public web origin."
        )
    # LOOPBACK IS CORRECT IN DEVELOPMENT, and it is the default there for a reason — a developer's
    # link should point at their own machine. The scheme/host check above still applies everywhere,
    # because an origin with no host is unusable in any environment.
    host = parsed.hostname.lower().rstrip(".")
    if settings.environment == "development":
        return origin
    if host == "localhost" or _is_local_address(host):
        raise LinkOriginNotConfigured(
            f"UPLOAD_LINK_BASE_URL points at {host!r} with ENVIRONMENT="
            f"{settings.environment!r}. Every secure upload link this environment mints would send "
            "the borrower to their own machine. Set it to this environment's public web origin."
        )
    return origin


def _is_local_address(host: str) -> bool:
    """Is this host literal an address that means "the machine reading this"?

    False for a name — a name is resolved by the reader's DNS and we are not going to ask.
    """
    try:
        address = ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_unspecified


@dataclass(frozen=True)
class MintedLink:
    """A new link and its URL. The plaintext token exists HERE AND NOWHERE ELSE — the row holds a
    hash, so this object is the only chance to send it."""

    link: UploadLink
    token: str

    @property
    def url(self) -> str:
        return f"{usable_link_origin()}/upload/{self.token}"


async def mint_upload_link(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    recipient_email: str | None = None,
    ttl_hours: int = DEFAULT_TTL_HOURS,
    max_uses: int = DEFAULT_MAX_USES,
    purpose: str | None = None,
) -> MintedLink:
    """Create a link for ``loan_file``. ``flush`` only; the caller commits.

    A NEW LINK EVERY TIME, rather than reusing a live one. Reuse would mean one token in two
    mailboxes, so revoking it for one borrower revokes it for the other — and the row is cheap.
    """
    token = mint_token()
    link = UploadLink(
        loan_file_id=loan_file.id,
        token_hash=hash_token(token),
        expires_at=utcnow() + timedelta(hours=ttl_hours),
        recipient_email=recipient_email,
        max_uses=max_uses,
        purpose=purpose,
    )
    db.add(link)
    await db.flush()
    # NEVER THE TOKEN, and never the recipient. An id and a lifetime.
    logger.info("upload_link_minted", loan_file_id=str(loan_file.id), ttl_hours=ttl_hours)
    return MintedLink(link=link, token=token)


async def resolve_link(db: AsyncSession, *, token: str) -> UploadLink | None:
    """The live link this token opens, or None.

    THE TENANCY INVERSION. Everything else in this codebase starts from `current_user.company_id`;
    this starts from a string in a URL a stranger typed, and the loan file it resolves is what says
    whose it is. Nothing downstream may re-derive a company any other way.

    ONE ANSWER FOR EVERY FAILURE. Unknown, expired, revoked and spent all return None, so the
    endpoint cannot distinguish them and neither can a caller probing tokens. Which of the four it
    was is exactly what a prober wants to know — "expired" confirms a token existed.
    """
    if not token:
        return None
    link = (
        await db.execute(
            only_active(
                select(UploadLink).where(UploadLink.token_hash == hash_token(token)), UploadLink
            )
        )
    ).scalar_one_or_none()
    if link is None or not link.is_usable():
        return None
    return link


async def revoke_link(db: AsyncSession, *, link: UploadLink) -> UploadLink:
    """Withdraw a link. Idempotent — revoking twice keeps the first time, which is when it stopped
    working."""
    if link.revoked_at is None:
        link.revoked_at = utcnow()
        await db.flush()
    return link


async def list_links(db: AsyncSession, *, loan_file: LoanFile) -> list[UploadLink]:
    """Every link minted for this file, newest first. Never carries a token — there is none to
    carry."""
    return list(
        (
            await db.execute(
                only_active(
                    select(UploadLink)
                    .where(UploadLink.loan_file_id == loan_file.id)
                    .order_by(UploadLink.created_at.desc()),
                    UploadLink,
                )
            )
        )
        .scalars()
        .all()
    )


async def redeem_link(
    db: AsyncSession, *, link: UploadLink, filename: str, content: bytes
) -> Document:
    """Put one uploaded file on the link's loan file. ``flush`` only; the caller commits.

    THE SAME SAFETY GATE AS INBOUND MAIL, and it has to be: this is a stranger's bytes arriving over
    a channel with no authentication beyond the token, which is exactly the inbound-attachment
    threat model. `assess` sniffs the magic bytes, refuses anything off the allowlist, strips a PDF's
    active content and proves it renders. A file that does not come back SAFE never becomes a
    document, and the borrower is told the REASON, which is what makes the refusal actionable —
    "ask for a copy without a password" is a different next step from "send the file, not a zip".

    THE COUNTER MOVES ON A SUCCESSFUL UPLOAD, not on a page view. A borrower who opens the link
    twice before sending anything has spent nothing; `max_uses` bounds documents delivered, which is
    what a leaked link would be used for.
    """
    if len(content) == 0:
        raise UploadLinkError("That file was empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise UploadLinkError(
            f"That file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB. "
            "Send it in parts, or ask for another way to deliver it."
        )
    if not link.is_usable():
        # Re-checked here and not only at the endpoint. The link was live when the page loaded; a
        # borrower can sit on that page past the expiry, and this is the moment that matters.
        raise UploadLinkError("This link is no longer active. Ask for a new one.")

    outcome = assess(content)
    if outcome.state is not AttachmentSafetyState.SAFE:
        raise UploadLinkError(outcome.reason or "That file could not be accepted.")

    loan_file = await db.get(LoanFile, link.loan_file_id)
    if loan_file is None:  # pragma: no cover - FK is CASCADE, so this cannot be reached
        raise UploadLinkError("This link is no longer active. Ask for a new one.")

    document_id = uuid4()
    storage_path = await get_storage_backend().save(
        company_id=loan_file.company_id,
        file_id=loan_file.id,
        document_id=document_id,
        filename=filename,
        content=content,
    )
    # LP-1000 — the borrower sending the same file twice is the most likely duplicate of all (a
    # retry, a second tap on an unresponsive button), so this path gets the same refusal as the
    # others, in `UploadLinkError`'s borrower-facing register. It says the file is already there
    # WITHOUT naming the existing document: this response goes to an unauthenticated stranger
    # holding a link, and which documents a loan file holds is not theirs to learn.
    try:
        document = await create_document(
            db,
            loan_file=loan_file,
            document_id=document_id,
            filename=filename,
            content=content,
            storage_path=storage_path,
            mime_type=outcome.sniffed_content_type or "application/octet-stream",
            # WHAT WAS WRITTEN, not what was claimed — the LP-806 lesson. A recorded size taken
            # from anywhere but the bytes agrees with a document containing something else.
            size=len(content),
            # ADR-056: no user actor. A borrower delivered this; naming the processor who minted
            # the link would make the provenance say something untrue.
            uploaded_by_user_id=None,
            upload_source=UploadSource.SECURE_LINK,
        )
    except DuplicateDocumentError as exc:
        raise UploadLinkError(
            "We already have that file — there is no need to send it again."
        ) from exc

    link.uses += 1
    link.last_used_at = utcnow()
    await db.flush()
    # METADATA ONLY — never the filename, which is text a stranger typed.
    logger.info(
        "upload_link_redeemed",
        loan_file_id=str(loan_file.id),
        uses=link.uses,
        bytes=len(content),
    )
    return document


async def link_for_loan_file(db: AsyncSession, *, link: UploadLink) -> LoanFile | None:
    """The file a link opens. Separate so the endpoint never re-derives it from anything else."""
    return await db.get(LoanFile, link.loan_file_id)


def public_reference(loan_file: LoanFile) -> str:
    """What the borrower is shown about the file, and nothing more.

    THE DISPLAY ID, NOT THE ADDRESS OR THE BORROWER'S NAME. This page is reachable by anyone holding
    the token, which after a forward is anyone the borrower sent the email to. A page confirming
    "yes, Jane Borrower, 42 Maple Avenue" turns a leaked link into a disclosure as well as a write.
    """
    return loan_file.display_id


__all__ = [
    "MAX_UPLOAD_BYTES",
    "MintedLink",
    "UploadLinkError",
    "link_for_loan_file",
    "list_links",
    "mint_upload_link",
    "public_reference",
    "redeem_link",
    "resolve_link",
    "revoke_link",
]
