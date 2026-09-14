// @vitest-environment jsdom
import { PALETTE_COOKIE, THEME_COOKIE } from "@/lib/theme";
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { useTheme } from "./use-theme";

function cookieValue(name: string): string | null {
  const found = document.cookie.split("; ").find((c) => c.startsWith(`${name}=`));
  return found ? (found.split("=")[1] ?? "") : null;
}

afterEach(() => {
  // No `globals`, so RTL's auto-cleanup is not registered (see use-nav-collapse.test.ts).
  cleanup();
  const root = document.documentElement;
  root.removeAttribute("data-palette");
  root.classList.remove("dark");
  document.cookie = `${PALETTE_COOKIE}=;path=/;max-age=0`;
  document.cookie = `${THEME_COOKIE}=;path=/;max-age=0`;
});

describe("useTheme", () => {
  it("adopts what the server stamped without changing it", () => {
    document.documentElement.dataset.palette = "blue";
    document.documentElement.classList.add("dark");
    const { result } = renderHook(() => useTheme());
    expect(result.current.palette).toBe("blue");
    expect(result.current.mode).toBe("dark");
    expect(document.documentElement.dataset.palette).toBe("blue");
    expect(cookieValue(PALETTE_COOKIE)).toBeNull();
  });

  it("reads an unknown stamped palette as the default rather than trusting it", () => {
    // A cookie from a palette that has since been deleted must not leave the
    // switcher with nothing checked.
    document.documentElement.dataset.palette = "sepia";
    const { result } = renderHook(() => useTheme());
    expect(result.current.palette).toBe("petrol");
  });

  it("stamps a palette and remembers it, and the default DELETES both", () => {
    // The server stamps only a non-default palette, so "petrol" and no-cookie
    // are the same state; writing both is two spellings of it.
    const { result } = renderHook(() => useTheme());
    act(() => result.current.choosePalette("blue"));
    expect(document.documentElement.dataset.palette).toBe("blue");
    expect(cookieValue(PALETTE_COOKIE)).toBe("blue");
    expect(result.current.palette).toBe("blue");

    act(() => result.current.choosePalette("petrol"));
    expect(document.documentElement.hasAttribute("data-palette")).toBe(false);
    expect(cookieValue(PALETTE_COOKIE)).toBeNull();
    expect(result.current.palette).toBe("petrol");
  });

  it("puts `dark` on <html> — the element the roles resolve against", () => {
    // The roles are declared on :root, so a `.dark` anywhere else would not
    // re-theme anything (globals.css header).
    const { result } = renderHook(() => useTheme());
    act(() => result.current.chooseMode("dark"));
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(cookieValue(THEME_COOKIE)).toBe("dark");

    act(() => result.current.chooseMode("light"));
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(cookieValue(THEME_COOKIE)).toBeNull();
  });

  it("changing the palette leaves the theme alone, and the reverse", () => {
    const { result } = renderHook(() => useTheme());
    act(() => result.current.chooseMode("dark"));
    act(() => result.current.choosePalette("blue"));
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    act(() => result.current.chooseMode("light"));
    expect(document.documentElement.dataset.palette).toBe("blue");
  });
});
