// @vitest-environment jsdom
import { DropdownMenu, DropdownMenuContent } from "@/components/ui/dropdown-menu";
import { PALETTE_COOKIE, THEME_COOKIE } from "@/lib/theme";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { DevThemeItems } from "./dev-theme-items";

afterEach(() => {
  cleanup();
  const root = document.documentElement;
  root.removeAttribute("data-palette");
  root.classList.remove("dark");
  document.cookie = `${PALETTE_COOKIE}=;path=/;max-age=0`;
  document.cookie = `${THEME_COOKIE}=;path=/;max-age=0`;
});

/** Uncontrolled and open, so a select that is NOT prevented really closes it. */
function renderMenu() {
  render(
    <DropdownMenu defaultOpen>
      <DropdownMenuContent>
        <DevThemeItems />
      </DropdownMenuContent>
    </DropdownMenu>,
  );
}

describe("DevThemeItems", () => {
  it("offers every palette as a radio, with the current one checked", () => {
    renderMenu();
    expect(screen.getByRole("menuitemradio", { name: "Petrol" }).getAttribute("aria-checked")).toBe(
      "true",
    );
    expect(screen.getByRole("menuitemradio", { name: "Blue" }).getAttribute("aria-checked")).toBe(
      "false",
    );
  });

  it("recolours the page on select, and stays open to compare", () => {
    renderMenu();
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Blue" }));
    expect(document.documentElement.dataset.palette).toBe("blue");
    // Still mounted: the developer can flip straight back and watch the change.
    expect(screen.getByRole("menuitemradio", { name: "Blue" }).getAttribute("aria-checked")).toBe(
      "true",
    );
  });

  it("toggles the dark theme on <html>", () => {
    renderMenu();
    const toggle = screen.getByRole("menuitemcheckbox", { name: "Dark theme" });
    fireEvent.click(toggle);
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(toggle.getAttribute("aria-checked")).toBe("true");
    fireEvent.click(toggle);
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });
});
