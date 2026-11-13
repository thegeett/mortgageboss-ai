"use client";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { acceptInvite, lookupInvite } from "@/lib/api/invites";
import { getErrorMessage, normalizeError } from "@/lib/errors/api-error";
import type { InviteLookup } from "@/lib/types/invites";
import { ROLE_LABEL } from "@/lib/types/users";
import { Layers } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

/**
 * Accept an invitation (LP-MB-Admin-04, mockup 09). Outside the app shell, like /login.
 *
 * THE TOKEN IS READ FROM THE URL FRAGMENT, which a browser never sends to a server, and posted in
 * request bodies only. It never enters a path or a query string, and the fragment is cleared from
 * the address bar once read, so it does not sit in the history either.
 *
 * Every way a link can fail (unknown, expired, cancelled, used) shows the same card: the page never
 * says whether an address or a link exists.
 */
type State =
  | { kind: "loading" }
  | { kind: "invalid" }
  // The server could not be reached or failed: NOT a dead link (review finding 9). The token is
  // kept in memory, since the fragment has already left the address bar, so Try again works.
  | { kind: "unreachable"; token: string }
  | { kind: "ready"; token: string; invite: InviteLookup };

function Brand() {
  return (
    <div className="flex items-center gap-2.5">
      <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
        <Layers className="h-4 w-4" />
      </span>
      <span className="text-base font-semibold tracking-tight text-foreground">
        mortgageboss<span className="text-primary">·ai</span>
      </span>
    </div>
  );
}

function Invalid() {
  return (
    <Card className="space-y-3 p-6">
      <h1 className="text-xl font-semibold">This invitation is no longer valid</h1>
      <p className="text-sm text-muted-foreground">
        Ask the person who invited you to send a new one. If you already created your account, sign
        in.
      </p>
      <Button asChild variant="outline" className="w-full">
        <Link href="/login">Go to sign in</Link>
      </Button>
    </Card>
  );
}

export default function AcceptInvitePage() {
  const router = useRouter();
  const [state, setState] = useState<State>({ kind: "loading" });
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const token = window.location.hash.replace(/^#/, "");
    if (token) {
      // Off the address bar and out of history; the token is kept in memory only.
      window.history.replaceState(null, "", window.location.pathname);
    }
    if (!token) {
      setState({ kind: "invalid" });
      return;
    }
    void check(token);
  }, []);

  async function check(token: string) {
    setState({ kind: "loading" });
    try {
      setState({ kind: "ready", token, invite: await lookupInvite(token) });
    } catch (failure) {
      // Only the server's own "no longer valid" (404) is a dead link.
      setState(
        normalizeError(failure).status === 404
          ? { kind: "invalid" }
          : { kind: "unreachable", token },
      );
    }
  }

  async function submit() {
    if (state.kind !== "ready") return;
    setError(null);
    setSubmitting(true);
    try {
      await acceptInvite({
        token: state.token,
        first_name: firstName,
        last_name: lastName,
        password,
      });
      router.replace("/dashboard");
    } catch (failure) {
      setSubmitting(false);
      if (normalizeError(failure).status === 404) {
        setState({ kind: "invalid" });
      } else {
        setError(getErrorMessage(failure));
      }
    }
  }

  return (
    <main className="flex min-h-screen items-start justify-center bg-background px-4 py-16">
      <div className="w-full max-w-md space-y-4">
        <Brand />
        {state.kind === "loading" ? (
          <p className="text-sm text-muted-foreground" aria-busy>
            Checking your invitation…
          </p>
        ) : state.kind === "invalid" ? (
          <Invalid />
        ) : state.kind === "unreachable" ? (
          <Card className="space-y-3 p-6">
            <h1 className="text-xl font-semibold">We couldn&rsquo;t check your invitation</h1>
            <p className="text-sm text-muted-foreground">
              MortgageBoss didn&rsquo;t answer. Your link has not been used; try again in a moment.
            </p>
            <Button type="button" className="w-full" onClick={() => void check(state.token)}>
              Try again
            </Button>
          </Card>
        ) : (
          <Card className="p-6">
            <form
              className="space-y-4"
              onSubmit={(event) => {
                event.preventDefault();
                void submit();
              }}
            >
              <div>
                <h1 className="text-xl font-semibold">Join {state.invite.company_name}</h1>
                <p className="text-sm text-muted-foreground">
                  {state.invite.invited_by_name ?? "Your administrator"} invited you as{" "}
                  <span className="text-foreground">
                    {state.invite.roles.map((role) => ROLE_LABEL[role]).join(", ")}
                  </span>
                  .
                </p>
              </div>
              <div className="space-y-1">
                <Label htmlFor="accept-email">Email</Label>
                <Input id="accept-email" value={state.invite.email} readOnly disabled />
                <p className="text-xs text-muted-foreground">
                  You sign in with this address. It cannot be changed here.
                </p>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <Label htmlFor="accept-first">First name</Label>
                  <Input
                    id="accept-first"
                    autoComplete="given-name"
                    value={firstName}
                    onChange={(event) => setFirstName(event.target.value)}
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="accept-last">Last name</Label>
                  <Input
                    id="accept-last"
                    autoComplete="family-name"
                    value={lastName}
                    onChange={(event) => setLastName(event.target.value)}
                  />
                </div>
              </div>
              <div className="space-y-1">
                <Label htmlFor="accept-password">Password</Label>
                <Input
                  id="accept-password"
                  type="password"
                  autoComplete="new-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                />
                <p className="text-xs text-muted-foreground">At least 8 characters.</p>
              </div>
              {error ? (
                <p role="alert" className="text-sm text-destructive">
                  {error}
                </p>
              ) : null}
              <Button
                type="submit"
                className="w-full"
                disabled={
                  submitting || firstName.trim() === "" || lastName.trim() === "" || password === ""
                }
              >
                {submitting ? "Creating your account…" : "Create account and sign in"}
              </Button>
            </form>
          </Card>
        )}
      </div>
    </main>
  );
}
