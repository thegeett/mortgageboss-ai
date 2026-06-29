"use client";

import { useAuthStore } from "@/lib/stores/auth-store";
import { ShieldCheck, SlidersHorizontal } from "lucide-react";
import Link from "next/link";

/**
 * Administration placeholder (LP-27). The nav item is role-gated to admins, but
 * frontend gating is UX only, so this page also reflects the user's role rather
 * than assuming it. Real admin screens (user management) are deferred per LP-26;
 * the backend will be the actual authorization boundary when they land.
 */
export default function AdminPage() {
  const role = useAuthStore((state) => state.user?.role);
  const isAdmin = role === "admin";

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold tracking-tight text-gray-900">Administration</h2>
        <p className="mt-1 text-gray-500">Manage your company&apos;s users and configuration.</p>
      </div>

      <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-gray-300 bg-white px-6 py-16 text-center">
        <span className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 text-primary">
          <ShieldCheck className="h-6 w-6" />
        </span>
        {isAdmin ? (
          <>
            <h3 className="mt-4 text-sm font-semibold text-gray-900">User management is coming</h3>
            <p className="mt-1 max-w-sm text-sm text-gray-500">
              Inviting and managing processors arrives in a later phase. Accounts are seed/admin
              provisioned for now.
            </p>
            <Link
              href="/admin/lenders"
              className="mt-5 inline-flex items-center gap-2 rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-sm font-medium text-primary hover:bg-primary/10"
            >
              <SlidersHorizontal className="h-4 w-4" />
              Lender overlays
            </Link>
          </>
        ) : (
          <>
            <h3 className="mt-4 text-sm font-semibold text-gray-900">Restricted</h3>
            <p className="mt-1 max-w-sm text-sm text-gray-500">
              Administration is available to admins only.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
