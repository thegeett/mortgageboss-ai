"""Word positions for a page that has none (LP-708).

The module supplies POSITIONS, not readings — Claude already reads scans well, and
these tests are about rectangles rather than transcription accuracy. A test that
asserted what Tesseract read would be testing the wrong thing and would be brittle
for it.
"""

from __future__ import annotations

import pymupdf
import pytest
from app.services.page_ocr import (
    MAX_DPI,
    MAX_OCR_PAGES_PER_REQUEST,
    MIN_DPI,
    NATIVE_WORD_THRESHOLD,
    TARGET_EDGE_PX,
    dpi_for,
    has_native_words,
    ocr_available,
    ocr_words,
    words_for,
)


def _page(text_lines: list[str], width: float = 612, height: float = 792) -> pymupdf.Page:
    doc = pymupdf.open()
    page = doc.new_page(width=width, height=height)
    for i, line in enumerate(text_lines):
        page.insert_text((72, 100 + i * 20), line)
    return page


def _scanned_page(width: float = 612, height: float = 792) -> pymupdf.Page:
    """A page whose text is PIXELS — the real subject of this module.

    Built by rendering typed text to an image and putting the image on a blank
    page, which is what a photocopy is. `get_text("words")` returns nothing for it.
    """
    source = pymupdf.open()
    typed = source.new_page(width=width, height=height)
    typed.insert_text((72, 120), "GROSS PAY 4,200.00", fontsize=28)
    typed.insert_text((72, 200), "EMPLOYER NORTHWIND", fontsize=28)
    png = typed.get_pixmap(dpi=200).tobytes("png")
    source.close()

    doc = pymupdf.open()
    page = doc.new_page(width=width, height=height)
    page.insert_image(pymupdf.Rect(0, 0, width, height), stream=png)
    return page


class TestTheDpiIsChosenFromThePageSize:
    """MEASURED in both directions, because a fixed dpi fails at both ends.

    On a normal 612x1008 page the raster size IS the quality: 2996px found 103
    words and every anchor, 1400px found eleven. On an oversized 3331x5221 page a
    fixed 300 dpi rasters to 21,754px and takes 7.5s, while 3118px takes 1.5s and
    finds the same words. So the target is a raster, not a dpi — the same argument
    `MAX_RENDERED_EDGE` rests on, and for the same reason: a dpi is a multiplier
    and the page it multiplies is unbounded.
    """

    def test_a_letter_page_gets_a_readable_raster(self) -> None:
        dpi = dpi_for(pymupdf.Rect(0, 0, 612, 792))
        assert 792 * dpi / 72 == pytest.approx(TARGET_EDGE_PX, rel=0.02)

    def test_an_oversized_page_is_not_rastered_to_twenty_thousand_pixels(self) -> None:
        # The 3331x5221 survey page. A fixed 300 dpi would be 21,754px.
        dpi = dpi_for(pymupdf.Rect(0, 0, 3331, 5221))
        assert dpi == MIN_DPI
        assert 5221 * dpi / 72 < 6000

    def test_a_tiny_page_does_not_ask_for_an_absurd_dpi(self) -> None:
        assert dpi_for(pymupdf.Rect(0, 0, 20, 20)) == MAX_DPI

    def test_a_degenerate_page_does_not_divide_by_zero(self) -> None:
        assert dpi_for(pymupdf.Rect(0, 0, 0, 0)) == MIN_DPI

    @pytest.mark.parametrize(
        "rect",
        [
            pymupdf.Rect(0, 0, 612, 792),
            pymupdf.Rect(0, 0, 3331, 5221),
            pymupdf.Rect(0, 0, 20, 20),
            pymupdf.Rect(0, 0, 0, 0),
        ],
    )
    def test_the_dpi_always_lands_in_tesseracts_usable_range(self, rect: pymupdf.Rect) -> None:
        # Below ~70 Tesseract substitutes its own value silently ("Invalid
        # resolution 43 dpi. Using 70 instead"), so a number under the floor is not
        # an error anyone would see — it is a number that does not mean what it says.
        assert MIN_DPI <= dpi_for(rect) <= MAX_DPI


class TestWhichPagesAreOcrd:
    def test_a_typed_page_is_not(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """OCR is never REACHED for a page that has its own text.

        Asserted by making the call explode rather than by comparing the words
        afterwards — a first version compared word TEXT, and Tesseract reads a
        clean typed page accurately enough to produce the same strings, so the
        comparison passed with the shortcut deleted. What is lost when OCR runs on
        a typed page is not the text, it is the EXACTNESS of the rectangles.
        """

        def _must_not_run(*_a: object, **_k: object) -> object:
            raise AssertionError("a typed page was sent to OCR")

        monkeypatch.setattr("app.services.page_ocr.ocr_words", _must_not_run)
        page = _page(["Gross pay 4,200.00", "Employer Northwind Trading Company"])
        assert has_native_words(page) is True
        assert words_for(page) == [
            (float(w[0]), float(w[1]), float(w[2]), float(w[3]), str(w[4]))
            for w in page.get_text("words")
        ]

    def test_a_page_with_no_text_at_all_has_no_native_words(self) -> None:
        page = _scanned_page()
        assert page.get_text("words") == []
        assert has_native_words(page) is False

    @pytest.mark.skipif(not ocr_available(), reason="Tesseract is not installed here")
    def test_a_scanned_page_gets_words_with_rectangles(self) -> None:
        page = _scanned_page()
        words = words_for(page)
        assert words, "OCR produced nothing for a page that plainly has text on it"
        # POSITIONS are the point, not the transcription. Every rectangle must sit
        # inside the page, or the coordinate space is wrong and every box drawn
        # from it will be too.
        for x0, y0, x1, y1, _text in words:
            assert 0 <= x0 < x1 <= page.rect.width + 1
            assert 0 <= y0 < y1 <= page.rect.height + 1

    @pytest.mark.skipif(not ocr_available(), reason="Tesseract is not installed here")
    def test_the_rectangles_are_in_POINT_space_not_pixels(self) -> None:
        """The conversion that would be silently wrong if PyMuPDF did not do it.

        OCR reads a raster measured in pixels; a box is placed in page points. Get
        that wrong by the dpi factor and every box lands at a multiple of its
        correct offset — no error, no exception, just a wrong overlay. This asserts
        the words land in the page's own space, which is what makes the conversion
        PyMuPDF's problem rather than ours.
        """
        page = _scanned_page(width=612, height=792)
        words = words_for(page)
        assert words
        widest = max(w[2] for w in words)
        # At 200 dpi the raster is ~1700px wide. If these were pixels, the widest
        # word would be far outside a 612pt page.
        assert widest <= 612


class TestNativeWordsAreNeverDiscarded:
    """The bug this class exists for was written, caught by a test, and removed.

    The first version returned OCR whenever the native count was under the
    threshold — so a page holding three real words was rasterised and re-read,
    throwing away three EXACT rectangles for however many estimates Tesseract
    produced. The threshold decides whether a page LOOKS like a scan; it does not
    get to decide that a page's own text is worthless.
    """

    def test_a_sparse_but_genuine_page_keeps_its_own_RECTANGLES(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The rectangles, not the words, and the distinction is the whole test.

        Tesseract reads `15 000,00` off this page correctly, so a comparison of
        word TEXT passes whether the native list was kept or replaced — the first
        version of this test did exactly that and survived the mutation. The
        native rectangles are exact and OCR's are estimates, so a replacement is
        detectable only in the geometry.
        """
        page = _page(["15 000,00"])  # two words, under the threshold
        native = [
            (float(w[0]), float(w[1]), float(w[2]), float(w[3]), str(w[4]))
            for w in page.get_text("words")
        ]
        assert 0 < len(native) < NATIVE_WORD_THRESHOLD

        # OCR that returns MORE words, at positions of its own. Without the rule,
        # these replace two exact rectangles with three invented ones.
        monkeypatch.setattr(
            "app.services.page_ocr.ocr_words",
            lambda _page: [
                (1.0, 2.0, 3.0, 4.0, "15"),
                (5.0, 6.0, 7.0, 8.0, "000"),
                (9.0, 10.0, 11.0, 12.0, "00"),
            ],
        )
        assert words_for(page) == native

    def test_ocr_IS_used_when_the_page_really_has_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The positive control for the rule above. Without it, "never discard
        # native words" could be implemented as "never OCR anything" and every
        # assertion in this class would still pass.
        recognised = [(float(i), 2.0, float(i) + 1, 4.0, f"word{i}") for i in range(6)]
        monkeypatch.setattr("app.services.page_ocr.ocr_words", lambda _page: recognised)
        doc = pymupdf.open()
        page = doc.new_page(width=612, height=792)
        assert words_for(page) == recognised

    def test_a_blank_page_yields_nothing_rather_than_failing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("app.services.page_ocr.ocr_words", lambda _page: [])
        doc = pymupdf.open()
        page = doc.new_page(width=612, height=792)
        assert words_for(page) == []


class TestItDegradesRatherThanCrashing:
    """Tesseract is a system package and may simply be absent.

    A container built without it, a developer's machine, a base image change. The
    resulting state — a page with no words — is the state before this ticket and is
    handled everywhere downstream.
    """

    def test_no_ocr_available_means_no_words_not_an_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("app.services.page_ocr.ocr_available", lambda: False)
        page = _scanned_page()
        assert words_for(page) == []

    def test_an_ocr_failure_is_swallowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("app.services.page_ocr.ocr_available", lambda: True)

        def _boom(*_args: object, **_kwargs: object) -> object:
            raise RuntimeError("tesseract exploded")

        monkeypatch.setattr(pymupdf.Page, "get_textpage_ocr", _boom, raising=False)
        page = _scanned_page()
        assert words_for(page) == []


class TestTheRectanglesAreWhereTheWordsActuallyARE:
    """Bounded, non-degenerate and in point space — and still possibly wrong.

    THE ASSERTION THE SUITE WAS MISSING. Every existing check on these rectangles
    is a BOUND: inside the page, non-zero area, small enough not to be pixels. All
    three hold for a rectangle at the origin, so collapsing every OCR word to
    (0, 0) — a box drawn in the top-left corner for every field on every scanned
    page — passed the entire suite. Verified by making exactly that change.

    A position needs a positional assertion, and the only ground truth available is
    a page whose words have KNOWN rectangles: OCR a page that also has a text
    layer and the two must agree.
    """

    @staticmethod
    def _known_page() -> pymupdf.Page:
        doc = pymupdf.open()
        page = doc.new_page(width=612, height=792)
        # Distinct words at spread-out positions, so a rectangle cannot land near
        # the right place by accident.
        page.insert_text((72, 100), "Alpha", fontsize=14)
        page.insert_text((400, 300), "Bravo", fontsize=14)
        page.insert_text((72, 700), "Charlie", fontsize=14)
        return doc[0]

    def test_each_ocr_rectangle_lands_on_its_own_word(self) -> None:
        page = self._known_page()
        native = {w[4]: w[:4] for w in page.get_text("words")}
        assert len(native) == 3, "the fixture must have three distinct native words"

        recognised = {w[4]: w[:4] for w in ocr_words(page)}
        for word, (nx0, ny0, _nx1, _ny1) in native.items():
            assert word in recognised, f"OCR did not read {word!r}"
            ox0, oy0, _ox1, _oy1 = recognised[word]
            # Measured agreement on this fixture is ~1pt across and ~5pt down (the
            # glyph box against the text baseline). 20pt is loose enough to survive
            # a font or Tesseract version change and far tighter than the ~300pt an
            # origin collapse or an axis swap would produce.
            assert abs(ox0 - nx0) < 20, f"{word}: x is {ox0:.0f}, the word is at {nx0:.0f}"
            assert abs(oy0 - ny0) < 20, f"{word}: y is {oy0:.0f}, the word is at {ny0:.0f}"

    def test_the_words_are_not_all_in_one_place(self) -> None:
        # The cheap control, in case a future fixture loses its spread: three words
        # at three corners must produce three distinct rectangles.
        corners = {(round(w[0]), round(w[1])) for w in ocr_words(self._known_page())}
        assert len(corners) == 3


class TestAPageWithNothingToProtect:
    """OCR is refused only where there are exact rectangles to lose.

    The rule required OCR to reach `NATIVE_WORD_THRESHOLD` before it could be
    used at all — including on a page with NO words of its own, where there was no
    exact geometry at stake. A scan whose only legible text is a three-word header
    therefore returned nothing, guarding rectangles that did not exist.

    The guard was scoped by its symptom (a word count) rather than by what it
    guards, which is the shape that makes a guard refuse the case it was written
    for.
    """

    def test_a_page_with_no_words_takes_whatever_ocr_finds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        page = _page([])  # nothing at all
        assert page.get_text("words") == []
        few = [(1.0, 2.0, 3.0, 4.0, "Total"), (5.0, 6.0, 7.0, 8.0, "1,234.00")]
        assert len(few) < NATIVE_WORD_THRESHOLD
        monkeypatch.setattr("app.services.page_ocr.ocr_words", lambda _page: few)
        assert words_for(page) == few

    def test_a_page_WITH_words_still_refuses_a_thin_reading(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The control, and the case the threshold exists for: where exact
        # rectangles DO exist, a slightly luckier reading of the same page must not
        # replace them.
        page = _page(["15 000,00"])
        native = [
            (float(w[0]), float(w[1]), float(w[2]), float(w[3]), str(w[4]))
            for w in page.get_text("words")
        ]
        assert 0 < len(native) < NATIVE_WORD_THRESHOLD
        monkeypatch.setattr(
            "app.services.page_ocr.ocr_words",
            lambda _page: [(1.0, 2.0, 3.0, 4.0, "15"), (5.0, 6.0, 7.0, 8.0, "000,00")],
        )
        assert words_for(page) == native


class TestTheRequestHasAnOcrBudget:
    """OCR runs inside the request, and the client gives up at 30 seconds.

    Measured at ~0.74s for a dense letter page here and ~0.98s elsewhere, so a
    30-page scanned bank statement is 22-30s of one thread — the processor sees no
    boxes at all, and nothing is cached across requests, so the next viewer pays it
    again. Nothing bounded it.
    """

    def test_the_budget_stops_further_pages_being_ocrd(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = {"n": 0}

        def _counted(_page: object) -> list[tuple[float, float, float, float, str]]:
            calls["n"] += 1
            return [(1.0, 2.0, 3.0, 4.0, "word")]

        monkeypatch.setattr("app.services.page_ocr.ocr_words", _counted)
        budget = [2]
        blank = _page([])
        for _ in range(5):
            words_for(blank, budget)
        assert calls["n"] == 2, "OCR ran past the budget"

    def test_a_page_with_a_text_layer_costs_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The control, and the reason the budget is spent where the raster happens
        # rather than per page visited: a typed page never reaches OCR, so it must
        # not consume a page of the allowance.
        monkeypatch.setattr(
            "app.services.page_ocr.ocr_words", lambda _p: [(1.0, 2.0, 3.0, 4.0, "x")]
        )
        budget = [1]
        typed = _page(["Alpha Bravo Charlie Delta Echo Foxtrot"])
        assert has_native_words(typed)
        for _ in range(3):
            words_for(typed, budget)
        assert budget[0] == 1

    def test_the_cap_clears_the_worst_document_in_the_corpus(self) -> None:
        # 12 is chosen from the corpus, not picked: the most pages any stored
        # document needs OCR'd is 9. This pins the relationship so a later
        # reduction has to argue with the measurement.
        assert MAX_OCR_PAGES_PER_REQUEST >= 9
