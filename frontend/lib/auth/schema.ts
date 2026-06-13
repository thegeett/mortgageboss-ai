/**
 * Login form validation schema (LP-25).
 *
 * Extracted from the form component so it can be unit-tested in isolation.
 * Validation is intentionally minimal and client-side-only — the backend is
 * the real authority on credentials. We never reveal whether an email exists.
 */
import { z } from "zod";

export const loginSchema = z.object({
  email: z.string().min(1, "Email is required").email("Enter a valid email address"),
  password: z.string().min(1, "Password is required"),
});

export type LoginFormValues = z.infer<typeof loginSchema>;
