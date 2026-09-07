"use client";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Spinner } from "@/components/ui/spinner";
import { useDensity } from "@/hooks/use-density";
import { logout } from "@/lib/api/auth";
import { DENSITY_LABEL, ROW_DENSITIES } from "@/lib/api/preferences";
import type { User } from "@/lib/auth/types";
import { Check, ChevronDown, LogOut, Rows3, Settings, UserRound } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

/** First-name + last-name initials, e.g. "Pat Processor" → "PP". */
function initialsOf(user: User): string {
  const first = user.first_name.charAt(0);
  const last = user.last_name.charAt(0);
  return `${first}${last}`.toUpperCase() || user.email.charAt(0).toUpperCase();
}

/**
 * The top-right account menu (LP-27). Shows the user's initials + name and a
 * shadcn dropdown whose actions include Log out (the LP-25 flow: clear the
 * in-memory token, hit the backend to clear the refresh cookie, go to /login).
 * Profile/Settings are disabled placeholders for now.
 */
export function UserMenu({ user }: { user: User }) {
  const router = useRouter();
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const { density, choose } = useDensity();

  const handleLogout = async () => {
    setIsLoggingOut(true);
    try {
      await logout();
      router.replace("/login");
    } finally {
      setIsLoggingOut(false);
    }
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="flex items-center gap-2 rounded-md py-1 pl-1 pr-2 text-sm transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
          {initialsOf(user)}
        </span>
        <span className="hidden text-sm font-medium text-foreground-2 sm:block">
          {user.first_name} {user.last_name}
        </span>
        <ChevronDown className="hidden h-4 w-4 text-muted-foreground sm:block" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel className="font-normal">
          <p className="text-sm font-medium text-foreground">
            {user.first_name} {user.last_name}
          </p>
          <p className="truncate text-xs font-normal text-muted-foreground">{user.email}</p>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem disabled>
          <UserRound className="mr-2 h-4 w-4" />
          Profile
          <span className="ml-auto text-xs text-muted-foreground">Soon</span>
        </DropdownMenuItem>
        <DropdownMenuItem disabled>
          <Settings className="mr-2 h-4 w-4" />
          Settings
          <span className="ml-auto text-xs text-muted-foreground">Soon</span>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        {/* Density is a per-person ergonomic preference, so it belongs with the
            person — not in a view's toolbar, where it would read as view state
            and imply it only applies here. */}
        <DropdownMenuLabel className="flex items-center gap-2 font-normal text-muted-foreground">
          <Rows3 className="h-3.5 w-3.5" />
          Row density
        </DropdownMenuLabel>
        {ROW_DENSITIES.map((option) => (
          <DropdownMenuItem
            key={option}
            onSelect={() => choose(option)}
            aria-current={option === density ? "true" : undefined}
          >
            <span className="mr-2 flex h-3.5 w-3.5 items-center justify-center">
              {option === density ? <Check className="h-3.5 w-3.5 text-primary" /> : null}
            </span>
            {DENSITY_LABEL[option]}
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={(event) => {
            // Keep the menu's selection from racing the async navigation.
            event.preventDefault();
            void handleLogout();
          }}
          disabled={isLoggingOut}
          className="text-destructive focus:text-destructive"
        >
          {isLoggingOut ? (
            <Spinner className="mr-2 h-4 w-4" />
          ) : (
            <LogOut className="mr-2 h-4 w-4" />
          )}
          {isLoggingOut ? "Signing out…" : "Log out"}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
