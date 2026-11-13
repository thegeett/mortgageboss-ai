"use client";

import { PeopleTable } from "@/components/admin/people-table";
import { PersonSheet } from "@/components/admin/person-sheet";
import { usePeople } from "@/lib/api/users";
import { getErrorMessage } from "@/lib/errors/api-error";
import { useAuthStore } from "@/lib/stores/auth-store";
import { useState } from "react";

/**
 * People (LP-MB-Admin-03, mockup 03). The admin layout already requires `users.manage`, the key
 * every route behind this page checks. A row opens the person's sheet.
 */
export default function PeoplePage() {
  const { data, isPending, isError, error } = usePeople();
  const currentUserId = useAuthStore((state) => state.user?.id);
  const [openId, setOpenId] = useState<string | null>(null);
  // The open person is read from the list, so a save in the sheet shows in both at once.
  const open = data?.find((person) => person.id === openId) ?? null;

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
      {isPending ? (
        <p className="text-sm text-muted-foreground" aria-busy>
          Loading…
        </p>
      ) : isError ? (
        <p className="text-sm text-muted-foreground" role="alert">
          {getErrorMessage(error)}
        </p>
      ) : (
        <PeopleTable
          people={data}
          currentUserId={currentUserId}
          onOpen={(person) => setOpenId(person.id)}
        />
      )}
      <PersonSheet person={open} currentUserId={currentUserId} onClose={() => setOpenId(null)} />
    </section>
  );
}
