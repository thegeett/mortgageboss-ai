"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { logout } from "@/lib/api/auth";
import { useAuthStore } from "@/lib/stores/auth-store";
import { Layers, LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

/**
 * Minimal authenticated landing page (LP-25). Proves the auth chain end to end:
 * it only renders for a signed-in user (the `(app)` layout guards it) and reads
 * the user from the in-memory store. The real dashboard arrives in Epic 4+.
 */
export default function DashboardPage() {
  const router = useRouter();
  const user = useAuthStore((state) => state.user);
  const [isLoggingOut, setIsLoggingOut] = useState(false);

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
    <div className="min-h-screen bg-gray-50">
      <header className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
          <span className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm">
              <Layers className="h-4 w-4" />
            </span>
            <span className="text-lg font-semibold tracking-tight text-gray-900">
              mortgageboss<span className="text-primary">·ai</span>
            </span>
          </span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="gap-2"
            onClick={handleLogout}
            disabled={isLoggingOut}
          >
            <LogOut className="h-4 w-4" />
            {isLoggingOut ? "Signing out…" : "Sign out"}
          </Button>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 py-10">
        <Card className="border-gray-200/80 shadow-sm">
          <CardHeader>
            <CardTitle className="text-2xl font-bold tracking-tight text-gray-900">
              {user ? `Welcome back, ${user.first_name}.` : "Welcome back."}
            </CardTitle>
            <CardDescription>
              You&apos;re signed in. Loan files and processing tools arrive in a later phase.
            </CardDescription>
          </CardHeader>
          {user && (
            <CardContent>
              <dl className="grid gap-px overflow-hidden rounded-lg border border-gray-200 bg-gray-200 text-sm sm:grid-cols-2">
                <div className="bg-white px-4 py-3">
                  <dt className="text-xs font-medium uppercase tracking-wide text-gray-400">
                    Name
                  </dt>
                  <dd className="mt-1 font-medium text-gray-900">
                    {user.first_name} {user.last_name}
                  </dd>
                </div>
                <div className="bg-white px-4 py-3">
                  <dt className="text-xs font-medium uppercase tracking-wide text-gray-400">
                    Email
                  </dt>
                  <dd className="mt-1 font-medium text-gray-900">{user.email}</dd>
                </div>
                <div className="bg-white px-4 py-3">
                  <dt className="text-xs font-medium uppercase tracking-wide text-gray-400">
                    Role
                  </dt>
                  <dd className="mt-1">
                    <Badge variant="secondary" className="capitalize">
                      {user.role}
                    </Badge>
                  </dd>
                </div>
                <div className="bg-white px-4 py-3">
                  <dt className="text-xs font-medium uppercase tracking-wide text-gray-400">
                    Company ID
                  </dt>
                  <dd className="mt-1 font-mono text-xs text-gray-600">{user.company_id}</dd>
                </div>
              </dl>
            </CardContent>
          )}
        </Card>
      </main>
    </div>
  );
}
