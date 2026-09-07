"""Rendering one PDF page to PNG (LP-UI-030).

Server-side with PyMuPDF, which is already on the production path — and, more to
the point, the same library that will derive a field's highlight rectangle. One
renderer means one coordinate space; two would put the box a few points off, which
is worse than no box because it points confidently at the wrong words.
"""

import pymupdf
import pytest
from app.services.page_render import (
    DEFAULT_ZOOM,
    MAX_RENDERED_EDGE,
    MAX_ZOOM,
    PageImage,
    _bounded_zoom,
    fit_to_budget,
    render_page,
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"


def _pdf(pages: int = 1, width: float = 612, height: float = 792) -> bytes:
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page(width=width, height=height)
        page.insert_text((72, 72), f"page {i + 1}")
    return bytes(doc.tobytes())


class TestRenderingAPage:
    async def test_it_reports_the_document_length(self) -> None:
        # The reviewer needs "of 3" to stop at the last page, and the renderer
        # already has the document open — counting here costs nothing.
        image = await render_page(_pdf(pages=3), page_number=1, mime_type="application/pdf")
        assert image is not None
        assert image.page_count == 3

    async def test_returns_a_png(self) -> None:
        image = await render_page(_pdf(), page_number=1, mime_type="application/pdf")
        assert image is not None
        assert image.content.startswith(PNG_MAGIC)

    async def test_carries_the_page_geometry_in_points(self) -> None:
        # The box space. A caller placing a highlight needs the POINT size the
        # rectangle is expressed in, not just the pixels it received.
        image = await render_page(
            _pdf(width=612, height=792), page_number=1, mime_type="application/pdf"
        )
        assert image is not None
        assert (image.width_points, image.height_points) == (612.0, 792.0)

    async def test_pixels_are_points_times_zoom(self) -> None:
        image = await render_page(
            _pdf(width=612, height=792), page_number=1, zoom=2.0, mime_type="application/pdf"
        )
        assert image is not None
        assert (image.pixel_width, image.pixel_height) == (1224, 1584)

    async def test_renders_the_page_that_was_asked_for(self) -> None:
        # Not page one every time — the reviewer opens a field's cited page.
        first = await render_page(_pdf(pages=3), page_number=1, mime_type="application/pdf")
        third = await render_page(_pdf(pages=3), page_number=3, mime_type="application/pdf")
        assert first is not None and third is not None
        assert first.content != third.content

    @pytest.mark.parametrize("page_number", [0, -1, 4])
    async def test_a_page_the_document_does_not_have_is_absent(self, page_number: int) -> None:
        # Measured on real data: a model-cited page is out of range on ~4% of
        # extracted fields. That is a designed no-page state, never a 500.
        assert (
            await render_page(_pdf(pages=3), page_number=page_number, mime_type="application/pdf")
            is None
        )

    async def test_unreadable_bytes_are_absent_not_an_exception(self) -> None:
        assert (
            await render_page(b"not a pdf at all", page_number=1, mime_type="application/pdf")
            is None
        )

    async def test_zoom_is_capped(self) -> None:
        # Caps the MULTIPLIER. What caps the RESULT is `MAX_RENDERED_EDGE`, and a
        # small page is used here so only one of the two is being measured — a US
        # Letter page at 4x is 3168px and the render budget takes it first.
        image = await render_page(
            _pdf(width=100, height=100), page_number=1, zoom=99.0, mime_type="application/pdf"
        )
        assert image is not None
        assert image.zoom == MAX_ZOOM

    async def test_zoom_has_a_floor(self) -> None:
        image = await render_page(_pdf(), page_number=1, zoom=0.0, mime_type="application/pdf")
        assert image is not None
        assert image.zoom >= 1.0

    async def test_the_geometry_is_the_pages_own_not_the_zoomed_one(self) -> None:
        # The trap this guards: reporting pixel dimensions as points would put
        # every derived rectangle off by the zoom factor.
        a = await render_page(
            _pdf(width=612, height=792), page_number=1, zoom=1.0, mime_type="application/pdf"
        )
        b = await render_page(
            _pdf(width=612, height=792), page_number=1, zoom=3.0, mime_type="application/pdf"
        )
        assert a is not None and b is not None
        assert a.width_points == b.width_points == 612.0
        assert b.pixel_width == 3 * a.pixel_width

    def test_a_page_image_knows_its_pixel_size(self) -> None:
        image = PageImage(
            content=b"",
            media_type="image/png",
            width_points=100.0,
            height_points=50.0,
            zoom=2.0,
            page_count=1,
        )
        assert (image.pixel_width, image.pixel_height) == (200, 100)


def _image(fmt: str, width: float = 400, height: float = 300) -> bytes:
    """A JPEG or PNG, the way an upload arrives — a photograph, not a PDF."""
    doc = pymupdf.open()
    page = doc.new_page(width=width, height=height)
    page.insert_text((20, 40), "photographed pay stub")
    data: bytes = page.get_pixmap().tobytes(fmt)  # type: ignore[no-untyped-call]
    doc.close()
    return data


class TestImagesRender:
    """Uploads accept JPEG and PNG; this endpoint refused them (LP-704).

    `ALLOWED_CONTENT_TYPES` has taken image/jpeg and image/png since LP-36, so a
    photographed pay stub uploaded successfully and then showed the reviewer's
    no-page state permanently — a missing capability that reads as "still
    loading, for ever" rather than "cannot show this".
    """

    @pytest.mark.parametrize(("fmt", "mime"), [("png", "image/png"), ("jpg", "image/jpeg")])
    async def test_an_image_renders(self, fmt: str, mime: str) -> None:
        image = await render_page(_image(fmt), page_number=1, mime_type=mime)
        assert image is not None
        # THE SOURCE DECIDES THE ENCODING. A photograph re-encoded as PNG ships
        # more bytes than the file it previews — measured at 4.72 MB against a
        # 4.26 MB source — so an image source comes back as JPEG and a PDF page
        # as PNG.
        assert image.media_type == ("image/jpeg" if mime == "image/jpeg" else "image/png")
        assert image.content.startswith(JPEG_MAGIC if mime == "image/jpeg" else PNG_MAGIC)

    @pytest.mark.parametrize(("fmt", "mime"), [("png", "image/png"), ("jpg", "image/jpeg")])
    async def test_an_image_is_one_page(self, fmt: str, mime: str) -> None:
        # So the reviewer says "Page 1 of 1" and offers no Next that renders
        # nothing — the same contract a PDF has.
        image = await render_page(_image(fmt), page_number=1, mime_type=mime)
        assert image is not None
        assert image.page_count == 1

    async def test_an_images_points_are_its_pixels_at_96dpi(self) -> None:
        """An image's page rect is its pixels x 0.75, not its pixels.

        MEASURED, because the obvious guess is wrong: MuPDF reads an image at 96
        DPI and reports the page in 72-dpi points, so a 400 x 300 px image is a
        300 x 225 pt page. A caller placing a normalised box is unaffected — the
        ratio is what it uses — but anyone reading `width_points` as "pixels"
        would be off by a third on every image.
        """
        image = await render_page(
            _image("png", width=400, height=300), page_number=1, mime_type="image/png"
        )
        assert image is not None
        assert (image.width_points, image.height_points) == (300.0, 225.0)

    async def test_asking_an_image_for_page_two_is_absent(self) -> None:
        image = await render_page(_image("png"), page_number=2, mime_type="image/png")
        assert image is None

    async def test_a_type_the_renderer_cannot_open_is_absent(self) -> None:
        # Not an exception and not a special error: the caller has ONE no-page
        # state and does not need a second way to say the same thing.
        assert await render_page(_pdf(), page_number=1, mime_type="text/plain") is None
        assert await render_page(_pdf(), page_number=1, mime_type="") is None

    async def test_the_bytes_decide_the_reader_not_the_declared_type(self) -> None:
        """MuPDF SNIFFS. The `filetype` hint does not select a parser.

        Measured: PDF bytes open under filetype "png", "jpg" and even "xps", all
        returning the real page. So `RENDERABLE_TYPES` is an allow-list of what
        this endpoint is willing to serve, NOT a parser selector — and a document
        whose stored mime type disagrees with its bytes renders from its bytes.

        That is the safe direction (upload validation sniffs content too, so the
        stored type already comes from the bytes), but it has to be written down:
        a future reader could otherwise assume the hint is load-bearing and build
        a check on top of it that enforces nothing.
        """
        image = await render_page(_pdf(), page_number=1, mime_type="image/png")
        assert image is not None
        assert image.page_count == 1


class TestTheRenderBudget:
    """A cap on the RESULT, which the zoom cap never was (LP-704).

    Measured on a stored document rather than reasoned: one 25 MB survey is a
    single page of 4047 x 4998 points — 56 by 69 inches. At the default 2x the
    endpoint returned 69.3 MB in 4.9 s, and at 1x it still returned 23.4 MB.
    `MAX_ZOOM = 4.0` never applied, because 2.0 is already under it.
    """

    def test_an_ordinary_page_is_left_alone(self) -> None:
        # US Letter at the default 2x is 1224 x 1584. If the budget touched this,
        # it would be re-rendering every page in the corpus to no purpose.
        assert fit_to_budget(2.0, 612, 792) == 2.0

    def test_a_huge_page_is_scaled_to_the_budget(self) -> None:
        applied = fit_to_budget(2.0, 4047, 4998)
        assert max(4047, 4998) * applied == pytest.approx(MAX_RENDERED_EDGE)

    def test_it_goes_below_1x_when_the_page_needs_it(self) -> None:
        # THE POINT OF THE WHOLE THING. `render_page` floors a caller's zoom at
        # 1.0, and a 4998pt page at 1x is still 23 MB. A floor applied after the
        # budget would put it out of reach of the only pages that need it.
        assert fit_to_budget(1.0, 4047, 4998) < 1.0

    def test_a_degenerate_page_does_not_divide_by_zero(self) -> None:
        assert fit_to_budget(2.0, 0, 0) == 2.0

    async def test_the_rendered_page_actually_fits(self) -> None:
        # End to end, not just the arithmetic: the pixmap is what ships.
        image = await render_page(
            _pdf(width=4047, height=4998), page_number=1, zoom=2.0, mime_type="application/pdf"
        )
        assert image is not None
        assert max(image.pixel_width, image.pixel_height) <= MAX_RENDERED_EDGE

    async def test_it_reports_the_zoom_it_APPLIED(self) -> None:
        # Reporting the requested zoom would put every derived rectangle off by
        # the reduction — the client scales boxes by this number.
        image = await render_page(
            _pdf(width=4047, height=4998), page_number=1, zoom=2.0, mime_type="application/pdf"
        )
        assert image is not None
        assert image.zoom < 2.0
        assert image.pixel_width == pytest.approx(4047 * image.zoom, abs=1)

    async def test_the_point_geometry_is_still_the_pages_own(self) -> None:
        # The budget changes the pixels, never the point space a box lives in.
        image = await render_page(
            _pdf(width=4047, height=4998), page_number=1, zoom=2.0, mime_type="application/pdf"
        )
        assert image is not None
        assert (image.width_points, image.height_points) == (4047.0, 4998.0)


class TestAZoomThatMeansNothing:
    """`zoom` is a query parameter, and pydantic accepts `nan`/`inf`/`1e400`.

    What they cost is not theoretical. A NaN matrix renders a **0 x 0 pixmap** —
    a blank page reported as a success — and an inf matrix asks MuPDF for an
    **844 TB allocation** and raises. Both were already stopped, but only because
    `max(1.0, min(zoom, MAX_ZOOM))` returns the incumbent on an unordered
    comparison: a Python subtlety, asserted nowhere, that reverses silently if the
    clamp and the budget are ever reordered.
    """

    @pytest.mark.parametrize("zoom", [float("nan"), float("inf"), float("-inf")])
    def test_a_non_finite_zoom_becomes_the_default(self, zoom: float) -> None:
        assert _bounded_zoom(zoom) == DEFAULT_ZOOM

    @pytest.mark.parametrize("zoom", [float("nan"), float("inf"), float("-inf"), -2.0])
    def test_fit_to_budget_substitutes_the_default_AND_still_budgets(self, zoom: float) -> None:
        """ON THE HUGE PAGE, which is the whole point.

        A first version asserted this against 612x792 — where the default 2.0 is
        under budget anyway, so returning it unbudgeted passed. Green by
        construction, on the one function whose postcondition is a size bound.
        The survey is 4047 x 4998 pt: at 2.0 that is 9996 px, 3.3x over.
        """
        applied = fit_to_budget(zoom, 4047.0, 4998.0)
        assert 4998.0 * applied <= MAX_RENDERED_EDGE + 1e-6
        assert applied > 0

    def test_an_ordinary_page_keeps_a_substituted_default_intact(self) -> None:
        # The other direction: substitution must not also clip a page that fits.
        assert fit_to_budget(float("nan"), 612.0, 792.0) == DEFAULT_ZOOM

    @pytest.mark.parametrize("zoom", [float("nan"), float("inf")])
    async def test_the_endpoint_path_renders_a_real_page_anyway(self, zoom: float) -> None:
        # The behaviour that matters: a garbage zoom yields a PAGE, not a 0x0
        # image and not a 500.
        doc = pymupdf.open()
        doc.new_page(width=612, height=792)
        rendered = await render_page(
            doc.tobytes(), page_number=1, zoom=zoom, mime_type="application/pdf"
        )
        assert rendered is not None
        assert rendered.zoom == DEFAULT_ZOOM
        assert rendered.width_points == pytest.approx(612.0)


class TestTheTwoCapsDivideTheWork:
    """`MAX_ZOOM` and `MAX_RENDERED_EDGE` are complementary, not redundant.

    The ticket asked whether one of them is now nearly dead code, since a US
    Letter page at 4x is 3168 px and the budget clips it to ~3.79. The answer is
    no, and the crossover is exactly `MAX_RENDERED_EDGE / MAX_ZOOM` = 750 points:

      * a page whose longest side is UNDER 750 pt is bound by `MAX_ZOOM`
      * anything larger is bound by `MAX_RENDERED_EDGE`

    LP-704 made the first case common rather than theoretical. A photographed pay
    stub or a passport scan is a small page — MuPDF reports an image's rect as its
    pixels x 0.75 — so the multiplier cap is what stops a caller asking for 9x on
    one, and it is the newly enabled image types that live there.
    """

    CROSSOVER = MAX_RENDERED_EDGE / MAX_ZOOM

    @pytest.mark.parametrize(
        ("width", "height"),
        [(200.0, 300.0), (96.0, 128.0), (400.0, 700.0)],
    )
    def test_a_small_page_is_bound_by_the_multiplier(self, width: float, height: float) -> None:
        assert max(width, height) < self.CROSSOVER
        assert fit_to_budget(_bounded_zoom(9.0), width, height) == MAX_ZOOM

    @pytest.mark.parametrize(
        ("width", "height"),
        [(612.0, 792.0), (595.0, 842.0), (4047.0, 4998.0)],
    )
    def test_a_page_letter_size_or_larger_is_bound_by_the_budget(
        self, width: float, height: float
    ) -> None:
        assert max(width, height) > self.CROSSOVER
        applied = fit_to_budget(_bounded_zoom(9.0), width, height)
        assert applied < MAX_ZOOM
        assert max(width, height) * applied == pytest.approx(MAX_RENDERED_EDGE)


def test_every_uploadable_type_can_be_rendered() -> None:
    """`RENDERABLE_TYPES` must cover `ALLOWED_CONTENT_TYPES`, and nothing enforced it.

    THIS DRIFT IS THE BUG LP-704 FIXED. Uploads gained image/jpeg and image/png in
    LP-36; the renderer was never told, and refused everything that was not a PDF.
    A photographed pay stub uploaded successfully and then showed the reviewer's
    no-page state for ever — a missing capability wearing a loading problem's
    clothes, and it went unnoticed until a person reported it.

    Adding image/tiff or image/heic to uploads — a phone-photo format, and a
    plausible next step — would reproduce it exactly. This is the assertion that
    turns that into a failing test instead of a support conversation.
    """
    from app.services.documents import ALLOWED_CONTENT_TYPES
    from app.services.page_render import RENDERABLE_TYPES

    unrenderable = sorted(ALLOWED_CONTENT_TYPES - RENDERABLE_TYPES.keys())
    assert not unrenderable, (
        "these types can be UPLOADED but not previewed, so a document of one shows "
        f"the no-page state permanently: {unrenderable}"
    )


class TestAPhotographDoesNotGrow:
    """A preview must not ship more bytes than the file it is previewing.

    The whole point of LP-704's budget is that a page stopped costing 69 MB. But
    the same change routed photographs through a PNG encoder, and PNG is the wrong
    container for sensor noise: measured on 2000x1500 of real noise, a 4.26 MB
    source JPEG came back as a **4.72 MB PNG** and as a **1.82 MB JPEG**. A
    photographed pay stub — the exact case this ticket enabled — was made slower to
    display than the original it replaced.
    """

    async def test_a_photograph_comes_back_smaller_than_it_went_in(self) -> None:
        import os

        width, height = 1200, 900
        # Real noise, not a flat fill: a flat image compresses to nothing in any
        # format and would make this pass whatever the encoder did.
        pixmap = pymupdf.Pixmap(pymupdf.csRGB, width, height, os.urandom(width * height * 3), False)
        source = pixmap.tobytes("jpg", jpg_quality=85)

        rendered = await render_page(source, page_number=1, mime_type="image/jpeg")
        assert rendered is not None

        # NOT UPSCALED. This is the deterministic half: an image has a fixed number
        # of pixels, and the default zoom of 2.0 rendered it at 1.5x its own
        # resolution — inventing half the pixels it then spent bytes encoding.
        assert rendered.width_points * rendered.zoom == pytest.approx(width, abs=1.0)

        # AND NOT LARGER than the file it previews. `<=` with a small allowance
        # rather than `<`, because this source is pure noise — the pathological
        # case, which cannot compress at all and re-encodes to roughly its own
        # size. A real photograph has structure and comes back smaller; what must
        # never happen again is the 1.5x of the PNG-at-2.0 path.
        assert len(rendered.content) <= len(source) * 1.05, (
            f"the preview is {len(rendered.content)} bytes for a {len(source)}-byte source"
        )

    async def test_a_pdf_page_stays_lossless_png(self) -> None:
        # The other side of the choice: a PDF page is text and line art, where PNG
        # compresses better AND stays lossless. JPEG ringing lands on small type.
        rendered = await render_page(_pdf(), page_number=1, mime_type="application/pdf")
        assert rendered is not None
        assert rendered.media_type == "image/png"
