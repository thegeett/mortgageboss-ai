"use client";

import {
  DEFAULT_PALETTE,
  PALETTE_COOKIE,
  type PaletteId,
  THEME_COOKIE,
  type ThemeMode,
  isPaletteId,
} from "@/lib/theme";
import { useCallback, useEffect, useState } from "react";

/**
 * Palette and light/dark switching (LP-902), on the pattern of ⌘B (LP-UI-008)
 * and row density (LP-UI-010).
 *
 * `data-palette` and the `dark` class on `<html>` are the single source of
 * truth: the palettes hang every colour off them (app/palettes/*.css), and the
 * server stamps both from cookies so the first paint is already in the right
 * colours. The cookies are only that state's persistence; the React values are
 * only its mirror, for rendering which option is checked.
 *
 * Unlike density there is no database half. This is a development tool, not a
 * preference a processor has, so it follows the browser rather than the person.
 */
export function useTheme() {
  const [palette, setPalette] = useState<PaletteId>(DEFAULT_PALETTE);
  const [mode, setMode] = useState<ThemeMode>("light");

  // Adopt whatever the server already stamped, without changing it.
  useEffect(() => {
    setPalette(currentPalette());
    setMode(currentMode());
  }, []);

  const choosePalette = useCallback((next: PaletteId) => {
    const root = document.documentElement;
    if (next === DEFAULT_PALETTE) root.removeAttribute("data-palette");
    else root.dataset.palette = next;
    // The default deletes the cookie rather than writing a second spelling of
    // "no cookie" — the same rule as density and ⌘B.
    writeCookie(PALETTE_COOKIE, next === DEFAULT_PALETTE ? null : next);
    setPalette(next);
  }, []);

  const chooseMode = useCallback((next: ThemeMode) => {
    document.documentElement.classList.toggle("dark", next === "dark");
    writeCookie(THEME_COOKIE, next === "dark" ? "dark" : null);
    setMode(next);
  }, []);

  return { palette, mode, choosePalette, chooseMode };
}

/** What is on screen right now, read from the attribute that decides it. */
function currentPalette(): PaletteId {
  const stamped = document.documentElement.dataset.palette;
  return isPaletteId(stamped) ? stamped : DEFAULT_PALETTE;
}

function currentMode(): ThemeMode {
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

/** A year, `SameSite=Lax`; `null` deletes. Not httpOnly: this half writes it. */
function writeCookie(name: string, value: string | null) {
  document.cookie =
    value === null
      ? `${name}=;path=/;max-age=0;samesite=lax`
      : `${name}=${value};path=/;max-age=31536000;samesite=lax`;
}
