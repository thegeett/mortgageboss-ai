import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { config } from "@/lib/config";
import { ArrowRight, CheckCircle2, FileText, Layers, ShieldCheck } from "lucide-react";
import Link from "next/link";

const capabilities = [
  {
    icon: FileText,
    title: "Loan files",
    description: "Organize borrower files and track every document in one place.",
  },
  {
    icon: CheckCircle2,
    title: "Tasks & checklists",
    description: "Keep processing milestones moving with structured task lists.",
  },
  {
    icon: ShieldCheck,
    title: "Document review",
    description: "Flag findings and verify documents with clear status signals.",
  },
];

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

      <div className="relative z-10 w-full max-w-2xl">
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
            <Badge
              variant="secondary"
              className="gap-1.5 rounded-full px-3 py-1 text-xs font-medium text-muted-foreground"
            >
              <span className="h-1.5 w-1.5 rounded-full bg-warning" />
              Phase 1 — Foundation in progress
            </Badge>
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

          <CardContent className="space-y-8">
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

            <div className="grid gap-6 sm:grid-cols-3">
              {capabilities.map(({ icon: Icon, title, description }) => (
                <div key={title} className="space-y-2 text-center sm:text-left">
                  <span className="inline-flex h-9 w-9 items-center justify-center rounded-md bg-primary/10 text-primary">
                    <Icon className="h-5 w-5" />
                  </span>
                  <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
                  <p className="text-sm leading-relaxed text-gray-500">{description}</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <p className="mt-6 text-center text-xs text-gray-400">
          {config.appName} v{config.appVersion} · Phase 1 — Foundation
        </p>
      </div>
    </main>
  );
}
