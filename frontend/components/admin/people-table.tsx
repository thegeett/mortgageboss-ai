"use client";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { signInLabel } from "@/lib/admin-time";
import { type Person, ROLES, ROLE_LABEL, type Role } from "@/lib/types/users";
import { cn } from "@/lib/utils";
import { Search } from "lucide-react";
import { useMemo, useState } from "react";

/**
 * The company's people (LP-MB-Admin-03, mockup 03).
 *
 * Search, the role select and "Show inactive" all filter the one list the server sent: a company's
 * people fit a page, so there is nothing to ask the server again. The tabs (People, Invitations)
 * are the page's; the Files column waits for LP-MB-Admin-05.
 */
export function PeopleTable({
  people,
  currentUserId,
  onOpen,
}: {
  people: Person[];
  currentUserId: string | undefined;
  onOpen: (person: Person) => void;
}) {
  const [query, setQuery] = useState("");
  const [role, setRole] = useState<Role | "">("");
  const [showInactive, setShowInactive] = useState(false);

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return people.filter(
      (person) =>
        (showInactive || person.is_active) &&
        (role === "" || person.roles.includes(role)) &&
        (needle === "" ||
          `${person.first_name} ${person.last_name}`.toLowerCase().includes(needle) ||
          person.email.toLowerCase().includes(needle)),
    );
  }, [people, query, role, showInactive]);

  const active = people.filter((person) => person.is_active).length;
  const inactive = people.length - active;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative w-64">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            aria-label="Search name or email"
            placeholder="Search name or email"
            className="pl-7"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <Select
          aria-label="Role"
          className="w-36"
          value={role}
          onChange={(event) => setRole(event.target.value as Role | "")}
        >
          <option value="">All roles</option>
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {ROLE_LABEL[r]}
            </option>
          ))}
        </Select>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="accent-primary"
            checked={showInactive}
            onChange={(event) => setShowInactive(event.target.checked)}
          />
          Show inactive
        </label>
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Email</TableHead>
            <TableHead>Roles</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Last sign-in</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {shown.length === 0 ? (
            <TableRow>
              <TableCell colSpan={5} className="text-sm text-muted-foreground">
                Nobody matches.
              </TableCell>
            </TableRow>
          ) : (
            shown.map((person) => (
              <TableRow
                key={person.id}
                className={cn("cursor-pointer", !person.is_active && "text-muted-foreground")}
                onClick={() => onOpen(person)}
              >
                <TableCell>
                  <button
                    type="button"
                    className="text-left font-medium hover:underline"
                    onClick={(event) => {
                      event.stopPropagation();
                      onOpen(person);
                    }}
                  >
                    {person.first_name} {person.last_name}
                  </button>
                  {person.id === currentUserId ? (
                    <span className="text-muted-foreground"> (you)</span>
                  ) : null}
                </TableCell>
                <TableCell>{person.email}</TableCell>
                <TableCell>
                  <div className="flex flex-wrap items-center gap-1">
                    {person.roles.map((r) => (
                      <Badge key={r} variant="outline">
                        {ROLE_LABEL[r]}
                      </Badge>
                    ))}
                    {person.is_owner ? (
                      <span className="text-xs text-muted-foreground">· owner</span>
                    ) : null}
                  </div>
                </TableCell>
                <TableCell>
                  <span className="flex items-center gap-1.5">
                    <span
                      aria-hidden
                      className={cn(
                        "h-1.5 w-1.5 rounded-full",
                        person.is_active ? "bg-success" : "bg-muted-foreground",
                      )}
                    />
                    {person.is_active ? "Active" : "Inactive"}
                  </span>
                </TableCell>
                <TableCell>{signInLabel(person.last_login_at)}</TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>

      <p className="text-xs text-muted-foreground">
        {active} active, {inactive} inactive.
      </p>
    </div>
  );
}
