"""The schema specs (LP-434) — one JSON file per document type, describing that type's extraction
schema. THE SOURCE OF TRUTH for what each extractor captures: the generator emits extractors from
these, and the distrusted-field list validates its entries against them.

They live inside the package rather than under the repo's ``docs/`` because the backend image is
built with ``backend/`` as its build context — a repo-root ``docs/`` is not in the context and never
reached the image. The rule engine reads them at RUNTIME (``app.verification.rules.distrust``), so
"documentation that ships nowhere" was a fail-closed crash on every containerised run.

``SPECS_DIR`` is the ONE place the location is written down. Import it rather than recomputing a
``parents[N]`` walk: that walk is what broke, because the number of levels between a module and the
repo root differs from the number between that module and the package root, and only the second is
the same in the repo and in the image.
"""

from pathlib import Path

#: Absolute path to the directory holding ``NNN-<slug>.json`` (plus the ``_*.md`` authoring guides).
SPECS_DIR = Path(__file__).resolve().parent

__all__ = ["SPECS_DIR"]
