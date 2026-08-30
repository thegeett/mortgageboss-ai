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
 *  - A type scale with 13px as the workhorse, and row-height utilities. It
 *    REPLACES the stock ramp (theme level, not extend), so a size above 3xl
 *    does not exist — same discipline as the weight cap.
 */

/** hsl(var(--x)) so opacity modifiers (bg-warning/10) keep working. */
const token = (name: string) => `hsl(var(--${name}))`;
const pair = (name: string) => ({
  DEFAULT: token(name),
  foreground: token(`${name}-foreground`),
});

export default {
  darkMode: ["class"],
  // The `.dark` block lives in globals.css inside @layer base, and Tailwind
  // tree-shakes custom base CSS against the content globs. Nothing in app/,
  // components/ or lib/ yields the bare token `dark` today, so the whole dark
  // theme was being dropped from the build. Safelisting it makes the block's
  // survival independent of what any component happens to spell — including a
  // theme toggle that sets the class from a variable rather than a literal.
  safelist: ["dark"],
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    container: { center: true, padding: "2rem", screens: { "2xl": "1400px" } },
    // fontWeight sits at theme level, NOT theme.extend. `extend` MERGES with the
    // default scale, so `bold: 700` would survive and `font-bold` would still
    // resolve — which is exactly what happened the first time. Replacing the
    // scale is what makes the cap real. 700 does not exist in this system;
    // hierarchy comes from size, colour and space.
    fontWeight: {
      normal: "400",
      medium: "500",
      semibold: "600",
    },
    // fontSize sits at theme level for the SAME reason as fontWeight above, and
    // was left under `extend` on the first pass — so `text-3xl` and up still
    // resolved to Tailwind's stock ramp while xs..2xl were retuned, and the scale
    // jumped from a tracked 26px straight to an untracked 30px. Replacing the
    // scale means a size not listed here does not exist: `text-4xl` compiles to
    // nothing, which is the point, and tailwind.config.test.ts pins the set.
    fontSize: {
      // The dense scale. `sm` (13px) is the workhorse; `label` is the uppercase eyebrow.
      label: ["0.65625rem", { lineHeight: "1rem", letterSpacing: "0.09em", fontWeight: "600" }],
      xs: ["0.71875rem", { lineHeight: "1.05rem" }],
      sm: ["0.8125rem", { lineHeight: "1.2rem" }],
      base: ["0.875rem", { lineHeight: "1.3rem" }],
      // 16px, and it must not drop below it. Mobile Safari zooms the viewport
      // whenever a focused control computes under 16px and never zooms back out,
      // so every form control wears `text-field md:text-sm`. The usual guard is
      // `text-base md:text-sm`, which does NOT work here: `base` is 14px in this
      // scale. Named rather than borrowed from `lg` so the reason travels with it.
      field: ["1rem", { lineHeight: "1.25rem" }],
      lg: ["1rem", { lineHeight: "1.5rem", letterSpacing: "-0.01em" }],
      xl: ["1.25rem", { lineHeight: "1.6rem", letterSpacing: "-0.018em" }],
      "2xl": ["1.625rem", { lineHeight: "1.95rem", letterSpacing: "-0.022em" }],
      // Stock size and line-height (the 1.2 ratio the rest of the scale uses is
      // already right); what it was missing is the tracking. Six live sites — the
      // dashboard stat numbers, the marketing hero, and the four DTI/LTV headline
      // figures — so it is part of the scale, not an escape hatch above it.
      "3xl": ["1.875rem", { lineHeight: "2.25rem", letterSpacing: "-0.025em" }],
    },
    extend: {
      fontFamily: {
        // Set by next/font in app/layout.tsx — see assets/fonts.ts.
        sans: ["var(--font-plex-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-plex-mono)", "ui-monospace", "SFMono-Regular", "monospace"],
        serif: ["var(--font-plex-serif)", "Georgia", "serif"],
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
