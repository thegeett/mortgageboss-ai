"""Real-file smoke for the MISMO section assembler (LP-205).

Builds the ``mismo`` section for a real loan file (default LF-6T3N) against the
configured DB, asserts the top-level keys exist and no raw PII leaks, and prints
the section with PII masked for eyeball review. Read-only; run manually:

    uv run python -m app.scripts.mismo_section_smoke [DISPLAY_ID]
"""

import asyncio
import re
import sys

from sqlalchemy import select

from app.core.database import async_session_maker
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.verification.snapshot.mismo_section import load_mismo_section
from app.verification.snapshot.pii import PiiField

_SSN_RUN = re.compile(r"\d{9,}")  # a 9+ digit run — a raw SSN/account must never appear


async def main(display_id: str = "LF-6T3N") -> None:
    async with async_session_maker() as db:
        loan_file = (
            await db.execute(
                only_active(select(LoanFile).where(LoanFile.display_id == display_id), LoanFile)
            )
        ).scalar_one_or_none()
        if loan_file is None:
            raise SystemExit(f"no active loan file {display_id!r}")

        section = await load_mismo_section(db, loan_file)

    assert section, "expected a populated section"
    for prefix in ("loan.", "borrower.1.", "property.", "liability.1.", "asset.1."):
        assert any(k.startswith(prefix) for k in section), f"missing {prefix}*"

    for key, value in section.items():
        if key.endswith(".ssn"):
            assert isinstance(value, PiiField), f"{key} must be PiiField"
        if isinstance(value, PiiField):
            continue
        # No non-PII Field value may contain a raw 9+ digit run.
        assert not _SSN_RUN.search(str(value.value)), f"raw PII leak at {key}"

    print(f"{display_id}: {len(section)} keys")
    for key in sorted(section):
        value = section[key]
        if isinstance(value, PiiField):
            head = value.match_hash[:14] if value.match_hash else None
            print(f"  {key} = PII(display={value.display}, hash={head}…)")
        else:
            src = value.source.value if value.source else None
            print(f"  {key} = {value.value!r}  [source={src} conf={value.confidence}]")
    print("OK — no raw PII, expected sections present")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "LF-6T3N"))
