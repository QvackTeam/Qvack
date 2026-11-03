"use client";

import { useEffect, useRef } from "react";
import { createGlyphField } from "@/components/quack/landing/glyph-field";
import { cn } from "@/lib/utils";
import { Duck } from "../duck";

const ASSEMBLE_MS = 2600;

/**
 * Утка из глифов, как на лендинге: та же сцена, но в рамке родителя, а не на весь экран.
 * Без WebGL остаётся плоская штрихованная утка.
 */
export function AuthScene({ className }: { className?: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    let field: ReturnType<typeof createGlyphField>;
    try {
      field = createGlyphField(canvas);
    } catch {
      canvas.dataset.flat = ""; // shows the flat duck below, no state needed
      return;
    }

    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    let reduced = mq.matches;
    let visible = true;
    let raf = 0;
    const pointer = { x: 0, y: 0, active: false };
    const t0 = performance.now();

    const draw = () => {
      const sec = reduced ? 1 : (performance.now() - t0) / 1000;
      const p = reduced ? 1 : Math.min(1, Math.max(0, (performance.now() - t0 - 200) / ASSEMBLE_MS));
      field.render(sec, { pointerX: pointer.x, pointerY: pointer.y, pointerActive: pointer.active, disperse: Math.pow(1 - p, 3) });
    };
    const tick = () => {
      raf = requestAnimationFrame(tick);
      draw();
    };
    const sync = () => {
      const run = visible && !document.hidden && !reduced;
      if (run && !raf) raf = requestAnimationFrame(tick);
      if (!run && raf) {
        cancelAnimationFrame(raf);
        raf = 0;
      }
    };

    const ro = new ResizeObserver(() => {
      const r = canvas.getBoundingClientRect();
      if (r.width < 1 || r.height < 1) return;
      field.resize(r.width, r.height, window.devicePixelRatio);
      if (!raf) draw();
    });
    ro.observe(canvas);
    const io = new IntersectionObserver((entries) => {
      visible = entries[entries.length - 1]?.isIntersecting ?? true;
      sync();
    });
    io.observe(canvas);

    // The pointer is read against the scene itself, not the window, so the duck follows it inside its own frame
    const onMove = (e: PointerEvent) => {
      const r = canvas.getBoundingClientRect();
      pointer.x = ((e.clientX - r.left) / r.width) * 2 - 1;
      pointer.y = 1 - ((e.clientY - r.top) / r.height) * 2;
      pointer.active = pointer.x >= -1 && pointer.x <= 1 && pointer.y >= -1 && pointer.y <= 1;
    };
    const onVis = () => sync();
    const onMotion = () => {
      reduced = mq.matches;
      sync();
      if (reduced) draw();
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    document.addEventListener("visibilitychange", onVis);
    mq.addEventListener("change", onMotion);

    const r = canvas.getBoundingClientRect();
    if (r.width >= 1 && r.height >= 1) field.resize(r.width, r.height, window.devicePixelRatio);
    draw();
    sync();

    return () => {
      if (raf) cancelAnimationFrame(raf);
      ro.disconnect();
      io.disconnect();
      window.removeEventListener("pointermove", onMove);
      document.removeEventListener("visibilitychange", onVis);
      mq.removeEventListener("change", onMotion);
      field.dispose();
    };
  }, []);

  return (
    <div aria-hidden className={cn("relative overflow-hidden", className)}>
      {/* The scene is framed for a landscape screen, so the canvas keeps that shape and the frame crops it */}
      <canvas ref={canvasRef} className="peer absolute left-1/2 top-0 block aspect-[8/5] h-full w-auto -translate-x-1/2" />
      <div className="absolute inset-0 hidden place-items-center peer-data-flat:grid">
        <Duck className="w-40 text-[#ff8a2a]" />
      </div>
    </div>
  );
}
