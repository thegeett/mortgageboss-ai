import { beforeEach, describe, expect, it, vi } from "vitest";

const success = vi.fn();
const error = vi.fn();
const warning = vi.fn();
const plain = vi.fn();

vi.mock("sonner", () => ({
  toast: Object.assign((...a: unknown[]) => plain(...a), {
    success: (...a: unknown[]) => success(...a),
    error: (...a: unknown[]) => error(...a),
    warning: (...a: unknown[]) => warning(...a),
  }),
}));

import {
  TOASTER_CLASSNAMES,
  notifyError,
  notifyPartial,
  notifyStarted,
  notifySuccess,
} from "./toast";

beforeEach(() => vi.clearAllMocks());

describe("notifySuccess", () => {
  it("carries the consequence as the description", () => {
    // The whole reason this wrapper exists: 17 of 26 success toasts said only
    // what had happened, which the processor already knows — they just did it.
    notifySuccess({ title: "Bonus income set", consequence: "Back-end DTI moved to 43.8%." });
    expect(success).toHaveBeenCalledWith(
      "Bonus income set",
      expect.objectContaining({ description: "Back-end DTI moved to 43.8%." }),
    );
  });

  it("offers no action when there is nothing to undo", () => {
    notifySuccess({ title: "Saved", consequence: "It is on the file." });
    expect(success.mock.calls[0]?.[1]).not.toHaveProperty("action");
  });

  it("wires the undo and gives it time to be reached", () => {
    const onUndo = vi.fn();
    notifySuccess({ title: "Finding applied", consequence: "Closed.", undo: { onUndo } });
    const options = success.mock.calls[0]?.[1] as {
      action: { label: string; onClick: () => void };
      duration: number;
    };
    expect(options.action.label).toBe("Undo");
    options.action.onClick();
    expect(onUndo).toHaveBeenCalledOnce();
    // An undo the processor cannot reach is not an undo. The default dismiss is
    // shorter than it takes to read the consequence and decide it was wrong.
    expect(options.duration).toBeGreaterThanOrEqual(8000);
  });

  it("lets the reversal be named something better than 'Undo'", () => {
    notifySuccess({
      title: "Merged",
      consequence: "One need remains.",
      undo: { label: "Split them again", onUndo: vi.fn() },
    });
    expect((success.mock.calls[0]?.[1] as { action: { label: string } }).action.label).toBe(
      "Split them again",
    );
  });
});

describe("notifyError", () => {
  it("puts the next move in the description, not the failure again", () => {
    notifyError({
      title: "ellis.pdf couldn’t be uploaded",
      whatToDo: "It’s 68 MB; the limit is 50.",
    });
    expect(error).toHaveBeenCalledWith("ellis.pdf couldn’t be uploaded", {
      description: "It’s 68 MB; the limit is 50.",
    });
  });
});

describe("the tones that are neither", () => {
  it("reports started work without claiming it succeeded", () => {
    // Nothing has changed yet, so a success tone would be a claim.
    notifyStarted({
      title: "Replacing the document",
      consequence: "The new version is processing.",
    });
    expect(plain).toHaveBeenCalled();
    expect(success).not.toHaveBeenCalled();
  });

  it("reports a partial success as a warning, not a success", () => {
    // The file was created AND the property was dropped. Calling that a success
    // is a small lie, and the dropped thing still needs the processor.
    notifyPartial({
      title: "LF-1 created, with something missing",
      consequence: "Add the property.",
    });
    expect(warning).toHaveBeenCalled();
    expect(success).not.toHaveBeenCalled();
  });
});

describe("TOASTER_CLASSNAMES", () => {
  /** Every `border-l-<colour>` in a class string. */
  const rails = (classes: string) => classes.match(/(?<![\w:-])!?border-l-(?!2\b)[a-z-]+/g) ?? [];

  it("puts NO unscoped rail colour on the base, so it cannot fight a typed one", () => {
    // The bug: Sonner applies its `default` slot IN ADDITION to the typed one, so
    // an error toast carried border-l-primary AND border-l-destructive, and
    // Tailwind's output order picked the winner. It picked primary — every error
    // drew a petrol rail. Any UNSCOPED colour here brings that back.
    const unscoped = TOASTER_CLASSNAMES.toast
      .split(/\s+/)
      .filter((cls) => !cls.includes(":")) // drop every variant-scoped utility
      .join(" ");
    expect(rails(unscoped), "an unscoped rail colour overrides every typed one").toEqual([]);
  });

  it("still gives an untyped toast a rail, scoped by data-type", () => {
    // The other direction: dropping the scoped rule entirely would leave a plain
    // toast with a 2px border in the border colour and no tone at all.
    expect(TOASTER_CLASSNAMES.toast).toMatch(/data-\[type=default\]:!?border-l-\w/);
  });

  it("has no `default` slot at all", () => {
    expect(TOASTER_CLASSNAMES).not.toHaveProperty("default");
  });

  it("gives each status its own rail, and only one", () => {
    for (const key of ["success", "error", "warning", "info"] as const) {
      expect(rails(TOASTER_CLASSNAMES[key])).toHaveLength(1);
    }
  });

  /**
   * The CSS property a utility sets, for the prefixes this map uses.
   *
   * Explicit rather than clever, because the distinction that matters is one a
   * string comparison gets wrong: `border-l-2` and `border-l-destructive` share
   * a prefix and set DIFFERENT properties (width, colour), while `text-foreground`
   * and `text-destructive` share a prefix and set the SAME one.
   */
  const property = (cls: string): string => {
    const u = cls.replace(/^!/, "");
    if (u === "border" || /^border(-[a-z])?-\d+$/.test(u)) return "border-width";
    if (/^border-[a-z]-/.test(u)) return "border-left-color";
    if (/^border-/.test(u)) return "border-color";
    if (/^text-(xs|sm|base|lg|xl|\dxl)$/.test(u)) return "font-size";
    if (/^text-/.test(u)) return "color";
    if (/^bg-/.test(u)) return "background-color";
    if (/^font-/.test(u)) return "font-weight";
    if (/^rounded/.test(u)) return "border-radius";
    if (/^shadow/.test(u)) return "box-shadow";
    return u;
  };

  it("no typed slot sets a property the base slot already sets unscoped", () => {
    // THE GENERAL FORM of the rail bug. The test above pins the one instance that
    // shipped — a rail colour — and the hazard is not about rails: Sonner applies
    // the base slot AND the typed slot to the same element, both with `!`, so any
    // shared property is decided by Tailwind's output order rather than by intent.
    // Verified by giving `error` a `!text-destructive` against the base's
    // `!text-foreground`: the rail-specific test passes, this one does not.
    const baseUnscoped = new Set(
      TOASTER_CLASSNAMES.toast
        .split(/\s+/)
        .filter((cls) => cls.length > 0 && !cls.includes(":"))
        .map(property),
    );
    for (const key of ["success", "error", "warning", "info"] as const) {
      for (const cls of TOASTER_CLASSNAMES[key].split(/\s+/).filter(Boolean)) {
        expect(
          baseUnscoped.has(property(cls)),
          `${key}'s \`${cls}\` sets ${property(cls)}, which the base slot also sets unscoped`,
        ).toBe(false);
      }
    }
  });

  it("uses tokens, never a raw colour", () => {
    const all = Object.values(TOASTER_CLASSNAMES).join(" ");
    expect(all).not.toMatch(/#[0-9a-f]{3,8}\b/i);
    expect(all).not.toMatch(/\b(red|green|amber|blue|slate|gray|grey)-\d/);
  });
});
