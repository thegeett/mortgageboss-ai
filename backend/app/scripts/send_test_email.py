"""Send one sample email through the configured mail sender (LP-993). Dev and test only.

    uv run python -m app.scripts.send_test_email --to borrower@example.test [--html]

Builds the email with `build_mime` (From "Test Processor, MortgageBoss Test" <lf-test@…>, CC the
same test address, Reply-To the From address) and sends it through `get_mail_sender()`. Prints the
provider's message id. Refuses when no sender is configured (`MAIL_TRANSPORT` blank).

WITH `MAIL_TRANSPORT=ses` IT SENDS ONLY TO THE SES MAILBOX SIMULATOR (`…@simulator.amazonses.com`).
A real address is refused: a test script is not how an email reaches a person.
"""

from __future__ import annotations

import argparse
import sys

from app.core.config import settings
from app.services.mail_sender import SendError, get_mail_sender
from app.services.outbound_mime import build_mime

_SIMULATOR_DOMAIN = "simulator.amazonses.com"

_PLAIN = (
    "Hello,\n\n"
    "This is a test email from MortgageBoss (LP-993). Nothing needs doing.\n\n"
    "- Bank statements\n"
    "- Pay stubs\n\n"
    "Test Processor\n\n[LF-TEST]\n"
)
_HTML = (
    "<p>Hello,</p>"
    "<p>This is a test email from MortgageBoss (LP-993). Nothing needs doing.</p>"
    "<ul><li>Bank statements</li><li>Pay stubs</li></ul>"
    '<p><a href="https://example.test/upload/abc">Upload securely</a></p>'
    "<p>Test Processor</p><p>[LF-TEST]</p>"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--to", required=True, help="Recipient (also CC'd).")
    parser.add_argument("--html", action="store_true", help="Send an HTML body.")
    parser.add_argument(
        "--from-address",
        default="lf-test@mb-mail.localhost",
        help="From and Reply-To (default lf-test@mb-mail.localhost).",
    )
    args = parser.parse_args(argv)

    sender = get_mail_sender()
    if sender is None:
        print("Refused: MAIL_TRANSPORT is not set, so nothing can send.", file=sys.stderr)
        return 1
    if settings.mail_transport == "ses" and not args.to.lower().endswith("@" + _SIMULATOR_DOMAIN):
        print(f"Refused: with SES, --to must be an @{_SIMULATOR_DOMAIN} address.", file=sys.stderr)
        return 1

    message = build_mime(
        from_name="Test Processor, MortgageBoss Test",
        from_address=args.from_address,
        to=args.to,
        cc=args.to,
        reply_to=args.from_address,
        subject="LP-993 test email" + (" (HTML)" if args.html else ""),
        body=_HTML if args.html else _PLAIN,
        html=args.html,
    )
    try:
        message_id = sender.send(message)
    except SendError as exc:
        print(f"Send failed: {exc.code} (outcome unknown: {exc.outcome_unknown})", file=sys.stderr)
        return 1
    print(f"Sent via {settings.mail_transport}: {message_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
