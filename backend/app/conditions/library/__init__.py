"""The condition library v1 (LP-918): what each kind of condition asks for, as reviewed data.

`types.yaml` is the data; `loader.load_library()` validates it once and caches it. The library decides
the plan wherever it knows the condition (plan principle 5, "the library beats the AI").
"""

from app.conditions.library.loader import (
    ConditionType,
    Library,
    LibraryError,
    LibraryItem,
    TypeCategory,
    TypeRule,
    load_library,
)

__all__ = [
    "ConditionType",
    "Library",
    "LibraryError",
    "LibraryItem",
    "TypeCategory",
    "TypeRule",
    "load_library",
]
