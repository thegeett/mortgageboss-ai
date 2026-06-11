import { LoginForm } from "@/components/auth/login-form";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Layers, Loader2 } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

export const metadata: Metadata = {
  title: "Sign in",
};

export default function LoginPage() {
  return (
    <main className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-gray-50 px-4 py-12">
      {/* Ambient background accents — consistent with the home page. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,_hsl(217_91%_60%_/_0.08),_transparent_55%)]"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -top-24 left-1/2 h-72 w-72 -translate-x-1/2 rounded-full bg-primary/10 blur-3xl"
      />

      <div className="relative z-10 w-full max-w-md animate-in fade-in slide-in-from-bottom-2 duration-500">
        <div className="mb-8 flex justify-center">
          <Link
            href="/"
            className="flex items-center gap-2.5 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          >
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm">
              <Layers className="h-5 w-5" />
            </span>
            <span className="text-xl font-semibold tracking-tight text-gray-900">
              mortgageboss<span className="text-primary">·ai</span>
            </span>
          </Link>
        </div>

        <Card className="border-gray-200/80 shadow-xl shadow-gray-900/5">
          <CardHeader className="space-y-1.5">
            <CardTitle className="text-2xl font-bold tracking-tight text-gray-900">
              Sign in
            </CardTitle>
            <CardDescription className="text-gray-500">
              Enter your credentials to access your loan files.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Suspense
              fallback={
                <div className="flex justify-center py-10">
                  <Loader2 className="h-5 w-5 animate-spin text-primary" />
                </div>
              }
            >
              <LoginForm />
            </Suspense>
          </CardContent>
        </Card>

        <p className="mt-6 text-center text-xs text-gray-400">
          Accounts are provisioned by your administrator.
        </p>
      </div>
    </main>
  );
}
