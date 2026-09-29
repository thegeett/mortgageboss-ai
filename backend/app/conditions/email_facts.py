"""The facts in a condition email, and what an AI polish did to them (LP-922 follow-up).

CODE, NOT A MODEL, DECIDES WHETHER A FACT SURVIVED. The product owner's rule (2026-09-29): a polish that
changes or drops a fact is shown with a warning and she decides. So this reads the facts out of both
versions — amounts, dates, account endings and loan numbers, links, the numbered items — and names every
one that went missing or appeared. Asking a model whether a model changed a figure has the same failure
mode as the thing being checked.

PURE: text in, warnings out, so a test can state both versions and read the result.
"""

from __future__ import annotations

import calendar
import html
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

_MONEY = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})*|\d+)(?:\.(\d{2}))?")
_NUMERIC_DATE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b")
_MONTHS = [name for name in calendar.month_name if name]
_DAYS = [name for name in calendar.day_name if name]
_SPOKEN_DATE = re.compile(
    rf"\b(?:(?:{'|'.join(_DAYS)}),\s*)?({'|'.join(_MONTHS)})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b"
)
_DIGITS = re.compile(r"(?<![\d,.$/])\d{4,}(?![\d,/])")
_HREF = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)
_ITEM = re.compile(r"<li[\s>]", re.I)
_DATE_WORDS = frozenset(
    word.lower() for group in (calendar.day_name, calendar.month_name) for word in group if word
)


def plain(body_html: str) -> str:
    """The body as a reader sees it: tags gone, entities decoded, whitespace collapsed."""
    spaced = re.sub(r"<(?:br|/p|/li|li)\b[^>]*>", " ", body_html or "", flags=re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", spaced))).strip()


def _money(text: str) -> dict[Decimal, str]:
    """Amounts by VALUE, so "$2,850" and "$2,850.00" are one fact; the value maps to how it was written."""
    found: dict[Decimal, str] = {}
    for match in _MONEY.finditer(text):
        try:
            value = Decimal(f"{match.group(1).replace(',', '')}.{match.group(2) or '00'}")
        except InvalidOperation:
            continue
        found.setdefault(value, match.group(0).replace(" ", ""))
    return found


def _money_order(text: str) -> list[Decimal]:
    """The amounts in the order a reader meets them, for the re-attribution check below."""
    values: list[Decimal] = []
    for match in _MONEY.finditer(text):
        try:
            values.append(Decimal(f"{match.group(1).replace(',', '')}.{match.group(2) or '00'}"))
        except InvalidOperation:
            continue
    return values


def _dates(text: str) -> dict[str, str]:
    """Dates by what they mean: `09/03/2026`, and "Thursday, September 3" as `September 3`."""
    found = {match.group(0): match.group(0) for match in _NUMERIC_DATE.finditer(text)}
    for match in _SPOKEN_DATE.finditer(text):
        found.setdefault(f"{match.group(1)} {int(match.group(2))}", match.group(0))
    return found


def _digit_runs(text: str) -> set[str]:
    """Account endings and loan numbers: runs of four or more digits that are not part of an amount
    or a date (those are their own facts above)."""
    # THE PATTERN'S LOOKAROUNDS DO THE EXCLUDING: a run after "$", ",", "." or "/" belongs to an
    # amount or a date, which are compared as facts of their own.
    return set(_DIGITS.findall(text))


@dataclass(frozen=True)
class FactWarning:
    """One fact the polish changed. `kind` is dropped / added / items; `fact` is as written."""

    kind: Literal["dropped", "added", "items"]
    fact: str

    @property
    def sentence(self) -> str:
        if self.kind == "dropped":
            return f"Dropped: {self.fact}"
        if self.kind == "added":
            return f"Added: {self.fact}"
        return self.fact


def fact_warnings(before_html: str, after_html: str) -> list[FactWarning]:
    """Every fact the polished version dropped or added, in a stable order. Empty when all survived."""
    before, after = plain(before_html), plain(after_html)
    warnings: list[FactWarning] = []

    money_before, money_after = _money(before), _money(after)
    warnings += [
        FactWarning("dropped", money_before[v]) for v in money_before if v not in money_after
    ]
    warnings += [FactWarning("added", money_after[v]) for v in money_after if v not in money_before]

    dates_before, dates_after = _dates(before), _dates(after)
    warnings += [
        FactWarning("dropped", dates_before[k]) for k in dates_before if k not in dates_after
    ]
    warnings += [FactWarning("added", dates_after[k]) for k in dates_after if k not in dates_before]

    runs_before, runs_after = _digit_runs(before), _digit_runs(after)
    warnings += [FactWarning("dropped", run) for run in sorted(runs_before - runs_after)]
    warnings += [FactWarning("added", run) for run in sorted(runs_after - runs_before)]

    links_before = set(_HREF.findall(before_html or ""))
    links_after = set(_HREF.findall(after_html or ""))
    warnings += [FactWarning("dropped", "the upload link") for _ in links_before - links_after]
    warnings += [
        FactWarning("added", f"a link to {link}") for link in sorted(links_after - links_before)
    ]

    # "by Friday" has no digits: a day or month word the original did not use is a new commitment.
    words_before = {w for w in _DATE_WORDS if re.search(rf"\b{w}\b", before, re.I)}
    new_words = sorted(
        w for w in _DATE_WORDS if w not in words_before and re.search(rf"\b{w}\b", after, re.I)
    )
    warnings += [FactWarning("added", word.capitalize()) for word in new_words]

    # THE SAME AMOUNTS IN A DIFFERENT ORDER ARE NOT THE SAME EMAIL (LP-922 follow-up review). Every
    # comparison above is by SET, so a polish that keeps both figures and swaps what each one MEANS
    # passes them all: "$38,210.40 is required and $11,062.18 is verified" reversed still holds both
    # values, and the borrower is told the opposite of the truth with nothing shown. Order is the
    # cheapest evidence of re-attribution that does not need the sentence parsed. Only when the sets
    # match, because a genuine change already warns above and saying it twice buries it.
    order_before, order_after = _money_order(before), _money_order(after)
    if set(order_before) == set(order_after) and order_before != order_after:
        warnings.append(
            FactWarning(
                "items",
                "The amounts are in a different order: "
                + " then ".join(money_before[v] for v in order_before)
                + " became "
                + " then ".join(money_after[v] for v in order_after)
                + ". Check each one is still attached to the right thing.",
            )
        )

    items_before = len(_ITEM.findall(before_html or ""))
    items_after = len(_ITEM.findall(after_html or ""))
    if items_before != items_after:
        warnings.append(
            FactWarning(
                "items",
                f"The list had {items_before} item{'s' if items_before != 1 else ''}; "
                f"the AI's has {items_after}.",
            )
        )
    return warnings
