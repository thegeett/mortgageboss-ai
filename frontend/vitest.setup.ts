/**
 * Test-environment shims.
 *
 * jsdom implements no `ResizeObserver`, and the reviewer's pan hook uses one to
 * know whether the page currently overflows its pane (LP-UI-043). This is a gap
 * in the test environment rather than anything about the product, so it is
 * stubbed here rather than guarded in the hook — a `typeof ResizeObserver`
 * check in application code would make the feature silently do nothing, and the
 * tests would pass over a hook that never measured anything.
 *
 * The stub records its callback so a test can fire a resize deliberately.
 */
class ResizeObserverStub implements ResizeObserver {
  static observers: ResizeObserverStub[] = [];
  readonly callback: ResizeObserverCallback;

  constructor(callback: ResizeObserverCallback) {
    this.callback = callback;
    ResizeObserverStub.observers.push(this);
  }
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {
    ResizeObserverStub.observers = ResizeObserverStub.observers.filter((o) => o !== this);
  }
}

if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;
}

if (typeof Element !== "undefined" && !Element.prototype.setPointerCapture) {
  // jsdom has no pointer capture; the pan hook does not rely on it, but a
  // component under test may call it.
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
  Element.prototype.hasPointerCapture = () => false;
}
