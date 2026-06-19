"""Response schema for the MISMO import endpoint (LP-54).

Import-directly returns the **created file** plus any **parse warnings** (a
partial parse still creates the file — success-with-warnings). The file is the
existing :class:`~app.schemas.loan_file.LoanFileDetail`, so MISMO and manual
creation return the same shape and the SSN stays masked (borrowers expose only
``masked_ssn``).
"""

from pydantic import BaseModel

from app.schemas.loan_file import LoanFileDetail


class MismoImportResponse(BaseModel):
    """The created loan file plus the parse warnings (success-with-warnings)."""

    loan_file: LoanFileDetail
    # Needed-now fields that were missing/odd (LP-51); the UI shows
    # "imported with N warnings". Never contains PII values.
    warnings: list[str]
