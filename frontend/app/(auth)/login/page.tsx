import { LedgerFigure } from "@/components/auth/ledger-figure";
import { LoginForm } from "@/components/auth/login-form";
import { Layers, Loader2 } from "lucide-react";
import type { Metadata } from "next";
import { Suspense } from "react";

export const metadata: Metadata = {
  title: "Sign in",
};

/**
 * Where the day starts (LP-UI-012).
 *
 * Split layout: the ledger motif and the thesis on the left, the form on the
 * right. The left panel is the one piece of persuasion in the product, and it
 * is stated once and quietly — a figure and a sentence, no gradient, no glow.
 *
 * Below `lg` the left panel is gone entirely rather than stacked above the
 * form. Someone signing in on a narrow screen wants the form, not the argument
 * for the product they have already bought.
 */
export default function LoginPage() {
  return (
    <main className="flex min-h-screen">
      {/* The argument. Hidden below lg — see above. */}
      <section className="hidden flex-1 flex-col justify-between border-r border-border bg-muted p-10 lg:flex">
        <div className="flex items-center gap-2.5">
          <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <Layers className="h-4 w-4" />
          </span>
          <span className="text-base font-semibold tracking-tight text-foreground">
            mortgageboss<span className="text-primary">·ai</span>
          </span>
        </div>

        <div className="flex justify-center py-10">
          <LedgerFigure />
        </div>

        <div className="max-w-md">
          {/* The one upright-serif line in the app: this is the product speaking
              about itself, and the serif marks it as a different register from
              the interface around it. */}
          <p className="font-serif text-xl leading-relaxed text-foreground">
            A loan file is two columns that have to agree. Everything here exists to show you where
            they don&apos;t.
          </p>
          <p className="mt-3 font-mono text-label uppercase text-muted-foreground">
            The reconciliation principle
          </p>
        </div>
      </section>

      {/* The form. */}
      <section className="flex w-full flex-col justify-center bg-background px-6 py-12 lg:w-[26rem] lg:shrink-0 lg:px-10">
        <div className="mx-auto w-full max-w-sm">
          {/* The wordmark repeats here only where the left panel is gone. */}
          <div className="mb-8 flex items-center gap-2.5 lg:hidden">
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
              <Layers className="h-4 w-4" />
            </span>
            <span className="text-base font-semibold tracking-tight text-foreground">
              mortgageboss<span className="text-primary">·ai</span>
            </span>
          </div>

          <h1 className="text-xl font-semibold tracking-tight text-foreground">Sign in</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Enter your credentials to access your loan files.
          </p>

          <div className="mt-6">
            <Suspense
              fallback={
                <div className="flex justify-center py-10">
                  <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                </div>
              }
            >
              <LoginForm />
            </Suspense>
          </div>

          <p className="mt-6 text-xs text-muted-foreground">
            Accounts are provisioned by your administrator.
          </p>
        </div>
      </section>
    </main>
  );
}
