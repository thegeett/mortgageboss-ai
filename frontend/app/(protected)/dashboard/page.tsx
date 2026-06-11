"use client";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuthStore } from "@/lib/stores/auth-store";

/**
 * Authenticated landing page. Renders inside the app shell (LP-27), so it has no
 * chrome of its own — logout lives in the header user menu. Shows the signed-in
 * user's details from the in-memory store. The real dashboard arrives in Epic 4+.
 */
export default function DashboardPage() {
  const user = useAuthStore((state) => state.user);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold tracking-tight text-gray-900">
          {user ? `Welcome back, ${user.first_name}.` : "Welcome back."}
        </h2>
        <p className="mt-1 text-gray-500">
          You&apos;re signed in. Loan files and processing tools arrive in a later phase.
        </p>
      </div>

      {user && (
        <Card className="border-gray-200/80 shadow-sm">
          <CardHeader>
            <CardTitle className="text-base font-semibold text-gray-900">Your account</CardTitle>
            <CardDescription>The identity this session is scoped to.</CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="grid gap-px overflow-hidden rounded-lg border border-gray-200 bg-gray-200 text-sm sm:grid-cols-2">
              <div className="bg-white px-4 py-3">
                <dt className="text-xs font-medium uppercase tracking-wide text-gray-400">Name</dt>
                <dd className="mt-1 font-medium text-gray-900">
                  {user.first_name} {user.last_name}
                </dd>
              </div>
              <div className="bg-white px-4 py-3">
                <dt className="text-xs font-medium uppercase tracking-wide text-gray-400">Email</dt>
                <dd className="mt-1 font-medium text-gray-900">{user.email}</dd>
              </div>
              <div className="bg-white px-4 py-3">
                <dt className="text-xs font-medium uppercase tracking-wide text-gray-400">Role</dt>
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
        </Card>
      )}
    </div>
  );
}
