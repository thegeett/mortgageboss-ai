"use client";

import { Button } from "@/components/ui/button";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { login } from "@/lib/api/auth";
import { type LoginFormValues, loginSchema } from "@/lib/auth/schema";
import { useIsAuthenticated } from "@/lib/stores/auth-store";
import { zodResolver } from "@hookform/resolvers/zod";
import { isAxiosError } from "axios";
import { AlertCircle, Eye, EyeOff, LogIn } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";

/** Only follow internal, single-slash paths; everything else lands on /dashboard. */
function getSafeNext(raw: string | null): string {
  if (raw?.startsWith("/") && !raw.startsWith("//")) {
    return raw;
  }
  return "/dashboard";
}

/** Map any login failure to a generic, non-enumerating message. */
function getLoginErrorMessage(error: unknown): string {
  if (isAxiosError(error) && error.response?.status === 401) {
    return "Invalid email or password.";
  }
  return "Something went wrong. Please try again.";
}

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const isAuthenticated = useIsAuthenticated();
  const nextPath = getSafeNext(searchParams.get("next"));
  // When the axios layer bounces an expired session here, tell the user why
  // (LP-46) rather than dropping them on a bare login screen.
  const sessionExpired = searchParams.get("reason") === "session_expired";

  const [formError, setFormError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);

  const form = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", password: "" },
  });

  // If a session was restored (silent refresh) or login just succeeded, leave.
  useEffect(() => {
    if (isAuthenticated) {
      router.replace(nextPath);
    }
  }, [isAuthenticated, nextPath, router]);

  const onSubmit = async (values: LoginFormValues) => {
    setFormError(null);
    try {
      await login(values.email, values.password);
      router.replace(nextPath);
    } catch (error) {
      // Never log credentials or tokens.
      setFormError(getLoginErrorMessage(error));
    }
  };

  const isSubmitting = form.formState.isSubmitting;

  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-5" noValidate>
        {sessionExpired && !formError && (
          <output className="flex items-start gap-2 rounded-md border border-warning/30 bg-warning/10 px-3 py-2.5 text-sm text-warning">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>Your session expired. Please sign in again to continue.</span>
          </output>
        )}
        {formError && (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2.5 text-sm text-destructive"
          >
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{formError}</span>
          </div>
        )}

        <FormField
          control={form.control}
          name="email"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Email</FormLabel>
              <FormControl>
                <Input
                  type="email"
                  inputMode="email"
                  autoComplete="email"
                  autoFocus
                  placeholder="you@company.com"
                  disabled={isSubmitting}
                  {...field}
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />

        <FormField
          control={form.control}
          name="password"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Password</FormLabel>
              <FormControl>
                <div className="relative">
                  <Input
                    type={showPassword ? "text" : "password"}
                    autoComplete="current-password"
                    placeholder="••••••••"
                    disabled={isSubmitting}
                    className="pr-10"
                    {...field}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((shown) => !shown)}
                    disabled={isSubmitting}
                    aria-label={showPassword ? "Hide password" : "Show password"}
                    className="absolute inset-y-0 right-0 flex w-10 items-center justify-center text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-50"
                  >
                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />

        <Button type="submit" size="lg" className="w-full gap-2" disabled={isSubmitting}>
          {isSubmitting ? (
            <>
              <Spinner />
              Signing in…
            </>
          ) : (
            <>
              <LogIn className="h-4 w-4" />
              Sign in
            </>
          )}
        </Button>
      </form>
    </Form>
  );
}
