import { describe, expect, it } from "vitest";

import {
  FIT,
  SHARP_TO,
  ZOOM_STEPS,
  canZoomIn,
  canZoomOut,
  zoomIn,
  zoomLabel,
  zoomOut,
  zoomWidth,
} from "./zoom";

describe("zoom steps", () => {
  it("opens at fit, which is one of the steps", () => {
    expect(ZOOM_STEPS).toContain(FIT);
  });

  it("is ordered, so stepping is monotonic", () => {
    const sorted = [...ZOOM_STEPS].sort((a, b) => a - b);
    expect([...ZOOM_STEPS]).toEqual(sorted);
  });

  it("steps up and down through the ladder", () => {
    expect(zoomIn(1)).toBe(1.25);
    expect(zoomOut(1)).toBe(0.75);
    expect(zoomIn(0.5)).toBe(0.75);
    expect(zoomOut(2)).toBe(1.5);
  });

  it("stops at the ends rather than running off them", () => {
    // Returning the same value keeps the caller's state valid; returning
    // undefined would set the zoom to NaN and blank the page.
    expect(zoomIn(2)).toBe(2);
    expect(zoomOut(0.5)).toBe(0.5);
    expect(canZoomIn(2)).toBe(false);
    expect(canZoomOut(0.5)).toBe(false);
    expect(canZoomIn(1)).toBe(true);
    expect(canZoomOut(1)).toBe(true);
  });

  it("recovers from a value that is not on the ladder", () => {
    // A persisted or hand-edited zoom must not strand the controls.
    expect(zoomIn(1.1)).toBe(1.25);
    expect(zoomOut(1.1)).toBe(1);
  });

  it("stays within the range the 2x render can keep sharp, at fit and below", () => {
    // Above SHARP_TO the browser invents pixels. The steps go there on purpose —
    // a processor reading small print would rather have it big and soft — but
    // fit and every step below it are within the sharp range.
    expect(FIT).toBeLessThanOrEqual(SHARP_TO);
    for (const step of ZOOM_STEPS.filter((s) => s <= FIT)) {
      expect(step).toBeLessThanOrEqual(SHARP_TO);
    }
  });
});

describe("zoomLabel", () => {
  it("reads as a percentage", () => {
    expect(zoomLabel(1)).toBe("100%");
    expect(zoomLabel(0.5)).toBe("50%");
    expect(zoomLabel(1.25)).toBe("125%");
  });
});

describe("zoomWidth", () => {
  it("scales the fitted column rather than a fixed width", () => {
    // The base is `min(100%, 46rem)`: on a narrow pane a fixed 46rem base would
    // make 50% WIDER than the pane it is meant to fit inside.
    expect(zoomWidth(1)).toBe("calc(min(100%, 46rem) * 1)");
    expect(zoomWidth(0.5)).toContain("min(100%, 46rem)");
    expect(zoomWidth(2)).toContain("* 2");
  });
});
