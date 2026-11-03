"use client";

import { ChevronRight, Plus } from "lucide-react";
import Link from "next/link";
import type { Domain } from "@/lib/mock/types";
import { scrollToId } from "@/lib/scroll";
import { cn } from "@/lib/utils";
import { usePathname } from "next/navigation";
import { useRef } from "react";
import { useShell } from "./app-shell";
import { MenuToggle } from "./menu-toggle";
import { ProfileMenu } from "./profile-menu";
import { useT } from "@/lib/i18n/provider";

const row =
  "flex min-h-10 w-full items-center gap-2 rounded-control px-3 text-left transition-colors hover:bg-cloth-hover";

export function DomainSidebar({
  domains,
  activeId,
  onSelect,
  withMenu = true,
}: {
  domains: Domain[];
  activeId: string;
  onSelect: (id: string) => void;
  /** Кнопка полноэкранного меню в шапке; в мобильной шторке её нет (там она в верхней полосе) */
  withMenu?: boolean;
}) {
  const t = useT();
  const { graphMode, openGraph, menuOpen, openMenu, closeMenu } = useShell();
  const toggleRef = useRef<HTMLDivElement>(null);
  const pathname = usePathname();
  const onGraph = pathname === "/";

  // На телефоне вместо графа список: прокручиваем к главе
  const goHub = (hubId: string) => {
    openGraph({ kind: "hub", hubId });
    if (window.matchMedia("(max-width: 767px)").matches) {
      setTimeout(() => scrollToId(`hub-${hubId}`, 16), onGraph ? 320 : 700);
    }
  };
  const hubOn = (id: string) => onGraph && graphMode.kind === "hub" && graphMode.hubId === id;
  const sub = "pl-8 text-small hover:text-paper";
  const subOn = (on: boolean) => (on ? "bg-cloth-raised text-paper" : "text-paper-dim");

  return (
    <nav aria-label={t.shell.subjects} className="flex h-full flex-col bg-cloth-deep px-3 pt-4 pb-3">
      {/* шапка: кнопка меню слева, название антиквой капсом */}
      <div className="flex min-h-10 items-center justify-between gap-2 px-3 pb-1">
        {withMenu ? (
          <div ref={toggleRef} data-menu-anchor>
            <MenuToggle
              open={menuOpen}
              onClick={() => (menuOpen ? closeMenu() : openMenu(toggleRef.current?.querySelector("button") ?? null))}
              labelOpen={t.menu.open}
              labelClose={t.menu.close}
            />
          </div>
        ) : null}
        <p className="display-caps text-[1.375rem] text-paper">Qvack!</p>
      </div>

      <p className="caps flex items-center justify-between px-3 pt-5 pb-2 text-paper-dim">
        <span>{t.shell.subjects}</span>
        <span className="num">{domains.length}</span>
      </p>

      <ul className="flex flex-col gap-0.5 overflow-y-auto">
        {domains.map((d) => {
          const on = d.id === activeId;
          return (
            <li key={d.id}>
              <button
                type="button"
                aria-current={on ? "page" : undefined}
                aria-expanded={on}
                onClick={() => onSelect(d.id)}
                className={cn(row, on ? "bg-cloth-raised font-medium text-paper" : "text-paper-dim")}
              >
                <ChevronRight
                  aria-hidden
                  className={cn("size-3.5 shrink-0 transition-transform duration-200", on && "rotate-90")}
                />
                <span className="truncate">{d.title}</span>
              </button>
              {on && (
                <ul className="mt-0.5 mb-2 flex flex-col">
                  {d.hubs.map((h) => (
                    <li key={h.id}>
                      <button
                        type="button"
                        onClick={() => goHub(h.id)}
                        aria-current={hubOn(h.id) ? "true" : undefined}
                        className={cn(row, sub, subOn(hubOn(h.id)))}
                      >
                        <span className="num w-12 shrink-0 whitespace-nowrap">§ {h.num}</span>
                        <span className={cn("truncate", h.suggested && "italic")}>{h.title}</span>
                        {h.suggested && <span className="sr-only">{t.shell.suggestedSr}</span>}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
        <li>
          <Link
            href="/domains/new"
            className="caps mt-2 ml-3 inline-flex min-h-10 items-center gap-2 rounded-pill border border-seam px-4 text-paper-dim transition-colors hover:border-rule hover:bg-cloth-hover hover:text-paper"
          >
            <Plus aria-hidden className="size-3.5" />
            {t.shell.newSubject}
          </Link>
        </li>
      </ul>

      <ProfileMenu active={pathname.startsWith("/settings")} />
    </nav>
  );
}
