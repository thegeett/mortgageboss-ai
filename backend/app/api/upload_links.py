"""The upload link — minted by a processor, redeemed by a borrower (LP-815).

TWO ROUTERS AND ONE OF THEM IS UNAUTHENTICATED, which is the only such surface in this codebase and
the reason this module is worth reading carefully.

`public_router` is reachable by anyone holding a token. It exists because `phase4.md` §6 requires
that outbound email carry no NPI: the borrower gets an authenticated, expiring link instead of being
asked to attach a bank statement to an email. The token IS the authentication, and everything below
follows from that being the only credential:

* **Every failure is one answer.** Unknown, expired, revoked and spent all return the same 404, so
  probing cannot distinguish "wrong" from "was right yesterday".
* **The page names nothing.** Not the borrower, not the property, not the amount — only the file's
  display id. Anyone the borrower forwarded the email to holds this link, and a page confirming who
  the loan is for turns a leaked link into a disclosure as well as a write.
* **There is a size bound and a use bound.** A route anybody can reach with neither is a way to fill
  a bucket.
* **The bytes go through the same safety gate as inbound mail.** Same threat model, same `assess`.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel, EmailStr, Field

from app.api.dependencies import CurrentUser, ScopedLoanFile
from app.core.database import DbSession
from app.models.upload_link import DEFAULT_MAX_USES, DEFAULT_TTL_HOURS, UploadLink
from app.services.upload_links import (
    MAX_UPLOAD_BYTES,
    UploadLinkError,
    link_for_loan_file,
    list_links,
    mint_upload_link,
    public_reference,
    redeem_link,
    resolve_link,
    revoke_link,
)

router = APIRouter(prefix="/loan-files/{file_identifier}/upload-links", tags=["upload-links"])
public_router = APIRouter(prefix="/upload", tags=["upload-links"])

#: ONE ANSWER FOR EVERY FAILURE on the public path. Unknown, expired, revoked and spent are
#: indistinguishable — which of the four it was is exactly what a prober wants to learn, and
#: "expired" confirms a token existed.
_GONE = HTTPException(
    status.HTTP_404_NOT_FOUND,
    detail="This upload link is not active. Ask whoever sent it for a new one.",
)


class UploadLinkPublic(BaseModel):
    """A link as a PROCESSOR sees it. Never carries a token — the row holds only a hash."""

    id: UUID
    expires_at: str
    revoked_at: str | None
    recipient_email: str | None
    uses: int
    max_uses: int
    last_used_at: str | None
    is_usable: bool

    @classmethod
    def of(cls, link: UploadLink) -> "UploadLinkPublic":
        return cls(
            id=link.id,
            expires_at=link.expires_at.isoformat(),
            revoked_at=link.revoked_at.isoformat() if link.revoked_at else None,
            recipient_email=link.recipient_email,
            uses=link.uses,
            max_uses=link.max_uses,
            last_used_at=link.last_used_at.isoformat() if link.last_used_at else None,
            is_usable=link.is_usable(),
        )


class MintedLinkResponse(UploadLinkPublic):
    """The one response that carries the URL.

    THE ONLY TIME THE TOKEN EXISTS OUTSIDE A MINT. The row holds a hash, so if this response is lost
    the link is unrecoverable and a new one must be minted — which is the intended property, not a
    limitation to work around.
    """

    url: str


class MintRequest(BaseModel):
    recipient_email: EmailStr | None = None
    ttl_hours: int = Field(default=DEFAULT_TTL_HOURS, ge=1, le=168)
    max_uses: int = Field(default=DEFAULT_MAX_USES, ge=1, le=100)
    purpose: str | None = Field(default=None, max_length=200)


@router.get("", response_model=list[UploadLinkPublic])
async def list_for_file(
    loan_file: ScopedLoanFile, db: DbSession, current_user: CurrentUser
) -> list[UploadLinkPublic]:
    """Every link minted for this file. A processor needs to see what is live before minting more."""
    return [UploadLinkPublic.of(link) for link in await list_links(db, loan_file=loan_file)]


@router.post("", response_model=MintedLinkResponse, status_code=status.HTTP_201_CREATED)
async def mint(
    payload: MintRequest,
    loan_file: ScopedLoanFile,
    db: DbSession,
    current_user: CurrentUser,
) -> MintedLinkResponse:
    """Mint a link for this file, and return its URL once."""
    minted = await mint_upload_link(
        db,
        loan_file=loan_file,
        recipient_email=payload.recipient_email,
        ttl_hours=payload.ttl_hours,
        max_uses=payload.max_uses,
        purpose=payload.purpose,
    )
    await db.commit()
    return MintedLinkResponse(**UploadLinkPublic.of(minted.link).model_dump(), url=minted.url)


@router.delete("/{link_id}", response_model=UploadLinkPublic)
async def revoke(
    link_id: UUID,
    loan_file: ScopedLoanFile,
    db: DbSession,
    current_user: CurrentUser,
) -> UploadLinkPublic:
    """Withdraw a link. The route proves the caller owns the FILE; this proves the LINK is on it."""
    link = await db.get(UploadLink, link_id)
    if link is None or link.deleted_at is not None or link.loan_file_id != loan_file.id:
        # Same 404 for missing and for another file's — the LP-806 oracle argument.
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such upload link on this file")
    return UploadLinkPublic.of(await revoke_link(db, link=link))


# --------------------------------------------------------------------------------------------- #
# The unauthenticated path
# --------------------------------------------------------------------------------------------- #
class UploadPagePublic(BaseModel):
    """What a borrower holding the token is told, and the ceiling on it.

    A REFERENCE AND A PURPOSE, NOTHING ELSE. No name, no address, no amount, no needs list — the
    holder of this token is whoever the email reached, which after a forward is more people than the
    borrower, and after a spoof may not be the borrower at all.
    """

    reference: str
    purpose: str | None
    max_bytes: int
    remaining_uses: int


@public_router.get("/{token}", response_model=UploadPagePublic)
async def describe(token: str, db: DbSession) -> UploadPagePublic:
    """What this link is for. No authentication — the token is the credential."""
    link = await resolve_link(db, token=token)
    if link is None:
        raise _GONE
    loan_file = await link_for_loan_file(db, link=link)
    if loan_file is None:  # pragma: no cover - FK is CASCADE
        raise _GONE
    return UploadPagePublic(
        reference=public_reference(loan_file),
        purpose=link.purpose,
        max_bytes=MAX_UPLOAD_BYTES,
        remaining_uses=max(0, link.max_uses - link.uses),
    )


@public_router.post("/{token}", status_code=status.HTTP_201_CREATED)
async def upload(
    token: str,
    db: DbSession,
    file: Annotated[UploadFile, File(description="One document")],
) -> dict[str, str]:
    """Put one document on the link's loan file. No authentication — the token is the credential.

    THE RESPONSE SAYS NOTHING ABOUT THE FILE. Not the document id, not the loan file, not what it was
    classified as — an acknowledgement and a refusal reason are the whole vocabulary, because
    anything else is a read primitive on a write-only capability.
    """
    link = await resolve_link(db, token=token)
    if link is None:
        raise _GONE

    content = await file.read()
    try:
        await redeem_link(db, link=link, filename=file.filename or "document", content=content)
    except UploadLinkError as exc:
        # 400 with OUR OWN sentence. `assess` writes these for a person to act on — "ask for a copy
        # without a password" is a different next step from "send the file rather than a zip" — and
        # a borrower who is only told "rejected" sends the same file again.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    return {"status": "received"}
