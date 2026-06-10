"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { checkBackendHealth } from "@/lib/api/client";
import { config } from "@/lib/config";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  CheckCircle2,
  Database,
  Layers,
  Loader2,
  RefreshCw,
  Server,
  WifiOff,
  XCircle,
} from "lucide-react";
import Link from "next/link";

function DependencyRow({
  label,
  icon: Icon,
  state,
}: {
  label: string;
  icon: typeof Database;
  state: "ok" | "fail" | "unknown";
}) {
  const ok = state === "ok";
  const failed = state === "fail";
  return (
    <div className="flex items-center justify-between rounded-md border border-gray-200 bg-white px-3 py-2">
      <span className="flex items-center gap-2 text-sm font-medium text-gray-700">
        <Icon className="h-4 w-4 text-gray-400" />
        {label}
      </span>
      {ok && (
        <span className="flex items-center gap-1.5 text-sm font-medium text-success">
          <CheckCircle2 className="h-4 w-4" />
          Connected
        </span>
      )}
      {failed && (
        <span className="flex items-center gap-1.5 text-sm font-medium text-destructive">
          <XCircle className="h-4 w-4" />
          Unavailable
        </span>
      )}
      {state === "unknown" && <span className="text-sm text-gray-400">—</span>}
    </div>
  );
}

function SystemStatus() {
  const { data, isPending, isError, refetch, isFetching } = useQuery({
    queryKey: ["health"],
    queryFn: checkBackendHealth,
  });

  const healthy = data?.status === "healthy";

  return (
    <div className="space-y-3 rounded-lg bg-gray-50 p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-900">System status</h2>
        {isPending ? (
          <Badge variant="secondary" className="gap-1.5">
            <Loader2 className="h-3 w-3 animate-spin" />
            Checking
          </Badge>
        ) : isError ? (
          <Badge className="gap-1.5 border-transparent bg-destructive text-destructive-foreground">
            <WifiOff className="h-3 w-3" />
            Unreachable
          </Badge>
        ) : healthy ? (
          <Badge className="gap-1.5 border-transparent bg-success text-success-foreground">
            <CheckCircle2 className="h-3 w-3" />
            All systems go
          </Badge>
        ) : (
          <Badge className="gap-1.5 border-transparent bg-destructive text-destructive-foreground">
            <XCircle className="h-3 w-3" />
            Degraded
          </Badge>
        )}
      </div>

      {isError ? (
        <div className="space-y-3 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-3">
          <p className="text-sm text-gray-700">
            Couldn&apos;t reach the backend at{" "}
            <code className="rounded bg-gray-100 px-1 py-0.5 font-mono text-xs text-gray-700">
              {config.apiUrl}
            </code>
            . Make sure the API server is running.
          </p>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => refetch()}
            disabled={isFetching}
            className="gap-1.5"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${isFetching ? "animate-spin" : ""}`} />
            Retry
          </Button>
        </div>
      ) : (
        <div className="space-y-2">
          <DependencyRow label="API server" icon={Server} state={isPending ? "unknown" : "ok"} />
          <DependencyRow
            label="PostgreSQL"
            icon={Database}
            state={isPending ? "unknown" : data?.checks.database === "ok" ? "ok" : "fail"}
          />
          <DependencyRow
            label="Redis"
            icon={Layers}
            state={isPending ? "unknown" : data?.checks.redis === "ok" ? "ok" : "fail"}
          />
          {data && (
            <p className="pt-1 text-center text-xs text-gray-400">
              {data.service} v{data.version}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export default function HomePage() {
  return (
    <main className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-gray-50 px-4 py-16">
      {/* Ambient background accents */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,_hsl(217_91%_60%_/_0.08),_transparent_55%)]"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -top-24 left-1/2 h-72 w-72 -translate-x-1/2 rounded-full bg-primary/10 blur-3xl"
      />

      <div className="relative z-10 w-full max-w-xl">
        <Card className="border-gray-200/80 shadow-xl shadow-gray-900/5">
          <CardHeader className="items-center space-y-4 text-center">
            <div className="flex items-center gap-3">
              <span className="flex h-11 w-11 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm">
                <Layers className="h-6 w-6" />
              </span>
              <span className="text-2xl font-semibold tracking-tight text-gray-900">
                mortgageboss<span className="text-primary">·ai</span>
              </span>
            </div>
            <div className="space-y-2">
              <CardTitle className="text-3xl font-bold tracking-tight text-gray-900">
                Loan processing, organized.
              </CardTitle>
              <CardDescription className="mx-auto max-w-md text-base text-gray-500">
                An AI-powered assistant that helps mortgage loan processors manage files, documents,
                and tasks — from intake to clear-to-close.
              </CardDescription>
            </div>
          </CardHeader>

          <CardContent className="space-y-6">
            <SystemStatus />

            <div className="flex flex-col justify-center gap-3 sm:flex-row">
              <Button asChild size="lg" className="gap-2">
                <Link href="/login">
                  Sign in
                  <ArrowRight className="h-4 w-4" />
                </Link>
              </Button>
              <Button asChild size="lg" variant="outline">
                <a href={`${config.apiUrl}/docs`} target="_blank" rel="noreferrer">
                  View API docs
                </a>
              </Button>
            </div>

            <Separator />

            <p className="text-center text-xs text-gray-400">
              {config.appName} v{config.appVersion} · Phase 1 — Foundation
            </p>
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
