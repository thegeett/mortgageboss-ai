"""Rendering one PDF page to PNG (LP-UI-030).

Server-side with PyMuPDF, which is already on the production path — and, more to
the point, the same library that will derive a field's highlight rectangle. One
renderer means one coordinate space; two would put the box a few points off, which
is worse than no box because it points confidently at the wrong words.
"""

import pymupdf
import pytest
from app.services.page_render import MAX_ZOOM, PageImage, render_page

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
        # A page at 8x is a ~50MB PNG; the cap is what stops one request doing that.
        image = await render_page(_pdf(), page_number=1, zoom=99.0)
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
