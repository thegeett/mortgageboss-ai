"""Locating a field's value on the page (LP-UI-031).

The measured backdrop, over 105 stored PDFs / 752 valued fields: a box is
absent for roughly a quarter of them — 11.8% whose snippet is not in the text
layer, 11.0% on scans, 4.3% citing a page the document does not have. So the
no-box path is ordinary, and these tests treat it as a result rather than an
error case.
"""

import pymupdf
import pytest
from app.services.field_boxes import (
    MAX_MATCHES,
    BoxRequest,
    MatchKind,
    find_all_field_boxes,
    find_field_boxes,
    fold,
)


def _pdf(pages: list[str], width: float = 612, height: float = 792) -> bytes:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page(width=width, height=height)
        page.insert_text((72, 100), text)
    return bytes(doc.tobytes())


class TestFindingTheBox:
    async def test_finds_the_snippet_on_the_cited_page(self) -> None:
        result = await find_field_boxes(
            _pdf(["Gross pay 4,812.55"]), snippet="Gross pay 4,812.55", cited_page=1
        )
        assert len(result.boxes) == 1
        assert result.cited_page_exists is True
        assert result.found_elsewhere is False

    async def test_the_box_is_normalised_to_the_page(self) -> None:
        # 0..1 against the page box, so a client can overlay it on an image
        # rendered at any zoom without knowing which zoom that was.
        result = await find_field_boxes(_pdf(["Gross pay"]), snippet="Gross pay", cited_page=1)
        box = result.boxes[0]
        assert 0.0 <= box.x0 < box.x1 <= 1.0
        assert 0.0 <= box.y0 < box.y1 <= 1.0

    async def test_a_snippet_that_is_not_there_yields_no_box(self) -> None:
        # 11.8% of real fields. Absent, not an error.
        result = await find_field_boxes(
            _pdf(["Gross pay"]), snippet="Employer address", cited_page=1
        )
        assert result.boxes == ()
        assert result.cited_page_exists is True

    async def test_a_scan_with_no_text_layer_yields_no_box(self) -> None:
        # 11.0% of real fields — a page with no extractable text.
        blank = pymupdf.open()
        blank.new_page(width=612, height=792)
        result = await find_field_boxes(
            bytes(blank.tobytes()), snippet="anything at all", cited_page=1
        )
        assert result.boxes == ()

    async def test_unreadable_bytes_yield_no_box(self) -> None:
        result = await find_field_boxes(b"not a pdf", snippet="x", cited_page=1)
        assert result.boxes == ()


class TestAFabricatedCitation:
    """4.3% of real fields cite a page the document does not have.

    Measured, and it is not an off-by-one: NOT ONE field cites a
    wrong-but-existing page. Every one names a page beyond the document's length
    — "p.7" of a three-page letter. So there is no cited page to render, and
    searching the rest is the only way to show the processor anything.
    """

    async def test_finds_the_text_and_says_the_citation_was_wrong(self) -> None:
        result = await find_field_boxes(
            _pdf(["first page", "Gross pay 4,812.55"]),
            snippet="Gross pay 4,812.55",
            cited_page=7,
        )
        assert len(result.boxes) == 1
        assert result.boxes[0].page == 2
        # THE POINT: it does not quietly substitute a better page. Correcting the
        # model silently is how a provenance trail stops being one.
        assert result.cited_page_exists is False
        assert result.found_elsewhere is True

    async def test_a_real_page_that_simply_does_not_hold_the_text(self) -> None:
        # The other shape: the citation is in range, the text is on another page.
        result = await find_field_boxes(
            _pdf(["first page", "Gross pay 4,812.55"]),
            snippet="Gross pay 4,812.55",
            cited_page=1,
        )
        assert result.boxes[0].page == 2
        assert result.cited_page_exists is True
        assert result.found_elsewhere is True

    async def test_a_bad_citation_with_no_text_anywhere_is_still_flagged(self) -> None:
        result = await find_field_boxes(
            _pdf(["first page"]), snippet="nowhere at all", cited_page=9
        )
        assert result.boxes == ()
        assert result.cited_page_exists is False


class TestNotIdentifyingAnything:
    async def test_a_snippet_matching_everywhere_yields_no_box(self) -> None:
        # A bare "Total" appears forty times on a bank statement. Painting the
        # page and calling it provenance is worse than showing none.
        many = _pdf([" ".join(["Total"] * (MAX_MATCHES + 4))])
        result = await find_field_boxes(many, snippet="Total", cited_page=1)
        assert result.boxes == ()

    async def test_a_handful_of_matches_is_still_useful(self) -> None:
        few = _pdf(["Total Total"])
        result = await find_field_boxes(few, snippet="Total", cited_page=1)
        assert len(result.boxes) == 2

    @pytest.mark.parametrize("snippet", ["", "   "])
    async def test_an_empty_snippet_is_not_a_search(self, snippet: str) -> None:
        result = await find_field_boxes(_pdf(["anything"]), snippet=snippet, cited_page=1)
        assert result.boxes == ()


class TestManyFieldsAtOnce:
    """The batch path, which is the one the endpoint actually uses."""

    async def test_each_field_keeps_its_own_answer(self) -> None:
        content = _pdf(["Gross pay 4,200.00", "Employer Northwind Trading"])
        found = await find_all_field_boxes(
            content,
            {
                "gross_pay": BoxRequest("Gross pay 4,200.00", "4200.00", 1),
                "employer": BoxRequest("Employer Northwind Trading", "Northwind Trading", 2),
                "cited_wrong": BoxRequest("Employer Northwind Trading", "Northwind Trading", 1),
                "absent": BoxRequest("nothing like this", "nothing like this", 1),
                "fabricated": BoxRequest("Gross pay 4,200.00", "4200.00", 9),
            },
        )
        # Found where it was cited.
        assert found["gross_pay"].boxes and found["gross_pay"].found_elsewhere is False
        assert found["employer"].boxes and found["employer"].found_elsewhere is False
        # Cited page 1, the text is on page 2 — shown, and flagged as relocated.
        assert found["cited_wrong"].found_elsewhere is True
        assert found["cited_wrong"].boxes[0].page == 2
        # Not in the document at all — no box, no false flag.
        assert found["absent"].boxes == ()
        assert found["absent"].cited_page_exists is True
        # A page the document does not have: located elsewhere, citation flagged.
        assert found["fabricated"].cited_page_exists is False
        assert found["fabricated"].found_elsewhere is True

    async def test_a_document_that_will_not_open_answers_every_field(self) -> None:
        # A screen whose job is to show a page must not 500 because one file is
        # unreadable — every field gets an empty answer instead.
        found = await find_all_field_boxes(b"not a pdf", {"a": ("x", 1), "b": ("y", 2)})
        assert set(found) == {"a", "b"}
        assert all(lookup.boxes == () for lookup in found.values())

    async def test_no_fields_is_no_work(self) -> None:
        assert await find_all_field_boxes(_pdf(["anything"]), {}) == {}


# --- LP-706: folding, and LP-709: the guard that ships with it -------------- #


def _table_pdf() -> bytes:
    """A page whose figure is split the way a table splits one, plus a repeat of it."""
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), "Gross  Total")  # doubled space
    page.insert_text((300, 100), "15,000.00")  # the figure, its own text run
    page.insert_text((72, 200), "Net pay 9,706.69")
    page.insert_text((72, 300), "Prior balance 15,000.00")  # the SAME figure again
    return bytes(doc.tobytes())


class TestFolding:
    """LP-706 — the 11.8% whose text IS on the page, written differently."""

    async def test_whitespace_was_never_the_problem(self) -> None:
        """MEASURED, and it corrects this ticket's own first premise.

        `search_for` is already tolerant of doubled spaces, of case, and of text
        split across separate runs — so none of those was ever a cause of a missing
        box. Asserted here so nobody rebuilds folding to solve a problem the exact
        tier had already solved.
        """
        found = await find_field_boxes(
            _table_pdf(), snippet="Gross Total", value="Gross Total", cited_page=1
        )
        assert found.boxes
        assert found.match_kind is MatchKind.EXACT

    async def test_a_thousands_separator_does_not_matter(self) -> None:
        found = await find_field_boxes(
            _table_pdf(), snippet="15000.00", value="15000.00", cited_page=1
        )
        assert found.boxes

    @pytest.mark.parametrize("written", ["15000.00", "$15,000.00", "15 000,00"])
    async def test_notation_IS_what_folding_solves(self, written: str) -> None:
        """What `search_for` genuinely cannot do: the same figure written another way.

        The first assertion is the control. Without it this test would pass for any
        needle the exact tier already handles, and would go on passing if folding
        were deleted.
        """
        doc = pymupdf.open(stream=_table_pdf(), filetype="pdf")
        assert doc[0].search_for(written) == [], f"{written} never reaches the folded tier"
        doc.close()

        found = await find_field_boxes(_table_pdf(), snippet=written, value=written, cited_page=1)
        assert found.boxes
        assert found.match_kind is MatchKind.NORMALISED

    async def test_the_exact_tier_still_runs_first(self) -> None:
        # The guarantee that lets this ship: a box that was correct before LP-706
        # is found by the SAME call it was found by then, and never reaches the
        # folding. If this ever reports NORMALISED, the old path has been lost.
        found = await find_field_boxes(
            _pdf(["Gross pay 4,200.00"]),
            snippet="Gross pay 4,200.00",
            value="4200.00",
            cited_page=1,
        )
        assert found.match_kind is MatchKind.EXACT


class TestTheGuard:
    """LP-709 — folding buys coverage by giving up certainty. This is the price."""

    async def test_a_figure_is_not_found_inside_a_bigger_one(self) -> None:
        """THE FAILURE FOLDING CREATES. `1500` is a substring of `21,500.00` once
        the separators are gone, and an unaligned search would draw a confident box
        over the wrong figure. The match has to start where a word starts and end
        where one ends."""
        doc = pymupdf.open()
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 100), "Subtotal 21,500.00")
        content = bytes(doc.tobytes())

        found = await find_field_boxes(content, snippet="1500", value="1500", cited_page=1)
        assert found.boxes == ()

    async def test_a_very_short_FOLDED_needle_locates_nothing(self) -> None:
        """The floor applies to the folded tiers, and only to them.

        `search_for("15")` already returns two hits inside `15,000.00` — substring
        matching that predates this ticket and is not changed by it. What the floor
        stops is folding making that worse, since folding removes the separators
        that would otherwise break such a run up. The needle here is one the exact
        tier cannot match at all, so only the floor can be what refuses it.
        """
        doc = pymupdf.open(stream=_table_pdf(), filetype="pdf")
        assert doc[0].search_for("net,") == [], "must fail the exact tier to reach the floor"
        doc.close()

        # `net,` folds to `net` — three characters, and it WOULD match the page's
        # own word `Net` at both boundaries. So the floor is the only thing that
        # can refuse it, which is what makes this a test of the floor rather than
        # of the boundary check beside it.
        assert fold("net,") == "net"
        found = await find_field_boxes(_table_pdf(), snippet="net,", value="net,", cited_page=1)
        assert found.boxes == ()

    async def test_the_value_tier_refuses_an_ambiguous_page(self) -> None:
        """The strictest rule, on the weakest tier.

        `15,000.00` appears twice on this page — once as the gross total and once as
        a prior balance. With the quoted text unfindable, nothing distinguishes
        them, and drawing both invites a processor to verify against whichever they
        look at first.
        """
        found = await find_field_boxes(
            _table_pdf(),
            snippet="a quoted line that is nowhere on this page",
            value="15,000.00",
            cited_page=1,
        )
        assert found.boxes == ()

    async def test_the_value_tier_is_used_when_it_is_unambiguous(self) -> None:
        # The positive control for the test above. Same path, same page, a value
        # that appears once — so the refusal above is the ambiguity and not the
        # tier being dead code.
        found = await find_field_boxes(
            _table_pdf(),
            snippet="a quoted line that is nowhere on this page",
            value="9,706.69",
            cited_page=1,
        )
        assert found.boxes
        assert found.match_kind is MatchKind.VALUE

    async def test_the_kind_says_which_claim_the_box_is(self) -> None:
        # A box found by the model's quoted text and a box found by its bare value
        # are different claims. The caller is entitled to tell them apart.
        by_text = await find_field_boxes(
            _table_pdf(), snippet="Net pay 9,706.69", value="9,706.69", cited_page=1
        )
        by_value = await find_field_boxes(
            _table_pdf(), snippet="nowhere on this page at all", value="9,706.69", cited_page=1
        )
        assert by_text.match_kind is MatchKind.EXACT
        assert by_value.match_kind is MatchKind.VALUE

    async def test_no_boxes_means_no_kind(self) -> None:
        found = await find_field_boxes(
            _pdf(["Gross pay"]), snippet="absent", value="absent", cited_page=1
        )
        assert found.boxes == ()
        assert found.match_kind is None


class TestFold:
    """The folding function itself, which every tier above depends on."""

    @pytest.mark.parametrize(
        ("written", "expected"),
        [
            ("Gross Total 15,000.00", "grosstotal1500000"),
            ("15 000,00", "1500000"),
            ("$15,000.00", "1500000"),
            ("  spaced  out  ", "spacedout"),
            ("Caf\u00e9", "cafe"),
            ("\ufb01nal", "final"),  # the ligature a PDF text layer really holds
            ("1/1/2025", "112025"),
            ("", ""),
        ],
    )
    def test_folds_formatting_away(self, written: str, expected: str) -> None:
        assert fold(written) == expected

    def test_two_notations_of_one_figure_fold_alike(self) -> None:
        # The property the whole ticket rests on, asserted as a property rather
        # than as a list of examples.
        assert fold("15,000.00") == fold("15 000,00") == fold("$15,000.00")

    def test_two_different_figures_do_not(self) -> None:
        # The control. Without it, a fold that returned "" for everything would
        # pass every assertion above.
        assert fold("15,000.00") != fold("16,000.00")
        assert fold("Gross") != fold("Net")
