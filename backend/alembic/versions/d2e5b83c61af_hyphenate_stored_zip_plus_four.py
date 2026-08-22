"""Hyphenate a stored 9-digit ZIP+4 so it stops reading as an account number (bug-001)

Revision ID: d2e5b83c61af
Revises: c8d1a4e77b93

WHY A MIGRATION AND NOT A SCRIPT. The MISMO parser now hyphenates a 9-digit postal code, but import
is ONE-SHOT: the snapshot reads `properties.postal_code` from this table, not from the XML, so a file
imported before that change keeps the un-hyphenated value forever and keeps losing its snapshot on
every run. Unlike the LP-596 backfill this is a pure column normalization with no object-storage I/O
and no service logic, which is what a migration is for.

WHAT IT COSTS IF SKIPPED. The snapshot's at-rest guard refuses any bare run of 9+ digits — the shape
of an unmasked SSN — and an un-hyphenated ZIP+4 is exactly nine. The refusal is ALL OR NOTHING: the
whole snapshot is rejected, so the file loses every tag value and every calculation, not just the
postal code. One real file had two completed runs and zero persisted snapshots because of this.

NARROW BY CONSTRUCTION. The WHERE matches only a value that is exactly nine digits and nothing else.
A 5-digit ZIP, an already-hyphenated ZIP+4, and a non-US postal code are untouched, so this cannot
corrupt an address it does not understand.

REVERSIBLE, and the downgrade is written rather than a `pass`: it removes the hyphen from a value of
exactly the `NNNNN-NNNN` shape. Reversing it restores the defect, which is the honest meaning of
downgrading past this revision.
"""

from alembic import op

revision = "d2e5b83c61af"  # pragma: allowlist secret
down_revision = "c8d1a4e77b93"  # pragma: allowlist secret
branch_labels = None
depends_on = None

# `~` is a POSIX regex match; `^\d{9}$` anchors it to EXACTLY nine digits, so a 5-digit ZIP and an
# already-hyphenated one are both excluded by the pattern rather than by a second condition.
_UP = r"""
    UPDATE properties
       SET postal_code = substr(postal_code, 1, 5) || '-' || substr(postal_code, 6, 4)
     WHERE postal_code ~ '^\d{9}$'
"""

_DOWN = r"""
    UPDATE properties
       SET postal_code = replace(postal_code, '-', '')
     WHERE postal_code ~ '^\d{5}-\d{4}$'
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
