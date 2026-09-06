"""Rendering one PDF page to PNG (LP-UI-030).

Server-side with PyMuPDF, which is already on the production path — and, more to
the point, the same library that will derive a field's highlight rectangle. One
renderer means one coordinate space; two would put the box a few points off, which
is worse than no box because it points confidently at the wrong words.
"""

import pymupdf
import pytest
from app.services.page_render import (
    MAX_RENDERED_EDGE,
    MAX_ZOOM,
    PageImage,
    fit_to_budget,
    render_page,
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


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
        image = await render_page(_pdf(pages=3), page_number=1)
        assert image is not None
        assert image.page_count == 3

    async def test_returns_a_png(self) -> None:
        image = await render_page(_pdf(), page_number=1)
        assert image is not None
        assert image.png.startswith(PNG_MAGIC)

    async def test_carries_the_page_geometry_in_points(self) -> None:
        # The box space. A caller placing a highlight needs the POINT size the
        # rectangle is expressed in, not just the pixels it received.
        image = await render_page(_pdf(width=612, height=792), page_number=1)
        assert image is not None
        assert (image.width_points, image.height_points) == (612.0, 792.0)

    async def test_pixels_are_points_times_zoom(self) -> None:
        image = await render_page(_pdf(width=612, height=792), page_number=1, zoom=2.0)
        assert image is not None
        assert (image.pixel_width, image.pixel_height) == (1224, 1584)

    async def test_renders_the_page_that_was_asked_for(self) -> None:
        # Not page one every time — the reviewer opens a field's cited page.
        first = await render_page(_pdf(pages=3), page_number=1)
        third = await render_page(_pdf(pages=3), page_number=3)
        assert first is not None and third is not None
        assert first.png != third.png

    @pytest.mark.parametrize("page_number", [0, -1, 4])
    async def test_a_page_the_document_does_not_have_is_absent(self, page_number: int) -> None:
        # Measured on real data: a model-cited page is out of range on ~4% of
        # extracted fields. That is a designed no-page state, never a 500.
        assert await render_page(_pdf(pages=3), page_number=page_number) is None

    async def test_unreadable_bytes_are_absent_not_an_exception(self) -> None:
        assert await render_page(b"not a pdf at all", page_number=1) is None

    async def test_zoom_is_capped(self) -> None:
        # Caps the MULTIPLIER. What caps the RESULT is `MAX_RENDERED_EDGE`, and a
        # small page is used here so only one of the two is being measured — a US
        # Letter page at 4x is 3168px and the render budget takes it first.
        image = await render_page(_pdf(width=100, height=100), page_number=1, zoom=99.0)
        assert image is not None
        assert image.zoom == MAX_ZOOM

    async def test_zoom_has_a_floor(self) -> None:
        image = await render_page(_pdf(), page_number=1, zoom=0.0)
        assert image is not None
        assert image.zoom >= 1.0

    async def test_the_geometry_is_the_pages_own_not_the_zoomed_one(self) -> None:
        # The trap this guards: reporting pixel dimensions as points would put
        # every derived rectangle off by the zoom factor.
        a = await render_page(_pdf(width=612, height=792), page_number=1, zoom=1.0)
        b = await render_page(_pdf(width=612, height=792), page_number=1, zoom=3.0)
        assert a is not None and b is not None
        assert a.width_points == b.width_points == 612.0
        assert b.pixel_width == 3 * a.pixel_width

    def test_a_page_image_knows_its_pixel_size(self) -> None:
        image = PageImage(png=b"", width_points=100.0, height_points=50.0, zoom=2.0, page_count=1)
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
        assert image.png.startswith(PNG_MAGIC)

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
        image = await render_page(_pdf(width=4047, height=4998), page_number=1, zoom=2.0)
        assert image is not None
        assert max(image.pixel_width, image.pixel_height) <= MAX_RENDERED_EDGE

    async def test_it_reports_the_zoom_it_APPLIED(self) -> None:
        # Reporting the requested zoom would put every derived rectangle off by
        # the reduction — the client scales boxes by this number.
        image = await render_page(_pdf(width=4047, height=4998), page_number=1, zoom=2.0)
        assert image is not None
        assert image.zoom < 2.0
        assert image.pixel_width == pytest.approx(4047 * image.zoom, abs=1)

    async def test_the_point_geometry_is_still_the_pages_own(self) -> None:
        # The budget changes the pixels, never the point space a box lives in.
        image = await render_page(_pdf(width=4047, height=4998), page_number=1, zoom=2.0)
        assert image is not None
        assert (image.width_points, image.height_points) == (4047.0, 4998.0)
