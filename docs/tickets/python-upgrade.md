# python-upgrade — certifi and Pillow security bumps

Lockfile-only dependency bump in response to two October 2026 advisories. No code, schema or
infrastructure changes. Committed as `3579cb84`.

```
certifi 2026.5.20 -> 2026.10.23
pillow  12.3.0    -> 13.0.0
```

## What and why

**certifi: we were exposed.** eMudhra (emSign) had eight intermediate CA private keys compromised,
which lets an attacker forge an HTTPS certificate for any site. Python's expedited releases
(3.15.1, 3.14.9, 3.13.17) ship a certifi that drops trust in them; 3.12 is source-only and got no
release, so for us the fix is the certifi package itself. httpx, httpcore and sentry-sdk trust the
certifi bundle, so every outbound TLS call (Anthropic, Sentry) was affected. Exploiting it needs a
man-in-the-middle position, so the practical risk was narrow, but the fix is one line.

Some sources call this CVE-2026-115557. We found that ID only in secondary write-ups (Rapid7, HOL
Guard), never in a CPython record, so treat the number as unconfirmed.

**Pillow: installed, not reachable.** Pillow 2.6.0–12.3.0 carries CVE-2026-112900 (EPS filename
passed to Ghostscript, command execution), CVE-2026-112403 (lossless-JPEG `thumbnail()`/`draft()`
overflow), CVE-2026-112393 (compressed TIFF saved to `BytesIO`), an FPX decoding overflow, and a
stale-image-data bug; all fixed in 13.0.0 (source: The Hacker News, not yet checked against
Pillow's own advisory). None of these paths could be reached here:

- Pillow is only a transitive dependency of `pikepdf`. No code under `app/` imports `PIL`.
- `pikepdf` is used only in `app/services/attachment_safety.py` to open a PDF and strip actions and
  annotations. It never extracts or decodes an image.
- Image uploads go to Claude and PyMuPDF, not Pillow.
- The Dockerfile installs `tesseract-ocr` only, not Ghostscript (the EPS flaw needs `gs`).
- `olefile` is not in the lockfile (the FPX flaw needs it).

We bumped anyway, so security scanners stop flagging 12.3.0 and a future `as_pil_image()` call on an
attachment does not silently reopen the hole.

## Not affected (checked)

- **Brotli "Node2Shell" (CVE-2026-111497):** neither `brotli` nor `brotlicffi` is in `uv.lock`.
- **webbrowser command injection (CVE-2026-4519):** not relevant to a server app. We did not
  check whether our code uses the `webbrowser` module.
- **OpenSSL:** 3.5.6 (April 2026), not involved.

## Assumptions and open points

- The new bundle still trusts one eMudhra root, `emSign Root CA - G1`. That fits the report that
  only intermediates were compromised, but we have not confirmed it against Mozilla's or Python's
  notice.
- Python stays on 3.12 (`python:3.12-slim`). Pillow 13 needs Python 3.11 or newer, which 3.12
  meets.
- **Staging runs the old versions until a redeploy.** A deploy ships the working tree; check with
  `./scripts/deploy staging status`.

## Verification

- pikepdf 10.13.0.post1 works with Pillow 13 unchanged.
- Targeted tests: attachment safety, inbound triage and documents (408), plus AI, storage, config
  and health (1,772) — 2,180 passed. The full suite was not run.
- A live HTTPS request to `api.anthropic.com` connected with the new bundle (the 404 is normal
  for that bare URL).
