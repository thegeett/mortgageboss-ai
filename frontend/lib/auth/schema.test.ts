import { loginSchema } from "@/lib/auth/schema";
import { describe, expect, it } from "vitest";

describe("loginSchema", () => {
  it("accepts a valid email and non-empty password", () => {
    const result = loginSchema.safeParse({
      email: "processor@acme.com",
      password: "hunter2hunter2", // pragma: allowlist secret
    });
    expect(result.success).toBe(true);
  });

  it("rejects an invalid email", () => {
    const result = loginSchema.safeParse({ email: "not-an-email", password: "secret123" });
    expect(result.success).toBe(false);
  });

  it("rejects an empty email", () => {
    const result = loginSchema.safeParse({ email: "", password: "secret123" });
    expect(result.success).toBe(false);
  });

  it("rejects an empty password", () => {
    const result = loginSchema.safeParse({ email: "processor@acme.com", password: "" });
    expect(result.success).toBe(false);
  });
});
