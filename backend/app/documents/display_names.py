"""LP-943 — a document type's name for people outside the app: emails, re-asks and the package's notes.

`verification/rule_engine/reasons.document_label` turns a classifier slug into words by replacing
underscores, which is right for the rule engine's own reasons and wrong in an email to a title company:
`borrower_s_authorization_for_counseling` became "borrower s authorization for counseling", `verbal_voe`
"verbal voe", and `letter_of_explanation_asset` leaked its internal discriminator ("… asset"). This is
the display name: an explicit name where the rule reads badly, and a word-level rule (acronyms kept as
acronyms) for the rest. `tests/documents/test_display_names.py` fails for any CATALOGUED type without a
clean one: the attention panel names any document, not only the library's.

`display_name` is for a list or a heading ("Borrower's authorization for counseling"); `in_sentence`
for mid-sentence ("A corrected borrower's authorization for counseling").
"""

from __future__ import annotations

#: Where the underscore rule reads badly: possessives, hyphens, an internal discriminator, a form number.
DISPLAY_NAMES: dict[str, str] = {
    # A type whose slug extends another's is named on purpose (the test requires it): here the suffix
    # is a real word, where for `letter_of_explanation_*` it is the classifier's tag.
    "appraisal_payment": "Appraisal payment",
    "borrower_s_authorization_for_counseling": "Borrower's authorization for counseling",
    "drivers_license": "Driver's license",
    "e_consent_disclosure": "E-consent disclosure",
    "form_1040_personal_tax_transcripts": "Form 1040 tax transcripts",
    "government_issued_id": "Government-issued ID",
    "homeowner_s_insurance_quote": "Homeowner's insurance quote",
    "ira_401k": "IRA or 401(k) statement",
    "letter_of_explanation_asset": "Letter of explanation (assets)",
    # "(other)", not bare: the plain `letter_of_explanation` renders "Letter of explanation", and one
    # file can ask for both (LP-943 review). The family is parenthesised; this matches it.
    "letter_of_explanation_misc": "Letter of explanation (other)",
    "letter_of_explanation_property": "Letter of explanation (property)",
    # LP-943 follow-up review: catalogue types the attention panel can name, where a form number or an
    # acronym-plus-number is the whole name.
    "social_security_administration_ssa_89": "Form SSA-89",
    "k_1_shareholder_profit_and_loss_transcripts": "K-1 shareholder profit and loss transcripts",
    "k1_statement": "K-1 statement",
    "form_4506c": "Form 4506-C",
    "form_4506t_request_for_transcript": "Form 4506-T request for transcript",
    "verbal_voe": "Verbal VOE",
    "voe": "Verification of employment (VOE)",
    "w2": "W-2",
    "w9": "W-9",
}

#: Words that are acronyms wherever they appear in a slug (`hoa_statement` → "HOA statement").
ACRONYMS: dict[str, str] = {
    "voe": "VOE",
    "voa": "VOA",
    "vom": "VOM",
    "voi": "VOI",
    "hoa": "HOA",
    "id": "ID",
    "ira": "IRA",
    "irs": "IRS",
    "ssn": "SSN",
    "ssa": "SSA",
    "llc": "LLC",
    "hud": "HUD",
    "poa": "POA",
    "dti": "DTI",
    "emd": "EMD",
    "w2": "W-2",
    "w9": "W-9",
}


def display_name(document_type: str) -> str:
    """ "Borrower's authorization for counseling", "HOA statement", "Bank statement"."""
    slug = document_type.strip().lower()
    if slug in DISPLAY_NAMES:
        return DISPLAY_NAMES[slug]
    words = [ACRONYMS.get(word, word) for word in slug.split("_") if word]
    if not words:
        return document_type
    first = words[0]
    words[0] = first if first in ACRONYMS.values() else first[:1].upper() + first[1:]
    return " ".join(words)


def in_sentence(name: str) -> str:
    """The name mid-sentence: the first letter lowered unless the first word is an acronym or a number
    ("HOA statement", "W-2", "IRA or 401(k) statement" stay as they are)."""
    first = name.split(" ", 1)[0]
    if first.isupper() or any(ch.isdigit() for ch in first) or len(first) <= 1:
        return name
    return name[:1].lower() + name[1:]


__all__ = ["ACRONYMS", "DISPLAY_NAMES", "display_name", "in_sentence"]
