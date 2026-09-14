import { describe, expect, it } from "vitest";
import { stampedTheme } from "./theme";

describe("stampedTheme — what the server puts on <html>", () => {
  it("stamps a non-default palette and the dark theme", () => {
    expect(stampedTheme({ palette: "blue", theme: "dark" }, true)).toEqual({
      palette: "blue",
      dark: true,
    });
  });

  it("stamps nothing for the default palette in light", () => {
    // The default is the ABSENCE of the attribute; stamping it would be a second
    // spelling of the same state for the palette CSS to agree with.
    expect(stampedTheme({ palette: "petrol", theme: "light" }, true)).toEqual({
      palette: undefined,
      dark: false,
    });
    expect(stampedTheme({}, true)).toEqual({ palette: undefined, dark: false });
  });

  it("falls through to the default for a palette it does not know", () => {
    // A palette deleted since the cookie was written, or a hand-edited cookie.
    // An unknown attribute would match no palette block and render the default
    // anyway — while the switcher showed nothing checked.
    expect(stampedTheme({ palette: "sepia" }, true).palette).toBeUndefined();
    expect(stampedTheme({ palette: '"><script>' }, true).palette).toBeUndefined();
  });

  it("ignores both cookies when switching is off — a production build", () => {
    // Palette and dark theme are development-only (LP-902). Staging runs a
    // production build: a developer's cookie must not recolour it for them and
    // make a screenshot of staging disagree with what processors see.
    expect(stampedTheme({ palette: "blue", theme: "dark" }, false)).toEqual({
      palette: undefined,
      dark: false,
    });
  });
});
