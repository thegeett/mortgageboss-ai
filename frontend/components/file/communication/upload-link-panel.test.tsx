// @vitest-environment jsdom
/**
 * LP-815 — the link panel, and the one thing about it that is irreversible.
 *
 * THE URL IS SHOWN ONCE. The server stores a SHA-256 of the token, so a processor who navigates
 * away without copying it has lost it — there is nothing to look up. That makes two claims worth
 * pinning: the panel says so at the moment it matters, and the LIST never carries a URL, because a
 * list that did would make the warning false and the hashing pointless.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockMint = vi.fn();
const mockRevoke = vi.fn();
const mockLinks = vi.fn();

vi.mock("@/lib/api/upload-links", () => ({
  useUploadLinks: () => mockLinks(),
  useMintUploadLink: () => ({ mutate: mockMint, isPending: false }),
  useRevokeUploadLink: () => ({ mutate: mockRevoke, isPending: false }),
}));
vi.mock("@/lib/toast", () => ({ notifySuccess: vi.fn(), notifyError: vi.fn() }));

import { UploadLinkPanel } from "./upload-link-panel";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const TOMORROW = new Date(Date.now() + 24 * 3600 * 1000).toISOString();

const LIVE = {
  id: "link-1",
  expires_at: TOMORROW,
  revoked_at: null,
  recipient_email: "jane@example.com",
  uses: 0,
  max_uses: 20,
  last_used_at: null,
  is_usable: true,
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("the list", () => {
  it("never carries a url", () => {
    // If it did, the "copy it now" warning would be false and hashing the token would buy nothing.
    mockLinks.mockReturnValue({ data: [LIVE], isPending: false, isError: false });

    const { container } = render(<UploadLinkPanel fileId="f1" />, { wrapper });

    expect(container.textContent).not.toContain("/upload/");
    expect(screen.getByText(/jane@example.com/)).toBeDefined();
  });

  it("says a link is live, used up, revoked or expired — not just a date", () => {
    mockLinks.mockReturnValue({
      data: [
        { ...LIVE, id: "a", revoked_at: new Date().toISOString(), is_usable: false },
        { ...LIVE, id: "b", uses: 20, is_usable: false },
        {
          ...LIVE,
          id: "c",
          expires_at: new Date(Date.now() - 1000).toISOString(),
          is_usable: false,
        },
      ],
      isPending: false,
      isError: false,
    });

    render(<UploadLinkPanel fileId="f1" />, { wrapper });

    expect(screen.getByText(/Revoked/)).toBeDefined();
    expect(screen.getByText(/Used up/)).toBeDefined();
    expect(screen.getByText(/Expired/)).toBeDefined();
  });

  it("offers Revoke only on a link that is still live", () => {
    mockLinks.mockReturnValue({
      data: [LIVE, { ...LIVE, id: "dead", is_usable: false }],
      isPending: false,
      isError: false,
    });

    render(<UploadLinkPanel fileId="f1" />, { wrapper });

    expect(screen.getAllByRole("button", { name: "Revoke" })).toHaveLength(1);
  });

  it("says nothing has been created rather than showing an empty list", () => {
    mockLinks.mockReturnValue({ data: [], isPending: false, isError: false });
    render(<UploadLinkPanel fileId="f1" />, { wrapper });
    expect(screen.getByText(/No links have been created/)).toBeDefined();
  });
});

describe("minting", () => {
  it("shows the url and warns that it will not be shown again", () => {
    mockLinks.mockReturnValue({ data: [], isPending: false, isError: false });
    mockMint.mockImplementation((_input, options) =>
      options.onSuccess({ ...LIVE, url: "https://app.example.com/upload/tok3n" }),
    );
    render(<UploadLinkPanel fileId="f1" />, { wrapper });

    fireEvent.click(screen.getByRole("button", { name: "Create link" }));

    expect(screen.getByText("https://app.example.com/upload/tok3n")).toBeDefined();
    expect(screen.getByText(/only time the link is shown/)).toBeDefined();
  });

  it("sends null rather than an empty recipient", () => {
    // The field is optional and the server takes `null`. An empty string is not a valid address and
    // would come back a 422, which a processor reads as "creating links is broken".
    mockLinks.mockReturnValue({ data: [], isPending: false, isError: false });
    render(<UploadLinkPanel fileId="f1" />, { wrapper });

    fireEvent.click(screen.getByRole("button", { name: "Create link" }));

    expect(mockMint).toHaveBeenCalledWith({ recipient_email: null }, expect.anything());
  });

  it("passes the address a processor typed", () => {
    mockLinks.mockReturnValue({ data: [], isPending: false, isError: false });
    render(<UploadLinkPanel fileId="f1" />, { wrapper });

    fireEvent.change(screen.getByLabelText(/Who is it for/), {
      target: { value: " jane@example.com " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create link" }));

    expect(mockMint).toHaveBeenCalledWith(
      { recipient_email: "jane@example.com" },
      expect.anything(),
    );
  });
});
