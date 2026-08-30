"""Locating a field's value on the page (LP-UI-031).

The measured backdrop, over 105 stored PDFs / 752 valued fields: a box is
absent for roughly a quarter of them — 11.8% whose snippet is not in the text
layer, 11.0% on scans, 4.3% citing a page the document does not have. So the
no-box path is ordinary, and these tests treat it as a result rather than an
error case.
"""

import pymupdf
import pytest
from app.services.field_boxes import MAX_MATCHES, find_all_field_boxes, find_field_boxes


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
                "gross_pay": ("Gross pay 4,200.00", 1),
                "employer": ("Employer Northwind Trading", 2),
                "cited_wrong": ("Employer Northwind Trading", 1),
                "absent": ("nothing like this", 1),
                "fabricated": ("Gross pay 4,200.00", 9),
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
