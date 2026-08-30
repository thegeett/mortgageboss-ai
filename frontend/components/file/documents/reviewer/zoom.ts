/**
 * The reviewer's zoom (LP-UI-042).
 *
 * SCALED IN CSS, not re-rendered on the server. The page arrives at 2× its point
 * size — a 612pt page is ~1224px of image in a ~736px column — so there is real
 * oversampling to spend. Zooming OUT is always sharp, and zooming in stays sharp
 * to roughly 165% before the browser starts inventing pixels.
 *
 * The alternative is asking the server for a bigger render at each step. That
 * costs a round trip per zoom, and it buys sharpness only above the range most
 * of this one covers. It is the right trade the other way round if a processor
 * ever needs to read a signature at 400%, and the endpoint already takes a
 * `zoom` parameter for that day.
 *
 * The highlight boxes need no adjustment: they are normalised 0..1 against the
 * page and positioned as percentages of the image's own box, so they scale with
 * it exactly (LP-UI-031).
 */

/** The steps, smallest first. `FIT` is the one a document opens at. */
export const ZOOM_STEPS = [0.5, 0.75, 1, 1.25, 1.5, 2] as const;

export const FIT: number = 1;

/** Above this, CSS scaling outruns the 2× render and the text softens. */
export const SHARP_TO = 1.65;

export function zoomIn(current: number): number {
  return ZOOM_STEPS.find((step) => step > current) ?? current;
}

export function zoomOut(current: number): number {
  return [...ZOOM_STEPS].reverse().find((step) => step < current) ?? current;
}

export function canZoomIn(current: number): boolean {
  return zoomIn(current) !== current;
}

export function canZoomOut(current: number): boolean {
  return zoomOut(current) !== current;
}

/** "125%" — the readout, and the accessible name of the reset control. */
export function zoomLabel(current: number): string {
  return `${Math.round(current * 100)}%`;
}

/**
 * The image's width at this zoom.
 *
 * `min(100%, 46rem)` is the unzoomed column: fit the pane, but never wider than
 * a comfortable reading measure. Multiplying THAT keeps zoom-out proportional on
 * a narrow pane, where a fixed 46rem base would make 50% wider than the pane it
 * is meant to fit inside.
 */
export function zoomWidth(current: number): string {
  return `calc(min(100%, 46rem) * ${current})`;
}
