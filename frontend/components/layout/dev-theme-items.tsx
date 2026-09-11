"use client";

import {
  DropdownMenuCheckboxItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import { useTheme } from "@/hooks/use-theme";
import { PALETTES, isPaletteId } from "@/lib/theme";
import { Palette } from "lucide-react";

/**
 * The palette and dark-theme switch (LP-902), for the account menu.
 *
 * DEVELOPMENT ONLY — the menu renders this behind `THEME_SWITCHING`, and the
 * server ignores the cookies in a production build (see lib/theme.ts). It sits
 * in the account menu rather than on a page of its own because the point is to
 * judge a palette on the real screens: a loan file, the verification panel, a
 * table at density — not a swatch sheet.
 *
 * Selecting keeps the menu open (`preventDefault` on select), so a developer can
 * flip between palettes and watch the screen behind the menu change.
 */
export function DevThemeItems() {
  const { palette, mode, choosePalette, chooseMode } = useTheme();

  return (
    <>
      <DropdownMenuSeparator />
      <DropdownMenuLabel className="flex items-center gap-2 font-normal text-muted-foreground">
        <Palette className="h-3.5 w-3.5" />
        Palette
        <span className="ml-auto text-xs">Dev</span>
      </DropdownMenuLabel>
      <DropdownMenuRadioGroup
        value={palette}
        onValueChange={(value) => {
          if (isPaletteId(value)) choosePalette(value);
        }}
      >
        {PALETTES.map((option) => (
          <DropdownMenuRadioItem
            key={option.id}
            value={option.id}
            onSelect={(event) => event.preventDefault()}
          >
            {option.label}
          </DropdownMenuRadioItem>
        ))}
      </DropdownMenuRadioGroup>
      <DropdownMenuCheckboxItem
        checked={mode === "dark"}
        onCheckedChange={(checked) => chooseMode(checked ? "dark" : "light")}
        onSelect={(event) => event.preventDefault()}
      >
        Dark theme
      </DropdownMenuCheckboxItem>
    </>
  );
}
