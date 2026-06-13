// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Skeleton, SkeletonRows, SkeletonText } from "./skeleton";
import { LoadingRegion, Spinner } from "./spinner";

afterEach(cleanup);

describe("Skeleton primitives", () => {
  it("the base skeleton is decorative (aria-hidden)", () => {
    const { container } = render(<Skeleton className="h-4 w-10" />);
    const el = container.firstElementChild as HTMLElement;
    expect(el.getAttribute("aria-hidden")).toBe("true");
    expect(el.className).toContain("animate-pulse");
  });

  it("SkeletonText renders one line per `lines`", () => {
    const { container } = render(<SkeletonText lines={4} />);
    // 4 line skeletons inside the wrapper.
    expect(container.querySelectorAll("[aria-hidden]")).toHaveLength(4);
  });

  it("SkeletonRows renders `count` rows with the given height", () => {
    const { container } = render(<SkeletonRows count={3} itemClassName="h-[58px]" />);
    const rows = container.querySelectorAll("[aria-hidden]");
    expect(rows).toHaveLength(3);
    expect((rows[0] as HTMLElement).className).toContain("h-[58px]");
  });
});

describe("Spinner / LoadingRegion", () => {
  it("Spinner renders a decorative spinning icon", () => {
    const { container } = render(<Spinner />);
    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("aria-hidden")).toBe("true");
    expect(svg?.classList.contains("animate-spin")).toBe(true);
  });

  it("LoadingRegion sets aria-busy and announces a status while loading", () => {
    const { rerender } = render(
      <LoadingRegion loading label="Loading docs">
        <div>content</div>
      </LoadingRegion>,
    );
    expect(screen.getByText("content").parentElement?.getAttribute("aria-busy")).toBe("true");
    expect(screen.getByText("Loading docs")).toBeDefined(); // sr-only status cue

    rerender(
      <LoadingRegion loading={false}>
        <div>content</div>
      </LoadingRegion>,
    );
    expect(screen.getByText("content").parentElement?.getAttribute("aria-busy")).toBe("false");
    expect(screen.queryByText("Loading docs")).toBeNull();
  });
});
