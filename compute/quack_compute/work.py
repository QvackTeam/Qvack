"""Job bodies of the WP24 endpoints; each runs in a pool process (`TaskPool.run`).

PyMuPDF (`pdf_pages`) and OpenCV (`image_*`), Т-§1.2. Rendering lives in
`quack_compute.renderer` (one Chromium per service). Images go out as WebP with the
encoder's default quality; numbers the documents do not give are Phase 4 decision D-C-110.
"""

from __future__ import annotations

import base64

import cv2
import numpy as np
import pymupdf

from quack_compute.contracts import (
    AlignResponse,
    CleanDrawingRequest,
    ImageRequest,
    ImageResponse,
    PdfPage,
    PdfPagesRequest,
    PdfPagesResponse,
    RenderStrokesRequest,
)

# D-C-110: sheet contour search (WP22.3 п.1) — the usual Canny + polygon approximation.
BLUR_KERNEL = 5
CANNY_LOW = 75
CANNY_HIGH = 200
CONTOUR_EPSILON_SHARE = 0.02  # of the contour perimeter
MIN_SHEET_AREA_SHARE = 0.2  # of the photo: a smaller quadrilateral is not the sheet
# D-C-110: a pen line in `render-strokes`, pixels.
STROKE_THICKNESS = 2

type Image = np.ndarray


def _decode(b64: str, flags: int = cv2.IMREAD_COLOR) -> Image:
    data = np.frombuffer(base64.b64decode(b64), dtype=np.uint8)
    image = cv2.imdecode(data, flags)
    if image is None:
        raise ValueError("not an image")
    return image


def _webp(image: Image) -> str:
    ok, encoded = cv2.imencode(".webp", image)
    if not ok:
        raise ValueError("WebP encoding failed")
    return base64.b64encode(encoded.tobytes()).decode()


def pdf_pages(request: PdfPagesRequest) -> PdfPagesResponse:
    """Text and an image of every page (WP20.2); the image at PyMuPDF's default resolution."""
    document = pymupdf.open(stream=base64.b64decode(request.pdf_b64), filetype="pdf")
    try:
        pages = []
        for index in range(document.page_count):
            page = document[index]
            number = index + 1
            pixmap = page.get_pixmap()
            image = _decode(base64.b64encode(pixmap.tobytes("png")).decode())
            pages.append(
                PdfPage(page=number, text=str(page.get_text()), image_webp_b64=_webp(image))
            )
    finally:
        document.close()
    return PdfPagesResponse(pages=pages)


def _ordered(corners: Image) -> Image:
    """Corners as top-left, top-right, bottom-right, bottom-left."""
    points = corners.reshape(4, 2).astype(np.float32)
    sums = points.sum(axis=1)
    diffs = np.diff(points, axis=1).ravel()
    return np.array(
        [
            points[np.argmin(sums)],
            points[np.argmin(diffs)],
            points[np.argmax(sums)],
            points[np.argmax(diffs)],
        ],
        dtype=np.float32,
    )


def _sheet_corners(image: Image) -> Image | None:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (BLUR_KERNEL, BLUR_KERNEL), 0), CANNY_LOW, CANNY_HIGH)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = MIN_SHEET_AREA_SHARE * image.shape[0] * image.shape[1]
    for contour in sorted(contours, key=cv2.contourArea, reverse=True):
        if cv2.contourArea(contour) < min_area:
            return None
        polygon = cv2.approxPolyDP(
            contour, CONTOUR_EPSILON_SHARE * cv2.arcLength(contour, True), True
        )
        if len(polygon) == 4:
            return _ordered(polygon)
    return None


def image_align(request: ImageRequest) -> AlignResponse:
    """Straighten the sheet by its contour; no contour — the photo as is (WP22.3 п.1)."""
    image = _decode(request.image_b64)
    corners = _sheet_corners(image)
    if corners is None:
        return AlignResponse(aligned=False, image_webp_b64=_webp(image))
    tl, tr, br, bl = corners
    width = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    height = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    target = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32
    )
    matrix = cv2.getPerspectiveTransform(corners, target)
    aligned = cv2.warpPerspective(image, matrix, (width, height))
    return AlignResponse(aligned=True, image_webp_b64=_webp(aligned))


def image_clean_drawing(request: CleanDrawingRequest) -> ImageResponse:
    """The drawing without its paper (Т-§16.3 п.4): ink by Otsu's threshold stays opaque,
    the paper and everything outside the `segmenter` mask become transparent."""
    image = _decode(request.image_b64)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    if request.mask_b64 is not None:
        mask = _decode(request.mask_b64, cv2.IMREAD_GRAYSCALE)
        if mask.shape != gray.shape:
            mask = cv2.resize(mask, (gray.shape[1], gray.shape[0]))
        ink = cv2.bitwise_and(ink, mask)
    cleaned = cv2.cvtColor(image, cv2.COLOR_BGR2BGRA)
    cleaned[:, :, 3] = ink
    return ImageResponse(image_webp_b64=_webp(cleaned))


def image_render_strokes(request: RenderStrokesRequest) -> ImageResponse:
    """Pen strokes of one line as dark lines on white, `width` × `height` (WP21.3)."""
    canvas = np.full((request.height, request.width), 255, dtype=np.uint8)
    for stroke in request.strokes:
        points = np.array([[round(x), round(y)] for x, y in stroke.points], dtype=np.int32)
        if len(points) == 1:
            cv2.circle(canvas, tuple(int(v) for v in points[0]), STROKE_THICKNESS, 0, -1)
        else:
            cv2.polylines(canvas, [points], False, 0, STROKE_THICKNESS, cv2.LINE_AA)
    return ImageResponse(image_webp_b64=_webp(canvas))
