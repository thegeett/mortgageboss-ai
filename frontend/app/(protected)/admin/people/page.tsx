"use client";

import { CopyLinkCard, InvitationsPanel } from "@/components/admin/invitations-panel";
import { InviteDialog } from "@/components/admin/invite-dialog";
import { PeopleTable } from "@/components/admin/people-table";
import { PersonSheet } from "@/components/admin/person-sheet";
import { Button } from "@/components/ui/button";
import { useInvites } from "@/lib/api/invites";
import { usePeople } from "@/lib/api/users";
import { getErrorMessage } from "@/lib/errors/api-error";
import { useAuthStore } from "@/lib/stores/auth-store";
import type { InviteIssued } from "@/lib/types/invites";
import { cn } from "@/lib/utils";
import { Plus } from "lucide-react";
import { useState } from "react";

/**
 * People (LP-MB-Admin-03, mockup 03) and Invitations (LP-MB-Admin-04, mockup 08). The admin layout
 * already requires `users.manage`, the key every route behind this page checks.
 */
type Tab = "people" | "invitations";

export default function PeoplePage() {
  const people = usePeople();
  const invites = useInvites();
  const currentUserId = useAuthStore((state) => state.user?.id);
  const [tab, setTab] = useState<Tab>("people");
  const [openId, setOpenId] = useState<string | null>(null);
  const [inviting, setInviting] = useState(false);
  // The last link the server handed back (no mail transport). Shown once; dismissing drops it.
  const [issued, setIssued] = useState<{ value: InviteIssued; verb: "created" | "resent" } | null>(
    null,
  );
  // The open person is read from the list, so a save in the sheet shows in both at once.
  const open = people.data?.find((person) => person.id === openId) ?? null;
  const activeCount = people.data?.filter((person) => person.is_active).length;

  function onIssued(value: InviteIssued, verb: "created" | "resent") {
    setIssued(value.accept_url ? { value, verb } : null);
    setTab("invitations");
  }

  const tabButton = (id: Tab, label: string, count: number | undefined) => (
    <button
      type="button"
      role="tab"
      aria-selected={tab === id}
      onClick={() => setTab(id)}
      className={cn(
        "-mb-px border-b-2 px-1 pb-2",
        tab === id ? "border-primary text-primary" : "border-transparent text-foreground",
      )}
    >
      {label} {count !== undefined ? <span className="text-muted-foreground">{count}</span> : null}
    </button>
  );

  return (
    <section aria-labelledby="people-heading" className="space-y-4">
      <header className="space-y-1">
        <h2 id="people-heading" className="text-label uppercase text-muted-foreground">
          People
        </h2>
        <p className="max-w-prose text-sm text-muted-foreground">
          Everyone who can sign in to your company, and what each of them can do.
        </p>
      </header>

      <div className="flex items-end justify-between gap-3 border-b border-border">
        <div className="flex gap-6 text-sm" role="tablist">
          {tabButton("people", "People", activeCount)}
          {tabButton("invitations", "Invitations", invites.data?.length)}
        </div>
        <Button
          type="button"
          size="sm"
          className="mb-1.5 gap-1.5"
          onClick={() => setInviting(true)}
        >
          <Plus className="h-3.5 w-3.5" />
          Invite person
        </Button>
      </div>

      {issued ? (
        <CopyLinkCard
          // Keyed by the link, so a new link starts as "Copy link", never as "Copied" (finding 10).
          key={issued.value.accept_url ?? ""}
          issued={issued.value}
          verb={issued.verb}
          onDismiss={() => setIssued(null)}
        />
      ) : null}

      {tab === "people" ? (
        people.isPending ? (
          <p className="text-sm text-muted-foreground" aria-busy>
            Loading…
          </p>
        ) : people.isError ? (
          <p className="text-sm text-muted-foreground" role="alert">
            {getErrorMessage(people.error)}
          </p>
        ) : (
          <PeopleTable
            people={people.data}
            currentUserId={currentUserId}
            onOpen={(person) => setOpenId(person.id)}
          />
        )
      ) : invites.isPending ? (
        <p className="text-sm text-muted-foreground" aria-busy>
          Loading…
        </p>
      ) : invites.isError ? (
        <p className="text-sm text-muted-foreground" role="alert">
          {getErrorMessage(invites.error)}
        </p>
      ) : (
        <InvitationsPanel invites={invites.data} onIssued={onIssued} />
      )}

      <PersonSheet person={open} currentUserId={currentUserId} onClose={() => setOpenId(null)} />
      <InviteDialog
        open={inviting}
        onOpenChange={setInviting}
        onIssued={(value) => onIssued(value, "created")}
      />
    </section>
  );
}
