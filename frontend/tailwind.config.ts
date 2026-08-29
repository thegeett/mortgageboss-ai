import type { Config } from "tailwindcss";
import animate from "tailwindcss-animate";

/**
 * LEDGER — Tailwind config                                          LP-UI-001
 *
 * Changes from the LP-5 config:
 *  - `danger` is DEFINED. Twenty class names across four files referenced it and
 *    it did not exist, which is why FailedRunBanner has been rendering grey.
 *    It aliases `destructive` so no call site has to change (LP-UI-002).
 *  - `foreground-2` (middle text tone) and `ai` (provenance, not status) added.
 *  - `input` is now the CONTROL border at >=3:1; `border` stays the hairline.
 *  - IBM Plex replaces the bare system stack; the variables come from next/font.
 *  - Radius drops to 5px controls / 8px containers.
 *  - A type scale with 13px as the workhorse, and row-height utilities.
 */

/** hsl(var(--x)) so opacity modifiers (bg-warning/10) keep working. */
const token = (name: string) => `hsl(var(--${name}))`;
const pair = (name: string) => ({
  DEFAULT: token(name),
  foreground: token(`${name}-foreground`),
});

export default {
  darkMode: ["class"],
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    container: { center: true, padding: "2rem", screens: { "2xl": "1400px" } },
    extend: {
      fontFamily: {
        // Set by next/font in app/layout.tsx — see assets/fonts.ts.
        sans: ["var(--font-plex-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-plex-mono)", "ui-monospace", "SFMono-Regular", "monospace"],
        serif: ["var(--font-plex-serif)", "Georgia", "serif"],
      },
      fontSize: {
        // The dense scale. `sm` (13px) is the workhorse; `label` is the uppercase eyebrow.
        label: ["0.65625rem", { lineHeight: "1rem", letterSpacing: "0.09em", fontWeight: "600" }],
        xs: ["0.71875rem", { lineHeight: "1.05rem" }],
        sm: ["0.8125rem", { lineHeight: "1.2rem" }],
        base: ["0.875rem", { lineHeight: "1.3rem" }],
        lg: ["1rem", { lineHeight: "1.5rem", letterSpacing: "-0.01em" }],
        xl: ["1.25rem", { lineHeight: "1.6rem", letterSpacing: "-0.018em" }],
        "2xl": ["1.625rem", { lineHeight: "1.95rem", letterSpacing: "-0.022em" }],
      },
      fontWeight: {
        // 700 does not exist in this system. Hierarchy comes from size, colour, space.
        normal: "400",
        medium: "500",
        semibold: "600",
      },
      colors: {
        background: token("background"),
        foreground: token("foreground"),
        "foreground-2": token("foreground-2"),
        border: token("border"),
        "border-strong": token("border-strong"),
        input: token("input"),
        ring: token("ring"),
        skeleton: token("skeleton"),
        primary: pair("primary"),
        secondary: pair("secondary"),
        muted: { DEFAULT: token("muted"), foreground: token("muted-foreground") },
        accent: pair("accent"),
        popover: pair("popover"),
        card: pair("card"),
        destructive: pair("destructive"),
        // `danger` is the SAME colour as `destructive`. Defined so the twenty
        // existing text-danger / border-danger / bg-danger usages resolve.
        danger: pair("destructive"),
        success: pair("success"),
        warning: pair("warning"),
        info: pair("info"),
        ai: pair("ai"),
      },
      borderRadius: {
        lg: "var(--radius-container)",
        md: "var(--radius)",
        sm: "calc(var(--radius) - 2px)",
      },
      height: { row: "var(--row-h)" },
      minHeight: { row: "var(--row-h)" },
      spacing: { row: "var(--row-h)", cell: "var(--row-px)" },
      width: { rail: "var(--rail-w)", nav: "var(--nav-w)", ctx: "var(--ctx-w)" },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
      },
    },
  },
  plugins: [animate],
} satisfies Config;
