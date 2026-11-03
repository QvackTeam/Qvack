"""Drawings of a sheet photo (ТЗ Ф4 WP22.3 step 5; Т-§22.6, Т-§16.3 п.4; D-C-151)."""

from __future__ import annotations

from quack.canvas.recognition import SheetBox
from quack.llm.media import BoxPrompt, SegmentedObject


def webp_size(data: bytes) -> tuple[int, int] | None:
    raise NotImplementedError


def pixel_box(box: SheetBox, size: tuple[int, int]) -> BoxPrompt:
    raise NotImplementedError


def drawing_mask(found: SegmentedObject | None, area: BoxPrompt, size: tuple[int, int]) -> str:
    raise NotImplementedError
