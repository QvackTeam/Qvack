"""HTML rendering with Playwright and Chromium (Т-§1.2, Т-§13.6, Т-§17.6, ТЗ Фазы 4 WP24).

Chromium starts on the first render job, serves the next jobs with new pages and closes after
`chromium_idle_close_s` without jobs (Д-§4.1, `T-CM3`). One browser per service process.
`snapshots` waits for the way a param set reaches the page (BLOCKED-C-201, Т-§13.6).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib

import pymupdf
from playwright.async_api import Browser, Playwright, async_playwright

from quack_compute.contracts import (
    RenderPdfRequest,
    RenderPdfResponse,
    RenderSnapshotsRequest,
    RenderSnapshotsResponse,
)


class Renderer:
    def __init__(self, idle_close_s: int) -> None:
        self._idle_close_s = idle_close_s
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._lock = asyncio.Lock()
        self._active = 0
        self._idle_timer: asyncio.Task[None] | None = None

    @property
    def browser_open(self) -> bool:
        return self._browser is not None

    async def snapshots(self, request: RenderSnapshotsRequest) -> RenderSnapshotsResponse:
        raise NotImplementedError("BLOCKED-C-201: how a param set reaches the page")

    async def pdf(self, request: RenderPdfRequest) -> RenderPdfResponse:
        """HTML → A4 PDF and its page count (Т-§17.6: the one-page check of a cheat sheet)."""
        browser = await self._acquire()
        try:
            page = await browser.new_page()
            try:
                await page.set_content(request.html, wait_until="load")
                data = await page.pdf(format="A4", print_background=True)
            finally:
                await page.close()
        finally:
            self._release()
        document = pymupdf.open(stream=data, filetype="pdf")
        try:
            page_count = document.page_count
        finally:
            document.close()
        return RenderPdfResponse(pdf_b64=base64.b64encode(data).decode(), page_count=page_count)

    async def close(self) -> None:
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None
        async with self._lock:
            await self._shutdown()

    # --- browser lifetime ---

    async def _acquire(self) -> Browser:
        async with self._lock:
            if self._idle_timer is not None:
                self._idle_timer.cancel()
                self._idle_timer = None
            if self._browser is None:
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch()
            self._active += 1
            return self._browser

    def _release(self) -> None:
        self._active -= 1
        if self._active == 0:
            self._idle_timer = asyncio.create_task(self._close_when_idle())

    async def _close_when_idle(self) -> None:
        await asyncio.sleep(self._idle_close_s)
        async with self._lock:
            if self._active == 0:
                await self._shutdown()

    async def _shutdown(self) -> None:
        if self._browser is not None:
            with contextlib.suppress(Exception):
                await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            with contextlib.suppress(Exception):
                await self._playwright.stop()
            self._playwright = None
