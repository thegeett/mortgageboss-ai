/**
 * Palette and light/dark theme (LP-902).
 *
 * The colours live in `app/palettes/<id>.css` (LP-901); this is the list of
 * them the app knows how to switch between, and the cookies that remember the
 * choice. `app/palettes/palettes.test.ts` fails if this list and the files on
 * disk ever disagree, so adding a palette is: write the CSS file, import it in
 * `app/layout.tsx`, add a row here.
 *
 * DEVELOPMENT ONLY. There is no product decision yet on offering a palette or a
 * dark theme to processors, so a production build neither shows the switcher
 * nor honours the cookies — the server stamps nothing and every user sees the
 * default palette in light. Staging runs a production build and behaves the same.
 */

export const PALETTES = [
  { id: "petrol", label: "Petrol" },
  { id: "blue", label: "Blue" },
] as const;

export type PaletteId = (typeof PALETTES)[number]["id"];

/** What `<html>` shows with no `data-palette` attribute. */
export const DEFAULT_PALETTE: PaletteId = "petrol";

export type ThemeMode = "light" | "dark";

/** The cookies the server reads to stamp `data-palette` and `.dark` before first paint. */
export const PALETTE_COOKIE = "ledger-palette";
export const THEME_COOKIE = "ledger-theme";

/**
 * Whether palette and theme switching exist in this build. `NODE_ENV` is
 * inlined at build time, so in production every branch behind this is dead code.
 */
export const THEME_SWITCHING = process.env.NODE_ENV !== "production";

export function isPaletteId(value: string | undefined): value is PaletteId {
  return PALETTES.some((palette) => palette.id === value);
}

/**
 * What the root layout stamps on `<html>`, from the two cookies.
 *
 * Only a non-default palette is stamped (the default is the absence of the
 * attribute), and an unknown one — a palette since deleted, a hand-edited
 * cookie — falls through to the default rather than to nothing. With switching
 * off, the cookies are not consulted at all. `enabled` is a parameter only so
 * the production branch can be tested from a development test run.
 */
export function stampedTheme(
  cookies: { palette?: string; theme?: string },
  enabled: boolean = THEME_SWITCHING,
): { palette: PaletteId | undefined; dark: boolean } {
  if (!enabled) return { palette: undefined, dark: false };
  const palette = isPaletteId(cookies.palette) ? cookies.palette : DEFAULT_PALETTE;
  return {
    palette: palette === DEFAULT_PALETTE ? undefined : palette,
    dark: cookies.theme === "dark",
  };
}
