"use client";

/**
 * The borrower's upload page (LP-815) — the only page in this app with no session.
 *
 * WHY IT EXISTS. `phase4.md` §6: GLBA Safeguards 16 CFR 314.4(c)(3) requires customer information
 * to be encrypted in transit over external networks, so outbound email must not carry NPI. It
 * carries this link instead, and the borrower sends their documents here rather than attaching them
 * to a reply.
 *
 * OUTSIDE THE `(protected)` GROUP, DELIBERATELY. That layout runs `useRequireAuth`, which would
 * bounce every borrower to `/login` — the page has to be reachable by somebody who has no account
 * and never will.
 *
 * AND IT DOES NOT USE `apiClient`. That client attaches an `Authorization` header and, on a 401,
 * attempts a silent refresh and then redirects to the login screen. A borrower has no token to
 * refresh, so the one thing it would reliably do here is send them somewhere that makes no sense.
 * Plain `fetch`, and the link token in the path is the whole credential.
 *
 * IT NAMES NOBODY. The reference is the file's display id and nothing else: whoever holds this link
 * is whoever the email reached, which after a forward is more people than the borrower.
 */

import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface LinkDetail {
  reference: string;
  purpose: string | null;
  max_bytes: number;
  remaining_uses: number;
}

/** One delivered file, so the page can say what it has already taken. */
interface Delivered {
  name: string;
}

function megabytes(bytes: number): string {
  return `${Math.floor(bytes / (1024 * 1024))} MB`;
}

export default function UploadPage() {
  const { token } = useParams<{ token: string }>();
  const [detail, setDetail] = useState<LinkDetail | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "gone">("loading");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [delivered, setDelivered] = useState<Delivered[]>([]);
  const input = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/upload/${token}`);
      if (!response.ok) {
        setState("gone");
        return;
      }
      setDetail((await response.json()) as LinkDetail);
      setState("ready");
    } catch {
      // A network failure is NOT "this link is dead" — telling a borrower their link expired when
      // their wifi dropped sends them back to the processor for a new one they do not need.
      setState("ready");
      setError("We couldn’t reach the server. Check your connection and try again.");
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  async function send(file: File) {
    setBusy(true);
    setError(null);
    try {
      const body = new FormData();
      body.append("file", file);
      const response = await fetch(`${API_BASE_URL}/api/v1/upload/${token}`, {
        method: "POST",
        body,
      });
      if (response.ok) {
        setDelivered((previous) => [...previous, { name: file.name }]);
        if (input.current) input.current.value = "";
        await load();
        return;
      }
      // THE SERVER'S OWN SENTENCE. `assess` writes these for a person to act on — "ask for a copy
      // without a password" is a different next step from "send the file rather than a zip" — and a
      // borrower told only "rejected" sends the same file again.
      const payload = (await response.json().catch(() => null)) as {
        error?: { message?: string };
      } | null;
      setError(
        payload?.error?.message ??
          "That file couldn’t be accepted. Try a PDF or a photo of the document.",
      );
      if (response.status === 404) setState("gone");
    } catch {
      setError("We couldn’t reach the server. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  if (state === "loading") {
    return <Frame>Checking this link…</Frame>;
  }

  if (state === "gone") {
    return (
      <Frame>
        <h1 className="text-lg font-semibold text-foreground">This link is no longer active</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Upload links expire after a few days. Reply to the email you received and ask for a new
          one.
        </p>
      </Frame>
    );
  }

  return (
    <Frame>
      <h1 className="text-lg font-semibold text-foreground">Send your documents securely</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        {detail?.purpose ?? "Documents for your loan application"} · Reference {detail?.reference}
      </p>
      <p className="mt-4 text-sm text-foreground-2">
        Please use this page rather than email. Email is not a secure way to send documents that
        contain personal information such as account numbers or a Social Security number.
      </p>

      <div className="mt-6 flex flex-col gap-2">
        <label
          htmlFor="document-file"
          className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground"
        >
          Choose a file
        </label>
        <input
          id="document-file"
          ref={input}
          type="file"
          disabled={busy || (detail?.remaining_uses ?? 0) <= 0}
          className="text-sm"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void send(file);
          }}
        />
        <p className="text-xs text-muted-foreground">
          PDF, JPEG, PNG, TIFF or HEIC, up to {megabytes(detail?.max_bytes ?? 0)} each. You can send
          several files — {detail?.remaining_uses ?? 0} left on this link.
        </p>
      </div>

      {busy ? <p className="mt-4 text-sm text-muted-foreground">Sending…</p> : null}
      {error ? <p className="mt-4 text-sm text-danger">{error}</p> : null}

      {delivered.length > 0 ? (
        <div className="mt-6 border-t border-border pt-4">
          <h2 className="text-sm font-medium text-foreground">Received</h2>
          <ul className="mt-2 flex flex-col gap-1">
            {delivered.map((item) => (
              <li key={item.name} className="truncate text-sm text-muted-foreground">
                {item.name}
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-muted-foreground">
            A processor will review these. You do not need to email them as well.
          </p>
        </div>
      ) : null}
    </Frame>
  );
}

function Frame({ children }: { children: React.ReactNode }) {
  return (
    <main className="mx-auto max-w-md px-6 py-16">
      <div className="rounded-lg border border-input bg-card p-6">{children}</div>
    </main>
  );
}
