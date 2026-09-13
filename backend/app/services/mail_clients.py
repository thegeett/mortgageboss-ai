"""Which compose window to open, and the guess that pre-selects it (LP-855).

NOTHING IN A BROWSER CAN DETECT THIS. There is no API that reports which mail client somebody uses,
so LP-855 asks — once, on the first draft — and this is the half that makes the asking cheap: the
picker arrives with a radio already selected and a sentence saying why.

IT MOVES A RADIO BUTTON AND SAYS WHY. IT NEVER DECIDES. A guess that applied itself would be a
message opened in the wrong place with nothing on screen explaining it, and the processor would have
to work out that we had chosen for them. A guess that is visible and wrong costs one click.
"""

from __future__ import annotations

from app.models.user import MailClient

#: Sign-in domains that say which web client somebody almost certainly uses.
#:
#: EXACT DOMAINS, NOT SUBSTRINGS. A `"outlook" in domain` test matches `outlook-consulting.com`,
#: which is a mortgage brokerage in Ohio rather than a Microsoft tenant — and the suggestion would
#: then be wrong in a way that looks authoritative. A company on Google Workspace signs in as
#: `@theirfirm.com` and is not detectable here at all, which is why the safe answer is the fallback.
_BY_DOMAIN: dict[str, tuple[MailClient, str]] = {
    "gmail.com": (MailClient.GMAIL, "you sign in as {email}"),
    "googlemail.com": (MailClient.GMAIL, "you sign in as {email}"),
    "outlook.com": (MailClient.OUTLOOK_PERSONAL, "you sign in as {email}"),
    "hotmail.com": (MailClient.OUTLOOK_PERSONAL, "you sign in as {email}"),
    "live.com": (MailClient.OUTLOOK_PERSONAL, "you sign in as {email}"),
    "msn.com": (MailClient.OUTLOOK_PERSONAL, "you sign in as {email}"),
}


def suggest_mail_client(email: str | None) -> tuple[MailClient, str]:
    """Which option to pre-select, and the sentence saying why.

    THE SAFE ANSWER WHEN THE DOMAIN SAYS NOTHING, which is the common case: a processor at a
    mortgage company signs in as `@theirfirm.com`, and that domain is consistent with Gmail,
    Outlook, Apple Mail and a locally installed Outlook alike. Suggesting one of them on no evidence
    would be a coin flip wearing a recommendation's clothes.

    The reason is empty for the fallback rather than invented. "Suggested because we could not tell"
    is not a reason a processor benefits from reading, and the option's own description already says
    it is the safe one if you are unsure.
    """
    address = (email or "").strip().lower()
    _, _, domain = address.partition("@")
    found = _BY_DOMAIN.get(domain)
    if found is None:
        return MailClient.MAILTO, ""
    client, template = found
    return client, template.format(email=address)


__all__ = ["suggest_mail_client"]
