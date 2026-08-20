"""lp600 rekey snapshot findings

Revision ID: b7c4e91f2d38
Revises: a3f7c21b9e05
Create Date: 2026-08-20 19:00:00.000000

"""

import hashlib
import json
import re
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7c4e91f2d38"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "a3f7c21b9e05"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# --------------------------------------------------------------------------- #
# A FROZEN COPY of `app.ai.snapshot_cross_source`'s identity derivation, as of LP-598.
#
# Frozen on purpose: a migration must keep producing the same result forever, and importing app code
# would let a later refactor silently change what this already-run migration meant. The risk of a
# frozen copy is that it drifts from the app BEFORE it runs, which would leave every key still
# mismatched — so `test_lp600_migration_matches_the_app` pins the two implementations equal.
# --------------------------------------------------------------------------- #

_KINDS = frozenset(
    {
        "value_mismatch",
        "identity_mismatch",
        "date_inconsistency",
        "undisclosed_obligation",
        "calculation_blocked",
        "other",
    }
)


def _normalise(value: str) -> str:
    text = value.strip().casefold()
    candidate = re.sub(r"[,$\s]", "", text)
    if re.fullmatch(r"-?\d+(\.\d+)?", candidate):
        try:
            return str(Decimal(candidate).normalize())
        except InvalidOperation:
            pass
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _normalised_kind(kind: str) -> str:
    candidate = kind.strip().casefold().replace("-", "_").replace(" ", "_")
    return candidate if candidate in _KINDS else "other"


def _finding_key(kind: str, sources: list) -> str:
    material = json.dumps(
        {
            "kind": _normalised_kind(kind),
            "sources": sorted(
                f"{_normalise(str(s.get('label', '')))}={_normalise(str(s.get('value', '')))}"
                for s in sources
                if isinstance(s, dict)
            ),
        },
        sort_keys=True,
    )
    return hashlib.sha256(material.encode()).hexdigest()


def upgrade() -> None:
    # LP-600 — WHY THIS EXISTS. LP-598 stopped hashing the model's free-text `kind` verbatim, because
    # a re-phrased slug minted a new finding and read as "resolved by a file change". That fix is
    # correct going forward and, without this, destructive once: every stored row was keyed with its
    # raw slug, none of which is in the new vocabulary, so on the first run after deploy NO stored row
    # would match its draft.
    #
    # The consequence is not cosmetic churn. Every `signed_off` / `not_an_issue` row would be retained
    # under a key nothing produces again, while the same finding re-opens beside it UN-DISMISSED — a
    # processor's decisions silently discarded, which is the exact failure `finding_key` was written
    # to prevent (see the model docstring: "what lets a processor's disposition survive a re-run").
    #
    # Recomputing the key here makes the transition invisible: a dismissed finding stays dismissed.
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, kind, sources FROM snapshot_findings")).fetchall()

    for row_id, kind, sources in rows:
        parsed = sources if isinstance(sources, list) else json.loads(sources or "[]")
        connection.execute(
            sa.text("UPDATE snapshot_findings SET kind = :kind, finding_key = :key WHERE id = :id"),
            {
                "kind": _normalised_kind(kind or ""),
                "key": _finding_key(kind or "", parsed),
                "id": row_id,
            },
        )


def downgrade() -> None:
    # The raw slugs are not recoverable — they were overwritten by the normalised ones, deliberately,
    # since keeping a category the dedupe does not use is what this closes. A downgrade leaves the
    # normalised values in place; the code that reads them tolerates either.
    pass
