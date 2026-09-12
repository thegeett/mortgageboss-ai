import { afterEach, describe, expect, it, vi } from "vitest";
import { copyMessage } from "./copy-rich";

/**
 * LP-844 — formatting survives the copy, because the copy is how the message is sent.
 */
const BODY = "Hello,\n\n- Bank statements\n- Pay stubs";

afterEach(() => {
  vi.unstubAllGlobals();
});

function stubClipboard(opts: { rich: boolean; throws?: boolean }) {
  const write = vi.fn(async (_items: unknown[]) => {
    if (opts.throws) throw new Error("denied");
  });
  const writeText = vi.fn(async () => {});
  vi.stubGlobal("navigator", { clipboard: opts.rich ? { write, writeText } : { writeText } });
  if (opts.rich) {
    vi.stubGlobal(
      "ClipboardItem",
      class {
        constructor(public readonly items: Record<string, Blob>) {}
      },
    );
  } else {
    vi.stubGlobal("ClipboardItem", undefined);
  }
  return { write, writeText };
}

describe("copyMessage", () => {
  it("writes BOTH flavours, so a mail client keeps the bullets and a textarea keeps the text", async () => {
    const { write, writeText } = stubClipboard({ rich: true });

    expect(await copyMessage(BODY)).toBe("rich");

    const item = write.mock.calls[0]?.[0]?.[0] as unknown as { items: Record<string, Blob> };
    expect(Object.keys(item.items).sort()).toEqual(["text/html", "text/plain"]);
    // The point of the whole ticket: the html flavour is not the text flavour.
    expect(await item.items["text/html"]?.text()).toContain("<li>Bank statements</li>");
    expect(await item.items["text/plain"]?.text()).toBe(BODY);
    // And it did NOT also fall back, which would leave the plain flavour last-writer-wins.
    expect(writeText).not.toHaveBeenCalled();
  });

  it("still copies when the browser has no ClipboardItem", async () => {
    const { writeText } = stubClipboard({ rich: false });

    expect(await copyMessage(BODY)).toBe("plain");
    expect(writeText).toHaveBeenCalledWith(BODY);
  });

  it("still copies when the rich write is refused", async () => {
    // A processor whose copy silently did nothing cannot send the message at all — plain text is
    // exactly what they had before this ticket, which makes it the right fallback rather than a
    // degraded one.
    const { writeText } = stubClipboard({ rich: true, throws: true });

    expect(await copyMessage(BODY)).toBe("plain");
    expect(writeText).toHaveBeenCalledWith(BODY);
  });
});
