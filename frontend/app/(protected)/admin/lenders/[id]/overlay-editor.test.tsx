// @vitest-environment jsdom
import type { LenderOverlayView } from "@/lib/types/overlay-admin";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const useLenderOverlay = vi.hoisted(() => vi.fn());
const useUpdateLenderOverlay = vi.hoisted(() =>
  vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
);
vi.mock("@/lib/api/overlay-admin", () => ({ useLenderOverlay, useUpdateLenderOverlay }));
vi.mock("next/navigation", () => ({ useParams: () => ({ id: "l1" }) }));

const authState = vi.hoisted(() => ({ role: "admin" as string | undefined }));
vi.mock("@/lib/stores/auth-store", () => ({
  useAuthStore: (selector: (s: unknown) => unknown) => selector({ user: { role: authState.role } }),
}));

import EditLenderOverlayPage from "./page";

afterEach(() => {
  cleanup();
  useLenderOverlay.mockReset();
  authState.role = "admin";
});

function view(overrides: Partial<LenderOverlayView> = {}): LenderOverlayView {
  return {
    id: "l1",
    name: "UWM",
    slug: "uwm",
    overrides: [],
    audit: [],
    ...(overrides as Partial<LenderOverlayView>),
  } as LenderOverlayView;
}

function loaded(v: LenderOverlayView) {
  useLenderOverlay.mockReturnValue({ data: v, isPending: false, isError: false, refetch: vi.fn() });
}

describe("Lender overlay editor (LP-UI-026)", () => {
  it("does not claim the override is in force", () => {
    // The sentence this replaces said "editing a threshold changes what
    // enforcement uses for this lender". The engine builds its overlays from
    // hardcoded dicts and never reads the column this editor writes, so that was
    // false. A screen telling an admin their change is live when it is not is the
    // worst thing this editor could do.
    loaded(view());
    render(<EditLenderOverlayPage />);
    expect(screen.getByText(/Recorded, not yet applied/)).toBeTruthy();
    expect(screen.queryByText(/changes what enforcement uses/)).toBeNull();
  });

  it("shows the agency base beside the lender's value", () => {
    loaded(
      view({
        overrides: [
          {
            rule_id: "conv.dti.back_end_max",
            rule_description: "Back-end DTI ceiling",
            op: "<=",
            unit: "%",
            base_value: "43",
            effective_value: "45",
            reason: "Investor allows 45 with reserves",
          },
        ],
      }),
    );
    render(<EditLenderOverlayPage />);
    expect(screen.getByText("Agency base")).toBeTruthy();
    expect(screen.getByText("43")).toBeTruthy();
    expect(screen.getByLabelText("Override value")).toHaveProperty("value", "45");
  });

  it("reads a change as a sentence, not a diff", () => {
    loaded(
      view({
        audit: [
          {
            at: "2026-08-30T09:00:00Z",
            actor_user_id: "u1",
            actor_name: "Avery Stone",
            reason: "Investor bulletin 2026-14",
            changes: [
              {
                field: "conv.dti.back_end_max",
                field_label: "Back-end DTI ceiling",
                from: "43",
                to: "45",
              },
            ],
          },
        ],
      }),
    );
    render(<EditLenderOverlayPage />);
    expect(screen.getByText(/Avery Stone/)).toBeTruthy();
    expect(screen.getByText(/changed “Back-end DTI ceiling” from 43 to 45/)).toBeTruthy();
    expect(screen.getByText(/Investor bulletin 2026-14/)).toBeTruthy();
    // Not the diff dump it replaced.
    expect(screen.queryByText(/conv\.dti\.back_end_max: 43 → 45/)).toBeNull();
  });

  it("distinguishes setting, moving and removing an override", () => {
    loaded(
      view({
        audit: [
          {
            at: "2026-08-30T09:00:00Z",
            actor_user_id: null,
            actor_name: null,
            reason: "cleanup",
            changes: [
              // Descriptions are full sentences in the real catalog; the trailing stop
              // is trimmed so the name does not end the clause early.
              { field: "a", field_label: "Rule A is short.", from: null, to: "10" },
              { field: "b", field_label: "Rule B", from: "20", to: null },
            ],
          },
        ],
      }),
    );
    render(<EditLenderOverlayPage />);
    expect(screen.getByText(/set “Rule A is short” to 10/)).toBeTruthy();
    expect(screen.getByText(/removed the override on “Rule B”, which was 20/)).toBeTruthy();
  });

  it("falls back to the rule id for a rule the catalog no longer has", () => {
    // An audit outlives the rule it refers to. The id at least identifies what
    // moved; a placeholder like "(unknown rule)" identifies nothing.
    loaded(
      view({
        audit: [
          {
            at: "2026-08-30T09:00:00Z",
            actor_user_id: null,
            actor_name: null,
            reason: "r",
            changes: [{ field: "retired.rule", field_label: null, from: "1", to: "2" }],
          },
        ],
      }),
    );
    render(<EditLenderOverlayPage />);
    expect(screen.getByText(/changed retired\.rule from 1 to 2/)).toBeTruthy();
  });

  it("says someone rather than inventing a name", () => {
    loaded(
      view({
        audit: [
          {
            at: "2026-08-30T09:00:00Z",
            actor_user_id: null,
            actor_name: null,
            reason: "r",
            changes: [],
          },
        ],
      }),
    );
    render(<EditLenderOverlayPage />);
    expect(screen.getByText(/Someone/)).toBeTruthy();
  });
});
